#!/usr/bin/env python3
# Copyright (c) 2024-2025 Institute of Information Engineering, Chinese Academy of Sciences
#
# DiveFuzz is licensed under Mulan PSL v2.
# See http://license.coscl.org.cn/MulanPSL2 for more details.

"""Matrix rows: one filter per unified-db implementation-defined parameter.

Rows come from riscv-unified-db spec/std/isa/param (see
scripts/param_curation.{json,md}); every row id is the parameter name.
Arms (information budgets) reuse the signature tiers:

  arm "text"    = tier text   (opcode + operand text)
  arm "static"  = tier static (+ generation history)
  arm "operval" = static + current values of the operand registers only
                  (write value = source register, effective address = base
                  register + immediate, vsetvli AVL = rs1)
  arm "dynamic" = tier post   (+ full runtime state before/after execution)

Per-arm evaluation mirrors experiment_signatures.SignatureFilter:
precise predicate when the arm's budget covers the row's tier, otherwise
class-level rejection over the row's correlated opcode class.

Kinds implemented here (existing kinds are delegated to
experiment_signatures evaluators):

  csr_addr_read         CSR read (rs1=x0/zimm form) touches address set  [text]
  csr_addr_write_any    CSR write touches address set                    [text]
  csr_addr_in           any CSR op touches address set                   [text]
  csr_write_field_eq    CSR write requests field == value                [pre]
  csr_write_field_notin CSR write requests field not in values          [pre]
  csr_bits_changed      CSR bits differ pre/post on opcode class        [post]
  reserved_encoding     operand pattern is a reserved encoding          [text]
  ea_misaligned_cross_page misaligned EA crosses a 4KiB page            [pre]
  vsetvli_sew_lt        vsetvli requests SEW below bound                [pre]
"""

from __future__ import annotations

from .experiment_signatures import (
    FULL64,
    _eval_post,
    _eval_pre,
    _eval_static,
    _matches,
    _mem_operand_raw,
    _effective_address_pre,
    _op,
    _opers,
)
from .experiment_filter_utils import ALL_CSR_OPCODES, parse_csr_from_operands, parse_int_token

SCALAR_LOADS = ["lb", "lbu", "lh", "lhu", "lw", "lwu", "ld"]
SCALAR_STORES = ["sb", "sh", "sw", "sd"]
FP_LOADS = ["flh", "flw", "fld"]
FP_STORES = ["fsh", "fsw", "fsd"]
AMO_OPS = ["amoswap.w", "amoadd.w", "amoxor.w", "amoand.w", "amoor.w",
           "amomin.w", "amomax.w", "amominu.w", "amomaxu.w",
           "amoswap.d", "amoadd.d", "amoxor.d", "amoand.d", "amoor.d",
           "amomin.d", "amomax.d", "amominu.d", "amomaxu.d"]
JUMP_OPS = ["jalr", "c.jr", "c.jalr", "jal", "c.jal"]
BRANCH_OPS = ["beq", "bne", "blt", "bge", "bltu", "bgeu"]
VEC_LOADS = ["vle8.v", "vle16.v", "vle32.v", "vle64.v",
             "vle8ff.v", "vle16ff.v", "vle32ff.v", "vle64ff.v",
             "vlseg2e8.v", "vlseg2e16.v", "vlseg2e32.v", "vlseg2e64.v",
             "vlseg2e32ff.v", "vlseg3e64ff.v",
             "vluxei8.v", "vluxei16.v", "vluxei32.v", "vluxei64.v",
             "vloxei8.v", "vloxei16.v", "vloxei32.v", "vloxei64.v",
             "vluxseg2e32.v", "vloxseg2e32.v",
             "vlse8.v", "vlse16.v", "vlse32.v", "vlse64.v", "vlsseg3e64.v",
             "vl1re8.v", "vl2re8.v", "vl4re8.v", "vl8re8.v"]
VEC_STORES = ["vse8.v", "vse16.v", "vse32.v", "vse64.v",
              "vsseg2e32.v", "vssseg2e32.v", "vssseg3e64.v",
              "vsuxei8.v", "vsuxei32.v", "vsuxseg2e32.v", "vsoxei32.v",
              "vsuxseg3e16.v", "vsoxseg2e16.v",
              "vsse16.v", "vsse32.v", "vsse64.v",
              "vs1r.v", "vs2r.v", "vs4r.v", "vs8r.v"]
LOAD_CAUSE_CLASS = SCALAR_LOADS + FP_LOADS + ["lr.w", "lr.d"] + VEC_LOADS
STORE_CAUSE_CLASS = (SCALAR_STORES + FP_STORES + AMO_OPS
                     + ["sc.w", "sc.d"] + VEC_STORES)
FETCH_CAUSE_CLASS = JUMP_OPS + BRANCH_OPS
ILLEGAL_CAUSE_CLASS = ["vmv1r.v", "vmv2r.v", "vmv4r.v", "vmv8r.v",
                       "vsetvl", "vsetvli"]
FP_COMPUTE_PREFIXES = ["fadd.", "fsub.", "fmul.", "fdiv.", "fsqrt.",
                       "fmadd.", "fmsub.", "fnmadd.", "fnmsub.",
                       "fcvt.", "fmv.", "fsgnj.", "fmin.", "fmax.",
                       "feq.", "flt.", "fle.", "fclass."]
HPM_READS = list(range(0xC03, 0xC20)) + list(range(0xC83, 0xCA0))

