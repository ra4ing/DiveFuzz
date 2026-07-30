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

def _build_wrc(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # Write-Read-Causality (3 harts):
    # P0: Store(x,vx)
    # P1: Load(x -> d0); Store(y,vy)
    # P2: Load(y -> d1); Load(x -> d2)
    alloc = ctx.alloc
    alloc.addr("x")
    alloc.addr("y")
    addr_regs = alloc.addr_regs()
    vx_reg = alloc.value()
    vy_reg = alloc.value()
    vx = ctx.store_value()
    vy = ctx.store_value()
    d0 = alloc.dst(1)
    d1 = alloc.dst(2)
    d2 = alloc.dst(2)
    p0 = HartProgram(
        hart_id=0,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[_store("x", vx, vx_reg)],
        epilogue_noise=[],
        result_capture=[],
    )
    p1 = HartProgram(
        hart_id=1,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[
            _load("x", d0),
            _store("y", vy, vy_reg),
        ],
        epilogue_noise=[],
        result_capture=[_obs(1, d0)],
    )
    p2 = HartProgram(
        hart_id=2,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 2),
        modeled_window=[
            _load("y", d1),
            _load("x", d2),
        ],
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


def _build_iriw(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # Independent Reads of Independent Writes (4 harts):
    # P0: Store(x,vx)   P1: Store(y,vy)
    # P2: Load(y -> d0); Load(x -> d1)
    # P3: Load(x -> d2); Load(y -> d3)
    alloc = ctx.alloc
    alloc.addr("x")
    alloc.addr("y")
    addr_regs = alloc.addr_regs()
    vx_reg = alloc.value()
    vy_reg = alloc.value()
    vx = ctx.store_value()
    vy = ctx.store_value()
    d0 = alloc.dst(2)
    d1 = alloc.dst(2)
    d2 = alloc.dst(3)
    d3 = alloc.dst(3)
    p0 = HartProgram(
        hart_id=0,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[_store("x", vx, vx_reg)],
        epilogue_noise=[],
        result_capture=[],
    )
    p1 = HartProgram(
        hart_id=1,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[_store("y", vy, vy_reg)],
        epilogue_noise=[],
        result_capture=[],
    )
    p2 = HartProgram(
        hart_id=2,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 2),
        modeled_window=[
            _load("y", d0),
            _load("x", d1),
        ],
        epilogue_noise=[],
        result_capture=[_obs(2, d0), _obs(2, d1)],
    )
    p3 = HartProgram(
        hart_id=3,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 3),
        modeled_window=[
            _load("x", d2),
            _load("y", d3),
        ],
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


def _build_rwc(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # RWC (Read-Write-Causality, 3 harts): P0 writes x; P1 reads x then y;
    # P2 writes y then reads x. Probes independent visibility of two writes to
    # two readers -- a multi-hart analogue of MP. Value-insensitive: the two
    # writes hit different locations (x and y), so equal values stay sound.
    alloc = ctx.alloc
    alloc.addr("x")
    alloc.addr("y")
    addr_regs = alloc.addr_regs()
    vx_reg = alloc.value()
    vy_reg = alloc.value()
    vx = ctx.store_value()
    vy = ctx.store_value()
    d0 = alloc.dst(1)
    d1 = alloc.dst(1)
    d2 = alloc.dst(2)
    p0 = HartProgram(
        hart_id=0,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[_store("x", vx, vx_reg)],
        epilogue_noise=[],
        result_capture=[],
    )
    p1 = HartProgram(
        hart_id=1,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[
            _load("x", d0),
            _load("y", d1),
        ],
        epilogue_noise=[],
        result_capture=[_obs(1, d0), _obs(1, d1)],
    )
    p2 = HartProgram(
        hart_id=2,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 2),
        modeled_window=[
            _store("y", vy, vy_reg),
            _load("x", d2),
        ],
        epilogue_noise=[],
        result_capture=[_obs(2, d2)],
    )
    return MCProgram(
        seed_id=seed_id,
        name=f"RWC-mc{seed_id}",
        isa=_ISA,
        hart_count=3,
        shared_vars=_shared_vars("x", "y"),
        hart_programs=[p0, p1, p2],
        observed=[_obs(1, d0), _obs(1, d1), _obs(2, d2)],
        oracle_spec={"family": "RWC", "allowed_condition": "forall"},
        noise_profile=noise_level,
        metadata={"family": "RWC"},
    )


def _build_wwc(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # WWC (Write-Write-Causality, 3 harts): P0 writes x; P1 reads x then writes
    # y; P2 reads y then writes x. Probes causality across two locations with
    # competing writes to x. Value-sensitive (x written by P0 and P2).
    alloc = ctx.alloc
    alloc.addr("x")
    alloc.addr("y")
    addr_regs = alloc.addr_regs()
    vreg = alloc.value()
    vx0, vy, vx1 = _distinct_values(ctx, 3)
    d0 = alloc.dst(1)
    d1 = alloc.dst(2)
    p0 = HartProgram(
        hart_id=0, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[_store("x", vx0, vreg)], epilogue_noise=[], result_capture=[],
    )
    p1 = HartProgram(
        hart_id=1, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[_load("x", d0), _store("y", vy, vreg)],
        epilogue_noise=[], result_capture=[_obs(1, d0)],
    )
    p2 = HartProgram(
        hart_id=2, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 2),
        modeled_window=[_load("y", d1), _store("x", vx1, vreg)],
        epilogue_noise=[], result_capture=[_obs(2, d1)],
    )
    return MCProgram(
        seed_id=seed_id, name=f"WWC-mc{seed_id}", isa=_ISA, hart_count=3,
        shared_vars=_shared_vars("x", "y"), hart_programs=[p0, p1, p2],
        observed=[_obs(1, d0), _obs(2, d1)],
        oracle_spec={"family": "WWC", "allowed_condition": "forall"},
        noise_profile=noise_level, metadata={"family": "WWC"},
    )


def _build_wrw(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # WRW (Write-Read-Write, 3 harts): P0 writes x; P1 reads x then writes y;
    # P2 writes y then writes x. Competing writes to both x and y.
    alloc = ctx.alloc
    alloc.addr("x")
    alloc.addr("y")
    addr_regs = alloc.addr_regs()
    vreg = alloc.value()
    vx0, vy0, vy1, vx1 = _distinct_values(ctx, 4)
    d0 = alloc.dst(1)
    p0 = HartProgram(
        hart_id=0, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[_store("x", vx0, vreg)], epilogue_noise=[], result_capture=[],
    )
    p1 = HartProgram(
        hart_id=1, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[_load("x", d0), _store("y", vy0, vreg)],
        epilogue_noise=[], result_capture=[_obs(1, d0)],
    )
    p2 = HartProgram(
        hart_id=2, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 2),
        modeled_window=[_store("y", vy1, vreg), _store("x", vx1, vreg)],
        epilogue_noise=[], result_capture=[],
    )
    return MCProgram(
        seed_id=seed_id, name=f"WRW-mc{seed_id}", isa=_ISA, hart_count=3,
        shared_vars=_shared_vars("x", "y"), hart_programs=[p0, p1, p2],
        observed=[_obs(1, d0)],
        oracle_spec={"family": "WRW", "allowed_condition": "forall"},
        noise_profile=noise_level, metadata={"family": "WRW"},
    )


def _build_wrr(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # WRR (Write-Read-Read, 3 harts): P0 writes x; P1 reads x then reads y;
    # P2 writes y then writes x. Competing writes to x.
    alloc = ctx.alloc
    alloc.addr("x")
    alloc.addr("y")
    addr_regs = alloc.addr_regs()
    vreg = alloc.value()
    vx0, vy, vx1 = _distinct_values(ctx, 3)
    d0 = alloc.dst(1)
    d1 = alloc.dst(1)
    p0 = HartProgram(
        hart_id=0, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[_store("x", vx0, vreg)], epilogue_noise=[], result_capture=[],
    )
    p1 = HartProgram(
        hart_id=1, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[_load("x", d0), _load("y", d1)],
        epilogue_noise=[], result_capture=[_obs(1, d0), _obs(1, d1)],
    )
    p2 = HartProgram(
        hart_id=2, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 2),
        modeled_window=[_store("y", vy, vreg), _store("x", vx1, vreg)],
        epilogue_noise=[], result_capture=[],
    )
    return MCProgram(
        seed_id=seed_id, name=f"WRR-mc{seed_id}", isa=_ISA, hart_count=3,
        shared_vars=_shared_vars("x", "y"), hart_programs=[p0, p1, p2],
        observed=[_obs(1, d0), _obs(1, d1)],
        oracle_spec={"family": "WRR", "allowed_condition": "forall"},
        noise_profile=noise_level, metadata={"family": "WRR"},
    )


def _build_isa2(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # ISA2 (3 harts, 3 vars x->y->z->x): P0 writes x then y; P1 reads y then
    # writes z; P2 reads z then reads x. A canonical 3-thread MP-causality cycle
    # (one of the most cited litmus tests). Value-insensitive (no competing
    # writes).
    alloc = ctx.alloc
    alloc.addr("x")
    alloc.addr("y")
    alloc.addr("z")
    addr_regs = alloc.addr_regs()
    vreg = alloc.value()
    v = ctx.store_value()
    d0 = alloc.dst(1)
    d1 = alloc.dst(2)
    d2 = alloc.dst(2)
    p0 = HartProgram(
        hart_id=0, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[_store("x", v, vreg), _store("y", v, vreg)],
        epilogue_noise=[], result_capture=[],
    )
    p1 = HartProgram(
        hart_id=1, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[_load("y", d0), _store("z", v, vreg)],
        epilogue_noise=[], result_capture=[_obs(1, d0)],
    )
    p2 = HartProgram(
        hart_id=2, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 2),
        modeled_window=[_load("z", d1), _load("x", d2)],
        epilogue_noise=[], result_capture=[_obs(2, d1), _obs(2, d2)],
    )
    return MCProgram(
        seed_id=seed_id, name=f"ISA2-mc{seed_id}", isa=_ISA, hart_count=3,
        shared_vars=_shared_vars("x", "y", "z"), hart_programs=[p0, p1, p2],
        observed=[_obs(1, d0), _obs(2, d1), _obs(2, d2)],
        oracle_spec={"family": "ISA2", "allowed_condition": "forall"},
        noise_profile=noise_level, metadata={"family": "ISA2"},
    )


def _build_w(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # W (3 harts, 3 vars): P0 writes x then y; P1 reads y then reads z; P2
    # writes z then reads x. A 3-var generalization of RWC. Value-insensitive.
    alloc = ctx.alloc
    alloc.addr("x")
    alloc.addr("y")
    alloc.addr("z")
    addr_regs = alloc.addr_regs()
    vreg = alloc.value()
    v = ctx.store_value()
    d0 = alloc.dst(1)
    d1 = alloc.dst(1)
    d2 = alloc.dst(2)
    p0 = HartProgram(
        hart_id=0, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[_store("x", v, vreg), _store("y", v, vreg)],
        epilogue_noise=[], result_capture=[],
    )
    p1 = HartProgram(
        hart_id=1, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[_load("y", d0), _load("z", d1)],
        epilogue_noise=[], result_capture=[_obs(1, d0), _obs(1, d1)],
    )
    p2 = HartProgram(
        hart_id=2, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 2),
        modeled_window=[_store("z", v, vreg), _load("x", d2)],
        epilogue_noise=[], result_capture=[_obs(2, d2)],
    )
    return MCProgram(
        seed_id=seed_id, name=f"W-mc{seed_id}", isa=_ISA, hart_count=3,
        shared_vars=_shared_vars("x", "y", "z"), hart_programs=[p0, p1, p2],
        observed=[_obs(1, d0), _obs(1, d1), _obs(2, d2)],
        oracle_spec={"family": "W", "allowed_condition": "forall"},
        noise_profile=noise_level, metadata={"family": "W"},
    )


def _build_3lb(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # 3.LB (3 harts, 3 vars): each hart reads one location then writes the next
    # in the cycle x->y->z->x. The 3-thread load-buffering cycle.
    alloc = ctx.alloc
    alloc.addr("x")
    alloc.addr("y")
    alloc.addr("z")
    addr_regs = alloc.addr_regs()
    vreg = alloc.value()
    v = ctx.store_value()
    d0 = alloc.dst(0)
    d1 = alloc.dst(1)
    d2 = alloc.dst(2)
    p0 = HartProgram(
        hart_id=0, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[_load("x", d0), _store("y", v, vreg)],
        epilogue_noise=[], result_capture=[_obs(0, d0)],
    )
    p1 = HartProgram(
        hart_id=1, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[_load("y", d1), _store("z", v, vreg)],
        epilogue_noise=[], result_capture=[_obs(1, d1)],
    )
    p2 = HartProgram(
        hart_id=2, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 2),
        modeled_window=[_load("z", d2), _store("x", v, vreg)],
        epilogue_noise=[], result_capture=[_obs(2, d2)],
    )
    return MCProgram(
        seed_id=seed_id, name=f"3.LB-mc{seed_id}", isa=_ISA, hart_count=3,
        shared_vars=_shared_vars("x", "y", "z"), hart_programs=[p0, p1, p2],
        observed=[_obs(0, d0), _obs(1, d1), _obs(2, d2)],
        oracle_spec={"family": "3.LB", "allowed_condition": "forall"},
        noise_profile=noise_level, metadata={"family": "3.LB"},
    )


def _build_3sb(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # 3.SB (3 harts, 3 vars): each hart writes one location then reads the next
    # in the cycle x->y->z->x. The 3-thread store-buffering cycle.
    alloc = ctx.alloc
    alloc.addr("x")
    alloc.addr("y")
    alloc.addr("z")
    addr_regs = alloc.addr_regs()
    vreg = alloc.value()
    v = ctx.store_value()
    d0 = alloc.dst(0)
    d1 = alloc.dst(1)
    d2 = alloc.dst(2)
    p0 = HartProgram(
        hart_id=0, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[_store("x", v, vreg), _load("y", d0)],
        epilogue_noise=[], result_capture=[_obs(0, d0)],
    )
    p1 = HartProgram(
        hart_id=1, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[_store("y", v, vreg), _load("z", d1)],
        epilogue_noise=[], result_capture=[_obs(1, d1)],
    )
    p2 = HartProgram(
        hart_id=2, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 2),
        modeled_window=[_store("z", v, vreg), _load("x", d2)],
        epilogue_noise=[], result_capture=[_obs(2, d2)],
    )
    return MCProgram(
        seed_id=seed_id, name=f"3.SB-mc{seed_id}", isa=_ISA, hart_count=3,
        shared_vars=_shared_vars("x", "y", "z"), hart_programs=[p0, p1, p2],
        observed=[_obs(0, d0), _obs(1, d1), _obs(2, d2)],
        oracle_spec={"family": "3.SB", "allowed_condition": "forall"},
        noise_profile=noise_level, metadata={"family": "3.SB"},
    )


def _build_z6_0(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # Z6.0 (3 harts, 3 vars): P0 writes x,y; P1 reads y writes z; P2 writes z
    # reads x. Coherence/anomaly cycle; competing writes to z. Value-sensitive.
    alloc = ctx.alloc
    alloc.addr("x"); alloc.addr("y"); alloc.addr("z")
    addr_regs = alloc.addr_regs()
    vreg = alloc.value()
    vx, vy, vz0, vz1 = _distinct_values(ctx, 4)
    d0 = alloc.dst(1)
    d1 = alloc.dst(2)
    p0 = HartProgram(hart_id=0, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[_store("x", vx, vreg), _store("y", vy, vreg)],
        epilogue_noise=[], result_capture=[])
    p1 = HartProgram(hart_id=1, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[_load("y", d0), _store("z", vz0, vreg)],
        epilogue_noise=[], result_capture=[_obs(1, d0)])
    p2 = HartProgram(hart_id=2, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 2),
        modeled_window=[_store("z", vz1, vreg), _load("x", d1)],
        epilogue_noise=[], result_capture=[_obs(2, d1)])
    return MCProgram(seed_id=seed_id, name=f"Z6.0-mc{seed_id}", isa=_ISA,
        hart_count=3, shared_vars=_shared_vars("x", "y", "z"),
        hart_programs=[p0, p1, p2], observed=[_obs(1, d0), _obs(2, d1)],
        oracle_spec={"family": "Z6.0", "allowed_condition": "forall"},
        noise_profile=noise_level, metadata={"family": "Z6.0"})


def _build_z6_1(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # Z6.1 (3 harts, 3 vars): P0 writes x,y; P1 writes y,z; P2 reads z writes x.
    # Competing writes to x and y. Value-sensitive.
    alloc = ctx.alloc
    alloc.addr("x"); alloc.addr("y"); alloc.addr("z")
    addr_regs = alloc.addr_regs()
    vreg = alloc.value()
    vx0, vy0, vy1, vz, vx1 = _distinct_values(ctx, 5)
    d0 = alloc.dst(2)
    p0 = HartProgram(hart_id=0, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[_store("x", vx0, vreg), _store("y", vy0, vreg)],
        epilogue_noise=[], result_capture=[])
    p1 = HartProgram(hart_id=1, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[_store("y", vy1, vreg), _store("z", vz, vreg)],
        epilogue_noise=[], result_capture=[])
    p2 = HartProgram(hart_id=2, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 2),
        modeled_window=[_load("z", d0), _store("x", vx1, vreg)],
        epilogue_noise=[], result_capture=[_obs(2, d0)])
    return MCProgram(seed_id=seed_id, name=f"Z6.1-mc{seed_id}", isa=_ISA,
        hart_count=3, shared_vars=_shared_vars("x", "y", "z"),
        hart_programs=[p0, p1, p2], observed=[_obs(2, d0)],
        oracle_spec={"family": "Z6.1", "allowed_condition": "forall"},
        noise_profile=noise_level, metadata={"family": "Z6.1"})


def _build_z6_2(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # Z6.2 (3 harts, 3 vars): P0 writes x,y; P1 reads y writes z; P2 reads z
    # writes x. Competing writes to x. Value-sensitive.
    alloc = ctx.alloc
    alloc.addr("x"); alloc.addr("y"); alloc.addr("z")
    addr_regs = alloc.addr_regs()
    vreg = alloc.value()
    vx0, vy, vz, vx1 = _distinct_values(ctx, 4)
    d0 = alloc.dst(1)
    d1 = alloc.dst(2)
    p0 = HartProgram(hart_id=0, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[_store("x", vx0, vreg), _store("y", vy, vreg)],
        epilogue_noise=[], result_capture=[])
    p1 = HartProgram(hart_id=1, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[_load("y", d0), _store("z", vz, vreg)],
        epilogue_noise=[], result_capture=[_obs(1, d0)])
    p2 = HartProgram(hart_id=2, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 2),
        modeled_window=[_load("z", d1), _store("x", vx1, vreg)],
        epilogue_noise=[], result_capture=[_obs(2, d1)])
    return MCProgram(seed_id=seed_id, name=f"Z6.2-mc{seed_id}", isa=_ISA,
        hart_count=3, shared_vars=_shared_vars("x", "y", "z"),
        hart_programs=[p0, p1, p2], observed=[_obs(1, d0), _obs(2, d1)],
        oracle_spec={"family": "Z6.2", "allowed_condition": "forall"},
        noise_profile=noise_level, metadata={"family": "Z6.2"})


def _build_z6_3(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # Z6.3 (3 harts, 3 vars): P0 writes x,y; P1 writes y,z; P2 reads z reads x.
    # Competing writes to y. Value-sensitive.
    alloc = ctx.alloc
    alloc.addr("x"); alloc.addr("y"); alloc.addr("z")
    addr_regs = alloc.addr_regs()
    vreg = alloc.value()
    vx, vy0, vy1, vz = _distinct_values(ctx, 4)
    d0 = alloc.dst(2)
    d1 = alloc.dst(2)
    p0 = HartProgram(hart_id=0, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[_store("x", vx, vreg), _store("y", vy0, vreg)],
        epilogue_noise=[], result_capture=[])
    p1 = HartProgram(hart_id=1, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[_store("y", vy1, vreg), _store("z", vz, vreg)],
        epilogue_noise=[], result_capture=[])
    p2 = HartProgram(hart_id=2, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 2),
        modeled_window=[_load("z", d0), _load("x", d1)],
        epilogue_noise=[], result_capture=[_obs(2, d0), _obs(2, d1)])
    return MCProgram(seed_id=seed_id, name=f"Z6.3-mc{seed_id}", isa=_ISA,
        hart_count=3, shared_vars=_shared_vars("x", "y", "z"),
        hart_programs=[p0, p1, p2], observed=[_obs(2, d0), _obs(2, d1)],
        oracle_spec={"family": "Z6.3", "allowed_condition": "forall"},
        noise_profile=noise_level, metadata={"family": "Z6.3"})


def _build_z6_4(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # Z6.4 (3 harts, 3 vars): P0 writes x,y; P1 writes y reads z; P2 writes z
    # reads x. Competing writes to y. Value-sensitive.
    alloc = ctx.alloc
    alloc.addr("x"); alloc.addr("y"); alloc.addr("z")
    addr_regs = alloc.addr_regs()
    vreg = alloc.value()
    vx, vy0, vy1, vz = _distinct_values(ctx, 4)
    d0 = alloc.dst(1)
    d1 = alloc.dst(2)
    p0 = HartProgram(hart_id=0, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[_store("x", vx, vreg), _store("y", vy0, vreg)],
        epilogue_noise=[], result_capture=[])
    p1 = HartProgram(hart_id=1, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[_store("y", vy1, vreg), _load("z", d0)],
        epilogue_noise=[], result_capture=[_obs(1, d0)])
    p2 = HartProgram(hart_id=2, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 2),
        modeled_window=[_store("z", vz, vreg), _load("x", d1)],
        epilogue_noise=[], result_capture=[_obs(2, d1)])
    return MCProgram(seed_id=seed_id, name=f"Z6.4-mc{seed_id}", isa=_ISA,
        hart_count=3, shared_vars=_shared_vars("x", "y", "z"),
        hart_programs=[p0, p1, p2], observed=[_obs(1, d0), _obs(2, d1)],
        oracle_spec={"family": "Z6.4", "allowed_condition": "forall"},
        noise_profile=noise_level, metadata={"family": "Z6.4"})


def _build_z6_5(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # Z6.5 (3 harts, 3 vars): P0 writes x,y; P1 writes y,z; P2 writes z reads x.
    # Competing writes to y and z. Value-sensitive.
    alloc = ctx.alloc
    alloc.addr("x"); alloc.addr("y"); alloc.addr("z")
    addr_regs = alloc.addr_regs()
    vreg = alloc.value()
    vx, vy0, vy1, vz0, vz1 = _distinct_values(ctx, 5)
    d0 = alloc.dst(2)
    p0 = HartProgram(hart_id=0, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[_store("x", vx, vreg), _store("y", vy0, vreg)],
        epilogue_noise=[], result_capture=[])
    p1 = HartProgram(hart_id=1, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[_store("y", vy1, vreg), _store("z", vz0, vreg)],
        epilogue_noise=[], result_capture=[])
    p2 = HartProgram(hart_id=2, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 2),
        modeled_window=[_store("z", vz1, vreg), _load("x", d0)],
        epilogue_noise=[], result_capture=[_obs(2, d0)])
    return MCProgram(seed_id=seed_id, name=f"Z6.5-mc{seed_id}", isa=_ISA,
        hart_count=3, shared_vars=_shared_vars("x", "y", "z"),
        hart_programs=[p0, p1, p2], observed=[_obs(2, d0)],
        oracle_spec={"family": "Z6.5", "allowed_condition": "forall"},
        noise_profile=noise_level, metadata={"family": "Z6.5"})

def _build_irwiw(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # IRWIW (4 harts, 2 vars): P0 writes x; P1 reads x writes y; P2 writes y;
    # P3 reads y writes x. An IRIW-style extension with trailing writes.
    # Competing writes to x and y. Value-sensitive. (Base topology; the
    # +addrs decoration variant is generated by the dependency axis, not here.)
    alloc = ctx.alloc
    alloc.addr("x")
    alloc.addr("y")
    addr_regs = alloc.addr_regs()
    vreg = alloc.value()
    vx0, vy0, vy1, vx1 = _distinct_values(ctx, 4)
    d0 = alloc.dst(1)
    d1 = alloc.dst(3)
    p0 = HartProgram(
        hart_id=0, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[_store("x", vx0, vreg)], epilogue_noise=[], result_capture=[],
    )
    p1 = HartProgram(
        hart_id=1, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[_load("x", d0), _store("y", vy0, vreg)],
        epilogue_noise=[], result_capture=[_obs(1, d0)],
    )
    p2 = HartProgram(
        hart_id=2, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 2),
        modeled_window=[_store("y", vy1, vreg)], epilogue_noise=[], result_capture=[],
    )
    p3 = HartProgram(
        hart_id=3, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 3),
        modeled_window=[_load("y", d1), _store("x", vx1, vreg)],
        epilogue_noise=[], result_capture=[_obs(3, d1)],
    )
    return MCProgram(
        seed_id=seed_id, name=f"IRWIW-mc{seed_id}", isa=_ISA, hart_count=4,
        shared_vars=_shared_vars("x", "y"), hart_programs=[p0, p1, p2, p3],
        observed=[_obs(1, d0), _obs(3, d1)],
        oracle_spec={"family": "IRWIW", "allowed_condition": "forall"},
        noise_profile=noise_level, metadata={"family": "IRWIW"},
    )


