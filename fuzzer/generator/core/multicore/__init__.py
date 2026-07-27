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

This package generates model-checkable 2-hart multicore RISC-V test programs,
exports them to ``.litmus`` form, queries the RVWMO/herd oracle for allowed
outcomes, and (optionally) builds a litmus7-compatible executable.
"""

from .model import (
    EventKind,
    SharedVar,
    ObservedReg,
    ModeledEvent,
    HartProgram,
    MCProgram,
)
from .families import build_program
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
    "validate",
    "export_litmus",
    "canonical_key",
    "canonical_outcome",
    "parse_assignment_state",
    "parse_litmus_histogram",
    "parse_herd_states",
    "HerdOracle",
    "OracleResult",
    "SeedBundle",
    "LitmusExecutableBackend",
    "MultiCoreGenerationConfig",
    "generate_multicore_seed",
    "generate_multicore_seeds",
]
