# DiveFuzz-MC：多核随机测试架构与使用

DiveFuzz-MC 的端到端闭环：**生成可判定的多 hart 内存序测试 → herd7/RVWMO 求解允许结果集 → 编译为 litmus7 兼容可执行文件 → 在 DUT 上重复运行 → 解析观测直方图 → 与允许集比对 → 归档违规**。

执行后端统一为 **litmus7**（`MCProgram → .litmus → litmus7 → C → ELF`）。无第二个后端。

---

## 1. 架构概览

```
生成侧 (fuzzer/generator/core/multicore/)
  families.build_program()          选族(声明式 catalog) → 构造 MCProgram
    ├─ families.py                  FamilySpec catalog + 各族 builder (SB/LB/MP/MPTSO/CoRR/WRC/IRIW)
    ├─ regalloc.py                  RegAllocator: 按角色(addr/value/dst/scratch)分配寄存器，与族拓扑解耦
    ├─ noise.py                     NoisePool: 按级别(none/L0)提供 oracle-sound 噪声指令
    ├─ model.py                     数据模型: MCProgram / HartProgram / ModeledEvent / SharedVar / ObservedReg
    ├─ validator.validate()         静态校验: hart 数、事件宽度、噪声∈NoisePool、observed 由 Load 定义
    └─ litmus_exporter.export_litmus()   渲染为 RISCV .litmus (含 L0 噪声行)
  herd_oracle.HerdOracle            调用 herd7 解析 "States N" → allowed_outcomes.json
  litmus_backend.LitmusExecutableBackend   make compile (litmus7 生成 C → gcc 链接) → seed.elf
  generate.generate_multicore_seed  编排: 写 seed.mc.json / seed.litmus / allowed_outcomes.json / manifest.json / seed.elf
                                       herd 失败仍保留 mc.json+litmus 并抛 HERD_ORACLE_ERROR

执行侧 (fuzzer/executor/multicore/)
  runner.XiangShanMultiCoreRunner.run_bundle()
    ├─ _run_once()                  PTY 流式采集 DUT 输出, 检测 litmus "Observation" 完成标记即终止
    ├─ outcome.parse_litmus_histogram()  解析 "Histogram" 块 → 观测结果计数
    └─ oracle.classify_outcomes()   trap > 直方图 > 超时 > 无结果 的优先级判定
  archive.archive_multicore_result()  非 SUCCESS 才归档 (mc.json/litmus/elf/allowed/observed/log/oracle_report.json)

接线
  config/dut_config.py              MultiCoreConfig + MultiCoreSeedConfig + YAML 解析分支
  executor/dut_executor.py          run_single_test() 前置 multicore 分支 → run_multicore_test()
  generator/config/cli_parser.py    --multicore 系列参数
  generator/main.py                 generate+multicore 走 generate_multicore_seeds()
```

两种入口：
- **CLI（仅生成）**：`python -m generator.main --generate --multicore ...`
- **YAML（生成+运行+判定+归档）**：`python run_dut.py --config <yaml>`

---

## 2. 核心模型与原理

### 2.1 MCProgram 数据模型

- `EventKind`：`Load / Store / Fence / FenceTso / AMO / LR / SC / Dependency / Delay`（当前仅实现 Load/Store/Fence/FenceTso，其余在 validator/exporter 中以明确 `ValueError` 拒绝）。
- `SharedVar(name, init_value, width, alignment)`：跨 hart 共享内存变量。
- `ModeledEvent`：一次被建模的内存事件（addr/dst/value/width/aq/rl/pred/succ…）。
- `HartProgram`：单 hart 程序 = `prologue_noise + modeled_window + epilogue_noise + result_capture`。
- `MCProgram`：完整多核测试方案（seed_id、isa、hart_count、shared_vars、hart_programs、observed、oracle_spec、noise_profile）。

### 2.2 规范结果键（canonical outcome key）

