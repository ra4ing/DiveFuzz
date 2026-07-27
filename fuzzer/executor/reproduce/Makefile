# ============================================================================
# Bug Reproduction Makefile for BOOM V4 CSRRSI hpmcounter Bug
# ============================================================================
#
# Prerequisites:
#   - riscv64-unknown-elf-{as,ld,objcopy} in PATH
#   - BOOM Verilator simulator built with cosim support
#   - (optional) Spike RISC-V ISA Simulator in PATH or $spike env var
#
# Quick start:
#   make reproduce             # Full pipeline: compile + run DUT + analyze
#   make reproduce-yaml        # Use existing boom_fuzz.yaml for DUT config
#   make compile               # Just compile the assembly seed
#   make spike                 # Run standalone Spike only
#   make analyze-log           # Analyze an existing DUT log file
#   make clean
#
# ============================================================================

PYTHON ?= python3
REPRODUCE_DIR := $(dir $(lastword $(MAKEFILE_LIST)))
SCRIPT := $(REPRODUCE_DIR)reproduce_bug.py
ASM := $(REPRODUCE_DIR)mismatch_analysis/bug_csrrsi_hpmcounter/bug_csrrsi_hpmcounter.S
OUTPUT := $(REPRODUCE_DIR)output

# Default DUT config - override these or use --config
DUT_CMD ?= ""
DUT_CWD ?= ""
YAML_CONFIG ?= ../../boom_fuzz.yaml

.PHONY: all compile reproduce reproduce-yaml spike analyze-log clean help

all: help

help:
	@echo "Bug Reproduction Targets:"
	@echo "  make compile          - Compile the minimal reproduction seed"
	@echo "  make reproduce        - Compile + run DUT + analyze (needs DUT_CMD)"
	@echo "  make reproduce-yaml   - Compile + run DUT using YAML config"
	@echo "  make spike            - Run standalone Spike reference only"
	@echo "  make analyze-log      - Analyze an existing DUT output log"
	@echo "  make clean            - Remove generated files"
	@echo ""
	@echo "Variables:"
	@echo "  DUT_CMD=<cmd>         DUT command with $$1 for seed path"
	@echo "  DUT_CWD=<dir>         DUT working directory"
	@echo "  YAML_CONFIG=<path>    Path to boom_fuzz.yaml"
	@echo "  PYTHON=<path>         Python interpreter (default: python3)"
	@echo ""
	@echo "Example:"
	@echo "  make reproduce-yaml YAML_CONFIG=../../boom_fuzz.yaml"

compile:
	$(PYTHON) $(SCRIPT) --asm $(ASM) --dut-cmd "echo" --output-dir $(OUTPUT) || true

reproduce: compile
	$(PYTHON) $(SCRIPT) \
		--asm $(ASM) \
		--dut-cmd '$(DUT_CMD)' \
		--dut-cwd '$(DUT_CWD)' \
		--output-dir $(OUTPUT)

reproduce-yaml:
	$(PYTHON) $(SCRIPT) \
		--config $(YAML_CONFIG) \
		--output-dir $(OUTPUT)

reproduce-existing-elf:
	$(PYTHON) $(SCRIPT) \
		--elf $(ELF) \
		--config $(YAML_CONFIG) \
		--output-dir $(OUTPUT)

spike:
	$(PYTHON) $(SCRIPT) \
		--spike-only \
		--asm $(ASM) \
		--output-dir $(OUTPUT)

analyze-log:
	$(PYTHON) -c "\
import sys; sys.path.insert(0, '$(REPRODUCE_DIR)'); \
from reproduce_bug import parse_cosim_output, report_results; \
from pathlib import Path; \
log = Path('$(LOG)').read_text(); \
r = parse_cosim_output(log); \
print(f'Mismatch: {r[\"mismatch_found\"]}'); \
print(f'Exceptions: {r[\"exception_count\"]}'); \
print(f'Status: {r[\"test_status\"]}'); \
if r['mismatch_line']: print(f'Line: {r[\"mismatch_line\"]}')"

clean:
	rm -rf $(OUTPUT)
