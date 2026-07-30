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

"""RVWMO/herd oracle: compute the set of memory-model-allowed outcomes.

Wraps the ``herd7`` tool. Every failure mode (missing binary, timeout, nonzero
exit, unparseable output) is surfaced as a ``RuntimeError`` whose message starts
with ``HERD_ORACLE_ERROR:`` so callers can distinguish infrastructure failure
from a genuine model violation.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .outcome import parse_herd_states


@dataclass
class OracleResult:
    """Result of querying herd for a single litmus test."""

    allowed: set[tuple[tuple[str, int], ...]]
    raw_output: str


class HerdOracle:
    """Run herd7 to obtain allowed outcomes for a ``.litmus`` file."""

    def __init__(self, herd_path: str, cache=None):
        self.herd_path = herd_path
        # Optional HerdCache: when set, allowed sets are served from / stored to
        # a content-addressed on-disk cache keyed by the litmus text, so herd7
        # is only invoked for litmus it has not already solved.
        self.cache = cache

    def allowed_outcomes(self, litmus_path: str) -> OracleResult:
        """Return the set of allowed outcomes for ``litmus_path``.

        Serves from the cache (if any) when the litmus text is already known;
        otherwise runs herd7 and stores the result for reuse.
        """
        litmus_text = Path(litmus_path).read_text()
        if self.cache is not None:
            cached = self.cache.get(litmus_text)
            if cached is not None:
                return OracleResult(
                    allowed=cached, raw_output="(served from herd cache)"
                )
        try:
            proc = subprocess.run(
                [self.herd_path, str(litmus_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=120,
            )
        except FileNotFoundError as e:
            raise RuntimeError(
                f"HERD_ORACLE_ERROR: herd executable not found at "
                f"'{self.herd_path}': {e}"
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                "HERD_ORACLE_ERROR: herd timed out after 120s"
            )
        except OSError as e:
            raise RuntimeError(
                f"HERD_ORACLE_ERROR: could not run herd: {e}"
            )

        output = proc.stdout or ""
        if proc.returncode != 0:
            raise RuntimeError(
                f"HERD_ORACLE_ERROR: herd exited with code "
                f"{proc.returncode}\n{output}"
            )
        try:
            allowed = parse_herd_states(output)
        except ValueError as e:
            raise RuntimeError(
                f"HERD_ORACLE_ERROR: failed to parse herd states: {e}\n{output}"
            )
        if self.cache is not None:
            self.cache.put(litmus_text, allowed)
        return OracleResult(allowed=allowed, raw_output=output)
