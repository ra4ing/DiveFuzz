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

"""Parsing of canonical multicore outcomes from herd7 / litmus7 output.

A canonical outcome is ``tuple(sorted(dict.items()))`` of a ``{key: int}``
mapping. Two key shapes occur in herd7 ``States`` and litmus7 ``Histogram``
output alike:

- register keys ``0:x10`` -> canonicalized to ``h0.x10``;
- final-memory keys, which both tools render bracketed as ``[x]`` -> stripped
  to the bare location name ``x`` (kept as-is).

All-store families (e.g. 3.2W) have no register observations; their outcome is
the final memory of the shared locations, so bracket handling is what makes
them classifiable.
"""

import re
from collections import Counter

# Matches a single assignment such as ``0:x10=1`` or ``x=0``.
_ASSIGN_RE = re.compile(r'([0-9]+:[A-Za-z0-9_.]+|[A-Za-z_][A-Za-z0-9_.]*)\s*=\s*(-?\d+)')
# Matches one histogram row: ``3920 :> 0:x10=0; 1:x10=0;``
_HIST_ROW_RE = re.compile(r'^\s*(\d+)\s+:>?(.+);\s*$')


def canonical_key(raw_key: str) -> str:
    """Map a litmus/herd raw key to the canonical outcome key.

    ``"0:x10"`` -> ``"h0.x10"``; a bare memory name (e.g. ``"x"``) is
    returned unchanged.
    """
    if ':' in raw_key:
        hart, loc = raw_key.split(':', 1)
        return f"h{hart}.{loc}"
    return raw_key


def canonical_outcome(state: dict[str, int]) -> tuple[tuple[str, int], ...]:
    """Return a hashable, JSON-stable canonical form of an outcome state."""
    return tuple(sorted(state.items()))


def parse_assignment_state(text: str) -> dict[str, int]:
    r"""Parse ``"0:x10=1 /\ 1:x10=0"`` (or ``;``-separated) into a state dict.

    Final-memory keys arrive bracketed (``[x]=2``) from both herd7 ``States``
    and the litmus7 histogram; strip the brackets so they canonicalize to the
    bare location name and align across the two sources.
    """
    state: dict[str, int] = {}
    for m in _ASSIGN_RE.finditer(text.replace("[", "").replace("]", "")):
        state[canonical_key(m.group(1))] = int(m.group(2))
    return state


def parse_litmus_histogram(output: str) -> Counter[tuple[tuple[str, int], ...]]:
    """Parse a litmus7 ``Histogram`` block into ``{outcome: count}``.

    Only rows of the form ``<count> :> <assignments>;`` are recognized; these
    rows are distinctive to the histogram block, so no block-boundary tracking
    is required.
    """
    result: Counter[tuple[tuple[str, int], ...]] = Counter()
    for line in output.splitlines():
        m = _HIST_ROW_RE.match(line)
        if not m:
            continue
        count = int(m.group(1))
        state = parse_assignment_state(m.group(2))
        if not state:
            continue
        result[canonical_outcome(state)] += count
    return result


def parse_herd_states(output: str) -> set[tuple[tuple[str, int], ...]]:
    """Parse a herd7 ``States <N>`` block into the set of allowed outcomes.

    Raises ``ValueError("herd output did not contain a States block")`` when
    no ``States`` block is present.
    """
    lines = output.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r'^\s*States\s+(\d+)', line)
        if not m:
            continue
        n = int(m.group(1))
        states: set[tuple[tuple[str, int], ...]] = set()
        for j in range(i + 1, min(i + 1 + n, len(lines))):
            state = parse_assignment_state(lines[j])
            if state:
                states.add(canonical_outcome(state))
        return states
    raise ValueError("herd output did not contain a States block")
