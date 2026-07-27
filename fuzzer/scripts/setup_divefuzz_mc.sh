#!/usr/bin/env bash
# Copyright (c) 2024-2025 Institute of Information Engineering, Chinese Academy of Sciences
#
# DiveFuzz is licensed under Mulan PSL v2.
#
# DiveFuzz-MC *litmus* environment setup.
#
# Provisions exactly the litmus toolchain the multicore pipeline needs to turn a
# `.litmus` into a checkable/compilable artifact:
#
#   apt (cross GCC + python)  ->  opam + herdtools7 (herd7/litmus7)  ->
#   riscv.cfg fix  ->  newlib medany rebuild (only if toolchain source present)
#   ->  fuzzer/scripts/env.sh
#
# What this script does NOT do (by design -- they are not "litmus"):
#   * build spike            -- spike is a DUT, not part of the litmus env
#   * build riscv-gnu-toolchain from source -- the newlib sysroot is assumed to
#     already exist on the host (or be provided separately); this script only
#     reapplies the -mcmodel=medany fix when the toolchain source tree is present
#
# Usage (from the repo root, on the target host):
#   bash fuzzer/scripts/setup_divefuzz_mc.sh
#   source fuzzer/scripts/env.sh
#
# Knobs:
#   RISCV_ROOT       where spike/newlib live if present (default: $HOME/riscv)
#   TOOLCHAIN_SRC    riscv-gnu-toolchain source tree, for the medany rebuild
#                    (default: $RISCV_ROOT/src/riscv-gnu-toolchain)
#   NPROC            parallel jobs for the optional newlib rebuild (default: $(nproc))
#
# Idempotent: every step short-circuits when its output already exists.

set -euo pipefail

RISCV_ROOT="${RISCV_ROOT:-$HOME/riscv}"
TOOLCHAIN_SRC="${TOOLCHAIN_SRC:-$RISCV_ROOT/src/riscv-gnu-toolchain}"
NPROC="${NPROC:-$(nproc)}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_SH="$SCRIPT_DIR/env.sh"

if [ -t 1 ]; then
    C_BLUE=$'\033[1;34m'; C_GREEN=$'\033[1;32m'; C_YELLOW=$'\033[1;33m'; C_RST=$'\033[0m'
else
    C_BLUE=""; C_GREEN=""; C_YELLOW=""; C_RST=""
fi
log()  { printf '%s[setup]%s %s\n' "$C_BLUE" "$C_RST" "$*"; }
ok()   { printf '%s[setup]%s %s%s%s\n' "$C_BLUE" "$C_RST" "$C_GREEN" "$*" "$C_RST"; }
warn() { printf '%s[setup]%s %s%s%s\n' "$C_BLUE" "$C_RST" "$C_YELLOW" "$*" "$C_RST" >&2; }
section() { printf '\n%s=== %s ===%s\n' "$C_BLUE" "$*" "$C_RST"; }

as_root() {
    if [ "$(id -u)" -eq 0 ]; then "$@"
    elif command -v sudo >/dev/null 2>&1; then sudo "$@"
    else
        warn "need root for: $*"
        warn "re-run as root, or install sudo."
        return 1
    fi
}

# --------------------------------------------------------------------------- #
# [1/5] apt: cross GCC + opam/OCaml + python runtime
# --------------------------------------------------------------------------- #
section "[1/5] apt: cross GCC + opam + python"
APT_PKGS=(
    build-essential ca-certificates curl git
    # cross toolchain the litmus7 harness links against (provides libgcc.a)
    gcc-riscv64-linux-gnu
    # OCaml / opam for herdtools7
    opam ocaml-nox ocaml-findlib
    # python runtime (multicore pipeline imports)
    python3 python3-pip python3-venv
    python3-yaml python3-numpy python3-psutil python3-tqdm
)
log "apt-get install ${#APT_PKGS[@]} packages"
as_root apt-get update -qq
as_root apt-get install -y --no-install-recommends "${APT_PKGS[@]}"
ok "apt packages installed"

