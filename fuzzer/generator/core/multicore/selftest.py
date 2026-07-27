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

"""Pure-Python smoke test for the multicore generator.

Run with ``cd fuzzer && python -m generator.core.multicore.selftest``. Requires
no external tooling (no herd7 / litmus7 / XiangShan); it exercises program
generation, validation, litmus export, outcome parsing on fixtures, and oracle
classification.
"""

import random
from collections import Counter

from .families import build_program, available_families
from .validator import validate
from .litmus_exporter import export_litmus
from .outcome import parse_litmus_histogram, parse_herd_states

from executor.multicore.oracle import classify_outcomes
from utils.results_reporter import ResultType


def _check_programs() -> None:
    for family in available_families():
        for noise in ("none", "L0"):
            rng = random.Random(42)
            program = build_program(0, family, noise, rng)
            validate(program)
            litmus = export_litmus(program)
            # Every hart must appear as a process column P0..P{N-1}.
            for h in range(program.hart_count):
                assert f"P{h}" in litmus, (
                    f"{family}/{noise}: litmus missing column P{h}"
                )
            for token in ("RISCV", "exists", "sd", "ld"):
                assert token in litmus, (
                    f"{family}/{noise}: litmus missing token '{token}'"
                )
            # Fence families must render their barrier.
            if family == "MP":
                assert "fence rw,rw" in litmus, f"{family}: missing fence"
            elif family == "MPTSO":
                assert "fence.tso" in litmus, f"{family}: missing fence.tso"


def _check_histogram_parsing() -> Counter:
    output = (
        "Histogram (2 states)\n"
        "3920 :> 0:x10=0; 1:x10=0;\n"
        "1080 :> 0:x10=1; 1:x10=1;\n"
        "Ok\n"
    )
    hist = parse_litmus_histogram(output)
    assert len(hist) == 2, f"expected 2 histogram states, got {len(hist)}"
    total = sum(hist.values())
    assert total == 5000, f"expected 5000 total observations, got {total}"
    return hist


def _check_herd_parsing() -> set:
    output = (
        "States 2\n"
        "0:x10=0 /\\ 1:x10=0\n"
        "0:x10=1 /\\ 1:x10=1\n"
    )
    allowed = parse_herd_states(output)
    assert len(allowed) == 2, f"expected 2 allowed states, got {len(allowed)}"
    return allowed


def _check_oracle(allowed: set, hist: Counter) -> None:
    # All observed outcomes are allowed -> SUCCESS.
    rt, _ = classify_outcomes(allowed, hist)
    assert rt == ResultType.SUCCESS, f"expected SUCCESS, got {rt}"

    # An outcome not in the allowed set -> MODEL_VIOLATION.
    forbidden = Counter({(("h0.x10", 2), ("h1.x10", 2)): 1})
    rt2, _ = classify_outcomes(allowed, forbidden)
    assert rt2 == ResultType.MODEL_VIOLATION, (
        f"expected MODEL_VIOLATION, got {rt2}"
    )

    # No observations -> NO_OUTCOME.
    rt3, _ = classify_outcomes(allowed, Counter())
    assert rt3 == ResultType.NO_OUTCOME, f"expected NO_OUTCOME, got {rt3}"


def _check_randomized() -> None:
    # Randomized programs must still validate + export, and randomization must
    # actually perturb output for at least one (family, seed) draw.
    seen_diff = False
    for family in available_families():
        for seed in range(8):
            det = build_program(seed, family, "none", random.Random(seed))
            rnd = build_program(
                seed, family, "none", random.Random(seed), randomize=True
            )
            validate(rnd)
            det_lit = export_litmus(det)
            rnd_lit = export_litmus(rnd)
            for token in ("RISCV", "exists"):
                assert token in rnd_lit, (
                    f"{family}/{seed}: randomized litmus missing '{token}'"
                )
            if det_lit != rnd_lit:
                seen_diff = True
    assert seen_diff, "randomize=True never changed output across families/seeds"


def _check_ordering_randomization() -> None:
    # Deterministic MP keeps the canonical fence.
    det_mp = export_litmus(build_program(0, "MP", "none", random.Random(0)))
    assert "fence rw,rw" in det_mp, "deterministic MP lost canonical fence rw,rw"
    # Randomized mode must, across draws, vary the fence pred/succ bits.
    seen_varied_fence = False
    for seed in range(40):
        lit = export_litmus(
            build_program(0, "MP", "none", random.Random(seed), randomize=True)
        )
        for line in lit.splitlines():
            if "fence " in line and "fence.tso" not in line and "fence rw,rw" not in line:
                seen_varied_fence = True
    assert seen_varied_fence, "randomize=True never varied fence bits across 40 MP seeds"


def _check_aliasing() -> None:
    # Deterministic programs declare every shared var (identity alias map).
    det = export_litmus(build_program(0, "SB", "none", random.Random(0)))
    assert det.count("uint64_t") == 2, (
        f"deterministic SB should declare 2 vars, got:\n{det}"
    )
    # Randomized mode must, across draws, sometimes collapse to one physical
    # var (same-word alias).
    seen_alias = False
    for seed in range(40):
        prog = build_program(0, "SB", "none", random.Random(seed), randomize=True)
        validate(prog)
        if export_litmus(prog).count("uint64_t") == 1:
            seen_alias = True
    assert seen_alias, (
        "randomize=True never produced a same-word alias across 40 SB seeds"
    )


def _check_width_mixing() -> None:
    # Deterministic programs use width 8 only (sd/ld).
    det = export_litmus(build_program(0, "SB", "none", random.Random(0)))
    assert " sd " in det and " ld " in det, "deterministic SB should use sd/ld"
    assert not any(op in det for op in (" sb ", " sh ", " sw ", " lb ", " lh ", " lw ")), (
        "deterministic SB leaked a narrow access"
    )
    # Randomized mode must, across draws, produce at least one narrow access.
    seen_narrow = False
    for seed in range(40):
        lit = export_litmus(build_program(0, "SB", "none", random.Random(seed), randomize=True))
        if any(op in lit for op in (" sb ", " sh ", " sw ", " lb ", " lh ", " lw ")):
            seen_narrow = True
    assert seen_narrow, (
        "randomize=True never produced a narrow access across 40 SB seeds"
    )


def main() -> None:
    _check_programs()
    _check_randomized()
    _check_ordering_randomization()
    _check_aliasing()
    _check_width_mixing()
    hist = _check_histogram_parsing()
    allowed = _check_herd_parsing()
    _check_oracle(allowed, hist)
    print("DFMC selftest PASS")


if __name__ == "__main__":
    main()
