# BOOM Issue Report

This directory contains a minimized upload package. The assembly source is a reduced reproducer designed to trigger a specific CSR access-control bug on BOOM V4.

## Files to attach

| File | Description | SHA-256 |
|---|---|---|
| `bug_csrrsi_hpmcounter.S` | Reduced, commented assembly reproducer | `ea65268d868a1aa4f27bdabd19355c7c9684acedfe619859727944d532f3432b` |
| `bug_csrrsi_hpmcounter.elf` | ELF built from the reduced assembly | `78200d2debe843465981b51807ade6de3388568aad13839bcd617d5d920e8ce1` |
| `bug_csrrsi_hpmcounter.img` | Binary image (ELF → objcopy -O binary) | `d76e5d5e503ed7f050934ffb63891f62e7bd3eef662fb9da8e2662968c385fc7` |
| `link.ld` | Linker script used to build the ELF | `006132fe05ae025874180b3b8bfec2302c5968218e25c0b3656e38279eafd3d8` |
| `spike_standalone_trace.log` | Standalone Spike execution trace of the reproducer | `6bec610ba16ccbcbc4bb75702b87513079e69cf505f882947ff8af5743d2427d` |
| `dut_cosim_output.log` | BOOM cosim run log showing the PC mismatch | `b4869a00dcc8defd76c7fe347e86a0dbdfa543811ab4dbcfea12e7629c972f17` |
---

## Add a title

U-mode `CSRRSI` with `uimm=0` skips `mcounteren` access check, silently reading restricted `hpmcounter` CSRs

---

## Describe the bug

When BOOM V4 executes `CSRRSI` with `uimm=0` targeting an `hpmcounter` CSR from U-mode while `mcounteren=0`, the instruction is silently committed without raising an illegal-instruction exception. The reference model (Spike) correctly raises the exception.

In the attached reduced repro workload:

- **exception PC / `mepc`**: `0x000000008000105c`
- **faulting instruction bits**: `0xc0806273`
- **disassembly**: `csrrsi tp, hpmcounter8, 0`
- **`mcause`**: `2` (`Illegal instruction`)

The reference model (Spike) reports:

```text
core   0: 0x000000008000105c (0xc0806273) csrrsi  tp, hpmcounter8, 0
core   0: exception trap_illegal_instruction, epc 0x000000008000105c
core   0:           tval 0x00000000c0806273
```

BOOM V4 commits the instruction without any trap. The cosim detects a PC mismatch:

```text
Cosim: 207389 exception 2                      ← CSRRCI correctly traps (both Spike & BOOM)
Cosim: 207433 commit: 80001000                 ← enter trap handler
...                                            ← handler: mcause=2, mepc+=4, mret
Cosim: 207563 commit: 80001054                 ← back to U-mode: li x10, 1
Cosim: 207568 commit: 80001058                 ← sw to mem_region (no fault — clean!)
Cosim: 207631 commit: 8000105c                 ← ← CSRRSI hpmcounter8 COMMITTED (BUG!)
Cosim: 207644 commit: 80001060                 ← BOOM continues to li x10, 2
core   0: 3 0x80001000 (0x34202773) x14 0x0000000000000002  ← Spike mcause=2 (illegal inst)
Cosim: 32b1c PC mismatch spike 80001000 != DUT 80001060
```

**Key evidence:**
- `Cosim: 207389 exception 2`: CSRRCI at `0x80001050` correctly traps on both BOOM and Spike (control passes)
- `Cosim: 207631 commit: 8000105c`: CSRRSI at `0x8000105c` is committed by BOOM **without any preceding `exception`** — the bug
- `Cosim: 207644 commit: 80001060`: BOOM continues past CSRRSI to `li x10, 2`
- Spike `mcause=2` at `0x80001000`: Spike correctly trapped on CSRRSI with illegal-instruction exception
- PC mismatch: Spike at trap handler (`0x80001000`), DUT past CSRRSI (`0x80001060`)

The control experiment — `CSRRCI x14, hpmcounter27, 0` at `0x80001050` (also `uimm=0`, same privilege, same `mcounteren=0`) — correctly traps on both Spike and BOOM:

