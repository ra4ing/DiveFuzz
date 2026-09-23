# Copyright (c) 2024-2025 Institute of Information Engineering, Chinese Academy of Sciences
#
# DiveFuzz is licensed under Mulan PSL v2.
# See http://license.coscl.org.cn/MulanPSL2 for more details.

"""Static / generated-program information policy (``exp_static``).

Information budget (category 1 only):
- opcode and operand TEXT (register names, CSR names/addresses, immediates)
- machine code / assembly text
- target configuration (ISA knowledge such as CSR address ranges)
- generation history: instructions already accepted into the program

Structurally denied: any runtime register/CSR value, privilege, reservation,
vector state, and anything observed after execution.  The runner enforces this
by building FilterContext with ``spike_session=None, s_pre=None, s_post=None``;
every value-query helper on such a context returns inert defaults.

Cascade-style generators operate in this budget: they reason about the program
they are building and configuration knowledge, never about live CPU state.
"""

from __future__ import annotations

from ..base import FilterResult, collect_filters_from_caller, pre_execution_filter
from .experiment_filter_utils import (
    ALL_CSR_OPCODES,
    is_counter_or_timer_csr,
    parse_csr_from_operands,
)

# How far back into the accepted-program history a static filter may look.
HISTORY_WINDOW = 8


def _op(ctx) -> str:
    return ctx.opcode.lower().strip()


def _opers(ctx) -> list:
    return [op.strip().lower().rstrip(",") for op in ctx.operands]


def _history_tokens(ctx) -> list:
    """Lower-cased opcode tokens of the accepted-program history tail."""
    tail = list(getattr(ctx, "history", []))[-HISTORY_WINDOW:]
    return [line.strip().lower().split()[0] for line in tail if line.strip()]


@pre_execution_filter(
    name="ST-counter-csr",
    opcodes=sorted(ALL_CSR_OPCODES),
    description=(
        "Noise N1: counter/timer CSR values (cycle/time/hpmcounter) are "
        "implementation-sensitive; DUT/ISS readbacks may legally differ. "
        "Expressible from CSR address text alone."
    ),
)
def f_counter_csr(ctx):
    addr = parse_csr_from_operands(_opers(ctx), _op(ctx))
    if is_counter_or_timer_csr(addr):
        return FilterResult.reject(
            f"counter/timer CSR 0x{addr:x}: implementation-sensitive value"
        )
    return FilterResult.accept()


@pre_execution_filter(
    name="ST-vsetvl-reserved-encoding",
    opcodes=["vsetvl", "vsetvli"],
    description=(
        "Known bug XS#5725 (fixed): vsetvl with rd=x0 and rs1=x0 is a reserved "
        "encoding that some DUTs fail to trap.  Detectable from operand text."
    ),
)
def f_vsetvl_reserved(ctx):
    ops = _opers(ctx)
    if len(ops) >= 2 and ops[0] == "x0" and ops[1] == "x0":
        return FilterResult.reject("vsetvl rd=x0, rs1=x0 reserved encoding (XS#5725)")
    return FilterResult.accept()


@pre_execution_filter(
    name="ST-csrr-vl-after-vsetvl",
    opcodes=sorted(ALL_CSR_OPCODES),
    description=(
        "Known bug XS#5739 (unfixed): csrr vl right after a vsetvli can read a "
        "stale vl on the DUT.  The trigger pattern is program structure: a vl "
        "read that closely follows vector-length configuration.  Generation "
        "history is static/generated-program information."
    ),
)
def f_csrr_vl_after_vsetvl(ctx):
    addr = parse_csr_from_operands(_opers(ctx), _op(ctx))
    if addr != 0xC20:  # vl
        return FilterResult.accept()
    if any(tok.startswith("vsetvl") for tok in _history_tokens(ctx)):
        return FilterResult.reject("csrr vl within history window after vsetvli (XS#5739)")
    return FilterResult.accept()


def register_filters(registry):
    for f in collect_filters_from_caller():
        registry.register(f)


__all__ = ["register_filters"]
