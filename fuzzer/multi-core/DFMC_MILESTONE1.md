# DiveFuzz-MC 里程碑 1 — 可建模多核种子生成与验证

本里程碑实现了 DiveFuzz-MC 的第一条端到端闭环：**生成可判定的 2-hart 多核测试 → 通过 herd7/RVWMO 求解允许结果集 → 编译为 litmus7 兼容可执行文件 → 在模拟器上重复运行 → 解析观测直方图 → 与允许集比对 → 归档违规**。

> 状态：闭环已在 **spike**（litmus7 harness 的目标参考模拟器）上验证通过。XiangShan `emu` 为单 hart difftest，litmus7 harness 无法直接引导（启动即 trap），真正的 XiangShan 多核 DUT 集成属于研究计划的 Phase 4（custom ASM runtime）。

---

## 1. 架构概览

```
生成侧 (fuzzer/generator/core/multicore/)
  families.build_program()          选族(SB/LB/MP) → 构造 MCProgram
    ├─ model.py                     数据模型: MCProgram / HartProgram / ModeledEvent / SharedVar / ObservedReg
    ├─ validator.validate()         静态校验: hart 数、事件宽度、噪声白名单、observed 由 Load 定义
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

入口两种：
- **CLI（仅生成）**：`python -m generator.main --generate --multicore ...`
- **YAML（生成+运行+判定+归档）**：`python run_dut.py --config <yaml>`

---

## 2. 核心模型与原理

### 2.1 MCProgram 数据模型

- `EventKind`：`Load / Store / Fence / FenceTso / AMO / LR / SC / Dependency / Delay`（本里程碑仅实现 Load/Store/Fence/FenceTso，其余在 validator/exporter 中以明确 `ValueError` 拒绝）。
- `SharedVar(name, init_value, width, alignment)`：跨 hart 共享内存变量。
- `ModeledEvent`：一次被建模的内存事件（addr/dst/value/width/aq/rl/pred/succ…）。
- `HartProgram`：单 hart 程序 = `prologue_noise + modeled_window + epilogue_noise + result_capture`。
- `MCProgram`：完整多核测试方案（seed_id、isa、hart_count、shared_vars、hart_programs、observed、oracle_spec、noise_profile）。

### 2.2 规范结果键（canonical outcome key）

litmus7/herd7 的输出使用 `0:x10=1` 形式。DiveFuzz-MC 采用**原始寄存器键** `h{hart}.{reg}`（如 `h0.x10`、`h1.x10`），而非逻辑别名（如 `h0.r1`）。这样 allowed（来自 herd）与 observed（来自 litmus 直方图）使用**同一套键**，比对时无需发明别名映射。

一个规范结果 = `tuple(sorted(state.items()))`，可哈希、可 JSON 序列化。

### 2.3 测试族（2-hart MVP）

共享变量 `x=0, y=0`（width 8）；地址寄存器 `x6=x, x7=y`（两 hart 相同）；值寄存器 `x12/x13`；观测 load 目的 `x10/x11`。

| 族 | P0 modeled window | P1 modeled window | RVWMO 允许结果 |
|---|---|---|---|
| **SB**（Store Buffering） | `sd x=1; ld y→x10` | `sd y=1; ld x→x10` | 全部 4 种（无 fence） |
| **LB**（Load Buffering） | `ld x→x10; sd y=1` | `ld y→x10; sd x=1` | 全部 4 种 |
| **MP**（Message Passing） | `sd x=1; fence rw,rw; sd y=1` | `ld y→x10; ld x→x11` | 4 种，但 `{x10=1,x11=0}` 被 fence 禁止 |

族选择为确定性轮换：`family = test_families[(seed_id - seed_offset) % len(test_families)]`，保证覆盖度可复现。

### 2.4 L0 噪声

`noise_level="L0"` 在每个 hart 的 modeled window 之前插入 `nop` / `addi x20,x20,0`（由 seeded RNG 选择），并**写入 `.litmus` 表格**（作为各 process 列的前导行）。这两条指令不触碰共享内存或观测寄存器，故不影响 herd 的允许结果集（已实测：SB+L0 的 `States` 与无噪声一致）。`noise_level="none"` 不插入噪声。其他值在 `build_program` 立即 `ValueError`。

### 2.5 litmus 导出格式

匹配现有 harness 样例（`build/LB-mixed1/gen/run.sh`）的 RISCV 表格式：

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

执行器分类顺序（适应 spike 打印结果后挂起的行为）：

1. 输出含 `HIT BAD TRAP` / `ABORT` → `RUNTIME_TRAP`
2. 有可解析直方图 → `classify_outcomes`（`SUCCESS` / `MODEL_VIOLATION` / `NO_OUTCOME`）
3. 硬超时且无直方图 → `TIMEOUT`
4. 否则 → `NO_OUTCOME`

> 关键点：spike 完成测试后会**挂起**（不自动退出），但直方图已打印。因此“拿到直方图”优先于“超时”——只要解析到合法结果，即使进程随后被超时终止，仍按直方图判定为 SUCCESS/MODEL_VIOLATION，而非误判为 TIMEOUT。

---

## 3. 环境依赖

全部在 Docker `divefuzz-dev`（Ubuntu 24.04）内：

| 工具 | 用途 | 来源 |
|---|---|---|
| `herd7` 7.58 | RVWMO 模型 oracle（求 allowed outcomes） | `opam install herdtools7` |
| `litmus7` 7.58 | `.litmus` → C harness 代码生成 | `opam install herdtools7` |
| `riscv64-linux-gnu-gcc` 13 | 编译 litmus7 harness C 代码 + 链接 | `apt install gcc-riscv64-linux-gnu` |
| newlib (`riscv64-unknown-elf`) | harness 的 libc/libm | riscv-gnu-toolchain（**需 medany 重建**） |
| `spike` | RISC-V ISA 模拟器，多核 `-pN` + HTIF 直方图输出 | 容器自带 `/home/ra4ing/workspace/riscv/bin/spike` |
| `riscv64-unknown-elf-gcc` 15.1 | 提供 libgcc（matched newlib） | 容器自带 |

### 两个关键环境修复（setup 脚本自动完成）

1. **herdtools7 不附带 `riscv.cfg`**，只附带 `riscv-qemu.cfg`。litmus7 的 `-mach riscv` 找不到 `riscv.cfg` 会报 `Cannot find file riscv.cfg`。修复：`ln -sf riscv-qemu.cfg <share>/riscv.cfg`（两者 `carch=RISCV`，代码生成等价）。

2. **newlib 默认以 `-mcmodel=medlow` 编译**，medlow 的绝对 `lui` 寻址在加载基址 `0x80000000`（bit 31 置位）下符号扩展错误，导致 `relocation truncated to fit: R_RISCV_HI20` 链接失败。修复：把 riscv-gnu-toolchain `Makefile` 的 `-mcmodel=medlow` 改为 `-mcmodel=medany` 并 `make stamps/build-newlib`（medany 用 PC 相对寻址，在 `0x80000000` 严格安全且更强）。

---

## 4. 部署方式

```bash
# 一次性环境搭建（在容器内执行，幂等可重复）
cd DiveFuzz
docker exec divefuzz-dev bash fuzzer/scripts/setup_divefuzz_mc.sh
```

脚本第 5 步（newlib medany 重建）约 5–10 分钟。其余步骤 < 2 分钟。

> 若容器内非 root，apt 步骤需要 root：`docker exec -u root divefuzz-dev bash fuzzer/scripts/setup_divefuzz_mc.sh`。

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

每个种子产出：`seed.mc.json` / `seed.litmus` / `allowed_outcomes.json` / `manifest.json` / `seed.elf`。
加 `--no-build-executable` 跳过 ELF 构建（仅模型产物）。

### 5.3 完整闭环（YAML，spike 模拟器）

```bash
cd fuzzer
python run_dut.py --config spike_multicore.yaml
```

`spike_multicore.yaml` 的 DUT cmd 为 `spike -p3 $1`（1 main + 2 workers，匹配 AVAIL=2）。执行：生成 → herd → 编译 ELF → spike 运行（PTY 检测 `Observation` 即终止）→ 解析直方图 → 判定 → 归档。

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
| seed_2 | MP | 4 states | `{h1.x10:1,h1.x11:1}`×200 | SUCCESS（观测到“消息完整传递”，**未**观测被 fence 禁止的 `{x10:1,x11:0}`） |

MP 的结果尤其有意义：spike 从未观测到 `y 已可见但 x 尚不可见`（`{h1.x10:1, h1.x11:0}`），证明 spike 遵守 release fence，流水线正确将其归类为合规。

所有结果均为 SUCCESS，故无 bug 归档（`outputs/multicore_bugs_*` 不产生），符合预期。

---

## 7. 已知限制与后续

- **仅支持 2-hart、族 {SB, LB, MP}、noise_level ∈ {none, L0}**。其他组合在 `build_program` / `MultiCoreConfig.__post_init__` 立即 `ValueError`。
- **XiangShan `emu`（单 hart difftest）无法运行 litmus7 harness**：实测 emu 加载 ELF 后仅提交 3 条指令即在 `pc=0xe` 处 `HIT GOOD TRAP`（double trap）。litmus7 harness 的启动/HTIF/barrier 是 spike 专用的。真正的 XiangShan 多核 DUT 判定需要研究计划的 **Phase 4：custom ASM runtime**（XiangShan 原生引导、多 hart、独立输出通道），届时 `LitmusExecutableBackend` 将由 custom ASM 后端替代。
- **AMO / LR / SC / Dependency / Delay** 事件已在模型中声明，但在 validator/exporter 中显式拒绝（`Modeled event <kind> is declared but not implemented in the MVP exporter`）。
- spike 完成测试后挂起；运行器用 PTY + `Observation` 检测提前终止，单种子运行约 30s（含 litmus7 内部数百次迭代）。

---

## 8. XiangShan 多核：根因分析与 Phase 4 自写后端设计（关键落盘）

本节记录里程碑 1 期间排查 XiangShan 多核得到的**硬性结论与设计要点**，供 Phase 4 执行（可能在新 session）直接接续，不依赖任何隐性记忆。

### 8.1 litmus7 harness 的 hart 模型（为什么 litmus7 上不了 XiangShan）

litmus7 生成的 harness 采用**控制器 + 工作线程**模型，**hart 0 永远是控制器、不参与测试**：

- `spike-litmus-harness/spike_hart.c:8`：`static unsigned int _next_hart = 1;`（hart 分配从 1 开始）。
- `startup.S`：hart 0 → `.Lhart0` → `call main()`；hart>0 → `.Lsecondary_spin` 等待 `_litmus_slots[hartid]` 被设置。
- 生成的 `main()`（`seed.c`）：`for id in AVAIL: launch(...)`，`launch()` 用 `_next_hart++` 分配，故 P0→hart1、P1→hart2。
- Makefile 实锤：`SPIKE_HARTS := $(AVAIL)+1`，`spike -p3`（AVAIL=2），注释 `"3 harts: 1 main + 2 workers"`。

**结论**：一个 2 进程（P0/P1）的 litmus7 测试需要 **3 个 hart**（hart0 控制器 + hart1 P0 + hart2 P1）。

### 8.2 XiangShan 的核数上限

- 当前 emu 构建：`KunminghuV2MinimalConfig`，`numCores: 1`，`--num-cores 1`（见 `build/generated-src/difftest_profile.json`）。
- 配置核数参数化：`Configs.scala` `KunminghuV2MinimalConfig(n: Int = 1)`，`case XSTileKey => Seq.tabulate(n){...}`；Makefile `NUM_CORES ?= 1` → 生成器 `--num-cores $(NUM_CORES)`。
- KunminghuV2 是**双核架构**（L3/一致性按 2 核设计），**上限 2 核**。
- difftest 参考最高只有 `riscv64-nemu-interpreter-dual-so`（双核），**无 triple/quad 参考**（`ls ready-to-run/` 确认）。

### 8.3 3 > 2 阻塞

litmus7 要 3 hart，XiangShan 最多 2 核 → **litmus7 harness 无法在双核 XiangShan 上跑 2 进程测试**。即使编出 `NUM_CORES=2`，hart 2（P1）无核 → barrier 永久等待 → 卡死（与单核同症，仅缺核后移一位）。`NUM_CORES=3` XiangShan 不支持。

> 旁证（已实测）：`emu --diff spike-so` 因单线程参考模型建模不了多 hart，3 条指令后假 trap；`emu --no-diff` 则不 crash，hart0 能跑过 startup 进 main、卡在 barrier 等 hart1——**证明 harness 的引导/HTIF/BSS 在 XiangShan 上本身正常，唯一缺的就是核数**。

### 8.4 双核 emu 编译（Phase 4 前置，由用户执行）

```bash
cd /home/ra4ing/workspace/riscv/DiveFuzz/dut/XiangShan
make clean
make emu CONFIG=KunminghuV2MinimalConfig NUM_CORES=2 -j$(nproc)
# 验证: grep numCores build/generated-src/difftest_profile.json  -> 2
# difftest 参考: ready-to-run/riscv64-nemu-interpreter-dual-so（现成，无需自编）
```

### 8.5 Phase 4：custom ASM 后端设计要点（替代 LitmusExecutableBackend）

**核心改动**：放弃 litmus7 的"控制器独占一 hart"模型，自写 **2-hart 裸机程序——hart0=P0、hart1=P1、无控制器**，恰好塞进双核 XiangShan。

| 模块 | 要点 |
|---|---|
| `startup.S` | 两核复位→`csrr mhartid`→hart0 走 P0、hart1 走 P1；设 sp/gp（参考现有 spike-litmus-harness/startup.S） |
| `linker.ld` | RAM 0x80000000；结果区与 barrier 标志**独立缓存行**，远离 x/y |
| 初始化 | 把共享变量写到各自地址（init_value） |
| 测试窗口 | 每个 hart 顺序执行 modeled events——**直接复用** `litmus_exporter._event_instructions()` 的 event→指令映射 |
| 结果采集 | 窗口结束后把观测寄存器(x10/x11)存到独立结果区（**独立缓存行**） |
| barrier | 独立标志变量（与 x/y 不同缓存行）汇合后再读结果 |
| 重复+随机 | 跑 N 次 + 随机延迟/地址扰动，暴露弱行为 |
| 输出 | 一个 hart 把 `outcome→count` 直方图经 tohost 打印（复用 `outcome.parse_litmus_histogram` 解析，或 `DFMC_OUTCOME` 行格式） |
| 退出 | tohost 干净退出 |

**可靠性硬规则（必须遵守 + 审计）**：
1. 测试窗口内**只**触碰共享变量 x/y，绝不写观测寄存器、绝不碰 runtime/barrier/结果区。
2. 结果区、barrier 标志、输出缓冲**必须与 x/y 在不同缓存行**（64B 对齐隔离），否则采集/同步动作会给 x/y 强加序 → 假阳性/假阴性。
3. barrier 只序结果汇报，**不得**对被测内存操作施加额外序。

### 8.6 可靠性验证：spike 对拍（先不上 XiangShan）

自写后端**先在 spike 上和 litmus7 后端对拍**证明可信，再上 XiangShan：
- 对同一 `MCProgram`，分别用 litmus7 后端和 custom 后端在 spike 上跑足够多次。
- 断言两者**观测到的结果集合一致**（`observed_outcome_set_litmus == observed_outcome_set_custom`）。
- 一致 → 证明自写后端没有制造/遗漏结果，可信；不一致 → 排查采集隔离/随机化缺陷。
- 通过对拍后，custom 后端 + 双核 emu（`--diff riscv64-nemu-interpreter-dual-so`）即可在 XiangShan 上端到端闭环。

### 8.7 环境状态（已就绪，Phase 4 无需重做）

`scripts/setup_divefuzz_mc.sh` 已配置：herd7/litmus7（opam，`~/.opam/default` 符号链接）、`riscv.cfg → riscv-qemu.cfg`、medany newlib、`gcc-riscv64-linux-gnu`、spike。Phase 4 仅需额外：双核 emu（8.4）+ custom 后端代码。

### 8.8 接口契约（与现有流水线对接）

- `MCProgram`（`generator/core/multicore/model.py`）不变；custom 后端读 `seed.mc.json` 生成 `seed.S`/`seed.elf`。
- 新增 `LitmusExecutableBackend` 的并列实现（如 `CustomAsmBackend`），实现同一 `build(...) -> ELF` 契约；通过 `MultiCoreConfig` 选择后端。
- runner（`executor/multicore/runner.py`）的 `_run_once` PTY 流式 + 完成标记检测、`oracle.classify_outcomes`、`archive` 全部复用，**不因后端切换而改**。
- canonical outcome key 仍是 `h{hart}.{reg}`（`h0.x10` 等），与 herd `allowed_outcomes.json` 直接比对。
