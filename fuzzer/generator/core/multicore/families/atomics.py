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
from .events import _amo, _lr, _obs, _prologue, _sc, _shared_vars, _store
from .genctx import GenCtx, _ISA

def _build_amo(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # AMO atomicity (2 harts): both harts perform an atomic read-modify-write
    # on x; the old value each AMO returns is observed. RVWMO atomicity forbids
    # both from reading the initial value -- the AMOs are totally ordered.
    alloc = ctx.alloc
    alloc.addr("x")
    addr_regs = alloc.addr_regs()
    p0_vreg = alloc.value()
    p1_vreg = alloc.value()
    p0_val = ctx.store_value()
    p1_val = ctx.store_value()
    d0 = alloc.dst(0)
    d1 = alloc.dst(1)
    op = ctx.amo_op()
    aq0, rl0 = ctx.aqrl()
    aq1, rl1 = ctx.aqrl()
    p0 = HartProgram(
        hart_id=0,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[_amo("x", op, p0_val, p0_vreg, d0, aq=aq0, rl=rl0)],
        epilogue_noise=[],
        result_capture=[_obs(0, d0)],
    )
    p1 = HartProgram(
        hart_id=1,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[_amo("x", op, p1_val, p1_vreg, d1, aq=aq1, rl=rl1)],
        epilogue_noise=[],
        result_capture=[_obs(1, d1)],
    )
    return MCProgram(
        seed_id=seed_id,
        name=f"AMO-mc{seed_id}",
        isa=_ISA,
        hart_count=2,
        shared_vars=_shared_vars("x"),
        hart_programs=[p0, p1],
        observed=[_obs(0, d0), _obs(1, d1)],
        oracle_spec={"family": "AMO", "allowed_condition": "forall"},
        noise_profile=noise_level,
        metadata={"family": "AMO"},
    )


def _build_lrsc(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # LR/SC reservation conflict (2 harts): P0 does LR then SC on x (observing
    # the loaded value and the SC success flag); P1 stores to x concurrently.
    # RVWMO: a store hitting the reservation set between LR and SC must make the
    # SC fail, so (LR saw the new value) /\ (SC succeeded) is forbidden.
    alloc = ctx.alloc
    alloc.addr("x")
    addr_regs = alloc.addr_regs()
    sc_vreg = alloc.value()
    p1_vreg = alloc.value()
    sc_val = ctx.store_value()
    p1_val = ctx.store_value()
    d_lr = alloc.dst(0)
    d_sc = alloc.dst(0)
    aq_lr, rl_lr = ctx.aqrl()
    aq_sc, rl_sc = ctx.aqrl()
    p0 = HartProgram(
        hart_id=0,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[
            _lr("x", d_lr, aq=aq_lr, rl=rl_lr),
            _sc("x", sc_val, sc_vreg, d_sc, aq=aq_sc, rl=rl_sc),
        ],
        epilogue_noise=[],
        result_capture=[_obs(0, d_lr), _obs(0, d_sc)],
    )
    p1 = HartProgram(
        hart_id=1,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[_store("x", p1_val, p1_vreg)],
        epilogue_noise=[],
        result_capture=[],
    )
    return MCProgram(
        seed_id=seed_id,
        name=f"LRSC-mc{seed_id}",
        isa=_ISA,
        hart_count=2,
        shared_vars=_shared_vars("x"),
        hart_programs=[p0, p1],
        observed=[_obs(0, d_lr), _obs(0, d_sc)],
        oracle_spec={"family": "LRSC", "allowed_condition": "forall"},
        noise_profile=noise_level,
        metadata={"family": "LRSC"},
    )

def _build_mp_acqrel(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # Release/acquire message passing (2 harts): P0 store-releases x then y via
    # amoswap.w.rl (rd=x0 discards the swapped-out old value); P1 load-acquires
    # y then x via lr.w.aq. This is the canonical RVWMO release-acquire MP
    # idiom and the only hardware-runnable form: plain load/store encodings
    # carry no aq/rl bits (the assembler rejects lw.aq), so the ordering must
    # ride on AMO/LR. RVWMO forbids P1 seeing y's new value yet x's old -- a DUT
    # that mishandles the aq/rl ordering bits exhibits that forbidden outcome.
    alloc = ctx.alloc
    alloc.addr("x")
    alloc.addr("y")
    addr_regs = alloc.addr_regs()
    vreg = alloc.value()
    vx = ctx.store_value()
    vy = ctx.store_value()
    dy = alloc.dst(1)
    dx = alloc.dst(1)
    p0 = HartProgram(
        hart_id=0,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[
            _amo("x", "swap", vx, vreg, "x0", rl=True),
            _amo("y", "swap", vy, vreg, "x0", rl=True),
        ],
        epilogue_noise=[],
        result_capture=[],
    )
    p1 = HartProgram(
        hart_id=1,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[
            _lr("y", dy, aq=True),
            _lr("x", dx, aq=True),
        ],
        epilogue_noise=[],
        result_capture=[_obs(1, dy), _obs(1, dx)],
    )
    return MCProgram(
        seed_id=seed_id,
        name=f"MPAcqRel-mc{seed_id}",
        isa=_ISA,
        hart_count=2,
        shared_vars=_shared_vars("x", "y"),
        hart_programs=[p0, p1],
        observed=[_obs(1, dy), _obs(1, dx)],
        oracle_spec={"family": "MPAcqRel", "allowed_condition": "forall"},
        noise_profile=noise_level,
        metadata={"family": "MPAcqRel"},
    )