```text
core   0: 0x0000000080001050 (0xc1b07773) csrrci  a4, hpmcounter27, 0
core   0: exception trap_illegal_instruction, epc 0x0000000080001050
```

The second control — `CSRRWI x6, hpmcounter23, 0` at `0x80001068` — also correctly traps on Spike.

Per the RISC-V Privileged Architecture Manual §3.1.11 (Machine Counter-Enable `mcounteren` Register):

> "When the CY, TM, IR, or HPM_n bit in the `mcounteren` register is clear, attempts to read the `cycle`, `time`, `instret`, or `hpmcountern` register while executing in S-mode or U-mode will cause an illegal-instruction exception."

With `mcounteren=0` (never written, reset default), all HPM bits are clear. Any read of `hpmcounter8` from U-mode **must** raise illegal-instruction. `CSRRSI` with `uimm=0` is a pure read (no bits to set), so the access check must still apply.

Per the RISC-V Unprivileged ISA, Section 6.1 "Zicsr Extension for CSR Instructions":

> "For CSRRSI and CSRRCI, if the uimm[4:0] field is zero, then these instructions will not write to the CSR, and shall not cause any of the side effects that might otherwise occur on a CSR write, nor raise illegal-instruction exceptions on accesses to read-only CSRs. Both CSRRSI and CSRRCI will always read the CSR and cause any read side effects regardless of `rd` and `rs1` fields."

When `uimm=0`, CSRRSI (funct3=6) and CSRRCI (funct3=7) have **identical** semantics: pure read, no write. The fact that CSRRCI correctly traps on BOOM while CSRRSI does not indicates the `mcounteren` check is present but is skipped on the CSRRSI instruction path.

---

## Expected behavior

For the `CSRRSI tp, hpmcounter8, 0` instruction at `mepc = 0x000000008000105c` with `mcounteren=0` and `privilege=U-mode`, BOOM should raise an illegal-instruction exception, matching Spike. The CSRRSI instruction path must perform the same `mcounteren` access check as CSRRCI.

---

## Environment

- **BOOM commit**: `5223e44cfeb26f41380057a2eb4d651197475f69` (chipyard `756ffa75`, BOOM v3.0.0-411)
- **Configuration**: MediumBoomV4CosimConfig
- **ISA**: `rv64imafdc_zicsr_zifencei_zihpm_zba_zbb_zbs_zicntr`
- **Toolchain**: `riscv64-unknown-elf-as/ld` (SiFive GCC/Newlib)
- **Build tool**: Mill

Build commands:

```bash
riscv64-unknown-elf-as \
  -march=rv64imafdc_zicsr_zifencei_zihpm_zba_zbb_zbs_zicntr \
  -c bug_csrrsi_hpmcounter.S -o bug_csrrsi_hpmcounter.o

riscv64-unknown-elf-ld \
  -T ./link.ld bug_csrrsi_hpmcounter.o \
  -o bug_csrrsi_hpmcounter.elf

riscv64-unknown-elf-objcopy -O binary \
  bug_csrrsi_hpmcounter.elf bug_csrrsi_hpmcounter.img
```

---

## To Reproduce


1. Download the attached reduced workload files into one directory:
   - `bug_csrrsi_hpmcounter.S`
   - `bug_csrrsi_hpmcounter.elf`
   - `bug_csrrsi_hpmcounter.img`
   - `link.ld`

2. Verify the reference model behavior (Spike):

   ```bash
   spike --isa=rv64imafdc_zicsr_zifencei_zihpm_zba_zbb_zbs_zicntr \
     --priv msu --pmpregions 8 -l \
     bug_csrrsi_hpmcounter.elf 2>&1 | grep -E "csrr|exception"
   ```

   Expected output showing all three CSR instructions trap:

   ```text
   core   0: 0x0000000080001050 (0xc1b07773) csrrci  a4, hpmcounter27, 0
   core   0: exception trap_illegal_instruction, epc 0x0000000080001050
   core   0: 0x000000008000105c (0xc0806273) csrrsi  tp, hpmcounter8, 0
   core   0: exception trap_illegal_instruction, epc 0x000000008000105c
   core   0: 0x0000000080001068 (0xc1705373) csrrwi  t1, hpmcounter23, 0
   core   0: exception trap_illegal_instruction, epc 0x0000000080001068
   ```

