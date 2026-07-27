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

Noise perturbs pipeline timing without changing the memory-model-allowed
outcome set. The pool is the single source of truth for which noise
instructions are sound: the family builder draws from it, and the validator
accepts exactly what :meth:`is_safe` permits.

Soundness contract
------------------
Every noise instruction writes **only** scratch registers (:data:`SCRATCH`),
which never appear in any modeled window (they are disjoint from address,
value, observed, and runtime/reserved registers). Therefore noise is sound
*anywhere* it is inserted -- prologue, between window events (interleaving),
or epilogue -- because it cannot influence the window's memory accesses or
the observed outcome. herd reasons about the modeled window only; noise rows
outside it are invisible to the allowed-set computation.

Levels (research plan §5)
-------------------------
- ``none`` : no noise.
- ``L0``   : inert instructions (``nop``, ``addi x20,x20,0``).
- ``L1``   : scratch-only integer ALU ops on x20 (``addi``/``slli``/``srli``
  with random immediates, plus ``add``/``sub``/``and``/``or``/``xor``/``mul``
  ``x20,x20,x20``). These perturb the ALU/rename pipeline and (when
  interleaved between window events) separate the loads/stores in time,
  exposing reordering-sensitive timing. No memory accesses, no branches, no
  traps. L2 (broader instruction pool, private memory) is deferred.
"""

import random
import re

# A noise instruction "emitter" turns an rng into one instruction string.
Emitter = callable


def _is_reg(token: str) -> bool:
    return bool(re.fullmatch(r"x\d+", token))


class NoisePool:
    """Sound noise-instruction source, parameterized by level."""

    # The single scratch register noise may touch. Disjoint from every other
    # register role (addr x6/x7, value x12/x13, observed x10/x11, and the
    # harness/ABI reserved set), so writing it cannot affect any test.
    SCRATCH: tuple[str, ...] = ("x20",)

    # Mnemonic whitelists for :meth:`is_safe` (register-register and
    # register-immediate ALU ops that cannot trap).
    _ALU3 = frozenset({"add", "sub", "and", "or", "xor", "sll", "srl"})
    _ALU2I = frozenset({"addi", "slli", "srli", "andi", "ori", "xori"})

    @classmethod
    def _l0_emitters(cls) -> list[Emitter]:
        return [
            lambda rng: "nop",
            lambda rng: "addi x20,x20,0",
        ]

    @classmethod
    def _l1_emitters(cls) -> list[Emitter]:
        s = cls.SCRATCH[0]
        return [
            lambda rng: "nop",
            lambda rng: f"addi {s},{s},{rng.randint(-50, 50)}",
            lambda rng: f"slli {s},{s},{rng.randint(0, 31)}",
            lambda rng: f"srli {s},{s},{rng.randint(0, 31)}",
            lambda rng: f"add {s},{s},{s}",
            lambda rng: f"sub {s},{s},{s}",
            lambda rng: f"and {s},{s},{s}",
            lambda rng: f"or {s},{s},{s}",
            lambda rng: f"xor {s},{s},{s}",
        ]

    _EMITTERS: dict[str, classmethod] = {}  # populated below

    @classmethod
    def supported_levels(cls) -> tuple[str, ...]:
        """Levels that have a populated emitter pool."""
        return tuple(cls._EMITTERS.keys())

    @classmethod
    def is_supported(cls, level: str) -> bool:
        return level == "none" or level in cls._EMITTERS

    @classmethod
    def sample(cls, level: str, count: int, rng: random.Random) -> list[str]:
        """Draw ``count`` noise instructions for ``level``.

        ``none`` returns ``[]`` (``count`` must be 0). Unknown levels raise.
        """
        if level == "none":
            if count:
                raise ValueError("noise level 'none' cannot take a nonzero count")
            return []
        if level not in cls._EMITTERS:
            raise ValueError(
                f"Unsupported noise level: {level!r}. Supported: none, "
                f"{', '.join(cls._EMITTERS)}"
            )
        emitters = cls._EMITTERS[level]()
        return [rng.choice(emitters)(rng) for _ in range(count)]

    @classmethod
    def is_safe(cls, instr: str) -> bool:
        """True iff ``instr`` is a permitted noise instruction.

        Permits ``nop`` and the ALU ops whose every register operand is in
        :data:`SCRATCH`; immediates/shifts are unconstrained. This is the
        soundness backstop the validator calls for every noise row.
        """
        instr = instr.strip()
        if instr == "nop":
            return True
        tokens = [t for t in re.split(r"[,\s]+", instr) if t]
        if not tokens:
            return False
        mnem = tokens[0]
        regs = [t for t in tokens[1:] if _is_reg(t)]
        scratch = set(cls.SCRATCH)
        if mnem in cls._ALU3:
            return len(regs) == 3 and set(regs) <= scratch
        if mnem in cls._ALU2I:
            return len(regs) == 2 and set(regs) <= scratch
        return False


NoisePool._EMITTERS = {
    "L0": NoisePool._l0_emitters,
    "L1": NoisePool._l1_emitters,
}
