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

"""Lightweight memory statistics collector for the memory profiling experiment.

Enabled by setting the ``DIVEFUZZ_MEMORY_STATS_DIR`` environment variable (same
pattern as the phase profiler).  Worker processes write a JSON file at the end
of generation with counters that help attribute memory to specific components.

Overhead: a handful of integer increments per instruction — negligible compared
to the instruction validation work itself.

Output file::

    $DIVEFUZZ_MEMORY_STATS_DIR/memory_stats_seed_<idx>_pid_<pid>.json

Collected counters:

- SpikeSession init RSS delta (via ``psutil``)
- checkpoint / rollback / confirm counts
- Bloom filter size and estimated fill
- XOR cache type
- candidate attempts vs accepted instructions
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Module state (per-process, zero overhead when disabled)
# ---------------------------------------------------------------------------

_enabled: bool | None = None
_stats: dict | None = None


def enabled() -> bool:
    """Return whether memory stats collection is active for this process."""
    global _enabled
    if _enabled is None:
        _enabled = bool(os.environ.get("DIVEFUZZ_MEMORY_STATS_DIR"))
    return _enabled


def _stats_dict() -> dict:
    global _stats
    if _stats is None:
        _stats = {
            # SpikeSession lifecycle
            "spike_init_rss_before": None,
            "spike_init_rss_after": None,
            "spike_init_rss_delta_bytes": None,
            # Checkpoint/rollback counters
            "checkpoint_count": 0,
            "rollback_count": 0,
            "confirm_count": 0,
            "engine_checkpoint_save_count": None,
            "engine_checkpoint_restore_count": None,
            "checkpoint_total_bytes": None,
            "checkpoint_gpr_bytes": None,
            "checkpoint_fpr_bytes": None,
            "checkpoint_csr_bytes": None,
            "checkpoint_csr_count": None,
            "checkpoint_memory_snapshot_bytes": None,
            "checkpoint_memory_region_bytes": None,
            "checkpoint_stack_region_bytes": None,
            "checkpoint_vector_total_bytes": None,
            "checkpoint_vector_regfile_bytes": None,
            "checkpoint_reservation_bytes": None,
            "checkpoint_privilege_bytes": None,
            # Bloom filter / XOR cache
            "bloom_filter_size_bytes": None,
            "bloom_filter_size_kb": None,
            "bloom_filter_num_hashes": None,
            "bloom_filter_inserted_count": None,
            "bloom_filter_duplicate_count": None,
            "bloom_filter_opcode_cache_entries": None,
            "bloom_filter_estimated_fp_rate": None,
            "xor_cache_type": None,
            "xor_cache_context_type": None,
            # Instruction generation
            "candidate_attempts": 0,
            "accepted_instructions": 0,
            # Metadata
            "pid": os.getpid(),
            "timestamp_start": time.time(),
            "timestamp_end": None,
            "seed_index": None,
            "instr_number": None,
        }
    return _stats


# ---------------------------------------------------------------------------
# Recording helpers
# ---------------------------------------------------------------------------

def record_spike_init_rss(phase: str) -> None:
    """Record RSS before or after SpikeSession initialization.

    Call with ``phase="before"`` before engine creation, ``"after"`` after.
    """
    if not enabled():
        return
    try:
        import psutil
        rss = psutil.Process(os.getpid()).memory_info().rss
    except Exception:
        return
    stats = _stats_dict()
    if phase == "before":
        stats["spike_init_rss_before"] = rss
    elif phase == "after":
        stats["spike_init_rss_after"] = rss
        before = stats["spike_init_rss_before"]
        if before is not None:
            stats["spike_init_rss_delta_bytes"] = rss - before


def record_checkpoint() -> None:
    if not enabled():
        return
    _stats_dict()["checkpoint_count"] += 1


def record_rollback() -> None:
    if not enabled():
        return
    _stats_dict()["rollback_count"] += 1


def record_confirm() -> None:
    if not enabled():
        return
    _stats_dict()["confirm_count"] += 1


def record_bloom_stats(
    size_bytes: int,
    num_hashes: int,
    inserted_count: int,
    cache_type: str,
    context_type: str | None = None,
    duplicate_count: int | None = None,
    opcode_cache_entries: int | None = None,
) -> None:
    """Record Bloom filter / XOR cache statistics."""
    if not enabled():
        return
    stats = _stats_dict()
    stats["bloom_filter_size_bytes"] = size_bytes
    stats["bloom_filter_size_kb"] = round(size_bytes / 1024, 2)
    stats["bloom_filter_num_hashes"] = num_hashes
    stats["bloom_filter_inserted_count"] = inserted_count
    stats["bloom_filter_duplicate_count"] = duplicate_count
    stats["bloom_filter_opcode_cache_entries"] = opcode_cache_entries
    stats["xor_cache_type"] = cache_type
    stats["xor_cache_context_type"] = context_type
    # Estimated FP rate: (1 - e^(-kn/m))^k
    if size_bytes > 0:
        import math
        m = size_bytes * 8  # bits
        k = num_hashes
        n = inserted_count
        if m > 0 and n > 0:
            exponent = -k * n / m
            stats["bloom_filter_estimated_fp_rate"] = round(
                (1 - math.exp(exponent)) ** k, 6
            )

def record_checkpoint_stats(stats_map: dict) -> None:
    """Record SpikeEngine checkpoint counters and byte breakdown."""
    if not enabled() or not stats_map:
        return
    stats = _stats_dict()
    key_map = {
        "save_count": "engine_checkpoint_save_count",
        "restore_count": "engine_checkpoint_restore_count",
        "total_bytes": "checkpoint_total_bytes",
        "gpr_bytes": "checkpoint_gpr_bytes",
        "fpr_bytes": "checkpoint_fpr_bytes",
        "csr_bytes": "checkpoint_csr_bytes",
        "csr_count": "checkpoint_csr_count",
        "memory_snapshot_bytes": "checkpoint_memory_snapshot_bytes",
        "memory_region_bytes": "checkpoint_memory_region_bytes",
        "stack_region_bytes": "checkpoint_stack_region_bytes",
        "vector_total_bytes": "checkpoint_vector_total_bytes",
        "vector_regfile_bytes": "checkpoint_vector_regfile_bytes",
        "reservation_bytes": "checkpoint_reservation_bytes",
        "privilege_bytes": "checkpoint_privilege_bytes",
    }
    for source_key, dest_key in key_map.items():
        value = stats_map.get(source_key)
        if value is not None:
            stats[dest_key] = int(value)


def record_attempt() -> None:
    if not enabled():
        return
    _stats_dict()["candidate_attempts"] += 1


def record_accepted() -> None:
    if not enabled():
        return
    _stats_dict()["accepted_instructions"] += 1


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_stats(seed_index: int, instr_number: int) -> None:
    """Write collected statistics to the configured output directory."""
    if not enabled():
        return
    output_dir = os.environ.get("DIVEFUZZ_MEMORY_STATS_DIR")
    if not output_dir:
        return
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    stats = _stats_dict()
    stats["timestamp_end"] = time.time()
    stats["seed_index"] = seed_index
    stats["instr_number"] = instr_number
    out_file = path / f"memory_stats_seed_{seed_index}_pid_{os.getpid()}.json"
    out_file.write_text(json.dumps(stats, indent=2, sort_keys=True), encoding="utf-8")


def reset_stats() -> None:
    """Reset all counters (called at the start of each seed generation)."""
    global _stats
    _stats = None
