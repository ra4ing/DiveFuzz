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

"""Export an ``MCProgram`` to the bare-metal custom-backend assembly.

Two outputs are produced for the ``xs-custom-harness``:

* ``export_asm``  -> ``seed.S``: per-hart ``litmus_P{N}`` functions (prologue
  noise, address-register setup, the modeled window reusing
  :func:`litmus_exporter._event_instructions`, observed-register capture into
  ``dfmc_obs_flat``), a ``dfmc_init`` function, and the ``.bss`` data layout.
* ``export_meta`` -> ``seed_meta.h``: the ``DFMC_*`` macros + ``dfmc_keys[]``
  the runtime consumes.

The emitted rows use ``"<hart>:<reg>=<v>"`` keys which
``outcome.canonical_key`` maps to ``h{hart}.{reg}`` -- matching
``allowed_outcomes.json`` exactly.
"""

from .model import MCProgram
from .litmus_exporter import _event_instructions

# Each modeled/observed variable gets its own 64-byte cache line so barrier
# sync and result capture (which touch dfmc_obs_flat) cannot impose ordering on
# the modeled locations (dfmc_var_*). `.balign` is byte alignment -> 64 bytes.
_CACHE_LINE = 64


def export_asm(program: MCProgram) -> str:
    """Render ``program`` as a single ``.S`` string for the custom harness."""
    var_index = {v.name: i for i, v in enumerate(program.shared_vars)}
    obs_sorted = sorted(program.observed, key=lambda o: (o.hart, o.reg))
    slot = {(o.hart, o.reg): i for i, o in enumerate(obs_sorted)}

    out: list[str] = []

    # ---- .text: per-hart litmus functions ---- #
    out.append("    .section .text")
    for hp in program.hart_programs:
        out.append(f"    .globl litmus_P{hp.hart_id}")
        out.append(f"litmus_P{hp.hart_id}:")
        for nl in hp.prologue_noise:
            if nl.strip():
                out.append(f"    {nl}")
        # Load each shared var's address into its assigned physical register.
        for var, reg in hp.address_regs.items():
            out.append(f"    la {reg}, dfmc_var_{var_index[var]}")
        # Modeled window: identical asm to the litmus exporter.
        for event in hp.modeled_window:
            for instr in _event_instructions(event, hp.address_regs):
                out.append(f"    {instr}")
        # Observed-register epilogue: store each observed reg into its flat slot.
        for o in obs_sorted:
            if o.hart != hp.hart_id:
                continue
            out.append("    la t0, dfmc_obs_flat")
            out.append(f"    sd {o.reg}, {slot[(o.hart, o.reg)] * 8}(t0)")
        for nl in hp.epilogue_noise:
            if nl.strip():
                out.append(f"    {nl}")
        out.append("    ret")

    # ---- dfmc_init: zero/seed shared vars + obs flat (hart 0 only) ---- #
    out.append("    .globl dfmc_init")
    out.append("dfmc_init:")
    for i, v in enumerate(program.shared_vars):
        out.append(f"    la t0, dfmc_var_{i}")
        if v.init_value == 0:
            out.append("    sd zero, 0(t0)")
        else:
            out.append(f"    li t1, {v.init_value}")
            out.append("    sd t1, 0(t0)")
    out.append("    la t0, dfmc_obs_flat")
    for s in range(len(obs_sorted)):
        out.append(f"    sd zero, {s * 8}(t0)")
    out.append("    ret")

    # ---- .bss: per-var cache lines + the flat observed buffer ---- #
    out.append("    .section .bss")
    for i in range(len(program.shared_vars)):
        out.append(f"    .balign {_CACHE_LINE}")
        out.append(f"dfmc_var_{i}:")
        out.append(f"    .skip {_CACHE_LINE}")
    out.append(f"    .balign {_CACHE_LINE}")
    out.append("    .globl dfmc_obs_flat")
    out.append("dfmc_obs_flat:")
    out.append(f"    .skip {max(len(obs_sorted) * 8, _CACHE_LINE)}")

    return "\n".join(out) + "\n"


def export_meta(program: MCProgram) -> str:
    """Render ``program`` as a ``seed_meta.h`` header for the custom runtime."""
    obs_sorted = sorted(program.observed, key=lambda o: (o.hart, o.reg))
    keys = ", ".join(f'"{o.hart}:{o.reg}"' for o in obs_sorted)

    out = [
        "#pragma once",
        "#include <stdint.h>",
        f'#define DFMC_NAME "{program.name}"',
        f"#define DFMC_NHART {program.hart_count}",
        f"#define DFMC_NVAR {len(program.shared_vars)}",
        f"#define DFMC_NOBS_TOTAL {len(obs_sorted)}",
        "#define DFMC_MAXOBS 8",
        "extern uint64_t dfmc_obs_flat[DFMC_MAXOBS];",
        f"static const char* const dfmc_keys[DFMC_NOBS_TOTAL] = {{ {keys} }};",
    ]
    return "\n".join(out) + "\n"
