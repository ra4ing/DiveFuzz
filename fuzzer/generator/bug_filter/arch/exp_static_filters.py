# Copyright (c) 2024-2025 Institute of Information Engineering, Chinese Academy of Sciences
#
# DiveFuzz is licensed under Mulan PSL v2.
# See http://license.coscl.org.cn/MulanPSL2 for more details.

"""Static / generated-program information policy (``exp_static``).

Information budget: opcode and operand TEXT, ISA / target-configuration
knowledge, and the accepted-program generation history (including recorded
execution facts of already-accepted instructions).  Structurally denied:
runtime state and execution outcomes.

Paper-level grouping: static information (superset of exp_text).
"""

from __future__ import annotations

from .experiment_signatures import register_signatures


def register_filters(registry):
    register_signatures(registry, group_tier="static")


__all__ = ["register_filters"]
