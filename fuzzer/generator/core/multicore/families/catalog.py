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

import random
from dataclasses import dataclass, replace
from typing import Callable

from ..model import EventKind, MCProgram
from ..noise import NoisePool
from .genctx import GenCtx
from .atomics import _build_amo, _build_lrsc, _build_mp_acqrel
from .coherence import _build_corr, _build_corw, _build_cowr, _build_coww
from .dependency import _build_lbadc, _build_lbdep, _build_rdw, _build_rsw
from .multithread import (
    _build_3_2w, _build_3lb, _build_3sb, _build_iriw, _build_irrwiw, _build_irwiw,
    _build_isa2, _build_rwc, _build_w, _build_wrc, _build_wrr, _build_wrw,
    _build_wwc, _build_z6_0, _build_z6_1, _build_z6_2, _build_z6_3, _build_z6_4,
    _build_z6_5,
)
from .plain import _build_2plus2w, _build_lb, _build_mp, _build_r, _build_s, _build_sb

@dataclass(frozen=True)
class FamilySpec:
    """Declarative description of one test family."""

    name: str
    harts: int
    value_sensitive: bool
    build: Callable[[int, GenCtx, str], MCProgram]


CATALOG: dict[str, FamilySpec] = {
    "SB": FamilySpec("SB", harts=2, value_sensitive=False, build=_build_sb),
    "LB": FamilySpec("LB", harts=2, value_sensitive=False, build=_build_lb),
    "MP": FamilySpec("MP", harts=2, value_sensitive=False, build=_build_mp("fence", "MP")),
    "MPTSO": FamilySpec(
        "MPTSO", harts=2, value_sensitive=False, build=_build_mp("fence_tso", "MPTSO")
    ),
    "CoRR": FamilySpec("CoRR", harts=2, value_sensitive=False, build=_build_corr),
    "WRC": FamilySpec("WRC", harts=3, value_sensitive=False, build=_build_wrc),
    "IRIW": FamilySpec("IRIW", harts=4, value_sensitive=False, build=_build_iriw),
    "AMO": FamilySpec("AMO", harts=2, value_sensitive=False, build=_build_amo),
    "LRSC": FamilySpec("LRSC", harts=2, value_sensitive=False, build=_build_lrsc),
    "CoWR": FamilySpec("CoWR", harts=2, value_sensitive=True, build=_build_cowr),
    "CoRW": FamilySpec("CoRW", harts=2, value_sensitive=True, build=_build_corw),
    "CoWW": FamilySpec("CoWW", harts=2, value_sensitive=True, build=_build_coww),
    "2+2W": FamilySpec("2+2W", harts=3, value_sensitive=True, build=_build_2plus2w),
    "LBdep": FamilySpec("LBdep", harts=2, value_sensitive=False, build=_build_lbdep),
    "LBadc": FamilySpec("LBadc", harts=2, value_sensitive=False, build=_build_lbadc),
    "S": FamilySpec("S", harts=2, value_sensitive=True, build=_build_s),
    "R": FamilySpec("R", harts=2, value_sensitive=True, build=_build_r),
    "RWC": FamilySpec("RWC", harts=3, value_sensitive=False, build=_build_rwc),
    "MPAcqRel": FamilySpec(
        "MPAcqRel", harts=2, value_sensitive=False, build=_build_mp_acqrel
    ),
    "WWC": FamilySpec("WWC", harts=3, value_sensitive=True, build=_build_wwc),
    "WRW": FamilySpec("WRW", harts=3, value_sensitive=True, build=_build_wrw),
    "WRR": FamilySpec("WRR", harts=3, value_sensitive=True, build=_build_wrr),
    "ISA2": FamilySpec("ISA2", harts=3, value_sensitive=False, build=_build_isa2),
    "W": FamilySpec("W", harts=3, value_sensitive=False, build=_build_w),
    "3.LB": FamilySpec("3.LB", harts=3, value_sensitive=False, build=_build_3lb),
    "3.SB": FamilySpec("3.SB", harts=3, value_sensitive=False, build=_build_3sb),
    "Z6.0": FamilySpec("Z6.0", harts=3, value_sensitive=True, build=_build_z6_0),
    "Z6.1": FamilySpec("Z6.1", harts=3, value_sensitive=True, build=_build_z6_1),
    "Z6.2": FamilySpec("Z6.2", harts=3, value_sensitive=True, build=_build_z6_2),
    "Z6.3": FamilySpec("Z6.3", harts=3, value_sensitive=True, build=_build_z6_3),
    "Z6.4": FamilySpec("Z6.4", harts=3, value_sensitive=True, build=_build_z6_4),
    "Z6.5": FamilySpec("Z6.5", harts=3, value_sensitive=True, build=_build_z6_5),
    "IRWIW": FamilySpec("IRWIW", harts=4, value_sensitive=True, build=_build_irwiw),
    "IRRWIW": FamilySpec("IRRWIW", harts=4, value_sensitive=True, build=_build_irrwiw),
    "3.2W": FamilySpec("3.2W", harts=3, value_sensitive=True, build=_build_3_2w),
    "RDW": FamilySpec("RDW", harts=3, value_sensitive=False, build=_build_rdw),
    "RSW": FamilySpec("RSW", harts=2, value_sensitive=False, build=_build_rsw),
}


