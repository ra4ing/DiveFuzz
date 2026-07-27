/* Copyright (c) 2024-2025 Institute of Information Engineering, Chinese Academy of Sciences
 *
 * DiveFuzz is licensed under Mulan PSL v2.
 * You can use this software according to the terms and conditions of the Mulan PSL v2.
 * You may obtain a copy of Mulan PSL v2 at:
 *          http://license.coscl.org.cn/MulanPSL2
 *
 * THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
 * EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO,
 * MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
 *
 * See the Mulan PSL v2 for more details.
 *
 * Byte-for-byte copy of spike-litmus-harness/linker.ld: RAM 0x80000000/128M,
 * .tohost section with tohost/fromhost, _bss_start/_bss_end,
 * _stack_top = 0x87FFF000.
 */
OUTPUT_ARCH(riscv)
ENTRY(_start)

MEMORY {
    RAM (rwx) : ORIGIN = 0x80000000, LENGTH = 128M
}

SECTIONS {
    . = 0x80000000;

    .text : {
        *(.text.init)
        *(.text*)
        *(.rodata*)
    } > RAM

    .tohost ALIGN(64) : {
        PROVIDE(tohost   = .); LONG(0); LONG(0);
        PROVIDE(fromhost = .); LONG(0); LONG(0);
    } > RAM

    .data ALIGN(8) : {
        PROVIDE(__global_pointer$ = . + 0x800);
        *(.data*)
        *(.sdata*)
    } > RAM

    .bss ALIGN(8) : {
        PROVIDE(_bss_start = .);
        *(.bss*)
        *(.sbss*)
        *(COMMON)
        PROVIDE(_bss_end = .);
    } > RAM

    .heap ALIGN(8) : {
        PROVIDE(_heap_start = .);
        . += 8M;
        PROVIDE(_heap_end = .);
    } > RAM

    PROVIDE(_stack_top = ORIGIN(RAM) + LENGTH(RAM) - 0x1000);

    /DISCARD/ : { *(.eh_frame) *(.rela*) *(.comment) }
}
