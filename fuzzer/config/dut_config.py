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
import re
import yaml
from dataclasses import dataclass, field
from typing import List, Optional, Union, Dict
from config.logger_config import get_global_logger


config_logger = get_global_logger(__name__)

# ---------------------------------------------------------------------------
# Auto seed_offset detection
# ---------------------------------------------------------------------------

# Matches seed filenames like "seeds_42_.S", "seeds_42_.elf", "seeds_42_.img"
_SEED_INDEX_RE = re.compile(r'^seeds_(\d+)_[^/]*\.(S|elf|img)$')


def _detect_seed_offset(seeds_output: str, mode: str) -> int:
    """
    Scan the output directory for existing seed files and return the next
    available seed index (max_existing_index + 1).

    Checks both the top-level directory and the img_file/ subdirectory so
    that partially-compiled batches are handled correctly.
    """
    max_index = -1

    for search_dir in [seeds_output, os.path.join(seeds_output, 'img_file')]:
        if not os.path.isdir(search_dir):
            continue
        for fname in os.listdir(search_dir):
            m = _SEED_INDEX_RE.match(fname)
            if m:
                idx = int(m.group(1))
                if idx > max_index:
                    max_index = idx

    offset = max_index + 1 if max_index >= 0 else 0
    if offset > 0:
        config_logger.info(
            f"Auto-detected seed_offset={offset} "
            f"(found existing seeds up to index {max_index} in {seeds_output})"
        )
    return offset


# ---------------------------------------------------------------------------
# DUT target config
# ---------------------------------------------------------------------------

@dataclass
class DUTTarget:
    name: str
    version: str
    diff_ref: str
    emu_path: str
    cmd: str
    threads: int = 0
    timeout: int = 300
    
    def __post_init__(self):
        self.emu_path = os.path.expanduser(self.emu_path)
        if self.threads == 0:
            config_logger.warning("DUT target config warning: threads is not specified, default to 1 thread")
            self.threads = 1
            

# seed input config
@dataclass
class DiveFuzzConfig:
    gen_only: bool
    threads: int
    dive_enable: bool
    mode: str
    seeds_output: str

    template_type: str
    mutate_input: Optional[str] = None
    enable_extension: bool = True
    exclude_extension: Optional[List[str]] = None
    # Specify which extension set to use: 'nutshell', 'general', 'cva6', etc.
    allowed_ext_name: str = 'base'
    # Architecture for bug filtering: 'xs' (XiangShan), 'nts' (NutShell), 'rkt' (Rocket), 'kmh' (Kunminghu)
    architecture: str = 'xs'

    # generate mode fields
    seeds_num: int = 10
    # seed_offset: integer starting index, or "auto" to detect from existing seeds
    seed_offset: Union[int, str] = 0
    ins_num: int = 200
    is_cva6: bool = False
    is_rv32: bool = False
    bug_filter_enable: bool = True
    jump_enable: bool = True
    stateful_xor_cache: bool = True
    xor_cache_expected_seeds: Optional[int] = None
    clean_cache: bool = False
    debug: bool = False
    debug_mode: str = 'FULL'
    debug_all: bool = False
    debug_no_csr: bool = False
    debug_no_fpr: bool = False
    
    def __post_init__(self):
        self.seeds_output = os.path.expanduser(self.seeds_output)
        if self.mutate_input:
            self.mutate_input = os.path.expanduser(self.mutate_input)
        # Resolve "auto" seed_offset to actual integer
        if isinstance(self.seed_offset, str) and self.seed_offset.lower() == "auto":
            self.seed_offset = _detect_seed_offset(self.seeds_output, self.mode)
        elif isinstance(self.seed_offset, str):
            self.seed_offset = int(self.seed_offset)