# CSR addresses reachable from the generator pool that this reference build
# (rv64imafdcv_zicsr_zifencei_zba_zbb_zbc_zbs_zfh — no H/Smte/Sstc/legacy
# deleg CSRs) does not implement: accessing them is implementation choice.
UNIMPLEMENTED_IN_REF = {
    0x600, 0x602, 0x603, 0x604, 0x606, 0x607, 0x60A, 0x680,   # h* config
    0x643, 0x644, 0x645, 0x64A, 0x64B, 0xE12,                 # h* trap
    0x200, 0x204, 0x205, 0x240, 0x241, 0x242, 0x243, 0x244,   # vs* (vsatp 与 satp 同址 0x180，参考实现已实现)
    0x102, 0x103,        # sedeleg/sideleg（已废弃）
    0x34A, 0x34B,        # mtinst/mtval2 (Smte)
    0xDBD, 0xDBF,        # stimecmp/vstimecmp (Sstc)
}


def _row(param, tier, kind, phase="pre", note="", **kw):
    return dict(id=param, tier=tier, kind=kind, phase=phase, note=note, **kw)


MATRIX_ROWS = [
    # ---- id_config：身份/配置寄存器读数 ----
    _row("ARCH_ID_VALUE", "text", "csr_addr_read", addrs=[0xF12],
         note="marchid 读数属实现自定义"),
    _row("MARCHID_IMPLEMENTED", "text", "csr_addr_read", addrs=[0xF12],
         note="marchid 是否实现影响读行为"),
    _row("IMP_ID_VALUE", "text", "csr_addr_read", addrs=[0xF13],
         note="mimpid 读数属实现自定义"),
    _row("MIMPID_IMPLEMENTED", "text", "csr_addr_read", addrs=[0xF13],
         note="mimpid 是否实现影响读行为"),
    _row("VENDOR_ID_BANK", "text", "csr_addr_read", addrs=[0xF11],
         note="mvendorid 读数（JEDEC 银号）属实现自定义"),
    _row("VENDOR_ID_OFFSET", "text", "csr_addr_read", addrs=[0xF11],
         note="mvendorid 读数（JEDEC 偏移）属实现自定义"),
    _row("CONFIG_PTR_ADDRESS", "text", "csr_addr_read", addrs=[0xF15],
         note="mconfigptr 读数属实现自定义"),
    _row("MISA_CSR_IMPLEMENTED", "text", "csr_addr_read", addrs=[0x301],
         note="misa 是否实现影响读行为"),
    # ---- misaligned ----
    _row("MISALIGNED_LDST", "pre", "ea_misaligned",
         opcodes=SCALAR_LOADS + FP_LOADS + SCALAR_STORES + FP_STORES,
         note="非对齐标量访存支持与拆分属实现自定义"),
    _row("MISALIGNED_AMO", "pre", "ea_misaligned", opcodes=AMO_OPS,
         note="非对齐 AMO 是否支持属实现自定义"),
    _row("MISALIGNED_SPLIT_STRATEGY", "pre", "ea_misaligned_cross_page",
         opcodes=SCALAR_LOADS + SCALAR_STORES,
         note="拆分执行顺序仅在跨越页边界时可观察"),
    _row("MISALIGNED_LDST_EXCEPTION_PRIORITY", "pre", "ea_misaligned_cross_page",
         opcodes=SCALAR_LOADS + SCALAR_STORES + FP_LOADS + FP_STORES,
         note="非对齐异常与访问/缺页异常的优先级仅在跨页时可观察"),
    _row("LRSC_MISALIGNED_BEHAVIOR", "pre", "ea_misaligned",
         opcodes=["lr.w", "lr.d"], size_override={"lr.w": 4, "lr.d": 8},
         class_opcodes=["lr.w", "lr.d", "sc.w", "sc.d"],
         note="非对齐 LR/SC 行为属实现自定义"),
    # ---- tval_report（mtval/stval 内容）----
    _row("REPORT_VA_IN_MTVAL_ON_BREAKPOINT", "post", "trap_on", phase="post",
         causes=[3], class_opcodes=["ebreak"], note=""),
    _row("REPORT_VA_IN_STVAL_ON_BREAKPOINT", "post", "trap_on", phase="post",
         causes=[3], class_opcodes=["ebreak"], note="stval 与 mtval 同源"),
    _row("REPORT_VA_IN_MTVAL_ON_INSTRUCTION_MISALIGNED", "post", "trap_on", phase="post",
         causes=[0], class_family="fetch", note=""),
    _row("REPORT_VA_IN_STVAL_ON_INSTRUCTION_MISALIGNED", "post", "trap_on", phase="post",
         causes=[0], class_family="fetch", note=""),
    _row("REPORT_VA_IN_MTVAL_ON_INSTRUCTION_ACCESS_FAULT", "post", "trap_on", phase="post",
         causes=[1], class_family="fetch", note=""),
    _row("REPORT_VA_IN_STVAL_ON_INSTRUCTION_ACCESS_FAULT", "post", "trap_on", phase="post",
         causes=[1], class_family="fetch", note=""),
    _row("REPORT_VA_IN_MTVAL_ON_INSTRUCTION_PAGE_FAULT", "post", "trap_on", phase="post",
         causes=[12], class_family="fetch", note=""),
    _row("REPORT_VA_IN_STVAL_ON_INSTRUCTION_PAGE_FAULT", "post", "trap_on", phase="post",
         causes=[12], class_family="fetch", note=""),
    _row("REPORT_VA_IN_MTVAL_ON_LOAD_MISALIGNED", "post", "trap_on", phase="post",
         causes=[4], class_family="load", note=""),
    _row("REPORT_VA_IN_STVAL_ON_LOAD_MISALIGNED", "post", "trap_on", phase="post",
         causes=[4], class_family="load", note=""),
    _row("REPORT_VA_IN_MTVAL_ON_LOAD_ACCESS_FAULT", "post", "trap_on", phase="post",
         causes=[5], class_family="load", note=""),
    _row("REPORT_VA_IN_STVAL_ON_LOAD_ACCESS_FAULT", "post", "trap_on", phase="post",
         causes=[5], class_family="load", note=""),
    _row("REPORT_VA_IN_MTVAL_ON_LOAD_PAGE_FAULT", "post", "trap_on", phase="post",
         causes=[13], class_family="load", note=""),
    _row("REPORT_VA_IN_STVAL_ON_LOAD_PAGE_FAULT", "post", "trap_on", phase="post",
         causes=[13], class_family="load", note=""),
    _row("REPORT_VA_IN_MTVAL_ON_STORE_AMO_MISALIGNED", "post", "trap_on", phase="post",
         causes=[6], class_family="store", note=""),
    _row("REPORT_VA_IN_STVAL_ON_STORE_AMO_MISALIGNED", "post", "trap_on", phase="post",
         causes=[6], class_family="store", note=""),
    _row("REPORT_VA_IN_MTVAL_ON_STORE_AMO_ACCESS_FAULT", "post", "trap_on", phase="post",
         causes=[7], class_family="store", note=""),
    _row("REPORT_VA_IN_STVAL_ON_STORE_AMO_ACCESS_FAULT", "post", "trap_on", phase="post",
         causes=[7], class_family="store", note=""),
    _row("REPORT_VA_IN_MTVAL_ON_STORE_AMO_PAGE_FAULT", "post", "trap_on", phase="post",
         causes=[15], class_family="store", note=""),
    _row("TINST_VALUE_ON_BREAKPOINT", "post", "trap_on", phase="post",
         causes=[3], class_opcodes=["ebreak"], note="mtinst 取值属实现自定义"),
    _row("TINST_VALUE_ON_MCALL", "post", "trap_on", phase="post",
         causes=[11], class_opcodes=["ecall"], note="mtinst 取值属实现自定义"),
    _row("TINST_VALUE_ON_SCALL", "post", "trap_on", phase="post",
         causes=[9], class_opcodes=["ecall"], note="mtinst 取值属实现自定义"),
    _row("TINST_VALUE_ON_UCALL", "post", "trap_on", phase="post",
         causes=[8], class_opcodes=["ecall"], note="mtinst 取值属实现自定义"),
    _row("TRAP_ON_ECALL_FROM_M", "text", "opcode_set",
         opcodes=["ecall"], class_suppression=True,
         note="ecall 是否实现属实现选择（编码器可产生）"),
    _row("TRAP_ON_ECALL_FROM_S", "text", "opcode_set",
         opcodes=["ecall"], class_suppression=True,
         note="同上（S 模式形态）"),
    _row("TRAP_ON_ECALL_FROM_U", "text", "opcode_set",
         opcodes=["ecall"], class_suppression=True,
         note="同上（U 模式形态）"),
    _row("TRAP_ON_EBREAK", "text", "opcode_set",
         opcodes=["ebreak"], class_suppression=True,
         note="ebreak 是否陷入属实现选择（编码器可产生）"),
    _row("TRAP_ON_SFENCE_VMA_WHEN_SATP_MODE_IS_READ_ONLY", "post", "trap_on", phase="post",
         prefixes=["sfence.vma"], causes=[2], class_opcodes=["sfence.vma"],
         note="satp 只读配置下 sfence.vma 是否陷入属实现选择"),
    _row("REPORT_VA_IN_STVAL_ON_STORE_AMO_PAGE_FAULT", "post", "trap_on", phase="post",
         causes=[15], class_family="store", note=""),
    _row("REPORT_ENCODING_IN_MTVAL_ON_ILLEGAL_INSTRUCTION", "post", "trap_on", phase="post",
         causes=[2], class_family="illegal", class_opcodes=sorted(ALL_CSR_OPCODES),
         note="非法指令是否回报编码属实现自定义"),
    _row("REPORT_ENCODING_IN_STVAL_ON_ILLEGAL_INSTRUCTION", "post", "trap_on", phase="post",
         causes=[2], class_family="illegal", class_opcodes=sorted(ALL_CSR_OPCODES),
         note="同上（stval）"),
    # ---- tinst_report（非 ecall、非客户机）----
    _row("TINST_VALUE_ON_INSTRUCTION_ADDRESS_MISALIGNED", "post", "trap_on", phase="post",
         causes=[0], class_family="fetch", note="mtinst 取值属实现自定义"),
    _row("TINST_VALUE_ON_LOAD_ACCESS_FAULT", "post", "trap_on", phase="post",
         causes=[5], class_family="load", note=""),
    _row("TINST_VALUE_ON_LOAD_ADDRESS_MISALIGNED", "post", "trap_on", phase="post",
         causes=[4], class_family="load", note=""),
    _row("TINST_VALUE_ON_LOAD_PAGE_FAULT", "post", "trap_on", phase="post",
         causes=[13], class_family="load", note=""),
    _row("TINST_VALUE_ON_STORE_AMO_ACCESS_FAULT", "post", "trap_on", phase="post",
         causes=[7], class_family="store", note=""),
    _row("TINST_VALUE_ON_STORE_AMO_ADDRESS_MISALIGNED", "post", "trap_on", phase="post",
         causes=[6], class_family="store", note=""),
    _row("TINST_VALUE_ON_STORE_AMO_PAGE_FAULT", "post", "trap_on", phase="post",
         causes=[15], class_family="store", note=""),
    # ---- trap_on 家族 ----
    _row("TRAP_ON_RESERVED_INSTRUCTION", "text", "reserved_encoding",
         class_opcodes=["vmv1r.v", "vmv2r.v", "vmv4r.v", "vmv8r.v", "vsetvl", "vsetvli"],
         note="保留编码译码行为 UNSPECIFIED（可编码的保留形态）"),
    _row("TRAP_ON_UNIMPLEMENTED_INSTRUCTION", "text", "reserved_encoding",
         class_opcodes=["vmv1r.v", "vmv2r.v", "vmv4r.v", "vmv8r.v", "vsetvl", "vsetvli"],
         note="未实现指令是否陷入属实现选择（与上一行共享可编码形态）"),
    _row("TRAP_ON_UNIMPLEMENTED_CSR", "text", "csr_addr_in",
         addrs=sorted(UNIMPLEMENTED_IN_REF), class_opcodes=sorted(ALL_CSR_OPCODES),
         note="参考实现未实现的 CSR：访问是否陷入属实现选择"),
    _row("TRAP_ON_ILLEGAL_WLRL", "pre", "csr_write_field_notin",
         csr=[0x180], field_mask=0xF000000000000000, values=[0, 8 << 60],
         class_opcodes=sorted(ALL_CSR_OPCODES),
         note="satp 写保留模式值是否陷入属实现选择"),
    # ---- warl_write ----
    _row("MSTATUS_FS_LEGAL_VALUES", "pre", "csr_write_bits",
         csr=[0x100], mask=0x6000, class_opcodes=sorted(ALL_CSR_OPCODES),
         note="sstatus.FS 写入值可能被 WARL 规范化"),
    _row("MSTATUS_VS_LEGAL_VALUES", "pre", "csr_write_bits",
         csr=[0x100], mask=0x600, class_opcodes=sorted(ALL_CSR_OPCODES),
         note="sstatus.VS 写入值可能被 WARL 规范化", encoder=True),
    _row("SATP_MODE_BARE", "pre", "csr_write_bits",
         csr=[0x180], mask=0xF000000000000000, class_opcodes=sorted(ALL_CSR_OPCODES),
         note="satp 模式位支持集属实现自定义"),
    _row("ASID_WIDTH", "pre", "csr_write_bits",
         csr=[0x180], mask=0x00FFFF0000000000, class_opcodes=sorted(ALL_CSR_OPCODES),
         note="satp.ASID 位宽属实现自定义，非零位可能被丢弃"),
    _row("MTVAL_WIDTH", "post", "trap_on", phase="post",
         causes=[4, 6, 0], class_family="mem",
         note="陷入后 mtval 高位是否实现影响读回值"),
    _row("STVAL_WIDTH", "post", "trap_on", phase="post",
         causes=[4, 6, 0], class_family="mem",
         note="同上（stval）"),
    # misa 可变位（8 行）
    *[_row(f"MUTABLE_MISA_{L}", "pre", "csr_write_bits", csr=[0x301],
           mask=1 << (ord(L) - 65), class_opcodes=sorted(ALL_CSR_OPCODES),
           note=f"misa.{L} 是否可变属实现自定义")
      for L in "ACDFMSUV"],
    # ---- pmp ----
    _row("PMP_NA4_SUPPORTED", "pre", "csr_write_field_eq",
         csr=[0x3A0, 0x3A1, 0x3A2], field_mask=0x18, field_value=0x10,
         class_opcodes=sorted(ALL_CSR_OPCODES), note="NA4 模式支持属实现自定义"),
    _row("PMP_NAPOT_SUPPORTED", "pre", "csr_write_field_eq",
         csr=[0x3A0, 0x3A1, 0x3A2], field_mask=0x18, field_value=0x18,
         class_opcodes=sorted(ALL_CSR_OPCODES), note="NAPOT 模式支持属实现自定义"),
    _row("PMP_TOR_SUPPORTED", "pre", "csr_write_field_eq",
         csr=[0x3A0, 0x3A1, 0x3A2], field_mask=0x18, field_value=0x08,
         class_opcodes=sorted(ALL_CSR_OPCODES), note="TOR 模式支持属实现自定义"),
    _row("NUM_PMP_ENTRIES", "pre", "csr_write_bits",
         csr=[0x3B0, 0x3B1, 0x3B2], mask=FULL64, class_opcodes=sorted(ALL_CSR_OPCODES),
         note="pmpaddr 写读回受表项数约束"),
    _row("NUM_USABLE_PMP_ENTRIES", "pre", "csr_write_bits",
         csr=[0x3B0, 0x3B1, 0x3B2], mask=FULL64, class_opcodes=sorted(ALL_CSR_OPCODES),
         note="同上（可用表项数）"),
    _row("PMP_GRANULARITY", "pre", "csr_write_bits",
         csr=[0x3B0, 0x3B1, 0x3B2], mask=FULL64, class_opcodes=sorted(ALL_CSR_OPCODES),
         note="pmpaddr 低位受粒度约束"),
    # ---- counter ----
    _row("HPM_COUNTER_EN", "text", "csr_addr_read",
         addrs=HPM_READS, class_opcodes=sorted(ALL_CSR_OPCODES),
         note="hpmcounter 是否实现属实现自定义"),
    _row("HPM_EVENTS", "text", "csr_addr_read",
         addrs=HPM_READS, class_opcodes=sorted(ALL_CSR_OPCODES),
         note="事件计数内容属实现自定义"),
    _row("COUNTINHIBIT_EN", "text", "csr_addr_write_any",
         addrs=[0x320], class_opcodes=sorted(ALL_CSR_OPCODES),
         note="mcountinhibit 位支持属实现自定义"),
    _row("MCOUNTINHIBIT_IMPLEMENTED", "text", "csr_addr_write_any",
         addrs=[0x320], class_opcodes=sorted(ALL_CSR_OPCODES),
         note="mcountinhibit 是否实现属实现自定义"),
    _row("TIME_CSR_IMPLEMENTED", "text", "csr_addr_read",
         addrs=[0xC01, 0xB01], class_opcodes=sorted(ALL_CSR_OPCODES),
         note="time 是否实现属实现自定义"),
    # ---- mtvec/stvec/mip：实验正例手写指令即可构造（实测读回可见 WARL）----
    _row("MTVEC_MODES", "pre", "csr_write_field_notin",
         csr=[0x305], field_mask=0x3, values=[0, 1],
         class_opcodes=sorted(ALL_CSR_OPCODES), note="mtvec 保留模式 WARL 属实现自定义"),
    _row("MTVEC_ACCESS", "text", "csr_addr_write_any",
         addrs=[0x305], class_opcodes=sorted(ALL_CSR_OPCODES),
         note="mtvec 写行为属实现选择"),
    _row("MTVEC_BASE_ALIGNMENT_DIRECT", "pre", "csr_write_bits",
         csr=[0x305], mask=0x2, class_opcodes=sorted(ALL_CSR_OPCODES),
         note="direct 模式基址对齐 WARL 属实现自定义"),
    _row("MTVEC_BASE_ALIGNMENT_VECTORED", "pre", "csr_write_bits",
         csr=[0x305], mask=0x3, class_opcodes=sorted(ALL_CSR_OPCODES),
         note="vectored 模式基址对齐 WARL 属实现自定义"),
    _row("MTVEC_ILLEGAL_WRITE_BEHAVIOR", "pre", "csr_write_field_notin",
         csr=[0x305], field_mask=0x3, values=[0, 1],
         class_opcodes=sorted(ALL_CSR_OPCODES), note="mtvec 非法写入保留/变值属实现自定义"),
    _row("STVEC_MODES", "pre", "csr_write_field_notin",
         csr=[0x105], field_mask=0x3, values=[0, 1],
         class_opcodes=sorted(ALL_CSR_OPCODES), note="stvec 保留模式 WARL 属实现自定义"),
    _row("STVEC_BASE_ALIGNMENT_VECTORED", "pre", "csr_write_bits",
         csr=[0x105], mask=0x3, class_opcodes=sorted(ALL_CSR_OPCODES),
         note="stvec 基址对齐 WARL 属实现自定义"),
    _row("MEI_INTR_IMPL", "text", "csr_addr_read",
         addrs=[0x344], class_opcodes=sorted(ALL_CSR_OPCODES),
         note="mip.MEIP 读数属平台实现"),
    _row("MSI_INTR_IMPL", "text", "csr_addr_read",
         addrs=[0x344], class_opcodes=sorted(ALL_CSR_OPCODES),
         note="mip.MSIP 读数属平台实现"),
    _row("MTI_INTR_IMPL", "text", "csr_addr_read",
         addrs=[0x344], class_opcodes=sorted(ALL_CSR_OPCODES),
         note="mip.MTIP 读数属平台实现"),
    # ---- H 扩展可构造行（实测：恢复 misa.H 位后引擎 H CSR/指令可用）----
    _row("GSTAGE_MODE_BARE", "pre", "csr_write_field_notin",
         csr=[0x680], field_mask=0xF000000000000000, values=[0, 8 << 60],
         class_opcodes=sorted(ALL_CSR_OPCODES),
         note="hgatp 保留模式值是否 WARL 规范化属实现自定义"),
    _row("NUM_EXTERNAL_GUEST_INTERRUPTS", "text", "csr_addr_read",
         addrs=[0xE12], class_opcodes=sorted(ALL_CSR_OPCODES),
         note="hgeip 读数（客户机外部中断数）属平台实现"),
    _row("VSEI_INTR_IMPL", "text", "csr_addr_read",
         addrs=[0x644], class_opcodes=sorted(ALL_CSR_OPCODES),
         note="hip.VSEIP 待定位读数属平台实现"),
    _row("VSSI_INTR_IMPL", "text", "csr_addr_read",
         addrs=[0x644], class_opcodes=sorted(ALL_CSR_OPCODES),
         note="hip.VSSIP 待定位读数属平台实现"),
    _row("VSTI_INTR_IMPL", "text", "csr_addr_read",
         addrs=[0x644], class_opcodes=sorted(ALL_CSR_OPCODES),
         note="hip.VSTIP 待定位读数属平台实现"),
    # ---- interrupt_impl ----
    _row("SEI_INTR_IMPL", "text", "csr_addr_read",
         addrs=[0x144, 0x044], class_opcodes=sorted(ALL_CSR_OPCODES),
         note="外部中断待定位读数属平台实现"),
    _row("SSI_INTR_IMPL", "text", "csr_addr_read",
         addrs=[0x144, 0x044], class_opcodes=sorted(ALL_CSR_OPCODES),
         note="软件中断待定位读数属平台实现"),
    _row("STI_INTR_IMPL", "text", "csr_addr_read",
         addrs=[0x144, 0x044], class_opcodes=sorted(ALL_CSR_OPCODES),
         note="计时器中断待定位读数属平台实现"),
    # ---- wfi ----
    _row("WFI_U_MODE", "post", "trap_on", phase="post",
         prefixes=["wfi"], causes=[2],
         note="低特权级 WFI 是否陷入属实现选择"),
    # ---- 置脏位 ----
    _row("HW_MSTATUS_FS_DIRTY_UPDATE", "post", "csr_bits_changed", phase="post",
         csr=0x100, mask=0x6000, prefixes=list(FP_COMPUTE_PREFIXES),
         class_opcodes=["fadd.d", "fdiv.s", "fmadd.d", "fcvt.d.s", "fmv.w.x"],
         note="浮点指令是否硬件置脏 FS 属实现自定义"),
    _row("HW_MSTATUS_VS_DIRTY_UPDATE", "post", "csr_bits_changed", phase="post",
         csr=0x100, mask=0x600, prefixes=["v"],
         class_opcodes=["vadd.vv", "vmv.v.v", "vsetvli"],
         note="向量指令是否硬件置脏 VS 属实现自定义", encoder=True),
    # ---- width 保留项 ----
    _row("VLEN", "text", "csr_addr_read",
         addrs=[0xC22], class_opcodes=sorted(ALL_CSR_OPCODES),
         note="vlenb 读数即 VLEN/8 属实现自定义"),
    _row("ELEN", "text", "csr_addr_read",
         addrs=[0xC21, 0xC22], class_opcodes=sorted(ALL_CSR_OPCODES),
         note="vl/vlenb 读数受 ELEN 影响", encoder=True),
    _row("SEW_MIN", "text", "operand_sew_pattern", sews=["e8"],
         opcodes=["vsetvli", "vsetvl"], class_opcodes=["vsetvli", "vsetvl"],
         note="最小 SEW 属实现自定义（e8 请求的结果可能被规范化）", encoder=True),
    _row("VECTOR_LS_INDEX_MAX_EEW", "pre", "ea_misaligned",
         prefixes=["vluxei", "vloxei"], vector_element=True,
         class_opcodes=["vluxei8.v", "vloxei8.v"],
         note="索引访存最大 EEW 属实现自定义", encoder=True),
    # ---- vector（keep_encoder）----
    _row("RVV_VL_WHEN_AVL_LT_DOUBLE_VLMAX", "pre", "vsetvli_avl_range",
         opcodes=["vsetvli", "vsetvl"], class_opcodes=["vsetvli", "vsetvl"],
         note="AVL∈[VLMAX,2*VLMAX) 时 vl 取值二选一属实现自定义", encoder=True),
    _row("FOLLOW_VTYPE_RESET_RECOMMENDATION", "text", "csr_addr_read",
         addrs=[0xC21], class_opcodes=sorted(ALL_CSR_OPCODES),
         note="vtype 复位值属实现自定义", encoder=True),
    _row("LEGAL_VSTART", "text", "csr_addr_write_any",
         addrs=[0x020], class_opcodes=sorted(ALL_CSR_OPCODES),
         note="vstart 合法值属实现自定义", encoder=True),
    _row("VILL_SET_ON_RESERVED_VTYPE", "text", "csr_addr_write_any",
         addrs=[0xC21], class_opcodes=sorted(ALL_CSR_OPCODES),
         note="保留 vtype 直接写入是否置 vill 属实现自定义", encoder=True),
    _row("RESERVED_VSET_X0X0_VILL_SET", "text", "reserved_encoding",
         class_opcodes=["vsetvl", "vsetvli"],
         note="vsetvl rd=x0,rs1=x0 保留编码行为", encoder=True),
    _row("RESERVED_VSET_X0X0_VLMAX_CHANGE", "text", "reserved_encoding",
         class_opcodes=["vsetvl", "vsetvli"],
         note="同上（vlmax 变体）", encoder=True),
    _row("VECTOR_FF_NO_EXCEPTION_TRIM", "post", "trap_on", phase="post",
         prefixes=["vle8ff", "vle16ff", "vle32ff", "vle64ff"], causes=[4, 5],
         note="仅故障优先载入的裁剪行为属实现自定义", encoder=True),
    _row("VECTOR_FF_SEG_EXCEPTION_PARTIAL_LOAD", "post", "trap_on", phase="post",
         prefixes=["vlseg"], contains="ff", causes=[4, 5],
         note="段式 FOF 载入行为属实现自定义", encoder=True),
    _row("VECTOR_FF_UPDATE_PAST_TRIM", "post", "trap_on", phase="post",
         prefixes=["vle", "vlseg"], contains="ff", causes=[4, 5],
         note="故障后裁剪是否继续更新属实现自定义", encoder=True),
    _row("VECTOR_LOAD_PAST_TRAP", "post", "trap_on", phase="post",
         prefixes=["vle", "vlseg", "vlux", "vlox", "vls"], causes=[4, 5, 13],
         note="陷入后已载入元素是否保留属实现自定义", encoder=True),
    _row("VECTOR_LOAD_SEG_FF_OVERWRITE_ELEMENTS_AFTER_FAULT", "post", "trap_on", phase="post",
         prefixes=["vlseg"], contains="ff", causes=[4, 5],
         note="故障后元素覆盖行为属实现自定义", encoder=True),
    _row("VECTOR_LS_MISALIGNED_LEGAL", "pre", "ea_misaligned",
         prefixes=["vle", "vse"], vector_element=True,
         class_opcodes=["vle32.v", "vse32.v"],
         note="向量访存非对齐是否合法属实现自定义", encoder=True),
    _row("VECTOR_LS_WHOLEREG_MISALIGNED_LEGAL", "pre", "ea_misaligned",
         vector_element=True,
         prefixes=["vl1re", "vl2re", "vl4re", "vl8re", "vs1r", "vs2r", "vs4r", "vs8r"],
         class_opcodes=["vl1re8.v", "vs1r.v"],
         note="整寄存器访存非对齐行为属实现自定义", encoder=True),
    _row("VECTOR_LS_SEG_PARTIAL_ACCESS", "post", "trap_on", phase="post",
         prefixes=["vlseg", "vssseg", "vsseg"], causes=[4, 5, 6, 7],
         note="段式访存部分完成行为属实现自定义", encoder=True),
    _row("SUPPORT_FRACTIONAL_LMUL_BEYOND_REQUIRED", "text",
         "operand_lmul_pattern", lmuls=["mf2", "mf4"],
         opcodes=["vsetvli", "vsetvl"], class_opcodes=["vsetvli", "vsetvl"],
         note="超出必备范围的分数 LMUL 支持属实现自定义（mf2/mf4 请求）", encoder=True),
    _row("VFREDUSUM_FINAL_NODE_ELEMENT_BEHAVIOR", "text", "opcode_set",
         opcodes=["vfredusum.vs"], class_suppression=True,
         note="归约求和末元素行为属实现自定义", encoder=True),
    _row("VFREDUSUM_INACTIVE_NODE_ELEMENT_BEHAVIOR", "text", "opcode_set",
         opcodes=["vfredusum.vs"], class_suppression=True,
         note="归约求和非活动元素行为属实现自定义", encoder=True),
    _row("VFREDUSUM_NAN", "text", "opcode_set",
         opcodes=["vfredusum.vs"], class_suppression=True,
         note="归约求和 NaN 处理属实现自定义", encoder=True),
    _row("VFREDUSUM_NODE_ROUNDING_BEHAVIOR", "text", "opcode_set",
         opcodes=["vfredusum.vs"], class_suppression=True,
         note="归约求和中间舍入属实现自定义", encoder=True),
]

