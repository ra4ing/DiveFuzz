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

"""Declarative catalog of multicore test families.

Each family is a ``FamilySpec``: a named topology (hart count, value semantics)
plus a builder that turns a seed id + noise level + rng into a concrete
``MCProgram``. Builders are register-agnostic -- they obtain every physical
register from a ``RegAllocator`` and every noise instruction from a
``NoisePool``, so family topology stays decoupled from register/noise choice.
That decoupling is the seam the randomization phase will exercise.

Hart count is a property of the family, not a global knob: SB is defined as a
2-hart topology, WRC as 3-hart, IRIW as 4-hart. Generating an N-hart test means
selecting a family whose topology requires N harts. Parametric "same family at
arbitrary hart count" is a randomization-axis concern (planned, not here).

All families in this catalog use only Load/Store/Fence/FenceTso events, which
the exporter and validator fully support. AMO/LR/SC/Dependency/Delay families
are deferred to the randomization phase (they need exporter + validator
extensions).
"""

import random
from dataclasses import dataclass
from typing import Callable

from .model import EventKind, HartProgram, MCProgram, ModeledEvent, ObservedReg, SharedVar
from .noise import NoisePool
from .regalloc import RegAllocator

# Width of the shared vars (bytes); 8 -> sd/ld, uint64_t.
_WIDTH = 8
_ISA = "rv64gc"


# --------------------------------------------------------------------------- #
# Event constructors (register-agnostic; store the symbolic var name, the
# exporter resolves it through the hart's address_regs at render time).
# --------------------------------------------------------------------------- #
def _store(addr: str, value: int, value_reg: str) -> ModeledEvent:
    return ModeledEvent(
        kind=EventKind.STORE,
        addr=addr,
        value=value,
        value_reg=value_reg,
        width=_WIDTH,
    )


def _load(addr: str, dst: str) -> ModeledEvent:
    return ModeledEvent(kind=EventKind.LOAD, addr=addr, dst=dst, width=_WIDTH)


def _fence(pred: str = "rw", succ: str = "rw") -> ModeledEvent:
    return ModeledEvent(kind=EventKind.FENCE, pred=pred, succ=succ)


def _fence_tso() -> ModeledEvent:
    return ModeledEvent(kind=EventKind.FENCE_TSO)


def _obs(hart: int, reg: str) -> ObservedReg:
    return ObservedReg(hart=hart, reg=reg, alias=f"h{hart}.{reg}")


def _shared_vars(*names: str) -> list[SharedVar]:
    return [SharedVar(n, 0, _WIDTH, _WIDTH) for n in names]


def _prologue(noise_level: str, rng: random.Random, alloc: RegAllocator, hart: int) -> list[str]:
    # One noise instruction per hart prologue (L0 convention).
    return NoisePool.prologue(noise_level, 1, rng, alloc, hart)


# --------------------------------------------------------------------------- #
# Family builders. Each returns a fully concrete MCProgram.
# --------------------------------------------------------------------------- #
def _build_sb(seed_id: int, noise_level: str, rng: random.Random) -> MCProgram:
    # P0: Store(x,1); Load(y -> d0)   P1: Store(y,1); Load(x -> d1)
    alloc = RegAllocator()
    alloc.addr("x")
    alloc.addr("y")
    addr_regs = alloc.addr_regs()
    v = alloc.value()       # one value reg reused by both stores (x12)
    d0 = alloc.dst(0)       # hart0 load destination (x10)
    d1 = alloc.dst(1)       # hart1 load destination (x10)
    p0 = HartProgram(
        hart_id=0,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, rng, alloc, 0),
        modeled_window=[_store("x", 1, v), _load("y", d0)],
        epilogue_noise=[],
        result_capture=[_obs(0, d0)],
    )
    p1 = HartProgram(
        hart_id=1,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, rng, alloc, 1),
        modeled_window=[_store("y", 1, v), _load("x", d1)],
        epilogue_noise=[],
        result_capture=[_obs(1, d1)],
    )
    return MCProgram(
        seed_id=seed_id,
        name=f"SB-mc{seed_id}",
        isa=_ISA,
        hart_count=2,
        shared_vars=_shared_vars("x", "y"),
        hart_programs=[p0, p1],
        observed=[_obs(0, d0), _obs(1, d1)],
        oracle_spec={"family": "SB", "allowed_condition": "forall"},
        noise_profile=noise_level,
        metadata={"family": "SB"},
    )


