# Copyright (c) 2024-2025 Institute of Information Engineering, Chinese Academy of Sciences
#
# DiveFuzz is licensed under Mulan PSL v2.
# See http://license.coscl.org.cn/MulanPSL2 for more details.

"""Signature table for the filtering-specificity experiment.

Each entry describes one known suppression target — a RISC-V-legal difference
(noise) or a real acknowledged CPU bug — as a declarative predicate plus the
minimum information tier that can express it:

  tier "static"  opcode/operand text, ISA knowledge, generation history
  tier "pre"     adds candidate-position runtime state (pre-execution)
  tier "post"    adds the actual execution outcome (post-execution)

A signature is registered in every policy whose information budget covers its
tier (policies are supersets).  Evaluators are generic per predicate class;
adding a case means adding a table row, not new filter code.

Predicate classes
-----------------
opcode_set          opcode ∈ set / has prefix                       [static]
operand_csr_addr    CSR address text ∈ set                           [static]
operand_reg_align   register-number alignment of operand i           [static]
operand_reserved    exact operand-token pattern (e.g. vsetvl x0,x0)  [static]
operand_masked      trailing mask operand (v0.t) present             [static]
history_seq         trigger matches pattern X with setup history Y   [static]
reg_value_bits      runtime register value bits set / zero           [pre]
csr_write_bits      CSR write requests bits in mask                  [pre]
csr_state_bits      CSR value ∈ set (e.g. reserved frm)              [pre]
vector_state        vl/vtype predicate (vl<vlmax, sew, ta/ma)        [pre]
ea_misaligned       effective address misaligned (scalar or vector)  [pre]
ea_cross_boundary   access crosses a 2^k boundary                    [pre]
trap_on             trapped with cause ∈ set on opcode class         [post]
csr_readback_dropped WARL/WPRI dropped requested bits                [post]
fpr_nan_result      FP destination register is NaN after execution   [post]
"""

from __future__ import annotations

import re
from typing import Optional

from ..base import (
    FilterResult,
    PrecisionFilter,
    PreExecutionFilter,
    PostExecutionFilter,
    FilterPhase,
)
from .experiment_filter_utils import (
    ALL_CSR_OPCODES,
    SCALAR_MEMORY_SIZES,
    parse_csr_from_operands,
    parse_int_token,
    parse_memory_operand,
)

TIERS = ("static", "pre", "post")
TIER_RANK = {t: i for i, t in enumerate(TIERS)}

FULL64 = (1 << 64) - 1

# ---------------------------------------------------------------------------
# Signature table
# ---------------------------------------------------------------------------