ROW_INDEX = {r["id"]: r for r in MATRIX_ROWS}

# 臂 → 信息预算（tier 秩；与 experiment_signatures.TIER_RANK 一致）
ARM_TIER = {"text": 0, "static": 1, "operval": 2, "dynamic": 3}

# Kinds whose precise predicates consume nothing beyond the instruction text
# and the current values of its operand registers.
OPERVAL_KINDS = {
    "csr_write_bits",          # write value = source operand register
    "csr_write_field_eq",      # ditto
    "csr_write_field_notin",   # ditto
    "ea_misaligned",           # base register value + immediate
    "ea_misaligned_cross_page",
    "vsetvli_avl_range",       # rs1 value or immediate AVL
}
_ROW_TIER_RANK = {"text": 0, "static": 1, "pre": 2, "post": 3}


# ---------------------------------------------------------------------------
# New-kind evaluators (existing kinds delegate to experiment_signatures)
# ---------------------------------------------------------------------------


def _in_cause_family(op: str, family: str) -> bool:
    """指令家族判定：能引发该类异常的全部指令形态（含向量变体）。"""
    if family in ("load", "mem"):
        if op in set(SCALAR_LOADS) | set(FP_LOADS) | {"lr.w", "lr.d"}:
            return True
        if op.startswith(("vle", "vlux", "vlox", "vls", "vlseg",
                          "vl1re", "vl2re", "vl4re", "vl8re")):
            return True
        if family == "load":
            return False
    if family in ("store", "mem"):
        if op in set(SCALAR_STORES) | set(FP_STORES) | set(AMO_OPS) | {"sc.w", "sc.d"}:
            return True
        return op.startswith(("vse", "vsux", "vsox", "vss", "vsseg",
                              "vs1r", "vs2r", "vs4r", "vs8r"))
    if family == "fetch":
        return op in set(JUMP_OPS) | set(BRANCH_OPS)
    if family == "illegal":
        return op.startswith("vmv") or op.startswith("vsetv")
    return False


