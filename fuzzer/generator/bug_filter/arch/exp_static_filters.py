# Copyright (c) 2024-2025 Institute of Information Engineering, Chinese Academy of Sciences
#
# DiveFuzz is licensed under Mulan PSL v2.
# See http://license.coscl.org.cn/MulanPSL2 for more details.

"""Static / generated-program information policy (``exp_static``).

Information budget (category 1 only):
- opcode and operand TEXT (register names, CSR names/addresses, immediates)
- ISA / target-configuration knowledge
- generation history: instructions already accepted into the program

Structurally denied: any runtime register/CSR value, privilege, reservation,
vector state, and anything observed after execution.  The per-case runner
enforces this by building FilterContext with ``spike_session=None, s_pre=None,
s_post=None``.

All filters come from the shared signature table (experiment_signatures);
this module registers every signature whose minimum tier is "static".
"""

from __future__ import annotations

from .experiment_signatures import register_signatures


def register_filters(registry):
    register_signatures(registry, max_tier="static")


__all__ = ["register_filters"]
