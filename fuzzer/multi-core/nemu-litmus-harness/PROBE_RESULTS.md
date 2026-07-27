# NEMU Litmus Harness — Probe Results (T8 Gate)

Generated: 2026-04-23  
NEMU: OpenXiangShan commit `0a85fa0f48bd89320ed52c2b28749a176911ffe2`

---

## BLOCKER CHECK

| ID | Question | Result | BLOCKER? |
|----|----------|--------|----------|
| A2 | Multi-hart support | NEMU is single-hart per process; multi-hart via `-p N` flag or difftest API | NO — use `-p 2` flag |
| A3 | `mhartid` CSR readable | YES — `csr.h:651`, `isa_difftest_set_mhartid()` sets it | NO |
| A4 | AMO / LR-SC / fence | ALL REAL — `amo.c`, `fence.h` | NO |
| A6 | Exit mechanism | `nemu_trap` pseudo-instruction (opcode `0x6B`), exit code in `a0` | NO |
| A7 | Console output | MMIO UART16550 at `0x310b0000`, write byte to THR (offset 0) | NO |

**PROBE_VERDICT: OK — no blockers. Proceed to Wave-2.**

---

## Design Decisions

### D1: Multi-Hart Strategy
NEMU runs one hart per process instance. The litmus harness will use **`-p N`** to launch N NEMU processes, one per hart. Each process gets its own `mhartid` (0, 1, …). The harness host process forks N NEMU instances and waits for all to complete — matching the spike multi-hart model.

**Alternative considered**: Single NEMU process with software thread simulation — rejected (too complex, not faithful to hardware).

### D2: Exit Implementation
Use `nemu_trap` pseudo-instruction (encoding: `.word 0x0000006b`). Exit code passed in `a0` (x10). NEMU reads `a0` and calls `HOSTCALL_EXIT`.

```asm
# _exit(int code):
#   a0 = code (already set by caller per RISC-V ABI)
.word 0x0000006b   # nemu_trap
```

### D3: Console Output
Write byte to MMIO UART16550 THR at `0x310b0000 + 0x00`.

```c
static inline void putchar(char c) {
    *(volatile char *)0x310b0000UL = c;
}
```

### D4: Memory Base
`0x80000000` — matches NEMU default `CONFIG_MBASE`. Linker script RAM base = `0x80000000`.

### D5: Hart-ID Source
`csrr a0, mhartid` — NEMU sets `mhartid` per-process. Hart 0 is primary, harts 1+ are secondary.

### D6: Toolchain
Reuse spike harness toolchain verbatim:
- `GCC = riscv64-linux-gnu-gcc`
- `GCC_INCLUDE = /usr/lib/gcc-cross/riscv64-linux-gnu/13/include`
- `LIBGCC = /usr/lib/gcc-cross/riscv64-linux-gnu/13/libgcc.a`
- `NEWLIB_SYSROOT = /home/ra4ing/workspace/riscv/riscv64-unknown-elf`

### D7: NEMU Invocation
```
$(NEMU) --config $(NEMU_CONFIG) -b -e $(IMAGE) -- $(ARGS)
```
- `-b` = batch mode (no interactive prompt)
- `-e` = load ELF (requires `CONFIG_USE_SPARSEMM` or flat binary)
- Use flat binary (`.bin`) to avoid ELF dependency on `CONFIG_USE_SPARSEMM`

---

## Key Facts

| Item | Value | Source |
|------|-------|--------|
| MBASE | `0x80000000` | `src/memory/Kconfig:6` |
| nemu_trap opcode | `0x0000006b` | `src/isa/riscv64/instr/decode.c:98` |
| UART16550 MMIO | `0x310b0000` | `configs/riscv64-xs_defconfig:180` |
| mhartid CSR | `0xF14` | `csr.h:359` |
| Build deps | `build-essential gcc git libreadline-dev libsdl2-dev zstd libzstd-dev` | `README.md:147` |
| rdtime readable | YES | `csr.h:76-85` |
| AMO instructions | All real, no CONFIG gate | `amo.c` |
| fence / fence.i | Real | `fence.h:16-24` |

---

## Differences from Spike Harness

| Aspect | Spike | NEMU |
|--------|-------|------|
| Exit | HTIF `tohost = (code<<1)\|1` | `nemu_trap` (`.word 0x0000006b`), code in `a0` |
| Console | HTIF `tohost = (1<<56)\|(1<<48)\|ch` | MMIO store to `0x310b0000` |
| Multi-hart | Single binary, `-p N` flag | One process per hart (fork model) |
| Memory base | `0x80000000` | `0x80000000` (same) |
| Hart ID | `csrr a0, mhartid` | `csrr a0, mhartid` (same) |
| ELF loading | Direct ELF | Flat binary (`.bin`) recommended |
