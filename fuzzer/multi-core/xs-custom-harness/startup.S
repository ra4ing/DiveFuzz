# Copyright (c) 2024-2025 Institute of Information Engineering, Chinese Academy of Sciences
#
# DiveFuzz is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#          http://license.coscl.org.cn/MulanPSL2
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
#
# See the Mulan PSL v2 for more details.

#
# 2-hart bare-metal boot. Both harts enter at _start; hart 0 zeroes .bss then
# calls entry(0), hart 1 calls entry(1), harts >= 2 park (defensive: only 2
# cores exist). Per-hart stack = _stack_top - hart*0x10000.
#

.section .text.init
.globl _start
_start:
    csrr a0, mhartid
.option push
.option norelax
    la gp, __global_pointer$
.option pop
    la sp, _stack_top
    li t1, 0x10000
    mul t2, a0, t1
    sub sp, sp, t2
    li t0, 2
    bgeu a0, t0, 2f
    beqz a0, 3f
    j 4f
3:                                  /* hart0: zero .bss */
    la t0, _bss_start
    la t1, _bss_end
1:  bgeu t0, t1, 4f
    sd zero, 0(t0)
    addi t0, t0, 8
    j 1b
4:
    call entry
2:
    wfi
    j 2b