# --------------------------------------------------------------------------- #
# [2/5] opam: herdtools7 (herd7 + litmus7) under a switch named 'default'
#        (the harness Makefile expects ~/.opam/default/bin/litmus7)
# --------------------------------------------------------------------------- #
section "[2/5] opam + herdtools7 (herd7 / litmus7) + riscv.cfg"
if [ ! -d "$HOME/.opam" ]; then
    log "opam init (default switch, sandboxing off)"
    opam init -y --disable-sandboxing
fi
# Ensure a usable ~/.opam/default (real switch OR symlink). On a fresh host
# `opam init` already creates it; we only create when the path is absent.
if [ ! -e "$HOME/.opam/default" ]; then
    log "creating opam switch 'default' from system OCaml"
    opam switch create default ocaml-system -y || opam switch create default -y
fi
opam switch default -y 2>/dev/null || true
# shellcheck disable=SC1090
eval "$(opam env || true)"
opam install -y herdtools7

# riscv.cfg: herdtools7 ships riscv-qemu.cfg; litmus7 -mach riscv wants riscv.cfg.
LITMUS_SHARE="$HOME/.opam/default/share/herdtools7/litmus"
if [ -f "$LITMUS_SHARE/riscv-qemu.cfg" ] && [ ! -e "$LITMUS_SHARE/riscv.cfg" ]; then
    ln -sf riscv-qemu.cfg "$LITMUS_SHARE/riscv.cfg"
    ok "riscv.cfg -> riscv-qemu.cfg"
elif [ -e "$LITMUS_SHARE/riscv.cfg" ]; then
    ok "riscv.cfg already present"
else
    warn "riscv-qemu.cfg not found under $LITMUS_SHARE; herdtools7 layout may differ"
fi
ok "herdtools7 installed"

# --------------------------------------------------------------------------- #
# [3/5] newlib medany rebuild -- ONLY if the riscv-gnu-toolchain source tree is
#        present. The sysroot itself is assumed to already exist on the host
#        (this script does not build the toolchain). medlow -> medany so the
#        bare-metal ELF links cleanly at base 0x80000000.
# --------------------------------------------------------------------------- #
section "[3/5] newlib medany rebuild (conditional)"
if [ -f "$TOOLCHAIN_SRC/Makefile" ]; then
    log "toolchain source found at $TOOLCHAIN_SRC; applying medany fix + rebuild newlib"
    (
        cd "$TOOLCHAIN_SRC"
        sed -i 's/-mcmodel=medlow/-mcmodel=medany/g' Makefile || true
        rm -f stamps/build-newlib
        make -j"$NPROC" stamps/build-newlib
    )
    ok "newlib rebuilt with -mcmodel=medany"
else
    warn "riscv-gnu-toolchain source not found at $TOOLCHAIN_SRC"
    warn "skipping medany rebuild -- ensure your newlib sysroot is already medany"
    warn "(set TOOLCHAIN_SRC=<path> if the source tree is elsewhere)"
fi

# --------------------------------------------------------------------------- #
# [4/5] generate env.sh -- source it before running the pipeline. The harness
#        Makefile uses ?= for every path, so these exports override its
#        hardcoded defaults. NEWLIB_SYSROOT / SPIKE are discovered, not built.
# --------------------------------------------------------------------------- #
section "[4/5] generate $ENV_SH"
OPAM_BIN="$HOME/.opam/default/bin"
LIBGCC_DIR="$(dirname "$(riscv64-linux-gnu-gcc -print-libgcc-file-name 2>/dev/null)")"

# Discover the newlib sysroot (not provisioned by this script).
NEWLIB_SYSROOT=""
for c in "$RISCV_ROOT/riscv64-unknown-elf" \
         "$(command -v riscv64-unknown-elf-gcc >/dev/null 2>&1 && riscv64-unknown-elf-gcc -print-sysroot 2>/dev/null)"; do
    if [ -n "$c" ] && [ -f "$c/lib/libc.a" ]; then NEWLIB_SYSROOT="$c"; break; fi
