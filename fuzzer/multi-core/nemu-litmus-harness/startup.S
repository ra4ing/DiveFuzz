/*
 * startup.S — bare-metal multi-hart entry for NEMU
 *
 * Hart 0: clears BSS, sets up stack, calls main().
 * Hart N>0: spins waiting for _litmus_slots[hartid].fn to be set,
 *           calls the function, marks done, then loops again.
 */

#include "nemu_htif.h"

#define STACK_SIZE  4096

.section .rodata
.Lprog_name:
    .asciz "litmus"

.section .data
.Largv:
    .dword .Lprog_name
    .dword 0

.section .text.init
.globl _start
_start:
    csrr    a0, mhartid

    beqz    a0, .Lhart0

.option push
.option norelax
    la      gp, __global_pointer$
.option pop

    la      sp, _stack_top
    li      t0, STACK_SIZE
    mul     t0, t0, a0
    sub     sp, sp, t0

    mv      s0, a0
    j       .Lsecondary_spin

.Lhart0:
.option push
.option norelax
    la      gp, __global_pointer$
.option pop

    la      sp, _stack_top

    la      a0, _bss_start
    la      a1, _bss_end
.Lbss_loop:
    bgeu    a0, a1, .Lbss_done
    sd      zero, 0(a0)
    addi    a0, a0, 8
    j       .Lbss_loop
.Lbss_done:

    li      a0, 1
    la      a1, .Largv
    call    main

    mv      s2, a0
    li      a0, 0
    call    fflush
    mv      a0, s2

    call    nemu_exit

.Lhart0_spin:
    wfi
    j       .Lhart0_spin

.Lsecondary_spin:
    la      t0, _litmus_slots
    li      t1, 32
    mul     t1, t1, s0
    add     s1, t0, t1

.Lwait_fn:
    fence   rw, rw
    ld      t3, 0(s1)
    beqz    t3, .Lwait_fn

    ld      a0, 8(s1)
    sd      zero, 0(s1)
    fence   rw, rw

    jalr    ra, t3, 0

    li      t4, 1
    fence   rw, rw
    sw      t4, 16(s1)
    fence   rw, rw

    j       .Lsecondary_spin
