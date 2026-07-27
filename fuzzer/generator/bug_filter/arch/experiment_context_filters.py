# Copyright (c) 2024-2025 Institute of Information Engineering, Chinese Academy of Sciences
# DiveFuzz is licensed under Mulan PSL v2.

"""Context-aware filter policy — 15 filters, one per noise/bug item.

Includes the 6 precise operand-text filters (counter_csr, misaligned_ea,
warl_addr, vsetvl_reserved, vmv_alignment, frm_immediate) and adds pre-state
CSR/privilege and post-state predicates for the remaining items.
"""

from __future__ import annotations

from ..base import FilterResult, collect_filters_from_caller, post_execution_filter, pre_execution_filter
from .experiment_filter_utils import (
    CSR_FRM, CSR_MSTATUS, CSR_MTVAL, CSR_STVAL, CSR_VL, CSR_VTYPE, CSR_VSTART,
    ALL_CSR_OPCODES, HFENCE_OPCODES, LR_SC_OPCODES, MSTATUS_TW,
    opcode as _op, parse_csr_from_operands, parse_int_token as _int,
)


# ── N1: CSR counter read ── (from operand text, same as operand) ──

@pre_execution_filter(name="CTX-N1_counter_csr", description="N1: reject CSR counter reads from CSR address in operands")
def f_N1(ctx):
    from .experiment_filter_utils import is_counter_or_timer_csr
    addr = parse_csr_from_operands(ctx.operands, _op(ctx))
    return FilterResult.reject("N1") if is_counter_or_timer_csr(addr, False) else FilterResult.accept()


# ── N2: Misaligned memory (POST-state: only reject when actual trap cause is misaligned) ──

@post_execution_filter(name="CTX-N2_misaligned_post", description="N2: reject only when post trap cause is address-misaligned (4/6)")
def f_N2(ctx):
    if ctx.s_post and ctx.was_trapped() and ctx.get_trap_cause() in {4, 6}:
        return FilterResult.reject("N2")
    return FilterResult.accept()


# ── N3: CSR WARL (POST-state: compare intended vs actual) ──

_WARL = {0x305, 0x105, 0x205, 0x300, 0x3A0, 0x3A1, 0x3A2, 0x3A3, 0x7a1}

def _expected(ctx, addr):
    op, pre, mask = _op(ctx), ctx.get_csr(addr), (1 << 64) - 1
    if op == "csrrw" and len(ctx.operands) >= 3:
        s = ctx.parse_register_operand(ctx.operands[2])
        return ctx.get_xpr(s) & mask if s is not None else None
    if op == "csrrwi" and len(ctx.operands) > 2: return _int(ctx.operands[2])
    if op in {"csrrs", "csrrc"} and len(ctx.operands) >= 3:
        s = ctx.parse_register_operand(ctx.operands[2])
        if s is None: return None
        v = ctx.get_xpr(s)
        return (pre | v) & mask if op == "csrrs" else (pre & ~v) & mask
    if op in {"csrrsi", "csrrci"}:
        imm = _int(ctx.operands[2]) if len(ctx.operands) > 2 else None
        return ((pre | imm) if op == "csrrsi" else (pre & ~imm)) & mask if imm is not None else None
    if op == "csrw" and len(ctx.operands) >= 2:
        s = ctx.parse_register_operand(ctx.operands[1])
        return ctx.get_xpr(s) & mask if s is not None else None
    if op == "csrwi" and len(ctx.operands) > 1: return _int(ctx.operands[1])
    return None

@post_execution_filter(name="CTX-N3_csr_warl", opcodes=sorted(ALL_CSR_OPCODES), description="N3/#5721: post-state WARL normalization check")
def f_N3(ctx):
    if ctx.s_post is None: return FilterResult.accept()
    addr = parse_csr_from_operands(ctx.operands, _op(ctx))
    if addr not in _WARL: return FilterResult.accept()
    exp = _expected(ctx, addr)
    if exp is not None and ctx.get_post_csr(addr) != exp:
        return FilterResult.reject("N3")
    return FilterResult.accept()


# ── N4: SC spurious failure (POST-state: check dest register) ──

@post_execution_filter(name="CTX-N4_sc", opcodes=["sc.w", "sc.d"], description="N4: reject SC when dest=0 (failed)")
def f_N4(ctx):
    if ctx.s_post is None: return FilterResult.accept()
    d = ctx.get_destination_register()
    return FilterResult.reject("N4") if d is not None and ctx.get_post_xpr(d) != 0 else FilterResult.accept()


# ── N5: WFI TW (PRE-state: privilege + mstatus) ──

@pre_execution_filter(name="CTX-N5_wfi", opcodes=["wfi"], description="N5: reject WFI when mstatus.TW=1 below M-mode")
def f_N5(ctx):
    if ctx.get_privilege() < 3 and (ctx.get_csr(CSR_MSTATUS) & MSTATUS_TW):
        return FilterResult.reject("N5")
    return FilterResult.accept()


# ── N6: Trap xtval=0 (POST-state: check mtval/stval) ──

@post_execution_filter(name="CTX-N6_trap_xtval", description="N6: reject trapped when xtval=0 on value-bearing faults")
def f_N6(ctx):
    if ctx.s_post is None or not ctx.was_trapped(): return FilterResult.accept()
    if ctx.get_trap_cause() in {1, 2, 5, 7, 12, 13, 15}:
        if ctx.get_post_csr(CSR_MTVAL) == 0 and ctx.get_post_csr(CSR_STVAL) == 0:
            return FilterResult.reject("N6")
    return FilterResult.accept()


