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

"""DiveFuzz-MC multicore executor: run litmus7-compatible ELF seeds on a DUT,
classify observed outcomes against the RVWMO/herd allowed set, and archive any
non-success result.
"""

from .oracle import classify_outcomes
from .runner import (
    XiangShanMultiCoreRunner,
    MultiCoreRunResult,
    run_multicore_test,
)
from .archive import archive_multicore_result

__all__ = [
    "classify_outcomes",
    "XiangShanMultiCoreRunner",
    "MultiCoreRunResult",
    "run_multicore_test",
    "archive_multicore_result",
]
