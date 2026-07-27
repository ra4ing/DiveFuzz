# Makefile — NEMU bare-metal litmus test harness
#
# Usage:
#   make LITMUS=path/to/test.litmus        # generate, compile, run
#   make run   LITMUS=path/to/test.litmus  # same as above
#   make build-nemu                        # build NEMU (one-time setup)
#   make clean

# ---- Tool paths ---- #
GCC         ?= riscv64-unknown-elf-gcc
GCC_INCLUDE ?= /usr/lib/gcc/riscv64-unknown-elf/13.2.0/include
LIBGCC      ?= /usr/lib/gcc/riscv64-unknown-elf/13.2.0/libgcc.a
LIBGCC_EH   ?=
LITMUS7     ?= /home/ra4ing/.opam/default/bin/litmus7
LITMUS7_SHARE ?= /home/ra4ing/.opam/default/share/herdtools7/litmus
PICOLIBC    ?= /usr/lib/picolibc/riscv64-unknown-elf

NEMU_HOME   ?= $(abspath $(dir $(abspath $(lastword $(MAKEFILE_LIST))))/../nemu)
NEMU_CONFIG ?= riscv64-xs_defconfig
NEMU        ?= $(NEMU_HOME)/build/nemu-interpreter

# ---- Test configuration ---- #
LITMUS      ?=
AVAIL       ?= 2

# ---- Derived paths ---- #
HARNESS_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
LITMUS_NAME := $(basename $(notdir $(LITMUS)))
BUILD_DIR   := build/$(LITMUS_NAME)
GEN_DIR     := $(BUILD_DIR)/gen
ELF         := $(BUILD_DIR)/$(LITMUS_NAME).elf
BIN         := $(BUILD_DIR)/$(LITMUS_NAME).bin

NRUNS       ?= 2
SIZE        ?= 20

# ---- Compiler flags ---- #
CFLAGS := \
    -O2 -g \
    -march=rv64gc \
    -mabi=lp64d \
    -mcmodel=medany \
    -static \
    -ffreestanding \
    -fno-PIE \
    -nostartfiles \
    -nostdinc \
    -DAVAIL=$(AVAIL) \
    -DCPUS_DEFINED \
    -DFORCE_AFFINITY \
    -include $(HARNESS_DIR)/mbar.h \
    -include $(HARNESS_DIR)/harness_barrier.h \
    -I$(HARNESS_DIR) \
    -I$(GEN_DIR) \
    -isystem $(GCC_INCLUDE) \
    -I$(PICOLIBC)/include

LDFLAGS := \
    -T $(HARNESS_DIR)/linker.ld \
    -static \
    -nostdlib \
    -nodefaultlibs \
    -Wl,--allow-multiple-definition \
    -Wl,--start-group \
    -L$(PICOLIBC)/lib \
    -lc \
    -ldummyhost \
    $(LIBGCC) \
    -Wl,--end-group

# ---- Source files ---- #
GEN_SRCS := $(GEN_DIR)/$(LITMUS_NAME).c \
            $(GEN_DIR)/utils.c \
            $(GEN_DIR)/litmus_io.c \
            $(GEN_DIR)/platform_io.c \
            $(GEN_DIR)/litmus_rand.c

HARNESS_SRCS := \
    $(HARNESS_DIR)/nemu_hart.c \
    $(HARNESS_DIR)/harness_barrier.c \
    $(HARNESS_DIR)/syscalls.c \
    $(HARNESS_DIR)/affinity_stub.c

HARNESS_ASM := $(HARNESS_DIR)/startup.S \
               $(HARNESS_DIR)/fiber.S

ALL_SRCS := $(HARNESS_ASM) $(HARNESS_SRCS) $(GEN_SRCS)

# ---- NEMU invocation ---- #
NEMU_HARTS := $(shell echo $$(($(AVAIL)+1)))

.PHONY: all run clean generate compile build-nemu

all: run

run: compile
	@echo "=== Running $(LITMUS_NAME) on NEMU ($(NEMU_HARTS) harts: 1 main + $(AVAIL) workers) ==="
	$(NEMU) -b $(BIN)

compile: generate $(GEN_DIR)/$(LITMUS_NAME).h $(ELF) $(BIN)

# ---- Build NEMU (one-time) ---- #
build-nemu:
	$(MAKE) -C $(NEMU_HOME) NEMU_HOME=$(NEMU_HOME) $(NEMU_CONFIG)
	$(MAKE) -C $(NEMU_HOME) NEMU_HOME=$(NEMU_HOME)

# ---- Generate C from .litmus ---- #
generate: $(GEN_DIR)/.generated

$(GEN_DIR)/.generated: $(LITMUS)
	@mkdir -p $(GEN_DIR)
	@echo "=== Generating C from $(LITMUS) ==="
	cd $(dir $(LITMUS)) && \
	    $(LITMUS7) -mach riscv -mode presi -stdio false \
	    -avail $(AVAIL) -o $(abspath $(GEN_DIR)) $(abspath $(LITMUS))
	cp $(HARNESS_DIR)/affinity.h $(GEN_DIR)/affinity.h
	cp $(LITMUS7_SHARE)/_toh_nostdio.sh $(GEN_DIR)/toh.sh
	sed -i 's/^#define NUMBER_OF_RUN .*/#define NUMBER_OF_RUN $(NRUNS)/' $(GEN_DIR)/$(LITMUS_NAME).c
	sed -i 's/^#define SIZE_OF_TEST .*/#define SIZE_OF_TEST $(SIZE)/' $(GEN_DIR)/$(LITMUS_NAME).c
	@touch $@

# ---- Generate <test>.h ---- #
$(GEN_DIR)/$(LITMUS_NAME).h: $(GEN_DIR)/.generated
	@echo "=== Generating $(LITMUS_NAME).h from assembly ==="
	$(GCC) $(CFLAGS) -DASS -S -o $(GEN_DIR)/$(LITMUS_NAME).s $(GEN_DIR)/$(LITMUS_NAME).c
	awk -f $(GEN_DIR)/show.awk $(GEN_DIR)/$(LITMUS_NAME).s > $(GEN_DIR)/$(LITMUS_NAME).t
	sh $(GEN_DIR)/toh.sh $(GEN_DIR)/$(LITMUS_NAME).t > $@

# ---- Compile + Link ---- #
$(ELF): $(GEN_DIR)/.generated $(GEN_DIR)/$(LITMUS_NAME).h $(ALL_SRCS) $(HARNESS_DIR)/linker.ld
	@mkdir -p $(dir $@)
	@echo "=== Compiling $(LITMUS_NAME) ==="
	$(GCC) $(CFLAGS) \
	    $(ALL_SRCS) \
	    $(LDFLAGS) \
	    -o $@
	@echo "=== ELF ready: $@ ==="

# ---- Convert ELF to flat binary for NEMU ---- #
$(BIN): $(ELF)
	riscv64-unknown-elf-objcopy -O binary $< $@
	@echo "=== BIN ready: $@ ==="

clean:
	rm -rf build/