done
# Discover spike if present (DUT -- only needed for the spike reference闭环).
SPIKE_PATH=""
for c in "$RISCV_ROOT/bin/spike" "$(command -v spike 2>/dev/null)"; do
    if [ -n "$c" ] && [ -x "$c" ]; then SPIKE_PATH="$c"; break; fi
done

{
    echo "# Generated by setup_divefuzz_mc.sh -- source it, do not run."
    echo "#   source fuzzer/scripts/env.sh"
    echo "# Machine-specific; not committed to git."
    echo "export PATH=\"$OPAM_BIN${RISCV_ROOT:+:$RISCV_ROOT/bin}:\$PATH\""
    echo
    echo "# litmus7 harness Makefile overrides (all use ?=):"
    echo "export GCC=\"riscv64-linux-gnu-gcc\""
    echo "export LIBGCC=\"$LIBGCC_DIR/libgcc.a\""
    echo "export LIBGCC_EH=\"$LIBGCC_DIR/libgcc_eh.a\""
    echo "export LITMUS7=\"$OPAM_BIN/litmus7\""
    echo "export LITMUS7_SHARE=\"$LITMUS_SHARE\""
    if [ -n "$NEWLIB_SYSROOT" ]; then
        echo "export NEWLIB_SYSROOT=\"$NEWLIB_SYSROOT\"   # discovered"
    else
        echo "# NEWLIB_SYSROOT not discovered -- set it to your riscv64-unknown-elf sysroot:"
        echo "# export NEWLIB_SYSROOT=\"$RISCV_ROOT/riscv64-unknown-elf\""
    fi
    echo
    echo "# herd7 oracle (DiveFuzz-MC RVWMO model):"
    echo "export HERD7=\"$OPAM_BIN/herd7\""
    if [ -n "$SPIKE_PATH" ]; then
        echo
        echo "# spike (reference DUT -- present on this host):"
        echo "export SPIKE=\"$SPIKE_PATH\""
    else
        echo
        echo "# spike (DUT) not found -- uncomment & set if you run the spike reference闭环:"
        echo "# export SPIKE=\"/path/to/spike\""
    fi
} > "$ENV_SH"
ok "wrote $ENV_SH"

# --------------------------------------------------------------------------- #
# [5/5] verify
# --------------------------------------------------------------------------- #
section "[5/5] verify"
fail=0
check() {
    if command -v "$1" >/dev/null 2>&1 || [ -e "$1" ]; then ok "$2"
    else warn "MISSING: $2 ($1)"; fail=1; fi
}
check riscv64-linux-gnu-gcc        "cross GCC (libgcc.a for harness link)"
check "$HOME/.opam/default/bin/herd7"   "herd7 (RVWMO oracle)"
check "$HOME/.opam/default/bin/litmus7" "litmus7 (.litmus -> C codegen)"
check "$LITMUS_SHARE/riscv.cfg"    "litmus7 riscv.cfg"
python3 -c "import yaml, numpy, psutil, tqdm" 2>/dev/null && ok "python runtime deps" \
    || { warn "python deps incomplete"; fail=1; }

if [ -n "$NEWLIB_SYSROOT" ]; then ok "newlib sysroot: $NEWLIB_SYSROOT"
else warn "newlib sysroot NOT discovered -- set NEWLIB_SYSROOT in env.sh before building ELFs"; fail=1; fi
if [ -n "$SPIKE_PATH" ]; then ok "spike (DUT): $SPIKE_PATH"
else warn "spike (DUT) not found -- only needed for the spike reference闭环"; fi

cat <<EOF

${C_GREEN}DiveFuzz-MC litmus environment ready.${C_RST}

Next step -- source the generated env file before running the pipeline:

    source $ENV_SH

Then (example) generate + run a multicore seed:

    cd fuzzer
    python run_dut.py --config spike_multicore.yaml   # needs NEWLIB_SYSROOT + a DUT

EOF
[ "$fail" -eq 0 ] || warn "one or more checks failed (see MISSING/WARN lines above)"
exit 0
