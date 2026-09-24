"""Compare legacy and checkpoint-engine values across control-flow joins."""
import os
import random
import tempfile
import unittest
from pathlib import Path

from generator.asm_template_manager import create_template_instance
from generator.asm_template_manager.riscv_asm_syntex import ArchConfig
from generator.reg_analyzer import _engine_read_sources
from generator.reg_analyzer.engine_session import EngineSession, SPIKE_ENGINE_AVAILABLE
from generator.reg_analyzer.hybrid_encoder import HybridEncoder
from generator.reg_analyzer.instruction_parser import InstructionParser
from generator.reg_analyzer.nop_template_gen import generate_nop_elf, NOP_REDUNDANCY
from generator.reg_analyzer.spike_resolution import Spike

ISA = 'rv64g_v_zicsr_zifencei_zfh_zba_zbb_zbkc_zbc_zbkb_zbs_zmmul_zknh_zkne_zknd_zbkx_zfa'
NOP = 0x13


def taken(e, c):
    e.execute_one(c.encode('addi a0,zero,1'))
    e.execute_one(c.encode('addi a1,zero,1'))
    e.engine.execute_sequence([c.encode('beq a0,a1,.+12'), NOP, NOP], [4]*3, 64)


def not_taken(e, c):
    e.execute_one(c.encode('addi a0,zero,1'))
    e.execute_one(c.encode('addi a1,zero,2'))
    e.execute_one(c.encode('beq a0,a1,.+12'))
    e.execute_one(c.encode('addi t0,zero,7'))
    e.execute_one(c.encode('addi t1,zero,11'))


def backward(e, c):
    e.execute_one(c.encode('addi a0,zero,5'))
    e.execute_one(c.encode('addi s11,zero,3'))
    e.execute_one(c.encode('addi a0,a0,1'))
    e.execute_one(c.encode('addi s11,s11,-1'))
    e.execute_loop_control(c.encode('bne s11,zero,.-8'))


def indirect(e, c):
    e.execute_one(c.encode('addi a0,zero,1'))
    e.execute_one(c.encode('auipc t0,0'))
    e.execute_one(c.encode('addi t0,t0,20'))
    e.engine.execute_sequence([c.encode('jalr ra,0(t0)'), NOP, NOP], [4]*3, 64)


SCENARIOS = (
    ('taken', ['addi a0,zero,1', 'addi a1,zero,1', 'beq a0,a1,fwd_0',
               'addi t0,zero,7', 'addi t1,zero,11', 'fwd_0:'], 'add a2, t0, t1', taken),
    ('not_taken', ['addi a0,zero,1', 'addi a1,zero,2', 'beq a0,a1,fwd_0',
                   'addi t0,zero,7', 'addi t1,zero,11', 'fwd_0:'], 'add a2, t0, t1', not_taken),
    ('backward', ['addi a0,zero,5', 'li s11,3', 'bwd_0:', 'addi a0,a0,1',
                  'addi s11,s11,-1', 'bne s11,zero,bwd_0'], 'add a2, a0, s11', backward),
    ('indirect', ['addi a0,zero,1', 'la t0,fwd_0', 'jalr ra,0(t0)',
                  'addi t1,zero,17', 'addi t2,zero,19', 'fwd_0:'], 'add a2, ra, t1', indirect),
)


@unittest.skipUnless(SPIKE_ENGINE_AVAILABLE, 'compiled spike_engine unavailable')
class ControlFlowEquivalenceTest(unittest.TestCase):
    def test_taken_fallthrough_backward_and_indirect(self):
        repo = Path(__file__).resolve().parents[2]
        spike_build = repo / 'ref/riscv-isa-sim-adapter/build'
        if not (spike_build / 'spike').is_file():
            self.skipTest('patched Spike binary unavailable')
        old_path = os.environ.get('PATH', '')
        os.environ['PATH'] = str(spike_build) + os.pathsep + old_path
        try:
            for name, prefix, candidate, run in SCENARIOS:
                with self.subTest(name=name), tempfile.TemporaryDirectory(dir='/dev/shm') as temp:
                    random.seed(349002)
                    template = create_template_instance(ArchConfig(64, ISA), 'rocket')
                    elf = str(Path(temp) / 'initial.elf')
                    generate_nop_elf(template, 128, elf)
                    e = EngineSession(elf, ISA, 128 + NOP_REDUNDANCY)
                    self.assertTrue(e.initialize())
                    c = HybridEncoder(march=ISA, quiet=True)
                    _, info = InstructionParser.parse_instruction(candidate)
                    payload = '\n'.join(prefix) + '\n' + candidate + '\n li t5,0x2727272727\n'
                    expected = Spike.get_registers_values(info, payload, template)
                    try:
                        run(e, c)
                        e.execute_one(c.encode(candidate) & 0xffffffff)
                        self.assertEqual(expected, _engine_read_sources(info, e))
                    finally:
                        e.close()
        finally:
            os.environ['PATH'] = old_path
