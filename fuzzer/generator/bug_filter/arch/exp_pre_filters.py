# Copyright (c) 2024-2025 Institute of Information Engineering, Chinese Academy of Sciences
#
# DiveFuzz is licensed under Mulan PSL v2.
# See http://license.coscl.org.cn/MulanPSL2 for more details.

"""pre-execution runtime state policy.

See experiment_signatures for the tier definitions; every signature is
registered (precise within budget, class fallback below it).
"""

from __future__ import annotations

from .experiment_signatures import register_signatures


def register_filters(registry):
    register_signatures(registry, group_tier="pre")


__all__ = ["register_filters"]
