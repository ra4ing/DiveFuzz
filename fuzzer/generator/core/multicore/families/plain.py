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
from .events import _distinct_values, _fence_tso, _load, _obs, _prologue, _shared_vars, _store
from .genctx import GenCtx, _ISA

def _build_sb(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # P0: Store(x,vx); Load(y -> d0)   P1: Store(y,vy); Load(x -> d1)
    alloc = ctx.alloc
    alloc.addr("x")
    alloc.addr("y")
    addr_regs = alloc.addr_regs()
    vreg = alloc.value()       # one value reg reused by both stores
    vx = ctx.store_value()
    vy = ctx.store_value()
    d0 = alloc.dst(0)
    d1 = alloc.dst(1)
    p0 = HartProgram(
        hart_id=0,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[
            _store("x", vx, vreg),
            _load("y", d0),
        ],
        epilogue_noise=[],
        result_capture=[_obs(0, d0)],
    )
    p1 = HartProgram(
        hart_id=1,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[
            _store("y", vy, vreg),
            _load("x", d1),
        ],
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


def _build_lb(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # P0: Load(x -> d0); Store(y,vy)   P1: Load(y -> d1); Store(x,vx)
    alloc = ctx.alloc
    alloc.addr("x")
    alloc.addr("y")
    addr_regs = alloc.addr_regs()
    vreg = alloc.value()
    vx = ctx.store_value()
    vy = ctx.store_value()
    d0 = alloc.dst(0)
    d1 = alloc.dst(1)
    p0 = HartProgram(
        hart_id=0,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[
            _load("x", d0),
            _store("y", vy, vreg),
        ],
        epilogue_noise=[],
        result_capture=[_obs(0, d0)],
    )
    p1 = HartProgram(
        hart_id=1,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[
            _load("y", d1),
            _store("x", vx, vreg),
        ],
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


def _build_mp(fence_kind: str, family: str):
    """Return an MP builder whose inter-store barrier is ``fence_kind``.

    ``"fence"`` -> a (possibly randomized) full fence via ``ctx.fence()``;
    ``"fence_tso"`` -> a fixed ``fence.tso`` (the MPTSO variant).
    """

    def _build(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
        # P0: Store(x,vx); <barrier>; Store(y,vy)
        # P1: Load(y -> dy); Load(x -> dx)
        alloc = ctx.alloc
        alloc.addr("x")
        alloc.addr("y")
        addr_regs = alloc.addr_regs()
        vx_reg = alloc.value()  # x12
        vy_reg = alloc.value()  # x13
        vx = ctx.store_value()
        vy = ctx.store_value()
        dy = alloc.dst(1)       # x10  (load y)
        dx = alloc.dst(1)       # x11  (load x)
        barrier = _fence_tso() if fence_kind == "fence_tso" else ctx.fence()
        p0 = HartProgram(
            hart_id=0,
            address_regs=dict(addr_regs),
            prologue_noise=_prologue(noise_level, ctx, 0),
            modeled_window=[
                _store("x", vx, vx_reg),
                barrier,
                _store("y", vy, vy_reg),
            ],
            epilogue_noise=[],
            result_capture=[],
        )
        p1 = HartProgram(
            hart_id=1,
            address_regs=dict(addr_regs),
            prologue_noise=_prologue(noise_level, ctx, 1),
            modeled_window=[
                _load("y", dy),
                _load("x", dx),
            ],
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


def _build_s(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # S (store-load archetype, 2 harts): P0 writes x then y; P1 reads y then
    # writes x. RVWMO permits P1 to observe P0's store to y out of the writer's
    # store-store order -- the complementary shape to LB, probing store-store
    # (and store-forwarding) timing. Value-sensitive: P0 and P1 write distinct
    # competing values to x, so the x race has a non-trivial allowed set.
    alloc = ctx.alloc
    alloc.addr("x")
    alloc.addr("y")
    addr_regs = alloc.addr_regs()
    vreg = alloc.value()
    vx0, vy, vx1 = _distinct_values(ctx, 3)
    d = alloc.dst(1)
    p0 = HartProgram(
        hart_id=0,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[
            _store("x", vx0, vreg),
            _store("y", vy, vreg),
        ],
        epilogue_noise=[],
        result_capture=[],
    )
    p1 = HartProgram(
        hart_id=1,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[
            _load("y", d),
            _store("x", vx1, vreg),
        ],
        epilogue_noise=[],
        result_capture=[_obs(1, d)],
    )
    return MCProgram(
        seed_id=seed_id,
        name=f"S-mc{seed_id}",
        isa=_ISA,
        hart_count=2,
        shared_vars=_shared_vars("x", "y"),
        hart_programs=[p0, p1],
        observed=[_obs(1, d)],
        oracle_spec={"family": "S", "allowed_condition": "forall"},
        noise_profile=noise_level,
        metadata={"family": "S"},
    )


def _build_r(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # R (load-store archetype, 2 harts): P0 writes x then y; P1 writes y then
    # reads x. RVWMO permits P1 to read the stale initial x -- the complementary
    # shape to S, probing load-store ordering across distinct locations.
    # Value-sensitive: P0 and P1 write distinct competing values to y.
    alloc = ctx.alloc
    alloc.addr("x")
    alloc.addr("y")
    addr_regs = alloc.addr_regs()
    vreg = alloc.value()
    vx, vy0, vy1 = _distinct_values(ctx, 3)
    d = alloc.dst(1)
    p0 = HartProgram(
        hart_id=0,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[
            _store("x", vx, vreg),
            _store("y", vy0, vreg),
        ],
        epilogue_noise=[],
        result_capture=[],
    )
    p1 = HartProgram(
        hart_id=1,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[
            _store("y", vy1, vreg),
            _load("x", d),
        ],
        epilogue_noise=[],
        result_capture=[_obs(1, d)],
    )
    return MCProgram(
        seed_id=seed_id,
        name=f"R-mc{seed_id}",
        isa=_ISA,
        hart_count=2,
        shared_vars=_shared_vars("x", "y"),
        hart_programs=[p0, p1],
        observed=[_obs(1, d)],
        oracle_spec={"family": "R", "allowed_condition": "forall"},
        noise_profile=noise_level,
        metadata={"family": "R"},
    )


def _build_2plus2w(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # Store-store ordering across two locations (3 harts): P0 writes y then x,
    # P1 writes x then y (no fence), and P2 reads both. Without a fence the
    # writers' store-store order is unconstrained, so P2 can see mixed outcomes
    # (x from P0, y from P1) that a fence would forbid -- a 9-state outcome set.
    alloc = ctx.alloc
    alloc.addr("x")
    alloc.addr("y")
    addr_regs = alloc.addr_regs()
    vreg = alloc.value()
    v_y0, v_x0, v_x1, v_y1 = _distinct_values(ctx, 4)
    d0 = alloc.dst(2)
    d1 = alloc.dst(2)
    p0 = HartProgram(
        hart_id=0,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[_store("y", v_y0, vreg), _store("x", v_x0, vreg)],
        epilogue_noise=[],
        result_capture=[],
    )
    p1 = HartProgram(
        hart_id=1,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[_store("x", v_x1, vreg), _store("y", v_y1, vreg)],
        epilogue_noise=[],
        result_capture=[],
    )
    p2 = HartProgram(
        hart_id=2,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 2),
        modeled_window=[_load("x", d0), _load("y", d1)],
        epilogue_noise=[],
        result_capture=[_obs(2, d0), _obs(2, d1)],
    )
    return MCProgram(
        seed_id=seed_id,
        name=f"2+2W-mc{seed_id}",
        isa=_ISA,
        hart_count=3,
        shared_vars=_shared_vars("x", "y"),
        hart_programs=[p0, p1, p2],
        observed=[_obs(2, d0), _obs(2, d1)],
        oracle_spec={"family": "2+2W", "allowed_condition": "forall"},
        noise_profile=noise_level,
        metadata={"family": "2+2W"},
    )

