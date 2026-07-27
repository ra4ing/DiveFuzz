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

"""Custom 2-hart bare-metal backend: MCProgram -> seed.S/seed_meta.h -> ELF.

A drop-in alternative to :class:`LitmusExecutableBackend` that drops the
litmus7 controller hart. On any failure the backend raises a ``RuntimeError``
whose message starts with ``CUSTOM_BACKEND_ERROR:`` (no silent fallback).
"""

import shutil
import subprocess
from pathlib import Path

from .model import MCProgram
from .asm_exporter import export_asm, export_meta


class CustomAsmBackend:
    """Build a 2-hart custom litmus ELF via the ``xs-custom-harness`` Makefile."""

    def __init__(self, harness_dir: str):
        self.harness_dir = harness_dir

    def build(self, program: MCProgram, nruns: int, output_elf: Path) -> Path:
        """Generate seed.S/seed_meta.h, compile via the harness Makefile, copy ELF."""
        if program.hart_count != 2:
            raise ValueError(
                "Custom ASM backend supports hart_count=2 only "
                f"(got {program.hart_count})"
            )

        output_elf = Path(output_elf)
        harness = Path(self.harness_dir).resolve()

        build = output_elf.parent / "xsbuild"
        gen = build / "gen"
        gen.mkdir(parents=True, exist_ok=True)

        (gen / "seed.S").write_text(export_asm(program))
        (gen / "seed_meta.h").write_text(export_meta(program))

        cmd = [
            "make",
            "-C",
            str(harness),
            f"BUILD={build.resolve()}",
            f"NRUNS={nruns}",
            "compile",
        ]
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                "CUSTOM_BACKEND_ERROR: make compile timed out after 300s"
            )
        except OSError as e:
            raise RuntimeError(f"CUSTOM_BACKEND_ERROR: could not run make: {e}")

        build_log = proc.stdout or ""
        if proc.returncode != 0:
            tail = "\n".join(build_log.splitlines()[-40:])
            raise RuntimeError(
                f"CUSTOM_BACKEND_ERROR: make compile exited with code "
                f"{proc.returncode}\n{tail}"
            )

        produced_elf = build / "seed.elf"
        if not produced_elf.exists():
            raise RuntimeError(
                f"CUSTOM_BACKEND_ERROR: expected ELF not produced at "
                f"{produced_elf}\n{build_log}"
            )

        output_elf.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(produced_elf, output_elf)
        return output_elf
