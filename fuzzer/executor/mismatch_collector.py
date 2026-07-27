# Copyright (c) 2024-2025 Institute of Information Engineering, Chinese Academy of Sciences
#
# DiveFuzz is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#          http://license.coscl.org.cn/MulanPSL2
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
#
# See the Mulan PSL v2 for more details.

"""
Mismatch collector for DiveFuzz DUT test results.

After running DUT tests, this module collects mismatch seeds, logs, and related
files into a timestamped directory for easy analysis. Supports both XiangShan
(difftest) and BOOM (cosim) log formats.
"""

import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from utils.results_reporter import TestResult, ResultType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Log parsing: extract mismatch details from raw DUT output
# ---------------------------------------------------------------------------

# BOOM cosim patterns
_RE_BOOM_PC_MISMATCH = re.compile(
    r"PC\s+mismatch\s+spike\s+([0-9a-fA-F]+)\s*!=\s*DUT\s+([0-9a-fA-F]+)",
    re.IGNORECASE,
)
_RE_BOOM_EXCEPTION = re.compile(r"exception\s+(\d+)", re.IGNORECASE)
_RE_BOOM_COMMIT = re.compile(
    r"Cosim:\s+\d+\s+commit:\s+([0-9a-fA-F]+)", re.IGNORECASE
)
_RE_BOOM_CORE_INSN = re.compile(
    r"core\s+\d+:\s+\d+\s+(0x[0-9a-fA-F]+)\s+\(0x[0-9a-fA-F]+\)"
)

# XiangShan difftest patterns
_RE_XS_BAD_TRAP = re.compile(r"HIT\s+BAD\s+TRAP", re.IGNORECASE)
_RE_XS_ABORT = re.compile(r"\bABORT\b", re.IGNORECASE)
_RE_XS_GOOD_TRAP = re.compile(r"HIT\s+GOOD\s+TRAP", re.IGNORECASE)
_RE_XS_REG_DIFF = re.compile(
    r"(pc| différence|DIFFERENCE|x\d+|f\d+|csr)", re.IGNORECASE
)
_RE_XS_DIFF_LINE = re.compile(
    r"\[DIFF\]|DIFFERENCE|diff\s+at|commit\s+diff|reg\s+diff",
    re.IGNORECASE,
)
_RE_XS_MISMATCH_PC = re.compile(
    r"mismatch.*pc\s*=\s*0x([0-9a-fA-F]+)", re.IGNORECASE
)


def _strip_logger_prefix(line: str) -> str:
    """Remove the Python logging timestamp prefix from a log line."""
    # Lines look like: 2026-05-19 13:25:10,394 - test.name - INFO - <content>
    m = re.match(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2},\d+\s+-\s+.*?\s+-\s+\w+\s+-\s+(.*)", line)
    if m:
        return m.group(1)
    return line


def parse_log_for_mismatch(log_path: str) -> dict:
    """
    Parse a DUT test log file and extract mismatch information.

    Returns a dict with:
        has_mismatch: bool
        dut_type: str - 'xiangshan', 'boom', or 'unknown'
        mismatch_summary: str - human-readable summary
        spike_pc: str or None
        dut_pc: str or None
        mismatch_context: list[str] - lines around the mismatch point
        full_output: list[str] - stripped raw output lines
    """
    result = {
        "has_mismatch": False,
        "dut_type": "unknown",
        "mismatch_summary": "",
        "spike_pc": None,
        "dut_pc": None,
        "mismatch_context": [],
        "full_output": [],
    }

    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            raw_lines = f.readlines()
    except Exception as e:
        logger.warning(f"Cannot read log file {log_path}: {e}")
        return result

    # Strip logger prefix and keep clean output
    stripped = [_strip_logger_prefix(l.rstrip()) for l in raw_lines]
    result["full_output"] = stripped

    # Detect DUT type from log content
    for line in stripped:
        if "Cosim:" in line:
            result["dut_type"] = "boom"
            break
        if "HIT GOOD TRAP" in line or "HIT BAD TRAP" in line or "ABORT" in line:
            result["dut_type"] = "xiangshan"
            break

    # Parse based on DUT type
    if result["dut_type"] == "boom":
        _parse_boom_log(stripped, result)
    elif result["dut_type"] == "xiangshan":
        _parse_xiangshan_log(stripped, result)
    else:
        _parse_generic_log(stripped, result)

    return result