def _csr_addr(ctx) -> int | None:
    return parse_csr_from_operands(_opers(ctx), _op(ctx))


def _is_read_form(ctx) -> bool:
    """csrrs/csrrc with rs1=x0 (pure read); csrrw with rs1=x0 is a WRITE of 0."""
    op = _op(ctx)
    ops = _opers(ctx)
    if op in {"csrrs", "csrrc"} and len(ops) >= 3:
        return ops[2] in {"x0", "zero"}
    return False


def _requested_value(ctx):
    op = _op(ctx)
    ops = _opers(ctx)
    if op in {"csrrwi", "csrrsi", "csrrci"}:
        return parse_int_token(ops[2]) if len(ops) > 2 else None
    if len(ctx.operands) > 2:
        reg = ctx.parse_register_operand(ctx.operands[2])
        if reg is not None and ctx.s_pre is not None:
            return ctx.get_xpr(reg)
    return None


def _eval_matrix_new(ctx, sig: dict):
    """Evaluators for the kinds defined in this module."""
    op = _op(ctx)
    kind = sig["kind"]
    addrs = set(sig.get("addrs", []))

    if kind == "csr_addr_read":
        if op not in ALL_CSR_OPCODES or not _is_read_form(ctx):
            return None
        addr = _csr_addr(ctx)
        if addr is not None and addr in addrs:
            return f"CSR 0x{addr:x} 读数属实现自定义（{sig['id']}）"
        return None

    if kind == "csr_addr_write_any":
        if op not in ALL_CSR_OPCODES:
            return None
        if _is_read_form(ctx):
            return None
        addr = _csr_addr(ctx)
        if addr is not None and addr in addrs:
            return f"CSR 0x{addr:x} 写入结果属实现自定义（{sig['id']}）"
        return None

    if kind == "csr_addr_in":
        if op not in ALL_CSR_OPCODES:
            return None
        addr = _csr_addr(ctx)
        if addr is not None and addr in addrs:
            return f"CSR 0x{addr:x} 参考实现未实现，访问行为属实现选择（{sig['id']}）"
        return None

    if kind == "csr_write_field_eq":
        if op not in ALL_CSR_OPCODES or _is_read_form(ctx):
            return None
        addr = _csr_addr(ctx)
        if addr not in set(sig.get("csr", [])):
            return None
        requested = _requested_value(ctx)
        if requested is None:
            return None
        field = (requested & sig.get("field_mask", 0)) & FULL64
        if field == (sig.get("field_value", 0) & FULL64):
            return (f"CSR 0x{addr:x} 写请求字段值 0x{field:x}"
                    f"（该模式支持属实现自定义，{sig['id']}）")
        return None

    if kind == "csr_write_field_notin":
        if op not in ALL_CSR_OPCODES or _is_read_form(ctx):
            return None
        addr = _csr_addr(ctx)
        if addr not in set(sig.get("csr", [])):
            return None
        requested = _requested_value(ctx)
        if requested is None:
            return None
        field = (requested & sig.get("field_mask", 0)) & FULL64
        if field not in {v & FULL64 for v in sig.get("values", [])}:
            return (f"CSR 0x{addr:x} 写请求保留字段值 0x{field:x}"
                    f"（WLRL 行为属实现选择，{sig['id']}）")
        return None

    if kind == "csr_bits_changed":
        prefixes = sig.get("prefixes", [])
        if prefixes and not any(op.startswith(p) for p in prefixes):
            return None
        if ctx.s_pre is None or ctx.s_post is None:
            return None
        before = ctx.get_csr(sig["csr"]) & sig["mask"]
        after = ctx.get_post_csr(sig["csr"]) & sig["mask"]
        if before != after:
            return (f"CSR 0x{sig['csr']:x} 位 0x{sig['mask']:x} 由硬件更新"
                    f"（置脏策略属实现自定义，{sig['id']}）")
        return None

    if kind == "reserved_encoding":
        ops = _opers(ctx)
        if op in {"vmv1r.v", "vmv2r.v", "vmv4r.v", "vmv8r.v"} and len(ops) >= 2:
            nr = {"vmv1r.v": 1, "vmv2r.v": 2, "vmv4r.v": 4, "vmv8r.v": 8}[op]
            token = ops[1].strip().lower().lstrip("v")
            if token.isdigit() and int(token) % nr != 0:
                return f"{op} 源寄存器组未对齐（保留编码，{sig['id']}）"
        if op in {"vsetvl", "vsetvli"} and len(ops) >= 2 \
                and ops[0] == "x0" and ops[1] == "x0":
            return f"{op} rd=x0, rs1=x0（保留编码，{sig['id']}）"
        return None

    if kind == "ea_misaligned_cross_page":
        if not _matches(op, sig):
            return None
        from .experiment_signatures import SCALAR_MEMORY_SIZES
        size = SCALAR_MEMORY_SIZES.get(op)
        if not size or size == 1:
            return None
        base_reg, imm = _mem_operand_raw(ctx)
        if base_reg is None:
            return None
        ea = _effective_address_pre(ctx, base_reg, imm or 0)
        if ea is None:
            return None
        if ea % size != 0 and ((ea ^ (ea + size - 1)) >> 12) != 0:
            return (f"非对齐访问 0x{ea:x} 跨 4KiB 页边界"
                    f"（拆分/优先级行为属实现自定义，{sig['id']}）")
        return None

    if kind == "operand_sew_pattern":
        if op not in {"vsetvli", "vsetvl"}:
            return None
        if any(o.startswith(tuple(sig.get("sews", []))) for o in _opers(ctx)):
            return f"{op} 请求 {sig.get('sews')}（结果可能被规范化，{sig['id']}）"
        return None

    if kind == "operand_lmul_pattern":
        if op not in {"vsetvli", "vsetvl"}:
            return None
        lmus = tuple(sig.get("lmuls", []))
        if any(tok.startswith(lmus)
               for o in _opers(ctx) for tok in o.split(",")):
            return f"{op} 请求分数 LMUL {sig.get('lmuls')}（支持范围属实现自定义，{sig['id']}）"
        return None

    if kind == "vsetvli_avl_range":
        if op not in {"vsetvli", "vsetvl"}:
            return None
        if ctx.s_pre is None:
            return None
        vlmax = ctx.get_vlmax()
        if not vlmax:
            return None
        ops = _opers(ctx)
        avl = None
        if len(ops) >= 2:
            token = ops[1]
            reg = ctx.parse_register_operand(token)
            if reg is not None:
                avl = ctx.get_xpr(reg)
            else:
                try:
                    avl = int(token, 0)
                except ValueError:
                    avl = None
        if avl is None:
            return None
        if vlmax <= avl < 2 * vlmax:
            return (f"{op} AVL={avl}∈[VLMAX={vlmax},2*VLMAX)"
                    f"（vl 取值属实现自定义，{sig['id']}）")
        return None

    if kind == "vsetvli_sew_lt":
        if op not in {"vsetvli", "vsetvl"}:
            return None
        if ctx.s_pre is None:
            return None
        sew = ctx.get_vsew()
        if sew and sew < sig.get("sew_lt", 16):
            return (f"{op} 请求 SEW={sew}（最小 SEW 属实现自定义，{sig['id']}）")
        return None

    return None


