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

from .families import build_program
from .validator import validate
from .litmus_exporter import export_litmus
from .outcome import parse_litmus_histogram, parse_herd_states
from .asm_exporter import export_asm, export_meta

from executor.multicore.oracle import classify_outcomes
from utils.results_reporter import ResultType


def _check_programs() -> None:
    for family in ("SB", "LB", "MP"):
        for noise in ("none", "L0"):
            rng = random.Random(42)
            program = build_program(0, family, 2, noise, rng)
            validate(program)
            litmus = export_litmus(program)
            for token in ("RISCV", "P0", "P1", "exists", "sd", "ld"):
                assert token in litmus, (
                    f"{family}/{noise}: litmus missing token '{token}'"
                )


def _check_asm_export() -> None:
    """The custom-backend asm/meta export must be well-formed for SB/LB/MP."""
    for family in ("SB", "LB", "MP"):
        rng = random.Random(42)
        program = build_program(0, family, 2, "none", rng)
        validate(program)

        asm = export_asm(program)
        for token in (
            "litmus_P0", "litmus_P1", "dfmc_init",
            "la x6, dfmc_var_0", "la x7, dfmc_var_1",
            "sd", "ld", "dfmc_obs_flat", "ret",
        ):
            assert token in asm, (
                f"{family}: asm export missing token '{token}'"
            )

        meta = export_meta(program)
        assert f"#define DFMC_NAME \"{program.name}\"" in meta, (
            f"{family}: meta missing DFMC_NAME"
        )
        assert f"#define DFMC_NHART {program.hart_count}" in meta, (
            f"{family}: meta missing DFMC_NHART"
        )
        assert f"#define DFMC_NOBS_TOTAL {len(program.observed)}" in meta, (
            f"{family}: DFMC_NOBS_TOTAL mismatch "
            f"(expected {len(program.observed)})"
        )


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


def main() -> None:
    _check_programs()
    _check_asm_export()
    hist = _check_histogram_parsing()
    allowed = _check_herd_parsing()
    _check_oracle(allowed, hist)
    print("DFMC selftest PASS")


if __name__ == "__main__":
    main()
