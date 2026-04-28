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

"""Materialize integer constants using only real RISC-V instructions."""

from __future__ import annotations


I12_MIN = -(1 << 11)
I12_MAX = (1 << 11) - 1
I32_MIN = -(1 << 31)
I32_MAX = (1 << 31) - 1
U20_MASK = (1 << 20) - 1


def sign_extend(value: int, bits: int) -> int:
    """Return value interpreted as a signed two's-complement integer."""
    mask = (1 << bits) - 1
    value &= mask
    sign_bit = 1 << (bits - 1)
    return value - (1 << bits) if value & sign_bit else value


def _fits_i12(value: int) -> bool:
    return I12_MIN <= value <= I12_MAX


def _fits_i32(value: int) -> bool:
    return I32_MIN <= value <= I32_MAX


def _u20_field(value: int) -> int:
    """Return an assembler-accepted 20-bit unsigned immediate field."""
    return value & U20_MASK


def _materialize_i32(rd: str, value: int, xlen: int) -> list[str]:
    """Materialize a signed 32-bit value."""
    if _fits_i12(value):
        return [f"addi {rd}, zero, {value}"]

    lo12 = sign_extend(value, 12)
    hi20 = (value - lo12) // (1 << 12)
    lui_imm = _u20_field(hi20)

    instrs = [f"lui {rd}, {lui_imm}"]
    if lo12:
        add_op = "addiw" if xlen == 64 else "addi"
        instrs.append(f"{add_op} {rd}, {rd}, {lo12}")
    return instrs


def _materialize_i64(rd: str, value: int) -> list[str]:
    """Materialize a signed 64-bit value."""
    if _fits_i32(value):
        return _materialize_i32(rd, value, 64)

    lo12 = sign_extend(value, 12)
    hi = (value - lo12) // (1 << 12)

    instrs = _materialize_i64(rd, hi)
    instrs.append(f"slli {rd}, {rd}, 12")
    if lo12:
        instrs.append(f"addi {rd}, {rd}, {lo12}")
    return instrs


def materialize_const(rd: str, imm: int, xlen: int = 64) -> list[str]:
    """
    Emit real RISC-V instructions that set ``rd`` to ``imm``.

    The returned sequence never contains pseudo-instructions. Values are first
    normalized to the requested XLEN bit pattern, so callers can pass either
    signed Python integers or unsigned bit patterns.
    """
    if xlen not in (32, 64):
        raise ValueError("xlen must be 32 or 64")
    if rd in ("zero", "x0"):
        raise ValueError("cannot materialize a constant into x0/zero")

    value = sign_extend(imm, xlen)
    if xlen == 32:
        return _materialize_i32(rd, value, 32)
    return _materialize_i64(rd, value)
