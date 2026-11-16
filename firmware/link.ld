ENTRY(Reset_Handler)
MEMORY { CODE (rx) : ORIGIN = CODE_BASE, LENGTH = 8K }
SECTIONS {
 .text : { KEEP(*(.isr_vector)) *(.text*) *(.rodata*) } > CODE
 /DISCARD/ : { *(.comment*) *(.ARM.exidx*) *(.ARM.extab*) }
}
