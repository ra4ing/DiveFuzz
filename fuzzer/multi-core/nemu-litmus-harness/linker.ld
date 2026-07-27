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
        PROVIDE(__heap_start = .);
        . += 8M;
        PROVIDE(_heap_end = .);
        PROVIDE(__heap_end = .);
    } > RAM

    PROVIDE(_stack_top = ORIGIN(RAM) + LENGTH(RAM) - 0x1000);

    /DISCARD/ : { *(.eh_frame) *(.rela*) *(.comment) }
}
