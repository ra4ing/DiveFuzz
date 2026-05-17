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

"""Hierarchical value pools for RISC-V fuzzing data initialization.

Provides categorized value generation covering four tiers per data type:

    REGULAR     — common-case values that exercise mainstream execution paths
    BOUNDARY    — values near overflow, rounding, sign, and architectural edges
    EXTREME     — maximum/minimum representable values, single-bit patterns
    EXCEPTIONAL — NaN, Inf, subnormal, illegal encodings, address-like patterns

Data types:
    GPR_64   — 64-bit general-purpose integer registers
    FPR_16   — IEEE 754 binary16 (half-precision) via fmv.h.x
    FPR_32   — IEEE 754 binary32 (single-precision) via fmv.w.x / flw
    FPR_64   — IEEE 754 binary64 (double-precision) via fmv.d.x / fld
    MEM_WORD — 32-bit memory words with two-level sampling:
               (1) category roll → (2) semantic sub-type roll (INT/FP/ADDR/OTHER)

All category probabilities and MEM_WORD semantic sub-type ratios are
configurable via ValuePoolConfig.
"""

from __future__ import annotations

import random
import struct
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Union


# =============================================================================
# Enumerations
# =============================================================================

class DataType(Enum):
    GPR_64   = "gpr_64"
    FPR_16   = "fpr_16"
    FPR_32   = "fpr_32"
    FPR_64   = "fpr_64"
    MEM_WORD = "mem_word"


class ValueCategory(Enum):
    REGULAR     = "regular"
    BOUNDARY    = "boundary"
    EXTREME     = "extreme"
    EXCEPTIONAL = "exceptional"


class MemSemantic(Enum):
    """Semantic sub-type for MEM_WORD two-level sampling.

    A single 32-bit memory word is consumed by different RISC-V
    instructions that interpret the bits differently:
        lw / sw / amoxxx → integer
        flw / fsw        → float32
    """
    INT   = "int"
    FP    = "fp"
    ADDR  = "addr"
    OTHER = "other"


# =============================================================================
# Configurable Distributions
# =============================================================================

@dataclass
class PoolConfig:
    """Per-DataType category distribution (fractions should sum to ~1.0)."""
    regular:     float = 0.50
    boundary:    float = 0.20
    extreme:     float = 0.15
    exceptional: float = 0.15

    def to_dict(self) -> Dict[ValueCategory, float]:
        return {
            ValueCategory.REGULAR:     self.regular,
            ValueCategory.BOUNDARY:    self.boundary,
            ValueCategory.EXTREME:     self.extreme,
            ValueCategory.EXCEPTIONAL: self.exceptional,
        }

    def normalize(self) -> PoolConfig:
        total = self.regular + self.boundary + self.extreme + self.exceptional
        if total == 0:
            return PoolConfig(0.25, 0.25, 0.25, 0.25)
        return PoolConfig(
            regular=self.regular / total,
            boundary=self.boundary / total,
            extreme=self.extreme / total,
            exceptional=self.exceptional / total,
        )


@dataclass
class MemWordConfig:
    """Secondary distribution for MEM_WORD semantic sub-types.

    Within each category the sampler first rolls a MemSemantic according
    to these fractions, then picks a 32-bit word from the sub-pool.
    """
    int_ratio:   float = 0.45
    fp_ratio:    float = 0.40
    addr_ratio:  float = 0.10
    other_ratio: float = 0.05

    def to_dict(self) -> Dict[MemSemantic, float]:
        return {
            MemSemantic.INT:   self.int_ratio,
            MemSemantic.FP:    self.fp_ratio,
            MemSemantic.ADDR:  self.addr_ratio,
            MemSemantic.OTHER: self.other_ratio,
        }

    def normalize(self) -> "MemWordConfig":
        total = self.int_ratio + self.fp_ratio + self.addr_ratio + self.other_ratio
        if total == 0:
            return MemWordConfig(0.25, 0.25, 0.25, 0.25)
        return MemWordConfig(
            int_ratio=self.int_ratio / total,
            fp_ratio=self.fp_ratio / total,
            addr_ratio=self.addr_ratio / total,
            other_ratio=self.other_ratio / total,
        )


