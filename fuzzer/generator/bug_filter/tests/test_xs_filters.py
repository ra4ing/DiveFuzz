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

import unittest

from fuzzer.generator.bug_filter.context import FilterContext
from fuzzer.generator.asm_template_manager.riscv_asm_syntex.csr import CSR
from fuzzer.generator.bug_filter.arch.xs_filters import (
    HSTATEEN0_ADDR,
    MSTATEEN0_ADDR,
    STATEEN0_ENVCFG_MASK,
    w1_tvec_mode_filter,
    w16_senvcfg_filter,
    w17_henvcfg_filter,
)


class FakePreState:
    def __init__(self, privilege, virtualization=False, csrs=None, xprs=None):
        self.privilege = privilege
        self.virtualization = virtualization
        self._csrs = csrs or {}
        self._xprs = xprs or {}

    def get_csr(self, addr):
        return self._csrs.get(addr, 0)

    def get_xpr(self, idx):
        return self._xprs.get(idx, 0)


def make_context(
    privilege,
    virtualization=False,
    csrs=None,
    operands=None,
    opcode="csrrwi",
    xprs=None,
):
    return FilterContext(
        opcode=opcode,
        operands=operands or ["zero", "senvcfg", "0"],
        s_pre=FakePreState(privilege, virtualization, csrs, xprs),
    )



class XSTvecModeFilterTest(unittest.TestCase):
    def test_rejects_seed_6_csrrs_vstvec_reserved_effective_mode(self):
        ctx = make_context(
            privilege=1,
            opcode="csrrs",
            operands=["ra", "vstvec", "t2"],
            csrs={0x205: 0x00000000800010E0},
            xprs={7: 0x7FFFFFFFFFFFFFFF},
        )

        result = w1_tvec_mode_filter.check(ctx)

        self.assertTrue(result.should_filter)
        self.assertIn("MODE=3", result.reason)

    def test_rejects_seed_5_csrrs_vstvec_reserved_effective_mode(self):
        ctx = make_context(
            privilege=3,
            opcode="csrrs",
            operands=["s4", "vstvec", "t4"],
            csrs={CSR.VSTVEC: 0},
            xprs={29: 0xFFFFFFFFFFFFFFFF},
        )

        result = w1_tvec_mode_filter.check(ctx)

        self.assertTrue(result.should_filter)
        self.assertIn("MODE=3", result.reason)

    def test_accepts_csrrs_when_effective_mode_stays_legal(self):
        ctx = make_context(
            privilege=1,
            opcode="csrrs",
            operands=["ra", "vstvec", "t2"],
            csrs={0x205: 0x00000000800010E0},
            xprs={7: 0x0000000000000001},
        )

        result = w1_tvec_mode_filter.check(ctx)

        self.assertFalse(result.should_filter)

    def test_accepts_csrrc_that_clears_reserved_mode_to_legal(self):
        ctx = make_context(
            privilege=1,
            opcode="csrrc",
            operands=["ra", "vstvec", "t2"],
            csrs={0x205: 0x00000000800010E3},
            xprs={7: 0x0000000000000002},
        )

        result = w1_tvec_mode_filter.check(ctx)

        self.assertFalse(result.should_filter)


