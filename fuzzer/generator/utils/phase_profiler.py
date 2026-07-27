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

"""Lightweight phase profiler for generator worker processes."""

from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


_lock = threading.Lock()
_seconds: dict[str, float] = {}
_counts: dict[str, int] = {}
_metadata: dict[str, object] = {}


def enabled() -> bool:
    """Return whether phase profiling is enabled for this process."""

    return bool(os.environ.get("DIVEFUZZ_PHASE_PROFILE_DIR"))


def reset_phase_profile(tool: str, seed_index: int, instr_number: int) -> None:
    """Reset per-process profile state."""

    if not enabled():
        return
    with _lock:
        _seconds.clear()
        _counts.clear()
        _metadata.clear()
        _metadata.update(
            {
                "tool": tool,
                "seed_index": seed_index,
                "instr_number": instr_number,
                "pid": os.getpid(),
            }
        )


def add_phase_time(name: str, seconds: float) -> None:
    """Accumulate elapsed seconds for one phase."""

    if not enabled():
        return
    with _lock:
        _seconds[name] = _seconds.get(name, 0.0) + seconds
        _counts[name] = _counts.get(name, 0) + 1


@contextmanager
def phase(name: str) -> Iterator[None]:
    """Measure a phase when profiling is enabled."""

    if not enabled():
        yield
        return
    start = time.perf_counter()
    try:
        yield
    finally:
        add_phase_time(name, time.perf_counter() - start)


def write_phase_profile() -> None:
    """Write this worker's phase profile as JSON."""

    output_dir = os.environ.get("DIVEFUZZ_PHASE_PROFILE_DIR")
    if not output_dir:
        return
    with _lock:
        metadata = dict(_metadata)
        seconds = dict(_seconds)
        counts = dict(_counts)
    if not metadata:
        return
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    seed_index = metadata.get("seed_index", "unknown")
    pid = metadata.get("pid", os.getpid())
    output = path / f"phase_seed_{seed_index}_pid_{pid}.json"
    payload = {
        **metadata,
        "phase_seconds": seconds,
        "phase_counts": counts,
        "profile_total_seconds": sum(seconds.values()),
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
