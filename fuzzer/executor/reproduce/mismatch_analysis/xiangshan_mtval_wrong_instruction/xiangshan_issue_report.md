# XiangShan Issue Report: Wrong `mtval` for Illegal Instruction

## Add a title

```text
Illegal-instruction mtval contains a later instruction encoding instead of the faulting instruction
```

## Describe the bug

```markdown
When XiangShan takes an illegal-instruction exception, `mtval` is written with a nonzero value that is not the faulting instruction encoding.

In the attached repro, the exception is:

- exception PC / `mepc`: `0x0000000080001030`
- faulting instruction bits: `0x002026f3`
- disassembly: `csrr a3, frm` / `frrm a3`
- `mcause`: `2` (`Illegal instruction`)

However, XiangShan reports:

- expected/reference `mtval`: `0x00000000002026f3`
- XiangShan `mtval`: `0x00000000c02cf5d3`

The wrong value `0xc02cf5d3` is not the faulting instruction. It is the instruction encoding at `PC + 8`:

```text
0x80001030: 0x002026f3   csrr a3, frm    <-- faulting instruction
0x80001038: 0xc02cf5d3   fcvt.l.s a1, fs9
```

Standalone Spike on the same ELF traps at the same PC and reports `tval = 0x00000000002026f3`.

Per the RISC-V Privileged Spec, `mtval` may be zero for illegal-instruction exceptions, but if it is written with a nonzero value, it must contain the faulting instruction bits. XiangShan documentation also states that for exception cause 2, `tval` is updated with the illegal instruction encoding.

Please see the attached logs and workload files:
- `original_rerun_dut.log`
- `original_spike_standalone.log`
- `original_test.log`
- `original_seeds_2_.S`
- `original_seeds_2_.elf`
- `original_seeds_2_.img`
```

## Expected behavior

```markdown
For the illegal-instruction exception at `mepc = 0x0000000080001030`, XiangShan should not write the encoding of a later instruction into `mtval`.

According to XiangShan's documented behavior for illegal-instruction exceptions, `mtval` should contain the illegal instruction encoding:

```text
mtval = 0x00000000002026f3
```

At minimum, per the RISC-V Privileged Spec, if `mtval` is nonzero on an illegal-instruction exception, it must contain the faulting instruction bits, not the instruction at `PC + 8`.
```

## Environment

```markdown
- Hardware
  - CPU: AMD Ryzen 7 5800H with Radeon Graphics
  - Memory (GB): 15
  - Storage (GB): 1006 total / 785 free
- Software
  - Operating system: Ubuntu 24.04.4 LTS on WSL2, Linux 6.6.87.2-microsoft-standard-WSL2
  - gcc version: `gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0`
  - clang version: `Ubuntu clang version 18.1.3 (1ubuntu1)`
  - java version: `openjdk version "21.0.10" 2026-01-20`
  - mill version: `Mill Build Tool version 1.1.5`
- Repo
  - XiangShan commit id: `b381818d9242cd587d9e9ebf8567ad62bfd1d15b`
  - NEMU commit id (if difftest failed with NEMU): `N/A`
  - SPIKE commit id (if difftest failed with SPIKE): `40a76fd18e7bea5b8a29b4f12b195f14ec7c4958`
- Build & Run
  - Build command: `used existing ./build/emu; the binary reports "emu compiled at Apr 26 2026, 15:12:53"`
  - Run command:
    ```bash
    ./build/emu -b 0 -e 0 \
      -i /path/to/original_seeds_2_.img \
      --diff /path/to/ready-to-run/riscv64-spike-so
    ```
```

## To Reproduce

```markdown
1. Use the attached workload files:
   - `original_seeds_2_.img`
   - `original_seeds_2_.elf`
   - `original_seeds_2_.S`

2. Run XiangShan with Spike difftest:

   ```bash
   cd /path/to/XiangShan
   ./build/emu -b 0 -e 0 \
     -i /path/to/original_seeds_2_.img \
     --diff /path/to/ready-to-run/riscv64-spike-so
   ```

3. The run aborts with an `mtval` mismatch:

   ```text
   exception pc 0000000080001030 inst 002026f3 cause 0000000000000002 csrr a3, frm
   mtval different at pc = 0x0080001028,
     right = 0x00000000002026f3,
     wrong = 0x00000000c02cf5d3
   ```

4. The instruction bytes in the workload are:

   ```text
   0x80001030: 0x002026f3   csrr a3, frm
   0x80001038: 0xc02cf5d3   fcvt.l.s a1, fs9
   ```

   So the reported XiangShan `mtval` value is the later instruction at `PC + 8`, not the faulting instruction at `mepc`.

5. Standalone Spike on the same ELF reports the expected trap value:

   ```text
   0x0000000080001030 (0x002026f3) csrr a3, frm
   exception trap_illegal_instruction, epc 0x0000000080001030
   tval 0x00000000002026f3
   ```
```

## Additional context

```markdown
This does not look like a vector-unit issue. The observed mismatch is in trap metadata for an illegal-instruction exception.

A possible area to inspect is the trap instruction / `mtval` selection path: the value written to `mtval` appears to come from a later instruction (`PC + 8`) instead of the instruction that raised the illegal-instruction exception. This may indicate that the instruction bits used for `mtval` are being selected from the wrong pipeline stage or wrong trap metadata entry.
```
