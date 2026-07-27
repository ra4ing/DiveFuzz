# XiangShan illegal-instruction `mtval` 错误最小复现

## 结论

这是 **XiangShan DUT 的真实 bug**，不是 DiveFuzz 生成器假阳性，也不是直接拿原始 seed 重跑得到的偶然现象。

当前目录中的最小复现工件：

- `xiangshan_mtval_minimal.S`：带注释的最小复现源码；
- `xiangshan_mtval_minimal.elf`：由最小源码重新编译得到；
- `xiangshan_mtval_minimal.img`：DUT 输入镜像；
- `xiangshan_mtval_minimal_rerun_dut.log`：用当前最小镜像重新运行 XiangShan+difftest 得到的日志。

原始 seed 约 1489 行；当前复现源码只保留约 54 行有效汇编代码，并在源码中保留中文注释解释每段为什么存在。

## 复现命令

```bash
docker exec divefuzz-dev bash -c '
cd /home/ra4ing/workspace/riscv/DiveFuzz/dut/XiangShan &&
./build/emu -b 0 -e 0 \
  -i /home/ra4ing/workspace/riscv/DiveFuzz/fuzzer/executor/reproduce/mismatch_analysis/xiangshan_mtval_wrong_instruction/xiangshan_mtval_minimal.img \
  --diff /home/ra4ing/workspace/riscv/DiveFuzz/dut/XiangShan/ready-to-run/riscv64-spike-so
'
```

实测结果：`exit code = 1`，difftest 报告：

```text
mtval different at pc = 0x0080001014, right = 0x00000000002026f3, wrong = 0x00000000c02cf5d3
```

## 最小复现中的关键指令窗口

`xiangshan_mtval_minimal.S` 中的核心窗口：

```asm
main:
  fmv.x.d s2, fs7          # 前置 illegal-instruction trap
  rem s7, s2, t1
  subw s1, t1, t4
  csrrs a3, frm, zero      # 本次 mismatch 的 faulting instruction
  rolw t2, s1, t2
  fcvt.l.s a1, fs9, dyn    # PC+8 canary；XiangShan 错误报告成 mtval
  csrrs s3, frm, zero
  beq s11, zero, . + 28
```

编译后关键地址和指令编码：

| 地址 | 编码 | 指令 | 作用 |
|---|---:|---|---|
| `0x80001010` | `0xe20b8953` | `fmv.x.d s2, fs7` | 前置 illegal-instruction trap |
| `0x80001014` | `0x02696bb3` | `rem s7, s2, t1` | trap 返回后的合法指令 |
| `0x80001018` | `0x41d304bb` | `subw s1, t1, t4` | trap 返回后的合法指令 |
| `0x8000101c` | `0x002026f3` | `csrrs a3, frm, zero` | 本次 mismatch 的 faulting instruction |
| `0x80001020` | `0x607493bb` | `rolw t2, s1, t2` | PC+4 指令 |
| `0x80001024` | `0xc02cf5d3` | `fcvt.l.s a1, fs9, dyn` | PC+8 canary，被 XiangShan 错写进 `mtval` |
| `0x80001028` | `0x002029f3` | `csrrs s3, frm, zero` | 保持当前触发窗口 |
| `0x8000102c` | `0x000d8e63` | `beq s11, zero, . + 28` | 保持当前取指/流水窗口 |

## 复现日志证据

来自 `xiangshan_mtval_minimal_rerun_dut.log`：

```text
[20] exception pc 0000000080001010 inst e20b8953 cause 0000000000000002 fmv.x.d s2, fs7
...
[25] commit pc 0000000080001014 inst 02696bb3 wen 1 dst 23 data 0000000000000000 idx 018 rem     s7, s2, t1
[26] exception pc 000000008000101c inst 002026f3 cause 0000000000000002 csrr    a3, frm <--
...
mtval: 0x00000000002026f3
...
mtval different at pc = 0x0080001014, right = 0x00000000002026f3, wrong = 0x00000000c02cf5d3
```

解释：

- `right = 0x00000000002026f3` 是 difftest 参考模型 Spike 的 `mtval`；
- `wrong = 0x00000000c02cf5d3` 是 XiangShan DUT 的 `mtval`；
- faulting instruction 位于 `mepc = 0x8000101c`，编码是 `0x002026f3`；
- DUT 却把 `0x80001024` 处的 PC+8 canary 指令编码 `0xc02cf5d3` 写入了 `mtval`。

## 镜像字节验证

对 `xiangshan_mtval_minimal.img` 直接读取字节，确认：

```text
0x8000101c: 0x002026f3   # faulting instruction: csrrs a3, frm, zero
0x80001024: 0xc02cf5d3   # PC+8 canary: fcvt.l.s a1, fs9, dyn
```

因此 DUT 的 `wrong mtval = 0xc02cf5d3` 不是随机值，而是来自 faulting PC 之后 8 字节处的后续指令。

## RISC-V 手册依据（已在线验证）