@dataclass
class ValuePoolConfig:
    """Master distribution config for all data types.

    Override any field to tune fuzzing bias — e.g. raise
    ``fpr_64.exceptional`` to inject more NaN patterns.
    """
    gpr_64:    PoolConfig = field(default_factory=lambda: PoolConfig(
        regular=0.50, boundary=0.20, extreme=0.15, exceptional=0.15,
    ))
    fpr_16:    PoolConfig = field(default_factory=lambda: PoolConfig(
        regular=0.50, boundary=0.20, extreme=0.15, exceptional=0.15,
    ))
    fpr_32:    PoolConfig = field(default_factory=lambda: PoolConfig(
        regular=0.40, boundary=0.25, extreme=0.20, exceptional=0.15,
    ))
    fpr_64:    PoolConfig = field(default_factory=lambda: PoolConfig(
        regular=0.40, boundary=0.25, extreme=0.20, exceptional=0.15,
    ))
    mem_word:  PoolConfig = field(default_factory=lambda: PoolConfig(
        regular=0.35, boundary=0.20, extreme=0.20, exceptional=0.25,
    ))
    mem_semantic: MemWordConfig = field(default_factory=MemWordConfig)

    def for_type(self, dt: DataType) -> PoolConfig:
        return getattr(self, dt.value)


# =============================================================================
# IEEE 754 Bit-Level Helpers
# =============================================================================

def _float64_to_bits(value: float) -> int:
    return int.from_bytes(struct.pack(">d", value), "big")


def _float32_to_bits(value: float) -> int:
    return int.from_bytes(struct.pack(">f", value), "big")


# --- binary16 helpers (Python has no native float16) ---

def _fp16_pack(sign: int, exponent: int, mantissa: int) -> int:
    return ((sign & 1) << 15) | ((exponent & 0x1F) << 10) | (mantissa & 0x3FF)


def _random_normal_f16() -> int:
    sign = random.randint(0, 1)
    exponent = random.randint(1, 30)
    mantissa = random.randint(0, 1023)
    return _fp16_pack(sign, exponent, mantissa)


def _random_small_f16() -> int:
    sign = random.randint(0, 1)
    exponent = random.randint(10, 22)
    mantissa = random.randint(0, 1023)
    return _fp16_pack(sign, exponent, mantissa)


def _random_normal_f32() -> int:
    sign = random.randint(0, 1)
    exponent = random.randint(1, 254)
    mantissa = random.randint(0, (1 << 23) - 1)
    return (sign << 31) | (exponent << 23) | mantissa


def _random_small_f32() -> int:
    sign = random.randint(0, 1)
    exponent = random.randint(118, 143)
    mantissa = random.randint(0, (1 << 23) - 1)
    return (sign << 31) | (exponent << 23) | mantissa


def _random_normal_f64() -> int:
    sign = random.randint(0, 1)
    exponent = random.randint(1, 2046)
    mantissa = random.getrandbits(52)
    return (sign << 63) | (exponent << 52) | mantissa


def _random_small_f64() -> int:
    sign = random.randint(0, 1)
    exponent = random.randint(1010, 1035)
    mantissa = random.getrandbits(52)
    return (sign << 63) | (exponent << 52) | mantissa


# =============================================================================
# Value Pools — GPR_64
# =============================================================================

_GPR64_BOUNDARY: List[int] = [
    0x0000_0000_0000_0000,
    0x0000_0000_0000_0001,
    0xFFFF_FFFF_FFFF_FFFF,
    0x7FFF_FFFF_FFFF_FFFF,
    0x8000_0000_0000_0000,
    0x0000_0000_FFFF_FFFF,
    0x0000_0001_0000_0000,
    0xFFFF_FFFF_0000_0000,
    0x8000_0000_0000_0001,
    0x7FFF_FFFF_FFFF_FFFF,
    *[1 << n for n in [0, 7, 8, 15, 16, 31, 32, 47, 48, 62, 63]],
    *[(1 << n) - 1 for n in [8, 16, 31, 32, 63, 64]],
]