def _parse_boom_log(lines: list[str], result: dict):
    """Parse BOOM cosim log for PC mismatch."""
    mismatch_idx = -1
    for i, line in enumerate(lines):
        m = _RE_BOOM_PC_MISMATCH.search(line)
        if m:
            result["has_mismatch"] = True
            result["spike_pc"] = m.group(1)
            result["dut_pc"] = m.group(2)
            result["mismatch_summary"] = (
                f"PC mismatch: spike=0x{m.group(1)} != DUT=0x{m.group(2)}"
            )
            mismatch_idx = i
            break

    if mismatch_idx >= 0:
        # Collect context: 30 lines before and 10 lines after the mismatch
        start = max(0, mismatch_idx - 30)
        end = min(len(lines), mismatch_idx + 10)
        result["mismatch_context"] = lines[start:end]
    else:
        # No PC mismatch found — but the test still failed.
        # Look for other cosim error indicators.
        for i, line in enumerate(lines):
            lower = line.lower()
            # "verilog $finish" is normal BOOM termination, not an error
            if "cosim" in lower and ("error" in lower or "fail" in lower):
                result["has_mismatch"] = True
                result["mismatch_summary"] = f"BOOM cosim error: {line.strip()}"
                start = max(0, i - 10)
                end = min(len(lines), i + 5)
                result["mismatch_context"] = lines[start:end]
                break
            elif "assertion" in lower and "fail" in lower:
                result["has_mismatch"] = True
                result["mismatch_summary"] = f"BOOM assertion failure: {line.strip()}"
                start = max(0, i - 10)
                end = min(len(lines), i + 5)
                result["mismatch_context"] = lines[start:end]
                break


def _parse_xiangshan_log(lines: list[str], result: dict):
    """Parse XiangShan difftest log for BAD TRAP / ABORT."""
    trap_idx = -1
    trap_type = None

    for i, line in enumerate(lines):
        if _RE_XS_BAD_TRAP.search(line):
            trap_idx = i
            trap_type = "BAD TRAP"
            # Try to extract PC
            pc_match = re.search(r"pc\s*=\s*(0x[0-9a-fA-F]+)", line)
            if pc_match:
                result["dut_pc"] = pc_match.group(1)
            break
        elif _RE_XS_ABORT.search(line) and "ABORT at pc" in line:
            trap_idx = i
            trap_type = "ABORT"
            pc_match = re.search(r"pc\s*=\s*(0x[0-9a-fA-F]+)", line)
            if pc_match:
                result["dut_pc"] = pc_match.group(1)
            break

    if trap_idx >= 0:
        result["has_mismatch"] = True
        result["mismatch_summary"] = f"XiangShan {trap_type}"
        if result["dut_pc"]:
            result["mismatch_summary"] += f" at pc={result['dut_pc']}"

        # Collect context: the difftest register diff is printed BEFORE the trap message
        # So we look further back (up to 100 lines before)
        start = max(0, trap_idx - 100)
        end = min(len(lines), trap_idx + 5)
        result["mismatch_context"] = lines[start:end]
    else:
        # No explicit trap line, but the test still failed.
        # Look for difftest register diff lines.
        for i, line in enumerate(lines):
            if _RE_XS_DIFF_LINE.search(line):
                result["has_mismatch"] = True
                result["mismatch_summary"] = "XiangShan difftest mismatch detected"
                start = max(0, i - 5)
                end = min(len(lines), i + 20)
                result["mismatch_context"] = lines[start:end]
                break


