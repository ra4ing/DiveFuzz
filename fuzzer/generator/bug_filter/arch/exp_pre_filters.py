# Copyright (c) 2024-2025 Institute of Information Engineering, Chinese Academy of Sciences
#
# DiveFuzz is licensed under Mulan PSL v2.
# See http://license.coscl.org.cn/MulanPSL2 for more details.

"""Pre-execution runtime state policy (``exp_pre``).

Information budget: category 1 (see exp_static_filters) PLUS the
candidate-position architectural state:
- runtime operand values (GPR/FPR reads)
- CSR values, privilege mode, virtualization bit
- LR/SC reservation state, vector configuration state

Structurally denied: anything observed after the candidate executes.

DiveFuzz occupies a subset of this budget: its generator reconstructs runtime
*source operand values* by replaying the program prefix through the ISS debug
interface and uses those values for its dedup filter.

Registers every signature whose minimum tier is "static" or "pre".
"""

from __future__ import annotations

from .experiment_signatures import register_signatures


def register_filters(registry):
    # Includes every signature of tier "static" and "pre".
    register_signatures(registry, max_tier="pre")


__all__ = ["register_filters"]