SIGNATURES = [
    # ---- noise (RISC-V-legal implementation differences) ----
    dict(id="n1-counter-csr", tier="static", phase="pre", kind="operand_csr_addr",
         csr_sets="counter", source="spec: counter/timer values implementation-sensitive"),
    dict(id="n2-misaligned-ea", tier="pre", phase="pre", kind="ea_misaligned",
         opcodes=sorted(SCALAR_MEMORY_SIZES), source="spec: misaligned handling is implementation freedom"),
    dict(id="n3a-mtvec-unaligned", tier="pre", phase="pre", kind="csr_write_bits",
         csr=[0x305, 0x105, 0x205], mask=0x3, source="spec: mtvec WARL"),
    dict(id="n3b-wpri-dropped", tier="post", phase="post", kind="csr_readback_dropped",
         source="spec: WPRI bits may be dropped"),
    dict(id="n4-sc-no-reservation", tier="pre", phase="pre", kind="sc_no_reservation",
         source="spec: SC failure reporting is implementation freedom"),
    # ---- XiangShan acknowledged bugs ----
    dict(id="xs2464", tier="static", phase="pre", kind="history_seq",
         source="XS#2464 fixed: fused slli+add mis-decode"),
    dict(id="xs2642", tier="post", phase="post", kind="fpr_nan_result",
         opcodes=["fmadd.d"], source="XS#2642 fixed: fmadd.d non-canonical NaN"),
    dict(id="xs4639", tier="post", phase="post", kind="trap_on",
         opcodes=["fld"], causes=[4, 5], source="XS#4639 fixed: fld fault random mtval"),
    dict(id="xs5695", tier="pre", phase="pre", kind="ea_misaligned",
         opcodes=["lw", "sw", "ld", "sd", "lb", "lbu", "sb", "lh", "lhu", "sh"],
         region=[0x10000000, 0x1F000000], source="XS#5695 fixed: MMIO misaligned wrong exception"),
    dict(id="xs5721", tier="pre", phase="pre", kind="csr_write_bits",
         csr=[0x7A1], mask=0x10, source="XS#5721 open: mcontrol6 chain WARL"),
    dict(id="xs5725", tier="static", phase="pre", kind="operand_reserved",
         source="XS#5725 fixed: vsetvl rd=x0,rs1=x0 reserved"),
    dict(id="xs5739", tier="static", phase="pre", kind="csrr_vl_after_vsetvl",
         source="XS#5739 open: csrr vl stale after vsetvli"),
    dict(id="xs5765", tier="pre", phase="pre", kind="vector_state",
         vector="vl_lt_vlmax", opcodes=["vlm.v"], source="XS#5765 open: vlm.v corrupts v0 tail"),
    dict(id="xs5766", tier="post", phase="post", kind="trap_on",
         prefixes=["vle8ff.v", "vle16ff.v", "vle32ff.v", "vle64ff.v"], causes=[4, 5],
         source="XS#5766 open: FOF load vl not updated on fault"),
    dict(id="xs5767", tier="post", phase="post", kind="trap_on",
         prefixes=["vlseg"], contains="ff", causes=[4, 5],
         source="XS#5767 open: segment FOF double-trap"),
    dict(id="xs5768", tier="pre", phase="pre", kind="csr_state_bits",
         csr=0x002, values=[5, 6, 7], opcodes=["vfmv.v.f", "vfmerge.vfm", "vfmv.f.s", "vfmv.s.f"],
         source="XS#5768 open: vector FP move missing reserved frm check"),
    dict(id="xs5769", tier="post", phase="post", kind="trap_on",
         prefixes=["vsuxseg", "vssseg"], causes=[6, 7],
         source="XS#5769 open: indexed segment store mtval missing offset"),
    dict(id="xs5770", tier="post", phase="post", kind="trap_on",
         prefixes=["vl1re", "vl2re", "vl4re", "vl8re"], causes=[4, 5],
         source="XS#5770 open: whole-register load fault updates dest+vstart"),
    dict(id="xs5772", tier="static", phase="pre", kind="operand_reg_align",
         opcodes=["vmv1r.v", "vmv2r.v", "vmv4r.v", "vmv8r.v"],
         source="XS#5772 open: vmv<nr>r.v unaligned source not illegal"),
    dict(id="xs5773", tier="pre", phase="pre", kind="ea_misaligned",
         opcodes=["flh", "fsh", "flw", "fsw", "fld", "fsd"],
         source="XS#5773 open: flh exception priority"),
    dict(id="xs5779", tier="pre", phase="pre", kind="reg_value_bits",
         opcodes=["hfence.gvma"], operand=1, mask=(1 << 64) - (1 << 14), mode="any",
         source="XS#5779 open: hfence.gvma reserved VMID bits"),
    dict(id="xs5908", tier="pre", phase="pre", kind="ea_cross_boundary",
         opcodes=["sb", "sh", "sw", "sd"], boundary=16, size=4,
         source="XS#5908 open: store crossing 16B breaks UnalignQueue"),
    dict(id="xs5919", tier="static", phase="pre", kind="operand_reg_align",
         opcodes=["vmv1r.v", "vmv2r.v", "vmv4r.v", "vmv8r.v"],
         source="XS#5919 open: reserved vmv<nr>r.v encodings execute"),
    dict(id="xs5921", tier="post", phase="post", kind="trap_on",
         prefixes=["vsuxei", "vsoxei"], causes=[6, 7],
         source="XS#5921 open: indexed store vstart not updated"),
    dict(id="xs5928", tier="pre", phase="pre", kind="vector_state",
         vector="sew_eq", sew=32, opcodes=["vsext.vf4"],
         source="XS#5928 open: vsext.vf4 SEW=e32 wrong source elements"),
    dict(id="xs5930", tier="static", phase="pre", kind="operand_masked",
         opcodes=["vle8ff.v"], source="XS#5930 open: masked vle8ff.v bit7 corruption"),
    dict(id="xs5931", tier="pre", phase="pre", kind="ea_misaligned",
         opcodes=["vlseg2e32ff.v"], vector_element=True,
         source="XS#5931 open: misaligned FOF segment load data corruption"),
    dict(id="xs5932", tier="pre", phase="pre", kind="ea_misaligned",
         prefixes=["vluxseg", "vloxseg"], vector_element=True,
         source="XS#5932 open: indexed segment load data corruption"),
    dict(id="xs5933", tier="pre", phase="pre", kind="reg_value_bits",
         opcodes=["vlsseg3e64.v"], operand=2, mask=FULL64, mode="eq0",
         source="XS#5933 open: zero-stride segment load wrong data"),
    dict(id="xs5934", tier="pre", phase="pre", kind="vector_state",
         vector="policy_tu_mu", opcodes=["vlseg2e16.v"], masked_only=True,
         source="XS#5934 open: masked segment load with tu,mu corrupts elements"),
    dict(id="xs5943", tier="post", phase="post", kind="trap_on",
         opcodes=["vsse16.v", "vsse32.v", "vsse64.v"], causes=[6, 7],
         source="XS#5943 open: strided store fault mtval wrong element"),
    dict(id="xs6001", tier="pre", phase="pre", kind="csr_write_bits",
         csr=[0xF59], mask=1 << 9, source="XS#6001 open: mvip.SEIP priority"),
    dict(id="xs6015", tier="post", phase="post", kind="trap_on",
         prefixes=["vluxei", "vloxei"], causes=[4, 5],
         source="XS#6015 open: indexed load unmapped no fault deadlock"),
    dict(id="xs6022", tier="post", phase="post", kind="trap_on",
         opcodes=["vlse64.v"], causes=[4, 5],
         source="XS#6022 open: strided load illegal address no fault"),
    # ---- CVA6 acknowledged bugs ----
    dict(id="cva6-1466", tier="pre", phase="pre", kind="branch_not_taken_misaligned",
         source="CVA6 #1466 fixed: not-taken branch with misaligned target traps"),
    dict(id="cva6-898", tier="static", phase="pre", kind="opcode_set",
         opcodes=["ecall", "ebreak"], class_suppression=True,
         source="CVA6 #898/#448 confirmed: ecall/ebreak tval written with instruction bits"),
    dict(id="cva6-3174", tier="post", phase="post", kind="trap_on",
         opcodes=["sb", "sh", "sw", "sd", "fsb", "fsh", "fsw", "fsd"], causes=[7],
         source="CVA6 #3174 fixed: PMP store violation reported as load access fault"),
    dict(id="cva6-3457", tier="pre", phase="pre", kind="csr_write_bits",
         csr=[0x302], mask=1 << 9,
         source="CVA6 #3457 open: medeleg[9] not retained"),
    dict(id="cva6-3511", tier="pre", phase="pre", kind="csr_write_value",
         csr=[0x30C, 0x10C], field_mask=0x30, field_value=0x20,
         source="CVA6 #3511 fixed: CBIE reserved 2'b10 accepted"),
    dict(id="cva6-3316", tier="pre", phase="pre", kind="csr_write_bits",
         csr=[0x341, 0x141, 0x241], mask=0x2,
         config_note="targets IALIGN=32 (C-extension disabled) configs only",
         source="CVA6 #3316 fixed: mepc bit[1] not masked without RVC"),
    # ---- BOOM acknowledged bugs ----
    dict(id="boom698", tier="pre", phase="pre", kind="misaligned_overlap_locked",
         opcodes=["lh", "lhu", "lw", "lwu", "ld", "flh", "flw", "fld"],
         source="BOOM #698 confirmed: misaligned load over M-private region leaks data"),
    dict(id="boom503", tier="post", phase="post", kind="fflags_bits",
         opcodes=["fdiv.d", "fdiv.s"], bits=0x10,
         source="BOOM #503 closed: fdiv invalid-operation flag not set"),
    dict(id="boom504", tier="pre", phase="pre", kind="ea_misaligned",
         opcodes=["lr.w", "lr.d"], size_override={"lr.w": 4, "lr.d": 8},
         source="BOOM #504 closed: misaligned LR still sets reservation"),
    dict(id="boom574", tier="pre", phase="pre", kind="jalr_target_misaligned",
         ialign32=True,
         config_note="targets IALIGN=32 configs; bit0 targets are illegal everywhere",
         source="BOOM #574 closed: jalr to misaligned target executes"),
    dict(id="boom771", tier="pre", phase="pre", kind="csr_imm_read_low_priv",
         source="BOOM #771 open: U-mode CSRRSI uimm=0 skips mcounteren check"),
    # ---- Rocket acknowledged bugs ----
    dict(id="rkt3829", tier="pre", phase="pre", kind="pmp_empty_tor_load",
         opcodes=["lb", "lbu", "lh", "lhu", "lw", "lwu", "ld", "flh", "flw", "fld"],
         source="Rocket #3829 open: empty TOR PMP entry causes access faults"),
]

