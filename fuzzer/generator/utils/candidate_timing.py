# Copyright (c) 2024-2025 Institute of Information Engineering, Chinese Academy of Sciences
#
# DiveFuzz is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#          http://license.coscl.org.cn/Mulan PSL2/
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FITNESS FOR A PARTICULAR PURPOSE.
#
# See the Mulan PSL v2 for more details.
"""Per-candidate-attempt timing for generator worker processes.

Companion to ``phase_profiler``: instead of aggregating whole phases per
worker, this module records one JSON line per candidate evaluation attempt
(and per one-time setup segment), so downstream analysis can relate
candidate-position state acquisition cost to the accepted prefix length.

Enable by pointing ``DIVEFUZZ_CANDIDATE_TIMING_DIR`` at an output directory.
Each worker process appends to ``candidates_seed_{seed}_pid_{pid}.jsonl``.

Record types
------------
``setup``
    One-time initialization segments of a seed (template creation, NOP ELF
    generation, persistent-ISS initialization, encoder/validator setup).
``attempt``
    One candidate evaluation attempt at the current candidate position
    (``position`` = accepted prefix length).  Outer segments are timed at
    the attempt call site (``t_parse``, ``t_payload``, ``t_eval``,
    ``t_bug_filter``, ``t_xor_io``); inner components of the replay-based
    evaluation path are attached by the ISS wrapper via ``record_extra``
    (``t_materialization``, ``t_compile``, ``t_replay``, ``t_cleanup``).
    ``t_replay`` is the execution-state reconstruction cost and
    ``t_materialization`` + ``t_compile`` form the toolchain-mediated
    executable-context reconstruction cost.  Segments not reached by an
    attempt are ``None``.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Optional

_lock = threading.Lock()
_enabled: Optional[bool] = None
_dir: Optional[str] = None
_tool: str = ""
_records: list[dict] = []
_extra_fields: dict = {}
_position: int = -1
_pid: int = os.getpid()
_attempt_in_position: int = 0
_attempt_open: bool = False

# Segment slots always present in ``attempt`` records (None = not reached).
ATTEMPT_SEGMENTS = (
    "t_parse",
    "t_payload",
    "t_eval",
    "t_bug_filter",
    "t_xor_io",
    "t_materialization",
    "t_compile",
    "t_replay",
    "t_cleanup",
)


def enabled() -> bool:
    """Return whether per-candidate timing is enabled for this process."""
    global _enabled
    if _enabled is None:
        _enabled = bool(os.environ.get("DIVEFUZZ_CANDIDATE_TIMING_DIR"))
    return _enabled


def configure(tool: str, seed_index: int, instr_number: int) -> None:
    """Bind worker metadata (tool name, seed index, target N). No-op when disabled."""
    global _tool, _seed_index, _instr_number, _dir, _position, _attempt_in_position
    if not enabled():
        return
    with _lock:
        _tool = tool
        _seed_index = seed_index
        _instr_number = instr_number
        _dir = os.environ.get("DIVEFUZZ_CANDIDATE_TIMING_DIR")
        _position = -1
        _attempt_in_position = 0


def note_position(position: int) -> None:
    """Advance the candidate position; resets the per-position attempt counter."""
    global _position, _attempt_in_position
    if not enabled():
        return
    with _lock:
        if position != _position:
            _position = position
            _attempt_in_position = 0


def record_extra(name: str, value) -> None:
    """Attach an extra field to the attempt currently being timed.

    Used when a component is timed inside a nested helper (e.g. the replay
    call inside the ISS wrapper) rather than at the attempt call site.
    Ignored when no attempt is currently open.
    """
    if not enabled():
        return
    with _lock:
        if _attempt_open:
            _extra_fields[name] = value



class AttemptTimer:

    def __init__(self, record_type: str, position: int = -1, attempt: int = -1):
        self.record_type = record_type
        self.position = position
        self.attempt = attempt
        self._t0 = time.perf_counter()
        self._t_last = self._t0
        self.fields: dict = (
            {name: None for name in ATTEMPT_SEGMENTS}
            if record_type == "attempt"
            else {}
        )

    def mark(self, name: str) -> None:
        """Record elapsed time since the previous mark (or start) as ``name``."""
        now = time.perf_counter()
        self.fields[name] = now - self._t_last
        self._t_last = now

    def finish(self, **extra) -> None:
        """Append the completed record to the worker buffer."""
        now = time.perf_counter()
        with _lock:
            nested = dict(_extra_fields)
            _extra_fields.clear()
        record = {
            "record_type": self.record_type,
            "tool": _tool,
            "pid": _pid,
            "seed_index": _seed_index,
            "instr_number": _instr_number,
            "position": self.position,
            "attempt": self.attempt,
            "t_total": now - self._t0,
            **self.fields,
            **nested,
            **extra,
        }
        with _lock:
            _records.append(record)


def start_attempt() -> Optional[AttemptTimer]:
    """Start timing one candidate evaluation attempt at the current position."""
    global _attempt_in_position, _attempt_open
    if not enabled():
        return None
    with _lock:
        _extra_fields.clear()
        _attempt_in_position += 1
        attempt_index = _attempt_in_position
        position = _position
        _attempt_open = True
    return AttemptTimer("attempt", position=position, attempt=attempt_index)


def finish_attempt(timer: Optional[AttemptTimer], **extra) -> None:
    """Finish an attempt started by :func:`start_attempt` (no-op for ``None``)."""
    global _attempt_open
    if timer is None:
        return
    with _lock:
        _attempt_open = False
    timer.finish(**extra)


def start_setup() -> Optional[AttemptTimer]:
    """Start timing a one-time setup segment sequence."""
    if not enabled():
        return None
    return AttemptTimer("setup")



def finish_setup(timer: Optional[AttemptTimer], **extra) -> None:
    """Finish a setup timer started by :func:`start_setup` (no-op for ``None``)."""
    if timer is None:
        return
    timer.finish(**extra)


def flush() -> None:
    """Append buffered records to this worker's JSONL file."""
    global _records
    if not enabled():
        return
    with _lock:
        records = _records
        _records = []
        seed_index = _seed_index
    if not records:
        return
    output_dir = _dir or os.environ.get("DIVEFUZZ_CANDIDATE_TIMING_DIR")
    if not output_dir:
        return
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(
        output_dir, f"candidates_seed_{seed_index}_pid_{_pid}.jsonl"
    )
    with open(path, "a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