def _parse_generic_log(lines: list[str], result: dict):
    """Fallback parser for unknown DUT types — look for common error patterns."""
    error_patterns = [
        re.compile(r"mismatch", re.IGNORECASE),
        re.compile(r"error", re.IGNORECASE),
        re.compile(r"abort", re.IGNORECASE),
        re.compile(r"fail", re.IGNORECASE),
    ]
    for i, line in enumerate(lines):
        for pat in error_patterns:
            if pat.search(line):
                result["has_mismatch"] = True
                result["mismatch_summary"] = f"Error detected: {line.strip()[:200]}"
                start = max(0, i - 5)
                end = min(len(lines), i + 10)
                result["mismatch_context"] = lines[start:end]
                return


# ---------------------------------------------------------------------------
# Seed file discovery: find related files (.elf, .img, .S) for a seed
# ---------------------------------------------------------------------------

def _find_seed_related_files(seed_path: str) -> list[str]:
    """
    Find all related files for a given seed path.

    For a seed like '/path/seeds_42_.img', returns:
      - /path/seeds_42_.img
      - /path/seeds_42_.elf  (if exists in sibling elf_file/ dir or same dir)
      - /path/seeds_42_.S    (if exists in same dir)
      - /path/img_file/seeds_42_.img  (if exists)
      - /path/elf_file/seeds_42_.elf  (if exists)
    """
    if not seed_path or not os.path.isfile(seed_path):
        return []

    found = [seed_path]
    seed = Path(seed_path)
    stem = seed.stem
    parent = seed.parent
    grandparent = parent.parent

    # Check for .S in the same directory or parent directory
    for s_dir in [parent, grandparent]:
        s_file = s_dir / f"{stem}.S"
        if s_file.is_file():
            found.append(str(s_file))
            break

    # Check for .elf in elf_file/ subdir or same dir
    for base in [parent, grandparent]:
        elf_file = base / "elf_file" / f"{stem}.elf"
        if elf_file.is_file():
            found.append(str(elf_file))
            break
    if not any(Path(f).suffix == ".elf" for f in found):
        elf_same = parent / f"{stem}.elf"
        if elf_same.is_file():
            found.append(str(elf_same))

    # Check for .img in img_file/ subdir or same dir
    for base in [parent, grandparent]:
        img_file = base / "img_file" / f"{stem}.img"
        if img_file.is_file():
            found.append(str(img_file))
            break
    if not any(Path(f).suffix == ".img" for f in found):
        img_same = parent / f"{stem}.img"
        if img_same.is_file():
            found.append(str(img_same))

    # Deduplicate
    return list(dict.fromkeys(found))


# ---------------------------------------------------------------------------
# Main collection logic
# ---------------------------------------------------------------------------

