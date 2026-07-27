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

# Makefile — 2-hart bare-metal custom litmus harness (no litmus7 generation).
#
# Compiles startup.S + runtime.c + syscalls.c + gen/seed.S into a single ELF.
# CFLAGS/LDFLAGS mirror the proven spike-litmus-harness toolchain. The backend
# passes BUILD=<abs> per seed so concurrent seeds do not collide.
#
#   make compile BUILD=<abs> NRUNS=<N> GEN_DIR is derived under BUILD/gen.

# ---- Tool paths ---- #
GCC        ?= riscv64-linux-gnu-gcc
GCC_INCLUDE ?= /usr/lib/gcc-cross/riscv64-linux-gnu/13/include
NEWLIB_SYSROOT ?= /home/ra4ing/workspace/riscv/riscv64-unknown-elf
LIBGCC     ?= /usr/lib/gcc-cross/riscv64-linux-gnu/13/libgcc.a
LIBGCC_EH  ?= /usr/lib/gcc-cross/riscv64-linux-gnu/13/libgcc_eh.a

# ---- Build configuration ---- #
NRUNS      ?= 2
BUILD      ?= build
GEN_DIR    := $(BUILD)/gen
ELF        := $(BUILD)/seed.elf

# ---- Derived paths ---- #
HARNESS_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

# ---- Compiler flags (mirror spike-litmus-harness/Makefile:43-60) ---- #
CFLAGS := -O2 -g -march=rv64gc -mabi=lp64d -mcmodel=medany -static -ffreestanding \
  -fno-PIE -nostartfiles -nostdinc -include $(HARNESS_DIR)/mbar.h \
  -DNUMBER_OF_RUN=$(NRUNS) -I$(HARNESS_DIR) -I$(GEN_DIR) \
  -isystem $(GCC_INCLUDE) -I$(NEWLIB_SYSROOT)/include

# ---- Linker flags (mirror spike-litmus-harness/Makefile:62-73, minus
#      --allow-multiple-definition: no symbol conflicts without litmus7) ---- #
LDFLAGS := -T $(HARNESS_DIR)/linker.ld -static -nostdlib -nodefaultlibs \
  -Wl,--start-group -L$(NEWLIB_SYSROOT)/lib -lc $(LIBGCC) $(LIBGCC_EH) \
  -Wl,--end-group

# ---- Sources ---- #
ALL_SRCS := $(HARNESS_DIR)/startup.S $(HARNESS_DIR)/runtime.c \
            $(HARNESS_DIR)/syscalls.c $(GEN_DIR)/seed.S

# ---- Targets ---- #
.PHONY: compile clean

compile: $(ELF)

$(ELF): $(ALL_SRCS) $(HARNESS_DIR)/linker.ld $(GEN_DIR)/seed_meta.h
	@mkdir -p $(BUILD)
	$(GCC) $(CFLAGS) $(ALL_SRCS) $(LDFLAGS) -o $@

clean:
	rm -rf $(BUILD)
