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

"""Export generated instruction lists as difuzz-rtl SimInput files.

The exporter keeps normal seed ``.S`` output unchanged and writes a sidecar
``.si`` file plus a ``.astra_template.json`` snapshot so that
``coverage_compile_si.py`` can render the final RTL replay binary using the
exact same per-seed AstraFuzz template initialization, memory layout, CSR
values, trap handlers, and data sections.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Protocol, Sequence


SI_TEMPLATE = "p-m-astra"
UNSUPPORTED_PREFIXES = (
    ".section",
    ".option",
    ".align",
    ".balign",
    ".p2align",
    ".globl",
    ".global",
    ".type",
    ".size",
    ".text",
    ".data",
    ".bss",
    ".word",
    ".dword",
    ".8byte",
    ".4byte",
    ".byte",
    ".zero",
    ".space",
)
TERMINATOR_LABELS = {"write_tohost:", "instr_end:"}


class TemplateSnapshot(Protocol):
    """Minimal template instance interface needed for per-seed snapshots."""

    @property
    def header(self) -> str: ...

    @property
    def footer(self) -> str: ...

    @property
    def template_type(self) -> object: ...

    @property
    def isa(self) -> str: ...

    @property
    def arch_bits(self) -> int: ...


def strip_comment(line: str) -> str:
    """Remove simple assembly comments while preserving the instruction text."""

    return line.split("#", 1)[0].split("//", 1)[0].rstrip()


def normalize_instruction(line: str) -> str | None:
    """Return a SimInput-safe instruction/label line, or ``None`` to skip it."""

    stripped = strip_comment(line).strip()
    if not stripped:
        return None
    if stripped in TERMINATOR_LABELS:
        return None
    if stripped.startswith(UNSUPPORTED_PREFIXES):
        return None
    return stripped


def sanitize_instructions(instructions: Sequence[str]) -> tuple[list[str], list[str]]:
    """Filter generated assembly into SimInput body lines and rejection notes."""

    body: list[str] = []
    notes: list[str] = []
    for index, instruction in enumerate(instructions):
        normalized = normalize_instruction(instruction)
        if normalized is None:
            notes.append(f"skipped:{index}:{strip_comment(instruction).strip()}")
            continue
        body.append(normalized)
    return body, notes


def format_si_instruction(label: str, instruction: str, interrupt_bits: str = "0000") -> str:
    """Format one SimInput instruction line."""

    if not re.fullmatch(r"[01]{4}", interrupt_bits):
        raise ValueError(f"interrupt bits must be a 4-bit binary string: {interrupt_bits}")
    return f"{label:<8}{instruction:<56}{interrupt_bits}\n"


def export_difuzz_si(
    instructions: Sequence[str],
    output_si: Path,
    *,
    method: str,
    seed_id: str,
    template_snapshot: TemplateSnapshot,
    manifest_path: Path | None = None,
) -> Path:
    """Write a difuzz-rtl SimInput sidecar for one generated seed."""

    body, notes = sanitize_instructions(instructions)
    if not body:
        raise ValueError("no SimInput-compatible instructions to export")

    output_si.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [f"{SI_TEMPLATE}\n", "\n"]
    for index, instruction in enumerate(body):
        lines.append(format_si_instruction(f"_l{index}:", instruction))
    output_si.write_text("".join(lines), encoding="utf-8")

    manifest = {
        "schema_version": 1,
        "adapter_mode": "difuzz_si_direct",
        "exporter": "difuzz_si_exporter_v2",
        "method": method,
        "seed_id": seed_id,
        "si_path": str(output_si.resolve()),
        "template": SI_TEMPLATE,
        "main_instruction_count": len(body),
        "data_sha256": hashlib.sha256(output_si.read_bytes()).hexdigest(),
        "notes": notes,
    }

    snapshot_path = output_si.with_suffix(".astra_template.json")
    template_type = getattr(template_snapshot.template_type, "value", str(template_snapshot.template_type))
    snapshot = {
        "schema_version": 1,
        "snapshot_type": "astra_template_v1",
        "method": method,
        "seed_id": seed_id,
        "template_type": template_type,
        "isa": template_snapshot.isa,
        "arch_bits": template_snapshot.arch_bits,
        "header": template_snapshot.header,
        "footer": template_snapshot.footer,
        "header_sha256": hashlib.sha256(template_snapshot.header.encode("utf-8")).hexdigest(),
        "footer_sha256": hashlib.sha256(template_snapshot.footer.encode("utf-8")).hexdigest(),
    }
    snapshot_path.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")
    manifest["astra_template_snapshot"] = str(snapshot_path.resolve())

    if manifest_path is None:
        manifest_path = output_si.with_suffix(output_si.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return output_si
