# BOOM V4 CSRRSI hpmcounter Bug 复现工具使用文档

## 背景

BOOM V4 在 U-mode 下执行 `CSRRSI` 对 `hpmcounter` CSR 的访问时，未正确检查
`mcounteren` 权限位，导致本应触发 illegal-instruction 异常的指令被静默放行。
Spike 参考模型行为符合 RISC-V Privileged Spec v20240411 §3.1.11 的要求，
cosim 检测到 PC 分歧。

已发现的 mismatch 分析见 `mismatch_analysis/ANALYSIS.md`。

## 环境要求

**所有操作必须在 Docker 容器 `divefuzz-dev` 中执行。** 工具链、BOOM 仿真器、
Spike 参考模型均在容器内，宿主机上无法运行。

```bash
# 确认容器运行中
docker ps --filter "name=divefuzz-dev"

# 进入容器
docker exec -it divefuzz-dev zsh

# 或直接在容器内执行命令
docker exec divefuzz-dev bash -c '<command>'
```

### 容器内工具链

| 工具 | 路径 |
|------|------|
| RISC-V 工具链 | `/home/ra4ing/workspace/riscv/bin/riscv64-unknown-elf-*` |
| BOOM 仿真器 | `/home/ra4ing/workspace/riscv/DiveFuzz/dut/chipyard/sims/verilator/simulator-chipyard.harness-MediumBoomV4CosimConfig` |
| Spike | `/home/ra4ing/workspace/riscv/bin/spike` |
| 项目根目录 | `/home/ra4ing/workspace/riscv/DiveFuzz/fuzzer/executor/reproduce/` |

## 文件清单

```text
fuzzer/executor/reproduce/
├── reproduce_bug.py          # 一体化复现脚本（编译 / 执行 / 分析）
├── reproduce_bug.yaml        # 可供 run_dut.py 直接使用的 YAML 配置
├── Makefile                  # 快捷 make 目标
├── USAGE.md                  # 本文档
├── output/                   # 编译 & 运行输出（运行时自动创建）
└── mismatch_analysis/        # 已发现 mismatch 的独立分析（按种子分子目录）
    ├── README.md             # 索引和目录约定
    └── bug_csrrsi_hpmcounter/     # 种子: CSRRSI hpmcounter bug
        ├── DETAILED_BUG_REPORT.md # 详细分析（规范引用、证据、时间线）
        ├── ANALYSIS.md            # 简要分析摘要
        ├── bug_csrrsi_hpmcounter.S
        ├── bug_csrrsi_hpmcounter.elf
        ├── bug_csrrsi_hpmcounter.img
        ├── dut_cosim_output.log
        └── spike_standalone_trace.log
```

## 快速开始

以下命令均在 Docker 容器内执行：

```bash
docker exec -it divefuzz-dev zsh
cd /home/ra4ing/workspace/riscv/DiveFuzz/fuzzer/executor/reproduce
```

### 1. 编译种子

```bash
MARCH="rv64gcv_zicsr_zifencei_zfh_zba_zbb_zbkc_zbc_zbkb_zbs_zmmul_zknh_zkne_zknd_zbkx_zfhmin"
LINK=../../generator/reg_analyzer/linker/link.ld

riscv64-unknown-elf-as -march $MARCH -c bug_csrrsi_hpmcounter.S -o output/bug_csrrsi_hpmcounter.o
riscv64-unknown-elf-ld -T $LINK output/bug_csrrsi_hpmcounter.o -o output/bug_csrrsi_hpmcounter.elf
riscv64-unknown-elf-objcopy -O binary output/bug_csrrsi_hpmcounter.elf output/bug_csrrsi_hpmcounter.img
```

### 2. 运行 DUT（BOOM cosim）

```bash
cd /home/ra4ing/workspace/riscv/DiveFuzz/dut/chipyard
SEED="/home/ra4ing/workspace/riscv/DiveFuzz/fuzzer/executor/reproduce/output/bug_csrrsi_hpmcounter.img"
bash -c 'p="${1/img_file/elf_file}"; exec ./sims/verilator/simulator-chipyard.harness-MediumBoomV4CosimConfig "${p%.img}.elf"' _ "$SEED"
```

