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

from ..model import EventKind, ModeledEvent
from ..regalloc import RegAllocator

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

    def delay_amount(self) -> int:
        """Load-to-use delay chain length. Default 4; when randomizing, a draw
        in [1, 8]. A semantic-neutral perturbation: the chain is value-preserving
        (``add x,x,x0``), so the allowed set is unchanged -- it only stresses the
        DUT's load-to-use / dependency-tracking pipeline."""
        if self.randomize:
            return self.rng.randint(1, 8)
        return 4

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