def _build_irrwiw(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # IRRWIW (4 harts, 2 vars): P0 writes x; P1 reads x reads y; P2 writes y;
    # P3 reads y writes x. Competing writes to x. Value-sensitive.
    alloc = ctx.alloc
    alloc.addr("x")
    alloc.addr("y")
    addr_regs = alloc.addr_regs()
    vreg = alloc.value()
    vx0, vy, vx1 = _distinct_values(ctx, 3)
    d0 = alloc.dst(1)
    d1 = alloc.dst(1)
    d2 = alloc.dst(3)
    p0 = HartProgram(
        hart_id=0, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[_store("x", vx0, vreg)], epilogue_noise=[], result_capture=[],
    )
    p1 = HartProgram(
        hart_id=1, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[_load("x", d0), _load("y", d1)],
        epilogue_noise=[], result_capture=[_obs(1, d0), _obs(1, d1)],
    )
    p2 = HartProgram(
        hart_id=2, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 2),
        modeled_window=[_store("y", vy, vreg)], epilogue_noise=[], result_capture=[],
    )
    p3 = HartProgram(
        hart_id=3, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 3),
        modeled_window=[_load("y", d2), _store("x", vx1, vreg)],
        epilogue_noise=[], result_capture=[_obs(3, d2)],
    )
    return MCProgram(
        seed_id=seed_id, name=f"IRRWIW-mc{seed_id}", isa=_ISA, hart_count=4,
        shared_vars=_shared_vars("x", "y"), hart_programs=[p0, p1, p2, p3],
        observed=[_obs(1, d0), _obs(1, d1), _obs(3, d2)],
        oracle_spec={"family": "IRRWIW", "allowed_condition": "forall"},
        noise_profile=noise_level, metadata={"family": "IRRWIW"},
    )


