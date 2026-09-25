# Copyright (c) 2024-2025 Institute of Information Engineering, Chinese Academy of Sciences
#
# DiveFuzz is licensed under Mulan PSL v2.
# See http://license.coscl.org.cn/MulanPSL2 for more details.

"""Opcode + operand-text policy (``exp_text``).

Information budget: opcode and operand TEXT only (register names, CSR
names/addresses, immediates).  No generation history, no runtime state, no
execution outcome.  The runner enforces this structurally: FilterContext
without spike_session, s_pre, s_post, history, or env.

This is the grain classic known-bug tables use (per-instruction text
patterns).  Paper-level grouping: static information.
"""

from __future__ import annotations

from .experiment_signatures import register_signatures


def register_filters(registry):
    # Includes every signature: precise for text-tier predicates, class
    # fallback for the rest (best-effort interception).
    register_signatures(registry, group_tier="text")


__all__ = ["register_filters"]
