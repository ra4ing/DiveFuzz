# ============================================================================
# BOOM V4 Bug Reproduction Seed: CSRRSI hpmcounter8 U-mode mcounteren=0
#
# Bug: BOOM fails to raise illegal-instruction exception when executing
#   CSRRSI x4, hpmcounter8, 0
# from U-mode while mcounteren=0 (all bits clear).
#
# Per RISC-V Privileged Spec v20240411 Section 3.1.11:
#   "When the HPM_n bit in mcounteren is clear, attempts to read
#    hpmcountern while executing in S-mode or U-mode will cause an
#    illegal-instruction exception."
#
# Control experiment: CSRRCI x14, hpmcounter27, 0 (same uimm=0, pure read)
# does correctly trap on BOOM. Only CSRRSI is broken.
# ============================================================================

.globl _start
.section .text.init
_start:
trap_vec_init:
  la x13, other_exp
  csrw 0x305, x13          # MTVEC = trap handler

mepc_setup:
  la x13, init
  csrw 0x341, x13           # MEPC = init

init_env:
  li x26, 0x0000000a00184020
  csrw 0x300, x26           # MSTATUS (MPP=0 => U-mode after mret)
  li x16, -0x1
  csrw 0x3b0, x16           # pmpaddr0 = all 1s (NAPOT full coverage)
  li x16, 0x1f
  csrw 0x3a0, x16           # pmpcfg0: entry 0 = NAPOT+RWX
  li x16, 0x0
  csrw 0x3a2, x16           # pmpcfg2 = 0
  sfence.vma x0, x0
  li x26, 0x0
  csrw 0x302, x26           # MEDELEG = 0
  csrw 0x303, x26           # MIDELEG = 0
  csrw 0x304, x26           # MIE = 0
  csrw 0x340, x26           # MSCRATCH = 0
  csrw 0x343, x26           # MTVAL = 0
  csrw 0x342, x26           # MCAUSE = 0
  csrw 0x140, x26           # SSCRATCH = 0
  csrw 0x143, x26           # STVAL = 0
  csrw 0x142, x26           # SCAUSE = 0
  csrw 0x141, x26           # SEPC = 0
  # IMPORTANT: mcounteren (0x306) is NOT set, defaults to 0
  # This means U-mode cannot access any hpmcounter registers
  mret

init:
  fsrmi 3
  csrwi fflags, 0
  # Set up some registers
  li x1, 0xba0b9e1ba27837d3
  li x4, 0x999ca46897848696
  li x10, 0xce3a1f1580e4a794
  j main

.align 12
other_exp:
.option norvc
  csrr x14, 0x342           # read mcause
  blt x14, x0, m_handle_interrupt
  csrr x13, 0x341           # read mepc
  addi x13, x13, 4
  csrw 0x341, x13           # mepc += 4 (skip faulting instruction)
  # Store mcause to tohost for diagnostics (address 0x80003000)
  li x15, 0x80003000
  sw x14, 0(x15)
  mret
m_handle_interrupt:
  li x15, 0
  csrw 0x304, x15
  csrr x13, 0x300
  li x15, -9
  and x13, x13, x15
  csrw 0x300, x13
  mret
.option rvc

.align 2
.option norvc
main:
  # Set up base address for debug stores in mem_region (0x80100000)
  li x11, 0x80100000

  # ---- TEST 1: CSRRCI x14, hpmcounter27, 0 (CONTROL) ----
  # CSRRCI with uimm=0 is a pure read. mcounteren=0 so this MUST trap.
  # Both Spike and BOOM correctly trap on this.
  csrrci x14, 0xc1b, 0     # hpmcounter27, uimm=0

  # If we reach here, trap handler skipped the instruction (mepc+=4)
  li x10, 0x1               # test 1 passed (trapped correctly)
  sw x10, 0(x11)            # marker at mem_region[0]

  # ---- TEST 2: CSRRSI x4, hpmcounter8, 0 (BUG TRIGGER) ----
  # CSRRSI with uimm=0 is a pure read. mcounteren=0 so this MUST trap.
  # Spike traps correctly. BOOM does NOT trap => BUG.
  csrrsi x4, 0xc08, 0       # hpmcounter8, uimm=0

  # If BOOM reaches here without trapping, x4 now contains hpmcounter8 value.
  # Spike would never reach here — it trapped into the handler.
  li x10, 0x2               # We should NOT reach here on Spike
  sw x10, 4(x11)            # marker at mem_region[4]

  # ---- TEST 3: CSRRWI x6, hpmcounter23, 0 (additional control) ----
  # CSRRWI writes 0 to hpmcounter23 (read-only), should trap.
  csrrwi x6, 0xc17, 0       # hpmcounter23, uimm=0

  li x10, 0x3               # test 3 passed (trapped correctly)
  sw x10, 8(x11)            # marker at mem_region[8]

  # ---- DONE: write sentinel ----
  li x10, 1
  li x15, 0x80003000
  sw x10, 0(x15)

  # Infinite loop
done:
  j done

.option rvc

.section .tohost
.align 6
.globl tohost
tohost:
  .dword 0

.section .mem_region
.align 12
mem_region:
  .fill 8192, 1, 0

.section .stack_region
.align 12
stack_region:
  .fill 1024, 1, 0