3. Run the attached ELF with `MediumBoomV4CosimConfig` (BOOM Verilator cosim with Spike difftest). The simulation will abort with a PC mismatch.
4. The run aborts with a PC mismatch. BOOM commits the CSRRSI at `0x8000105c` without trapping, while Spike enters the trap handler with `mcause=2` (illegal instruction):

   ```text
   Cosim: 207389 exception 2                      ← CSRRCI correctly traps
   ...
   Cosim: 207631 commit: 8000105c                 ← CSRRSI committed on BOOM (BUG!)
   Cosim: 207644 commit: 80001060                 ← BOOM continues past CSRRSI
   core   0: 3 0x80001000 (csrr x14, mcause) → 2  ← Spike illegal-instruction trap
   Cosim: 32b1c PC mismatch spike 80001000 != DUT 80001060
   ```

5. The relevant instruction window in `bug_csrrsi_hpmcounter.S`:

   ```asm
   main:
     li a1, 0x80100000          # base address for debug stores (mem_region)
     # ---- TEST 1: CSRRCI hpmcounter27 (CONTROL) ----
     csrrci a4, hpmcounter27, 0   # Both trap -> illegal instruction
     li a0, 1; sw a0, 0(a1)       # marker: test 1 passed
     # ---- TEST 2: CSRRSI hpmcounter8 (BUG) ----
     csrrsi tp, hpmcounter8, 0    # Spike traps; BOOM does NOT -> BUG
     li a0, 2; sw a0, 4(a1)       # BOOM reaches here; Spike never does
     # ---- TEST 3: CSRRWI hpmcounter23 (ADDITIONAL CONTROL) ----
     csrrwi t1, hpmcounter23, 0   # Both trap
     li a0, 3; sw a0, 8(a1)
   ```

---

## Bug test design

| Test | Instruction | funct3 | CSR | uimm | Spike | BOOM | Spec Requirement |
|------|-------------|--------|-----|------|-------|------|-----------------|
| 1 (Control) | `CSRRCI x14, hpmcounter27, 0` | 7 | 0xC1B | 0 | trap ✅ | trap ✅ | trap |
| **2 (Bug)** | **`CSRRSI x4, hpmcounter8, 0`** | **6** | **0xC08** | **0** | **trap ✅** | **pass ❌** | **trap** |
| 3 (Control) | `CSRRWI x6, hpmcounter23, 0` | 5 | 0xC17 | 0 | trap ✅ | (N/A) | trap |

- `mcounteren` is **never written** (reset default = 0x0, all HPM bits clear)
- `mstatus.MPP=0` → U-mode after `mret`
- PMP is configured to allow full access (avoids spurious access faults)
- Trap handler reads `mcause`, advances `mepc += 4`, and returns via `mret`

## Additional context / suspected RTL mechanism

This is an instruction-specific CSR access-control bypass. The `mcounteren` permission check exists in BOOM's CSR execution unit, as evidenced by CSRRCI (funct3=7) correctly trapping. The bypass is specific to CSRRSI (funct3=6).

RISC-V CSR instruction funct3 encoding:

| funct3 | Instruction | uimm=0 behavior |
|--------|-------------|-----------------|
| 5 | CSRRWI | Write uimm to CSR, read CSR |
| 6 | CSRRSI | Read CSR, set bits per uimm (uimm=0 → pure read) |
| 7 | CSRRCI | Read CSR, clear bits per uimm (uimm=0 → pure read) |

When `uimm=0`, CSRRSI and CSRRCI are semantically identical (pure read, no write). The asymmetry suggests the `mcounteren` check in BOOM's CSRRSI execution path is either:
- Gated on `uimm != 0` (incorrectly treating `uimm=0` as "no read side effects"), or
- Missing entirely from the CSRRSI micro-op while present in the CSRRCI micro-op.

The fix should ensure that the `mcounteren` access check is performed on **all CSR read operations** for `hpmcounter` CSRs, regardless of funct3 or uimm value.
