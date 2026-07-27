# Copyright (c) 2024-2025 Institute of Information Engineering, Chinese Academy of Sciences
#
# DiveFuzz is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#          http://license.coscl.org.cn/MulanPSL2
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
#
# See the Mulan PSL v2 for more details.

"""Helpers for bug-grounded experimental filter policies.

These helpers intentionally live outside ``xs_filters.py``.  They are used by
experimental architectures that compare opcode-only, pre-only, and pre+post
context-aware filtering.  The existing XiangShan filter set remains reference
material, not the policy under test.
"""

from __future__ import annotations

import re
from typing import Optional

from ...asm_template_manager.riscv_asm_syntex.csr import CSR_NAME_TO_ADDR

CSR_OPCODES = {"csrrw", "csrrs", "csrrc", "csrrwi", "csrrsi", "csrrci"}
CSR_PSEUDO_OPCODES = {"csrr", "csrw", "csrs", "csrc", "csrwi", "csrsi", "csrci"}
ALL_CSR_OPCODES = CSR_OPCODES | CSR_PSEUDO_OPCODES

SCALAR_MEMORY_SIZES = {
    "lb": 1, "lbu": 1, "sb": 1,
    "lh": 2, "lhu": 2, "sh": 2, "flh": 2, "fsh": 2,
    "lw": 4, "lwu": 4, "sw": 4, "flw": 4, "fsw": 4,
    "ld": 8, "sd": 8, "fld": 8, "fsd": 8,
    "flq": 16, "fsq": 16,
}
LR_SC_OPCODES = {"lr.w", "lr.d", "sc.w", "sc.d"}
HFENCE_OPCODES = {"hfence.gvma", "hfence.vvma", "sfence.vma"}

VECTOR_MEMORY_PREFIXES = (
    "vl", "vs", "vle", "vse", "vlseg", "vsseg", "vlux", "vsux", "vloxe", "vsoxe",
)
VECTOR_FP_MOVE_OPCODES = {"vfmerge.vfm", "vfmv.v.f", "vfmv.f.s", "vfmv.s.f"}
VECTOR_STATE_CSRS = {"vl", "vtype", "vstart", "vxrm", "vxsat"}

CSR_CYCLE_COUNTERS = {0xC00, 0xB00, 0xC80, 0xB80}
CSR_TIME_COUNTERS = {0xC01, 0xC81}
CSR_INSTRET_COUNTERS = {0xC02, 0xB02, 0xC82, 0xB82}
CSR_TVEC = {0x305, 0x105, 0x205}  # mtvec, stvec, vstvec
CSR_TRANSLATION = {0x180, 0x280, 0x680}  # satp, vsatp, hgatp
CSR_STATUS = {0x300, 0x100, 0x200, 0x600}  # mstatus, sstatus, vsstatus, hstatus
CSR_COUNTEREN = {0x306, 0x106, 0x606}  # mcounteren, scounteren, hcounteren
CSR_FRM = 0x002
CSR_VL = 0xC20
CSR_VTYPE = 0xC21
CSR_VSTART = 0x008
CSR_MTVAL = 0x343
CSR_STVAL = 0x143
CSR_MCAUSE = 0x342
CSR_SCAUSE = 0x142
CSR_MSTATUS = 0x300
MSTATUS_TW = 1 << 21

MEMORY_OPERAND_RE = re.compile(r"^(-?(?:0x[0-9a-fA-F]+|\d+))?\(([^)]+)\)$")


def opcode(ctx) -> str:
    """Return normalized opcode."""
    return ctx.opcode.lower().strip()


def parse_int_token(token: str) -> Optional[int]:
    """Parse decimal or hexadecimal integer tokens."""
    try:
        return int(token, 0)
    except (TypeError, ValueError):
        return None


def parse_csr_from_operands(operands: list[str], op: str | None = None) -> Optional[int]:
    """Extract the CSR address from canonical and pseudo CSR operands."""
    if not operands:
        return None
    op_lower = (op or "").lower()
    if op_lower in {"csrw", "csrs", "csrc", "csrwi", "csrsi", "csrci"}:
        index = 0
    elif op_lower == "csrr":
        index = 1
    else:
        index = 1
    if len(operands) <= index:
        return None
    csr_operand = operands[index].lower().strip().rstrip(",")
    value = parse_int_token(csr_operand)
    if value is not None:
        return value
    return CSR_NAME_TO_ADDR.get(csr_operand)