在线来源：RISC-V Privileged Architecture Manual, §3.1.16 Machine Trap Value (`mtval`) Register

URL：<https://riscv.github.io/riscv-isa-manual/snapshot/privileged/#machine-trap-value-mtval-register>

手册原文关键段落：

> The `mtval` register can optionally also be used to return the faulting instruction bits on an illegal-instruction exception (`mepc` points to the faulting instruction in memory). If `mtval` is written with a nonzero value when an illegal-instruction exception occurs, then `mtval` will contain the shortest of:
>
> * the actual faulting instruction
> * the first ILEN bits of the faulting instruction
> * the first MXLEN bits of the faulting instruction
>
> The value loaded into `mtval` on an illegal-instruction exception is right-justified and all unused upper bits are cleared to zero.

规范含义：

1. illegal-instruction 异常时，`mtval` 可以为 0；
2. 但如果实现选择写入非零 `mtval`，该值必须是 faulting instruction 的指令编码；
3. 该编码需要右对齐，未使用高位清零。

本复现中：

- faulting instruction：`0x002026f3`；
- Spike/ref `mtval`：`0x00000000002026f3`，符合规范；
- XiangShan/DUT `mtval`：`0x00000000c02cf5d3`，非零但不是 faulting instruction，违反规范。


## 为什么是真实 bug

| 判断项 | 结论 |
|---|---|
| 是否可由独立最小复现触发 | 是，当前 `xiangshan_mtval_minimal.img` 重新运行后稳定触发 |
| 是否仍依赖原始大 seed | 否，原始 seed 已缩减为独立最小复现程序 |
| 是否为 reference/Spike 错误 | 否，Spike/ref 的 `mtval` 等于 faulting instruction 编码 |
| 是否为生成器假阳性 | 否，DUT 与 ref 的 architectural state 出现真实不一致 |
| 是否违反 RISC-V 规范 | 是，DUT 写入了错误的非零 `mtval` |

## 触发该 bug 的指令组合

当前最小复现中，触发 bug 的不是某一条指令，而是下面这组指令形成的时序关系：

```asm
fmv.x.d s2, fs7          # A：前置 illegal trap，建立 trap 返回后的流水窗口
rem s7, s2, t1           # B：trap 返回后第一条提交指令
subw s1, t1, t4          # C：继续推进 older CSR 指令前的窗口
csrrs a3, frm, zero      # D：真正发生 mismatch 的 older illegal CSR 指令
rolw t2, s1, t2          # E：D 后面的普通 younger 指令
fcvt.l.s a1, fs9, dyn    # F：PC+8 younger FP 指令，编码被错误写入 mtval
csrrs s3, frm, zero      # G：保持 decode/CSR illegal sideband 竞争窗口
beq s11, zero, . + 28    # H：保持取指/流水窗口
```

各自作用：

| 标记 | 指令 | 作用 |
|---|---|---|
| A | `fmv.x.d s2, fs7` | 先触发一次 illegal-instruction trap，再由 handler `mepc += 4` 返回；没有这个前置 trap，后面的极短程序不复现。 |
| B/C | `rem`、`subw` | 让 trap 返回后进入一个稳定的提交/解码时序；删除任一条，当前最小用例不再稳定触发。 |
| D | `csrrs a3, frm, zero` | 真正的 faulting instruction。由于当前 `mstatus.FS` 为 Off，访问 FP CSR `frm` 在 CSR permit 路径产生 `EX_II`。规范上非零 `mtval` 应等于 `0x002026f3`。 |
| E | `rolw t2, s1, t2` | D 和 F 之间的 PC+4 指令，维持当前错误窗口。 |
| F | `fcvt.l.s a1, fs9, dyn` | younger FP 指令，位于 D 的 PC+8。由于 FS/frm 状态，它可在 decode 阶段被提前标成 illegal，并进入 `TrapInstMod`；最终 XiangShan 错把它的编码 `0xc02cf5d3` 写进 D 的 `mtval`。 |
| G | `csrrs s3, frm, zero` | 后续 CSR illegal 指令，维持 `TrapInstMod`/CSR FU 的 pending illegal 指令竞争。 |
| H | `beq s11, zero, . + 28` | 分支本身不是 architectural mismatch 的直接证据，但删除会改变取指/flush 窗口，导致当前最小复现失效。 |

因此可以把触发条件概括为：

> 前置 illegal trap 返回后，一个 older CSR illegal instruction（D）在 CSR FU 中产生 trap；同时较年轻的 FP illegal instruction（F）已经通过 decode-side illegal 路径进入 `TrapInstMod`。trap entry 写 `mtval` 时消费了 F 的 stale/younger instruction bits，而不是 D 的 actual faulting instruction bits。

## RTL 机制分析

该问题的核心不是 `csrrs a3, frm, zero` 单条 CSR 指令本身，而是 XiangShan 给 illegal-instruction trap 填写 `mtval` 时，使用了一个与实际 trap 指令解耦的“待报告非法指令”旁路寄存器。