def _build_lb(seed_id: int, noise_level: str, rng: random.Random) -> MCProgram:
    # P0: Load(x -> d0); Store(y,1)   P1: Load(y -> d1); Store(x,1)
    alloc = RegAllocator()
    alloc.addr("x")
    alloc.addr("y")
    addr_regs = alloc.addr_regs()
    v = alloc.value()
    d0 = alloc.dst(0)
    d1 = alloc.dst(1)
    p0 = HartProgram(
        hart_id=0,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, rng, alloc, 0),
        modeled_window=[_load("x", d0), _store("y", 1, v)],
        epilogue_noise=[],
        result_capture=[_obs(0, d0)],
    )
    p1 = HartProgram(
        hart_id=1,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, rng, alloc, 1),
        modeled_window=[_load("y", d1), _store("x", 1, v)],
        epilogue_noise=[],
        result_capture=[_obs(1, d1)],
    )
    return MCProgram(
        seed_id=seed_id,
        name=f"LB-mc{seed_id}",
        isa=_ISA,
        hart_count=2,
        shared_vars=_shared_vars("x", "y"),
        hart_programs=[p0, p1],
        observed=[_obs(0, d0), _obs(1, d1)],
        oracle_spec={"family": "LB", "allowed_condition": "forall"},
        noise_profile=noise_level,
        metadata={"family": "LB"},
    )


def _build_mp(fence_fn: Callable[[], ModeledEvent], family: str):
    """Return an MP builder using ``fence_fn`` as the inter-store barrier.

    MP and MP+fence.tso share their topology; only the fence event differs.
    """

    def _build(seed_id: int, noise_level: str, rng: random.Random) -> MCProgram:
        # P0: Store(x,1); <fence>; Store(y,1)
        # P1: Load(y -> dy); Load(x -> dx)
        alloc = RegAllocator()
        alloc.addr("x")
        alloc.addr("y")
        addr_regs = alloc.addr_regs()
        vx = alloc.value()  # x12
        vy = alloc.value()  # x13
        dy = alloc.dst(1)   # x10  (load y)
        dx = alloc.dst(1)   # x11  (load x)
        p0 = HartProgram(
            hart_id=0,
            address_regs=dict(addr_regs),
            prologue_noise=_prologue(noise_level, rng, alloc, 0),
            modeled_window=[_store("x", 1, vx), fence_fn(), _store("y", 1, vy)],
            epilogue_noise=[],
            result_capture=[],
        )
        p1 = HartProgram(
            hart_id=1,
            address_regs=dict(addr_regs),
            prologue_noise=_prologue(noise_level, rng, alloc, 1),
            modeled_window=[_load("y", dy), _load("x", dx)],
            epilogue_noise=[],
            result_capture=[_obs(1, dy), _obs(1, dx)],
        )
        return MCProgram(
            seed_id=seed_id,
            name=f"{family}-mc{seed_id}",
            isa=_ISA,
            hart_count=2,
            shared_vars=_shared_vars("x", "y"),
            hart_programs=[p0, p1],
            observed=[_obs(1, dy), _obs(1, dx)],
            oracle_spec={"family": family, "allowed_condition": "forall"},
            noise_profile=noise_level,
            metadata={"family": family},
        )

    return _build


def _build_corr(seed_id: int, noise_level: str, rng: random.Random) -> MCProgram:
    # Coherence Read-Read: P0 writes x once; P1 reads x twice.
    # RVWMO coherence forbids P1 from seeing the new value then the old.
    alloc = RegAllocator()
    alloc.addr("x")
    addr_regs = alloc.addr_regs()
    v = alloc.value()       # x12
    d0 = alloc.dst(1)       # x10
    d1 = alloc.dst(1)       # x11
    p0 = HartProgram(
        hart_id=0,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, rng, alloc, 0),
        modeled_window=[_store("x", 1, v)],
        epilogue_noise=[],
        result_capture=[],
    )
    p1 = HartProgram(
        hart_id=1,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, rng, alloc, 1),
        modeled_window=[_load("x", d0), _load("x", d1)],
        epilogue_noise=[],
        result_capture=[_obs(1, d0), _obs(1, d1)],
    )
    return MCProgram(
        seed_id=seed_id,
        name=f"CoRR-mc{seed_id}",
        isa=_ISA,
        hart_count=2,
        shared_vars=_shared_vars("x"),
        hart_programs=[p0, p1],
        observed=[_obs(1, d0), _obs(1, d1)],
        oracle_spec={"family": "CoRR", "allowed_condition": "forall"},
        noise_profile=noise_level,
        metadata={"family": "CoRR"},
    )


