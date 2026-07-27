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

"""Outcome classification: compare observed outcomes to the allowed set."""

from collections import Counter

from utils.results_reporter import ResultType


def classify_outcomes(
    allowed: set[tuple[tuple[str, int], ...]],
    observed: Counter[tuple[tuple[str, int], ...]],
) -> tuple[ResultType, str]:
    """Classify observed outcomes against the RVWMO/herd allowed set.

    Returns:
        ``(ResultType, summary)``:
        * ``NO_OUTCOME`` when nothing was observed.
        * ``MODEL_VIOLATION`` when an observed outcome is not allowed.
        * ``SUCCESS`` when every observed outcome is allowed.
    """
    if not observed:
        return (ResultType.NO_OUTCOME, "No parseable multicore outcome")

    for outcome in observed:
        if outcome not in allowed:
            return (
                ResultType.MODEL_VIOLATION,
                f"Observed outcome is not allowed by RVWMO/herd: {dict(outcome)}",
            )

    return (
        ResultType.SUCCESS,
        "All observed outcomes are allowed by RVWMO/herd",
    )