# ── N7: Vector agnostic (POST-state: vl<vlmax + vta/vma) ──

@post_execution_filter(name="CTX-N7_vector_agnostic", description="N7: reject vector ops in active agnostic context")
def f_N7(ctx):
    if ctx.s_post is None or not _op(ctx).startswith("v") or ctx.was_trapped(): return FilterResult.accept()
    vl, vlmax = ctx.get_post_vl(), ctx.get_vlmax()
    if vlmax > 0 and vl < vlmax and (ctx.get_vta() or ctx.get_vma()):
        return FilterResult.reject("N7")
    return FilterResult.accept()


# ── #2642: fmadd.d NaN (POST-state: non-canonical NaN) ──

@post_execution_filter(name="CTX-B1_fmadd_nan", opcodes=["fmadd.d"], description="#2642: reject non-canonical NaN in post-state")
def f_B1(ctx):
    if ctx.s_post is None: return FilterResult.accept()
    d = ctx.get_destination_register()
    if d is None: return FilterResult.accept()
    v = ctx.get_post_fpr(d)
    exp, frac = (v >> 52) & 0x7FF, v & ((1 << 52) - 1)
    if exp == 0x7FF and frac != 0 and frac != 0x8000000000000:
        return FilterResult.reject("B1")
    return FilterResult.accept()


# ── #4639: fld random mtval (POST-state: non-zero mtval on trap) ──

@post_execution_filter(name="CTX-B2_fld_mtval", opcodes=["fld"], description="#4639: reject fld trap with non-zero mtval")
def f_B2(ctx):
    if ctx.s_post is None or not ctx.was_trapped(): return FilterResult.accept()
    return FilterResult.reject("B2") if ctx.get_post_csr(CSR_MTVAL) != 0 else FilterResult.accept()



@post_execution_filter(name="CTX-B3_mcontrol6", opcodes=sorted(ALL_CSR_OPCODES), description="#5721: reject mcontrol6 chain bit WARL change")
def f_B3(ctx):
    if ctx.s_post is None: return FilterResult.accept()
    addr = parse_csr_from_operands(ctx.operands, _op(ctx))
    if addr != 0x7a1: return FilterResult.accept()
    pre_chain = (ctx.get_csr(addr) >> 11) & 1
    post_chain = (ctx.get_post_csr(addr) >> 11) & 1
    return FilterResult.reject("B3") if pre_chain != post_chain else FilterResult.accept()

# ── #5725: reserved vsetvl ── (operand text, same as operand) ──

@pre_execution_filter(name="CTX-B4_vsetvl_reserved", description="#5725: reject reserved vsetvl encoding (rd=x0, rs1=x0)")
def f_B4(ctx):
    if _op(ctx) not in {"vsetvl", "vsetvli"}: return FilterResult.accept()
    ops = [o.strip().lower().rstrip(",") for o in ctx.operands]
    return FilterResult.reject("B4") if len(ops) >= 3 and ops[0] == "x0" and ops[1] == "x0" else FilterResult.accept()


# ── #5765: vlm.v tail ── (POST-state: tail-undisturbed context) ──

@post_execution_filter(name="CTX-B5_vlm_tail", opcodes=["vlm.v"], description="#5765: reject vlm.v in tail-undisturbed agnostic context")
def f_B5(ctx):
    if ctx.s_post is None: return FilterResult.accept()
    vl, vlmax = ctx.get_post_vl(), ctx.get_vlmax()
    if vlmax > 0 and vl < vlmax and ctx.get_vta() == 0:
        return FilterResult.reject("B5")
    return FilterResult.accept()


# ── #5766: vle8ff.v vl=0 ── (POST-state: FOF + trap + vl==0) ──

@post_execution_filter(name="CTX-B6_vle8ff_vl0", description="#5766: reject FOF load when vl=0 after trap")
def f_B6(ctx):
    if ctx.s_post is None or not _op(ctx).endswith("ff.v"): return FilterResult.accept()
    if ctx.was_trapped() and ctx.get_trap_cause() == 13 and ctx.get_post_csr(CSR_VL) == 0:
        return FilterResult.reject("B6")
    return FilterResult.accept()


# ── #5767: vlseg double-trap ── (POST-state: double-trap) ──

@post_execution_filter(name="CTX-B7_vlseg_double", description="#5767: reject segment FOF with double-trap")
def f_B7(ctx):
    if ctx.s_post is None or not _op(ctx).startswith("vlseg"): return FilterResult.accept()
    if ctx.was_trapped() and "dbltrp" in ctx.get_trap_name().lower():
        return FilterResult.reject("B7")
    return FilterResult.accept()


# ── #5769: vsuxseg mtval offset ── (POST-state: mtval mismatch) ──

@post_execution_filter(name="CTX-B8_vsuxseg_mtval", description="#5769: reject vsuxseg when post mtval lacks index offset")
def f_B8(ctx):
    if ctx.s_post is None or not _op(ctx).startswith("vsuxseg"): return FilterResult.accept()
    if ctx.was_trapped() and "store" in ctx.get_trap_name().lower():
        rs1 = ctx.parse_register_operand(ctx.operands[1]) if len(ctx.operands) > 1 else None
        if rs1 is not None:
            expected = ctx.get_xpr(rs1)
            mtval = ctx.get_post_csr(CSR_MTVAL)
            if mtval < expected or mtval > expected + 0x1000:
                return FilterResult.reject("B8")
    return FilterResult.accept()


def register_filters(registry):
    for f in collect_filters_from_caller():
        registry.register(f)

__all__ = ["register_filters"]
