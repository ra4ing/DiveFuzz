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

"""XiangShan multicore runner + the ``run_multicore_test`` entry point.

Reuses the existing single-core subprocess convention (``cmd.replace('$1', ...)``)
and the ``create_test_logger`` harness. For each bundle it runs the ELF
``runs_per_seed`` times, aggregates the parsed outcome histogram, and classifies
against the RVWMO/herd allowed set.
"""

import json
import os
import logging
import subprocess
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from config.logger_config import create_test_logger
import time
import select
import pty
from config.dut_config import DUTTarget, MultiCoreSeedConfig
from utils.results_reporter import TestResult, ResultType
from generator.core.multicore.generate import (
    MultiCoreGenerationConfig,
    generate_multicore_seeds,
)
from generator.core.multicore.litmus_backend import SeedBundle
from generator.core.multicore.outcome import (
    parse_litmus_histogram,
    canonical_outcome,
)

from .oracle import classify_outcomes
from .archive import archive_multicore_result


@dataclass
class MultiCoreRunResult:
    """Detailed per-bundle run diagnostics (one logical run of the ELF)."""

    bundle: SeedBundle
    run_id: int
    returncode: int | None
    timed_out: bool
    stdout: str
    log_path: str
    outcome_histogram: Counter[tuple[tuple[str, int], ...]]
    result_type: ResultType
    summary: str


def _load_allowed(allowed_path) -> set[tuple[tuple[str, int], ...]]:
    """Read ``allowed_outcomes.json`` back into a set of canonical outcomes."""
    data = json.loads(Path(allowed_path).read_text())
    return {canonical_outcome(d) for d in data}


class XiangShanMultiCoreRunner:
    """Run a litmus7-compatible multicore ELF on XiangShan repeatedly."""

    def __init__(self, dut_config: DUTTarget, config_filename: str):
        self.dut_config = dut_config
        self.config_filename = config_filename

    def _run_once(self, command, seed_logger):
        """Run one DUT invocation, capturing output via a PTY.

        The litmus7 harness prints an ``Observation`` line when the test
        completes; spike then hangs (it does not self-exit). A PTY is used so
        the child sees a terminal and line-buffers its output, letting us detect
        ``Observation`` immediately and terminate spike instead of waiting for a
        pipe buffer flush or the full timeout. A ``select`` loop still enforces
        the deadline for a no-output hang.

        Returns ``(stdout, saw_observation, hard_timeout)``.
        """
        master_fd, slave_fd = pty.openpty()
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=self.dut_config.emu_path,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
        )
        os.close(slave_fd)  # only the child keeps the slave end

        parts: list[str] = []
        saw_observation = False
        hard_timeout = False
        deadline = time.monotonic() + self.dut_config.timeout
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    hard_timeout = True
                    break
                ready, _, _ = select.select([master_fd], [], [], min(remaining, 0.5))
                if not ready:
                    if proc.poll() is not None:
                        break  # process exited; no more output
                    continue
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError:
                    break  # master closed (child exited)
                if not chunk:
                    break  # EOF
                text = chunk.decode("utf-8", "replace")
                parts.append(text)
                if "Observation" in text:
                    saw_observation = True
                    break
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            # Drain any remaining data flushed as the child terminates.
            try:
                while True:
                    ready, _, _ = select.select([master_fd], [], [], 0.1)
                    if not ready:
                        break
                    chunk = os.read(master_fd, 4096)
                    if not chunk:
                        break
                    parts.append(chunk.decode("utf-8", "replace"))
            except OSError:
                pass
            os.close(master_fd)
        return "".join(parts), saw_observation, hard_timeout

    def run_bundle(
        self,
        bundle: SeedBundle,
        runs_per_seed: int,
        allowed: set[tuple[tuple[str, int], ...]],
    ) -> TestResult:
        safe_name = bundle.name.replace(" ", "_").replace(os.sep, "_")
        with create_test_logger(
            test_name=safe_name,
            config_filename=self.config_filename,
        ) as (seed_logger, seed_log_path):
            elf_path = str(bundle.elf_path)
            command = self.dut_config.cmd.replace('$1', f'"{elf_path}"')
            seed_logger.info(f"Starting multicore seed: {bundle.name}")
            seed_logger.info(f"ELF: {elf_path}")
            seed_logger.info(f"Command: {command}")
            seed_logger.info(f"Working directory: {self.dut_config.emu_path}")

            aggregate: Counter[tuple[tuple[str, int], ...]] = Counter()
            any_timeout = False
            any_trap = False

            for run_id in range(runs_per_seed):
                seed_logger.info(f"==== RUN {run_id} BEGIN ====")
                stdout, saw_obs, hard_to = self._run_once(command, seed_logger)
                seed_logger.info(stdout)
                if "HIT BAD TRAP" in stdout or "ABORT" in stdout:
                    any_trap = True
                if saw_obs or parse_litmus_histogram(stdout):
                    aggregate += parse_litmus_histogram(stdout)
                elif hard_to:
                    any_timeout = True
                    seed_logger.error(
                        f"Run {run_id} produced no outcome "
                        f"(hard timeout after {self.dut_config.timeout}s)"
                    )
                seed_logger.info(f"==== RUN {run_id} END ====")

            # Classification: trap beats a histogram; a real histogram (even when
            # the simulator hangs after printing it, as spike does) beats a
            # timeout; otherwise a hard timeout with no outcome is TIMEOUT.
            if any_trap:
                result_type = ResultType.RUNTIME_TRAP
                summary = "Multicore seed hit a runtime trap (HIT BAD TRAP / ABORT)"
            elif aggregate:
                result_type, summary = classify_outcomes(allowed, aggregate)
            elif any_timeout:
                result_type = ResultType.TIMEOUT
                summary = f"Multicore seed timed out ({self.dut_config.timeout}s)"
            else:
                result_type, summary = classify_outcomes(allowed, aggregate)

            seed_logger.info(f"result_type={result_type.name}; {summary}")

            # Persist the aggregated observed histogram beside the seed manifest.
            hist_path = bundle.seed_dir / "observed_histogram.json"
            hist_data = [
                {"outcome": dict(outcome), "count": count}
                for outcome, count in sorted(aggregate.items())
            ]
            hist_path.write_text(json.dumps(hist_data, indent=2))

            return TestResult(
                dut_name=self.dut_config.name,
                version=self.dut_config.version,
                diff_ref=self.dut_config.diff_ref,
                seed_name=bundle.name,
                result_type=result_type,
                summary=summary,
                log_path=seed_log_path,
                seed_path=elf_path,
                artifacts={
                    "manifest": str(bundle.manifest_path),
                    "allowed_outcomes": str(bundle.allowed_path),
                    "histogram": str(hist_path),
                },
            )