_GPR64_EXTREME: List[int] = [
    0x0000_0000_0000_0000,
    0xFFFF_FFFF_FFFF_FFFF,
    0x0000_0000_0000_0001,
    *[1 << n for n in [0, 1, 3, 7, 8, 15, 16, 24, 31, 32, 40, 48, 56, 63]],
    0x5555_5555_5555_5555,
    0xAAAA_AAAA_AAAA_AAAA,
    0x0101_0101_0101_0101,
    0x8080_8080_8080_8080,
    0xFF00_FF00_FF00_FF00,
    0x0123_4567_89AB_CDEF,
    0xFEDC_BA98_7654_3210,
]

_GPR64_EXCEPTIONAL: List[int] = [
    0x0000_0000_0000_0000,
    0x0000_0000_0000_0008,
    0x0000_0000_0000_0FFF,
    0x0000_7FFF_FFFF_FFFF,
    0x8000_0000_0000_0000,
    0xFFFF_FFFF_FFFF_F000,
    0x0000_0000_8000_0000,
    0x0000_0000_FFFF_FFFF,
    0xFFFF_FFFF_0000_0000,
    0xFFFF_FFFF_8000_0000,
    0x0000_0000_0000_0003,
    0x0000_0000_0000_0005,
    0x0000_0000_0000_0007,
]


# =============================================================================
# Value Pools — FPR_16 (binary16)
# =============================================================================

_FPR16_BOUNDARY: List[int] = [
    _fp16_pack(0, 15, 0),     _fp16_pack(1, 15, 0),
    _fp16_pack(0, 16, 0),     _fp16_pack(1, 16, 0),
    _fp16_pack(0, 14, 0),
    _fp16_pack(0, 30, 1023),  _fp16_pack(1, 30, 1023),
    _fp16_pack(0, 1, 0),      _fp16_pack(0, 1, 1),
    _fp16_pack(0, 0, 1),
    _fp16_pack(0, 30, 0),
    _fp16_pack(0, 14, 1023),
]

_FPR16_EXTREME: List[int] = [
    _fp16_pack(0, 30, 1023),  _fp16_pack(1, 30, 1023),
    _fp16_pack(0, 1, 0),      _fp16_pack(0, 0, 1),
    _fp16_pack(0, 31, 0),     _fp16_pack(1, 31, 0),
    _fp16_pack(0, 0, 0),      _fp16_pack(1, 0, 0),
    _fp16_pack(0, 30, 1022),
    _fp16_pack(0, 1, 2),
    _fp16_pack(0, 2, 0),
]

_FPR16_EXCEPTIONAL: List[int] = [
    _fp16_pack(0, 31, 1),     _fp16_pack(0, 31, 512),
    _fp16_pack(0, 31, 1023),  _fp16_pack(1, 31, 1),
    _fp16_pack(0, 31, 0x200),
    _fp16_pack(0, 0, 0),      _fp16_pack(1, 0, 0),
    _fp16_pack(0, 31, 0),     _fp16_pack(1, 31, 0),
    _fp16_pack(0, 0, 1023),   _fp16_pack(0, 0, 512),
]


# =============================================================================
# Value Pools — FPR_32 (binary32)
# =============================================================================

_FPR32_BOUNDARY: List[int] = [
    _float32_to_bits(1.0),         _float32_to_bits(-1.0),
    _float32_to_bits(2.0),         _float32_to_bits(-2.0),
    _float32_to_bits(0.5),         _float32_to_bits(3.14159265),
    _float32_to_bits(10.0),        _float32_to_bits(100.0),
    _float32_to_bits(0.1),         _float32_to_bits(0.01),
    0x3F80_0001, 0x3F7F_FFFF, 0x3F00_0001, 0x3EFF_FFFF,
    0x4B80_0000, 0x4B7F_FFFF, 0x4F00_0000,
    0x7F7F_FFFF, 0x0080_0000, 0x0000_0001,
    0x7F7F_FFFE, 0x7F80_0000,
]

_FPR32_EXTREME: List[int] = [
    0x7F7F_FFFF, 0xFF7F_FFFF, 0x0080_0000, 0x8080_0000,
    0x0000_0001, 0x8000_0001,
    0x7F80_0000, 0xFF80_0000, 0x0000_0000, 0x8000_0000,
    0x7F7F_FFFE, 0x0080_0001, 0x0000_0002,
    0x7F80_0001, 0x477F_E000,
]

