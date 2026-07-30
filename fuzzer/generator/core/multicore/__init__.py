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

"""DiveFuzz-MC multicore seed generator (litmus7-compatible backend).

This package generates model-checkable multicore RISC-V test programs across a
declarative family catalog (2/3/4-hart topologies), exports them to ``.litmus``
form, queries the RVWMO/herd oracle for allowed outcomes, and (optionally)
builds a litmus7-compatible executable.
"""

from .model import (
    EventKind,
    SharedVar,
    ObservedReg,
    ModeledEvent,
    HartProgram,
    MCProgram,
)
from .families import (
    FamilySpec,
    available_families,
    build_program,
    family_hart_count,
    families_for_hart_count,
)
from .regalloc import RegAllocator, RegAllocError
from .noise import NoisePool
from .validator import validate
from .litmus_exporter import export_litmus
from .outcome import (
    canonical_key,
    canonical_outcome,
    parse_assignment_state,
    parse_litmus_histogram,
    parse_herd_states,
)
from .herd_oracle import HerdOracle, OracleResult
from .herd_cache import HerdCache
from .litmus_backend import SeedBundle, LitmusExecutableBackend
from .generate import (
    MultiCoreGenerationConfig,
    generate_multicore_seed,
    generate_multicore_seeds,
)

__all__ = [
    "EventKind",
    "SharedVar",
    "ObservedReg",
    "ModeledEvent",
    "HartProgram",
    "MCProgram",
    "build_program",
    "FamilySpec",
    "available_families",
    "family_hart_count",
    "families_for_hart_count",
    "RegAllocator",
    "RegAllocError",
    "NoisePool",
    "validate",
    "export_litmus",
    "canonical_key",
    "canonical_outcome",
    "parse_assignment_state",
    "parse_litmus_histogram",
    "parse_herd_states",
    "HerdOracle",
    "HerdCache",
    "OracleResult",
    "SeedBundle",
    "LitmusExecutableBackend",
    "MultiCoreGenerationConfig",
    "generate_multicore_seed",
    "generate_multicore_seeds",
]
