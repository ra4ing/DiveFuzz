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

"""Noise instruction pool for multicore test programs.

Noise is inserted around the modeled window to perturb pipeline timing without
changing the memory-model-allowed outcome set. The pool is the single source
of truth for which noise instructions are sound at each level: the family
builder draws from it, and the validator accepts exactly its emitted set.

Levels (research plan §5)
-------------------------
- ``none`` : no noise.
- ``L0``   : inert instructions (``nop``, ``addi x20,x20,0``). Cannot touch
  shared memory, observed registers, or the runtime area; the herd allowed set
  is provably unchanged (verified by the L0 soundness regression).
- ``L1``/``L2`` : integer compute / private branches / non-trapping supported
  instructions. **Planned for the randomization phase** -- not yet populated;
  requesting them raises ``ValueError``.

This module is deliberately structured (not a bare list) so that L1/L2 plug in
by extending ``_LEVELS`` without touching families or the validator.
"""

import random

from .regalloc import RegAllocator


class NoisePool:
    """Sound noise-instruction source, parameterized by level."""

    # Each entry: the literal instruction strings the level may emit at the
    # default scratch register (x20). L0 reproduces the pre-refactor set verbatim.
    # L1/L2 are intentionally absent until the randomization phase.
    _LEVELS: dict[str, tuple[str, ...]] = {
        "L0": ("nop", "addi x20,x20,0"),
    }

    @classmethod
    def supported_levels(cls) -> tuple[str, ...]:
        """Levels that actually have a populated instruction pool."""
        return tuple(cls._LEVELS.keys())

    @classmethod
    def is_supported(cls, level: str) -> bool:
        return level == "none" or level in cls._LEVELS

    @classmethod
    def allowed_instructions(cls, level: str) -> frozenset[str]:
        """The exact set of instruction strings the pool may emit at ``level``.

        The validator accepts precisely these strings; anything else in a
        ``*_noise`` list is rejected. ``none`` has no allowed instructions
        (a noise list must be empty).
        """
        if level == "none":
            return frozenset()
        if level not in cls._LEVELS:
            raise ValueError(
                f"Unsupported noise level: {level!r}. Supported: none, "
                f"{', '.join(cls._LEVELS)}"
            )
        return frozenset(cls._LEVELS[level])

    @classmethod
    def prologue(
        cls,
        level: str,
        count: int,
        rng: random.Random,
        alloc: RegAllocator,
        hart: int,
    ) -> list[str]:
        """Draw ``count`` noise instructions for one hart's prologue.

        ``alloc``/``hart`` are accepted so future levels (L1/L2) can bind
        per-hart scratch registers via ``alloc.scratch(hart)``; L0 uses the
        fixed x20 convention and ignores them.
        """
        if level == "none":
            return []
        if level not in cls._LEVELS:
            raise ValueError(
                f"Unsupported noise level: {level!r}. Supported: none, "
                f"{', '.join(cls._LEVELS)}"
            )
        pool = cls._LEVELS[level]
        return [rng.choice(pool) for _ in range(count)]
