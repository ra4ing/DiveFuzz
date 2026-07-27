"""
Rollback correctness experiment for AstraFuzz persistent Spike execution.

The experiment checks two independent oracles:
1. Local rollback equivalence: state before candidate execution equals state after restore.
2. Fresh replay equivalence: persistent execution with rejected candidates equals a fresh Spike
   session that replays only the accepted instruction prefix.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

# ---------------------------------------------------------------------------
# AstraFuzz imports -- resolve FUZZER_ROOT from __file__
# ---------------------------------------------------------------------------
FUZZER_ROOT = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, FUZZER_ROOT)

from generator.asm_template_manager import create_template_instance
from generator.asm_template_manager.riscv_asm_syntex.arch import ArchConfig
from generator.asm_template_manager.riscv_asm_syntex.csr import CSR_NAME_TO_ADDR
from generator.reg_analyzer.hybrid_encoder import HybridEncoder
from generator.reg_analyzer.nop_template_gen import generate_nop_elf
from generator.reg_analyzer.spike_session import SpikeSession

# ---------------------------------------------------------------------------
# Transient fields that are not part of persistent architectural state
# ---------------------------------------------------------------------------
DEFAULT_TRANSIENT_FIELDS = frozenset({
    "privilege.prv_changed",
    "privilege.v_changed",
})

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class InstructionSequence:
    """One accepted or rejected instruction sequence in the experiment stream."""
    name: str
    instructions: tuple[str, ...]
    category: str


@dataclass
class CaseResult:
    """Result for one rollback correctness case."""
    name: str
    category: str
    local_mismatches: list[str] = field(default_factory=list)
    replay_mismatches: list[str] = field(default_factory=list)
    ignored_local_mismatches: list[str] = field(default_factory=list)
    ignored_replay_mismatches: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    checkpoint_seconds: float = 0.0
    rollback_seconds: float = 0.0
    trapped: bool = False
    error: str | None = None

    def passed(self) -> bool:
        return (
            not self.local_mismatches
            and not self.replay_mismatches
            and not self.unsupported
            and self.error is None
        )


@dataclass
class CategorySummary:
    """Aggregated result counters for one experiment category."""
    cases: int = 0
    passed: int = 0
    local_mismatches: int = 0
    replay_mismatches: int = 0
    errors: int = 0
    unsupported: set[str] = field(default_factory=set)
    checkpoint_seconds_total: float = 0.0
    rollback_seconds_total: float = 0.0

    def add(self, result: CaseResult) -> None:
        self.cases += 1
        if result.passed():
            self.passed += 1
        self.local_mismatches += len(result.local_mismatches)
        self.replay_mismatches += len(result.replay_mismatches)
        if result.error:
            self.errors += 1
        self.unsupported.update(result.unsupported)
        self.checkpoint_seconds_total += result.checkpoint_seconds
        self.rollback_seconds_total += result.rollback_seconds

    def to_dict(self) -> dict:
        return {
            "cases": self.cases,
            "passed": self.passed,
            "local_mismatches": self.local_mismatches,
            "replay_mismatches": self.replay_mismatches,
            "errors": self.errors,
            "unsupported": sorted(self.unsupported),
            "checkpoint_seconds_avg": self.checkpoint_seconds_total / max(self.cases, 1),
            "rollback_seconds_avg": self.rollback_seconds_total / max(self.cases, 1),
        }


# ---------------------------------------------------------------------------
# Encoding helpers
# ---------------------------------------------------------------------------
def encode_sequence(encoder: HybridEncoder, sequence: InstructionSequence) -> tuple[list[int], list[int]]:
    """Encode an assembly sequence into SpikeEngine machine code and size arrays."""
    codes: list[int] = []
    sizes: list[int] = []
    for instruction in sequence.instructions:
        for code, size in encoder.encode_sequence(instruction):
            codes.append(code)
            sizes.append(size)
    return codes, sizes


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------
def object_to_dict(obj, fields: Sequence[str]) -> dict:
    """Extract pybind object fields into a JSON-serializable dictionary."""
    result = {}
    for field_name in fields:
        try:
            value = getattr(obj, field_name, f"<unsupported: {field_name}>")
            if isinstance(value, bytes):
                value = value.hex()
            elif hasattr(value, "__int__"):
                value = int(value)
            result[field_name] = value
        except Exception as exc:
            result[field_name] = f"<unsupported: {field_name}: {exc}>"
    return result


def hash_bytes(data: bytes) -> str:
    """Return a short deterministic hash for state digest fields."""
    return hashlib.sha256(data).hexdigest()[:16]


def snapshot_state(
    session: SpikeSession,
    memory_bytes: int,
    stack_memory_bytes: int,
    include_vector_regfile: bool,
):
    """Capture the architectural and selected simulator-visible state used by AstraFuzz."""
    state = {}
    # GPR
    state["x"] = [int(session.get_xpr(i)) for i in range(32)]
    # FPR
    state["f"] = []
    for i in range(32):
        val = session.get_fpr(i)
        if isinstance(val, bytes):
            state["f"].append(val.hex())
        else:
            state["f"].append(int(val))
    # PC
    state["pc"] = int(session.get_current_pc())
    # CSRs
    csr_fields = [
        "fflags", "frm", "fcsr", "vstart", "vxsat", "vxrm",
        "vl", "vtype", "vlenb",
        "mstatus", "misa", "mie", "mtvec", "mscratch",
        "mepc", "mcause", "mtval",
    ]
    csr_state = {}
    for name in csr_fields:
        try:
            val = session.get_csr(CSR_NAME_TO_ADDR[name])
            if val is not None:
                csr_state[name] = int(val)
            else:
                csr_state[name] = f"<unsupported: {name}: CSR name not found>"
        except Exception as exc:
            csr_state[name] = f"<unsupported: {name}: {exc}>"
    state["csr"] = csr_state
    # Privilege
    try:
        priv = session.get_privilege_state()
        state["privilege"] = object_to_dict(priv, [
            "prv", "v", "prev_prv", "prev_v", "debug_mode",
            "prv_changed", "v_changed",
        ])
    except Exception as exc:
        state["privilege"] = {"level": f"<unsupported: {exc}>", "virtual": False}
    # Trap state
    try:
        trap = session.get_last_trap_info()
        state["trap"] = object_to_dict(trap, [
            "occurred", "cause", "tval", "tval2", "tinst", "has_gva", "name",
        ])
    except Exception as exc:
        state["trap"] = {"occurred": False, "cause": f"<unsupported: {exc}>"}
    # Vector state
    try:
        vector_state = session.get_vector_state(include_vector_regfile)
        vec = object_to_dict(vector_state, [
            "vl", "vtype", "vstart", "vxsat", "vxrm",
            "vlenb", "vlmax", "vsew", "vflmul",
            "vma", "vta", "vill", "VLEN", "ELEN",
        ])
        if include_vector_regfile:
            vec["vreg_file_hash"] = hash_bytes(bytes(vector_state.vreg_file))
        state["vector"] = vec
    except Exception as exc:
        state["vector"] = {"vl": f"<unsupported: {exc}>"}
    # Reservation state
    try:
        res = session.get_reservation_state()
        state["reservation"] = object_to_dict(res, [
            "valid", "address",
        ])
    except Exception as exc:
        state["reservation"] = {"reserved": False}
    # Debug state
    try:
        dbg = session.get_debug_state()
        state["debug"] = object_to_dict(dbg, [
            "debug_mode", "single_step", "critical_error", "elp", "serialized",
        ])
    except Exception as exc:
        state["debug"] = {"debug_mode": False}
    # Memory regions touched by the rollback stress cases.
    try:
        mem_start, mem_size = session.get_mem_region_info()
        sample_size = min(memory_bytes, mem_size)
        state["memory"] = {
            "start": int(mem_start),
            "bytes": int(sample_size),
            "sha256_16": hash_bytes(session.read_memory(mem_start, sample_size)),
        }
    except Exception as exc:
        state["memory"] = {"sha256_16": f"<unsupported: mem_region: {exc}>"}
    try:
        stack_start, stack_size = session.get_stack_region_info()
        sample_size = min(stack_memory_bytes, stack_size)
        state["stack"] = {
            "start": int(stack_start),
            "bytes": int(sample_size),
            "sha256_16": hash_bytes(session.read_memory(stack_start, sample_size)),
        }
    except Exception as exc:
        state["stack"] = {"sha256_16": f"<unsupported: stack_region: {exc}>"}
    return state


def diff_state(left: dict, right: dict, prefix: str = "") -> list[str]:
    """Return field paths whose values differ between two state snapshots."""
    mismatches = []
    for key in left:
        path = f"{prefix}.{key}" if prefix else key
        left_value = left[key]
        right_value = right.get(key, "<missing>")
        if isinstance(left_value, dict) and isinstance(right_value, dict):
            mismatches.extend(diff_state(left_value, right_value, path))
        elif left_value != right_value:
            mismatches.append(f"{path}: {left_value} != {right_value}")
    for key in right:
        if key not in left:
            path = f"{prefix}.{key}" if prefix else key
            mismatches.append(f"{path}: <missing> != {right[key]}")
    return mismatches


def split_transient_mismatches(mismatches: list[str]):
    """Split architectural mismatches from known transient execution metadata."""
    relevant = []
    ignored = []
    for mismatch in mismatches:
        field = mismatch.split(":")[0].strip()
        if any(field.startswith(t) for t in DEFAULT_TRANSIENT_FIELDS):
            ignored.append(mismatch)
        else:
            relevant.append(mismatch)
    return relevant, ignored


def collect_unsupported(state: dict) -> list[str]:
    """Collect unsupported state fields from a snapshot."""
    unsupported = []
    for key, value in state.items():
        if isinstance(value, str) and value.startswith("<unsupported:"):
            unsupported.append(f"{key}: {value}")
        elif isinstance(value, dict):
            for child in collect_unsupported(value):
                unsupported.append(f"{key}.{child}")
    return unsupported


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------
def make_session(elf_path: str, isa: str, num_instrs: int) -> SpikeSession:
    """Create and initialize a SpikeSession."""
    try:
        session = SpikeSession(elf_path, isa, num_instrs)
        if not session.initialize():
            raise RuntimeError("SpikeSession.initialize() returned False")
        return session
    except Exception as exc:
        raise RuntimeError(f"failed to initialize SpikeSession: {exc}") from exc


# ---------------------------------------------------------------------------
# Execution helpers
# ---------------------------------------------------------------------------
def execute(session: SpikeSession, encoder: HybridEncoder, sequence: InstructionSequence):
    """Execute a sequence and return whether Spike reported a trap."""
    codes, sizes = encode_sequence(encoder, sequence)
    session.execute_sequence(codes, sizes, max(len(codes) * 4, 10_000))
    trap = session.get_last_trap_info()
    return bool(trap.occurred) if hasattr(trap, "occurred") else False


def execute_without_trap_query(
    session: SpikeSession,
    encoder: HybridEncoder,
    sequence: InstructionSequence,
) -> None:
    """Execute an accepted sequence with enough step budget for expanded instructions."""
    codes, sizes = encode_sequence(encoder, sequence)
    session.execute_sequence(codes, sizes, max(len(codes) * 4, 100))


# ---------------------------------------------------------------------------
# Core test case runner
# ---------------------------------------------------------------------------
def run_case(
    elf_path: str,
    isa: str,
    num_instrs: int,
    accepted_prefix: InstructionSequence,
    rejected: InstructionSequence,
    accepted_after: InstructionSequence,
    memory_bytes: int,
    stack_memory_bytes: int,
    include_vector_regfile: bool,
    allow_unsupported: bool,
) -> CaseResult:
    """Run local rollback and fresh replay oracles for one rejected candidate."""
    result = CaseResult(name=rejected.name, category=rejected.category)

    # Create persistent session
    persistent = make_session(elf_path, isa, num_instrs)
    encoder = HybridEncoder()

    # Execute accepted prefix
    if accepted_prefix:
        execute_without_trap_query(persistent, encoder, accepted_prefix)

    # --- Oracle 1: Local rollback ---
    # Snapshot state before rejected candidate
    sequence = rejected
    before = snapshot_state(persistent, memory_bytes, stack_memory_bytes, include_vector_regfile)

    # Set checkpoint
    checkpoint_start = time.perf_counter()
    persistent.set_checkpoint()
    result.checkpoint_seconds = time.perf_counter() - checkpoint_start

    # Execute rejected candidate
    trapped = execute(persistent, encoder, sequence)
    result.trapped = trapped

    # Rollback
    rollback_start = time.perf_counter()
    persistent.restore_checkpoint_and_reset()
    result.rollback_seconds = time.perf_counter() - rollback_start

    # Compare state after restore
    after_restore = snapshot_state(persistent, memory_bytes, stack_memory_bytes, include_vector_regfile)
    raw_local = diff_state(before, after_restore)
    result.local_mismatches, result.ignored_local_mismatches = split_transient_mismatches(raw_local)
    result.unsupported = collect_unsupported(after_restore)

    # --- Oracle 2: Fresh replay ---
    # Execute accepted prefix + rejected rollback + accepted_after in persistent
    if accepted_after:
        execute_without_trap_query(persistent, encoder, accepted_after)
    persistent_state = snapshot_state(persistent, memory_bytes, stack_memory_bytes, include_vector_regfile)

    # Fresh session: replay only accepted_prefix + accepted_after
    try:
        fresh = make_session(elf_path, isa, num_instrs)
        if accepted_prefix:
            execute_without_trap_query(fresh, encoder, accepted_prefix)
        if accepted_after:
            execute_without_trap_query(fresh, encoder, accepted_after)
        fresh_state = snapshot_state(fresh, memory_bytes, stack_memory_bytes, include_vector_regfile)
    except Exception as exc:
        result.replay_mismatches.append(f"fresh_session_error: {exc}")
        result.error = str(exc)
        return result

    raw_replay = diff_state(persistent_state, fresh_state)
    result.replay_mismatches, result.ignored_replay_mismatches = split_transient_mismatches(raw_replay)
    if not allow_unsupported and result.unsupported:
        pass  # keep them; the caller can decide

    return result


# ---------------------------------------------------------------------------
# Test case factories
# ---------------------------------------------------------------------------
def deterministic_cases(
    mem_start: int,
) -> tuple[InstructionSequence, list[InstructionSequence], InstructionSequence]:
    """Build deterministic accepted prefix and rejected candidate matrix."""
    prefix = InstructionSequence(
        name="setup",
        instructions=(
            "li x1, 0x12345678",
            "li x2, 0x87654321",
            f"li x10, {mem_start}",
            "li x11, 0xAABBCCDD",
        ),
        category="setup",
    )
    rejected_list: list[InstructionSequence] = []
    accepted_after = InstructionSequence(
        name="accepted",
        instructions=("addi x3, x2, 1",),
        category="accepted",
    )

    # GPR arithmetic
    rejected_list.append(InstructionSequence(
        name="gpr_add",
        instructions=("add x5, x1, x2",),
        category="GPR",
    ))
    rejected_list.append(InstructionSequence(
        name="gpr_shift",
        instructions=("slli x5, x1, 3",),
        category="GPR",
    ))

    # Memory store
    rejected_list.append(InstructionSequence(
        name="memory_store",
        instructions=(f"sw x11, 0(x10)",),
        category="Memory",
    ))

    # Stack memory store (compressed SP)
    rejected_list.append(InstructionSequence(
        name="stack_memory_store",
        instructions=("c.swsp x11, 0",),
        category="Stack-Memory",
    ))

    # CSR mscratch
    rejected_list.append(InstructionSequence(
        name="csr_mscratch",
        instructions=("csrw mscratch, x1",),
        category="CSR",
    ))

    # FP flags
    rejected_list.append(InstructionSequence(
        name="fp_flags",
        instructions=("fadd.s f0, f1, f2",),
        category="FPR/FP flags",
    ))

    # Multi-instruction pseudo
    rejected_list.append(InstructionSequence(
        name="multi_pseudo_li",
        instructions=("li x6, 0x123456789ABC",),
        category="Multi-instruction",
    ))

    # Branch not taken
    rejected_list.append(InstructionSequence(
        name="branch_not_taken",
        instructions=("beq x1, x2, 8",),
        category="Branch/PC",
    ))

    # Exception ecall
    rejected_list.append(InstructionSequence(
        name="exception_ecall",
        instructions=("ecall",),
        category="Exception",
    ))

    # AMO add
    rejected_list.append(InstructionSequence(
        name="amo_add",
        instructions=("amoadd.w x5, x1, (x10)",),
        category="AMO/LRSC",
    ))

    # LR/SC reservation
    rejected_list.append(InstructionSequence(
        name="lr_reservation",
        instructions=("lr.w x5, (x10)",),
        category="AMO/LRSC",
    ))

    # Vector config
    rejected_list.append(InstructionSequence(
        name="vector_config",
        instructions=("vsetvli x5, x1, e32, m1",),
        category="Vector",
    ))

    # Vector register file
    rejected_list.append(InstructionSequence(
        name="vector_regfile",
        instructions=("vsetvli x5, x1, e32, m1", "vmv.v.i v0, 1"),
        category="Vector-Regfile",
    ))

    return prefix, rejected_list, accepted_after


def random_gpr_cases(count: int, seed: int) -> list[InstructionSequence]:
    """Generate simple random GPR rejected candidates for rollback stress."""
    rng = random.Random(seed)
    opcodes = ["add", "sub", "xor", "or", "and", "slli", "srli", "srai", "sll", "srl", "sra"]
    cases = []
    for index in range(count):
        rd = rng.randint(5, 31)
        rs1 = rng.randint(1, 31)
        rs2 = rng.randint(1, 31)
        opcode = rng.choice(opcodes)
        if opcode in {"slli", "srli", "srai"}:
            shamt = rng.randint(0, 63)
            instruction = f"{opcode} x{rd}, x{rs1}, {shamt}"
        else:
            instruction = f"{opcode} x{rd}, x{rs1}, x{rs2}"
        cases.append(InstructionSequence(
            name=f"random_gpr_{index:04d}",
            instructions=(instruction,),
            category="Random-GPR",
        ))
    return cases


def random_memory_cases(count: int, seed: int) -> list[InstructionSequence]:
    """Generate random memory-side-effect rejected candidates."""
    rng = random.Random(seed)
    stores = [
        ("sb", 1), ("sh", 2), ("sw", 4), ("sd", 8),
    ]
    cases = []
    for index in range(count):
        opcode, _ = rng.choice(stores)
        offset = rng.randint(0, 2040) // 4 * 4
        rs = rng.randint(5, 31)
        cases.append(InstructionSequence(
            name=f"random_memory_{index:04d}",
            instructions=(f"{opcode} x{rs}, {offset}(x10)",),
            category="Random-Memory",
        ))
    return cases


def random_stack_memory_cases(count: int, seed: int) -> list[InstructionSequence]:
    """Generate random stack-memory rejected candidates using compressed SP instructions."""
    rng = random.Random(seed)
    stores = ["c.swsp", "c.sdsp"]
    cases = []
    for index in range(count):
        opcode = rng.choice(stores)
        rs = rng.randint(8, 15)
        offset = rng.choice([0, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48, 52, 56, 60])
        cases.append(InstructionSequence(
            name=f"random_stack_memory_{index:04d}",
            instructions=(f"{opcode} x{rs}, {offset}",),
            category="Random-Stack-Memory",
        ))
    return cases


def random_csr_cases(count: int, seed: int) -> list[InstructionSequence]:
    """Generate random writable-CSR rejected candidates using mscratch."""
    rng = random.Random(seed)
    opcodes = ["csrrw", "csrrs", "csrrc"]
    cases = []
    for index in range(count):
        opcode = rng.choice(opcodes)
        rd = rng.randint(5, 31)
        rs = rng.randint(1, 31)
        cases.append(InstructionSequence(
            name=f"random_csr_{index:04d}",
            instructions=(f"{opcode} x{rd}, mscratch, x{rs}",),
            category="Random-CSR",
        ))
    return cases


def random_fp_cases(count: int, seed: int) -> list[InstructionSequence]:
    """Generate random floating-point rejected candidates."""
    rng = random.Random(seed)
    opcodes = ["fadd.s", "fsub.s", "fmul.s", "fdiv.s", "fmin.s", "fmax.s"]
    cases = []
    for index in range(count):
        opcode = rng.choice(opcodes)
        fd = rng.randint(0, 31)
        fs1 = rng.randint(0, 31)
        fs2 = rng.randint(0, 31)
        cases.append(InstructionSequence(
            name=f"random_fp_{index:04d}",
            instructions=(f"{opcode} f{fd}, f{fs1}, f{fs2}",),
            category="Random-FP",
        ))
    return cases


def random_vector_cases(count: int, seed: int) -> list[InstructionSequence]:
    """Generate random vector-configuration rejected candidates."""
    rng = random.Random(seed)
    sew_values = [8, 16, 32, 64]
    lmul_values = ["mf8", "mf4", "mf2", "m1", "m2", "m4", "m8"]
    policies = ["ta, ma", "tu, ma", "ta, mu", "tu, mu"]
    cases = []
    for index in range(count):
        rd = rng.randint(5, 31)
        rs1 = rng.randint(1, 31)
        sew = rng.choice(sew_values)
        lmul = rng.choice(lmul_values)
        policy = rng.choice(policies)
        # Some cases just vsetvli, some include vmv.v.i
        if rng.random() < 0.5:
            instructions = (f"vsetvli x{rd}, x{rs1}, e{sew}, {lmul}, {policy}",)
        else:
            instructions = (
                f"vsetvli x{rd}, x{rs1}, e{sew}, {lmul}, {policy}",
                "vmv.v.i v0, 1",
            )
        cases.append(InstructionSequence(
            name=f"random_vector_{index:04d}",
            instructions=instructions,
            category="Random-Vector",
        ))
    return cases


def random_branch_cases(count: int, seed: int) -> list[InstructionSequence]:
    """Generate random branch/PC rejected candidates."""
    rng = random.Random(seed)
    not_taken_forms = {
        "beq": "beq x1, x2, 8",
        "bne": "bne x1, x1, 8",
        "blt": "blt x1, x1, 8",
        "bge": "bge x1, x2, 8",
        "bltu": "bltu x1, x1, 8",
        "bgeu": "bgeu x1, x2, 8",
    }
    opcodes = list(not_taken_forms)
    cases = []
    for index in range(count):
        opcode = rng.choice(opcodes)
        instruction = not_taken_forms[opcode]
        cases.append(InstructionSequence(
            name=f"random_branch_{index:04d}",
            instructions=(instruction,),
            category="Random-Branch",
        ))
    return cases


def random_exception_cases(count: int, seed: int) -> list[InstructionSequence]:
    """Generate random trap-path rejected candidates."""
    rng = random.Random(seed)
    instructions = ["ecall", "ebreak", "unimp"]
    cases = []
    for index in range(count):
        instr = rng.choice(instructions)
        cases.append(InstructionSequence(
            name=f"random_exception_{index:04d}",
            instructions=(instr,),
            category="Random-Exception",
        ))
    return cases


def random_amo_cases(count: int, seed: int) -> list[InstructionSequence]:
    """Generate random AMO rejected candidates."""
    rng = random.Random(seed)
    opcodes = ["amoadd.w", "amoxor.w", "amoor.w", "amoand.w", "amoswap.w"]
    cases = []
    for index in range(count):
        opcode = rng.choice(opcodes)
        rd = rng.randint(5, 31)
        rs = rng.randint(1, 31)
        cases.append(InstructionSequence(
            name=f"random_amo_{index:04d}",
            instructions=(f"{opcode} x{rd}, x{rs}, (x10)",),
            category="Random-AMO",
        ))
    return cases


def random_mixed_cases(
    count_per_category: int,
    seed: int,
    memory_stack_count: int | None = None,
) -> list[InstructionSequence]:
    """Generate mixed random rejected candidates across architectural state classes."""
    cases = []
    rng_seeds = {}
    base = seed

    # Each category gets a unique seed derived from the base seed
    for cat_name, gen_fn in [
        ("GPR", random_gpr_cases),
        ("Memory", random_memory_cases),
        ("Stack-Memory", random_stack_memory_cases),
        ("CSR", random_csr_cases),
        ("FP", random_fp_cases),
        ("Vector", random_vector_cases),
        ("Branch", random_branch_cases),
        ("Exception", random_exception_cases),
        ("AMO", random_amo_cases),
    ]:
        cat_seed = hash((base, cat_name)) & 0xFFFFFFFF
        case_count = count_per_category
        if memory_stack_count is not None and cat_name in {"Memory", "Stack-Memory"}:
            case_count = memory_stack_count
        cases.extend(gen_fn(case_count, cat_seed))

    return cases


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rollback correctness experiment for AstraFuzz persistent Spike execution."
    )
    parser.add_argument("--isa", default="rv64imafdcv_zicsr_zifencei_zba_zbb_zbc_zbs_zfh")
    parser.add_argument("--template-type", default="xiangshan")
    parser.add_argument("--num-instrs", type=int, default=100)
    parser.add_argument("--memory-bytes", type=int, default=4096)
    parser.add_argument("--stack-memory-bytes", type=int, default=1024)
    parser.add_argument("--random-cases", type=positive_int, default=None,
                        help="Number of random cases per category (uses dedicated seed=0)")
    parser.add_argument("--random-mixed-cases", type=positive_int, default=None,
                        help="Number of random cases per category (mixed, uses --seed)")
    parser.add_argument("--memory-stack-random-cases", type=positive_int, default=None,
                        help="Override random Memory and Stack-Memory cases per seed")
    parser.add_argument("--seed", type=non_negative_int, default=0)
    parser.add_argument("--include-vector-regfile", action="store_true")
    parser.add_argument("--allow-unsupported", action="store_true")
    parser.add_argument("--output", default="/tmp/rollback_correctness_results.json")
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Summary & reporting
# ---------------------------------------------------------------------------
def summarize(results: list[CaseResult]) -> dict:
    by_category: dict[str, CategorySummary] = {}
    for result in results:
        cat = result.category
        if cat not in by_category:
            by_category[cat] = CategorySummary()
        by_category[cat].add(result)

    summary = {
        "by_category": {name: cat.to_dict() for name, cat in sorted(by_category.items())},
        "total_cases": len(results),
        "total_passed": sum(1 for r in results if r.passed()),
        "total_local_mismatches": sum(len(r.local_mismatches) for r in results),
        "total_replay_mismatches": sum(len(r.replay_mismatches) for r in results),
        "total_errors": sum(1 for r in results if r.error),
        "total_unsupported": len(set().union(*(set(r.unsupported) for r in results))),
    }
    # Compute overall averages
    t_ckpt = sum(r.checkpoint_seconds for r in results)
    t_rbck = sum(r.rollback_seconds for r in results)
    n = max(len(results), 1)
    summary["checkpoint_seconds_avg"] = t_ckpt / n
    summary["rollback_seconds_avg"] = t_rbck / n
    return summary


def print_markdown_summary(summary: dict) -> None:
    print("""
