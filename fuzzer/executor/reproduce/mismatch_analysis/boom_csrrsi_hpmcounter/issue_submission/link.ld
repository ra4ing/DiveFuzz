OUTPUT_ARCH( "riscv" )
ENTRY(_start)

/*
 * Memory Layout:
 *   0x80000000 - 0x800FFFFF : Code and data sections (.text.init, .text, .tohost, .data, .bss)
 *   0x80100000 - 0x80101FFF : Fixed mem_region for store/load testing (8KB)
 *   0x80102000 - 0x801023FF : Fixed stack_region (1KB)
 *
 * NOTE: .text.init is placed first for CVA6 compatibility.
 */

SECTIONS
{
  . = 0x80000000;
  .text : { *(.text.init) *(.text) }
  . = ALIGN(0x1000);
  .tohost : { *(.tohost) }
  . = ALIGN(0x1000);
  .page_table : { *(.page_table) }
  .data : { *(.data) }
  .bss : { *(.bss) }

  /* Place mem_region at fixed absolute address */
  . = 0x80100000;
  .mem_region : { *(.mem_region) }
  . = ALIGN(0x1000);
  .stack_region : { *(.stack_region) }
  _end = .;
}