def available_families() -> list[str]:
    """Names of all registered families."""
    return sorted(CATALOG)


def families_for_hart_count(hart_count: int) -> list[str]:
    """Names of families whose topology requires exactly ``hart_count`` harts."""
    return sorted(name for name, spec in CATALOG.items() if spec.harts == hart_count)


def family_hart_count(family: str) -> int:
    """The hart count a family's topology requires."""
    spec = CATALOG.get(family)
    if spec is None:
        raise ValueError(
            f"Unknown multicore test family: {family!r}. "
            f"Known: {available_families()}"
        )
    return spec.harts


def build_program(
    seed_id: int,
    family: str,
    noise_level: str,
    rng: random.Random,
    *,
    randomize: bool = False,
) -> MCProgram:
    """Build a multicore test program for ``family``.

    Args:
        seed_id: Stable seed identifier.
        family: One of :func:`available_families`.
        noise_level: One of the levels supported by :class:`NoisePool`.
        rng: Seeded RNG (drives noise selection now; register/value/fence
            randomization, address aliasing, and width mixing when
            ``randomize`` is set).
        randomize: Enable the sound-by-construction axes (register allocation,
            store values, fence pred/succ, same-word aliasing, access-width
            mixing). Off by default to reproduce the spike-verified seeds.

    Raises:
        ValueError: for unknown family or unsupported noise level.
    """
    spec = CATALOG.get(family)
    if spec is None:
        raise ValueError(
            f"Unknown multicore test family: {family!r}. "
            f"Known: {available_families()}"
        )
    if not NoisePool.is_supported(noise_level):
        raise ValueError(
            f"Unsupported noise level: {noise_level!r}. Supported: none, "
            f"{', '.join(NoisePool.supported_levels())}"
        )
    ctx = GenCtx(rng, randomize)
    program = spec.build(seed_id, ctx, noise_level)
    # Apply the same-word aliasing axis post-build from the program's shared
    # vars (no per-family change needed).
    program.alias_map = ctx.alias_map([v.name for v in program.shared_vars])
    # Width-mixing axis: re-width each Load/Store event from the rng.
    # ModeledEvent is frozen, so rebuild via dataclasses.replace.
    for hp in program.hart_programs:
        hp.modeled_window = [
            replace(ev, width=ctx.access_width())
            if ev.kind in (EventKind.LOAD, EventKind.STORE)
            else ev
            for ev in hp.modeled_window
        ]
    # L1 interleaving: one scratch-only noise instruction after each window
    # event, to separate the loads/stores in time. Sound because noise writes
    # only x20, which is never live in the modeled window.
    if noise_level == "L1":
        for hp in program.hart_programs:
            hp.interleave_noise = NoisePool.sample(
                "L1", len(hp.modeled_window), ctx.rng
            )
    return program