相关路径如下：

1. `TrapEntryMEvent` 对 illegal-instruction exception 写 `mtval` 时，从 `in.trapInst` 取指令编码：

   - `dut/XiangShan/src/main/scala/xiangshan/backend/fu/NewCSR/CSREvents/TrapEntryMEvent.scala:69` 判断 `EX_II/EX_VI`；
   - `TrapEntryMEvent.scala:85-90` 选择 `trapInst` 作为 `tval`；
   - `TrapEntryMEvent.scala:122` 把该值写入 `out.mtval.bits.ALL`。

2. `NewCSR` 并没有用 ROB trap entry 自带的 `instr` 来写 `mtval`，而是把外部 `io.trapInst` 传给 trap-entry event：

   - `dut/XiangShan/src/main/scala/xiangshan/backend/fu/NewCSR/NewCSR.scala:800-803`：`in.trapInst := io.trapInst`。

3. `io.trapInst` 在 CSR wrapper 中来自 `TrapInstMod.currentTrapInst`：

   - `dut/XiangShan/src/main/scala/xiangshan/backend/fu/wrapper/CSR.scala:119`：`csrMod.io.trapInst := trapInstMod.io.currentTrapInst`。

4. `TrapInstMod` 是单项寄存器队列，来源有两个：

   - decode 阶段提前发现的 illegal instruction：`DecodeStage.scala:130-139` 选择 decode 输出中的 illegal 指令，`DecodeStage.scala:301-302` 输出 `trapInstInfo`；
   - CSR FU 执行时发现的 illegal CSR access：`CSR.scala:189-193` 通过 `faultCsrUop` 送入 `TrapInstMod`，`TrapInstMod.scala:47-59` 重建 CSR 指令编码。

本复现正好击中这两个来源的竞争窗口：

- faulting instruction 是 `0x8000101c: 0x002026f3`，即 `csrrs a3, frm, zero`；
- 该 CSR access 的 illegal 原因在 CSR permit 路径中产生：`CSRPermitModule.scala:210` 识别 `frm` 属于 FP CSR，`CSRPermitModule.scala:217-220` 在 FS off 时令 FP CSR access 非法，`CSRPermitModule.scala:296` 产生 `EX_II`；
- 较年轻的 `0x80001024: 0xc02cf5d3` 是 FP 指令，decode 阶段可因 FS/frm 状态提前标记为 illegal：`DecodeUnit.scala:902-912`，再经 `DecodeStage.scala:301-302` 进入 `TrapInstMod`；
- 当旧的 decode-side illegal 指令已经存在于 `TrapInstMod` 时，`currentTrapInst` 只是寄存器当前值：`TrapInstMod.scala:96-97`，没有对同周期的 `faultCsrUop` 做组合旁路；
- 因此 CSR 指令自己触发 trap 的那个周期，`TrapEntryMEvent` 看到的仍可能是已经缓存的较年轻 FP 指令 `0xc02cf5d3`，而不是本次 trap 的 CSR 指令 `0x002026f3`。

这也解释了为什么最小复现必须保留前置 illegal trap、`rem/subw/rolw`、PC+8 canary 和后续分支：它们共同制造了 decode-side illegal 指令进入 `TrapInstMod`、而 older CSR illegal trap 随后消费 stale `currentTrapInst` 的时序窗口。

需要注意的是，difftest 日志中的 exception instruction 本身是正确的：

- `NewCSR.scala:1538` 使用 `io.fromRob.trap.bits.instr` 输出 `exceptionInst`；
- 日志也显示 `exception pc 0x8000101c inst 0x002026f3`。

错误发生在 `mtval` 写入路径，而不是 exception PC/instruction 的 ROB 信息路径。`diffCSRState.mtval` 直接来自 CSR 寄存器读值：`NewCSR.scala:1553`，所以这更像是 CSR trap-entry 写入源选择错误，而不是日志打印把指令显示错了。

## 修复方向

推荐修复原则：illegal-instruction trap 的 `mtval` 必须绑定到 **实际产生 trap 的 ROB entry**，不能依赖一个全局单项 pending illegal-instruction sideband。

可选修复方向：

1. 在 illegal-instruction trap entry 中直接使用 `io.fromRob.trap.bits.instr` 作为 `mtval` 的 instruction bits；
2. 或者在 `TrapInstMod.currentTrapInst` 对同周期 `faultCsrUop` 增加组合旁路，使 CSR FU 当周期发现的 illegal CSR instruction 优先于已有 decode-side pending instruction；
3. 同时给 `TrapInstMod` 增加与 trap ROB/FTQ offset 的一致性约束，避免较年轻 decode-side illegal 指令被 older trap 消费。

优先建议第 1 种：ROB trap payload 已经能在日志中给出正确 `exceptionInst = 0x002026f3`，让 `mtval` 和实际 trap entry 使用同一来源，能从根上避免跨阶段 sideband stale/younger 覆盖。