# multicore seed input config
@dataclass
class MultiCoreConfig:
    gen_only: bool
    threads: int
    seeds_output: str
    seeds_num: int = 10
    seed_offset: Union[int, str] = 0
    hart_count: int = 2
    runs_per_seed: int = 1
    litmus_runs: int = 20
    litmus_size: int = 20
    test_families: List[str] = field(default_factory=lambda: ["SB", "LB", "MP"])
    noise_level: str = "none"
    herd_path: str = "herd7"
    litmus_harness_dir: str = "multi-core/spike-litmus-harness"
    litmus7_path: Optional[str] = None
    litmus7_share: Optional[str] = None
    randomize: bool = False
    gen_workers: int = field(default_factory=lambda: os.cpu_count() or 4)
    use_herd_cache: bool = True
    herd_cache_dir: Optional[str] = None

    def __post_init__(self):
        self.seeds_output = os.path.expanduser(self.seeds_output)
        self.litmus_harness_dir = os.path.expanduser(self.litmus_harness_dir)
        # Resolve seed_offset: "auto" detects from existing seeds, else int
        if isinstance(self.seed_offset, str) and self.seed_offset.lower() == "auto":
            self.seed_offset = _detect_seed_offset(self.seeds_output, "multicore")
        elif isinstance(self.seed_offset, str):
            self.seed_offset = int(self.seed_offset)
        if self.hart_count < 2:
            raise ValueError("Only hart_count>=2 is supported for multicore mode")
        if self.runs_per_seed < 1:
            raise ValueError("runs_per_seed must be >= 1")
        if self.litmus_runs < 1:
            raise ValueError("litmus_runs must be >= 1")
        if self.litmus_size < 1:
            raise ValueError("litmus_size must be >= 1")

# base class for seed config
@dataclass
class SeedConfigBase:
    name: str

# predefined seed config
@dataclass
class PredefinedSeedConfig(SeedConfigBase):
    path: str
    
    def __post_init__(self):
        self.path = os.path.expanduser(self.path)

# directory seed input config
@dataclass
class DirSeedConfig(PredefinedSeedConfig):
   
    suffix: str

# runtime generated seed config
@dataclass
class GeneratedSeedConfig(SeedConfigBase):
    input_type: str
    divefuzz: DiveFuzzConfig

# multicore seed input config
@dataclass
class MultiCoreSeedConfig(SeedConfigBase):
    input_type: str
    multicore: MultiCoreConfig

# main config parser
@dataclass
class Config:
    dut_target: DUTTarget
    seeds: List[Union[PredefinedSeedConfig, GeneratedSeedConfig]]
    
    @classmethod
    def from_dict(cls, config_dict: Dict) -> 'Config':
        """ create a Config object from a dictionary """
        dut_target = DUTTarget(**config_dict['dut_target'][0])
        
        seeds = []
        for seed_cfg in config_dict.get('seeds', []):
            if 'path' in seed_cfg:
                # is a predefined seed
                if 'input' in seed_cfg:
                    if 'dir' == seed_cfg['input']:
                        # allow `suffix` to be empty
                        seeds.append(DirSeedConfig(
                            name=seed_cfg['name'],
                            path=seed_cfg['path'],
                            suffix=seed_cfg.get('suffix', '')
                        ))
                else:
                    seeds.append(PredefinedSeedConfig(
                        name=seed_cfg['name'],
                        path=seed_cfg['path']
                    ))
            elif seed_cfg.get("input") == "multicore" and "multicore" in seed_cfg:
                seeds.append(MultiCoreSeedConfig(
                    name=seed_cfg["name"],
                    input_type="multicore",
                    multicore=MultiCoreConfig(**seed_cfg["multicore"]),
                ))
            elif 'divefuzz' in seed_cfg:
                seeds.append(GeneratedSeedConfig(
                    name=seed_cfg['name'],
                    input_type=seed_cfg['input'],
                    divefuzz=DiveFuzzConfig(**seed_cfg['divefuzz'])
                ))
        return cls(dut_target=dut_target, seeds=seeds)
    
    @classmethod
    def from_yaml(cls, file_path: str) -> 'Config':
        """ create a Config object from a yaml file """
        with open(file_path, 'r') as f:
            config_dict = yaml.safe_load(f)
        return cls.from_dict(config_dict)
