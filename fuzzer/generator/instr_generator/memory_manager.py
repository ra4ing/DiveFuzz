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

"""
Memory Access Manager for Load/Store Instructions

This module provides utilities for managing safe memory access in generated
RISC-V assembly test cases. It ensures that load/store instructions access
valid memory regions without causing segmentation faults.

Design:
- T6 register: Points to center of 8KB data region (mem_region + 4096)
- SP register: Points to top of 1KB stack region (stack_end)
- No state management needed (stateless utility class)
"""

import random


class MemoryAccessManager:
    """Stateless utility class for constraining load/store instruction offsets"""

    # Memory region constants
    MEM_REGION_SIZE = 8192  # 8KB data region for T6-based access
    MEM_REGION_CENTER = 4096  # T6 points to this offset within mem_region
    MEM_REGION_RANDOM_START = 2048  # Start of randomized T6-accessible window
    MEM_REGION_RANDOM_SIZE = 4096  # Full signed IMM_12 window around T6
    STACK_SIZE = 1024  # 1KB stack region for SP-based access
    STACK_REGION_LABEL = "stack_region"

    # Access width mapping (instruction name -> bytes)
    ACCESS_WIDTH = {
        # Integer load/store
        'lb': 1, 'lbu': 1, 'sb': 1,
        'lh': 2, 'lhu': 2, 'sh': 2,
        'lw': 4, 'lwu': 4, 'sw': 4,
        'ld': 8, 'sd': 8,
        # Floating-point load/store
        'flw': 4, 'fsw': 4,
        'fld': 8, 'fsd': 8,
        # Compressed load/store
        'c.lw': 4, 'c.sw': 4,
        'c.ld': 8, 'c.sd': 8,
        'c.lwsp': 4, 'c.swsp': 4,
        'c.ldsp': 8, 'c.sdsp': 8,
        'c.flw': 4, 'c.fsw': 4,
        'c.fld': 8, 'c.fsd': 8,
        'c.flwsp': 4, 'c.fswsp': 4,
        'c.fldsp': 8, 'c.fsdsp': 8,
    }

    IMMEDIATE_MAX = {
        'UIMM_7': 127,
        'UIMM_7_4': 124,
        'UIMM_7_8': 120,
        'UIMM_8': 255,
        'UIMM_8_4': 252,
        'UIMM_8_8': 248,
        'UIMM_9_8': 504,
        'IMM_8': 127,
    }

    IMMEDIATE_ALIGNMENT = {
        'UIMM_7_4': 4,
        'UIMM_7_8': 8,
        'UIMM_8_4': 4,
        'UIMM_8_8': 8,
        'UIMM_9_8': 8,
    }

    @staticmethod
    def get_safe_offset_for_t6(instr_name):
        """
        Generate a safe offset for T6-based load/store instructions.

        Memory layout:
        - T6 points to mem_region + 4096 (center of 8KB region)
        - IMM_12 range: [-2048, 2047]
        - Accessible range: [mem_region + 2048, mem_region + 6143]

        Args:
            instr_name: Name of the instruction (e.g., 'lw', 'sw', 'ld')

        Returns:
            Safe offset value aligned to access width
        """
        access_width = MemoryAccessManager.ACCESS_WIDTH.get(instr_name, 4)

        # Calculate max offset considering access width
        # -2048 to (2047 - width + 1) ensures no out-of-bounds access
        max_offset = 2047 - access_width + 1
        min_offset = -2048

        # Generate random offset
        offset = random.randint(min_offset, max_offset)

        # Align to access width (e.g., ld requires 8-byte alignment)
        aligned_offset = offset & ~(access_width - 1)

        return aligned_offset

    @staticmethod
    def get_safe_offset_for_sp(uimm_type, access_width):
        """
        Generate a safe offset for SP-based load/store instructions.

        Memory layout:
        - SP points to stack_end (top of 1KB stack region)
        - Offsets are unsigned immediates with specific alignment

        Args:
            uimm_type: Type of unsigned immediate ('UIMM_8_4' or 'UIMM_9_8')
            access_width: Size of memory access in bytes (4 or 8)

        Returns:
            Safe offset value with proper alignment
        """
        max_value = MemoryAccessManager.IMMEDIATE_MAX.get(uimm_type, 252)
        alignment = MemoryAccessManager.IMMEDIATE_ALIGNMENT.get(uimm_type) or access_width or 1

        # Ensure offset doesn't exceed stack size
        max_safe_offset = min(max_value, MemoryAccessManager.STACK_SIZE - access_width)

        # Generate aligned offset
        max_count = max_safe_offset // alignment
        offset = random.randint(0, max_count) * alignment

        return offset

    @staticmethod
    def get_safe_offset_for_rs1p(instr_name, imm_type):
        """
        Generate a safe offset for compressed RS1_P-based memory operations.

        The generator emits a local prelude that sets RS1_P to
        mem_region + MEM_REGION_RANDOM_START.  Offsets are therefore generated
        as non-negative values that keep the full access inside the randomized
        T6-accessible window.
        """
        access_width = MemoryAccessManager.ACCESS_WIDTH.get(instr_name, 4)
        max_value = MemoryAccessManager.IMMEDIATE_MAX.get(imm_type, 127)
        alignment = MemoryAccessManager.IMMEDIATE_ALIGNMENT.get(imm_type) or access_width or 1
        max_safe_offset = min(
            max_value,
            MemoryAccessManager.MEM_REGION_RANDOM_SIZE - access_width,
        )
        max_count = max_safe_offset // alignment
        return random.randint(0, max_count) * alignment

    @staticmethod
    def get_rs1p_base_delta():
        """
        Return delta from T6 to the start of the randomized mem_region window.
        """
        return MemoryAccessManager.MEM_REGION_RANDOM_START - MemoryAccessManager.MEM_REGION_CENTER

    @staticmethod
    def get_rs1p_base_setup(base_reg):
        """
        Emit setup for RS1_P compressed memory bases using T6 as a stable anchor.
        """
        return f"addi {base_reg}, t6, {MemoryAccessManager.get_rs1p_base_delta()}"

    @staticmethod
    def get_sp_base_setup():
        """
        Emit setup for compressed SP memory operations.

        c.*sp immediates are unsigned positive offsets, so sp must point to the
        start of the stack access region rather than stack_end.
        """
        return f"la sp, {MemoryAccessManager.STACK_REGION_LABEL}"

    @staticmethod
    def get_template_initialization():
        """
        Get assembly code snippets for initializing T6 and SP.

        Returns:
            List of assembly instruction strings
        """
        return [
            "la t6, mem_region",
            "addi t6, t6, 4096",
            f"la sp, {MemoryAccessManager.STACK_REGION_LABEL}"
        ]

    @staticmethod
    def get_data_section_definitions():
        """
        Get assembly code for defining memory regions in data section.

        Returns:
            List of assembly directive strings
        """
        return [
            ".section .mem_region,\"aw\",@progbits",
            ".align 4",
            "mem_region:",
            f".space {MemoryAccessManager.MEM_REGION_SIZE}",
            "mem_region_end:",
            "",
            ".section .stack_region,\"aw\",@progbits",
            ".align 4",
            f"{MemoryAccessManager.STACK_REGION_LABEL}:",
            f".space {MemoryAccessManager.STACK_SIZE}",
            "stack_region_end:"
        ]
