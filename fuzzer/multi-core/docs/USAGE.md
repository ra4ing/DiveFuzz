# DiveFuzz-MC 使用

本文是操作手册：装什么、怎么生成种子、随机化怎么开、怎么在 DUT 上跑、结果怎么读、怎么扩展。所有命令都在 Docker 容器 `divefuzz-dev` 内执行（工作区已挂载）。

## 前置工具与两个已知的坑

完整闭环依赖四件工具，都在容器里：`herd7` 和 `litmus7`（`opam install herdtools7`，作为 RVWMO oracle 与 C 代码生成器）、`riscv64-linux-gnu-gcc`（`apt`，带 `libgcc.a`，交叉编译 litmus7 生成的 C）、`spike`（参考模拟器，多核 `-pN` + HTIF 直方图输出）。还需要一份 medany 编译的 newlib sysroot 作为 harness 的 libc。

有两个环境坑 `scripts/setup_divefuzz_mc.sh` 会自动修。其一，herdtools7 只附带 `riscv-qemu.cfg` 不附带 `riscv.cfg`，而 litmus7 的 `-mach riscv` 要找 `riscv.cfg`——做个符号链接即可，两者 `carch=RISCV`、代码生成等价。其二，newlib 默认 `-mcmodel=medlow`，medlow 的绝对 `lui` 寻址在加载基址 `0x80000000`（bit 31 置位）下符号扩展出错，报 `relocation truncated to fit: R_RISCV_HI20`——需要把工具链 Makefile 的 `-mcmodel=medlow` 改成 `-mcmodel=medany` 重建 newlib。这两步脚本幂等，已装的东西不会被动。

只想验证生成器逻辑、不需要任何外部工具时，跑纯 Python 自检：`cd fuzzer && python -m generator.core.multicore.selftest`，预期打印 `DFMC selftest PASS`。

## 两个入口，两种用途

CLI 入口 `python -m generator.main --generate --multicore ...` 只做生成（产 seed 产物，不碰 DUT），适合快速迭代模型/exporter、或在不方便跑模拟器的机器上预生成种子。YAML 入口 `python run_dut.py --config <yaml>` 走完整闭环：生成 → herd 求 allowed → litmus7 编译 → DUT 重复运行 → 解析直方图 → 比对判定 → 非 SUCCESS 归档。调试生成侧用前者，真正找 bug 用后者。

## 生成种子

典型命令（在容器内，从 `fuzzer/` 目录）：

```
python -m generator.main --generate --multicore --seeds 3 \
  --out-dir /tmp/dfmc-out --test-family SB --test-family LB --test-family MP \
  --noise-level none --randomize \
  --herd-path /home/ra4ing/.opam/default/bin/herd7 \
  --litmus-harness-dir multi-core/spike-litmus-harness
```

每个 seed 在 `<out>/seed_<id>/` 下产出五件产物，构成一个**自洽、可独立判定**的单元：`seed.mc.json`（程序模型）、`seed.litmus`（RISCV 源）、`allowed_outcomes.json`（herd 解析的 allowed 集）、`seed.elf`（litmus7 编译的裸机可执行）、`manifest.json`（路径与元数据）。加 `--no-build-executable` 跳过 ELF，只留模型产物。`--test-family` 可重复，省略则默认 SB/LB/MP。

注意 hart 的语义：`--hart-count N` 是**过滤器**，只生成拓扑要求 N hart 的族；省略则各族用自己的 hart 数（SB/LB/MP/MPTSO/CoRR 是 2，WRC 是 3，IRIW 是 4）。所以跑 IRIW 不需要传 `--hart-count 4`，只要 `--test-family IRIW` 或不传 `--hart-count` 即可；若传了 `--hart-count 2` 又点名 IRIW，会立刻报清晰错误而非静默生成错误的程序。

可选族覆盖 plain 访问（SB/LB/MP/MPTSO/CoRR/CoWR/CoRW/CoWW/WRC/IRIW/2+2W）、原子（AMO 压原子性、LRSC 压预留冲突）与依赖扰动（LBdep：数据依赖+延迟链；LBadc：地址依赖 xor 依赖加载 + 控制依赖分支跳过）。相干/序族（CoWR/CoRW/CoWW/2+2W）值敏感，builder 自动取互异竞争值；LBdep 的延迟链长在 `--randomize` 下从 [1,8] 抽取。原子族用 AMO/LR/SC 事件，是 `--test-family` 的一等公民；它们额外受两条随机化轴作用（见下）。

