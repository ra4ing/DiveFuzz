# Copyright (c) 2024-2025 Institute of Information Engineering, Chinese Academy of Sciences
#
# DiveFuzz is licensed under Mulan PSL v2.
# See http://license.coscl.org.cn/MulanPSL2 for more details.

"""Pre-execution runtime state policy (``exp_pre``).

Information budget: category 1 (static/generated-program information, see
``exp_static_filters``) PLUS the candidate-position architectural state:
- runtime operand values (GPR/FPR reads)
- CSR values, privilege mode, virtualization bit
- LR/SC reservation state, vector configuration state

Structurally denied: anything observed after the candidate executes.

DiveFuzz is the canonical occupant of a subset of this budget: its generator
reconstructs runtime *source operand values* by replaying the program prefix
through the ISS debug interface and uses those values for its dedup filter.
"""

from __future__ import annotations

from ..base import FilterResult, collect_filters_from_caller, pre_execution_filter
from . import exp_static_filters
from .experiment_filter_utils import (
    SCALAR_MEMORY_SIZES,
    is_scalar_misaligned,
    parse_csr_from_operands,
    parse_int_token,
    parse_memory_operand,
)

CSR_WRITE_OPCODES = {"csrrw", "csrrs", "csrrc", "csrrwi", "csrrsi", "csrrci"}
# WARL CSRs whose legal write values are constrained by simple value rules.
MTVEC_ADDRS = {0x305, 0x105, 0x205}  # mtvec, stvec, vstvec (direct mode: low 2 bits 0)
HFENCE_GVMA_OPCODES = {"hfence.gvma"}
# VMID field is at most 14 bits wide in hgatp; bits [63:14] are reserved.
HFENCE_VMID_RESERVED_MASK = (1 << 64) - (1 << 14)


def _op(ctx) -> str:
    return ctx.opcode.lower().strip()


def _opers(ctx) -> list:
    return [op.strip().lower().rstrip(",") for op in ctx.operands]


def _reg_operand_value(ctx, operand_index: int):
    """Value of an integer register operand read from pre-state."""
    if len(ctx.operands) <= operand_index:
        return None
    reg = ctx.parse_register_operand(ctx.operands[operand_index])
    if reg is None:
        return None
    return ctx.get_xpr(reg)


@pre_execution_filter(
    name="PR-scalar-misaligned-ea",
    opcodes=sorted(SCALAR_MEMORY_SIZES.keys()),
    description=(
        "Noise N2: misaligned effective address.  Whether a misaligned access "
        "traps, splits, or is handled by hardware is implementation freedom, so "
        "DUT/ISS behavior may legally differ.  Requires the runtime base "
        "register value; operand text alone cannot see it."
    ),
)
def f_scalar_misaligned(ctx):
    if is_scalar_misaligned(ctx):
        base_reg, imm, sz = parse_memory_operand(ctx)
        ea = (ctx.get_xpr(base_reg) + imm) & ((1 << 64) - 1)
        return FilterResult.reject(
            f"misaligned effective address 0x{ea:x} for size {sz} (N2)"
        )
    return FilterResult.accept()

@pre_execution_filter(
    name="PR-sc-without-reservation",
    opcodes=["sc.w", "sc.d"],
    description=(
        "Noise N4 (deterministic half): SC without a live LR reservation must "
        "fail; the reported failure and its side effects may legally differ "
        "between DUT and ISS.  Observable from the pre-state reservation flag."
    ),
)
def f_sc_without_reservation(ctx):
    if not ctx.has_reservation():
        return FilterResult.reject("SC with no live reservation (N4: must fail; reporting differs)")
    return FilterResult.accept()


@pre_execution_filter(
    name="PR-mtvec-unaligned-write-request",
    opcodes=sorted(CSR_WRITE_OPCODES),
    description=(
        "Noise N3 (request side): a CSR write *requesting* a value mtvec cannot "
        "hold (direct-mode low bits nonzero) is WARL-normalized, and the "
        "normalization choice may legally differ.  Register-form writes need "
        "the runtime rs1 value."
    ),
)
def f_mtvec_unaligned_write(ctx):
    addr = parse_csr_from_operands(_opers(ctx), _op(ctx))
    if addr not in MTVEC_ADDRS:
        return FilterResult.accept()
    if _op(ctx) in {"csrrwi", "csrrsi", "csrrci"}:
        requested = parse_int_token(_opers(ctx)[2]) if len(_opers(ctx)) > 2 else None
    else:
        requested = _reg_operand_value(ctx, 2)
    if requested is None:
        return FilterResult.accept()
    if requested & 0x3:
        return FilterResult.reject(
            f"mtvec write requesting unaligned value 0x{requested & ((1 << 64) - 1):x} (N3)"
        )
    return FilterResult.accept()


@pre_execution_filter(
    name="PR-hfence-gvma-reserved-vmid",
    opcodes=sorted(HFENCE_GVMA_OPCODES),
    description=(
        "Known bug XS#5779 (unfixed): hfence.gvma with reserved VMID bits "
        "(rs2[63:14] != 0) makes the DUT use those bits.  Requires the runtime "
        "rs2 register value."
    ),
)
def f_hfence_gvma_reserved_vmid(ctx):
    # hfence.gvma rs1, rs2  ->  operands[1] is rs2
    value = _reg_operand_value(ctx, 1)
    if value is None:
        return FilterResult.accept()
    if value & HFENCE_VMID_RESERVED_MASK:
        return FilterResult.reject(
            f"hfence.gvma with reserved VMID bits (rs2=0x{value & ((1 << 64) - 1):x}, XS#5779)"
        )
    return FilterResult.accept()


def register_filters(registry):
    # Category 2 is a superset of category 1: the static policy's filters are
    # part of this policy too.
    exp_static_filters.register_filters(registry)
    for f in collect_filters_from_caller():
        registry.register(f)


__all__ = ["register_filters"]
