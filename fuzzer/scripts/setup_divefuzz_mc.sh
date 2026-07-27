#!/usr/bin/env bash
# Copyright (c) 2024-2025 Institute of Information Engineering, Chinese Academy of Sciences
#
# DiveFuzz is licensed under Mulan PSL v2.
#
# DiveFuzz-MC milestone-1 environment setup.
#
# Run INSIDE the divefuzz-dev container:
#   docker exec divefuzz-dev bash /home/ra4ing/workspace/riscv/DiveFuzz/fuzzer/scripts/setup_divefuzz_mc.sh
#
# Idempotent: every step is safe to re-run. Installs the tools the multicore
# pipeline needs (herd7/litmus7 for the oracle + codegen, a cross GCC for the
# harness, and a medany newlib so bare-metal ELFs link at 0x80000000). Nothing
# already present is removed.

set -euo pipefail

RISCV_ROOT="${RISCV_ROOT:-/home/ra4ing/workspace/riscv}"
OPAM_SWITCH="${OPAM_SWITCH:-ocaml-system.4.14.1}"

as_root() {
    if [ "$(id -u)" -eq 0 ]; then "$@"
    elif command -v sudo >/dev/null 2>&1; then sudo -n "$@" 2>/dev/null || sudo "$@"
    else
        echo "[setup] need root for: $*" >&2
        echo "[setup] re-run this script as: docker exec -u root divefuzz-dev bash $0" >&2
        return 1
    fi
}

echo "=== [1/5] apt: cross GCC + opam + OCaml ==="
as_root apt-get update -qq
as_root apt-get install -y --no-install-recommends \
    gcc-riscv64-linux-gnu opam ocaml-nox ocaml-findlib libgmp-dev m4 pkg-config

echo "=== [2/5] opam: herdtools7 (herd7 + litmus7) ==="
opam init --disable-sandboxing -y --compiler "$OPAM_SWITCH" || true
eval "$(opam env)"
opam install -y herdtools7

echo "=== [3/5] align opam default switch (Makefile expects ~/.opam/default) ==="
ln -sfn "$OPAM_SWITCH" "$HOME/.opam/default"

echo "=== [4/5] litmus7 riscv.cfg (herdtools7 ships riscv-qemu.cfg; -mach riscv wants riscv.cfg) ==="
SHARE="$HOME/.opam/$OPAM_SWITCH/share/herdtools7/litmus"
if [ -f "$SHARE/riscv-qemu.cfg" ] && [ ! -e "$SHARE/riscv.cfg" ]; then
    ln -sf riscv-qemu.cfg "$SHARE/riscv.cfg"
fi

echo "=== [5/5] rebuild newlib with -mcmodel=medany (links cleanly at 0x80000000) ==="
TC="$RISCV_ROOT/riscv-gnu-toolchain"
if [ -f "$TC/Makefile" ]; then
    sed -i 's/-mcmodel=medlow/-mcmodel=medany/g' "$TC/Makefile"
    rm -f "$TC/stamps/build-newlib"
    make -C "$TC" -j"$(nproc)" stamps/build-newlib
else
    echo "[setup] riscv-gnu-toolchain not found at $TC; skipping newlib rebuild" >&2
fi

echo "=== verify ==="
command -v riscv64-linux-gnu-gcc
"$HOME/.opam/default/bin/herd7" --version 2>/dev/null | head -1 || true
"$HOME/.opam/default/bin/litmus7" --version 2>/dev/null | head -1 || true
echo "[setup] DiveFuzz-MC environment ready."
