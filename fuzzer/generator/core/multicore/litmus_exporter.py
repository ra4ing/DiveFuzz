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

r"""Export an MCProgram to RISCV ``.litmus`` source for herd7 / litmus7.

The emitted syntax matches the style of the existing harness fixture in
``fuzzer/multi-core/spike-litmus-harness/build/LB-mixed1/gen/run.sh``:

    RISCV <name>
    {
     uint64_t x=0;
     uint64_t y=0;
     0:x6=x; 0:x7=y;
     1:x6=x; 1:x7=y;
    }
     P0 | P1 ;
     <instr> | <instr> ;
     ...
    exists (0:x10=0 /\ 1:x10=0)
"""

from .model import MCProgram, EventKind, ModeledEvent


def _ctype(width: int) -> str:
    return "uint64_t" if width == 8 else "uint32_t"


def _mem_op(width: int) -> str:
    return "sd" if width == 8 else "sw"


def _load_op(width: int) -> str:
    return "ld" if width == 8 else "lw"


def _event_instructions(event: ModeledEvent, address_regs: dict[str, str]) -> list[str]:
    """Flatten one modeled event into its assembly instruction string(s)."""
    if event.kind is EventKind.STORE:
        addr_reg = address_regs[event.addr]
        return [
            f"ori {event.value_reg},x0,{event.value}",
            f"{_mem_op(event.width)} {event.value_reg},0({addr_reg})",
        ]
    if event.kind is EventKind.LOAD:
        addr_reg = address_regs[event.addr]
        return [f"{_load_op(event.width)} {event.dst},0({addr_reg})"]
    if event.kind is EventKind.FENCE:
        return [f"fence {event.pred},{event.succ}"]
    if event.kind is EventKind.FENCE_TSO:
        return ["fence.tso"]
    raise ValueError(
        f"Modeled event {event.kind.value} is declared but not implemented "
        f"in the MVP exporter"
    )


def export_litmus(program: MCProgram) -> str:
    """Render ``program`` as a RISCV litmus source string."""
    lines: list[str] = [f"RISCV {program.name}", ""]

    # Init block: shared var declarations + per-hart address register bindings.
    init = ["{"]
    for v in program.shared_vars:
        init.append(f" {_ctype(v.width)} {v.name}={v.init_value};")
    for hp in program.hart_programs:
        for var, reg in hp.address_regs.items():
            init.append(f" {hp.hart_id}:{reg}={var};")
    init.append("}")
    lines.append("\n".join(init))
    lines.append("")

    # Process table: align per-hart flattened instructions by row.
    hart_rows: list[list[str]] = []
    for hp in program.hart_programs:
        rows: list[str] = list(hp.prologue_noise)
        for event in hp.modeled_window:
            rows.extend(_event_instructions(event, hp.address_regs))
        rows.extend(hp.epilogue_noise)
        hart_rows.append(rows)

    max_rows = max((len(r) for r in hart_rows), default=0)
    headers = [f"P{hp.hart_id}" for hp in program.hart_programs]
    lines.append(" " + " | ".join(headers) + " ;")
    for i in range(max_rows):
        cells = [rows[i] if i < len(rows) else "" for rows in hart_rows]
        lines.append(" " + " | ".join(cells) + " ;")
    lines.append("")

    # exists clause: all observed registers pinned to 0 (litmus7 compatibility
    # only; the real oracle parses the full States block from herd).
    cond = " /\\ ".join(f"{o.hart}:{o.reg}=0" for o in program.observed)
    lines.append(f"exists ({cond})")
    return "\n".join(lines) + "\n"
