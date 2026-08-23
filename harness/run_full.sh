#!/bin/bash
# run_full — orchestrate the whole harness once the built binaries are ready.
#
# Runs the {cli.version, cli.svg_small, cli.svg_big} scenarios across
# {stock-9.0.8, stock-master, patched-master} and writes an aggregated
# report under harness/reports/YYYY-MM-DD-hhmm-full/.
#
# Usage:
#   ./run_full.sh                    # runs everything available
#   ./run_full.sh --runs 5           # 5 hyperfine runs per scenario
#
# Exits early with a clear message if a required binary is missing.

set -euo pipefail

RUNS="${RUNS:-3}"
HARNESS="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HARNESS/.." && pwd)"

# Discover binaries.
STOCK_908="$HOME/local/bin/kicad-cli"
STOCK_MASTER_CLI="$HOME/not-my-projects/kicad-stock/build-stock/kicad/kicad-cli"
PATCHED_MASTER_CLI="$HOME/not-my-projects/kicad/build-mini/kicad/kicad-cli"

# Shared LD path for master builds.
LD_MASTER="$HOME/not-my-projects/kicad/build-mini/common:\
$HOME/not-my-projects/kicad/build-mini/libs:\
$HOME/not-my-projects/kicad/build-mini:\
$HOME/local/wx-root/usr/lib/aarch64-linux-gnu:\
$HOME/local/kicad-root/usr/lib/aarch64-linux-gnu"

LD_STOCK_MASTER="$HOME/not-my-projects/kicad-stock/build-stock/common:\
$HOME/not-my-projects/kicad-stock/build-stock/libs:\
$HOME/not-my-projects/kicad-stock/build-stock:\
$HOME/local/wx-root/usr/lib/aarch64-linux-gnu:\
$HOME/local/kicad-root/usr/lib/aarch64-linux-gnu"

# Build the --binaries argv for runner.py based on what exists.
BINS=""
if [ -x "$STOCK_908" ]; then
    BINS="stock-9.0.8=$STOCK_908"
fi
if [ -x "$STOCK_MASTER_CLI" ]; then
    BINS="${BINS:+$BINS;}stock-master=$STOCK_MASTER_CLI|$LD_STOCK_MASTER"
fi
if [ -x "$PATCHED_MASTER_CLI" ]; then
    BINS="${BINS:+$BINS;}patched-master=$PATCHED_MASTER_CLI|$LD_MASTER"
fi

if [ -z "$BINS" ]; then
    echo "No binaries found — need at least one of:" >&2
    echo "  $STOCK_908" >&2
    echo "  $STOCK_MASTER_CLI" >&2
    echo "  $PATCHED_MASTER_CLI" >&2
    exit 2
fi

echo "Running with:  $BINS"
echo "Runs per (bin, scenario): $RUNS"
echo

cd "$HARNESS"
python3 runner.py \
    --binaries "$BINS" \
    --scenarios cli_version \
    --runs "$RUNS"

echo
echo "Done. Latest report:  $(ls -td reports/*/ | head -1)report.md"
