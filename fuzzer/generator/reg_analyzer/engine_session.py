# Copyright (c) 2024-2025 Institute of Information Engineering, Chinese Academy of Sciences
#
# DiveFuzz is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
"""
Minimal checkpoint-based spike engine session for DiveFuzzTest.

Ported (minimally) from the DiveFuzz (RevFuzz) codebase's
fuzzer/generator/reg_analyzer/spike_session.py.  It wraps the pybind11
`spike_engine` shared library (ref/riscv-isa-sim-adapter/spike_engine) which
provides in-process spike simulation with checkpoint/rollback:

    initialize(elf)   -- load ELF, run template init to the nop region
    set_checkpoint()  -- save current architectural state
    execute_one(code) -- inject one machine instruction at current pc and run
    rollback()        -- restore last checkpoint (reject path)
    read_register(n)  -- read x/f register by ABI name (post-exec semantics)

Why: the legacy path re-materializes the template, re-assembles the whole
program prefix and replays it in spike for EVERY candidate instruction
(O(N^2) work per seed), and its `until reg t5` marker wait can spin forever
when a candidate jump redirects control flow away from the marker.  The
engine path compiles once per seed, executes each candidate once with a
bounded step budget, and rolls back on reject.  No subprocesses are spawned,
so the multithreaded timeout/orphan-spike failure class disappears.
"""
import os
import sys
from pathlib import Path
from typing import Optional

_XPR = {}
for _i in range(32):
    _XPR[f"x{_i}"] = _i
for _i, _n in enumerate(
    "zero ra sp gp tp t0 t1 t2 s0 s1 a0 a1 a2 a3 a4 a5 a6 a7 "
    "s2 s3 s4 s5 s6 s7 s8 s9 s10 s11 t3 t4 t5 t6".split()
):
    _XPR[_n] = _i
_XPR["fp"] = 8
_FPR = {}
for _i in range(32):
    _FPR[f"f{_i}"] = _i
for _i, _n in enumerate(
    "ft0 ft1 ft2 ft3 ft4 ft5 ft6 ft7 fs0 fs1 fa0 fa1 fa2 fa3 fa4 fa5 fa6 fa7 "
    "fs2 fs3 fs4 fs5 fs6 fs7 fs8 fs9 fs10 fs11 ft8 ft9 ft10 ft11".split()
):
    _FPR[_n] = _i


def resolve_engine_path() -> Path:
    """Locate the spike_engine pybind11 module.

    Order: $DFT_SPIKE_ENGINE_PATH, this repo's own submodule, then the
    sibling DiveFuzz checkout (the built .so is shared, not copied).
    """
    env = os.environ.get("DFT_SPIKE_ENGINE_PATH")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    own = here.parents[3] / "ref" / "riscv-isa-sim-adapter" / "spike_engine"
    if any(own.glob("spike_engine*.so")):
        return own
    return here.parents[4] / "DiveFuzz" / "ref" / "riscv-isa-sim-adapter" / "spike_engine"


_engine_dir = resolve_engine_path()
if str(_engine_dir) not in sys.path:
    sys.path.insert(0, str(_engine_dir))

try:
    import spike_engine  # pyright: ignore[reportMissingImports]
    SPIKE_ENGINE_AVAILABLE = True
except ImportError as _e:  # pragma: no cover - environment guard
    SPIKE_ENGINE_AVAILABLE = False
    spike_engine = None
    print(f"[engine_session] spike_engine import failed: {_e}; path={_engine_dir}")


class EngineSession:
    """Thin lifecycle wrapper; state semantics match legacy verification."""

    def __init__(self, elf_path: str, isa: str, num_instrs: int):
        self.elf_path = elf_path
        self.isa = isa
        self.num_instrs = num_instrs
        self.engine = None
        self._sq = None
        self.initialized = False

    def initialize(self) -> bool:
        if not SPIKE_ENGINE_AVAILABLE:
            return False
        try:
            self.engine = spike_engine.SpikeEngine(
                self.elf_path, self.isa, self.num_instrs, verbose=False
            )
            if not self.engine.initialize():
                err = self.engine.get_last_error()
                print(f"[engine_session] initialize failed: {err}")
                return False
            self._sq = self.engine.get_state_query()
            self.initialized = True
            return True
        except Exception as e:  # pragma: no cover
            print(f"[engine_session] initialize exception: {e}")
            return False

    def _require(self):
        if not self.initialized or self.engine is None:
            raise RuntimeError("EngineSession not initialized")
        return self.engine

    def set_checkpoint(self):
        self._require().set_checkpoint()

    def rollback(self):
        self._require().restore_checkpoint()


    # -- execution -----------------------------------------------------------
    def execute_one(self, machine_code: int, size: int = 4, max_steps: int = 64):
        """Inject and run a single instruction with a bounded step budget."""
        return self._require().execute_sequence([machine_code], [size], max_steps)

    def execute_loop_control(self, machine_code: int, size: int = 4):
        """Run a synthesized backward-loop control instruction.

        The bounded loop (counter initialised to <=8, body <=10 instrs) needs
        a larger step budget to unwind to exit.
        """
        return self._require().execute_sequence([machine_code], [size], 512)

    # -- state ---------------------------------------------------------------
    def get_pc(self) -> int:
        return self._sq.get_pc() if self._sq is not None else 0

    def read_register(self, name: str, *, float_register: bool = False) -> Optional[int]:
        n = name.strip()
        sq = self._sq
        if sq is None:
            return None
        # Legacy wrapper issues a single `reg` OR `freg` command for every
        # source in an instruction. Mixed source types (e.g. fsw fa0,0(sp))
        # fail rather than switching register banks mid-query.
        if float_register:
            if n not in _FPR:
                return None
            value = sq.get_fpr(_FPR[n]) & 0xFFFFFFFFFFFFFFFF
            # Spike's debugger exposes the 128-bit NaN box for every FP
            # register (upper 64 bits are ones, even for positive values).
            return value | (((1 << 64) - 1) << 64)
        if n in _XPR:
            return sq.get_xpr(_XPR[n]) & 0xFFFFFFFFFFFFFFFF
        return None

    def close(self):
        self.engine = None
        self._sq = None
        self.initialized = False
