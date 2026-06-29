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

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import List
from datetime import datetime

@dataclass
class DiveFuzzArgConfig:
    mutation: bool = False
    generate: bool = False
    eliminate_enable: bool = False
    cva6: bool = False
    rv32: bool = False

    allowed_ext_name: str = 'base'
    architecture: str = 'xs'
    template_type: str = 'rocket'

    instr_number: int = 200
    seed_offset: int = 0
    seeds: int = 10
    max_workers: int = (os.cpu_count() or 20)

    prefix = "out"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    folder = f"{prefix}-{timestamp}"

    seed_dir: Path = Path(folder)
    mutate_out: Path = None
    out_dir: Path = Path(folder)

    enable_ext: bool = False
    exclude_ext: List[str] = field(default_factory=list)

    bug_filter_enable: bool = True
    jump_enable: bool = True
    stateful_xor_cache: bool = True

    # Debug configuration (disabled by default for executor usage)
    debug: bool = False
    debug_mode: str = 'FULL'
    debug_all: bool = False
    debug_no_csr: bool = False
    debug_no_fpr: bool = False
    xor_cache_expected_seeds: int | None = None
    clean_cache: bool = False