| Test category | Cases | Passed | Local mismatches | Replay mismatches | Errors | Unsupported | Avg checkpoint ms | Avg rollback ms |
|---|---:|---:|---:|---:|---:|---|---:|---:|""")
    by_category = summary["by_category"]
    for category_name, cat in sorted(by_category.items()):
        unsorted_text = ", ".join(sorted(cat.get("unsupported", [])))
        unsupported_text = unsorted_text if unsorted_text else "-"
        print(
            f"| {category_name} "
            f"| {cat['cases']} "
            f"| {cat['passed']} "
            f"| {cat['local_mismatches']} "
            f"| {cat['replay_mismatches']} "
            f"| {cat['errors']} "
            f"| {unsupported_text} "
            f"| {cat['checkpoint_seconds_avg']*1000:.3f} "
            f"| {cat['rollback_seconds_avg']*1000:.3f} "
            f"|"
        )

    # Totals row
    print(
        f"| **Total** "
        f"| {summary['total_cases']} "
        f"| {summary['total_passed']} "
        f"| {summary['total_local_mismatches']} "
        f"| {summary['total_replay_mismatches']} "
        f"| {summary['total_errors']} "
        f"| {summary['total_unsupported']} "
        f"| {summary['checkpoint_seconds_avg']*1000:.3f} "
        f"| {summary['rollback_seconds_avg']*1000:.3f} "
        f"|"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    arch = ArchConfig(64, args.isa)
    template = create_template_instance(arch, args.template_type)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Generate NOP ELF for spike initialization
    elf_path = f"/dev/shm/rollback_correctness_{os.getpid()}.elf"
    generate_nop_elf(template, args.num_instrs, elf_path)

    # Probe memory layout
    probe = make_session(elf_path, args.isa, args.num_instrs)
    mem_start, _ = probe.get_mem_region_info()
    mem_start = int(mem_start)
    probe.cleanup()

    # Build test cases
    prefix, rejected_deterministic, accepted_after = deterministic_cases(mem_start)

    rejected_cases = list(rejected_deterministic)

    # Add random mixed cases if requested
    if args.random_mixed_cases:
        mixed = random_mixed_cases(
            args.random_mixed_cases,
            args.seed,
            args.memory_stack_random_cases,
        )
        rejected_cases.extend(mixed)
    elif args.random_cases:
        rng = random.Random(args.seed)
        for fn, cat, kw in [
            (random_gpr_cases, "Random-GPR", {}),
            (random_memory_cases, "Random-Memory", {}),
            (random_stack_memory_cases, "Random-Stack-Memory", {}),
            (random_csr_cases, "Random-CSR", {}),
            (random_fp_cases, "Random-FP", {}),
            (random_vector_cases, "Random-Vector", {}),
            (random_branch_cases, "Random-Branch", {}),
            (random_exception_cases, "Random-Exception", {}),
            (random_amo_cases, "Random-AMO", {}),
        ]:
            cat_seed = hash((args.seed, cat)) & 0xFFFFFFFF
            case_count = args.random_cases
            if args.memory_stack_random_cases is not None and cat in {
                "Random-Memory",
                "Random-Stack-Memory",
            }:
                case_count = args.memory_stack_random_cases
            rejected_cases.extend(fn(case_count, cat_seed))

    # Run all cases
    results: list[CaseResult] = []
    for rejected in rejected_cases:
        result = run_case(
            elf_path=elf_path,
            isa=args.isa,
            num_instrs=args.num_instrs,
            accepted_prefix=prefix,
            rejected=rejected,
            accepted_after=accepted_after,
            memory_bytes=args.memory_bytes,
            stack_memory_bytes=args.stack_memory_bytes,
            include_vector_regfile=args.include_vector_regfile,
            allow_unsupported=args.allow_unsupported,
        )
        results.append(result)

    # Summarize
    summary = summarize(results)
    print_markdown_summary(summary)

    # Write output
    payload = {
        "config": {
            "isa": args.isa,
            "template_type": args.template_type,
            "num_instrs": args.num_instrs,
            "memory_bytes": args.memory_bytes,
            "stack_memory_bytes": args.stack_memory_bytes,
            "include_vector_regfile": args.include_vector_regfile,
            "allow_unsupported": args.allow_unsupported,
            "random_cases": args.random_cases,
            "random_mixed_cases": args.random_mixed_cases,
            "memory_stack_random_cases": args.memory_stack_random_cases,
            "seed": args.seed,
            "elf_path": elf_path,
        },
        "results": [
            {
                "name": r.name,
                "category": r.category,
                "local_mismatches": r.local_mismatches,
                "replay_mismatches": r.replay_mismatches,
                "ignored_local_mismatches": r.ignored_local_mismatches,
                "ignored_replay_mismatches": r.ignored_replay_mismatches,
                "unsupported": r.unsupported,
                "checkpoint_seconds": r.checkpoint_seconds,
                "rollback_seconds": r.rollback_seconds,
                "trapped": r.trapped,
                "error": str(r.error) if r.error else None,
            }
            for r in results
        ],
        "summary": summary,
    }

    with open(output_path, "w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    # Print pass/fail summary
    failed = [r for r in results if not r.passed()]
    if failed:
        print(f"\nFailed cases ({len(failed)}):")
        for r in failed:
            print(f"  {r.category}/{r.name}: "
                  f"local={len(r.local_mismatches)}, "
                  f"replay={len(r.replay_mismatches)}, "
                  f"unsupported={len(r.unsupported)}, "
                  f"error={r.error}")
    else:
        print(f"\nAll {len(results)} cases passed.")


if __name__ == "__main__":
    main()
