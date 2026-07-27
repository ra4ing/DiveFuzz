#!/usr/bin/env python3
# ============================================================================
# Bug Reproduction Script for BOOM V4 CSRRSI hpmcounter Bug
#
# Reproduces: BOOM V4 fails to raise illegal-instruction exception when
#   U-mode executes CSRRSI x4, hpmcounter8, 0 while mcounteren=0.
#
# This script:
#   1. Compiles a minimal reproduction assembly seed to ELF
#   2. Runs it on the BOOM DUT (Verilator simulation with Spike cosim)
#   3. Optionally runs standalone Spike for reference comparison
#   4. Parses cosim output to determine if the bug is reproduced
#
# Usage:
#   python reproduce_bug.py --dut-cmd "bash -c '...'" --dut-cwd /path/to/chipyard
#   python reproduce_bug.py --config ../../boom_fuzz.yaml
#   python reproduce_bug.py --elf /path/to/existing.elf --dut-cmd "..."
# ============================================================================

import os
import sys
import argparse
import subprocess
import struct
import re
import shutil
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
FUZZER_DIR = SCRIPT_DIR.parent.parent
LINKER_SCRIPT = FUZZER_DIR / "generator" / "reg_analyzer" / "linker" / "link.ld"
DEFAULT_SEED_ASM = SCRIPT_DIR / "mismatch_analysis" / "bug_csrrsi_hpmcounter" / "bug_csrrsi_hpmcounter.S"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "output"

# Expected results
SPIKE_ISA = "rv64imafdcbzicsr_zifencei_zihpm_zba_zbb_zbs_zicntr"
BUG_INSTRUCTION_CSR = 0xC08   # hpmcounter8
BUG_INSTRUCTION_ENCODING = 0xC0806273  # CSRRSI x4, hpmcounter8, 0
BUG_PC_OFFSET = None  # will be computed after assembly

# ---------------------------------------------------------------------------
# ANSI colors
# ---------------------------------------------------------------------------
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def log_info(msg):
    print(f"{CYAN}[INFO]{RESET}  {msg}")


def log_ok(msg):
    print(f"{GREEN}[PASS]{RESET}  {msg}")


def log_fail(msg):
    print(f"{RED}[FAIL]{RESET}  {msg}")


def log_warn(msg):
    print(f"{YELLOW}[WARN]{RESET}  {msg}")


# ---------------------------------------------------------------------------
# Step 1: Compile assembly to ELF
# ---------------------------------------------------------------------------
def compile_seed(asm_path: Path, output_dir: Path, link_script: Path) -> Path:
    """Compile an assembly file to ELF using the RISC-V toolchain.

    Follows the same pipeline as utils/elf_to_img.py:
      as -> ld -> objcopy (binary)
    Returns path to the generated ELF.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    base = asm_path.stem
    obj = output_dir / f"{base}.o"
    elf = output_dir / f"{base}.elf"
    img = output_dir / f"{base}.img"

    march = "rv64gcv_zicsr_zifencei_zfh_zba_zbb_zbkc_zbc_zbkb_zbs_zmmul_zknh_zkne_zknd_zbkx_zfhmin"

    log_info(f"Assembling {asm_path.name} -> {obj.name}")
    r = subprocess.run(
        ["riscv64-unknown-elf-as", "-march", march, "-c", str(asm_path), "-o", str(obj)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        log_fail(f"Assembly failed:\n{r.stderr}")
        sys.exit(1)

    log_info(f"Linking {obj.name} -> {elf.name}")
    r = subprocess.run(
        ["riscv64-unknown-elf-ld", "-T", str(link_script), str(obj), "-o", str(elf)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        log_fail(f"Link failed:\n{r.stderr}")
        sys.exit(1)

    log_info(f"Generating binary image -> {img.name}")
    r = subprocess.run(
        ["riscv64-unknown-elf-objcopy", "-O", "binary", str(elf), str(img)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        log_fail(f"Objcopy failed:\n{r.stderr}")
        sys.exit(1)

    # Clean up .o
    obj.unlink(missing_ok=True)
    log_ok(f"Compiled seed: {elf}")
    return elf


def use_existing_seed(seed_path: Path, output_dir: Path) -> Path:
    """Copy an existing seed ELF/IMG into the output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    dst = output_dir / seed_path.name
    if seed_path != dst:
        shutil.copy2(seed_path, dst)
    return dst