# ---------------------------------------------------------------------------
# Generic evaluators
# ---------------------------------------------------------------------------

COUNTER_CSR = None  # filled below


def _op(ctx) -> str:
    return ctx.opcode.lower().strip()


def _opers(ctx) -> list:
    return [op.strip().lower().rstrip(",") for op in ctx.operands]


def _matches(op: str, sig: dict) -> bool:
    opcodes = sig.get("opcodes")
    prefixes = sig.get("prefixes")
    if opcodes and op in {o.lower() for o in opcodes}:
        pass
    elif prefixes and any(op.startswith(p.lower()) for p in prefixes):
        pass
    elif opcodes or prefixes:
        return False
    contains = sig.get("contains")
    if contains and contains not in op:
        return False
    return True


def _reg_num(token: str):
    token = token.strip().lower().lstrip("v")
    if token.isdigit():
        return int(token)
    return None


def _vector_base_and_element(ctx):
    """(base_reg_index, element_size) for vector memory ops, or (None, None)."""
    sew = ctx.get_vsew() if ctx.s_pre is not None else 0
    elem = max(sew // 8, 1) if sew else 4
    for operand in _opers(ctx):
        m = re.match(r"^(?:-?(?:0x[0-9a-f]+|\d+))?\((\w+)\)$", operand.replace(" ", ""))
        if m:
            reg = ctx.parse_register_operand(m.group(1))
            if reg is not None:
                return reg, elem
    return None, None


def _mem_operand_raw(ctx):
    """(base_reg_index, imm) from the last operand's imm(reg) form, any opcode."""
    if not ctx.operands:
        return None, None
    token = ctx.operands[-1].replace(" ", "")
    m = re.match(r"^(-?(?:0x[0-9a-fA-F]+|\d+))?\(([^)]+)\)$", token)
    if not m:
        return None, None
    imm = int(m.group(1), 0) if m.group(1) else 0
    base = ctx.parse_register_operand(m.group(2))
    return base, imm


def _effective_address_pre(ctx, base_reg, extra: int = 0):
    if ctx.s_pre is None:
        return None
    return (ctx.get_xpr(base_reg) + extra) & FULL64


def _locked_no_perm_region(ctx):
    """First locked zero-permission NAPOT region from pre-state PMP CSRs."""
    if ctx.s_pre is None:
        return None
    cfg0 = ctx.get_csr(0x3A0)
    for i in range(4):
        byte = (cfg0 >> (8 * i)) & 0xFF
        locked = bool(byte & 0x80)
        a_field = (byte >> 3) & 0x3
        perms = byte & 0x7
        if not locked or perms != 0 or a_field != 3:  # NAPOT = A encoding 3
            continue
        addr = ctx.get_csr(0x3B0 + i)
        ones = 0
        while addr & 1:
            ones += 1
            addr >>= 1
        base = (addr << 2) & FULL64
        size = ((1 << ones) if ones else 1) * 4
        return base, base + size
    return None


def _counter_csr(addr) -> bool:
    if addr is None:
        return False
    return (
        addr in {0xC00, 0xB00, 0xC80, 0xB80, 0xC01, 0xC81}
        or 0xC03 <= addr <= 0xC1F or 0xC83 <= addr <= 0xC9F
        or 0xB03 <= addr <= 0xB1F or 0xB83 <= addr <= 0xB9F
    )


def _eval_static(ctx, sig: dict) -> Optional[str]:
    op = _op(ctx)
    kind = sig["kind"]

    if kind == "opcode_set":
        if op in {o.lower() for o in sig.get("opcodes", [])}:
            return "whole-opcode suppression class (no Spike-side differential twin)"
        return None

    if kind == "operand_csr_addr":
        if op not in ALL_CSR_OPCODES:
            return None
        addr = parse_csr_from_operands(_opers(ctx), op)
        if sig.get("csr_sets") == "counter" and _counter_csr(addr):
            return f"counter/timer CSR 0x{addr:x}: implementation-sensitive value"
        return None

    if kind == "operand_reserved":
        if op in {"vsetvl", "vsetvli"}:
            ops = _opers(ctx)
            if len(ops) >= 2 and ops[0] == "x0" and ops[1] == "x0":
                return "vsetvl rd=x0, rs1=x0 reserved encoding (XS#5725)"
        return None

    if kind == "operand_reg_align":
        # vmv<nr>r.v vd, vs  ->  vs (operands[1]) must be aligned to the group
        ops = _opers(ctx)
        if len(ops) < 2:
            return None
        nr = {"vmv1r.v": 1, "vmv2r.v": 2, "vmv4r.v": 4, "vmv8r.v": 8}.get(op)
        if nr is None:
            return None
        num = _reg_num(ops[1])
        if num is not None and num % nr != 0:
            return f"vmv{nr}r.v with unaligned source v{num} (reserved encoding)"
        return None

    if kind == "operand_masked":
        ops = _opers(ctx)
        if ops and ops[-1].replace(" ", "") == "v0.t":
            return "masked vector memory op in known-bug class"
        return None

    if kind == "history_seq":
        # XS#2464: trigger "add rd, rd, rd" preceded by "slli rd, rs, 1"
        if op != "add":
            return None
        ops = _opers(ctx)
        if len(ops) != 3 or ops[0] != ops[1] or ops[1] != ops[2]:
            return None
        rd = ops[0]
        history = [h.strip().lower() for h in getattr(ctx, "history", [])]
        pattern = re.compile(rf"^slli\s+{re.escape(rd)}\s*,\s*\w+\s*,\s*1$")
        if any(pattern.match(h) for h in history[-8:]):
            return "slli+add fusion-trigger sequence in history (XS#2464)"
        return None

    if kind == "csrr_vl_after_vsetvl":
        if op not in ALL_CSR_OPCODES:
            return None
        addr = parse_csr_from_operands(_opers(ctx), op)
        if addr != 0xC20:
            return None
        history = [h.strip().lower().split()[0] for h in getattr(ctx, "history", []) if h.strip()]
        if any(tok.startswith("vsetvl") for tok in history[-8:]):
            return "csrr vl within history window after vsetvli (XS#5739)"
        return None

    return None


def _eval_pre(ctx, sig: dict) -> Optional[str]:
    op = _op(ctx)
    kind = sig["kind"]

    if kind == "ea_misaligned":
        if not _matches(op, sig):
            return None
        region = sig.get("region")
        if sig.get("vector_element"):
            base_reg, elem = _vector_base_and_element(ctx)
            if base_reg is None:
                return None
            ea = _effective_address_pre(ctx, base_reg)
            if ea is None:
                return None
            if ea % elem != 0:
                return f"vector load with misaligned base 0x{ea:x} (elem {elem}B)"
            return None
        size = (sig.get("size_override") or {}).get(op) or SCALAR_MEMORY_SIZES.get(op)
        if not size or size == 1:
            return None
        base_reg, imm = _mem_operand_raw(ctx)
        if base_reg is None:
            return None
        ea = _effective_address_pre(ctx, base_reg, imm or 0)
        if ea is None:
            return None
        if region and not (region[0] <= ea < region[1]):
            return None
        if ea % size != 0:
            return f"misaligned effective address 0x{ea:x} for size {size}"
        return None

    if kind == "ea_cross_boundary":
        if not _matches(op, sig):
            return None
        base_reg, imm = _mem_operand_raw(ctx)
        if base_reg is None:
            return None
        ea = _effective_address_pre(ctx, base_reg, imm or 0)
        if ea is None:
            return None
        boundary = sig.get("boundary", 16)
        size = sig.get("size", 4)
        shift = boundary.bit_length() - 1
        if ((ea ^ (ea + size - 1)) >> shift) != 0:
            return f"store crossing {boundary}B boundary at 0x{ea:x}"
        return None

    if kind == "reg_value_bits":
        if not _matches(op, sig):
            return None
        index = sig.get("operand", 1)
        if len(ctx.operands) <= index:
            return None
        reg = ctx.parse_register_operand(ctx.operands[index])
        if reg is None:
            return None
        if ctx.s_pre is None:
            return None
        value = ctx.get_xpr(reg) & FULL64
        mask = sig.get("mask", 0)
        if sig.get("mode", "any") == "eq0":
            if value == 0:
                return f"register operand {index + 1} is zero (known-bug trigger)"
        elif value & mask:
            return f"register operand {index + 1} has reserved bits set (0x{value:x})"
        return None

    if kind == "csr_write_bits":
        if op not in {"csrrw", "csrrs", "csrrc", "csrrwi", "csrrsi", "csrrci"}:
            return None
        addr = parse_csr_from_operands(_opers(ctx), op)
        if addr not in set(sig.get("csr", [])):
            return None
        if op in {"csrrwi", "csrrsi", "csrrci"}:
            requested = parse_int_token(_opers(ctx)[2]) if len(_opers(ctx)) > 2 else None
        else:
            requested = None
            if len(ctx.operands) > 2:
                reg = ctx.parse_register_operand(ctx.operands[2])
                if reg is not None and ctx.s_pre is not None:
                    requested = ctx.get_xpr(reg)
        if requested is None:
            return None
        if requested & sig.get("mask", 0):
            return f"CSR 0x{addr:x} write requests restricted bits (0x{requested & FULL64:x})"
        return None

    if kind == "csr_state_bits":
        if not _matches(op, sig):
            return None
        if ctx.s_pre is None:
            return None
        value = ctx.get_csr(sig["csr"])
        if value in set(sig.get("values", [])):
            return f"CSR 0x{sig['csr']:x} in reserved state {value}"
        return None

    if kind == "vector_state":
        if not _matches(op, sig):
            return None
        if ctx.s_pre is None:
            return None
        if sig.get("masked_only") and _opers(ctx)[-1:] != ["v0.t"]:
            return None
        which = sig.get("vector")
        if which == "vl_lt_vlmax" and ctx.get_vl() < ctx.get_vlmax():
            return "vl < vlmax leaves tail elements (known-bug context)"
        if which == "sew_eq" and ctx.get_vsew() == sig.get("sew"):
            return f"vsew={sig.get('sew')} with {op} (known-bug context)"
        if which == "policy_tu_mu":
            if ctx.get_vta() == 0 and ctx.get_vma() == 0:
                return "tu,mu vector policy with masked op (known-bug context)"
        return None

    if kind == "csr_write_value":
        if op not in {"csrrw", "csrrs", "csrrc", "csrrwi", "csrrsi", "csrrci"}:
            return None
        addr = parse_csr_from_operands(_opers(ctx), op)
        if addr not in set(sig.get("csr", [])):
            return None
        if op in {"csrrwi", "csrrsi", "csrrci"}:
            requested = parse_int_token(_opers(ctx)[2]) if len(_opers(ctx)) > 2 else None
        else:
            requested = None
            if len(ctx.operands) > 2:
                reg = ctx.parse_register_operand(ctx.operands[2])
                if reg is not None and ctx.s_pre is not None:
                    requested = ctx.get_xpr(reg)
        if requested is None:
            return None
        field = (requested & sig.get("field_mask", 0)) & FULL64
        if field == (sig.get("field_value", 0) & FULL64):
            return (f"CSR 0x{addr:x} write requests reserved field value "
                    f"0x{field:x}")
        return None

    if kind == "branch_not_taken_misaligned":
        if op not in {"beq", "bne", "blt", "bge", "bltu", "bgeu"}:
            return None
        if ctx.s_pre is None:
            return None
        ops = _opers(ctx)
        if len(ops) < 3:
            return None
        rs1 = ctx.parse_register_operand(ops[0])
        rs2 = ctx.parse_register_operand(ops[1])
        offset = None
        for token in ctx.operands[2:]:
            value = parse_int_token(token.strip().rstrip(","))
            if value is not None:
                offset = value
                break
        if rs1 is None or rs2 is None or offset is None:
            return None
        a = ctx.get_xpr(rs1)
        b = ctx.get_xpr(rs2)
        taken = {"beq": a == b, "bne": a != b, "blt": a < b, "bge": a >= b,
                 "bltu": (a & FULL64) < (b & FULL64),
                 "bgeu": (a & FULL64) >= (b & FULL64)}[op]
        if taken:
            return None
        target = (ctx.get_pc() + offset) & FULL64
        if target % 2 != 0:
            return (f"not-taken branch with misaligned target 0x{target:x} "
                    f"(must not trap)")
        return None

    if kind == "jalr_target_misaligned":
        if op not in {"jalr"}:
            return None
        if ctx.s_pre is None:
            return None
        base_reg, imm = _mem_operand_raw(ctx)
        if base_reg is None:
            return None
        target = _effective_address_pre(ctx, base_reg, imm or 0)
        if target is None:
            return None
        misaligned = target % 2 != 0 or (
            sig.get("ialign32") and target % 4 != 0
        )
        if misaligned:
            return f"jalr to misaligned target 0x{target:x} (must trap)"
        return None

    if kind == "misaligned_overlap_locked":
        if not _matches(op, sig):
            return None
        size = SCALAR_MEMORY_SIZES.get(op)
        if not size or size == 1:
            return None
        base_reg, imm = _mem_operand_raw(ctx)
        if base_reg is None:
            return None
        ea = _effective_address_pre(ctx, base_reg, imm or 0)
        if ea is None:
            return None
        deny = _locked_no_perm_region(ctx)
        if deny is None:
            return None
        lo, hi = deny
        if ea % size != 0 and not (ea + size <= lo or ea >= hi):
            return (f"misaligned load 0x{ea:x} overlapping locked region "
                    f"0x{lo:x} (meltdown-class context)")
        return None

    if kind == "csr_imm_read_low_priv":
        if op != "csrrsi":
            return None
        ops = _opers(ctx)
        if len(ops) < 3 or parse_int_token(ops[2]) != 0:
            return None
        addr = parse_csr_from_operands(ops, op)
        if not _counter_csr(addr):
            return None
        if ctx.s_pre is None:
            return None
        if ctx.get_privilege() < 3:
            return (f"U/S-mode csrrsi uimm=0 on counter CSR 0x{addr:x} "
                    f"skips enable check on known-bug core")
        return None

    if kind == "pmp_empty_tor_load":
        if not _matches(op, sig):
            return None
        if ctx.s_pre is None:
            return None
        cfg0 = ctx.get_csr(0x3A0)
        addrs = [ctx.get_csr(0x3B0 + i) for i in range(4)]
        for i in range(4):
            a_field = (cfg0 >> (8 * i + 3)) & 0x3
            if a_field != 1:  # TOR
                continue
            prev = addrs[i - 1] if i > 0 else 0
            if addrs[i] == prev:
                return (f"load while empty TOR PMP entry {i} present "
                        f"(known-bug config)")
        return None

    if kind == "sc_no_reservation":
        if op in {"sc.w", "sc.d"} and ctx.s_pre is not None and not ctx.has_reservation():
            return "SC with no live reservation (must fail; reporting differs)"
        return None

    return None


def _eval_post(ctx, sig: dict) -> Optional[str]:
    op = _op(ctx)
    kind = sig["kind"]

    if kind == "trap_on":
        if not _matches(op, sig):
            return None
        if ctx.s_post is None or not ctx.was_trapped():
            return None
        cause = ctx.get_trap_cause()
        if cause in set(sig.get("causes", [])):
            return f"{op} trapped with cause {cause} (known-bug trigger class)"
        return None

    if kind == "fflags_bits":
        if op not in set(sig.get("opcodes", [])):
            return None
        if ctx.s_post is None or ctx.s_pre is None:
            return None
        bits = sig.get("bits", 0)
        before = ctx.get_csr(0x001) & bits
        after = ctx.get_post_csr(0x001) & bits
        if after and not before:
            return f"{op} raised fflags 0x{bits:x} (flag must match reference)"
        return None

    if kind == "csr_readback_dropped":
        if op not in {"csrrw", "csrrs", "csrrc", "csrrwi", "csrrsi", "csrrci"}:
            return None
        return _eval_warl_dropped(ctx)

    if kind == "fpr_nan_result":
        if op not in set(sig.get("opcodes", [])):
            return None
        if ctx.s_post is None:
            return None
        dest = ctx.get_destination_register()
        if dest is None:
            return None
        value = ctx.s_post.get_fpr(dest)
        if isinstance(value, bytes):
            value = int.from_bytes(value, "little")
        if value is None:
            return None
        if (value & 0x7FF0000000000000) == 0x7FF0000000000000 and (value & 0x000FFFFFFFFFFFFF) != 0:
            return f"{op} produced NaN result (0x{value & FULL64:016x})"
        return None

    return None


_MSTATUS_WRITABLE = (
    (1 << 1) | (1 << 3) | (1 << 5) | (1 << 6) | (1 << 7) | (1 << 8)
    | (1 << 11) | (1 << 12) | (1 << 13) | (1 << 14)
    | (1 << 17) | (1 << 18) | (1 << 19) | (1 << 20) | (1 << 21) | (1 << 22)
)
NORMALIZATION_SENSITIVE_MASKS = {
    0x300: ~_MSTATUS_WRITABLE & FULL64,
    0x305: 0x3, 0x105: 0x3, 0x205: 0x3,
}


def _eval_warl_dropped(ctx) -> Optional[str]:
    op = _op(ctx)
    ops = _opers(ctx)
    addr = parse_csr_from_operands(ops, op)
    mask = NORMALIZATION_SENSITIVE_MASKS.get(addr)
    if mask is None:
        return None
    if op in {"csrrwi", "csrrsi", "csrrci"}:
        requested = parse_int_token(ops[2]) if len(ops) > 2 else None
    else:
        requested = None
        if len(ctx.operands) > 2:
            reg = ctx.parse_register_operand(ctx.operands[2])
            if reg is not None:
                requested = ctx.get_xpr(reg)
    if requested is None or ctx.s_post is None:
        return None
    requested &= FULL64
    readback = ctx.get_post_csr(addr) & FULL64
    dropped = requested & mask & ~readback
    if dropped:
        return (f"CSR 0x{addr:x} write normalized: dropped requested bits "
                f"0x{dropped:x} of 0x{requested:x}")
    return None


# ---------------------------------------------------------------------------
# Registry construction
# ---------------------------------------------------------------------------

class SignatureFilter(PrecisionFilter):
    def __init__(self, sig: dict):
        tier = sig["tier"]
        phase = FilterPhase.PRE_EXECUTION if sig.get("phase", "pre") == "pre" else FilterPhase.POST_EXECUTION
        opcodes = list(sig.get("opcodes", [])) or None
        super().__init__(
            name=f"SIG-{sig['id']}",
            phase=phase,
            opcodes=opcodes,
            description=f"{sig.get('source', '')} [min tier: {tier}]",
        )
        self.sig = sig

    def check(self, ctx) -> FilterResult:
        sig = self.sig
        reason = None
        if sig["tier"] == "static" or sig.get("phase", "pre") == "pre":
            reason = _eval_static(ctx, sig)
            if reason is None:
                reason = _eval_pre(ctx, sig)
        else:
            reason = _eval_post(ctx, sig)
        if reason:
            return FilterResult.reject(f"[{sig['id']}] {reason}")
        return FilterResult.accept()


def register_signatures(registry, max_tier: str) -> None:
    """Register every signature whose minimum tier fits the policy budget."""
    for sig in SIGNATURES:
        if TIER_RANK[sig["tier"]] <= TIER_RANK[max_tier]:
            registry.register(SignatureFilter(sig))


def signature_index() -> dict:
    return {sig["id"]: sig for sig in SIGNATURES}


__all__ = [
    "SIGNATURES",
    "register_signatures",
    "signature_index",
    "SignatureFilter",
]
