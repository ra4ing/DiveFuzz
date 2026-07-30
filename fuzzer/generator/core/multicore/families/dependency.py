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
from .events import _delay, _dependency, _load, _obs, _prologue, _shared_vars, _store
from .genctx import GenCtx, _ISA

def _build_lbdep(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # LB with in-window dependency constructs (2 harts): P0 loads y, runs a
    # load-to-use DELAY chain on the result, then stores x; P1 loads x, threads
    # the result through a data DEPENDENCY into the observed register, then
    # stores y. Both constructs are value-preserving in-window perturbations --
    # they stress the DUT's load-to-use / dependency-tracking pipeline without
    # changing the RVWMO allowed set (herd recomputes it on the emitted litmus).
    alloc = ctx.alloc
    alloc.addr("x")
    alloc.addr("y")
    addr_regs = alloc.addr_regs()
    vreg = alloc.value()
    vx = ctx.store_value()
    vy = ctx.store_value()
    d0 = alloc.dst(0)
    d1 = alloc.dst(1)
    d_dep = alloc.dst(1)
    amount = ctx.delay_amount()
    p0 = HartProgram(
        hart_id=0,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[_load("y", d0), _delay(d0, amount), _store("x", vx, vreg)],
        epilogue_noise=[],
        result_capture=[_obs(0, d0)],
    )
    p1 = HartProgram(
        hart_id=1,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[_load("x", d1), _dependency(d_dep, d1), _store("y", vy, vreg)],
        epilogue_noise=[],
        result_capture=[_obs(1, d_dep)],
    )
    return MCProgram(
        seed_id=seed_id,
        name=f"LBdep-mc{seed_id}",
        isa=_ISA,
        hart_count=2,
        shared_vars=_shared_vars("x", "y"),
        hart_programs=[p0, p1],
        observed=[_obs(0, d0), _obs(1, d_dep)],
        oracle_spec={"family": "LBdep", "allowed_condition": "forall"},
        noise_profile=noise_level,
        metadata={"family": "LBdep"},
    )

def _build_lbadc(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # LB with address + control dependency (2 harts): P0 loads y then
    # dependent-loads x through an ADDRESS dependency on y (xor-trick); P1 loads
    # x then dependent-loads y through a CONTROL dependency on x (branch-over).
    # Each hart then stores its dependent-load target. Under RVWMO neither
    # dependency orders the two loads, so the LB-style outcomes stay allowed --
    # the constructs probe the DUT's address-generation interlock and
    # control-flow + load ordering without changing the allowed set.
    alloc = ctx.alloc
    alloc.addr("x")
    alloc.addr("y")
    addr_regs = alloc.addr_regs()
    vreg = alloc.value()
    vx = ctx.store_value()
    vy = ctx.store_value()
    d0 = alloc.dst(0)
    d_a = alloc.dst(0)
    d1 = alloc.dst(1)
    d_c = alloc.dst(1)
    p0 = HartProgram(
        hart_id=0,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[
            _load("y", d0),
            _dependency(d_a, d0, "addr", "x"),
            _store("x", vx, vreg),
        ],
        epilogue_noise=[],
        result_capture=[_obs(0, d0), _obs(0, d_a)],
    )
    p1 = HartProgram(
        hart_id=1,
        address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[
            _load("x", d1),
            _dependency(d_c, d1, "ctrl", "y"),
            _store("y", vy, vreg),
        ],
        epilogue_noise=[],
        result_capture=[_obs(1, d1), _obs(1, d_c)],
    )
    return MCProgram(
        seed_id=seed_id,
        name=f"LBadc-mc{seed_id}",
        isa=_ISA,
        hart_count=2,
        shared_vars=_shared_vars("x", "y"),
        hart_programs=[p0, p1],
        observed=[_obs(0, d0), _obs(0, d_a), _obs(1, d1), _obs(1, d_c)],
        oracle_spec={"family": "LBadc", "allowed_condition": "forall"},
        noise_profile=noise_level,
        metadata={"family": "LBadc"},
    )

def _build_rdw(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # RDW (3 harts, 3 vars): P0 writes x then y (fenced); P1 reads y, then
    # address-dependently reads z (the load address is computed from the y
    # result), reads z directly, then address-dependently reads x; P2 writes z.
    # The two address-dependency chains probe whether the DUT honors address
    # dependencies for visibility -- a canonical "MP + addr-dep" anomaly. The
    # reader hart needs 4 destinations (2 loads + 2 addr-dep loads), hence the
    # DST_POOL of 4.
    alloc = ctx.alloc
    alloc.addr("x"); alloc.addr("y"); alloc.addr("z")
    addr_regs = alloc.addr_regs()
    vreg = alloc.value()
    v = ctx.store_value()
    d0 = alloc.dst(1); d1 = alloc.dst(1); d2 = alloc.dst(1); d3 = alloc.dst(1)
    p0 = HartProgram(hart_id=0, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[_store("x", v, vreg), ctx.fence(), _store("y", v, vreg)],
        epilogue_noise=[], result_capture=[])
    p1 = HartProgram(hart_id=1, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[
            _load("y", d0),
            _dependency(d1, d0, dependency="addr", addr="z"),
            _load("z", d2),
            _dependency(d3, d2, dependency="addr", addr="x"),
        ],
        epilogue_noise=[],
        result_capture=[_obs(1, d0), _obs(1, d1), _obs(1, d2), _obs(1, d3)])
    p2 = HartProgram(hart_id=2, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 2),
        modeled_window=[_store("z", v, vreg)],
        epilogue_noise=[], result_capture=[])
    return MCProgram(seed_id=seed_id, name=f"RDW-mc{seed_id}", isa=_ISA,
        hart_count=3, shared_vars=_shared_vars("x", "y", "z"),
        hart_programs=[p0, p1, p2],
        observed=[_obs(1, d0), _obs(1, d1), _obs(1, d2), _obs(1, d3)],
        oracle_spec={"family": "RDW", "allowed_condition": "forall"},
        noise_profile=noise_level, metadata={"family": "RDW"})


def _build_rsw(seed_id: int, ctx: GenCtx, noise_level: str) -> MCProgram:
    # RSW (2 harts, 3 vars): P0 writes x then y (fenced); P1 reads y, address-
    # dependently reads z, reads z directly, address-dependently reads x. Same
    # address-dependency probe as RDW but with a single writer+reader pair.
    # Only the first and last loads are observed (the canonical exists clause
    # references them); the reader hart still needs 4 dst registers.
    alloc = ctx.alloc
    alloc.addr("x"); alloc.addr("y"); alloc.addr("z")
    addr_regs = alloc.addr_regs()
    vreg = alloc.value()
    v = ctx.store_value()
    d0 = alloc.dst(1); d1 = alloc.dst(1); d2 = alloc.dst(1); d3 = alloc.dst(1)
    p0 = HartProgram(hart_id=0, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 0),
        modeled_window=[_store("x", v, vreg), ctx.fence(), _store("y", v, vreg)],
        epilogue_noise=[], result_capture=[])
    p1 = HartProgram(hart_id=1, address_regs=dict(addr_regs),
        prologue_noise=_prologue(noise_level, ctx, 1),
        modeled_window=[
            _load("y", d0),
            _dependency(d1, d0, dependency="addr", addr="z"),
            _load("z", d2),
            _dependency(d3, d2, dependency="addr", addr="x"),
        ],
        epilogue_noise=[], result_capture=[_obs(1, d0), _obs(1, d3)])
    return MCProgram(seed_id=seed_id, name=f"RSW-mc{seed_id}", isa=_ISA,
        hart_count=2, shared_vars=_shared_vars("x", "y", "z"),
        hart_programs=[p0, p1],
        observed=[_obs(1, d0), _obs(1, d3)],
        oracle_spec={"family": "RSW", "allowed_condition": "forall"},
        noise_profile=noise_level, metadata={"family": "RSW"})


# --------------------------------------------------------------------------- #
# Catalog
# --------------------------------------------------------------------------- #
