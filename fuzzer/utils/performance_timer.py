# Copyright (c) 2024-2025 Institute of Information Engineering, Chinese Academy of Sciences
#
# Performance Timer Module for DiveFuzz
#
# This module provides timing instrumentation that can be enabled via environment variables.
# When enabled, it collects timing data for each phase of the fuzzing process.
#
# Environment Variables:
#   DIVEFUZZ_PERF_ENABLE=1       - Enable performance timing
#   DIVEFUZZ_PERF_OUTPUT=path    - Output file path (default: perf_results.json)
#
# Usage:
#   from utils.performance_timer import perf_timer, measure
#
#   # Context manager style
#   with measure("initialization"):
#       do_initialization()
#
#   # Manual timing
#   perf_timer.add_time("spike_execution", elapsed)
#
#   # At end of program
#   perf_timer.save()
#

import os
import time
import json
import atexit
import threading
from dataclasses import dataclass
from typing import Dict, Optional
from contextlib import contextmanager


@dataclass
class PhaseStats:
    """Statistics for a single timing phase."""
    total_time: float = 0.0
    call_count: int = 0
    min_time: float = float('inf')
    max_time: float = 0.0

    def add_sample(self, elapsed: float):
        self.total_time += elapsed
        self.call_count += 1
        self.min_time = min(self.min_time, elapsed)
        self.max_time = max(self.max_time, elapsed)

    @property
    def avg_time(self) -> float:
        return self.total_time / self.call_count if self.call_count > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "total_time": self.total_time,
            "call_count": self.call_count,
            "avg_time": self.avg_time,
            "min_time": self.min_time if self.min_time != float('inf') else 0.0,
            "max_time": self.max_time
        }


class PerformanceTimer:
    """
    Thread-safe performance timer for collecting timing statistics.

    Phases tracked:
    - initialization: Template creation, config setup, SpikeSession init
    - instruction_gen: Main instruction generation loop (including spike for DiveFuzz)
    - spike_execution: Spike validation (for DiveFuzzTest, separate from gen)
    - compilation: Assembly to binary compilation (process_assembly_files)
    - rtl_execution: DUT/RTL simulation time
    """

    # Standard phase names
    PHASE_INITIALIZATION = "initialization"
    PHASE_INSTRUCTION_GEN = "instruction_gen"
    PHASE_SPIKE_EXECUTION = "spike_execution"
    PHASE_COMPILATION = "compilation"
    PHASE_RTL_EXECUTION = "rtl_execution"

    def __init__(self):
        self._enabled = os.environ.get("DIVEFUZZ_PERF_ENABLE", "0") == "1"
        self._output_path = os.environ.get("DIVEFUZZ_PERF_OUTPUT", "perf_results.json")
        self._lock = threading.Lock()
        self._phases: Dict[str, PhaseStats] = {}
        self._total_start: Optional[float] = None
        self._metadata: Dict = {}
        self._saved = False

        if self._enabled:
            self._total_start = time.perf_counter()
            atexit.register(self._atexit_save)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_metadata(self, **kwargs):
        """Set metadata to include in output."""
        with self._lock:
            self._metadata.update(kwargs)

    def add_time(self, phase: str, elapsed: float):
        """Add elapsed time to a phase."""
        if not self._enabled:
            return

        with self._lock:
            if phase not in self._phases:
                self._phases[phase] = PhaseStats()
            self._phases[phase].add_sample(elapsed)

    @contextmanager
    def measure(self, phase: str):
        """Context manager for timing a code block."""
        if not self._enabled:
            yield
            return

        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            self.add_time(phase, elapsed)

    def get_results(self) -> dict:
        """Get timing results as a dictionary."""
        with self._lock:
            total_elapsed = 0.0
            if self._total_start is not None:
                total_elapsed = time.perf_counter() - self._total_start

            results = {
                "enabled": self._enabled,
                "phases": {name: stats.to_dict() for name, stats in self._phases.items()},
                "total_elapsed": total_elapsed,
                "metadata": self._metadata,
                "summary": {name: stats.total_time for name, stats in self._phases.items()}
            }
            results["summary"]["total"] = total_elapsed
            return results

    def save(self, output_path: Optional[str] = None):
        """Save timing results to JSON file."""
        if not self._enabled:
            return

        path = output_path or self._output_path
        results = self.get_results()

        try:
            with open(path, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"[PerfTimer] Results saved to: {path}")
        except Exception as e:
            print(f"[PerfTimer] Failed to save results: {e}")

        self._saved = True

    def _atexit_save(self):
        """Called at program exit to save results."""
        if self._enabled and not self._saved:
            self.save()

    def print_summary(self):
        """Print a summary of timing results."""
        if not self._enabled:
            print("[PerfTimer] Timing not enabled")
            return

        results = self.get_results()
        print("\n" + "=" * 60)
        print("PERFORMANCE TIMING SUMMARY")
        print("=" * 60)

        for phase, stats in results["phases"].items():
            print(f"  {phase}:")
            print(f"    Total: {stats['total_time']:.3f}s")
            print(f"    Calls: {stats['call_count']}")
            if stats['call_count'] > 0:
                print(f"    Avg:   {stats['avg_time']:.6f}s")

        print("-" * 60)
        print(f"  Total elapsed: {results['total_elapsed']:.3f}s")
        print("=" * 60)


# Global timer instance
perf_timer = PerformanceTimer()


def measure(phase: str):
    """Context manager for timing."""
    return perf_timer.measure(phase)
