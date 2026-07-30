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

"""Register allocation for multicore test programs.

A ``RegAllocator`` hands out concrete RISC-V register names by *role* so that
family topology (which refers to shared vars by name and to result slots by
logical position) stays decoupled from the physical register choice. This is
the seam that the later randomization phase (axis 5: randomized register
allocation) will perturb without touching family definitions.

Roles
-----
- ``addr(var)``  : base register bound to a shared variable. Global across
  harts (the litmus init block emits ``0:x6=x; 1:x6=x;`` -- same reg, each
  hart). Repeated calls for the same var return the same register.
- ``value()``    : register used to materialize a store immediate. Global.
- ``dst(hart)``  : destination register of an observed load. Per-hart: the
  pool restarts at each hart id, so ``dst(0)`` and ``dst(1)`` may both yield
  ``x10`` (they live on different harts).
- ``scratch()``  : scratch register for noise. Per-hart, same rationale.

The default (``rng=None``) assignment is deterministic and reproduces the
register set validated by the spike end-to-end run (addr x6/x7, value x12/x13,
dst x10/x11, scratch x20). Passing an ``rng`` shuffles each pool, reserved for
the randomization phase.
"""

import random


class RegAllocError(ValueError):
    """Raised when a register pool is exhausted (family needs more slots)."""


class RegAllocator:
    """Role-based register allocator with a deterministic default mapping."""

    # Working register set validated by the spike闭环, partitioned by role and
    # disjoint. Growing a family beyond these pool sizes means extending the
    # relevant pool *and* confirming the new register is harness-safe (the
    # spike startup.S uses s1=x9 as the slot pointer; gp/tp/sp/ra/zero and the
    # s2-s11/t3-t6 zone are reserved).
    # Three addr regs cover the 3-variable cycle families (ISA2, 3.LB/SB, the
    # Z6.0-Z6.5 series): x->y->z->x. x14 (a4) is caller-saved and outside the
    # harness RESERVED set; smoke-confirmed against the spike litmus harness.
    ADDR_POOL: tuple[str, ...] = ("x6", "x7", "x14")
    VALUE_POOL: tuple[str, ...] = ("x12", "x13")
    # Four dst regs cover the address-dependency families (RDW, RSW): their
    # reader hart chains 2 direct loads + 2 address-dependent loads, needing 4
    # distinct load destinations on one hart. x15/x16 (a5/a6) are caller-saved
    # and outside the harness RESERVED set.
    DST_POOL: tuple[str, ...] = ("x10", "x11", "x15", "x16")
    SCRATCH_POOL: tuple[str, ...] = ("x20",)

    # Registers never handed out (ABI + harness-reserved). Documented so the
    # randomization phase knows the exclusion zone.
    RESERVED: frozenset[str] = frozenset(
        {
            "x0", "x1", "x2", "x3", "x4", "x5",  # zero, ra, sp, gp, tp, t0
            "x8", "x9",  # s0/fp, s1 (harness slot pointer)
            "x18", "x19", "x24", "x25", "x26", "x27",  # s2, s3, s8..s11
            "x28", "x29", "x30", "x31",  # t3..t6
        }
    )

    def __init__(self, rng: random.Random | None = None):
        self._rng = rng
        self._addr_map: dict[str, str] = {}
        self._addr_pool = self._rotate(self.ADDR_POOL)
        self._value_pool = self._rotate(self.VALUE_POOL)
        self._dst_pools: dict[int, list[str]] = {}
        self._scratch_pools: dict[int, list[str]] = {}

    def _rotate(self, pool: tuple[str, ...]) -> list[str]:
        if self._rng is None:
            return list(pool)
        return self._rng.sample(list(pool), len(pool))

    def addr(self, var: str) -> str:
        """Return the base register for shared variable ``var`` (stable)."""
        if var not in self._addr_map:
            if not self._addr_pool:
                raise RegAllocError(
                    f"address register pool exhausted at var '{var}'; "
                    f"extend ADDR_POOL (currently {self.ADDR_POOL})"
                )
            self._addr_map[var] = self._addr_pool.pop(0)
        return self._addr_map[var]

    def addr_regs(self) -> dict[str, str]:
        """Snapshot of the ``{var: reg}`` address binding (shared by all harts)."""
        return dict(self._addr_map)

    def value(self) -> str:
        if not self._value_pool:
            raise RegAllocError(
                f"value register pool exhausted; extend VALUE_POOL "
                f"(currently {self.VALUE_POOL})"
            )
        return self._value_pool.pop(0)

    def dst(self, hart: int) -> str:
        """Observed-load destination register for ``hart`` (per-hart restart)."""
        pool = self._dst_pools.setdefault(hart, self._rotate(self.DST_POOL))
        if not pool:
            raise RegAllocError(
                f"destination register pool exhausted on hart {hart}; extend "
                f"DST_POOL (currently {self.DST_POOL})"
            )
        return pool.pop(0)

    def scratch(self, hart: int) -> str:
        """Noise scratch register for ``hart`` (per-hart restart)."""
        pool = self._scratch_pools.setdefault(hart, self._rotate(self.SCRATCH_POOL))
        if not pool:
            raise RegAllocError(
                f"scratch register pool exhausted on hart {hart}; extend "
                f"SCRATCH_POOL (currently {self.SCRATCH_POOL})"
            )
        return pool.pop(0)