class XSSEnvcfgFilterTest(unittest.TestCase):
    def test_rejects_supervisor_senvcfg_when_mstateen_envcfg_is_clear(self):
        ctx = make_context(privilege=1, csrs={MSTATEEN0_ADDR: 0})

        result = w16_senvcfg_filter.check(ctx)

        self.assertTrue(result.should_filter)
        self.assertIn("mstateen0.ENVCFG=0", result.reason)

    def test_rejects_seed_42_csrrci_senvcfg_when_mstateen_envcfg_is_clear(self):
        ctx = make_context(
            privilege=1,
            csrs={MSTATEEN0_ADDR: 0},
            opcode="csrrci",
            operands=["zero", "senvcfg", "5"],
        )

        result = w16_senvcfg_filter.check(ctx)

        self.assertTrue(result.should_filter)
        self.assertIn("mstateen0.ENVCFG=0", result.reason)

    def test_rejects_senvcfg_pseudo_alias_when_mstateen_envcfg_is_clear(self):
        ctx = make_context(
            privilege=1,
            csrs={MSTATEEN0_ADDR: 0},
            opcode="csrci",
            operands=["senvcfg", "5"],
        )

        self.assertTrue(w16_senvcfg_filter.should_apply(ctx))
        result = w16_senvcfg_filter.check(ctx)

        self.assertTrue(result.should_filter)
        self.assertIn("mstateen0.ENVCFG=0", result.reason)

    def test_accepts_supervisor_senvcfg_when_mstateen_envcfg_is_set(self):
        ctx = make_context(privilege=1, csrs={MSTATEEN0_ADDR: STATEEN0_ENVCFG_MASK})

        result = w16_senvcfg_filter.check(ctx)

        self.assertFalse(result.should_filter)

    def test_rejects_virtual_supervisor_senvcfg_when_hstateen_envcfg_is_clear(self):
        ctx = make_context(
            privilege=1,
            virtualization=True,
            csrs={
                MSTATEEN0_ADDR: STATEEN0_ENVCFG_MASK,
                HSTATEEN0_ADDR: 0,
            },
        )

        result = w16_senvcfg_filter.check(ctx)

        self.assertTrue(result.should_filter)
        self.assertIn("hstateen0.ENVCFG=0", result.reason)

    def test_accepts_virtual_supervisor_senvcfg_when_stateen_envcfg_is_set(self):
        ctx = make_context(
            privilege=1,
            virtualization=True,
            csrs={
                MSTATEEN0_ADDR: STATEEN0_ENVCFG_MASK,
                HSTATEEN0_ADDR: STATEEN0_ENVCFG_MASK,
            },
        )

        result = w16_senvcfg_filter.check(ctx)

        self.assertFalse(result.should_filter)

    def test_does_not_filter_user_or_machine_senvcfg_access(self):
        user_ctx = make_context(privilege=0, csrs={MSTATEEN0_ADDR: 0})
        machine_ctx = make_context(privilege=3, csrs={MSTATEEN0_ADDR: 0})

        self.assertFalse(w16_senvcfg_filter.check(user_ctx).should_filter)
        self.assertFalse(w16_senvcfg_filter.check(machine_ctx).should_filter)

    def test_does_not_filter_other_csr_access(self):
        ctx = make_context(privilege=1, operands=["zero", "menvcfg", "0"])

        result = w16_senvcfg_filter.check(ctx)

        self.assertFalse(result.should_filter)



class XSHEnvcfgFilterTest(unittest.TestCase):
    def test_rejects_seed_34_csrrs_henvcfg(self):
        ctx = make_context(
            privilege=1,
            virtualization=True,
            opcode="csrrs",
            operands=["s6", "henvcfg", "s2"],
        )

        result = w17_henvcfg_filter.check(ctx)

        self.assertTrue(result.should_filter)
        self.assertIn("henvcfg access", result.reason)

    def test_rejects_virtual_user_henvcfg(self):
        ctx = make_context(
            privilege=0,
            virtualization=True,
            opcode="csrrs",
            operands=["s6", "henvcfg", "s2"],
        )

        result = w17_henvcfg_filter.check(ctx)

        self.assertTrue(result.should_filter)

    def test_accepts_non_virtual_user_henvcfg(self):
        ctx = make_context(
            privilege=0,
            virtualization=False,
            opcode="csrrs",
            operands=["s6", "henvcfg", "s2"],
        )

        result = w17_henvcfg_filter.check(ctx)

        self.assertFalse(result.should_filter)

    def test_accepts_machine_henvcfg_with_h_enabled(self):
        """M-mode henvcfg access with H=1: legitimately accessible, no divergence."""
        ctx = make_context(
            privilege=3,
            opcode="csrrwi",
            operands=["s8", "henvcfg", "25"],
            csrs={0x301: 0x80},  # misa.H=1
        )
        result = w17_henvcfg_filter.check(ctx)
        self.assertFalse(result.should_filter)

    def test_rejects_machine_henvcfg_with_h_disabled(self):
        """M-mode henvcfg access with H=0: Spike mcause=22 vs DUT mcause=2."""
        ctx = make_context(
            privilege=3,
            opcode="csrrwi",
            operands=["s8", "henvcfg", "25"],
            # misa.H=0 (default/implicit since not set)
        )
        result = w17_henvcfg_filter.check(ctx)
        self.assertTrue(result.should_filter)
        self.assertIn("M-mode henvcfg", result.reason)
        self.assertIn("mcause=22", result.reason)
        self.assertIn("mcause=2", result.reason)

    def test_accepts_other_envcfg_csrs(self):
        menvcfg_ctx = make_context(
            privilege=3,
            opcode="csrrs",
            operands=["s6", "menvcfg", "s2"],
        )
        senvcfg_ctx = make_context(
            privilege=1,
            opcode="csrrs",
            operands=["s6", "senvcfg", "s2"],
        )

        self.assertFalse(w17_henvcfg_filter.check(menvcfg_ctx).should_filter)
        self.assertFalse(w17_henvcfg_filter.check(senvcfg_ctx).should_filter)

if __name__ == "__main__":
    unittest.main()
