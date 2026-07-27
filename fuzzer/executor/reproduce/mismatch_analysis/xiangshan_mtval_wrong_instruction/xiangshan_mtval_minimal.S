.globl _start
.section .text

# 最小复现说明：
# - 该文件不是原始 seed；它只保留能稳定触发 mtval mismatch 的初始化和指令窗口。
# - 缩减时验证过：删除 S-mode trap、mem_region、通用寄存器/浮点寄存器初始化、
#   fcsr 初始化、MEDELEG/MIDELEG/MIE 清零等后仍可复现。
# - 但删除 mstatus/PMP 初始化，或删除 main 中 rem/subw/rolw/csrrs s3/beq 指令，
#   当前 XiangShan+difftest 环境不再复现。因此这些内容保留。

_start:
  # 允许本用例使用 G/C/V/Z* 等扩展配置。该值来自原 seed 的 misa 初始化；
  # 删除后会改变 illegal-instruction 行为，不适合作为同一复现。
  li x13, 0x800000000084112d
  csrw 0x301, x13 # MISA

  # 所有 illegal-instruction trap 都回到同一个 M-mode handler。
  # handler 只做一件事：mepc += 4 后 mret，让程序继续进入后续指令窗口。
  la x13, other_exp
  csrw 0x305, x13 # MTVEC

  # 从 main 开始执行；不再保留原 seed 的 init 跳转层。
  la x13, main
  csrw 0x341, x13 # MEPC

  # mstatus/PMP 是当前复现必要条件：删除任一组后 DUT 不再触发该 mismatch。
  li x26, 0x000000a900362240
  csrw 0x300, x26 # MSTATUS
  li x16, -0x1
  csrw 0x3b0, x16 # PMPADDR0: NAPOT full coverage
  li x16, 0x1f
  csrw 0x3a0, x16 # PMPCFG0: RWX NAPOT
  mret

# trap handler 放到 0x80001000，main 放到 0x80001010。
# 该布局来自缩减后的稳定复现：faulting instruction 位于 0x8000101c，
# XiangShan 错误写入 faulting PC+8 的指令编码 0xc02cf5d3。
.align 12
other_exp:
.option norvc
  csrr x13, 0x341 # MEPC
  addi x13, x13, 4
  csrw 0x341, x13 # MEPC
  mret
.option rvc

.align 2
.option norvc
main:
  # 第一次 illegal trap：制造与原始触发场景一致的前置异常/恢复窗口。
  fmv.x.d s2, fs7

  # 删除 rem/subw/rolw/csrrs s3 中任一条后，当前缩减用例不再复现。
  # 因此这些指令不是业务逻辑，而是触发 XiangShan 错误 mtval 取值的最小窗口。
  rem s7, s2, t1
  subw s1, t1, t4

  # 第二次 illegal trap，本次应报告的 faulting instruction encoding 是 0x002026f3。
  # Spike/ref 的 mtval = 0x00000000002026f3。
  csrrs a3, frm, zero

  rolw t2, s1, t2

  # PC+8 canary。XiangShan/DUT 错把该后续指令编码写入 mtval：0xc02cf5d3。
  fcvt.l.s a1, fs9, dyn

  csrrs s3, frm, zero

  # 该分支本身在 mismatch 前不会成为 architectural 证据，
  # 但删除它会破坏当前复现的取指/流水窗口，故保留原立即数形式。
  beq s11, zero, . + 28
.option rvc

write_tohost:
  la t1, tohost
  li t2, 0x1
  sw t2, 0(t1)
_exit:
  j _exit

.section .data
.align 6
.global tohost
tohost:
.dword 0x0
.align 6
.global fromhost
fromhost:
.dword 0x0
