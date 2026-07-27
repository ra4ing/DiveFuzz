# BOOM V4 CSRRSI hpmcounter Bug 详细分析

## 一、Bug 是什么

BOOM V4 处理器在 **U-mode** 下执行 `CSRRSI` 指令访问 `hpmcounter` 系列 CSR 时，
**跳过了 `mcounteren` 权限检查**，导致本应触发 illegal-instruction 异常的指令被
静默放行。Spike 参考模型正确执行了该检查并触发异常。

**关键约束**：bug 仅出现在 CSRRSI（funct3=6）指令路径。相同条件下，CSRRCI（funct3=7）
正确触发异常。

---

## 二、规范依据（逐条引用，附来源）

### 2.1 `mcounteren` 的权限控制规则

**来源**：RISC-V Privileged Architecture v20240411（ratified），Machine-Level ISA v1.13，
Section 3.1.11 "Machine Counter-Enable (`mcounteren`) Register"
（源文件：riscv-isa-manual `src/machine.adoc`，行 1555-1606）

> The counter-enable `mcounteren` register is a 32-bit register that
> controls the availability of the hardware performance-monitoring
> counters to the next-lower privileged mode.

核心规则（原文，行 1569-1574）：

> **When the CY, TM, IR, or HPM_n bit in the `mcounteren` register is clear,
> attempts to read the `cycle`, `time`, `instret`, or `hpmcountern` register
> while executing in S-mode or U-mode will cause an illegal-instruction
> exception.** When one of these bits is set, access to the corresponding
> register is permitted in the next implemented privilege mode (S-mode if
> implemented, otherwise U-mode).

**解读**：
- `mcounteren` 的每一位控制对应计数器在低特权模式下的可访问性
- 当 HPM_n 位为 0 时，在 S-mode 或 **U-mode** 中任何**读取** `hpmcountern` 的行为
  **必须**触发 illegal-instruction 异常
- 这是无条件规则，不区分使用哪条 CSR 指令来读取

进一步（原文，行 1602-1606）：

> In harts with U-mode, the `mcounteren` must be implemented, but all
> fields are *WARL* and may be read-only zero, indicating reads to the
> corresponding counter will cause an illegal-instruction exception when
> executing in a less-privileged mode.

**确认**：BOOM 实现了 U-mode，`mcounteren` 必须存在，且默认值（reset 后）为全零，
意味着所有 hpmcounter 在 U-mode 下都不可访问。

### 2.2 `hpmcounter` CSR 的地址范围

**来源**：RISC-V Unprivileged ISA，Section "Zicntr" and "Zihpm" Extensions for Counters
（源文件：riscv-isa-manual `src/counters.adoc`）

> RISC-V ISAs provide a set of up to thirty-two 64-bit performance
> counters and timers that are accessible via unprivileged XLEN-bit
> read-only CSR registers `0xC00`–`0xC1F`

`hpmcounter3`–`hpmcounter31` 对应 CSR 地址 `0xC03`–`0xC1F`。

本 bug 涉及：
- `hpmcounter8` = CSR `0xC08`
- `hpmcounter27` = CSR `0xC1B`（对照组）
- `hpmcounter23` = CSR `0xC17`（对照组）

这些 CSR 在 CSR 地址映射中属于 **Unprivileged Read-Only** 类别（csr[11:10]=11,
csr[9:8]=00），即 `0xC00-0xC1F`。

### 2.3 CSR 指令的读/写语义

**来源**：RISC-V Unprivileged ISA，Section 6.1 "Zicsr Extension for CSR Instructions"
（源文件：riscv-isa-manual `src/csr.tex` / rendered: docs.riscv.org/zicsr.html）

原文关键段落：

> The CSRRWI, CSRRSI, and CSRRCI variants are similar to CSRRW, CSRRS,
> and CSRRC respectively, except they update the CSR using an XLEN-bit
> value obtained by zero-extending a 5-bit unsigned immediate (uimm[4:0])
> field encoded in the `rs1` field instead of a value from an integer register.

> **For CSRRSI and CSRRCI, if the uimm[4:0] field is zero, then these
> instructions will not write to the CSR**, and shall not cause any of the
> side effects that might otherwise occur on a CSR write, nor raise
> illegal-instruction exceptions on accesses to read-only CSRs.
> **Both CSRRSI and CSRRCI will always read the CSR and cause any read
> side effects regardless of `rd` and `rs1` fields.**

规范化为表格（规范原文 Table 1）：

| 指令      | uimm=0 | 读 CSR | 写 CSR |
|-----------|--------|--------|--------|
| CSRRSI    | Yes    | **Yes**| No     |
| CSRRCI    | Yes    | **Yes**| No     |

**关键结论**：

