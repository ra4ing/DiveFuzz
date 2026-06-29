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


import os
from pathlib import Path
import re
import subprocess
from config.dut_config import GeneratedSeedConfig

from config.divefuzz_config import DiveFuzzArgConfig
from generator.core.mutator import mutate_instructions_parallel
from utils.elf_to_img import process_assembly_files
from generator.core.generator import generate_instructions_parallel
from generator.config.config_manager import setup_config

# Module-level variable to store the Config object
_divefuzz_config = None


def setup_divefuzz(seed_config: GeneratedSeedConfig, global_logger):
    global _divefuzz_config
    # make sure `riscv64-unknown-elf-as`, `riscv64-unknown-elf-gcc`,
    # `riscv64-unknown-elf-ld` and `riscv64-unknown-elf-objcopy` are specified in the environment
    riscv_toolchain = [
        'riscv64-unknown-elf-as', 'riscv64-unknown-elf-gcc', 'riscv64-unknown-elf-ld', 'riscv64-unknown-elf-objcopy'
    ]
    for tool in riscv_toolchain:
        try:
            subprocess.run([tool, '--version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            raise Exception(f"{tool} not found in environment, DiveFuzz will not work.")
    
    # fetch `spike` path
    if 'spike' not in os.environ:
        global_logger.warning("spike not found in environment")
    else:
        spike_path = os.environ['spike']
        
        # check `spike` path contain `DiveFuzz`
        if 'DiveFuzz' not in spike_path:
            global_logger.warning("Your spike path does not contain `DiveFuzz`. Diversity function will not work.")
     
    divefuzz_config = DiveFuzzArgConfig(
        mutation=seed_config.divefuzz.mode == "mutate",
        generate=seed_config.divefuzz.mode == "generate",
        eliminate_enable=seed_config.divefuzz.dive_enable,
        cva6=seed_config.divefuzz.is_cva6,
        rv32=seed_config.divefuzz.is_rv32,
        instr_number=seed_config.divefuzz.ins_num,
        seed_offset=seed_config.divefuzz.seed_offset,
        seeds=seed_config.divefuzz.seeds_num,
        max_workers=seed_config.divefuzz.threads,
        seed_dir=Path(seed_config.divefuzz.seeds_output),
        mutate_out=Path(seed_config.divefuzz.mutate_input) if seed_config.divefuzz.mutate_input else Path.cwd(),
        out_dir=Path(seed_config.divefuzz.seeds_output),
        enable_ext=seed_config.divefuzz.enable_extension,
        exclude_ext=seed_config.divefuzz.exclude_extension if seed_config.divefuzz.exclude_extension else [],
        template_type=seed_config.divefuzz.template_type,
        allowed_ext_name=seed_config.divefuzz.allowed_ext_name,
        architecture=seed_config.divefuzz.architecture,
        bug_filter_enable=seed_config.divefuzz.bug_filter_enable,
        jump_enable=seed_config.divefuzz.jump_enable,
        stateful_xor_cache=seed_config.divefuzz.stateful_xor_cache,
        debug=seed_config.divefuzz.debug,
        debug_mode=seed_config.divefuzz.debug_mode,
        debug_all=seed_config.divefuzz.debug_all,
        debug_no_csr=seed_config.divefuzz.debug_no_csr,
        debug_no_fpr=seed_config.divefuzz.debug_no_fpr,
        xor_cache_expected_seeds=seed_config.divefuzz.xor_cache_expected_seeds,
        clean_cache=seed_config.divefuzz.clean_cache,
    )
    _divefuzz_config = setup_config(divefuzz_config)


def run_divefuzz(seed_config: GeneratedSeedConfig, seed_config_logger) -> list:
    global _divefuzz_config
    assert(_divefuzz_config is not None)
    # handle generate
    if seed_config.divefuzz.mode == "generate":
        debug_config = None
        if seed_config.divefuzz.debug:
            debug_config = {
                "enabled": True,
                "output_dir": str(seed_config.divefuzz.seeds_output),
                "mode": seed_config.divefuzz.debug_mode,
                "accepted_only": not seed_config.divefuzz.debug_all,
                "log_csr": not seed_config.divefuzz.debug_no_csr,
                "log_fpr": not seed_config.divefuzz.debug_no_fpr,
            }

        generate_instructions_parallel(
            instr_number=seed_config.divefuzz.ins_num,
            seed_times=seed_config.divefuzz.seeds_num,
            seed_offset=seed_config.divefuzz.seed_offset,
            eliminate_enable=seed_config.divefuzz.dive_enable,
            is_rv32=seed_config.divefuzz.is_rv32,
            max_workers=seed_config.divefuzz.threads,
            arch=_divefuzz_config.arch,
            template_type=seed_config.divefuzz.template_type,
            out_dir=str(_divefuzz_config.out_dir),
            architecture=_divefuzz_config.architecture,
            debug_config=debug_config,
            stateful_xor_cache=seed_config.divefuzz.stateful_xor_cache,
            bug_filter_enable=seed_config.divefuzz.bug_filter_enable,
            jump_enable=seed_config.divefuzz.jump_enable,
            xor_cache_expected_seeds=_divefuzz_config.xor_cache_expected_seeds,
            clean_cache=_divefuzz_config.clean_cache,
        )

    elif seed_config.divefuzz.mode == "mutate":
        mutate_instructions_parallel(
            directory_path=Path(seed_config.divefuzz.mutate_input) if seed_config.divefuzz.mutate_input else Path.cwd(),
            mutate_directory=Path(seed_config.divefuzz.seeds_output),
            max_workers=seed_config.divefuzz.threads,
            enable_ext=seed_config.divefuzz.enable_extension,
            exclude_extensions=seed_config.divefuzz.exclude_extension if seed_config.divefuzz.exclude_extension else [],
            eliminate_enable=seed_config.divefuzz.dive_enable,
            arch=_divefuzz_config.arch,
            template_type=seed_config.divefuzz.template_type
        )
    else:
        raise ValueError(f"Unknown mode: {seed_config.divefuzz.mode}")

    return process_divefuzz_asm(seed_config, seed_config_logger, seed_offset=seed_config.divefuzz.seed_offset)
        


def process_divefuzz_asm(seed_config: GeneratedSeedConfig, seed_config_logger, seed_offset: int = 0):

    # Use the configured seeds_output directory
    generator_output_dir = Path(seed_config.divefuzz.seeds_output)

    # convert img/elf — use incremental compilation when appending seeds
    incremental = seed_offset > 0
    seed_config_logger.info("Converting assembly to elf files..."
                            + (" (incremental)" if incremental else ""))
    process_assembly_files(str(generator_output_dir), incremental=incremental)

    # find img files (binary format for DUT execution)
    # All DUTs (NutShell, Rocket, XiangShan) use .img format
    img_dir = generator_output_dir / 'img_file'
    if not img_dir.exists():
        seed_config_logger.error(f"IMG directory not found: {img_dir}")
        return []

    seed_files = []
    for file in os.listdir(img_dir):
        if file.endswith(".img"):
            # Extract seed index from filename (e.g., seeds_50_.img -> 50)
            if seed_offset > 0:
                m = re.match(r'seeds_(\d+)_[^/]*\.img$', file)
                if m and int(m.group(1)) < seed_offset:
                    continue
            seed_files.append(os.path.join(img_dir, file))

    seed_config_logger.info(
        f"Found {len(seed_files)} generated seed files (.img)"
        + (f" (starting from #{seed_offset})" if seed_offset > 0 else ""))

    return seed_files