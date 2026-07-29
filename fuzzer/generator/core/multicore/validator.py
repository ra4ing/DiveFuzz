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

"""Static validation of a multicore program.

A valid program is sound to (a) export to ``.litmus`` for the herd oracle
and (b) build into a litmus7-compatible executable. Anything that cannot be
proven safe is rejected with a specific ``ValueError``.
"""

from .model import MCProgram, EventKind
from .noise import NoisePool

# All modeled event kinds are now implemented in the exporter
# (Load/Store/Fence/FenceTso/AMO/LR/SC/Dependency/Delay). This set is kept as
# the generic "declared but not implemented" guard; it is currently empty.
_UNSUPPORTED_KINDS: set[EventKind] = set()
# Dependency kinds the exporter renders. "data" is an in-window add; "addr" is a
# dependent-load via the xor-trick (dst doubles as scratch); "ctrl" is a branch
# over a dependent load. All three are herd-accepted and litmus7-compilable.
_DEPENDENCY_KINDS = frozenset({"data", "addr", "ctrl"})
# Delay chain length bounds (a load-to-use chain; kept modest).
_DELAY_AMOUNT_MAX = 16
# AMO operations herd7's RISC-V model implements (maxu/minu are not modelled,
# confirmed by probe -- "RISCV operation amomaxu is not implemented (yet)").
_AMO_OPS = frozenset({"add", "swap", "and", "or", "xor", "min", "max"})
# Atomics (AMO/LR/SC) only admit .w (4) / .d (8); there are no sub-word atomics.
_ATOMIC_KINDS = frozenset({EventKind.AMO, EventKind.LR, EventKind.SC})
_ATOMIC_WIDTHS = (4, 8)
# Kinds whose ``dst`` register defines an observed value.
_OBSERVING_KINDS = {
    EventKind.LOAD,
    EventKind.AMO,
    EventKind.LR,
    EventKind.SC,
    # Dependency/Delay define a dst register with a herd-computable value (a
    # data-dependent copy / a preserved load value), so their dst is observable.
    EventKind.DEPENDENCY,
    EventKind.DELAY,
}

# Valid letters in a fence pred/succ field (RISC-V iorw bits).
_FENCE_BITS = frozenset("iorw")