litmus7/herd7 的输出使用 `0:x10=1` 形式。DiveFuzz-MC 采用**原始寄存器键** `h{hart}.{reg}`（如 `h0.x10`、`h1.x10`），而非逻辑别名。这样 allowed（来自 herd）与 observed（来自 litmus 直方图）使用**同一套键**，比对时无需发明别名映射。

一个规范结果 = `tuple(sorted(state.items()))`，可哈希、可 JSON 序列化。

### 2.3 测试族（声明式 catalog）

族由 `families.py` 的 `FamilySpec` 声明：每族携带自己的 hart 数、变量布局、per-hart 事件模板。寄存器由 `RegAllocator` 按角色分配（addr x6/x7、value x12/x13、dst x10/x11、scratch x20），噪声由 `NoisePool` 提供——族拓扑与寄存器/噪声选择解耦，是后续随机化的接入点。

hart 数是族的固有属性（SB 定义为 2-hart、WRC 为 3-hart、IRIW 为 4-hart），不再是全局硬编码。`--hart-count N` 是可选过滤器：只生成拓扑要求 N hart 的族；省略则各族用自己的 hart 数。

| 族 | hart | 拓扑概要 | 备注 |
|---|---|---|---|
| **SB** / **LB** | 2 | 经典 store/load buffering | 全 4 种结果（无 fence） |
| **MP** | 2 | `sd x; fence rw,rw; sd y` ‖ `ld y; ld x` | fence 禁止 `{x10=1,x11=0}` |
| **MPTSO** | 2 | 同 MP，屏障换 `fence.tso` | store-store + load-store 序 |
| **CoRR** | 2 | `sd x` ‖ `ld x; ld x`（同地址） | coherence 禁止 new→old |
| **WRC** | 3 | `sd x` → `ld x; sd y` → `ld y; ld x` | 因果链传递 |
| **IRIW** | 4 | 两写者 + 两独立读者 | 独立写的可见序一致性 |

族选择为确定性轮换：`family = test_families[(seed_id - seed_offset) % len(test_families)]`，保证覆盖度可复现。`available_families()` 返回全集；`family_hart_count(f)` 返回族的 hart 数。

### 2.4 噪声（L0 / L1）

噪声只写 scratch 寄存器 `x20`，与 modeled window 用到的所有寄存器（addr x6/x7、value x12/x13、observed x10/x11）以及 harness/ABI 保留集都不相交，故对 window 的访存与 observed 结果零影响——无论插在 prologue、窗口事件之间（interleaving）还是 epilogue 都安全。herd 只对 modeled window 求解，噪声行不在其内。validator 用 `NoisePool.is_safe` 逐行校验（助记符白名单 + 所有寄存器操作数 ∈ SCRATCH）。

- `none`：无噪声。
- `L0`：惰性指令 `nop` / `addi x20,x20,0`，prologue 插 1 条。
- `L1`：x20 上的整数 ALU（`addi`/`slli`/`srli` 带随机立即数，`add`/`sub`/`and`/`or`/`xor`/`sll`/`srl` x20,x20,x20），prologue 插 2 条 **+ 窗口每条事件后插 1 条 interleaving 噪声**。interleaving 把 load/store 在时间上拉开，是压流水线时序的核心。无内存访问、无分支、不会 trap。

> 探针发现 herd7 的 RISC-V litmus 模型不含 M 扩展（`mul` 被拒），故 L1 不含 `mul`。

### 2.5 litmus 导出格式

匹配现有 harness 样例的 RISCV 表格式：

```
RISCV SB-mc0
{
 uint64_t x=0;
 uint64_t y=0;
 0:x6=x; 0:x7=y;
 1:x6=x; 1:x7=y;
}
 P0 | P1 ;
 nop | addi x20,x20,0 ;        <- L0 噪声（noise_level=none 时无此行）
 ori x12,x0,1 | ori x12,x0,1 ;
 sd x12,0(x6) | sd x12,0(x7) ;
 ld x10,0(x7) | ld x10,0(x6) ;
exists (0:x10=0 /\ 1:x10=0)
```

