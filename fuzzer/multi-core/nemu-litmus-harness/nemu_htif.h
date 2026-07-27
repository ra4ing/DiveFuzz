#ifndef NEMU_HTIF_H
#define NEMU_HTIF_H

/* NEMU UART16550 MMIO base address (from configs/riscv64-xs_defconfig:180) */
#define NEMU_UART_BASE   0x310b0000UL

/* nemu_trap pseudo-instruction encoding
 * Opcode bits[6:2]=0x1A (11010b), bits[1:0]=11 → full opcode byte = 0x6B
 * Usage: set a0 = exit_code, then execute .word NEMU_TRAP_OPCODE
 * Source: nemu/src/isa/riscv64/instr/decode.c:98
 */
#define NEMU_TRAP_OPCODE 0x0000006b

/* Stack alignment for secondary harts (matches litmus7 expectations) */
#define HTIF_DATA_ALIGN  64

#endif /* NEMU_HTIF_H */
