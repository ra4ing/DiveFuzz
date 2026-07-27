# Test: Verify Smstateen henvcfg access control
# Hypothesis: XiangShan implements Smstateen with mstateen0.ENVCFG=0 on reset.
#   When mstateen0.ENVCFG=0, accessing henvcfg from S-mode causes Illegal Instruction.
#   Spike (no Smstateen) does NOT enforce this, causing difftest mismatch.
#
# Expected:
#   XiangShan: traps to M-mode (Illegal Instruction, cause=2) on csrrwi s8, henvcfg, 29
#   Spike:     executes successfully in S-mode

.globl _start
.section .text
_start:
  # Set up misa
  li x13, 0x800000000084112d
  csrw 0x301, x13

trap_vec_init:
  la x13, other_exp
  csrw 0x305, x13    # MTVEC

  la x13, other_exp_s
  csrw 0x105, x13    # STVEC

mepc_setup:
  la x13, init
  csrw 0x341, x13    # MEPC

init_env:
  # MSTATUS: MPP=01 (S-mode), set FS=01
  li x26, 0x00000029006cccc2
  csrw 0x300, x26

  # PMP: full access
  li x16, -0x1
  csrw 0x3b0, x16     # pmpaddr0
  li x16, 0x1f
  csrw 0x3a0, x16     # pmpcfg0
  li x16, 0x0
  csrw 0x3a2, x16     # pmpcfg2

  sfence.vma x0, x0

  # No delegation
  li x26, 0x0
  csrw 0x302, x26     # MEDELEG
  csrw 0x303, x26     # MIDELEG
  csrw 0x304, x26     # MIE
  csrw 0x340, x26     # MSCRATCH
  csrw 0x343, x26     # MTVAL
  csrw 0x342, x26     # MCAUSE
  csrw 0x140, x26     # SSCRATCH
  csrw 0x143, x26     # STVAL
  csrw 0x142, x26     # SCAUSE
  csrw 0x141, x26     # SEPC

  # KEY: mstateen0 is NOT written → stays at reset value (0)
  # mstateen0.ENVCFG = 0 → henvcfg access from S-mode is ILLEGAL per Smstateen

  mret                 # drop to S-mode at 'init'

init:
  fsrmi 4              # enable FPU

  # === TEST: csrrwi s8, henvcfg, 29 ===
  # This should:
  #   XiangShan: raise Illegal Instruction (cause=2) due to mstateen0.ENVCFG=0
  #   Spike:     execute successfully (no Smstateen enforcement)
  csrrwi s8, henvcfg, 29

  # If we get here, henvcfg access succeeded (Spike behavior)
  # After henvcfg access, just exit cleanly
  li x10, 0
  ecall

.align 4
other_exp:
.option norvc
  # M-mode trap handler: skip the faulting instruction
  csrr x13, 0x341     # MEPC
  addi x13, x13, 4
  csrw 0x341, x13
  mret
.option rvc

other_exp_s:
.option norvc
  csrr x13, 0x141     # SEPC
  addi x13, x13, 4
  csrw 0x141, x13
  sret
.option rvc