`exists` 子句仅用于 litmus7 兼容性（litmus7 编译 harness 需要）；**真正的 oracle 来自 herd 的完整 `States` 块**，而非该 `exists`。

### 2.6 判定优先级

执行器分类顺序（适应模拟器打印结果后挂起的行为，如 spike）：

1. 输出含 `HIT BAD TRAP` / `ABORT` → `RUNTIME_TRAP`
2. 有可解析直方图 → `classify_outcomes`（`SUCCESS` / `MODEL_VIOLATION` / `NO_OUTCOME`）
3. 硬超时且无直方图 → `TIMEOUT`
4. 否则 → `NO_OUTCOME`

> 关键点：模拟器完成测试后可能**挂起**（不自动退出），但直方图已打印。因此"拿到直方图"优先于"超时"——只要解析到合法结果，即使进程随后被超时终止，仍按直方图判定，而非误判为 TIMEOUT。

---

## 3. DUT 可移植性（关键）

**结论先行：生成器 + herd oracle + runner + outcome/archive 这一整条 Python 流水线是 DUT 无关的。** runner 只做一件事：把 `dut_config.cmd` 中的 `$1` 替换为 ELF 路径后 shell 执行，PTY 流式采集 stdout，检测 `Observation`/`Histogram` 标记后终止并解析。**任何能跑起这个 ELF 并打印 litmus 格式输出的 DUT 都能接入。**

真正与 DUT 耦合的是**harness 胶水层**（`spike-litmus-harness/`：`startup.S` / `syscalls.c` / `linker.ld`）。它当前实现的是 **HTIF 约定**（`tohost` / `fromhost`，链接基址 `0x80000000`）。一个 DUT 可用，当且仅当满足三点：

| 约束 | 说明 |
|---|---|
| 加载裸机 ELF | 在 `0x80000000` 取指执行 |
| hart 数 ≥ `hart_count + 1` | litmus7 是"控制器 + 工作线程"模型：hart 0 永远是控制器、不参与测试；N 进程测试需要 N+1 个 hart |
| 输出/退出通道 | 能被 harness 的 HTIF 桩驱动，且输出落到 stdout（PTY 可捕获） |

各 DUT 现状：

- **spike**（参考模拟器）：原生 HTIF + `-p N` 多 hart。默认验证目标。
- **XiangShan `emu`**：支持 HTIF（HTIF 桩能在 XS 上正常引导/输出，此前的 harness bring-up 已确认），核数经 `--num-cores` 编译期参数化、可构建 ≥3 核。→ **满足 litmus7 约束，spike-litmus-harness 可直接用于 XS**，仅需一个 ≥3 核的 emu 构建做端到端 smoke。
- **chipyard（Rocket / BOOM）**：chipyard 仿真器提供标准 `tohost`/HTIF 通道，≥3 核配置可构建。→ 同一套 HTIF harness 预期可用，需一次 smoke 验证。
- **NEMU**：**不**说 HTIF（退出走 `nemu_trap` 伪指令、控制台走 UART16550 MMIO、单 hart per process + 私有地址空间）。需要独立的胶水层 → 已有 `nemu-litmus-harness/`（协作式纤程调度器，通过 `__sync_add_and_fetch` 宏注入 `fiber_yield` 拆解 barrier 死锁）。这是唯一需要专用 harness 的 DUT。

因此：**对 spike / XiangShan / chipyard(Rocket,BOOM) 这一类 HTIF + 可多核 DUT，pipeline 完全通用，只换 `dut_config`（cmd / emu_path / 核数）即可。** NEMU 类（非 HTIF）需另配 harness 胶水。

> DUT 实验与运行统一在服务器进行。本地仓库不保留 DUT 编译产物。

---

## 4. 环境依赖

`fuzzer/scripts/setup_divefuzz_mc.sh` 一键配置 **litmus 工具链**（裸 Ubuntu 服务器或 `divefuzz-dev` 容器均可，幂等）：