def _mc_to_gen_config(mc) -> MultiCoreGenerationConfig:
    return MultiCoreGenerationConfig(
        seeds_output=mc.seeds_output,
        seeds_num=mc.seeds_num,
        seed_offset=mc.seed_offset,
        hart_count=mc.hart_count,
        test_families=mc.test_families,
        noise_level=mc.noise_level,
        herd_path=mc.herd_path,
        litmus_harness_dir=mc.litmus_harness_dir,
        litmus7_path=mc.litmus7_path,
        litmus7_share=mc.litmus7_share,
        litmus_runs=mc.litmus_runs,
        litmus_size=mc.litmus_size,
        build_executable=not mc.gen_only,
    )


def run_multicore_test(
    dut_config: DUTTarget,
    seed_config: MultiCoreSeedConfig,
    config_filename: str,
    global_logger: logging.Logger,
) -> list[TestResult]:
    """Generate multicore seeds and (unless gen_only) run them on the DUT."""
    mc = seed_config.multicore
    gen_config = _mc_to_gen_config(mc)
    bundles = generate_multicore_seeds(gen_config, logger=global_logger)

    if mc.gen_only:
        results = []
        for bundle in bundles:
            result = TestResult(
                dut_name=dut_config.name,
                version=dut_config.version,
                diff_ref=dut_config.diff_ref,
                seed_name=bundle.name,
                result_type=ResultType.SUCCESS,
                summary="Generated multicore seed only",
                log_path="",
                seed_path=str(bundle.litmus_path),
                artifacts={"manifest": str(bundle.manifest_path)},
            )
            archive_multicore_result(result)
            results.append(result)
        return results

    runner = XiangShanMultiCoreRunner(dut_config, config_filename)
    results: list[TestResult] = []
    with ThreadPoolExecutor(max_workers=mc.threads) as pool:
        futures = {}
        for bundle in bundles:
            allowed = _load_allowed(bundle.allowed_path)
            futures[
                pool.submit(runner.run_bundle, bundle, mc.runs_per_seed, allowed)
            ] = bundle
        for future in as_completed(futures):
            bundle = futures[future]
            try:
                result = future.result()
            except Exception as e:
                global_logger.exception(
                    f"Error running multicore seed {bundle.name}: {e}"
                )
                result = TestResult(
                    dut_name=dut_config.name,
                    version=dut_config.version,
                    diff_ref=dut_config.diff_ref,
                    seed_name=bundle.name,
                    result_type=ResultType.INFRA_ERROR,
                    summary=f"Infrastructure error: {e}",
                    log_path="",
                    seed_path=str(bundle.elf_path) if bundle.elf_path else None,
                    artifacts={"manifest": str(bundle.manifest_path)},
                )
            archive_multicore_result(result)
            results.append(result)
    return results
