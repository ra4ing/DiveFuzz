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
import shutil
import signal
import time
from pathlib import Path
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from tqdm import tqdm  # pyright: ignore[reportMissingModuleSource]
from .generate_instrs import generate_instructions
from ...asm_template_manager.riscv_asm_syntex import ArchConfig
from ...reg_analyzer.xor_cache_sqlite import prepare as prepare_exact_cache


def _process_children(pid: int) -> list[int]:
    """Return direct child PIDs for a process by scanning /proc."""

    children = []
    proc_root = Path("/proc")
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        stat_path = entry / "stat"
        try:
            stat = stat_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        right_paren = stat.rfind(")")
        if right_paren == -1:
            continue
        fields = stat[right_paren + 2:].split()
        if len(fields) < 2:
            continue
        try:
            parent_pid = int(fields[1])
        except ValueError:
            continue
        if parent_pid == pid:
            children.append(int(entry.name))
    return children


def _process_descendants(pid: int) -> list[int]:
    """Return descendant PIDs deepest-first so child tools die with a timed-out worker."""

    descendants = []
    stack = _process_children(pid)
    while stack:
        child = stack.pop()
        descendants.append(child)
        stack.extend(_process_children(child))
    descendants.reverse()
    return descendants


def _terminate_executor_workers(executor: ProcessPoolExecutor):
    """
    Terminate running worker processes after a generation timeout.

    DiveFuzzTest workers can be blocked inside spike_wrapper, which launches
    shell/spike child processes.  Kill descendants first, then the worker, so a
    timed-out seed cannot leave an orphaned spike consuming CPU forever.
    """

    processes = getattr(executor, "_processes", None)
    if not processes:
        return

    for process in processes.values():
        if not process.is_alive():
            continue
        for child_pid in _process_descendants(process.pid):
            try:
                os.kill(child_pid, signal.SIGTERM)
            except OSError:
                pass
        process.terminate()

    time.sleep(0.2)

    for process in processes.values():
        if process.is_alive():
            for child_pid in _process_descendants(process.pid):
                try:
                    os.kill(child_pid, signal.SIGKILL)
                except OSError:
                    pass
            process.kill()

    for process in processes.values():
        process.join(timeout=1)


def generate_instructions_parallel(instr_number: int,
                                   seed_times: int,
                                   eliminate_enable: bool,
                                   is_cva6: bool,
                                   is_rv32: bool,
                                   max_workers: int,
                                   arch: ArchConfig,
                                    template_type: str,
                                    out_dir: str | None = None,
                                    xor_cache_dir: Path | None = None,
                                    xor_cache_mode: str = 'preserve',
                                    export_difuzz_si: bool = False,
                                    difuzz_si_dir: str | None = None,
                                    difuzz_si_template: str = 'p-m'):
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

    timeout_scale = float(os.environ.get("DIVEFUZZ_TIMEOUT_SCALE", "0.12"))
    timeout_seconds = instr_number * timeout_scale
    # Maximum retry count to prevent unlimited retries
    max_retries = 5

    print("---Start generate instrs---")
    print(f"# Timeout per seed: {timeout_seconds}s")

    if eliminate_enable and xor_cache_dir is not None:
        if xor_cache_mode == 'reset' and xor_cache_dir.exists():
            shutil.rmtree(xor_cache_dir)
        xor_cache_dir.mkdir(parents=True, exist_ok=True)
    if eliminate_enable and os.environ.get("DFT_FAST_ENGINE") == "1":
        prepare_exact_cache(Path(xor_cache_dir or "spike_resolution"))

    pending_seeds = list(range(seed_times))
    completed_count = 0
    retry_round = 0

    while pending_seeds and retry_round < max_retries:
        if retry_round > 0:
            print(f"# Retry round {retry_round}/{max_retries} for {len(pending_seeds)} timed out seeds")

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
                is_cva6,
                is_rv32,
                arch,
                template_type,
                out_dir=out_dir,
                xor_cache_dir=str(xor_cache_dir) if xor_cache_dir is not None else None,
                export_difuzz_si=export_difuzz_si,
                difuzz_si_dir=difuzz_si_dir,
                difuzz_si_template=difuzz_si_template,
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
                        f for f in futures if seed_deadlines[f] <= now
                    ]
                    if not timed_out_futures:
                        continue
                    # A timed-out worker remains in its ProcessPool slot
                    # until killed. Submitting another seed to that pool
                    # queues it behind the hang and starts its deadline
                    # before it can run. Terminate this pool now and retry
                    # every unfinished/queued seed in a fresh pool.
                    force_terminate_workers = True
                    for future in timed_out_futures:
                        seed_idx = futures.pop(future)
                        seed_deadlines.pop(future)
                        future.cancel()
                        timeout_count += 1
                        retry_seeds.append(seed_idx)
                        print(f"# Seed {seed_idx} timed out ({timeout_seconds}s)")
                        progress.update(1)
                    retry_seeds.extend(remaining_queue)
                    remaining_queue.clear()
                    break

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
                        retry_seeds.append(seed_idx)
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
            retry_seeds.extend(remaining_queue)
            remaining_queue.clear()

            if force_terminate_workers:
                _terminate_executor_workers(executor)
                executor.shutdown(wait=False, cancel_futures=True)
            else:
                executor.shutdown(wait=True)
            progress.close()

        pending_seeds = retry_seeds
        retry_round += 1

    if pending_seeds:
        print(f"# {len(pending_seeds)} seeds failed after {max_retries} retry rounds, skipping")

    print(f"# Successfully generated: {completed_count}/{seed_times} seeds")
    print(f"# Total timeouts: {timeout_count}")
    print(f"# Total conflict avoidances: {resolve_duplicates}")
    print(f"# Total failed conflict avoidances: {resolve_duplicates_fail}")
