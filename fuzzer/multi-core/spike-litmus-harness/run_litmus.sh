#!/usr/bin/env bash
# run_litmus.sh — convenience wrapper for spike-litmus-harness
#
# Usage:
#   ./run_litmus.sh path/to/test.litmus [num_harts]
#
# Example:
#   ./run_litmus.sh ~/workspace/litmus-tests-riscv/tests/mixed-size/HAND/LB-mixed1.litmus 2
#
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <path/to/test.litmus> [num_harts=2]"
    exit 1
fi

LITMUS="$(realpath "$1")"
AVAIL="${2:-2}"

if [[ ! -f "$LITMUS" ]]; then
    echo "Error: $LITMUS not found"
    exit 1
fi

echo "=== spike-litmus-harness ==="
echo "Test  : $LITMUS"
echo "Harts : $AVAIL"
echo ""

make -C "$SCRIPT_DIR" \
    LITMUS="$LITMUS" \
    AVAIL="$AVAIL" \
    run
