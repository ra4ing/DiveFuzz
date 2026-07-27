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

"""End-to-end multicore seed generation.

For each seed: pick a test family deterministically, build + validate the
program, export ``.litmus``, query herd for allowed outcomes, optionally build
the litmus7-compatible ELF, and write all artifacts to ``<out>/seed_<id>/``.

If herd fails, ``seed.mc.json`` and ``seed.litmus`` are still written and the
error is re-raised so an unchecked seed is never silently kept.
"""

import dataclasses
import json
import random
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .families import build_program, family_hart_count
from .validator import validate
from .litmus_exporter import export_litmus
from .herd_oracle import HerdOracle
from .litmus_backend import LitmusExecutableBackend, SeedBundle


@dataclass
class MultiCoreGenerationConfig:
    """Configuration consumed by ``generate_multicore_seeds``."""

    seeds_output: str
    seeds_num: int
    seed_offset: int
    test_families: list[str]
    noise_level: str
    herd_path: str
    litmus_harness_dir: str
    litmus7_path: str | None
    litmus7_share: str | None
    litmus_runs: int
    litmus_size: int
    hart_count: int | None = None
    build_executable: bool = True
    randomize: bool = False


def _to_jsonable(obj):
    """Recursively convert Enum instances to their values for JSON output."""
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, tuple):
        return [_to_jsonable(v) for v in obj]
    return obj


def _write_mc_json(mc_path: Path, program) -> None:
    payload = _to_jsonable(dataclasses.asdict(program))
    mc_path.write_text(json.dumps(payload, indent=2))


def _write_allowed(allowed_path: Path, allowed) -> None:
    allowed_list = [dict(outcome) for outcome in sorted(allowed)]
    allowed_path.write_text(json.dumps(allowed_list, indent=2))


def generate_multicore_seed(seed_id: int, config: MultiCoreGenerationConfig) -> SeedBundle:
    """Generate a single multicore seed and return its artifact bundle."""
    family = config.test_families[
        (seed_id - config.seed_offset) % len(config.test_families)
    ]
    required_harts = family_hart_count(family)
    if config.hart_count is not None and config.hart_count != required_harts:
        raise ValueError(
            f"family {family!r} requires {required_harts} harts but "
            f"--hart-count={config.hart_count}; drop --hart-count to let each "
            f"family use its own topology"
        )
    rng = random.Random(seed_id)
    program = build_program(seed_id, family, config.noise_level, rng, randomize=config.randomize)
    validate(program)

    seed_dir = Path(config.seeds_output) / f"seed_{seed_id}"
    seed_dir.mkdir(parents=True, exist_ok=True)
    mc_path = seed_dir / "seed.mc.json"
    litmus_path = seed_dir / "seed.litmus"
    allowed_path = seed_dir / "allowed_outcomes.json"
    manifest_path = seed_dir / "manifest.json"
    elf_path: Path | None = None

    # Write the program model + litmus first so a herd failure still leaves
    # inspectable artifacts behind.
    _write_mc_json(mc_path, program)
    litmus_path.write_text(export_litmus(program))

    # Query the RVWMO/herd oracle for allowed outcomes.
    oracle = HerdOracle(config.herd_path)
    result = oracle.allowed_outcomes(str(litmus_path.resolve()))
    _write_allowed(allowed_path, result.allowed)

    # Optionally build the litmus7-compatible executable.
    if config.build_executable:
        out_elf = seed_dir / "seed.elf"
        backend = LitmusExecutableBackend(
            config.litmus_harness_dir,
            config.litmus7_path,
            config.litmus7_share,
        )
        backend.build(
            litmus_path,
            program.hart_count,
            config.litmus_runs,
            config.litmus_size,
            out_elf,
        )
        elf_path = out_elf

    # Manifest with absolute paths + identifying metadata.
    manifest = {
        "seed_id": seed_id,
        "name": program.name,
        "family": program.metadata.get("family", family),
        "hart_count": program.hart_count,
        "noise_level": config.noise_level,
        "randomize": config.randomize,
        "isa": program.isa,
        "paths": {
            "seed_dir": str(seed_dir.resolve()),
            "mc_path": str(mc_path.resolve()),
            "litmus_path": str(litmus_path.resolve()),
            "allowed_path": str(allowed_path.resolve()),
            "elf_path": str(elf_path.resolve()) if elf_path else None,
            "manifest_path": str(manifest_path.resolve()),
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))

    return SeedBundle(
        seed_id=seed_id,
        name=program.name,
        seed_dir=seed_dir,
        mc_path=mc_path,
        litmus_path=litmus_path,
        elf_path=elf_path,
        allowed_path=allowed_path,
        manifest_path=manifest_path,
    )


def generate_multicore_seeds(
    config: MultiCoreGenerationConfig, logger=None
) -> list[SeedBundle]:
    """Generate ``config.seeds_num`` seeds starting at ``config.seed_offset``."""
    if config.hart_count is not None:
        bad = [
            f for f in config.test_families
            if family_hart_count(f) != config.hart_count
        ]
        if bad:
            raise ValueError(
                f"--hart-count={config.hart_count} but family(ies) {bad} "
                f"require a different hart count; drop --hart-count to let "
                f"each family use its own topology"
            )
    bundles: list[SeedBundle] = []
    for i in range(config.seeds_num):
        seed_id = config.seed_offset + i
        if logger is not None:
            logger.info(f"Generating multicore seed {seed_id} ({i + 1}/{config.seeds_num})")
        bundle = generate_multicore_seed(seed_id, config)
        bundles.append(bundle)
        if logger is not None:
            logger.info(f"Generated multicore seed {seed_id}: {bundle.litmus_path}")
    return bundles