_FPR32_EXCEPTIONAL: List[int] = [
    0x7FC0_0000, 0x7FFF_FFFF, 0xFFC0_0000,
    0x7F80_0001, 0x7FBF_FFFF, 0xFF80_0001,
    0x0000_0000, 0x8000_0000, 0x0000_0001, 0x007F_FFFF,
    0x7F80_0000, 0xFF80_0000,
]


# =============================================================================
# Value Pools — FPR_64 (binary64)
# =============================================================================

_FPR64_BOUNDARY: List[int] = [
    _float64_to_bits(1.0),         _float64_to_bits(-1.0),
    _float64_to_bits(2.0),         _float64_to_bits(-2.0),
    _float64_to_bits(0.5),         _float64_to_bits(3.141592653589793),
    _float64_to_bits(10.0),        _float64_to_bits(100.0),
    _float64_to_bits(0.1),         _float64_to_bits(0.01),
    0x3FF0_0000_0000_0001, 0x3FEF_FFFF_FFFF_FFFF,
    0x4340_0000_0000_0000, 0x433F_FFFF_FFFF_FFFF,
    0x7FEF_FFFF_FFFF_FFFF, 0x0010_0000_0000_0000,
    0x0000_0000_0000_0001,
    0x7FEF_FFFF_FFFF_FFFE, 0x7FF0_0000_0000_0000,
]

_FPR64_EXTREME: List[int] = [
    0x7FEF_FFFF_FFFF_FFFF, 0xFFEF_FFFF_FFFF_FFFF,
    0x0010_0000_0000_0000, 0x8010_0000_0000_0000,
    0x0000_0000_0000_0001, 0x8000_0000_0000_0001,
    0x7FF0_0000_0000_0000, 0xFFF0_0000_0000_0000,
    0x0000_0000_0000_0000, 0x8000_0000_0000_0000,
    0x7FEF_FFFF_FFFF_FFFE, 0x0010_0000_0000_0001,
]

_FPR64_EXCEPTIONAL: List[int] = [
    0x7FF8_0000_0000_0000, 0x7FFF_FFFF_FFFF_FFFF,
    0xFFF8_0000_0000_0000,
    0x7FF0_0000_0000_0001, 0x7FF7_FFFF_FFFF_FFFF,
    0xFFF0_0000_0000_0001,
    0x0000_0000_0000_0000, 0x8000_0000_0000_0000,
    0x0000_0000_0000_0001, 0x000F_FFFF_FFFF_FFFF,
    0x7FF0_0000_0000_0000, 0xFFF0_0000_0000_0000,
]


# =============================================================================
# Value Pools — MEM_WORD (two-level: category → semantic sub-type)
# =============================================================================

# --- REGULAR generators (on-the-fly) per semantic sub-type ---

def _random_addr_pattern() -> int:
    base = random.choice([0x8000_0000, 0x0000_0000, 0xFFFF_0000, 0x0000_7F00])
    return (base + random.randint(0, 0xFFF)) & 0xFFFF_FFFF


def _random_other_pattern() -> int:
    return random.choice([
        random.getrandbits(32),
        0x0101_0101, 0x8080_8080, 0xFF00_FF00, 0x00FF_00FF,
        0x0000_006F, 0x0000_0001, 0x0000_0002, 0x0000_0003,
    ])


_MEM_REGULAR_GENERATORS: Dict[MemSemantic, Callable[[], int]] = {
    MemSemantic.INT:   lambda: random.getrandbits(32),
    MemSemantic.FP:    _random_small_f32,
    MemSemantic.ADDR:  _random_addr_pattern,
    MemSemantic.OTHER: _random_other_pattern,
}

# --- BOUNDARY sub-pools ---

