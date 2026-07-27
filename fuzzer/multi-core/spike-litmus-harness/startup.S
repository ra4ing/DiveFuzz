/*
 * startup.S — bare-metal multi-hart entry for spike
 *
 * Hart 0: clears BSS, sets up stack, calls main().
 * Hart N>0: spins waiting for _litmus_fn[hartid] to be set,
 *           calls the function, marks done, then loops again
 *           (to support multiple rounds of litmus runs).
 *
 * Memory layout (see linker.ld):
 *   0x80000000  .text
 *   ...
 *   top-of-RAM  stacks (one STACK_SIZE page per hart)
 */

#include "spike_htif.h"   /* HTIF_DATA_ALIGN — just for stack sizing */

#define STACK_SIZE  4096  /* 4 KiB per hart */

.section .rodata
.Lprog_name:
    .asciz "litmus"

.section .data
.Largv:
    .dword .Lprog_name
    .dword 0            /* NULL terminator */

.section .text.init
.globl _start
_start:
    csrr    a0, mhartid

    beqz    a0, .Lhart0

    /* ---- Secondary harts ---- */
.option push
.option norelax
    la      gp, __global_pointer$
.option pop

    la      sp, _stack_top
    li      t0, STACK_SIZE
    mul     t0, t0, a0
    sub     sp, sp, t0

    mv      s0, a0          /* s0 = hartid (callee-saved) */
    j       .Lsecondary_spin

.Lhart0:
    /* ---- Primary hart (hart 0) ---- */
.option push
.option norelax
    la      gp, __global_pointer$
.option pop

    la      sp, _stack_top

    /* Clear BSS */
    la      a0, _bss_start
    la      a1, _bss_end
.Lbss_loop:
    bgeu    a0, a1, .Lbss_done
    sd      zero, 0(a0)
    addi    a0, a0, 8
    j       .Lbss_loop
.Lbss_done:

    /* Call main(1, {"litmus", NULL}) */
    li      a0, 1
    la      a1, .Largv
    call    main

    call    htif_exit

.Lhart0_spin:
    wfi
    j       .Lhart0_spin

    /* ---- Secondary hart work loop ---- */
.Lsecondary_spin:
    /*
     * Spin until _litmus_slots[hartid] != NULL.
     * The struct layout (see spike_hart.h):
     *   [0] volatile f_t *fn  (8 bytes)
     *   [8] void *arg         (8 bytes)
     *   [16] volatile int done (4 bytes)
     *
     * Array base: _litmus_slots, each slot is 32 bytes (padded).
     *
     * IMPORTANT: use callee-saved s1 for the slot pointer so it
     * survives the fn() call (t1 would be clobbered by the callee).
     */
    la      t0, _litmus_slots
    li      t1, 32              /* sizeof(litmus_slot_t) */
    mul     t1, t1, s0
    add     s1, t0, t1          /* s1 = &_litmus_slots[hartid]  (callee-saved) */

.Lwait_fn:
    /* fence to prevent reordering with store in launch() */
    fence   rw, rw
    ld      t3, 0(s1)           /* fn = slot->fn */
    beqz    t3, .Lwait_fn

    /* Load arg */
    ld      a0, 8(s1)           /* a0 = slot->arg */

    /* Clear fn so we can reuse the slot next round */
    sd      zero, 0(s1)
    fence   rw, rw

    /* Call fn(arg) — s1 is callee-saved and will be preserved across this call */
    jalr    ra, t3, 0

    /* Mark done — s1 still holds &_litmus_slots[hartid] */
    li      t4, 1
    fence   rw, rw
    sw      t4, 16(s1)          /* slot->done = 1 */
    fence   rw, rw

    j       .Lsecondary_spin
