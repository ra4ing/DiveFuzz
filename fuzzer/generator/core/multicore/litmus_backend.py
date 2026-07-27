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

"""Litmus7-compatible executable backend.

Reuses the existing ``spike-litmus-harness`` Makefile compile path rather than
reimplementing the C harness. On any failure the backend raises a
``RuntimeError`` whose message starts with ``LITMUS_BACKEND_ERROR:``.
"""

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SeedBundle:
    """Paths to all artifacts of one generated multicore seed."""

    seed_id: int
    name: str
    seed_dir: Path
    mc_path: Path
    litmus_path: Path
    elf_path: Path | None
    allowed_path: Path
    manifest_path: Path


class LitmusExecutableBackend:
    """Build a litmus7-compatible ELF via the spike-litmus-harness Makefile."""

    def __init__(
        self,
        harness_dir: str,
        litmus7_path: str | None = None,
        litmus7_share: str | None = None,
    ):
        self.harness_dir = harness_dir
        self.litmus7_path = litmus7_path
        self.litmus7_share = litmus7_share

    def build(
        self,
        litmus_path: Path,
        hart_count: int,
        litmus_runs: int,
        litmus_size: int,
        output_elf: Path,
    ) -> Path:
        """Compile ``litmus_path`` into ``output_elf`` and return the ELF path."""
        litmus_path = Path(litmus_path).resolve()
        output_elf = Path(output_elf)
        litmus_name = litmus_path.stem

        cmd = [
            "make",
            f"-C{self.harness_dir}",
            f"LITMUS={litmus_path}",
            f"AVAIL={hart_count}",
            f"NRUNS={litmus_runs}",
            f"SIZE={litmus_size}",
            "compile",
        ]
        if self.litmus7_path:
            cmd.append(f"LITMUS7={self.litmus7_path}")
        if self.litmus7_share:
            cmd.append(f"LITMUS7_SHARE={self.litmus7_share}")

        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=600,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                "LITMUS_BACKEND_ERROR: make compile timed out after 600s"
            )
        except OSError as e:
            raise RuntimeError(
                f"LITMUS_BACKEND_ERROR: could not run make: {e}"
            )

        output = proc.stdout or ""
        if proc.returncode != 0:
            raise RuntimeError(
                f"LITMUS_BACKEND_ERROR: make compile exited with code "
                f"{proc.returncode}\n{output}"
            )

        produced_elf = (
            Path(self.harness_dir) / "build" / litmus_name / f"{litmus_name}.elf"
        )
        if not produced_elf.exists():
            raise RuntimeError(
                f"LITMUS_BACKEND_ERROR: expected ELF not produced at "
                f"{produced_elf}\n{output}"
            )

        output_elf.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(produced_elf, output_elf)
        return output_elf