出现 `PC mismatch` 即表示 bug 复现成功。

### 3. 运行 Spike 参考

```bash
spike --isa rv64imafdcbzicsr_zifencei_zihpm_zba_zbb_zbs_zicntr \
  --priv msu --pmpregions 8 -l \
  output/bug_csrrsi_hpmcounter.elf 2>&1 | head -80
```

Spike 会在 CSRRSI 指令处正确触发 `trap_illegal_instruction`。

### 4. 通过 reproduce_bug.py 一键执行

```bash
cd /home/ra4ing/workspace/riscv/DiveFuzz/fuzzer/executor/reproduce

# 使用 YAML 配置
python reproduce_bug.py --config ../../boom_fuzz.yaml

# 直接指定已有 ELF
python reproduce_bug.py \
  --elf output/bug_csrrsi_hpmcounter.elf \
  --config ../../boom_fuzz.yaml

# 仅运行 Spike
python reproduce_bug.py --spike-only

# 仅编译
python reproduce_bug.py --dut-cmd "echo"
```

### 5. 通过 Makefile

```bash
make reproduce-yaml YAML_CONFIG=../../boom_fuzz.yaml
make reproduce-existing-elf ELF=output/bug_csrrsi_hpmcounter.elf
make compile
make spike
make clean
```

### 6. 通过 run_dut.py

```bash
# 先编译种子，然后
python ../../run_dut.py --config reproduce_bug.yaml
```

### 7. 从宿主机直接执行（不进入容器）

```bash
docker exec divefuzz-dev bash -c '
  cd /home/ra4ing/workspace/riscv/DiveFuzz/fuzzer/executor/reproduce && \
  python reproduce_bug.py --config ../../boom_fuzz.yaml
'
```

## reproduce_bug.py 参数

| 参数 | 说明 |
|------|------|
| `--config <yaml>` | YAML 配置文件（与 `--dut-cmd` 互斥） |
| `--dut-cmd <cmd>` | DUT 命令模板，`$1` 为种子路径占位符 |
| `--dut-cwd <dir>` | DUT 工作目录 |
| `--asm <file>` | 汇编源文件（默认内建种子） |
| `--elf <file>` | 直接使用已有 ELF |
| `--spike-only` | 仅 Spike，不跑 DUT |
| `--timeout <sec>` | DUT 超时（默认 600s） |
| `--output-dir <dir>` | 输出目录 |

## 种子设计

`bug_csrrsi_hpmcounter.S` 包含三个测试点：

| 测试 | 指令 | 预期 Spike | 预期 BOOM |
|------|------|-----------|-----------|
| TEST 1 (对照) | `CSRRCI x14, hpmcounter27, 0` | trap | trap |
| TEST 2 (BUG) | `CSRRSI x4, hpmcounter8, 0` | trap | **不 trap** |
| TEST 3 (对照) | `CSRRWI x6, hpmcounter23, 0` | trap | trap |

- `mcounteren=0`（默认全零），U-mode 禁止访问任何 hpmcounter
- `mstatus.MPP=0`，通过 `mret` 进入 U-mode
- Trap handler：读 mcause，mepc+=4 跳过异常指令，mret 返回

## 输出解读

`PC mismatch spike XXXX != DUT YYYY` — DUT 与 Spike 行为分歧，bug 复现。

详细分析流程：将 DUT 输出和 Spike trace 放入 `mismatch_analysis/` 目录，
编写 `ANALYSIS.md`，记录 divergence point、双方行为、规范依据和结论。

## 规范依据

RISC-V Privileged Architecture v20240411, §3.1.11:

> "When the CY, TM, IR, or HPM_n bit in the mcounteren register is clear,
> attempts to read the cycle, time, instret, or hpmcountern register while
> executing in S-mode or U-mode will cause an illegal-instruction exception."