def is_hpm_counter(csr_addr: Optional[int]) -> bool:
    """Return whether a CSR is an HPM counter or high half."""
    if csr_addr is None:
        return False
    return (
        0xC03 <= csr_addr <= 0xC1F
        or 0xC83 <= csr_addr <= 0xC9F
        or 0xB03 <= csr_addr <= 0xB1F
        or 0xB83 <= csr_addr <= 0xB9F
    )


def is_counter_or_timer_csr(csr_addr: Optional[int], include_instret: bool = False) -> bool:
    """Return whether a CSR is an implementation-sensitive counter/timer."""
    if csr_addr is None:
        return False
    if csr_addr in CSR_CYCLE_COUNTERS or csr_addr in CSR_TIME_COUNTERS or is_hpm_counter(csr_addr):
        return True
    return include_instret and csr_addr in CSR_INSTRET_COUNTERS


def is_pmp_csr(csr_addr: Optional[int]) -> bool:
    """Return whether a CSR is pmpcfg*/pmpaddr*."""
    if csr_addr is None:
        return False
    return 0x3A0 <= csr_addr <= 0x3AF or 0x3B0 <= csr_addr <= 0x3EF


def is_warl_csr(csr_addr: Optional[int]) -> bool:
    """Return whether the CSR is in a bug-grounded WARL/implementation-defined group."""
    if csr_addr is None:
        return False
    return (
        csr_addr in CSR_TVEC
        or csr_addr in CSR_TRANSLATION
        or csr_addr in CSR_STATUS
        or csr_addr in CSR_COUNTEREN
        or is_pmp_csr(csr_addr)
    )


def parse_memory_operand(ctx) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """Return ``(base_reg, immediate, size)`` for scalar memory operations."""
    op = opcode(ctx)
    size = SCALAR_MEMORY_SIZES.get(op)
    if size is None:
        return None, None, None
    if not ctx.operands:
        return None, None, size
    mem_operand = ctx.operands[-1].replace(" ", "")
    match = MEMORY_OPERAND_RE.match(mem_operand)
    if not match:
        return None, None, size
    imm_raw, base_raw = match.groups()
    immediate = int(imm_raw, 0) if imm_raw else 0
    base_reg = ctx.parse_register_operand(base_raw)
    return base_reg, immediate, size


def effective_address(ctx) -> Optional[int]:
    """Compute scalar load/store effective address from pre-state register values."""
    base_reg, immediate, size = parse_memory_operand(ctx)
    if base_reg is None or immediate is None or size is None:
        return None
    return (ctx.get_xpr(base_reg) + immediate) & ((1 << 64) - 1)


def is_scalar_misaligned(ctx) -> bool:
    """Return whether a scalar memory instruction has an unaligned effective address."""
    base_reg, immediate, size = parse_memory_operand(ctx)
    if base_reg is None or immediate is None or size is None or size <= 1:
        return False
    return ((ctx.get_xpr(base_reg) + immediate) % size) != 0


def register_value(ctx, operand_index: int) -> Optional[int]:
    """Read an integer register operand from pre-state."""
    if len(ctx.operands) <= operand_index:
        return None
    reg = ctx.parse_register_operand(ctx.operands[operand_index])
    if reg is None:
        return None
    return ctx.get_xpr(reg)


def is_vector_opcode(op: str) -> bool:
    """Return whether an opcode belongs to broad vector space."""
    return op.startswith("v") or op in VECTOR_FP_MOVE_OPCODES


def is_vector_memory_opcode(op: str) -> bool:
    """Return whether an opcode is a broad vector memory operation."""
    return op.startswith(VECTOR_MEMORY_PREFIXES)


def target_csr_changed(ctx, csr_addr: int) -> bool:
    """Return whether a CSR value changes across candidate execution."""
    if ctx.s_post is None:
        return False
    return ctx.get_csr(csr_addr) != ctx.get_post_csr(csr_addr)
