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

from ..model import EventKind, ModeledEvent, ObservedReg, SharedVar
from ..noise import NoisePool
from .genctx import GenCtx, _VALUE_MAX, _WIDTH

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


def _dependency(dst: str, value_reg: str, dependency: str = "data", addr: str | None = None, width: int = _WIDTH) -> ModeledEvent:
    return ModeledEvent(
        kind=EventKind.DEPENDENCY,
        dst=dst,
        value_reg=value_reg,
        dependency=dependency,
        addr=addr,
        width=width,
    )


def _delay(dst: str, amount: int) -> ModeledEvent:
    return ModeledEvent(kind=EventKind.DELAY, dst=dst, amount=amount)


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


def _distinct_values(ctx: "GenCtx", n: int) -> list[int]:
    """``n`` distinct store values in [_VALUE_MIN, _VALUE_MAX]. Coherence and
    store-store families are value-sensitive: they need distinct competing
    values to have a non-trivial allowed set (equal values collapse to one
    outcome). All values stay <= _VALUE_MAX so width-mixing (down to sb/lb)
    never truncates them."""
    base = ctx.store_value()
    return [(base + i - 1) % _VALUE_MAX + 1 for i in range(n)]
