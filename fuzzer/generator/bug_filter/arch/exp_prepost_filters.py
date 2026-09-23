# Copyright (c) 2024-2025 Institute of Information Engineering, Chinese Academy of Sciences
#
# DiveFuzz is licensed under Mulan PSL v2.
# See http://license.coscl.org.cn/MulanPSL2 for more details.

"""Pre- and post-execution runtime state policy (``exp_prepost``).

Information budget: category 1 (static/generated-program information) PLUS
pre-execution runtime state PLUS the actual execution outcome of the
candidate:
- trap occurrence, cause, and tval
- CSR readback values after the write
- write-back values (GPR/FPR destination)
- memory effects, privilege transitions

This is the increment RevFuzz's persistent ISS makes cheap: the candidate has
already executed inside the reference model when these predicates evaluate, and
a rejection rolls the state back.  Filters in the weaker policies cannot copy
these predicates: their information budget has no post-execution view at all.
"""

from __future__ import annotations

from ..base import FilterResult, collect_filters_from_caller, post_execution_filter
from . import exp_pre_filters
from .experiment_filter_utils import (
    parse_csr_from_operands,
    parse_int_token,
)

# CSR-writing canonical opcodes (pseudo read forms never write).
CSR_WRITE_OPCODES = {"csrrw", "csrrs", "csrrc", "csrrwi", "csrrsi", "csrrci"}

# Causes whose tval conventionally carries a value (faulting address or
# instruction bits).  A tval of 0 here is implementation freedom (noise).
VALUE_BEARING_CAUSES = {0, 1, 2, 4, 5, 6, 7, 12, 13, 15}
# WPRI-masked CSR note: mstatus (0x300) writes may drop unsupported bits; the
# dropped-bit choice is implementation freedom.
SCALAR_FP_LOAD_OPCODES = {"flw", "fld", "flh", "flq"}


def _op(ctx) -> str:
    return ctx.opcode.lower().strip()


def _opers(ctx) -> list:
    return [op.strip().lower().rstrip(",") for op in ctx.operands]


def _reg_operand_value_pre(ctx, operand_index: int):
    if len(ctx.operands) <= operand_index:
        return None
    reg = ctx.parse_register_operand(ctx.operands[operand_index])
    if reg is None:
        return None
    return ctx.get_xpr(reg)


@post_execution_filter(
    name="PP-trap-zero-tval",
    description=(
        "Noise N6: on value-bearing fault causes the spec allows xtval to be 0 "
        "or to carry the address/instruction bits.  DUT/ISS choices may differ. "
        "Observable only after the candidate executed and trapped."
    ),
)
def f_trap_zero_tval(ctx):
    if not ctx.was_trapped():
        return FilterResult.accept()
    cause = ctx.get_trap_cause()
    if cause not in VALUE_BEARING_CAUSES:
        return FilterResult.accept()
    if ctx.s_post is None:
        return FilterResult.accept()
    if ctx.s_post.trap_tval == 0:
        return FilterResult.reject(
            f"trap cause {cause} with tval=0 on a value-bearing fault (N6)"
        )
    return FilterResult.accept()


@post_execution_filter(
    name="PP-csr-warl-normalized",
    opcodes=sorted(CSR_WRITE_OPCODES),
    description=(
        "Noise N3 (outcome side): the reference model WARL-normalized a CSR "
        "write (readback != requested).  The DUT may keep the requested value "
        "or normalize differently; both are legal.  Observable only after the "
        "write executed.  Exercised with mstatus WPRI bits, which the pre-side "
        "mtvec alignment rule cannot see."
    ),
)
def f_csr_warl_normalized(ctx):
    addr = parse_csr_from_operands(_opers(ctx), _op(ctx))
    if addr is None:
        return FilterResult.accept()
    if _op(ctx) in {"csrrwi", "csrrsi", "csrrci"}:
        requested = parse_int_token(_opers(ctx)[2]) if len(_opers(ctx)) > 2 else None
    else:
        requested = _reg_operand_value_pre(ctx, 2)
    if requested is None or ctx.s_post is None:
        return FilterResult.accept()
    requested &= (1 << 64) - 1
    readback = ctx.get_post_csr(addr) & ((1 << 64) - 1)
    if readback != requested:
        return FilterResult.reject(
            f"CSR 0x{addr:x} write normalized: requested 0x{requested:x}, "
            f"readback 0x{readback:x} (N3)"
        )
    return FilterResult.accept()


@post_execution_filter(
    name="PP-sc-failed",
    opcodes=["sc.w", "sc.d"],
    description=(
        "Noise N4 (outcome side): SC that failed (destination != 0).  Spurious "
        "failure with a live reservation is implementation freedom; the DUT may "
        "succeed where the ISS fails or vice versa.  Requires the write-back "
        "value of the destination register."
    ),
)
def f_sc_failed(ctx):
    dest = ctx.get_destination_register()
    if dest is None or ctx.s_post is None:
        return FilterResult.accept()
    if ctx.s_post.get_xpr(dest) != 0:
        return FilterResult.reject("SC failed (rd != 0) (N4)")
    return FilterResult.accept()


@post_execution_filter(
    name="PP-fp-load-fault",
    opcodes=sorted(SCALAR_FP_LOAD_OPCODES),
    description=(
        "Known bug XS#4639 (fixed): fld that takes a load fault made the DUT "
        "write random mtval bits.  The trigger signature — a scalar floating "
        "point load that faults — is only observable after execution."
    ),
)
def f_fp_load_fault(ctx):
    if ctx.was_trapped() and ctx.get_trap_cause() in {4, 5}:
        return FilterResult.reject(
            f"{_op(ctx)} load fault (cause {ctx.get_trap_cause()}) (XS#4639)"
        )
    return FilterResult.accept()


def register_filters(registry):
    # Category 3 is a superset of categories 1 and 2.
    exp_pre_filters.register_filters(registry)
    for f in collect_filters_from_caller():
        registry.register(f)


__all__ = ["register_filters"]
