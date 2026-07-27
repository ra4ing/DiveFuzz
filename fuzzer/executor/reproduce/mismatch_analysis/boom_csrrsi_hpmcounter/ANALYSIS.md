# Mismatch Analysis: CSRRSI hpmcounter U-mode mcounteren Check Bug

## Summary

BOOM V4 (MediumBoomV4CosimConfig) fails to enforce `mcounteren` access restrictions
when U-mode executes `CSRRSI` with `uimm=0` on `hpmcounter` CSRs. Spike correctly
raises an illegal-instruction exception.

## Divergence Point

```
Seed:    bug_csrrsi_hpmcounter.elf
PC:      0x80001050
Insn:    0xc0806273 = CSRRSI x4 (tp), hpmcounter8 (CSR 0xC08), uimm=0
Mode:    U-mode (mstatus.MPP=0, entered via mret)
mcounteren: 0x0 (never written, all bits clear)
```

## Evidence

### Spike (Correct Behavior)

From `spike_standalone_trace.log`:

```
core   0: 0x0000000080001050 (0xc0806273) csrrsi  tp, hpmcounter8, 0
core   0: exception trap_illegal_instruction, epc 0x0000000080001050
core   0:           tval 0x00000000c0806273
```

Spike raises illegal-instruction at `0x80001050` → enters M-mode trap handler at
`0x80001000`, increments mepc by 4, returns via mret.

### BOOM V4 (Bug)

From `dut_cosim_output.log`:

```
Cosim: 207543 commit: 80001048    ← TEST 1 done (CSRRCI trapped correctly)
Cosim: 207569 commit: 80001050    ← CSRRSI hpmcounter8 executed, no trap
core   0: 3 0x80001000 (0x34202773) x14 0x0000000000000007  ← Spike traps here
Cosim: 32ad1 PC mismatch spike 80001000 != DUT 80001050
```

BOOM continues past `0x80001050` without trapping. DUT PC=`0x80001050`
(past the CSRRSI), Spike PC=`0x80001000` (in trap handler).

### Control Experiment (TEST 1: CSRRCI)

The same seed places `CSRRCI x14, hpmcounter27, 0` (also uimm=0 pure read) at
`0x80001044` **before** the bug instruction:

```
Cosim: 207379 exception 2                           ← BOOM correctly traps on CSRRCI
Cosim: 207413 commit: 80001000                      ← enters trap handler
```

Both Spike and BOOM correctly trap on CSRRCI. This proves the bug is **specific
to the CSRRSI (funct3=6) instruction path**, not a general mcounteren check failure.

## RISC-V Specification Reference

RISC-V Privileged Architecture v20240411, Section 3.1.11 (`mcounteren`):

> "When the CY, TM, IR, or HPM_n bit in the mcounteren register is clear,
> attempts to read the cycle, time, instret, or hpmcountern register while
> executing in S-mode or U-mode will cause an illegal-instruction exception."

With `mcounteren=0`, all HPM bits are clear. Any attempt to read `hpmcounter8`
from U-mode **must** raise illegal-instruction. CSRRSI with uimm=0 is a read
(no bits to set), so the access check must still apply.

## Test Seed Design

| Test | Instruction            | CSR  | uimm | Spike  | BOOM   | Expected |
|------|------------------------|------|------|--------|--------|----------|
| 1    | CSRRCI x14, hpmcnt27  | 0xC1B| 0    | trap ✓ | trap ✓ | trap     |
| **2**| **CSRRSI x4, hpmcnt8** | **0xC08**| **0** | **trap ✓** | **pass ✗** | **trap** |
| 3    | CSRRWI x6, hpmcnt23   | 0xC17| 0    | trap ✓ | trap ✓ | trap     |

## Verdict

**Real bug in BOOM V4.** The CSRRSI (funct3=6) instruction implementation skips the
`mcounteren` access check for `hpmcounter` CSRs when executed from U-mode with `uimm=0`.
The CSRRCI (funct3=7) path correctly performs this check.

## Files

- `dut_cosim_output.log` — Full BOOM cosim simulation output
- `spike_standalone_trace.log` — Standalone Spike execution trace (first 100 lines)
- `../output/bug_csrrsi_hpmcounter.elf` — Compiled reproduction seed ELF
- `../bug_csrrsi_hpmcounter.S` — Minimal reproduction assembly source
