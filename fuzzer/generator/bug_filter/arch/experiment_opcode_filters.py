# Copyright (c) 2024-2025 Institute of Information Engineering, Chinese Academy of Sciences
# DiveFuzz is licensed under Mulan PSL v2.

"""Opcode-only filter policy — 15 filters, one per noise/bug item.

Each filter rejects by opcode class.  Items in the same class share the same
rejection logic but are named individually for tracking.
"""

from __future__ import annotations
from ..base import FilterResult, collect_filters_from_caller, pre_execution_filter

def _op(ctx): return ctx.opcode.lower().strip()
_CSR = {"csrrw","csrrs","csrrc","csrrwi","csrrsi","csrrci","csrr","csrw","csrs","csrc","csrwi","csrsi","csrci"}
_MEM = {"lb","lbu","lh","lhu","lw","lwu","ld","sb","sh","sw","sd","flw","fld","fsw","fsd","flh","fsh","flq","fsq"}
_LRSC = {"lr.w","lr.d","sc.w","sc.d"}
_FENCE = {"hfence.gvma","hfence.vvma","sfence.vma"}

@pre_execution_filter(name="OP-N1_counter_csr", description="N1: reject all CSR (counter reads are CSR class)")
def f_N1(ctx): return FilterResult.reject("N1") if _op(ctx) in _CSR else FilterResult.accept()

@pre_execution_filter(name="OP-N2_misaligned", description="N2: reject all scalar memory (misaligned is memory class)")
def f_N2(ctx): return FilterResult.reject("N2") if _op(ctx) in _MEM else FilterResult.accept()

@pre_execution_filter(name="OP-N3_csr_warl", description="N3: reject all CSR (WARL writes are CSR class)")
def f_N3(ctx): return FilterResult.reject("N3") if _op(ctx) in _CSR else FilterResult.accept()

@pre_execution_filter(name="OP-N4_sc", description="N4: reject all LR/SC")
def f_N4(ctx): return FilterResult.reject("N4") if _op(ctx) in _LRSC else FilterResult.accept()

@pre_execution_filter(name="OP-N5_wfi", description="N5: reject all WFI")
def f_N5(ctx): return FilterResult.reject("N5") if _op(ctx)=="wfi" else FilterResult.accept()

@pre_execution_filter(name="OP-N6_trap_xtval", description="N6: trap is runtime, opcode cannot see — always accept")
def f_N6(ctx): return FilterResult.accept()

@pre_execution_filter(name="OP-N7_vector_agnostic", description="N7: reject all vector opcodes")
def f_N7(ctx): return FilterResult.reject("N7") if _op(ctx).startswith("v") else FilterResult.accept()

@pre_execution_filter(name="OP-B1_fmadd_nan", description="#2642: fmadd.d is other class, opcode cannot filter — accept")
def f_B1(ctx): return FilterResult.accept()

@pre_execution_filter(name="OP-B2_fld_mtval", description="#4639: reject all scalar memory (fld is memory class)")
def f_B2(ctx): return FilterResult.reject("B2") if _op(ctx) in _MEM else FilterResult.accept()

@pre_execution_filter(name="OP-B3_mcontrol6", description="#5721: reject all CSR (mcontrol6 is CSR class)")
def f_B3(ctx): return FilterResult.reject("B3") if _op(ctx) in _CSR else FilterResult.accept()

@pre_execution_filter(name="OP-B4_vsetvl_reserved", description="#5725: vsetvl is other class, opcode cannot filter — accept")
def f_B4(ctx): return FilterResult.accept()

@pre_execution_filter(name="OP-B5_vlm_tail", description="#5765: reject all vector")
def f_B5(ctx): return FilterResult.reject("B5") if _op(ctx).startswith("v") else FilterResult.accept()

@pre_execution_filter(name="OP-B6_vle8ff_vl", description="#5766: reject all vector")
def f_B6(ctx): return FilterResult.reject("B6") if _op(ctx).startswith("v") else FilterResult.accept()

@pre_execution_filter(name="OP-B7_vlseg_double", description="#5767: reject all vector")
def f_B7(ctx): return FilterResult.reject("B7") if _op(ctx).startswith("v") else FilterResult.accept()

@pre_execution_filter(name="OP-B8_vsuxseg_mtval", description="#5769: reject all vector")
def f_B8(ctx): return FilterResult.reject("B8") if _op(ctx).startswith("v") else FilterResult.accept()

def register_filters(registry):
    for f in collect_filters_from_caller():
        registry.register(f)
__all__ = ["register_filters"]
