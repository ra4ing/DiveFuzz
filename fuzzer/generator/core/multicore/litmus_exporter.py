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
    return {1: "uint8_t", 2: "uint16_t", 4: "uint32_t", 8: "uint64_t"}[width]


def _mem_op(width: int) -> str:
    return {1: "sb", 2: "sh", 4: "sw", 8: "sd"}[width]


def _load_op(width: int) -> str:
    return {1: "lb", 2: "lh", 4: "lw", 8: "ld"}[width]


def _atomic_width_suffix(width: int) -> str:
    """RISC-V atomics (AMO/LR/SC) only have ``.w`` (32-bit) and ``.d`` (64-bit)
    forms; sub-word atomics do not exist."""
    return {4: "w", 8: "d"}[width]


def _aqrl_suffix(aq: bool, rl: bool) -> str:
    """The aq/rl ordering-bit suffix; valid only on AMO/LR/SC encodings."""
    if aq and rl:
        return ".aqrl"
    if aq:
        return ".aq"
    if rl:
        return ".rl"
    return ""


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
    if event.kind is EventKind.AMO:
        addr_reg = address_regs[event.addr]
        suffix = _aqrl_suffix(event.aq, event.rl)
        return [
            f"ori {event.value_reg},x0,{event.value}",
            f"amo{event.amo_op}.{_atomic_width_suffix(event.width)}{suffix} "
            f"{event.dst},{event.value_reg},0({addr_reg})",
        ]
    if event.kind is EventKind.LR:
        addr_reg = address_regs[event.addr]
        return [
            f"lr.{_atomic_width_suffix(event.width)}{_aqrl_suffix(event.aq, event.rl)} "
            f"{event.dst},0({addr_reg})"
        ]
    if event.kind is EventKind.SC:
        addr_reg = address_regs[event.addr]
        return [
            f"ori {event.value_reg},x0,{event.value}",
            f"sc.{_atomic_width_suffix(event.width)}{_aqrl_suffix(event.aq, event.rl)} "
            f"{event.dst},{event.value_reg},0({addr_reg})",
        ]
    if event.kind is EventKind.DEPENDENCY:
        if event.dependency == "data":
            # In-window data dependency: link a prior load's value_reg into dst.
            return [f"add {event.dst},{event.value_reg},x0"]
        if event.dependency == "addr":
            # Address dependency: dependent-load `addr` through an address that
            # syntactically depends on value_reg (a prior load). dst doubles as
            # the scratch: xor zeroes it (depends on value_reg), add fixes it to
            # the base, then ld reads that address and writes the result -- the
            # address is read before the writeback, so there is no hazard.
            addr_reg = address_regs[event.addr]
            return [
                f"xor {event.dst},{event.value_reg},{event.value_reg}",
                f"add {event.dst},{event.dst},{addr_reg}",
                f"{_load_op(event.width)} {event.dst},0({event.dst})",
            ]
        if event.dependency == "ctrl":
            # Control dependency: branch on value_reg (a prior load) over the
            # dependent load of `addr`. The forward label is unique within a
            # hart (dst registers are distinct per hart) and per-process in
            # litmus (separate P0/P1 bodies), so L_{dst} never clashes. The
            # label is dot-free: litmus7's RISC-V lexer rejects dot-prefixed
            # labels (probed -- .Lx is a lex error, L_x is accepted).
            addr_reg = address_regs[event.addr]
            label = f"L_{event.dst}"
            return [
                f"beq {event.value_reg},x0,{label}",
                f"{_load_op(event.width)} {event.dst},0({addr_reg})",
                f"{label}:",
            ]
    if event.kind is EventKind.DELAY:
        # In-window load-to-use delay: a data-dependency chain of `amount`
        # adds on dst (adds zero, so value-preserving). Perturbs pipeline
        # timing without touching memory; herd recomputes the allowed set.
        return [f"add {event.dst},{event.dst},x0" for _ in range(event.amount)]
    raise ValueError(
        f"Modeled event {event.kind.value} is declared but not yet "
        f"implemented in the exporter (planned for the randomization phase)"
    )


def export_litmus(program: MCProgram) -> str:
    """Render ``program`` as a RISCV litmus source string."""
    lines: list[str] = [f"RISCV {program.name}", ""]

    # Init block: shared var declarations + per-hart address register bindings.
    # The alias map (logical -> physical) collapses shared vars onto physical
    # locations for same-word aliasing; each physical var is declared once and
    # every address register binds to its physical name.
    alias = program.alias_map
    init = ["{"]
    declared: set[str] = set()
    for v in program.shared_vars:
        phys = alias.get(v.name, v.name)
        if phys in declared:
            continue
        declared.add(phys)
        init.append(f" {_ctype(v.width)} {phys}={v.init_value};")
    for hp in program.hart_programs:
        for var, reg in hp.address_regs.items():
            phys = alias.get(var, var)
            init.append(f" {hp.hart_id}:{reg}={phys};")
    init.append("}")
    lines.append("\n".join(init))
    lines.append("")

    # Process table: align per-hart flattened instructions by row.
    hart_rows: list[list[str]] = []
    for hp in program.hart_programs:
        rows: list[str] = list(hp.prologue_noise)
        inter = hp.interleave_noise
        for i, event in enumerate(hp.modeled_window):
            rows.extend(_event_instructions(event, hp.address_regs))
            if i < len(inter):
                rows.append(inter[i])
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