```bash
bash fuzzer/scripts/setup_divefuzz_mc.sh     # apt(交叉 GCC+python) + herdtools7 + riscv.cfg + newlib medany 重建
source fuzzer/scripts/env.sh                 # 导出路径（运行 pipeline 前必须 source）
```

脚本只配到"`.litmus` 可编译/可判定"为止：herd7/litmus7 + 交叉 GCC + python。**不构建 spike（那是 DUT）、不从源码构建 riscv-gnu-toolchain** —— newlib sysroot 假定已在服务器存在（或单独提供），脚本仅探测并在 `env.sh` 导出；若 toolchain 源码同机则补做 medany 重建。

脚本生成 `fuzzer/scripts/env.sh`（机器相关，不入库），导出 `LITMUS7` / `LITMUS7_SHARE` / `HERD7` / `GCC` / `LIBGCC` / `NEWLIB_SYSROOT`(探测) / `SPIKE`(探测，有则导出)。harness Makefile 所有路径都用 `?=`，source 后即覆盖其硬编码默认值。

| 工具 | 用途 | setup.sh |
|---|---|---|
| `herd7` / `litmus7` 7.58 | RVWMO oracle + `.litmus`→C 代码生成 | `opam install herdtools7` |
| `riscv64-linux-gnu-gcc` 13 | 编译 harness C + 链接（libgcc.a） | `apt install gcc-riscv64-linux-gnu` |
| python (yaml/numpy/psutil/tqdm) | pipeline 运行时 | `apt install python3-{yaml,numpy,psutil,tqdm}` |
| newlib (`riscv64-unknown-elf`) | harness 的 libc/libm | **假定已存在**；脚本探测并导出 `NEWLIB_SYSROOT`，toolchain 源码同机时补做 medany 重建 |
| `spike` | 参考 DUT（非 litmus） | **假定已存在**；脚本探测，有则在 env.sh 导出 `SPIKE` |

两个关键修复（脚本自动 / 条件完成）：

1. **herdtools7 不附带 `riscv.cfg`**，只附带 `riscv-qemu.cfg`。litmus7 的 `-mach riscv` 找不到 `riscv.cfg` 会报 `Cannot find file riscv.cfg`。修复：`ln -sf riscv-qemu.cfg <share>/riscv.cfg`（两者 `carch=RISCV`，代码生成等价）。
2. **newlib 默认 `-mcmodel=medlow`**，medlow 的绝对 `lui` 寻址在加载基址 `0x80000000`（bit 31 置位）下符号扩展错误，导致 `relocation truncated to fit: R_RISCV_HI20`。修复：把 riscv-gnu-toolchain `Makefile` 的 `-mcmodel=medlow` 改为 `-mcmodel=medany` 再 `make stamps/build-newlib`。**仅在 toolchain 源码同机时执行**（`TOOLCHAIN_SRC` 指向源码树）；否则需确保服务器提供的 sysroot 已是 medany。

> 可调环境变量：`RISCV_ROOT`（spike/newlib 探测根，默认 `$HOME/riscv`）、`TOOLCHAIN_SRC`（riscv-gnu-toolchain 源码树，用于 medany 重建）、`NPROC`。
---

## 5. 使用方式

### 5.1 纯 Python 自检（无需任何外部工具）

```bash
cd fuzzer
python -m generator.core.multicore.selftest
# 预期: DFMC selftest PASS
```

### 5.2 CLI 生成（含 herd oracle + ELF 构建）

```bash
cd fuzzer
python -m generator.main --generate --multicore --seeds 3 \
  --out-dir /tmp/dfmc-out --hart-count 2 \
  --test-family SB --test-family LB --test-family MP \
  --noise-level none \
  --herd-path /home/ra4ing/.opam/default/bin/herd7
```

