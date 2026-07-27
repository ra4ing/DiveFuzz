# Copyright (c) 2024-2025 Institute of Information Engineering, Chinese Academy of Sciences
# DiveFuzz is licensed under Mulan PSL v2.

"""Operand-only filter policy — 15 filters, one per noise/bug item.

Uses opcode text, operand text, and source operand register values (ctx.get_xpr).
Cannot access CSR values, privilege, effective addresses, or post-state.
"""

from __future__ import annotations
import re
from typing import Optional
from ..base import FilterResult, collect_filters_from_caller, pre_execution_filter
from ...asm_template_manager.riscv_asm_syntex.csr import CSR_NAME_TO_ADDR

def _op(ctx): return ctx.opcode.lower().strip()
def _opers(ctx): return [op.strip().lower().rstrip(",") for op in ctx.operands]
def _int(s: str) -> Optional[int]:
    try: return int(s, 0)
    except: return None

def _csr_addr(ctx) -> Optional[int]:
    op, ops = _op(ctx), _opers(ctx)
    idx = 0 if op in {"csrw","csrs","csrc","csrwi","csrsi","csrci"} else (1 if op=="csrr" else 1)
    if len(ops) <= idx: return None
    v = _int(ops[idx])
    return v if v is not None else CSR_NAME_TO_ADDR.get(ops[idx])

_MEM_RE = re.compile(r"^(-?(?:0x[0-9a-fA-F]+|\d+))?\(([^)]+)\)$")
_SIZES = {"lb":1,"lbu":1,"lh":2,"lhu":2,"lw":4,"lwu":4,"ld":8,"sb":1,"sh":2,"sw":4,"sd":8,"flw":4,"fld":8,"fsw":4,"fsd":8,"flh":2,"fsh":2,"flq":16,"fsq":16}

_HPM = lambda a: a and ((0xC03<=a<=0xC1F)or(0xC83<=a<=0xC9F)or(0xB03<=a<=0xB1F)or(0xB83<=a<=0xB9F))
_COUNTER = lambda a: a in {0xC00,0xB00,0xC80,0xB80,0xC01,0xC81} or _HPM(a)
_WARL = {0x305,0x105,0x205,0x300,0x3A0,0x3A1,0x3A2,0x3A3,0x7a1}

@pre_execution_filter(name="OP-N1_counter_csr", description="N1: reject CSR counter/timer reads from operand text")
def f_N1(ctx):
    addr = _csr_addr(ctx)
    return FilterResult.reject("N1") if _COUNTER(addr) else FilterResult.accept()

@pre_execution_filter(name="OP-N2_misaligned", description="N2: reject scalar mem with misaligned EA (base reg value + offset)")
def f_N2(ctx):
    sz = _SIZES.get(_op(ctx)); ops = _opers(ctx)
    if not sz or sz<=1 or len(ops)<2: return FilterResult.accept()
    m = _MEM_RE.match(ops[-1].replace(" ",""))
    if not m: return FilterResult.accept()
    imm = int(m.group(1),0) if m.group(1) else 0
    base = ctx.parse_register_operand(m.group(2))
    if base is None: return FilterResult.accept()
    return FilterResult.reject("N2") if ((ctx.get_xpr(base)+imm)&((1<<64)-1)) % sz != 0 else FilterResult.accept()

@pre_execution_filter(name="OP-N3_csr_warl", description="N3: reject CSR writes to WARL addresses (mtvec/stvec/mstatus/pmpcfg/mcontrol6)")
def f_N3(ctx):
    return FilterResult.reject("N3") if _csr_addr(ctx) in _WARL else FilterResult.accept()

@pre_execution_filter(name="OP-N4_sc", description="N4: reject all SC instructions")
def f_N4(ctx):
    return FilterResult.reject("N4") if _op(ctx) in {"sc.w","sc.d"} else FilterResult.accept()

@pre_execution_filter(name="OP-N5_wfi", description="N5: reject all WFI")
def f_N5(ctx):
    return FilterResult.reject("N5") if _op(ctx)=="wfi" else FilterResult.accept()

@pre_execution_filter(name="OP-N6_trap_xtval", description="N6: trap is runtime event, operand cannot filter — always accept")
def f_N6(ctx):
    return FilterResult.accept()

@pre_execution_filter(name="OP-N7_vector_agnostic", description="N7: reject all vector opcodes")
def f_N7(ctx):
    return FilterResult.reject("N7") if _op(ctx).startswith("v") else FilterResult.accept()

@pre_execution_filter(name="OP-B1_fmadd_nan", description="#2642: post FPR needed, operand cannot — accept")
def f_B1(ctx):
    return FilterResult.accept()

@pre_execution_filter(name="OP-B2_fld_mtval", description="#4639: post mtval needed, operand cannot — accept")
def f_B2(ctx):
    return FilterResult.accept()

@pre_execution_filter(name="OP-B3_mcontrol6", description="#5721: reject CSR write to mcontrol6 (WARL addr)")
def f_B3(ctx):
    return FilterResult.reject("B3") if _csr_addr(ctx)==0x7a1 else FilterResult.accept()

@pre_execution_filter(name="OP-B4_vsetvl_reserved", description="#5725: reject reserved vsetvl/vsetvli (rd=x0, rs1=x0)")
def f_B4(ctx):
    if _op(ctx) not in {"vsetvl","vsetvli"}: return FilterResult.accept()
    ops = _opers(ctx)
    return FilterResult.reject("B4") if len(ops)>=3 and ops[0]=="x0" and ops[1]=="x0" else FilterResult.accept()

@pre_execution_filter(name="OP-B5_vlm_tail", description="#5765: reject all vector (vlm.v tail context)")
def f_B5(ctx):
    return FilterResult.reject("B5") if _op(ctx).startswith("v") else FilterResult.accept()

@pre_execution_filter(name="OP-B6_vle8ff_vl", description="#5766: reject all vector (FOF load vl context)")
def f_B6(ctx):
    return FilterResult.reject("B6") if _op(ctx).startswith("v") else FilterResult.accept()

@pre_execution_filter(name="OP-B7_vlseg_double", description="#5767: reject all vector (segment FOF context)")
def f_B7(ctx):
    return FilterResult.reject("B7") if _op(ctx).startswith("v") else FilterResult.accept()

@pre_execution_filter(name="OP-B8_vsuxseg_mtval", description="#5769: reject all vector (indexed store mtval context)")
def f_B8(ctx):
    return FilterResult.reject("B8") if _op(ctx).startswith("v") else FilterResult.accept()

def register_filters(registry):
    for f in collect_filters_from_caller():
        registry.register(f)
__all__ = ["register_filters"]