def collect_mismatches(
    total_results: list[TestResult],
    output_base_dir: str = "outputs",
    global_logger: Optional[logging.Logger] = None,
):
    """
    Collect mismatch seeds, logs, and related files into a timestamped directory.

    Creates:
        outputs/mismatches_<timestamp>/
        ├── SUMMARY.md                    # Overall summary of all mismatches
        ├── <seed_name>/
        │   ├── <seed_file>              # The seed binary (.elf or .img)
        │   ├── <seed_name>.S            # Assembly source (if available)
        │   ├── test.log                 # The DUT test log
        │   └── mismatch_context.log     # Extracted mismatch context
        └── ...

    Args:
        total_results: All test results from run_dut_tests
        output_base_dir: Base directory for outputs (default: 'outputs')
        global_logger: Logger for status messages
    """
    log = global_logger or logger

    # Filter to only non-success results
    failed_results = [
        r for r in total_results if r.result_type != ResultType.SUCCESS
    ]

    if not failed_results:
        log.info("No mismatches found. Nothing to collect.")
        return

    # Create output directory
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    mismatch_dir = Path(output_base_dir) / f"mismatches_{timestamp}"
    mismatch_dir.mkdir(parents=True, exist_ok=True)

    log.info(f"Collecting {len(failed_results)} mismatch result(s) into {mismatch_dir}")

    summary_entries = []

    for result in failed_results:
        seed_name = result.seed_name
        safe_name = seed_name.replace(" ", "_").replace(os.sep, "_").replace("/", "_")

        # Create per-seed subdirectory
        seed_dir = mismatch_dir / safe_name
        seed_dir.mkdir(exist_ok=True)

        entry = {
            "seed_name": seed_name,
            "result_type": result.result_type.name,
            "summary": result.summary or "",
            "dut_name": result.dut_name,
            "version": result.version,
            "seed_dir": str(seed_dir),
            "files": [],
        }

        # 1. Parse log file for mismatch details
        mismatch_info = parse_log_for_mismatch(result.log_path)

        # 2. Copy log file
        if result.log_path and os.path.isfile(result.log_path):
            log_dst = seed_dir / "test.log"
            shutil.copy2(result.log_path, log_dst)
            entry["files"].append("test.log")

        # 3. Write mismatch context
        if mismatch_info["mismatch_context"]:
            ctx_path = seed_dir / "mismatch_context.log"
            with open(ctx_path, "w", encoding="utf-8") as f:
                f.write(f"# Mismatch Context for: {seed_name}\n")
                f.write(f"# DUT: {result.dut_name} ({result.version})\n")
                f.write(f"# Summary: {mismatch_info['mismatch_summary']}\n")
                if mismatch_info["spike_pc"]:
                    f.write(f"# Spike PC: 0x{mismatch_info['spike_pc']}\n")
                if mismatch_info["dut_pc"]:
                    f.write(f"# DUT PC:   0x{mismatch_info['dut_pc']}\n")
                f.write("\n")
                for line in mismatch_info["mismatch_context"]:
                    f.write(line + "\n")
            entry["files"].append("mismatch_context.log")

        # 4. Copy seed files and related artifacts
        seed_files = _find_seed_related_files(result.seed_path)
        for src_path in seed_files:
            src = Path(src_path)
            dst = seed_dir / src.name
            if not dst.exists():
                shutil.copy2(src_path, dst)
            entry["files"].append(src.name)

        entry["mismatch_info"] = mismatch_info
        summary_entries.append(entry)

    # 5. Write overall summary
    _write_summary(mismatch_dir, summary_entries)

    log.info(f"Mismatch collection complete: {len(failed_results)} result(s) in {mismatch_dir}")


def _write_summary(mismatch_dir: Path, entries: list[dict]):
    """Write SUMMARY.md with an overview of all collected mismatches."""
    summary_path = mismatch_dir / "SUMMARY.md"

    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(f"# Mismatch Collection Report\n\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Total mismatches: {len(entries)}\n\n")

        # Table of contents
        f.write("## Seeds\n\n")
        f.write("| # | Seed | Result | DUT | Summary |\n")
        f.write("|---|------|--------|-----|--------|\n")
        for i, e in enumerate(entries, 1):
            summary = e["summary"][:80]
            f.write(
                f"| {i} | {e['seed_name']} | {e['result_type']} "
                f"| {e['dut_name']} | {summary} |\n"
            )
        f.write("\n")

        # Detailed entries
        f.write("## Details\n\n")
        for i, e in enumerate(entries, 1):
            f.write(f"### {i}. {e['seed_name']}\n\n")
            f.write(f"- **Result type**: {e['result_type']}\n")
            f.write(f"- **DUT**: {e['dut_name']} ({e['version']})\n")
            f.write(f"- **Summary**: {e['summary']}\n")

            info = e.get("mismatch_info", {})
            if info.get("mismatch_summary"):
                f.write(f"- **Mismatch**: {info['mismatch_summary']}\n")
            if info.get("dut_pc"):
                f.write(f"- **DUT PC**: `0x{info['dut_pc']}`\n")
            if info.get("spike_pc"):
                f.write(f"- **Spike PC**: `0x{info['spike_pc']}`\n")
            if info.get("dut_type"):
                f.write(f"- **DUT type**: {info['dut_type']}\n")

            f.write(f"- **Files**:\n")
            for fn in e.get("files", []):
                f.write(f"  - `{fn}`\n")
            f.write("\n")