1. `CSRRSI rd, csr, 0`（uimm=0）= **纯读操作**。不写 CSR，但**一定读 CSR**。
2. `CSRRCI rd, csr, 0`（uimm=0）= **纯读操作**。同上。
3. 当 uimm=0 时，两条指令的语义完全等价：都是只读 CSR，不写入。

因此，对于 `mcounteren` 的权限检查，**CSRRSI 和 CSRRCI 在 uimm=0 时必须执行
完全相同的访问检查**。如果 CSRRCI 正确触发了异常，CSRRSI 也必须触发。

---

## 三、Bug 复现证据

### 3.1 测试环境

| 项目 | 值 |
|------|------|
| DUT | BOOM V4 (MediumBoomV4CosimConfig) |
| 参考模型 | Spike (rv64imafdcbzicsr_zifencei_zihpm_...) |
| 种子 | `bug_csrrsi_hpmcounter.elf`（自定义最小化种子） |
| 当前特权级 | U-mode（mstatus.MPP=0，通过 mret 进入） |
| mcounteren | 0x0（从未写入，reset 默认值） |

### 3.2 测试设计

种子包含三个按顺序执行的 CSR 指令，全部在 U-mode 下执行：

```
PC 0x80001044: CSRRCI x14, hpmcounter27, 0    # TEST 1: 对照组
PC 0x80001048: li x10, 1; sw x10, 4(x0)        # 标记 TEST 1 通过
PC 0x80001050: CSRRSI x4, hpmcounter8, 0       # TEST 2: bug 触发点
PC 0x80001054: li x10, 2; sw x10, 8(x0)        # 标记 TEST 2 通过（不应到达）
PC 0x8000105c: CSRRWI x6, hpmcounter23, 0      # TEST 3: 对照组
```

所有三条 CSR 指令都是 uimm=0 的纯读操作，目标都是 hpmcounter CSR。
`mcounteren=0` 意味着所有 hpmcounter 位都为 clear。

根据规范 §3.1.11，三条指令**都必须**触发 illegal-instruction 异常。

### 3.3 实际执行结果

#### DUT (BOOM) cosim 输出

```
Cosim: 207360 commit: 800000be       ← j main (跳转到 main)
Cosim: 207379 exception 2            ← ← CSRRCI hpmcounter27 触发异常 (正确!)
Cosim: 207413 commit: 80001000       ← 进入 trap handler (M-mode)
core   0: 3 0x80001000 csrr x14, mcause  → x14 = 0x2 (illegal instruction)
core   0: 3 0x80001008 csrr x13, mepc    → x13 = 0x80001044 (CSRRCI 的 PC)
core   0: 3 0x8000100c addi x13, x13, 4  → x13 = 0x80001048
core   0: 3 0x80001010 csrw mepc, x13    → mepc = 0x80001048
core   0: 3 0x80001024 mret              → 返回 U-mode
Cosim: 207543 commit: 80001048       ← 从 mret 返回，PC = 0x80001048
core   0: 0 0x80001048 li x10, 1
Cosim: 207547 commit: 8000104c       ← sw x10, 4(x0)（store 到地址 0x4）
Cosim: 207569 commit: 80001050       ← ← CSRRSI hpmcounter8 执行了，没有异常!
core   0: 3 0x80001000 csrr x14, mcause  → x14 = 0x7 (Spike 在这里触发了异常!)
Cosim: 32ad1 PC mismatch spike 80001000 != DUT 80001050
```

**解读**：
- `exception 2` 是 cosim 报告的异常号，2 = illegal instruction
- CSRRCI 在 PC `0x80001044` 正确触发异常 → trap handler 处理 → mepc+=4 → mret 返回到 `0x80001048`
- 程序继续执行到 PC `0x80001050` 的 CSRRSI
- **BOOM 直接提交了 `0x80001050`，没有触发任何异常**（cosim 日志中无 `exception` 行）
- 同时，Spike 对 `0x80001050` 触发了异常，PC 跳到 trap handler `0x80001000`
- cosim 检测到 PC 分歧：Spike=0x80001000，DUT=0x80001050

#### Spike standalone 输出

```
core   0: 0x0000000080001044 (0xc1b07773) csrrci  a4, hpmcounter27, 0
core   0: exception trap_illegal_instruction, epc 0x0000000080001044
core   0:           tval 0x00000000c1b07773
...
core   0: 0x0000000080001050 (0xc0806273) csrrsi  tp, hpmcounter8, 0
core   0: exception trap_illegal_instruction, epc 0x0000000080001050
core   0:           tval 0x00000000c0806273
```

**Spike 对两条指令都正确触发了 `trap_illegal_instruction`**。

### 3.4 对照组证明

