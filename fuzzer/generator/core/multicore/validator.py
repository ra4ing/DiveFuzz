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

A valid MVP program is sound to (a) export to ``.litmus`` for the herd oracle
and (b) build into a litmus7-compatible executable. Anything that cannot be
proven safe is rejected with a specific ``ValueError``.
"""

from .model import MCProgram, EventKind

# Kinds declared in the model but unsupported by the MVP exporter.
_UNSUPPORTED_KINDS = {
    EventKind.AMO,
    EventKind.LR,
    EventKind.SC,
    EventKind.DEPENDENCY,
    EventKind.DELAY,
}
# Noise instructions permitted in the MVP (validated verbatim).
_ALLOWED_NOISE = {"nop", "addi x20,x20,0"}
# Kinds whose ``dst`` register defines an observed value.
_OBSERVING_KINDS = {EventKind.LOAD, EventKind.AMO, EventKind.LR, EventKind.SC}


def validate(program: MCProgram) -> None:
    """Raise ``ValueError`` if ``program`` is not a sound MVP seed."""
    if program.hart_count != len(program.hart_programs):
        raise ValueError(
            f"hart_count ({program.hart_count}) does not match number of "
            f"hart programs ({len(program.hart_programs)})"
        )

    shared = {v.name: v for v in program.shared_vars}

    for hp in program.hart_programs:
        if not hp.modeled_window:
            raise ValueError(f"hart {hp.hart_id} has no modeled events")

        for ev in hp.modeled_window:
            if ev.kind in _UNSUPPORTED_KINDS:
                raise ValueError(
                    f"Modeled event {ev.kind.value} is declared but not "
                    f"implemented in the MVP exporter"
                )
            if ev.width not in (4, 8):
                raise ValueError(
                    f"event width {ev.width} on hart {hp.hart_id} must be 4 or 8"
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

        for noise in list(hp.prologue_noise) + list(hp.epilogue_noise):
            if noise not in _ALLOWED_NOISE:
                raise ValueError(
                    f"noise instruction '{noise}' on hart {hp.hart_id} is not "
                    f"permitted in the MVP"
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