_NEW_KINDS = {
    "csr_addr_read", "csr_addr_write_any", "csr_addr_in",
    "csr_write_field_eq", "csr_write_field_notin", "csr_bits_changed",
    "reserved_encoding", "ea_misaligned_cross_page", "vsetvli_sew_lt",
    "operand_sew_pattern", "operand_lmul_pattern", "vsetvli_avl_range",
}


def evaluate_row(ctx, sig: dict):
    """Precise predicate for a row at its own phase.

    ctx must carry the information the row's tier requires
    (s_pre for pre rows, s_post for post rows).
    """
    if sig["kind"] in _NEW_KINDS:
        return _eval_matrix_new(ctx, sig)
    if sig.get("phase", "pre") == "pre":
        reason = _eval_static(ctx, sig)
        if reason is None:
            reason = _eval_pre(ctx, sig)
        return reason
    return _eval_post(ctx, sig)


def evaluate_row_arm(ctx_pre, ctx_post, sig: dict, arm: str):
    """One matrix cell.

    Returns "precise" when the arm's budget covers the row tier and the
    precise predicate fires; "class" when the budget does not cover the
    tier and the row's correlated opcode class matches; None otherwise.
    """
    arm_rank = ARM_TIER[arm]
    row_rank = _ROW_TIER_RANK[sig["tier"]]
    covers = arm_rank >= row_rank or (arm == "operval"
                                      and sig["kind"] in OPERVAL_KINDS)
    if covers:
        ctx = ctx_post if sig.get("phase", "pre") == "post" else ctx_pre
        if ctx is None:
            return None
        return "precise" if evaluate_row(ctx, sig) else None
    # Class fallback: the row's correlated instruction class.  Rows that
    # declare an explicit class list use it; rows whose precise scope is
    # opcode/prefix based fall back over exactly that scope (the narrowest
    # text-visible class correlated with the behavior).
    probe = ctx_pre or ctx_post
    if probe is None:
        return None
    op = _op(probe)
    family = sig.get("class_family")
    if family and _in_cause_family(op, family):
        return "class"
    class_list = sig.get("class_opcodes")
    if class_list and op in {o.lower() for o in class_list}:
        return "class"
    if not family and not class_list and (sig.get("opcodes") or sig.get("prefixes")):
        if _matches(op, sig):
            return "class"
    return None


__all__ = [
    "MATRIX_ROWS",
    "ROW_INDEX",
    "ARM_TIER",
    "evaluate_row",
    "evaluate_row_arm",
]