# ---------------------------------------------------------------------------
# Step 2: Run DUT (BOOM Verilator simulation with Spike cosim)
# ---------------------------------------------------------------------------
def run_dut(elf_path: Path, dut_cmd: str, dut_cwd: str, timeout: int = 600) -> str:
    """Execute the DUT simulation with the given ELF.

    dut_cmd should contain '$1' as placeholder for the seed path.
    Returns the raw stdout/stderr output.
    """
    cmd = dut_cmd.replace("$1", f'"{str(elf_path)}"')
    log_info(f"Running DUT: {cmd}")
    log_info(f"  CWD: {dut_cwd}")

    try:
        r = subprocess.run(
            cmd, shell=True, cwd=dut_cwd,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        return r.stdout
    except subprocess.TimeoutExpired:
        log_fail(f"DUT timed out after {timeout}s")
        return ""


# ---------------------------------------------------------------------------
# Step 3: Run standalone Spike (no cosim) for reference
# ---------------------------------------------------------------------------
def run_spike_standalone(elf_path: Path, spike_path: str = None) -> str:
    """Run Spike independently to show what the reference model does."""
    if spike_path is None:
        spike_path = os.environ.get("spike", "spike")
    if not shutil.which(spike_path):
        log_warn("Spike not found in PATH or $spike env var. Skipping standalone Spike run.")
        return ""

    cmd = [
        spike_path,
        "--isa", SPIKE_ISA,
        "--priv", "msu",
        "--pmpregions", "8",
        "-l",  # log commit traces
        str(elf_path),
    ]
    log_info(f"Running standalone Spike: {' '.join(cmd)}")

    try:
        r = subprocess.run(
            cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=120,
        )
        return r.stdout
    except subprocess.TimeoutExpired:
        log_warn("Spike standalone timed out")
        return ""


# ---------------------------------------------------------------------------
# Step 4: Parse cosim output and detect the bug
# ---------------------------------------------------------------------------
def parse_cosim_output(output: str):
    """Parse DUT cosim output and extract key events.

    Returns dict with:
      mismatch_found: bool
      mismatch_line: str or None
      spike_pc: int or None
      dut_pc: int or None
      exception_count: int
      last_exception_pc: int or None
    """
    result = {
        "mismatch_found": False,
        "mismatch_line": None,
        "spike_pc": None,
        "dut_pc": None,
        "exception_count": 0,
        "last_exception_pc": None,
        "test_status": None,
        "full_output": output,
    }

    for line in output.splitlines():
        line = line.strip()

        # Detect PC mismatch
        m = re.search(r"PC mismatch spike ([0-9a-f]+) != DUT ([0-9a-f]+)", line, re.IGNORECASE)
        if m:
            result["mismatch_found"] = True
            result["mismatch_line"] = line
            result["spike_pc"] = int(m.group(1), 16)
            result["dut_pc"] = int(m.group(2), 16)

        # Count exceptions
        if "exception 2" in line:
            result["exception_count"] += 1
            # Extract the Spike PC just before this exception
            # Look for "core 0: X 0xNNNN" in the preceding context

        # Test status
        if "Test completed with status: FAILURE" in line:
            result["test_status"] = "FAILURE"
        elif "Test completed with status: SUCCESS" in line:
            result["test_status"] = "SUCCESS"

    # Try to find the Spike PC that caused the last exception
    lines = output.splitlines()
    for i, line in enumerate(lines):
        if "PC mismatch" in line:
            # Look backward for the last Spike instruction before mismatch
            for j in range(i - 1, max(i - 20, 0), -1):
                m = re.search(r"core\s+\d+:\s+\d+\s+(0x[0-9a-f]+)\s+\(0x[0-9a-f]+\)", lines[j], re.IGNORECASE)
                if m:
                    result["last_exception_pc"] = int(m.group(1), 16)
                    break

    return result


def find_bug_instruction_in_elf(elf_path: Path, target_encoding: int) -> list:
    """Find all occurrences of the target instruction encoding in the ELF.

    Returns list of virtual addresses where the encoding appears.
    """
    # Parse ELF to find LOAD segments and search for the instruction
    with open(elf_path, "rb") as f:
        data = f.read()

    if data[:4] != b"\x7fELF":
        return []

    e_phoff = struct.unpack_from("<Q", data, 32)[0]
    e_phentsize = struct.unpack_from("<H", data, 54)[0]
    e_phnum = struct.unpack_from("<H", data, 56)[0]

    matches = []
    target_bytes = struct.pack("<I", target_encoding)

    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type = struct.unpack_from("<I", data, off)[0]
        if p_type != 1:  # PT_LOAD
            continue
        p_offset = struct.unpack_from("<Q", data, off + 8)[0]
        p_vaddr = struct.unpack_from("<Q", data, off + 16)[0]
        p_filesz = struct.unpack_from("<Q", data, off + 32)[0]

        # Search for the encoding in this segment
        seg_data = data[p_offset:p_offset + p_filesz]
        pos = 0
        while True:
            idx = seg_data.find(target_bytes, pos)
            if idx == -1:
                break
            matches.append(p_vaddr + idx)
            pos = idx + 1

    return matches


# ---------------------------------------------------------------------------
# Step 5: Report results
# ---------------------------------------------------------------------------
def print_banner():
    print(f"\n{'='*72}")
    print(f"  BOOM V4 Bug Reproduction: CSRRSI hpmcounter mcounteren check")
    print(f"  Bug: CSRRSI uimm=0 on hpmcounter from U-mode skips access check")
    print(f"{'='*72}\n")


def report_results(cosim_result, elf_path, spike_output=None):
    """Print a detailed analysis of the reproduction attempt."""
    bug_addrs = find_bug_instruction_in_elf(elf_path, BUG_INSTRUCTION_ENCODING)

    print(f"\n{'─'*72}")
    print(f"  RESULTS")
    print(f"{'─'*72}")

    # ELF analysis
    print(f"\n  ELF: {elf_path}")
    if bug_addrs:
        print(f"  Bug instruction (CSRRSI x4, hpmcounter8, 0 = 0x{BUG_INSTRUCTION_ENCODING:08x})")
        for addr in bug_addrs:
            print(f"    found at PC 0x{addr:08x}")
    else:
        print(f"  Warning: Bug instruction encoding 0x{BUG_INSTRUCTION_ENCODING:08x} not found in ELF")

    # Cosim results
    if cosim_result["test_status"]:
        print(f"\n  Test status: {cosim_result['test_status']}")

    print(f"  Total exception 2 (illegal instruction) events: {cosim_result['exception_count']}")

    if cosim_result["mismatch_found"]:
        print(f"\n  {RED}{BOLD}*** BUG REPRODUCED ***{RESET}")
        print(f"  Mismatch: {cosim_result['mismatch_line']}")
        if cosim_result["spike_pc"] is not None:
            print(f"    Spike PC: 0x{cosim_result['spike_pc']:08x} (trap handler - correctly trapped)")
        if cosim_result["dut_pc"] is not None:
            print(f"    DUT PC:   0x{cosim_result['dut_pc']:08x} (continued past - failed to trap)")

        # Cross-reference with expected bug address
        if bug_addrs:
            for addr in bug_addrs:
                # The DUT should have been at bug_addr+4 if it didn't trap
                if cosim_result["dut_pc"] and abs(cosim_result["dut_pc"] - (addr + 4)) <= 4:
                    print(f"\n  {RED}The mismatch occurs at the expected CSRRSI hpmcounter8 bug site (0x{addr:08x}){RESET}")
                    print(f"  Spike correctly trapped on this instruction (entered M-mode trap handler)")
                    print(f"  BOOM incorrectly continued execution (did not raise illegal-instruction)")

        return True  # bug confirmed
    else:
        if cosim_result["test_status"] == "SUCCESS":
            print(f"\n  {GREEN}No mismatch detected - DUT matches reference model{RESET}")
            print(f"  The bug may have been fixed in this DUT version, or the seed")
            print(f"  does not reach the bug instruction.")
        else:
            print(f"\n  {YELLOW}Test did not complete cleanly{RESET}")
            print(f"  Status: {cosim_result['test_status']}")

    return False


def report_spike_detail(spike_output: str):
    """Show relevant Spike trace lines around the bug instruction."""
    if not spike_output:
        return

    print(f"\n{'─'*72}")
    print(f"  STANDALONE SPIKE REFERENCE TRACE (filtered)")
    print(f"{'─'*72}")

    # Show lines containing hpmcounter accesses or illegal instruction exceptions
    lines = spike_output.splitlines()
    for i, line in enumerate(lines):
        line_s = line.strip()
        # Show lines with CSR reads in the 0xCxx range
        if re.search(r"0x000[cC][0-9a-fA-F]{2}", line_s):
            # Show context around this line
            start = max(0, i - 1)
            end = min(len(lines), i + 2)
            for j in range(start, end):
                print(f"  {lines[j]}")
            print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def build_config_from_yaml(yaml_path: str):
    """Load DUT config from an existing YAML file."""
    sys.path.insert(0, str(FUZZER_DIR))
    from config.dut_config import Config
    config = Config.from_yaml(yaml_path)
    return config.dut_target


def main():
    parser = argparse.ArgumentParser(
        description="Reproduce BOOM V4 CSRRSI hpmcounter bug",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Using an existing YAML config:
  python reproduce_bug.py --config ../../boom_fuzz.yaml

  # Direct DUT command:
  python reproduce_bug.py \\
    --dut-cmd 'bash -c "p=\\\"/path/seeds.elf\\\"; exec ./simulator-chipyard.harness-Config \\\"$p\\\"" _  $1' \\
    --dut-cwd /path/to/chipyard/sims/verilator

  # Reuse an existing seed ELF:
  python reproduce_bug.py --elf ../../output_boom_seeds/elf_file/seeds_2_.elf \\
    --dut-cmd '...' --dut-cwd /path/to/chipyard

  # Run standalone Spike only (no DUT):
  python reproduce_bug.py --spike-only --elf /path/to/seed.elf
        """,
    )

    # Config source
    cfg = parser.add_mutually_exclusive_group()
    cfg.add_argument("--config", help="Path to YAML config file (loads DUT cmd/cwd from it)")
    cfg.add_argument("--dut-cmd", help="DUT command template with $1 placeholder for seed path")

    parser.add_argument("--dut-cwd", help="Working directory for DUT execution")
    parser.add_argument("--timeout", type=int, default=600, help="DUT timeout in seconds (default: 600)")

    # Seed source
    seed = parser.add_mutually_exclusive_group()
    seed.add_argument("--asm", default=str(DEFAULT_SEED_ASM), help="Assembly source file (default: built-in)")
    seed.add_argument("--elf", help="Use an existing ELF file directly (skip compilation)")

    parser.add_argument("--spike-only", action="store_true", help="Only run standalone Spike, skip DUT")
    parser.add_argument("--spike-path", help="Path to Spike binary (default: $spike env or 'spike')")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Output directory")

    args = parser.parse_args()
    print_banner()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Resolve DUT config ---
    dut_cmd = args.dut_cmd
    dut_cwd = args.dut_cwd

    if args.config:
        log_info(f"Loading DUT config from {args.config}")
        dut_target = build_config_from_yaml(args.config)
        dut_cmd = dut_target.cmd
        dut_cwd = dut_target.emu_path
        log_info(f"  DUT cmd: {dut_cmd}")
        log_info(f"  DUT cwd: {dut_cwd}")
    elif not args.spike_only and not dut_cmd:
        log_fail("Must specify --config or --dut-cmd (unless --spike-only)")
        parser.print_help()
        sys.exit(1)

    # --- Resolve seed ELF ---
    if args.elf:
        elf_path = use_existing_seed(Path(args.elf), output_dir)
        log_info(f"Using existing ELF: {elf_path}")
    else:
        asm_path = Path(args.asm)
        if not asm_path.exists():
            log_fail(f"Assembly file not found: {asm_path}")
            sys.exit(1)
        link_script = LINKER_SCRIPT if LINKER_SCRIPT.exists() else (
            FUZZER_DIR / "generator" / "reg_analyzer" / "linker" / "link.ld"
        )
        if not link_script.exists():
            log_fail(f"Linker script not found: {link_script}")
            sys.exit(1)
        elf_path = compile_seed(asm_path, output_dir, link_script)

    # --- Find bug instruction in ELF ---
    bug_addrs = find_bug_instruction_in_elf(elf_path, BUG_INSTRUCTION_ENCODING)
    if bug_addrs:
        for addr in bug_addrs:
            log_info(f"Bug instruction 0x{BUG_INSTRUCTION_ENCODING:08x} at PC 0x{addr:08x}")
    else:
        log_warn("Bug instruction encoding not found in ELF - using seed as-is")

    # --- Run standalone Spike ---
    spike_output = None
    if args.spike_path or os.environ.get("spike"):
        spike_output = run_spike_standalone(elf_path, args.spike_path)

    if args.spike_only:
        report_spike_detail(spike_output)
        return

    # --- Run DUT ---
    dut_output = run_dut(elf_path, dut_cmd, dut_cwd, args.timeout)

    # Save raw output
    log_path = output_dir / "dut_output.log"
    log_path.write_text(dut_output)
    log_info(f"DUT output saved to {log_path}")

    # --- Parse & report ---
    cosim_result = parse_cosim_output(dut_output)
    bug_reproduced = report_results(cosim_result, elf_path, spike_output)
    report_spike_detail(spike_output)

    # --- Summary ---
    print(f"\n{'='*72}")
    if bug_reproduced:
        print(f"  {RED}{BOLD}VERDICT: BUG REPRODUCED{RESET}")
        print(f"  BOOM V4 fails to enforce mcounteren on CSRRSI uimm=0 for hpmcounter")
        print(f"  Reference: RISC-V Privileged Spec v20240411, Section 3.1.11")
    else:
        print(f"  {GREEN}VERDICT: NO MISMATCH{RESET}")
    print(f"{'='*72}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