def _build_wrc(seed_id: int, noise_level: str, rng: random.Random) -> MCProgram:
    # Write-Read-Causality (3 harts):
    # P0: Store(x,1)
    # P1: Load(x -> d0); Store(y,1)
    # P2: Load(y -> d1); Load(x -> d2)
    # Without a fence, the forbidden outcome is P1 sees x, P2 sees y, P2 sees !x.
    alloc = RegAllocator()
    alloc.addr("x")
    alloc.addr("y")
    addr_regs = alloc.addr_regs()
    vx = alloc.value()  # x12
    vy = alloc.value()  # x13
    d0 = alloc.dst(1)   # x10
    d1 = alloc.dst(2)   # x10 (per-hart restart)
    d2 = alloc.dst(2)   # x11
    p0 = HartProgram(
        hart_id=0,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, rng, alloc, 0),
        modeled_window=[_store("x", 1, vx)],
        epilogue_noise=[],
        result_capture=[],
    )
    p1 = HartProgram(
        hart_id=1,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, rng, alloc, 1),
        modeled_window=[_load("x", d0), _store("y", 1, vy)],
        epilogue_noise=[],
        result_capture=[_obs(1, d0)],
    )
    p2 = HartProgram(
        hart_id=2,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, rng, alloc, 2),
        modeled_window=[_load("y", d1), _load("x", d2)],
        epilogue_noise=[],
        result_capture=[_obs(2, d1), _obs(2, d2)],
    )
    return MCProgram(
        seed_id=seed_id,
        name=f"WRC-mc{seed_id}",
        isa=_ISA,
        hart_count=3,
        shared_vars=_shared_vars("x", "y"),
        hart_programs=[p0, p1, p2],
        observed=[_obs(1, d0), _obs(2, d1), _obs(2, d2)],
        oracle_spec={"family": "WRC", "allowed_condition": "forall"},
        noise_profile=noise_level,
        metadata={"family": "WRC"},
    )


def _build_iriw(seed_id: int, noise_level: str, rng: random.Random) -> MCProgram:
    # Independent Reads of Independent Writes (4 harts):
    # P0: Store(x,1)   P1: Store(y,1)
    # P2: Load(y -> d0); Load(x -> d1)
    # P3: Load(x -> d2); Load(y -> d3)
    # Tests whether two independent writers are observed in a consistent order
    # by two independent readers.
    alloc = RegAllocator()
    alloc.addr("x")
    alloc.addr("y")
    addr_regs = alloc.addr_regs()
    vx = alloc.value()  # x12
    vy = alloc.value()  # x13
    d0 = alloc.dst(2)   # x10
    d1 = alloc.dst(2)   # x11
    d2 = alloc.dst(3)   # x10
    d3 = alloc.dst(3)   # x11
    p0 = HartProgram(
        hart_id=0,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, rng, alloc, 0),
        modeled_window=[_store("x", 1, vx)],
        epilogue_noise=[],
        result_capture=[],
    )
    p1 = HartProgram(
        hart_id=1,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, rng, alloc, 1),
        modeled_window=[_store("y", 1, vy)],
        epilogue_noise=[],
        result_capture=[],
    )
    p2 = HartProgram(
        hart_id=2,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, rng, alloc, 2),
        modeled_window=[_load("y", d0), _load("x", d1)],
        epilogue_noise=[],
        result_capture=[_obs(2, d0), _obs(2, d1)],
    )
    p3 = HartProgram(
        hart_id=3,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, rng, alloc, 3),
        modeled_window=[_load("x", d2), _load("y", d3)],
        epilogue_noise=[],
        result_capture=[_obs(3, d2), _obs(3, d3)],
    )
    return MCProgram(
        seed_id=seed_id,
        name=f"IRIW-mc{seed_id}",
        isa=_ISA,
        hart_count=4,
        shared_vars=_shared_vars("x", "y"),
        hart_programs=[p0, p1, p2, p3],
        observed=[_obs(2, d0), _obs(2, d1), _obs(3, d2), _obs(3, d3)],
        oracle_spec={"family": "IRIW", "allowed_condition": "forall"},
        noise_profile=noise_level,
        metadata={"family": "IRIW"},
    )


# --------------------------------------------------------------------------- #
# Catalog
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FamilySpec:
    """Declarative description of one test family."""

    name: str
    harts: int
    value_sensitive: bool
    build: Callable[[int, str, random.Random], MCProgram]


CATALOG: dict[str, FamilySpec] = {
    "SB": FamilySpec("SB", harts=2, value_sensitive=False, build=_build_sb),
    "LB": FamilySpec("LB", harts=2, value_sensitive=False, build=_build_lb),
    "MP": FamilySpec("MP", harts=2, value_sensitive=False, build=_build_mp(_fence, "MP")),
    "MPTSO": FamilySpec(
        "MPTSO", harts=2, value_sensitive=False, build=_build_mp(_fence_tso, "MPTSO")
    ),
    "CoRR": FamilySpec("CoRR", harts=2, value_sensitive=False, build=_build_corr),
    "WRC": FamilySpec("WRC", harts=3, value_sensitive=False, build=_build_wrc),
    "IRIW": FamilySpec("IRIW", harts=4, value_sensitive=False, build=_build_iriw),
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
) -> MCProgram:
    """Build a multicore test program for ``family``.

    Args:
        seed_id: Stable seed identifier.
        family: One of :func:`available_families`.
        noise_level: One of the levels supported by :class:`NoisePool`.
        rng: Seeded RNG (used for noise selection today; for register/noise
            randomization in a later phase).

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
    return spec.build(seed_id, noise_level, rng)
