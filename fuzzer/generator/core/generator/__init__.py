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
import time
from concurrent.futures import ProcessPoolExecutor, as_completed, TimeoutError
from tqdm import tqdm
from .generate_instrs import generate_instructions
from ...asm_template_manager.riscv_asm_syntex import ArchConfig

# Performance timing support
PERF_ENABLED = os.environ.get("DIVEFUZZ_PERF_ENABLE", "0") == "1"


def generate_instructions_parallel(instr_number: int,
                                   seed_times: int,
                                   eliminate_enable: bool,
                                   is_cva6: bool,
                                   is_rv32: bool,
                                   max_workers: int,
                                   arch: ArchConfig,
                                   template_type: str):
    """
    Generate random RISC-V instructions in parallel across multiple processes.

    Each process creates its own template instance with random type and values,
    ensuring each seed gets independent random content.

    Args:
        instr_number: Number of instructions per seed
        seed_times: Number of seeds to generate
        eliminate_enable: Enable conflict elimination via Spike
        is_cva6: Target CVA6 processor
        is_rv32: Use RV32 architecture
        max_workers: Maximum number of parallel processes
        arch: Architecture configuration for template creation
    """
    resolve_duplicates = 0
    resolve_duplicates_fail = 0
    timeout_count = 0

    # The timeout period = the number of instructions * 0.8 seconds
    timeout_seconds = instr_number * 0.8
    # Maximum retry count to prevent unlimited retries
    max_retries = 5

    print("---Start generate instrs---")
    print(f"# Timeout per seed: {timeout_seconds}s")

    # The list of seed indexes to be generated
    pending_seeds = list(range(seed_times))
    completed_count = 0
    retry_round = 0
    # Aggregate time from all workers (cumulative, needs normalization)
    # spike = spike.debug_cmd_str_elf_file time, compile = generate_elf time
    total_spike_time = 0.0
    total_compile_time = 0.0

    # Time the instruction generation phase (includes spike execution in subprocesses)
    gen_start = time.perf_counter()

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        while pending_seeds and retry_round < max_retries:
            if retry_round > 0:
                print(f"# Retry round {retry_round}/{max_retries} for {len(pending_seeds)} timed out seeds")


            futures = {}
            for seed_idx in pending_seeds:
                future = executor.submit(
                    generate_instructions,
                    instr_number,
                    seed_idx,
                    eliminate_enable,
                    is_cva6,
                    is_rv32,
                    arch,
                    template_type
                )
                futures[future] = seed_idx

            # Clear the pending list and get ready to collect the failed tasks
            pending_seeds = []

            # collect results
            for future in tqdm(as_completed(futures), total=len(futures),
                             desc="# Generating instructions"):
                seed_idx = futures[future]
                try:
                    result1, result2, spike_time, compile_time = future.result(timeout=timeout_seconds)
                    resolve_duplicates += result1
                    resolve_duplicates_fail += result2
                    total_spike_time += spike_time
                    total_compile_time += compile_time
                    completed_count += 1
                except TimeoutError:
                    timeout_count += 1
                    print(f"# Seed {seed_idx} timed out ({timeout_seconds}s)")
                    pending_seeds.append(seed_idx)
                except Exception as e:
                    print(f"# Error generating seed {seed_idx}: {e}")

            retry_round += 1

        if pending_seeds:
            print(f"# {len(pending_seeds)} seeds failed after {max_retries} retry rounds, skipping")

    perf_gen_time = time.perf_counter() - gen_start

    print(f"# Successfully generated: {completed_count}/{seed_times} seeds")
    print(f"# Total timeouts: {timeout_count}")
    print(f"# Total conflict avoidances: {resolve_duplicates}")
    print(f"# Total failed conflict avoidances: {resolve_duplicates_fail}")

    # Report timing to global performance timer if enabled
    if PERF_ENABLED:
        try:
            # Use absolute import to avoid relative import issues
            from utils.performance_timer import perf_timer

            # When using parallel workers, spike/compile times are cumulative (sum of all workers)
            # but perf_gen_time is wall-clock time. We need to normalize.
            # Wall-clock time ≈ cumulative time / effective_workers
            if completed_count > 0:
                effective_workers = min(max_workers, completed_count)

                # Calculate wall-clock time for spike and compile
                # spike = spike.debug_cmd_str_elf_file, compile = generate_elf
                wall_spike_time = total_spike_time / effective_workers
                wall_compile_time = total_compile_time / effective_workers

                # Ensure spike + compile time doesn't exceed total generation time
                combined_time = wall_spike_time + wall_compile_time
                if combined_time > perf_gen_time * 0.95:
                    # Scale down proportionally
                    scale = (perf_gen_time * 0.95) / combined_time
                    wall_spike_time *= scale
                    wall_compile_time *= scale

                # Instruction generation time = total - spike - compile
                instr_gen_only = perf_gen_time - wall_spike_time - wall_compile_time
                instr_gen_only = max(0.0, instr_gen_only)  # Ensure non-negative
            else:
                wall_spike_time = 0.0
                wall_compile_time = 0.0
                instr_gen_only = perf_gen_time

            # Report 3 phases: instruction_gen, spike_execution, compilation
            perf_timer.add_time(perf_timer.PHASE_INSTRUCTION_GEN, instr_gen_only)
            perf_timer.add_time(perf_timer.PHASE_SPIKE_EXECUTION, wall_spike_time)
            perf_timer.add_time(perf_timer.PHASE_COMPILATION, wall_compile_time)
        except ImportError as e:
            print(f"[PerfTimer] Import error in generator: {e}")
        except Exception as e:
            print(f"[PerfTimer] Error adding time in generator: {e}")