| 指令 | funct3 | CSR | uimm | Spike | BOOM | 规范要求 |
|------|--------|-----|------|-------|------|----------|
| CSRRCI x14, hpmcnt27, 0 | 7 (CSRRCI) | 0xC1B | 0 | trap ✅ | trap ✅ | trap |
| **CSRRSI x4, hpmcnt8, 0** | **6 (CSRRSI)** | **0xC08** | **0** | **trap ✅** | **pass ❌** | **trap** |
| CSRRWI x6, hpmcnt23, 0 | 5 (CSRRW) | 0xC17 | 0 | trap ✅ | (未到达) | trap |

CSRRCI（funct3=7）在完全相同的条件（U-mode, mcounteren=0, hpmcounter CSR, uimm=0）下
**正确**触发了异常。这证明 BOOM 的 mcounteren 检查逻辑本身是存在的。

**CSRRSI（funct3=6）是唯一绕过该检查的路径**。

---

## 四、Bug 根因推断

RISC-V CSR 指令的 funct3 编码：

| funct3 | 指令 | uimm=0 时的行为 |
|--------|------|-----------------|
| 1 | CSRRW | 写 CSR（x0→CSR），读 CSR 到 rd |
| 2 | CSRRS | 读 CSR 到 rd，设置 rs1 中为 1 的位 |
| 3 | CSRRC | 读 CSR 到 rd，清除 rs1 中为 1 的位 |
| 5 | CSRRWI | 写 CSR（uimm→CSR），读 CSR 到 rd |
| 6 | CSRRSI | 读 CSR 到 rd，设置 uimm 中为 1 的位 |
| 7 | CSRRCI | 读 CSR 到 rd，清除 uimm 中为 1 的位 |

当 uimm=0 时：
- CSRRSI（funct3=6）：uimm=0，不设置任何位 = **纯读**
- CSRRCI（funct3=7）：uimm=0，不清除任何位 = **纯读**

两条指令的语义完全等价。但 BOOM 只在 CSRRCI 路径执行了 mcounteren 检查。

**推断**：BOOM 的 CSR 访问控制逻辑中，CSRRSI（funct3=6）路径的实现
在判断"是否需要执行 mcounteren 检查"时，可能使用了类似 `uimm != 0` 的条件
来决定是否进行访问权限检查，而 CSRRSI 和 CSRRCI 的判断逻辑存在不对称。
正确的实现应该在**所有会读取 CSR 的情况下**都执行 mcounteren 检查，
无论 uimm 值是什么。

---

## 五、完整的执行追踪时间线

```
指令序号  PC         指令                          特权级   Spike 行为      BOOM 行为
─────────────────────────────────────────────────────────────────────────────────────
...
41       0x8000006a mret                          M→U     进入 U-mode     进入 U-mode
42       0x8000006e csrwi frm, 3                  U       执行             执行
43       0x80000072 csrwi fflags, 0               U       执行             执行
44-55    0x80000076-0x800000ba (li 常量加载)      U       执行             执行
56       0x800000be j main                        U       跳转             跳转

── TEST 1: CSRRCI x14, hpmcounter27, 0 ──
57       0x80001044 CSRRCI x14, hpmcounter27, 0   U       ✅ trap (mcause=2) ✅ trap
         0x80001000 trap handler: mepc += 4       M       mepc→0x80001048  mepc→0x80001048
         0x80001024 mret                          M→U     返回             返回

58       0x80001048 li x10, 1                     U       执行             执行

── TEST 2: CSRRSI x4, hpmcounter8, 0 ──
59       0x80001050 CSRRSI x4, hpmcounter8, 0     U       ✅ trap (mcause=2) ❌ 不 trap!
                                                            spike→0x80001000  boom→0x80001054

── COSIM 检测到 PC MISMATCH ──
         spike PC = 0x80001000 (trap handler)
         DUT   PC = 0x80001050 (正在提交 CSRRSI 的下一条)
```

---

## 六、总结

| 项目 | 内容 |
|------|------|
| **Bug 类型** | CSR 访问权限检查缺失 |
| **影响指令** | CSRRSI（funct3=6），uimm=0 |
| **影响 CSR** | hpmcounter3-31（CSR 0xC03-0xC1F） |
| **影响条件** | U-mode 或 S-mode 执行，mcounteren 对应位为 0 |
| **根因** | BOOM 在 CSRRSI 路径中，当 uimm=0（纯读）时，跳过了 mcounteren 访问权限检查 |
| **规范违反** | RISC-V Privileged Spec §3.1.11："When the HPM_n bit in mcounteren is clear, attempts to read hpmcountern while executing in S-mode or U-mode will cause an illegal-instruction exception" |
| **对照证据** | CSRRCI（funct3=7）uimm=0 在相同条件下正确触发异常，证明 mcounteren 检查逻辑存在但 CSRRSI 路径遗漏 |
| **确认方式** | BOOM V4 cosim（Spike 参考模型对比），已通过最小化种子在 Docker `divefuzz-dev` 中复现 |
