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

"""Archive non-success multicore results for later replay/reduction.

A successful result is a no-op. Any other result is copied (with its run log,
ELF, litmus, model, allowed/observed outcomes, manifest) into a timestamped
``multicore_bugs_<ts>/<seed>/`` directory alongside an ``oracle_report.json``.
"""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from utils.results_reporter import ResultType, TestResult


def _safe_name(name: str) -> str:
    return name.replace(" ", "_").replace(os.sep, "_")


def archive_multicore_result(
    result: TestResult, output_base_dir: str = "outputs"
) -> None:
    """Archive ``result`` if it is not a SUCCESS; otherwise do nothing."""
    if result.result_type == ResultType.SUCCESS:
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dir = (
        Path(output_base_dir)
        / f"multicore_bugs_{timestamp}"
        / _safe_name(result.seed_name)
    )
    archive_dir.mkdir(parents=True, exist_ok=True)

    artifacts = result.artifacts or {}

    # Build (source, destination-name) candidates from the seed dir + artifacts.
    candidates: list[tuple[Path, str]] = []
    manifest = artifacts.get("manifest")
    seed_dir = Path(manifest).parent if manifest else None
    if seed_dir is not None:
        candidates.append((seed_dir / "seed.mc.json", "seed.mc.json"))
        candidates.append((seed_dir / "seed.litmus", "seed.litmus"))
        candidates.append((seed_dir / "manifest.json", "manifest.json"))
    if artifacts.get("allowed_outcomes"):
        candidates.append((Path(artifacts["allowed_outcomes"]), "allowed_outcomes.json"))
    if artifacts.get("histogram"):
        candidates.append((Path(artifacts["histogram"]), "observed_histogram.json"))
    if result.seed_path:
        candidates.append((Path(result.seed_path), "seed.elf"))
    if result.log_path:
        candidates.append((Path(result.log_path), Path(result.log_path).name))

    for src, dst_name in candidates:
        if src.exists():
            shutil.copy2(src, archive_dir / dst_name)

    report = {
        "result_type": result.result_type.name,
        "summary": result.summary,
        "dut_name": result.dut_name,
        "version": result.version,
        "diff_ref": result.diff_ref,
        "seed_name": result.seed_name,
        "seed_path": result.seed_path,
        "artifacts": result.artifacts,
    }
    (archive_dir / "oracle_report.json").write_text(json.dumps(report, indent=2))
