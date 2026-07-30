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

from ..asm_template_manager.ext_list import allowed_ext
from ..asm_template_manager.riscv_asm_syntex import ArchConfig

# ISA strings for different extension profiles
# Key: allowed_ext_name, Value: (isa_with_c, isa_without_c)
ISA_PROFILES = {
    "cva6": (
        # CVA6: RV64GC + B + ZKN, NO Zfh/Zfhmin
        # NOTE: Use 'gc' (not 'g_c') - standard RISC-V ISA string format
        "rv{bits}gc_zicsr_zifencei_zba_zbb_zbc_zbs_zbkb_zbkc_zbkx_zkne_zknd_zknh",
        "rv{bits}g_zicsr_zifencei_zba_zbb_zbc_zbs_zbkb_zbkc_zbkx_zkne_zknd_zknh",
    ),
    "cva6_cascade": (
        "rv{bits}gc_zicsr_zifencei_zba_zbb_zbc_zbs_zbkb_zbkc_zbkx_zkne_zknd_zknh",
        "rv{bits}g_zicsr_zifencei_zba_zbb_zbc_zbs_zbkb_zbkc_zbkx_zkne_zknd_zknh",
    ),
    # Default profile with all extensions including zfh
    "default": (
        "rv{bits}gc_zicsr_zifencei_zfh_zba_zbb_zbkc_zbc_zbkb_zbs_zmmul_zknh_zkne_zknd_zbkx_zfa",
        "rv{bits}g_zicsr_zifencei_zfh_zba_zbb_zbkc_zbc_zbkb_zbs_zmmul_zknh_zkne_zknd_zbkx_zfa",
    ),
}

MAX_MUTATE_TIME = 10


class Config:
    def __init__(self, args):
        self.mutation_enable = bool(args.mutation)
        self.generate_enable = bool(args.generate)
        self.eliminate_enable = bool(args.eliminate_enable)
        self.is_rv32 = bool(args.rv32)

        # Use command line arguments directly (no auto-override)
        # --allowed-ext-name: extension set (cva6, general, etc.)
        self.allowed_ext_name = str(args.allowed_ext_name)
        allowed_ext.setup_ext(self.allowed_ext_name)

        # --architecture: bug filter (xs, nts, rkt, cva6, etc.)
        # Map CLI architecture names to internal bug_filter names
        arch_mapping = {
            "xiangshan": "xs",
            "nutshell": "nts",
            "rocket": "xs",  # Use XiangShan filters for Rocket (similar RV64GC)
            "cva6": "cva6",
            "boom": "boom",
        }
        self.architecture = arch_mapping.get(args.architecture, args.architecture)

        # --template-type: template (xiangshan, cva6, nutshell, etc.)
        self.template_type = str(args.template_type)

        self.instr_number = int(args.instr_number)
        self.seed_times = int(args.seeds)
        self.xor_cache_expected_seeds = (
            int(args.xor_cache_expected_seeds)
            if args.xor_cache_expected_seeds is not None
            else self.seed_times
        )
        self.clean_cache = bool(getattr(args, 'clean_cache', False))
        self.seed_offset = int(getattr(args, 'seed_offset', 0))
        self.max_workers = max(1, int(args.max_workers))

        self.directory_path = args.seed_dir.resolve()
        self.mutate_directory = (
            args.mutate_out or (self.directory_path / "mutate")
        ).resolve()
        self.out_dir = args.out_dir.resolve()

        self.enable_ext = bool(args.enable_ext)
        self.exclude_extensions = list(args.exclude_ext)

        # Debug configuration
        self.debug_enabled = bool(args.debug)
        self.debug_mode = str(args.debug_mode)
        # Default: only log ACCEPTED instructions (use --debug-all to log all)
        self.debug_accepted_only = not bool(args.debug_all)
        self.debug_log_csr = not bool(args.debug_no_csr)
        self.debug_log_fpr = not bool(args.debug_no_fpr)

        self.stateful_xor_cache = bool(args.stateful_xor_cache)
        self.bug_filter_enable = bool(args.bug_filter_enable)
        self.jump_enable = bool(args.jump_enable)

        self.arch_bits = 32 if self.is_rv32 else 64

        # Build ISA string based on allowed_ext_name profile
        isa_profile = ISA_PROFILES.get(self.allowed_ext_name, ISA_PROFILES["default"])
        has_c_ext = any(ext in allowed_ext.allowed_ext for ext in ["RV64_C", "RV_C"])
        isa_template = isa_profile[0] if has_c_ext else isa_profile[1]
        self.isa = isa_template.format(bits=self.arch_bits)

        self.arch = ArchConfig(self.arch_bits, self.isa)
        self.mutate_time = getattr(args, "mutate_time", MAX_MUTATE_TIME)

        # Multicore (DiveFuzz-MC) configuration
        self.multicore_enable = bool(getattr(args, "multicore", False))
        self.hart_count = getattr(args, "hart_count", None)
        raw_families = getattr(args, "test_family", None)
        self.test_families = list(raw_families) if raw_families else ["SB", "LB", "MP"]
        self.noise_level = str(getattr(args, "noise_level", "none"))
        self.randomize = bool(getattr(args, "randomize", False))
        self.herd_path = str(getattr(args, "herd_path", "herd7"))
        self.litmus_harness_dir = str(getattr(args, "litmus_harness_dir", "fuzzer/multi-core/spike-litmus-harness"))
        self.litmus_runs = int(getattr(args, "litmus_runs", 20))
        self.litmus_size = int(getattr(args, "litmus_size", 20))
        self.build_executable = not bool(getattr(args, "no_build_executable", False))
        self.mc_workers = getattr(args, "mc_workers", None)
        self.use_herd_cache = not bool(getattr(args, "no_herd_cache", False))
        self.herd_cache_dir = getattr(args, "herd_cache_dir", None)


def setup_config(args):
    return Config(args)