_MEM_BOUNDARY: Dict[MemSemantic, List[int]] = {
    MemSemantic.INT: [
        0x0000_0000, 0x0000_0001, 0xFFFF_FFFF,
        0x7FFF_FFFF, 0x8000_0000,
        *[1 << n for n in [0, 7, 8, 15, 16, 24, 31]],
    ],
    MemSemantic.FP: [
        _float32_to_bits(1.0),
        _float32_to_bits(-1.0),
        _float32_to_bits(2.0),
        _float32_to_bits(0.0),
        0x7F80_0000,
        0xFF80_0000,
    ],
    MemSemantic.ADDR: [0x8000_0000, 0x0000_1000, 0xFFFF_F000],
    MemSemantic.OTHER: [],
}

# --- EXTREME sub-pools ---

_MEM_EXTREME: Dict[MemSemantic, List[int]] = {
    MemSemantic.INT: [
        0x0000_0000, 0xFFFF_FFFF, 0x8000_0000, 0x7FFF_FFFF,
        *[1 << n for n in [0, 1, 7, 8, 15, 16, 24, 31]],
        0x5555_5555, 0xAAAA_AAAA,
    ],
    MemSemantic.FP: [
        _float32_to_bits(3.4028235e38),
        _float32_to_bits(1.1754944e-38),
        0x0000_0001,
        0x7FC0_0000,
    ],
    MemSemantic.ADDR: [],
    MemSemantic.OTHER: [],
}

# --- EXCEPTIONAL sub-pools ---

_MEM_EXCEPTIONAL: Dict[MemSemantic, List[int]] = {
    MemSemantic.INT: [
        0x0000_0000, 0xFFFF_FFFF,
        0x0000_006F,
    ],
    MemSemantic.FP: [
        0x7FC0_0000, 0x7F80_0001,
        0x7F80_0000, 0xFF80_0000,
        0x8000_0000,
    ],
    MemSemantic.ADDR: [0x8000_0000, 0x8000_0004],
    MemSemantic.OTHER: [
        0x0101_0101, 0x8080_8080, 0xFF00_FF00, 0x00FF_00FF,
        0x0000_0001, 0x0000_0002, 0x0000_0003,
    ],
}

_MEM_POOLS: Dict[ValueCategory, Dict[MemSemantic, List[int]]] = {
    ValueCategory.BOUNDARY:    _MEM_BOUNDARY,
    ValueCategory.EXTREME:     _MEM_EXTREME,
    ValueCategory.EXCEPTIONAL: _MEM_EXCEPTIONAL,
}


# =============================================================================
# ValuePool — one-level engine (GPR / FPR)
# =============================================================================

class ValuePool:
    """Hierarchical value pool for single-semantic DataTypes."""

    _REGULAR_BATCH_SIZE = 128

    def __init__(
        self,
        data_type: DataType,
        config: Optional[PoolConfig] = None,
    ):
        self._dt = data_type
        self._cfg = (config or PoolConfig()).normalize()
        self._dist: Dict[ValueCategory, float] = self._cfg.to_dict()
        self._pool: Dict[ValueCategory, List[int]] = {
            ValueCategory.BOUNDARY:    _BOUNDARY_POOLS[data_type],
            ValueCategory.EXTREME:     _EXTREME_POOLS[data_type],
            ValueCategory.EXCEPTIONAL: _EXCEPTIONAL_POOLS[data_type],
        }
        self._regular_cache: List[int] = []
        self._regular_gen = _REGULAR_GENERATORS[data_type]

    def sample(self) -> int:
        roll = random.random()
        cumulative = 0.0
        for category in ValueCategory:
            cumulative += self._dist[category]
            if roll < cumulative:
                return self._sample_category(category)
        return self._sample_category(ValueCategory.REGULAR)

    def _sample_category(self, category: ValueCategory) -> int:
        if category == ValueCategory.REGULAR:
            return self._sample_regular()
        return random.choice(self._pool[category])

    def _sample_regular(self) -> int:
        if not self._regular_cache:
            self._regular_cache = [
                self._regular_gen() for _ in range(self._REGULAR_BATCH_SIZE)
            ]
        return self._regular_cache.pop()


# =============================================================================
# MemWordValuePool — two-level engine (MEM_WORD: category → semantic)
# =============================================================================

