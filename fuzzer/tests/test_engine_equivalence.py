"""The optional engine must reproduce legacy Spike's source-value protocol.

This is a behavioral test: same template, accepted prefix and candidate;
compare the exact values fed to bug filtering and XOR dedup. It includes
legacy quirks (t5 end marker and 128-bit float register display).
"""
import os
import random
import tempfile
import unittest
from pathlib import Path

from generator.asm_template_manager import create_template_instance
from generator.asm_template_manager.riscv_asm_syntex import ArchConfig
from generator.reg_analyzer import _engine_read_sources, temp_asm_to_debug_generate
from generator.reg_analyzer.engine_session import EngineSession, SPIKE_ENGINE_AVAILABLE
from generator.reg_analyzer.hybrid_encoder import HybridEncoder
from generator.reg_analyzer.instruction_parser import InstructionParser
from generator.reg_analyzer.nop_template_gen import generate_nop_elf, NOP_REDUNDANCY
from generator.reg_analyzer.spike_resolution import Spike

ISA = "rv64g_v_zicsr_zifencei_zfh_zba_zbb_zbkc_zbc_zbkb_zbs_zmmul_zknh_zkne_zknd_zbkx_zfa"
PREFIX = (
    "addi a0, zero, 123", "addi a1, zero, 7",
    "addi t0, zero, 11", "addi t1, zero, 3",
    "add s0, a0, a1", "sub s1, t0, t1",
    "fadd.s fa0, fa1, fa2", "fmul.d ft0, ft1, ft2",
)
CANDIDATES = (
    "add a0, a0, a1",          # destination aliases source
    "mul s2, a0, t0",          # independent destination
    "add s2, t5, a1",          # legacy synthetic t5 marker
    "addi t0, t0, -5",         # signed immediate
    "lw s3, 0(sp)",            # integer load
    "sw a0, 16(sp)",           # integer store
    "flw fa3, 0(sp)",          # FP load, integer base
    "fsw fa4, 4(sp)",          # mixed-register legacy rejection
    "fadd.s fa0, fa1, fa2",    # 128-bit FP display
    "fmax.d ft4, ft0, ft1",    # positive NaN with upper 64 bits set
    "fcvt.s.w fa4, a0",       # integer source for FP opcode
    "csrrs s4, 0x341, zero",  # CSR source parsing
)


@unittest.skipUnless(SPIKE_ENGINE_AVAILABLE, "compiled spike_engine unavailable")
class EngineEquivalenceTest(unittest.TestCase):
    def test_source_values_equal_legacy_replay(self):
        # The legacy wrapper requires this repository's patched Spike binary.
        repo = Path(__file__).resolve().parents[2]
        spike_build = repo / "ref/riscv-isa-sim-adapter/build"
        if not (spike_build / "spike").is_file():
            self.skipTest("patched Spike binary unavailable")
        original_path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(spike_build) + os.pathsep + original_path
        random.seed(38172)
        template = create_template_instance(ArchConfig(64, ISA), "rocket")
        with tempfile.TemporaryDirectory(dir="/dev/shm") as temp:
            elf = str(Path(temp) / "initial.elf")
            generate_nop_elf(template, len(PREFIX) + 128, elf)
            session = EngineSession(elf, ISA, len(PREFIX) + 128 + NOP_REDUNDANCY)
            self.assertTrue(session.initialize())
            encoder = HybridEncoder(march=ISA, quiet=True)
            try:
                for instruction in PREFIX:
                    session.execute_one(encoder.encode(instruction) & 0xFFFFFFFF)
                for candidate in CANDIDATES:
                    _, info = InstructionParser.parse_instruction(candidate)
                    payload = "\n".join(PREFIX) + "\n" + candidate + "\n  li t5,0x2727272727\n"
                    legacy = Spike.get_registers_values(info, payload, template)
                    session.set_checkpoint()
                    session.execute_one(encoder.encode(candidate) & 0xFFFFFFFF)
                    actual = _engine_read_sources(info, session)
                    session.rollback()
                    self.assertEqual(legacy, actual, candidate)
            finally:
                session.close()
                os.environ["PATH"] = original_path

    def test_code_three_discards_candidate_and_rolls_back(self):
        # Aligned semantics: a mixed-bank float store is unevaluable (3);
        # the caller discards it, so any engine step must be undone.
        random.seed(77518)
        template = create_template_instance(ArchConfig(64, ISA), "rocket")
        with tempfile.TemporaryDirectory(dir="/dev/shm") as temp:
            elf = str(Path(temp) / "initial.elf")
            generate_nop_elf(template, 80, elf)
            session = EngineSession(elf, ISA, 80 + NOP_REDUNDANCY)
            self.assertTrue(session.initialize())
            try:
                candidate = "fsw fa7, 4(t6)"
                code = HybridEncoder(march=ISA, quiet=True).encode(candidate)
                pc_before = session.get_pc()
                result = temp_asm_to_debug_generate(
                    tuple(), candidate, True, None, template,
                    xor_cache_dir=temp, engine=session, machine_code=code)
                self.assertEqual(result, 3)
                self.assertFalse(session.candidate_executed)
                self.assertEqual(session.get_pc(), pc_before)
            finally:
                session.close()


if __name__ == "__main__":
    unittest.main()