每个种子产出：`seed.mc.json` / `seed.litmus` / `allowed_outcomes.json` / `manifest.json` / `seed.elf`。加 `--no-build-executable` 跳过 ELF 构建（仅模型产物）。

### 5.3 完整闭环（YAML）

```bash
cd fuzzer
python run_dut.py --config spike_multicore.yaml
```

`spike_multicore.yaml` 是已验证的参考配置（DUT cmd 为 `spike -p3 $1`：1 main + 2 workers，匹配 `AVAIL=2`）。接入新 DUT 时复制一份、改 `dut_target`（cmd / emu_path / 核数）即可，详见第 3 节。

---

## 6. 已验证结果（spike 闭环）

`run_dut.py --config spike_multicore.yaml`（3 种子 SB/LB/MP，noise=none）：

```
Testing completed: 3 passed, 0 failed, 0 timed out, 0 errors. Total: 3.
```

| 种子 | 族 | herd allowed | spike 观测 | 判定 |
|---|---|---|---|---|
| seed_0 | SB | 4 states | `{h0.x10:0,h1.x10:1}`×200, `{h0.x10:1,h1.x10:0}`×200 | SUCCESS（均 ∈ allowed） |
| seed_1 | LB | 4 states | `{h0.x10:0,h1.x10:1}`×200, `{h0.x10:1,h1.x10:0}`×200 | SUCCESS |
| seed_2 | MP | 4 states | `{h1.x10:1,h1.x11:1}`×200 | SUCCESS（观测到"消息完整传递"，**未**观测被 fence 禁止的 `{x10:1,x11:0}`） |

MP 的结果尤其有意义：spike 从未观测到 `y 已可见但 x 尚不可见`（`{h1.x10:1, h1.x11:0}`），证明 spike 遵守 release fence。所有结果均为 SUCCESS，无 bug 归档，符合预期。

---

## 7. 当前限制

- **族**：SB/LB/MP/MPTSO/CoRR/WRC/IRIW（均仅用 Load/Store/Fence/FenceTso，exporter+validator 完整支持）。`hart_count` ∈ {2,3,4}（各族拓扑固有）。`noise_level ∈ {none, L0, L1}`。未知族/级别在 `build_program` 立即 `ValueError`；`--hart-count` 与族拓扑冲突时报错。
- **随机化已开启 6 轴**（`--randomize`）：寄存器分配、存值、fence pred/succ、同字别名、访问宽度混用，外加 L1 噪声（`--noise-level L1`，含指令间 interleaving）。全部 spike 端到端验证、可组合。确定性模式（`--randomize` 关）与已验证 seed 字节一致。所有轴集中在 `GenCtx`，新增轴只改 `GenCtx` 不碰族定义。
- **AMO / LR / SC / Dependency / Delay** 事件已在模型中声明，但在 validator/exporter 中显式拒绝（`... not yet implemented in the exporter (planned for the randomization phase)`）。后续独立工作流。
- **aq/rl 位受阻**：plain load/store 编码无 aq/rl 位（真实汇编器拒 `ld.aq`），herd7 虽接受但不编译。aq/rl 只存在于原子指令，需等 AMO/LR-SC 落地；plain 访问的 acquire/release 可用 fence 插入表达（未来轴）。
- **地址布局受限**：litmus7 不支持数组声明/指针偏移，故 only same-word 别名可表达；same-cacheline-different-word / 跨页 需改 harness 内存布局（独立大工程）。
- XiangShan / chipyard 端到端 smoke 尚未在仓库内验证（DUT 运行在服务器）。

---

## 8. 相关文档

- `multicore_divefuzz_research_plan.md`：后续生成/噪声/corpus/reducer 的研究路线。
- `README.md` / `PROGRESS.md`：litmus harness（spike / nemu）的实现细节、已修复 bug、文件结构。
- `spike-litmus-harness/docs/{DESIGN,MANUAL}.md`、`nemu-litmus-harness/docs/{DESIGN,MANUAL}.md`：各 harness 的逐行设计与使用手册。
