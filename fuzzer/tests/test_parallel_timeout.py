"""A hung seed must not time out seeds merely queued behind its pool slot.

Run from fuzzer/: PYTHONPATH=. python3 -m unittest discover -s tests
"""
import contextlib
import importlib
import io
import os
import tempfile
import time
import unittest
from pathlib import Path

from generator.asm_template_manager.riscv_asm_syntex import ArchConfig

parallel = importlib.import_module("generator.core.generator")
_MARKER_DIR = None


def _slow_first_attempt(instr_number, seed_idx, *args, **kwargs):
    marker = _MARKER_DIR / str(seed_idx)
    if seed_idx < 2:
        try:
            marker.touch(exist_ok=False)
        except FileExistsError:
            pass
        else:
            time.sleep(5)  # parent timeout must kill this process
    return 0, 0


class ParallelTimeoutTest(unittest.TestCase):
    def test_stalled_pool_restarts_without_expiring_queued_seeds(self):
        original = parallel.generate_instructions
        scale = os.environ.get("DIVEFUZZ_TIMEOUT_SCALE")
        with tempfile.TemporaryDirectory() as temp:
            global _MARKER_DIR
            _MARKER_DIR = Path(temp)
            parallel.generate_instructions = _slow_first_attempt
            os.environ["DIVEFUZZ_TIMEOUT_SCALE"] = "0.3"
            capture = io.StringIO()
            try:
                with contextlib.redirect_stdout(capture):
                    parallel.generate_instructions_parallel(
                        1, 4, False, False, False, 2,
                        ArchConfig(64, "rv64gc"), "rocket",
                        out_dir=temp,
                    )
            finally:
                parallel.generate_instructions = original
                _MARKER_DIR = None
                if scale is None:
                    os.environ.pop("DIVEFUZZ_TIMEOUT_SCALE", None)
                else:
                    os.environ["DIVEFUZZ_TIMEOUT_SCALE"] = scale
        output = capture.getvalue()
        self.assertIn("Successfully generated: 4/4 seeds", output)
        # Only the two running seeds expired. Seeds 2 and 3 were never
        # started in the first pool and must not receive a false deadline.
        self.assertIn("Total timeouts: 2", output)


if __name__ == "__main__":
    unittest.main()
