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

import os
from pathlib import Path
from typing import Tuple, Optional
from ..bug_filter import bug_filter
from ..utils import list2str
from ..utils.phase_profiler import phase
from ..utils import candidate_timing
from ..asm_template_manager import TemplateInstance
from .instruction_parser import InstructionParser
from .spike_resolution import Spike
from .xor_cache_sqlite import check_and_add as exact_check_and_add


def _resolve_xor_cache_dir(xor_cache_dir: Optional[str]) -> Path:
    """Return the directory that stores per-opcode XOR history files."""

    return Path(xor_cache_dir or "spike_resolution")

def _engine_read_sources(instr_info, engine):
    """Read candidate source registers from the live engine session.

    Mirrors Spike.get_registers_values return semantics exactly: None when
    there is nothing to read, immediate appended last when present.
    """
    source_regs = InstructionParser.get_source_registers(instr_info)
    if source_regs is None or len(source_regs) == 0:
        return [instr_info.imm] if instr_info.imm is not None else None
    float_register = InstructionParser.is_float_instruction(instr_info)
    values = []
    for r in source_regs:
        # The legacy debugger reads registers after executing the synthetic
        # `li t5,0x2727272727` end marker. Mirror that side effect for
        # candidates whose source is t5 (x30).
        v = 0x2727272727 if not float_register and r in ("t5", "x30") else engine.read_register(r, float_register=float_register)
        if v is None:
            return None
        values.append(v)
    if instr_info.imm is not None:
        values.append(instr_info.imm)
    return values



