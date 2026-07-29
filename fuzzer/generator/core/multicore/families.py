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
plus a builder that turns a seed id + generation context + noise level into a
concrete ``MCProgram``. Builders are agnostic of every randomization choice --
they obtain registers from ``ctx.alloc``, store values from ``ctx.store_value``,
fence events from ``ctx.fence``; the atomic builders additionally obtain the AMO
operation from ``ctx.amo_op`` and acquire/release bits from ``ctx.aqrl``. Family
topology stays decoupled from the randomization axes; that decoupling is the
seam every axis threads through.

Hart count is a property of the family (SB/AMO/LRSC=2, WRC=3, IRIW=4), not a
global knob. Generating an N-hart test means selecting a family whose topology
requires N harts.

Randomization axes live in :class:`GenCtx`. Sound-by-construction axes wired:

- **register allocation**: ``ctx.alloc`` shuffles per-role pools.
- **store values**: ``ctx.store_value`` draws a small immediate.
- **fence pred/succ**: ``ctx.fence`` draws pred/succ from {r,w,rw}.
- **same-word aliasing**: ``ctx.alias_map`` collapses logical vars onto one word.
- **access width**: ``ctx.access_width`` re-widths Load/Store events from {1..8}.
- **AMO operation**: ``ctx.amo_op`` draws from the ops herd7 models.
- **aq/rl bits**: ``ctx.aqrl`` draws acquire/release bits, on atomics only.

The last five are *semantic* axes -- they change the allowed-outcome set -- but
herd recomputes it on the emitted litmus, so the comparison stays sound. The
aq/rl axis threads exclusively through the atomic families: plain Load/Store
encodings carry no such bits (the assembler rejects ``ld.aq``), so acquire/
release on plain accesses must be expressed by fence insertion, a separate
future axis.

Deterministic mode (``randomize=False``, the default) reproduces the
spike-verified seeds byte-for-byte for the original families (fence rw,rw, no
aq/rl, value 1); the atomic families default to ``amoadd.w`` and ``lr.w``/``sc.w``
with no aq/rl.