def _build_3_2w(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # 3.2W (3 harts, 3 vars): each hart writes two locations in the cycle
    # x->y->z->x (P0: x,y; P1: y,z; P2: z,x). The 3-thread store-store cycle.
    # All-store topology: NO register observations -- the outcome is the final
    # memory of x,y,z (herd reports it in its States block; the exporter emits
    # a final-memory exists and outcome.py parses the bracketed [x]= keys).
    # Value-sensitive: every location has competing writes.
    alloc = ctx.alloc
    alloc.addr("x"); alloc.addr("y"); alloc.addr("z")
    addr_regs = alloc.addr_regs()
    vreg = alloc.value()
    vx0, vy0, vy1, vz0, vz1, vx1 = _distinct_values(ctx, 6)
    p0 = HartProgram(hart_id=0, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[_store("x", vx0, vreg), _store("y", vy0, vreg)],
        epilogue_noise=[], result_capture=[])
    p1 = HartProgram(hart_id=1, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[_store("y", vy1, vreg), _store("z", vz0, vreg)],
        epilogue_noise=[], result_capture=[])
    p2 = HartProgram(hart_id=2, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 2),
        modeled_window=[_store("z", vz1, vreg), _store("x", vx1, vreg)],
        epilogue_noise=[], result_capture=[])
    return MCProgram(seed_id=seed_id, name=f"3.2W-mc{seed_id}", isa=_ISA,
        hart_count=3, shared_vars=_shared_vars("x", "y", "z"),
        hart_programs=[p0, p1, p2], observed=[],
        oracle_spec={"family": "3.2W", "allowed_condition": "forall"},
        noise_profile=noise_level, metadata={"family": "3.2W"})


