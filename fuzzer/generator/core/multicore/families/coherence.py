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

from ..model import HartProgram, MCProgram
from .events import _distinct_values, _load, _obs, _prologue, _shared_vars, _store
from .genctx import GenCtx, _ISA

def _build_corr(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # Coherence Read-Read: P0 writes x once; P1 reads x twice.
    # RVWMO coherence forbids P1 from seeing the new value then the old.
    alloc = ctx.alloc
    alloc.addr("x")
    addr_regs = alloc.addr_regs()
    vreg = alloc.value()
    vx = ctx.store_value()
    d0 = alloc.dst(1)
    d1 = alloc.dst(1)
    p0 = HartProgram(
        hart_id=0,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[_store("x", vx, vreg)],
        epilogue_noise=[],
        result_capture=[],
    )
    p1 = HartProgram(
        hart_id=1,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[
            _load("x", d0),
            _load("x", d1),
        ],
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


def _build_cowr(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # Coherence Write-Read (2 harts): P0 writes x then reads it back; P1 writes
    # a distinct competing value. CoWR forbids P0 from reading the stale initial
    # value after its own store -- it must see its own value or P1's.
    alloc = ctx.alloc
    alloc.addr("x")
    addr_regs = alloc.addr_regs()
    vreg = alloc.value()
    v0, v1 = _distinct_values(ctx, 2)
    d0 = alloc.dst(0)
    p0 = HartProgram(
        hart_id=0,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[_store("x", v0, vreg), _load("x", d0)],
        epilogue_noise=[],
        result_capture=[_obs(0, d0)],
    )
    p1 = HartProgram(
        hart_id=1,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[_store("x", v1, vreg)],
        epilogue_noise=[],
        result_capture=[],
    )
    return MCProgram(
        seed_id=seed_id,
        name=f"CoWR-mc{seed_id}",
        isa=_ISA,
        hart_count=2,
        shared_vars=_shared_vars("x"),
        hart_programs=[p0, p1],
        observed=[_obs(0, d0)],
        oracle_spec={"family": "CoWR", "allowed_condition": "forall"},
        noise_profile=noise_level,
        metadata={"family": "CoWR"},
    )


def _build_corw(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # Coherence Read-Write (2 harts): P0 reads x, writes its own value, reads x
    # again; P1 writes a distinct competing value. The two observed reads probe
    # whether P0's own write and P1's write stay coherence-consistent.
    alloc = ctx.alloc
    alloc.addr("x")
    addr_regs = alloc.addr_regs()
    vreg = alloc.value()
    v0, v1 = _distinct_values(ctx, 2)
    d0 = alloc.dst(0)
    d1 = alloc.dst(0)
    p0 = HartProgram(
        hart_id=0,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[_load("x", d0), _store("x", v0, vreg), _load("x", d1)],
        epilogue_noise=[],
        result_capture=[_obs(0, d0), _obs(0, d1)],
    )
    p1 = HartProgram(
        hart_id=1,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[_store("x", v1, vreg)],
        epilogue_noise=[],
        result_capture=[],
    )
    return MCProgram(
        seed_id=seed_id,
        name=f"CoRW-mc{seed_id}",
        isa=_ISA,
        hart_count=2,
        shared_vars=_shared_vars("x"),
        hart_programs=[p0, p1],
        observed=[_obs(0, d0), _obs(0, d1)],
        oracle_spec={"family": "CoRW", "allowed_condition": "forall"},
        noise_profile=noise_level,
        metadata={"family": "CoRW"},
    )


def _build_coww(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # Coherence Write-Write (2 harts): P0 writes two distinct values to x in
    # program order; P1 reads x. P1 may observe the initial value, P0's first
    # value, or P0's second value -- but never an out-of-coherence-order value.
    alloc = ctx.alloc
    alloc.addr("x")
    addr_regs = alloc.addr_regs()
    vreg = alloc.value()
    v0, v1 = _distinct_values(ctx, 2)
    d0 = alloc.dst(1)
    p0 = HartProgram(
        hart_id=0,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[_store("x", v0, vreg), _store("x", v1, vreg)],
        epilogue_noise=[],
        result_capture=[],
    )
    p1 = HartProgram(
        hart_id=1,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[_load("x", d0)],
        epilogue_noise=[],
        result_capture=[_obs(1, d0)],
    )
    return MCProgram(
        seed_id=seed_id,
        name=f"CoWW-mc{seed_id}",
        isa=_ISA,
        hart_count=2,
        shared_vars=_shared_vars("x"),
        hart_programs=[p0, p1],
        observed=[_obs(1, d0)],
        oracle_spec={"family": "CoWW", "allowed_condition": "forall"},
        noise_profile=noise_level,
        metadata={"family": "CoWW"},
    )


