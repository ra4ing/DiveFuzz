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
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from tqdm import tqdm  # pyright: ignore[reportMissingModuleSource]
from .generate_instrs import generate_instructions
from ...asm_template_manager.riscv_asm_syntex import ArchConfig
from ...reg_analyzer.stateful_xor_cache import StatefulXORCache


def _terminate_executor_workers(executor: ProcessPoolExecutor):
    """
    Terminate running worker processes after a generation timeout.

    ProcessPoolExecutor.cancel() only affects tasks that have not started.  A
    timed-out generator task may still be running inside a worker, so terminate
    those workers before creating a fresh executor for retry isolation.
    """
    processes = getattr(executor, "_processes", None)
    if not processes:
        return

    for process in processes.values():
        if process.is_alive():
            process.terminate()

    for process in processes.values():
        process.join(timeout=0.2)

    for process in processes.values():
        if process.is_alive():
            process.kill()

    for process in processes.values():
        process.join(timeout=0.2)


def generate_instructions_parallel(
    instr_number: int,
    seed_times: int,
    eliminate_enable: bool,
    is_rv32: bool,
    max_workers: int,
    arch: ArchConfig,
    template_type: str,
    out_dir: str = "out-seeds-2025-test",
    architecture: str = "xs",
    debug_config: dict | None = None,
    stateful_xor_cache: bool = True,
    bug_filter_enable: bool = True,
    jump_enable: bool = True,
    xor_cache_expected_seeds: int | None = None,
    seed_offset: int = 0,
    clean_cache: bool = False,
):
    """
    Generate random RISC-V instructions in parallel across multiple processes.

    Each process creates its own template instance with random type and values,
    ensuring each seed gets independent random content.

    Uses shared memory XORCache for cross-process duplicate elimination with
    Bloom Filter.

    Args:
        instr_number: Number of instructions per seed
        seed_times: Number of seeds to generate
        eliminate_enable: Enable conflict elimination via Spike
        is_rv32: Use RV32 architecture
        max_workers: Maximum number of parallel processes
        arch: Architecture configuration for template creation
        template_type: Template type name
        out_dir: Output directory for seeds
        architecture: Architecture for bug filtering ('xs', 'nts', 'rkt', 'kmh')
        debug_config: Debug configuration dict with keys:
            - enabled: bool - Enable debug mode
            - output_dir: str - Debug output directory
            - mode: str - 'FULL', 'DIFF', or 'SUMMARY'
            - accepted_only: bool - Only log ACCEPTED instructions
            - log_csr: bool - Log CSR values
            - log_fpr: bool - Log FPR values
    """
    resolve_duplicates = 0
    resolve_duplicates_fail = 0
    timeout_count = 0

    timeout_scale = float(os.environ.get("ASTRAFUZZ_TIMEOUT_SCALE", "0.3"))
    timeout_min_seconds = float(os.environ.get("ASTRAFUZZ_TIMEOUT_MIN", "3.0"))
    timeout_seconds = max(instr_number * timeout_scale, timeout_min_seconds)
    # Maximum retry count to prevent unlimited retries
    max_retries = 5

    print("---Start generate instrs---")
    print(f"# Timeout per seed: {timeout_seconds}s")

    # Create shared XORCache for cross-process duplicate elimination
    # Uses shared memory Bloom Filter with optional file persistence
    xor_cache = None
    xor_cache_state = None
    cache_file = os.path.join(out_dir, "xor_cache.bloom")

    if eliminate_enable:
        # Ensure output directory exists
        os.makedirs(out_dir, exist_ok=True)

        cache_seed_count = xor_cache_expected_seeds or seed_times
        if cache_seed_count <= 0:
            cache_seed_count = seed_times

        use_stateful = stateful_xor_cache
        if use_stateful:
            xor_cache = StatefulXORCache.create_for_workload(
                num_seeds=cache_seed_count,
                instrs_per_seed=instr_number,
                false_positive_rate=0.01,
            )
        else:
            # 延迟导入以避免导入链对启动时间或依赖检查的影响
            from ...reg_analyzer.xor_cache import XORCache

            xor_cache = XORCache.create_for_workload(
                num_seeds=cache_seed_count,
                instrs_per_seed=instr_number,
                false_positive_rate=0.01,
            )
        xor_cache.create()

        # Remove existing cache if clean_cache is set (fresh start)
        if clean_cache and os.path.exists(cache_file):
            os.remove(cache_file)

        # Load existing cache if available (for incremental fuzzing)
        if os.path.exists(cache_file):
            try:
                xor_cache.load(cache_file)
            except Exception as e:
                print(f"# Error: Failed to load XOR cache from {cache_file}: {e}")
                print(f"# Please delete the file or fix the issue before continuing.")
                xor_cache.cleanup()
                raise RuntimeError(f"Failed to load XOR cache: {e}")
        xor_cache_state = xor_cache.get_state_for_worker()

    # Ensure xor_cache_state is a dict when passed to worker functions
    xor_cache_state = xor_cache_state or {}

    try:
        pending_seeds = list(range(seed_offset, seed_offset + seed_times))
        completed_count = 0
        retry_round = 0

        while pending_seeds and retry_round < max_retries:
            if retry_round > 0:
                print(
                    f"# Retry round {retry_round}/{max_retries} for {len(pending_seeds)} timed out seeds"
                )

            retry_seeds = []
            executor = ProcessPoolExecutor(max_workers=max_workers)
            futures = {}
            seed_deadlines = {}
            force_terminate_workers = False

            def _submit(seed_idx: int):
                """Submit a seed and record its per-seed deadline."""
                future = executor.submit(
                    generate_instructions,
                    instr_number,
                    seed_idx,
                    eliminate_enable,
                    is_rv32,
                    arch,
                    template_type,
                    out_dir,
                    xor_cache_state,
                    use_stateful_cache=stateful_xor_cache,
                    architecture=architecture,
                    debug_config=debug_config,
                    bug_filter_enable=bug_filter_enable,
                    jump_enable=jump_enable,
                )
                futures[future] = seed_idx
                seed_deadlines[future] = time.monotonic() + timeout_seconds
                return future

            initial_seeds = pending_seeds[:max_workers]
            remaining_queue = list(pending_seeds[max_workers:])
            for seed_idx in initial_seeds:
                _submit(seed_idx)

            progress = tqdm(
                total=len(pending_seeds),
                desc="# Generating instructions",
            )

            try:
                while futures:
                    earliest_deadline = min(seed_deadlines[f] for f in futures)
                    remaining_time = max(earliest_deadline - time.monotonic(), 0.1)

                    done, _ = wait(
                        futures,
                        timeout=remaining_time,
                        return_when=FIRST_COMPLETED,
                    )

                    now = time.monotonic()

                    if not done:
                        timed_out_futures = [
                            f for f in list(futures)
                            if seed_deadlines.get(f, float("inf")) <= now
                        ]
                        if timed_out_futures:
                            force_terminate_workers = True
                        for future in timed_out_futures:
                            seed_idx = futures.pop(future)
                            seed_deadlines.pop(future, None)
                            future.cancel()
                            timeout_count += 1
                            retry_seeds.append(seed_idx)
                            print(
                                f"# Seed {seed_idx} timed out ({timeout_seconds}s)"
                            )
                            progress.update(1)
                            if remaining_queue:
                                _submit(remaining_queue.pop(0))
                        continue

                    for future in done:
                        seed_idx = futures.pop(future)
                        seed_deadlines.pop(future, None)
                        try:
                            result1, result2 = future.result()
                            resolve_duplicates += result1
                            resolve_duplicates_fail += result2
                            completed_count += 1
                        except Exception as e:
                            print(f"# Error generating seed {seed_idx}: {e}")
                        progress.update(1)
                        if remaining_queue:
                            _submit(remaining_queue.pop(0))
            finally:
                if futures:
                    force_terminate_workers = True
                    for future in list(futures):
                        seed_idx = futures.pop(future)
                        future.cancel()
                        retry_seeds.append(seed_idx)

                if force_terminate_workers:
                    _terminate_executor_workers(executor)
                    executor.shutdown(wait=False, cancel_futures=True)
                else:
                    executor.shutdown(wait=True)
                progress.close()

            pending_seeds = retry_seeds
            retry_round += 1

        if pending_seeds:
            print(
                f"# {len(pending_seeds)} seeds failed after {max_retries} retry rounds, skipping"
            )

        print(f"# Successfully generated: {completed_count}/{seed_times} seeds")
        print(f"# Total timeouts: {timeout_count}")
        print(f"# Total conflict avoidances: {resolve_duplicates}")
        print(f"# Total failed conflict avoidances: {resolve_duplicates_fail}")

    finally:
        # Save and cleanup shared XORCache
        if xor_cache is not None:
            try:
                xor_cache.save(cache_file)
            except Exception:
                pass
            xor_cache.cleanup()