def temp_asm_to_debug_generate(updated_content: Tuple[str], instr: str, is_first: bool, label: Optional[str],
                                template: TemplateInstance, xor_cache_dir: Optional[str] = None,
                                engine=None, machine_code=None, execute: bool = True):
    """
    Debug-generate assembly and verify via Spike simulation.

    Args:
        updated_content: Tuple of existing instructions
        instr: New instruction to add
        is_first: Whether this is the first instruction
        label: Optional label for jump targets
        template: Template instance for wrapping content
    Returns:
        result_code: 1 if new unique value found, 0 if duplicate, 3 if error

    When per-candidate timing is enabled (DIVEFUZZ_CANDIDATE_TIMING_DIR),
    each attempt emits one record.  ``position`` is the accepted prefix
    length; the replay-based evaluation components (materialization,
    compile, replay, cleanup) are attached by ``Spike.get_registers_values``
    via ``candidate_timing.record_extra``.
    """
    candidate_timing.note_position(len(updated_content))
    timer = candidate_timing.start_attempt()

    def _finish(result_code: int, stage: Optional[str]) -> int:
        candidate_timing.finish_attempt(
            timer,
            accepted=result_code == 1,
            rejected_stage=stage,
            op_name=op_name,
            prefix_len=len(updated_content),
            n_source_values=n_source_values,
        )
        return result_code

    op_name = instr.split()[0] if instr.split() else None
    n_source_values = None

    with phase("prefix_materialization"):
        # parse instruction
        instr_processed, instr_info = InstructionParser.parse_instruction(instr)
        if timer:
            timer.mark("t_parse")
        if instr_info is None: # Unsupported instruction type
            return _finish(3, "parse")
        op_name = instr_info.op_name

        # first time to look up RSx value
        instr_payload_str = list2str(updated_content)
        if is_first:
            if label is not None:
                instr_payload_str += '\n' + instr_processed + '\n' + f'{label}:' + '\n  li t5,0x2727272727\n'
            else:
                instr_payload_str += '\n' + instr_processed + '\n  li t5,0x2727272727\n'
    if timer:
        timer.mark("t_payload")

    # Get register values: fast engine path (checkpoint/inject/read) or
    # legacy full-recompile replay.  Both must return identical value lists.
    if engine is not None and engine.initialized:
        try:
            if execute:
                if machine_code is None:
                    return _finish(3, "encode")
                engine.set_checkpoint()
                engine.execute_one(machine_code)
            register_values = _engine_read_sources(instr_info, engine)
        except Exception:
            try:
                if execute:
                    engine.rollback()
            except Exception:
                pass
            return _finish(3, "engine")
        if register_values is None:
            if execute:
                engine.rollback()
            return _finish(3, "eval")
    else:
        register_values = Spike.get_registers_values(instr_info, instr_payload_str, template)
    if timer:
        timer.mark("t_eval")
    if register_values is None:
        return _finish(3, "eval")
    n_source_values = len(register_values)

    bug_name = bug_filter.filter_known_bug(instr_info.op_name, register_values)
    if timer:
        timer.mark("t_bug_filter")
    if bug_name is not None:
        print(bug_name)
        if engine is not None and engine.initialized and execute:
            try:
                engine.rollback()
            except Exception:
                pass
        return _finish(3, "bug_filter")

    # Calculates the XOR value and returns it

    with phase("xor_dedup_io"):
        xor_stderr = Spike.xor_register_values(register_values)

        resolution_dir = _resolve_xor_cache_dir(xor_cache_dir)
        os.makedirs(resolution_dir, exist_ok=True)
        if engine is not None and engine.initialized:
            # Same opcode/XOR key and acceptance rule as legacy text files;
            # the unique index makes concurrent decisions atomic and avoids
            # rereading an ever-growing file for every candidate.
            if exact_check_and_add(resolution_dir, instr_info.op_name, xor_stderr):
                if timer:
                    timer.mark("t_xor_io")
                return _finish(1, None)
            if timer:
                timer.mark("t_xor_io")
            if execute:
                engine.rollback()
            return _finish(0, "dedup")
        xor_file_path = os.path.join(resolution_dir, f"{instr_info.op_name}_xor_values.txt")

        try:
            with open(xor_file_path, "r+") as file:
                existing_values = set(file.read().splitlines())
                if str(xor_stderr) not in existing_values:
                    file.write(f"{xor_stderr}\n")
                    if timer:
                        timer.mark("t_xor_io")
                    return _finish(1, None)
        except FileNotFoundError:
            with open(xor_file_path, "w") as file:
                file.write(f"{xor_stderr}\n")
            if timer:
                timer.mark("t_xor_io")
            return _finish(1, None)

    if timer:
        timer.mark("t_xor_io")
    if engine is not None and engine.initialized and execute:
        try:
            engine.rollback()
        except Exception:
            pass
    return _finish(0, "dedup")

def temp_asm_to_debug(updated_content: Tuple[str], instr: str, template: TemplateInstance,
                      is_first: bool = False, xor_cache_dir: Optional[str] = None):
    with phase("prefix_materialization"):
        # parse instruction
        instr_processed, instr_info = InstructionParser.parse_instruction(instr)
        if instr_info is None: # Unsupported instruction type
            return 3

        # first time to look up RSx value
        instr_payload_str = list2str(updated_content)
        if is_first:
            instr_payload_str += '\n' + instr_processed + '\n  li t5,0x2727272727\n'
    
    # Get register values by spike
    register_values = Spike.get_registers_values(instr_info, instr_payload_str, template)
    if register_values is None:
        return 3

    with phase("xor_dedup_io"):
        xor_value = Spike.xor_register_values(register_values)
        # Parsing the directory
        resolution_dir = _resolve_xor_cache_dir(xor_cache_dir)
        os.makedirs(resolution_dir, exist_ok=True)
        xor_file_path = os.path.join(resolution_dir, f"{instr_info.op_name}_xor_values.txt")
        # Check if the file exists and read its contents
        if os.path.exists(xor_file_path):
            with open(xor_file_path, "r") as file:
                existing_values = file.read().splitlines()
                # Check if the value already exists
                if str(xor_value) in existing_values:
                    return 0  # Value already exists
        
        # The value does not exist, add it to the file
        with open(xor_file_path, "a") as file:
            file.write(f"{xor_value}\n")
    
    return 1  # Value added