Families now span Load/Store/Fence/FenceTso (SB, LB, MP, MPTSO, CoRR, WRC, IRIW)
and AMO/LR/SC (AMO atomicity, LR/SC reservation conflict). Dependency/Delay
events remain deferred.
"""

import random
from dataclasses import dataclass, replace
from typing import Callable

from .model import EventKind, HartProgram, MCProgram, ModeledEvent, ObservedReg, SharedVar
from .noise import NoisePool
from .regalloc import RegAllocator

# Width of the shared vars (bytes); 8 -> sd/ld, uint64_t.
_WIDTH = 8
_ISA = "rv64gc"

# Bounds for randomized store values. The upper bound fits ``ori``'s 12-bit
# immediate (so the exporter's `ori reg,x0,V` materializes it in one insn) and
# a byte access width (so width-mixing, a later axis, stays sound).
_VALUE_MIN = 1
_VALUE_MAX = 127

# Fence pred/succ subsets restricted to data-memory bits {r,w}; the i/o bits
# are for device memory and irrelevant to coherence testing.
_FENCE_BIT_CHOICES = ("r", "w", "rw")

# Access widths (bytes) for width mixing. Store values are in [_VALUE_MIN,
# _VALUE_MAX] so they fit any width, including 1 byte.
_ACCESS_WIDTHS = (1, 2, 4, 8)
# AMO operations herd7's RISC-V model implements (probe-confirmed; the unsigned
# maxu/minu are rejected as "not implemented"). Kept in sync with the
# validator's _AMO_OPS: GenCtx draws must stay inside the validator's set.
_AMO_OPS = ("add", "swap", "and", "or", "xor", "min", "max")
# aq/rl ordering-bit combos for atomics (AMO/LR/SC). Plain Load/Store encodings
# carry no such bits, so this axis threads exclusively through atomic families.
_AQRL_CHOICES = ((False, False), (True, False), (False, True), (True, True))


class GenCtx:
    """Per-seed generation context: the single seam for every randomization axis.

    Family builders never read a toggle directly -- they ask the context for a
    register allocator, a store value, and a fence event. Enabling
    or adding an axis changes only this class, never the builders.
    """

    def __init__(self, rng: random.Random, randomize: bool):
        self.rng = rng
        self.randomize = randomize
        # RegAllocator is stateful across the whole program build, so construct
        # it once. Shuffling the per-role pools is sound (disjoint, RESERVED
        # excluded); renaming is a memory-model bijection.
        self.alloc = RegAllocator(rng if randomize else None)

    def store_value(self) -> int:
        """A value to store. Default 1; when randomizing, a draw in
        ``[_VALUE_MIN, _VALUE_MAX]``. Every catalog family is value-insensitive."""
        if self.randomize:
            return self.rng.randint(_VALUE_MIN, _VALUE_MAX)
        return 1

    def fence(self) -> ModeledEvent:
        """A full fence. Default ``rw,rw``; when randomizing, pred/succ drawn
        independently from {r, w, rw}. Sound: the allowed set changes, herd
        recomputes it."""
        if self.randomize:
            pred = self.rng.choice(_FENCE_BIT_CHOICES)
            succ = self.rng.choice(_FENCE_BIT_CHOICES)
            return ModeledEvent(kind=EventKind.FENCE, pred=pred, succ=succ)
        return ModeledEvent(kind=EventKind.FENCE, pred="rw", succ="rw")

    def alias_map(self, logical_vars: list[str]) -> dict[str, str]:
        """Map each logical shared var to a physical var name (identity by
        default). When randomizing, collapse all-but-first onto the first with
        probability 0.5 -- a same-word alias. herd models the collapsed program
        on the reduced location set; the DUT executes true same-word accesses
        (store-forwarding, same-word coherence)."""
        m = {v: v for v in logical_vars}
        if self.randomize and len(logical_vars) >= 2 and self.rng.random() < 0.5:
            first = logical_vars[0]
            for v in logical_vars[1:]:
                m[v] = first
        return m

    def access_width(self) -> int:
        """Access width in bytes for a memory op. Default 8; when randomizing,
        an independent draw from {1, 2, 4, 8}. Sound: herd7 models sub-word
        coherence; the exporter renders sb/sh/sw/sd and lb/lh/lw/ld, and store
        values fit any width."""
        if self.randomize:
            return self.rng.choice(_ACCESS_WIDTHS)
        return _WIDTH

    def amo_op(self) -> str:
        """The AMO operation. Default ``add``; when randomizing, an independent
        draw from the ops herd7 models. A semantic axis -- it changes the
        allowed set, but herd recomputes it on the emitted litmus."""
        if self.randomize:
            return self.rng.choice(_AMO_OPS)
        return "add"

    def aqrl(self) -> tuple[bool, bool]:
        """Acquire/release bits for an atomic (AMO/LR/SC) op, returned as
        ``(aq, rl)``. Default ``(False, False)``; when randomizing, a draw over
        the four {none, aq, rl, aqrl} combos. Sound only on atomics -- plain
        Load/Store encodings have no aq/rl bits, so this axis is wired solely
        into the atomic family builders."""
        if self.randomize:
            return self.rng.choice(_AQRL_CHOICES)
        return (False, False)


# --------------------------------------------------------------------------- #
# Event constructors (register-agnostic; store the symbolic var name, the
# exporter resolves it through the hart's address_regs at render time).
# --------------------------------------------------------------------------- #
def _store(addr: str, value: int, value_reg: str, aq: bool = False, rl: bool = False) -> ModeledEvent:
    return ModeledEvent(
        kind=EventKind.STORE,
        addr=addr,
        value=value,
        value_reg=value_reg,
        width=_WIDTH,
        aq=aq,
        rl=rl,
    )


def _load(addr: str, dst: str, aq: bool = False, rl: bool = False) -> ModeledEvent:
    return ModeledEvent(kind=EventKind.LOAD, addr=addr, dst=dst, width=_WIDTH, aq=aq, rl=rl)


def _amo(addr: str, op: str, value: int, value_reg: str, dst: str, width: int = 4, aq: bool = False, rl: bool = False) -> ModeledEvent:
    return ModeledEvent(
        kind=EventKind.AMO,
        addr=addr,
        amo_op=op,
        value=value,
        value_reg=value_reg,
        dst=dst,
        width=width,
        aq=aq,
        rl=rl,
    )


def _lr(addr: str, dst: str, width: int = 4, aq: bool = False, rl: bool = False) -> ModeledEvent:
    return ModeledEvent(kind=EventKind.LR, addr=addr, dst=dst, width=width, aq=aq, rl=rl)


def _sc(addr: str, value: int, value_reg: str, dst: str, width: int = 4, aq: bool = False, rl: bool = False) -> ModeledEvent:
    return ModeledEvent(
        kind=EventKind.SC,
        addr=addr,
        value=value,
        value_reg=value_reg,
        dst=dst,
        width=width,
        aq=aq,
        rl=rl,
    )


def _fence_tso() -> ModeledEvent:
    return ModeledEvent(kind=EventKind.FENCE_TSO)


def _obs(hart: int, reg: str) -> ObservedReg:
    return ObservedReg(hart=hart, reg=reg, alias=f"h{hart}.{reg}")


def _shared_vars(*names: str) -> list[SharedVar]:
    return [SharedVar(n, 0, _WIDTH, _WIDTH) for n in names]


def _prologue(noise_level: str, ctx: "GenCtx", hart: int) -> list[str]:
    # Prologue noise count by level: none=0, L0=1 (baseline), L1=2 (stronger).
    count = {"none": 0, "L0": 1, "L1": 2}.get(noise_level, 0)
    return NoisePool.sample(noise_level, count, ctx.rng)


# --------------------------------------------------------------------------- #
# Family builders. Each returns a fully concrete MCProgram.
#
# ``_load`` calls pass ``*ctx.aqrl(False)`` (load-acquire semantics) and
# ``_store`` calls pass ``*ctx.aqrl(True)`` (store-release semantics); the
# kind flag keeps every draw in herd7's accepted subspace.
# --------------------------------------------------------------------------- #
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

# --------------------------------------------------------------------------- #
# Catalog
# --------------------------------------------------------------------------- #
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
