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
 * Copy of spike-litmus-harness/mbar.h: defines mbar() = fence rw,rw.
 * Included via -include in CFLAGS so all C sees mbar().
 */
#ifndef MBAR_H
#define MBAR_H

#ifndef __ASSEMBLER__
inline static void mbar(void) {
    __asm__ __volatile__("fence rw,rw" ::: "memory");
}
#endif

#endif