def validate(program: MCProgram) -> None:
    """Raise ``ValueError`` if ``program`` is not a sound seed."""
    if program.hart_count != len(program.hart_programs):
        raise ValueError(
            f"hart_count ({program.hart_count}) does not match number of "
            f"hart programs ({len(program.hart_programs)})"
        )

    shared = {v.name: v for v in program.shared_vars}
    # Alias map (logical -> physical): targets must be declared shared vars,
    # and vars collapsed onto the same physical location must agree on width
    # and init value (the exporter declares one physical var per group).
    if program.alias_map:
        for logical, phys in program.alias_map.items():
            if logical not in shared:
                raise ValueError(
                    f"alias_map key {logical!r} is not a shared var"
                )
            if phys not in shared:
                raise ValueError(
                    f"alias_map target {phys!r} is not a shared var"
                )
        groups: dict = {}
        for v in program.shared_vars:
            phys = program.alias_map.get(v.name, v.name)
            groups.setdefault(phys, []).append(v)
        for phys, members in groups.items():
            if len({m.width for m in members}) > 1:
                raise ValueError(
                    f"shared vars aliased to {phys!r} disagree on width: "
                    f"{[(m.name, m.width) for m in members]}"
                )
            if len({m.init_value for m in members}) > 1:
                raise ValueError(
                    f"shared vars aliased to {phys!r} disagree on init value: "
                    f"{[(m.name, m.init_value) for m in members]}"
                )

    for hp in program.hart_programs:
        if not hp.modeled_window:
            raise ValueError(f"hart {hp.hart_id} has no modeled events")

        for ev in hp.modeled_window:
            if ev.kind in _UNSUPPORTED_KINDS:
                raise ValueError(
                    f"Modeled event {ev.kind.value} is declared but not yet "
                    f"implemented in the exporter (planned for the "
                    f"randomization phase)"
                )
            if ev.width not in (1, 2, 4, 8):
                raise ValueError(
                    f"event width {ev.width} on hart {hp.hart_id} must be "
                    f"1, 2, 4, or 8"
                )
            if ev.addr is not None:
                if ev.addr not in shared:
                    raise ValueError(
                        f"event address '{ev.addr}' on hart {hp.hart_id} is "
                        f"not a shared var"
                    )
                if ev.width > shared[ev.addr].width:
                    raise ValueError(
                        f"event width {ev.width} exceeds shared var "
                        f"'{ev.addr}' width {shared[ev.addr].width}"
                    )
            if ev.kind is EventKind.STORE and ev.value is None:
                raise ValueError(
                    f"STORE on hart {hp.hart_id} has no value"
                )
            if ev.kind is EventKind.LOAD and ev.dst is None:
                raise ValueError(
                    f"LOAD on hart {hp.hart_id} has no destination register"
                )
            if ev.kind is EventKind.FENCE and (
                not ev.pred
                or not ev.succ
                or not set(ev.pred) <= _FENCE_BITS
                or not set(ev.succ) <= _FENCE_BITS
            ):
                raise ValueError(
                    f"fence on hart {hp.hart_id} has invalid pred/succ "
                    f"'{ev.pred}','{ev.succ}' (must be non-empty subsets of iorw)"
                )
            if ev.kind in _ATOMIC_KINDS and ev.width not in _ATOMIC_WIDTHS:
                raise ValueError(
                    f"{ev.kind.value} on hart {hp.hart_id} must be width 4 or 8 "
                    f"(.w/.d), got {ev.width}"
                )
            if ev.kind is EventKind.AMO and (
                not ev.amo_op
                or ev.amo_op not in _AMO_OPS
                or ev.dst is None
                or ev.value_reg is None
                or ev.value is None
            ):
                raise ValueError(
                    f"AMO on hart {hp.hart_id} needs a valid amo_op "
                    f"({sorted(_AMO_OPS)}), dst, value_reg, and value"
                )
            if ev.kind is EventKind.LR and ev.dst is None:
                raise ValueError(
                    f"LR on hart {hp.hart_id} has no destination register"
                )
            if ev.kind is EventKind.SC and (
                ev.dst is None or ev.value_reg is None or ev.value is None
            ):
                raise ValueError(
                    f"SC on hart {hp.hart_id} needs dst, value_reg, and value"
                )
            if ev.kind is EventKind.DEPENDENCY:
                if ev.dependency not in _DEPENDENCY_KINDS:
                    raise ValueError(
                        f"Dependency on hart {hp.hart_id} has unsupported kind "
                        f"{ev.dependency!r}; supported: {sorted(_DEPENDENCY_KINDS)}"
                    )
                if ev.dst is None or ev.value_reg is None:
                    raise ValueError(
                        f"Dependency on hart {hp.hart_id} needs dst and value_reg"
                    )
                if ev.dependency in ("addr", "ctrl") and ev.addr is None:
                    raise ValueError(
                        f"{ev.dependency} dependency on hart {hp.hart_id} "
                        f"needs a base addr (shared var)"
                    )
            if ev.kind is EventKind.DELAY:
                if ev.dst is None:
                    raise ValueError(
                        f"Delay on hart {hp.hart_id} has no dst register"
                    )
                if not (1 <= ev.amount <= _DELAY_AMOUNT_MAX):
                    raise ValueError(
                        f"Delay on hart {hp.hart_id} has amount {ev.amount}, "
                        f"must be in [1, {_DELAY_AMOUNT_MAX}]"
                    )

        # LR/SC pairing: every SC must be preceded by an LR in program order on
        # the same hart -- an SC without a reservation has no defined semantics.
        seen_lr = False
        for ev in hp.modeled_window:
            if ev.kind is EventKind.LR:
                seen_lr = True
            elif ev.kind is EventKind.SC and not seen_lr:
                raise ValueError(
                    f"SC on hart {hp.hart_id} has no preceding LR "
                    f"(a reservation is required)"
                )

        for noise in (
            list(hp.prologue_noise) + list(hp.epilogue_noise)
            + list(hp.interleave_noise)
        ):
            if not NoisePool.is_safe(noise):
                raise ValueError(
                    f"noise instruction '{noise}' on hart {hp.hart_id} is "
                    f"not permitted (must be a scratch-only ALU op)"
                )

    # Every observed register must be defined by an observing event in its hart.
    by_hart = {hp.hart_id: hp for hp in program.hart_programs}
    for obs in program.observed:
        hp = by_hart.get(obs.hart)
        if hp is None:
            raise ValueError(
                f"observed register {obs.alias} references missing hart {obs.hart}"
            )
        defined = any(
            ev.kind in _OBSERVING_KINDS and ev.dst == obs.reg
            for ev in hp.modeled_window
        )
        if not defined:
            raise ValueError(
                f"observed register {obs.alias} is not defined by a "
                f"Load/AMO/LR/SC event on hart {obs.hart}"
            )