## 随机化：`--randomize` 与 `--noise-level`

这两组开关相互独立、可叠加。`--randomize` 打开七条"细节轴"：寄存器分配、存值、fence pred/succ、同字别名、访问宽度混用（这五条作用于 plain load/store 族），加上 AMO 操作与 aq/rl 位（这两条只作用于原子族——plain load/store 编码里没有 aq/rl 位，汇编器会拒绝 `ld.aq`）。它们都集中在 `GenCtx`，彼此正交、可任意组合。`--noise-level L1` 在此之外叠加 interleaving 噪声（在窗口事件之间插 scratch ALU 指令）；`L0` 是惰性单条噪声，`none` 无噪声。

确定性是默认行为，且很重要：**不传 `--randomize` 时，生成器走确定性默认，产物与最初 spike 验证过的 seed 字节一致**——这是回归基准。同一个 `seed_id` 加同一组开关永远产出同一个程序（RNG 用 seed 播种），所以任何种子都可复现。随机化不是"随机一点"，而是把每条轴都打开后，单个族能展开成大量形态各异的变体，大幅提升对同一拓扑的覆盖密度。

随机化的正确性不靠运气：allowed 集永远由 herd 对实际发出的那份 `.litmus` 重算，所以无论轴怎么组合，比对都成立。唯一约束是发出的构造必须同时被 herd 和汇编器接受——这是设计约束，不是运行期赌博。

## 在 DUT 上跑（YAML）

参考配置是 `fuzzer/spike_multicore.yaml`。结构是 `dut_target`（DUT 调用：`cmd` 里 `$1` 是 ELF 路径、`emu_path`、核数、超时）加 `seeds` 列表，每个 seed 的 `multicore:` 块镜像 CLI 参数。spike 的 `cmd` 是 `spike -p3 $1`——`-p3` 给 2 进程测试（1 控制器 + 2 worker）。接入 XiangShan 只需复制一份、把 `cmd` 换成 emu 调用、`emu_path` 指向 emu、并确保 emu 编译了 ≥ 测试 hart 数 + 1 个核；Python 流水线完全不用改。

`runs_per_seed` 与 `litmus_runs`/`litmus_size` 控制重复次数——内存序 bug 常是罕见结果，需要足够重复才观测得到，调高这些能提升罕见结果的捕获概率，代价是时间。判定结果四类：`SUCCESS` 表示所有观测都在 allowed 集内（正常）；`MODEL_VIOLATION` 表示观测到 allowed 集之外的结果，是**候选 bug**，触发归档；`TIMEOUT`/`RUNTIME_TRAP`/`NO_OUTCOME` 是执行异常（DUT 挂起、trap、没打印直方图），也归档但归类为基础设施问题而非模型违反。归档内容包含完整复现材料（mc.json/litmus/elf/allowed/observed/log/oracle_report）。

## 扩展：加族、加轴

加一个族，只需在 `families.py` 写一个 `_build_xxx(seed_id, ctx, noise_level)`（用 ctx 要寄存器/值/屏障，用 `_load`/`_store`/`_fence` 构造事件），再在 `CATALOG` 加一条 `FamilySpec`。它自动出现在 `--test-family` 的可选值、selftest、`available_families()` 里，无需改别处。族的 hart 数写在 spec 里。

加一条随机化轴，给 `GenCtx` 加一个方法（返回该轴的随机选择），然后在 `build_program` 里应用它（post-build 最省事，比如直接改 `hp.modeled_window` 或加字段）。族 builder 不用动。轴上线前必须过三道关，缺一不可：用 herd7 探针确认新构造可被建模；用 `riscv64-linux-gnu-gcc` 探针确认能汇编；在 selftest 加一条断言（确定性模式不变、随机模式产生预期变化）。这三步是本轮 aq/rl、mul、same-cacheline 三次踩坑换来的纪律——"herd 接受"绝不等于"能跑"。
