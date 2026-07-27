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

"""Core data model for DiveFuzz-MC multicore test programs.

These dataclasses describe a model-checkable multicore program: shared vars,
per-hart programs of modeled events plus noise, and the observed registers
whose final values form a test outcome.
"""

from dataclasses import dataclass, field
from enum import Enum


class EventKind(str, Enum):
    """Kind of a modeled memory event."""

    LOAD = "Load"
    STORE = "Store"
    FENCE = "Fence"
    FENCE_TSO = "FenceTso"
    AMO = "AMO"
    LR = "LR"
    SC = "SC"
    DEPENDENCY = "Dependency"
    DELAY = "Delay"


@dataclass(frozen=True)
class SharedVar:
    """A shared memory location shared across harts."""

    name: str
    init_value: int = 0
    width: int = 8
    alignment: int = 8


@dataclass(frozen=True)
class ObservedReg:
    """A register whose final value is part of the test outcome."""

    hart: int
    reg: str
    alias: str


@dataclass(frozen=True)
class ModeledEvent:
    """A single modeled memory event inside a hart's modeled window."""

    kind: EventKind
    addr: str | None = None
    dst: str | None = None
    value: int | None = None
    value_reg: str | None = None
    width: int = 8
    aq: bool = False
    rl: bool = False
    pred: str = "rw"
    succ: str = "rw"
    dependency: str | None = None
    amount: int = 0


@dataclass
class HartProgram:
    """Per-hart program: noise + modeled window + result capture."""

    hart_id: int
    address_regs: dict[str, str]
    prologue_noise: list[str]
    modeled_window: list[ModeledEvent]
    epilogue_noise: list[str]
    result_capture: list[ObservedReg]
    interleave_noise: list[str] = field(default_factory=list)


@dataclass
class MCProgram:
    """A complete multicore test program, checkable by an RVWMO/herd oracle."""

    seed_id: int
    name: str
    isa: str
    hart_count: int
    shared_vars: list[SharedVar]
    hart_programs: list[HartProgram]
    observed: list[ObservedReg]
    oracle_spec: dict
    noise_profile: str
    alias_map: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
