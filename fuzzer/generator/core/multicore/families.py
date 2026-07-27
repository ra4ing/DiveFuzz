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

"""Test-family builders for the multicore MVP.

Only the 2-hart ``SB``, ``LB`` and ``MP`` families with ``noise_level`` in
``{"none", "L0"}`` are supported in this milestone; anything else fails fast
with an explicit ``ValueError`` rather than a best-effort seed.
"""

import random

from .model import (
    EventKind,
    SharedVar,
    ObservedReg,
    ModeledEvent,
    HartProgram,
    MCProgram,
)

# Canonical register allocation shared by every MVP family.
_ADDR_REGS = {"x": "x6", "y": "x7"}
_VALUE_REGS = ["x12", "x13"]
# Allowed L0 noise instructions (validated verbatim by the validator).
_L0_NOISE_POOL = ["nop", "addi x20,x20,0"]

# Width of the shared vars for the MVP (bytes); 8 -> sd/ld, uint64_t.
_WIDTH = 8
_ISA = "rv64gc"


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


def _fence() -> ModeledEvent:
    return ModeledEvent(kind=EventKind.FENCE, pred="rw", succ="rw")


def _obs(hart: int, reg: str) -> ObservedReg:
    return ObservedReg(hart=hart, reg=reg, alias=f"h{hart}.{reg}")


def _noise(noise_level: str, rng: random.Random) -> list[str]:
    if noise_level == "none":
        return []
    if noise_level == "L0":
        # A short deterministic-but-rng-driven sequence drawn from the allowed pool.
        return [rng.choice(_L0_NOISE_POOL), rng.choice(_L0_NOISE_POOL)]
    raise ValueError(f"Unsupported noise level for MVP: {noise_level}")


def _shared_vars() -> list[SharedVar]:
    return [SharedVar("x", 0, _WIDTH, 8), SharedVar("y", 0, _WIDTH, 8)]


def _build_sb(seed_id: int, noise_level: str, rng: random.Random) -> MCProgram:
    # P0: Store(x,1); Load(y -> x10)   P1: Store(y,1); Load(x -> x10)
    p0 = HartProgram(
        hart_id=0,
        address_regs=dict(_ADDR_REGS),
        prologue_noise=_noise(noise_level, rng),
        modeled_window=[_store("x", 1, _VALUE_REGS[0]), _load("y", "x10")],
        epilogue_noise=[],
        result_capture=[_obs(0, "x10")],
    )
    p1 = HartProgram(
        hart_id=1,
        address_regs=dict(_ADDR_REGS),
        prologue_noise=_noise(noise_level, rng),
        modeled_window=[_store("y", 1, _VALUE_REGS[0]), _load("x", "x10")],
        epilogue_noise=[],
        result_capture=[_obs(1, "x10")],
    )
    observed = [_obs(0, "x10"), _obs(1, "x10")]
    return MCProgram(
        seed_id=seed_id,
        name=f"SB-mc{seed_id}",
        isa=_ISA,
        hart_count=2,
        shared_vars=_shared_vars(),
        hart_programs=[p0, p1],
        observed=observed,
        oracle_spec={"family": "SB", "allowed_condition": "forall"},
        noise_profile=noise_level,
        metadata={"family": "SB"},
    )


def _build_lb(seed_id: int, noise_level: str, rng: random.Random) -> MCProgram:
    # P0: Load(x -> x10); Store(y,1)   P1: Load(y -> x10); Store(x,1)
    p0 = HartProgram(
        hart_id=0,
        address_regs=dict(_ADDR_REGS),
        prologue_noise=_noise(noise_level, rng),
        modeled_window=[_load("x", "x10"), _store("y", 1, _VALUE_REGS[0])],
        epilogue_noise=[],
        result_capture=[_obs(0, "x10")],
    )
    p1 = HartProgram(
        hart_id=1,
        address_regs=dict(_ADDR_REGS),
        prologue_noise=_noise(noise_level, rng),
        modeled_window=[_load("y", "x10"), _store("x", 1, _VALUE_REGS[0])],
        epilogue_noise=[],
        result_capture=[_obs(1, "x10")],
    )
    observed = [_obs(0, "x10"), _obs(1, "x10")]
    return MCProgram(
        seed_id=seed_id,
        name=f"LB-mc{seed_id}",
        isa=_ISA,
        hart_count=2,
        shared_vars=_shared_vars(),
        hart_programs=[p0, p1],
        observed=observed,
        oracle_spec={"family": "LB", "allowed_condition": "forall"},
        noise_profile=noise_level,
        metadata={"family": "LB"},
    )


def _build_mp(seed_id: int, noise_level: str, rng: random.Random) -> MCProgram:
    # P0: Store(x,1); Fence(rw,rw); Store(y,1)
    # P1: Load(y -> x10); Load(x -> x11)
    p0 = HartProgram(
        hart_id=0,
        address_regs=dict(_ADDR_REGS),
        prologue_noise=_noise(noise_level, rng),
        modeled_window=[
            _store("x", 1, _VALUE_REGS[0]),
            _fence(),
            _store("y", 1, _VALUE_REGS[1]),
        ],
        epilogue_noise=[],
        result_capture=[],
    )
    p1 = HartProgram(
        hart_id=1,
        address_regs=dict(_ADDR_REGS),
        prologue_noise=_noise(noise_level, rng),
        modeled_window=[_load("y", "x10"), _load("x", "x11")],
        epilogue_noise=[],
        result_capture=[_obs(1, "x10"), _obs(1, "x11")],
    )
    observed = [_obs(1, "x10"), _obs(1, "x11")]
    return MCProgram(
        seed_id=seed_id,
        name=f"MP-mc{seed_id}",
        isa=_ISA,
        hart_count=2,
        shared_vars=_shared_vars(),
        hart_programs=[p0, p1],
        observed=observed,
        oracle_spec={"family": "MP", "allowed_condition": "forall"},
        noise_profile=noise_level,
        metadata={"family": "MP"},
    )


_BUILDERS = {"SB": _build_sb, "LB": _build_lb, "MP": _build_mp}


def build_program(
    seed_id: int,
    family: str,
    hart_count: int,
    noise_level: str,
    rng: random.Random,
) -> MCProgram:
    """Build a multicore test program for one MVP family.

    Args:
        seed_id: Stable seed identifier.
        family: One of ``"SB"``, ``"LB"``, ``"MP"``.
        hart_count: Must be ``2`` for the MVP.
        noise_level: One of ``"none"``, ``"L0"``.
        rng: Seeded RNG for deterministic-but-varied noise.

    Raises:
        ValueError: for unsupported family, hart count, or noise level.
    """
    if hart_count != 2:
        raise ValueError("Only hart_count=2 is implemented for the multicore MVP")
    builder = _BUILDERS.get(family)
    if builder is None:
        raise ValueError(f"Unsupported multicore test family for MVP: {family}")
    # Validate noise level eagerly so an unsupported value fails before building.
    if noise_level not in ("none", "L0"):
        raise ValueError(f"Unsupported noise level for MVP: {noise_level}")
    return builder(seed_id, noise_level, rng)
