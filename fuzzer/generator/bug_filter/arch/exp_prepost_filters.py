# Copyright (c) 2024-2025 Institute of Information Engineering, Chinese Academy of Sciences
#
# DiveFuzz is licensed under Mulan PSL v2.
# See http://license.coscl.org.cn/MulanPSL2 for more details.

"""Pre- and post-execution runtime state policy (``exp_prepost``).

Information budget: category 1 + pre-execution runtime state PLUS the actual
execution outcome of the candidate:
- trap occurrence, cause, and tval
- CSR readback values after the write, fflags transitions
- write-back values (GPR/FPR destination)
- memory effects, privilege transitions

This is the increment RevFuzz's persistent ISS makes cheap: the candidate has
already executed inside the reference model when these predicates evaluate,
and a rejection rolls the state back.

Registers every signature (tiers static, pre, and post).
"""

from __future__ import annotations

from .experiment_signatures import register_signatures


def register_filters(registry):
    # Includes every signature of tier "static", "pre", and "post".
    register_signatures(registry, max_tier="post")


__all__ = ["register_filters"]