class MemWordValuePool:
    """Two-level pool for MEM_WORD: category roll → semantic sub-type → value.

    Provides the same ``sample() → int`` interface as ValuePool, but
    internally applies a secondary distribution across MemSemantic
    sub-types so that integer, float32, address, and other bit patterns
    appear at controlled ratios.
    """

    _REGULAR_BATCH_SIZE = 128

    def __init__(
        self,
        category_config: PoolConfig,
        semantic_config: MemWordConfig,
    ):
        self._cat_cfg = category_config.normalize()
        self._sem_cfg = semantic_config.normalize()
        self._cat_dist = self._cat_cfg.to_dict()
        self._sem_dist = self._sem_cfg.to_dict()
        self._regular_cache: Dict[MemSemantic, List[int]] = {}

    def sample(self) -> int:
        roll = random.random()
        cum = 0.0
        for cat in ValueCategory:
            cum += self._cat_dist[cat]
            if roll < cum:
                return self._sample_category(cat)
        return self._sample_category(ValueCategory.REGULAR)

    def _sample_category(self, cat: ValueCategory) -> int:
        sem = self._roll_semantic()
        if cat == ValueCategory.REGULAR:
            return self._sample_regular(sem)
        sub = _MEM_POOLS[cat].get(sem, [])
        if not sub:
            return self._sample_regular(sem)
        return random.choice(sub)

    def _roll_semantic(self) -> MemSemantic:
        roll = random.random()
        cum = 0.0
        for sem in MemSemantic:
            cum += self._sem_dist[sem]
            if roll < cum:
                return sem
        return MemSemantic.INT

    def _sample_regular(self, sem: MemSemantic) -> int:
        if sem not in self._regular_cache or not self._regular_cache[sem]:
            gen = _MEM_REGULAR_GENERATORS[sem]
            self._regular_cache[sem] = [
                gen() for _ in range(self._REGULAR_BATCH_SIZE)
            ]
        return self._regular_cache[sem].pop()


# =============================================================================
# Pool Registry (maps DataType → pre-computed pools & generators)
# =============================================================================

_BOUNDARY_POOLS: Dict[DataType, List[int]] = {
    DataType.GPR_64: _GPR64_BOUNDARY,
    DataType.FPR_16: _FPR16_BOUNDARY,
    DataType.FPR_32: _FPR32_BOUNDARY,
    DataType.FPR_64: _FPR64_BOUNDARY,
}

_EXTREME_POOLS: Dict[DataType, List[int]] = {
    DataType.GPR_64: _GPR64_EXTREME,
    DataType.FPR_16: _FPR16_EXTREME,
    DataType.FPR_32: _FPR32_EXTREME,
    DataType.FPR_64: _FPR64_EXTREME,
}

_EXCEPTIONAL_POOLS: Dict[DataType, List[int]] = {
    DataType.GPR_64: _GPR64_EXCEPTIONAL,
    DataType.FPR_16: _FPR16_EXCEPTIONAL,
    DataType.FPR_32: _FPR32_EXCEPTIONAL,
    DataType.FPR_64: _FPR64_EXCEPTIONAL,
}

_REGULAR_GENERATORS: Dict[DataType, Callable[[], int]] = {
    DataType.GPR_64: lambda: random.getrandbits(64),
    DataType.FPR_16: _random_small_f16,
    DataType.FPR_32: _random_small_f32,
    DataType.FPR_64: _random_small_f64,
}


# =============================================================================
# Convenience factories
# =============================================================================

_DEFAULT_CONFIG = ValuePoolConfig()


def create_value_pool(
    data_type: DataType,
    config: Optional[ValuePoolConfig] = None,
) -> ValuePool:
    cfg = (config or _DEFAULT_CONFIG)
    return ValuePool(data_type, config=cfg.for_type(data_type))


def create_all_pools(
    config: Optional[ValuePoolConfig] = None,
):
    """Create all six pool instances."""
    cfg = config or _DEFAULT_CONFIG
    pools: dict = {}
    for dt in DataType:
        if dt == DataType.MEM_WORD:
            pools[dt] = MemWordValuePool(
                category_config=cfg.for_type(dt),
                semantic_config=cfg.mem_semantic,
            )
        else:
            pools[dt] = ValuePool(dt, config=cfg.for_type(dt))
    return pools
