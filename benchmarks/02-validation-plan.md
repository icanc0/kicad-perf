# Validation plan — pinning real numbers on each patch

The estimates in `patches/README.md` and `analysis/00-hot-paths.md` are
engineering guesses from source review + syscall traces + `time -v` on
the stock 9.0.8 aarch64 binary. A working full-tree build of KiCad
against this patch series is still open (see `benchmarks/00-baseline-…`
for the userspace-dep-chase blocker); once that lands, run the tests
below to replace estimates with measurements.

## Setup

```
# Baseline: stock 9.0.8 (or whichever kicad master HEAD is being
# compared against). Same binary used across all benchmarks in
# benchmarks/00-baseline-*.md.
which kicad-cli
kicad-cli --version

# Patched: the fork with the patch series applied.
$PATCHED_KICAD_CLI --version   # should print same version

# Test fixtures:
export TINY_BOARD=$HOME/not-my-projects/kicad/demos/ecc83/ecc83-pp.kicad_pcb        # 156 KB
export MED_BOARD=$HOME/not-my-projects/kicad/demos/pic_programmer/pic_programmer.kicad_pcb  # 632 KB
export LARGE_BOARD=$HOME/not-my-projects/kicad/demos/video/video.kicad_pcb          # 5.6 MB

mkdir -p /tmp/bench/{stock,patched}
```

## Per-patch validation

### P1 — `wxSafeYield` skip in CLI

```
hyperfine --warmup 3 --runs 10 \
  "kicad-cli pcb export svg --mode-multi -l F.Cu,B.Cu,F.SilkS,B.SilkS,F.Mask,B.Mask -o /tmp/bench/stock $LARGE_BOARD" \
  "$PATCHED_KICAD_CLI pcb export svg --mode-multi -l F.Cu,B.Cu,F.SilkS,B.SilkS,F.Mask,B.Mask -o /tmp/bench/patched $LARGE_BOARD"
```

Expected: 5-30 ms faster patched. Tiny signal per layer, may be lost in
noise on this ARM. Test on x86 with 20 runs if inconclusive.

### P2 — defer `LoadGlobalTables`

```
hyperfine --warmup 3 --runs 20 \
  "kicad-cli --version" \
  "$PATCHED_KICAD_CLI --version"

hyperfine --warmup 3 --runs 20 \
  "kicad-cli --help" \
  "$PATCHED_KICAD_CLI --help"
```

Expected: 20-100 ms faster patched, more if the user has a big PCM
library tree.

Verify no regression on commands that DO need tables:

```
hyperfine --warmup 2 --runs 5 \
  "kicad-cli pcb export bom -o /tmp/bench/stock/bom.csv $LARGE_BOARD" \
  "$PATCHED_KICAD_CLI pcb export bom -o /tmp/bench/patched/bom.csv $LARGE_BOARD"
```

Expected: within ±5% of stock.

### P3 — skip connectivity/DRC/class init for export

```
hyperfine --warmup 3 --runs 10 \
  "kicad-cli pcb export svg --mode-multi -l F.Cu -o /tmp/bench/stock $LARGE_BOARD" \
  "$PATCHED_KICAD_CLI pcb export svg --mode-multi -l F.Cu -o /tmp/bench/patched $LARGE_BOARD"
```

Expected: **1.5-2 s faster** on the 5.6 MB board. Biggest single win in
the series.

Sanity: bit-for-bit compare outputs.

```
diff -r /tmp/bench/stock /tmp/bench/patched
# Empty diff. If not: audit the plot code path — connectivity graph
# was consulted somewhere it shouldn't have been.
```

Regression check on DRC and BOM which need connectivity:

```
hyperfine --warmup 2 --runs 5 \
  "kicad-cli pcb drc -o /tmp/bench/stock/drc.rpt $LARGE_BOARD" \
  "$PATCHED_KICAD_CLI pcb drc -o /tmp/bench/patched/drc.rpt $LARGE_BOARD"
diff /tmp/bench/stock/drc.rpt /tmp/bench/patched/drc.rpt
```

### P4 — lazy argparse subtree

Same benches as P2. Additional 5-20 ms win.

### P5 — skip libcurl + Sentry init in headless

Same benches as P2. Additional 10-50 ms win.

### P6 — lazy thread-pool

```
strace -f -e trace=clone,futex -c $PATCHED_KICAD_CLI --version 2>&1 | tail -6
```

Expected: 0-1 clone() calls (no thread pool), vs 8 clones in stock.
Wall improvement per-invocation: 15-30 ms.

### P7 — daemon scaffold, P8 — socket bind, P9 — wire protocol

```
$PATCHED_KICAD_CLI daemon start &
sleep 0.3
$PATCHED_KICAD_CLI daemon status
# expect: kicad-cli daemon: RUNNING (pid …, socket …)
```

### P10 — dispatch integration

The end-to-end money shot for the whole daemon story:

```
$PATCHED_KICAD_CLI daemon start &
sleep 0.3

# Cold first call:
time $PATCHED_KICAD_CLI --via-daemon pcb export svg --mode-multi -l F.Cu -o /tmp/bench/d $LARGE_BOARD

# Warm subsequent calls:
hyperfine --warmup 1 --runs 20 \
  "$PATCHED_KICAD_CLI --via-daemon pcb export svg --mode-multi -l F.Cu -o /tmp/bench/d $LARGE_BOARD"

$PATCHED_KICAD_CLI daemon stop
```

Expected first call: ~1.4 s (with P3 applied). Expected warm calls:
**50-150 ms** (~20-60× faster than stock's 3.1 s).

Bit-compare against stock:

```
$PATCHED_KICAD_CLI pcb export svg --mode-multi -l F.Cu -o /tmp/bench/direct $LARGE_BOARD
diff -r /tmp/bench/direct /tmp/bench/d
```

### P11 — daemon stop / status via pidfile

```
$PATCHED_KICAD_CLI daemon start &
DPID=$!
sleep 0.3
$PATCHED_KICAD_CLI daemon status | grep -q RUNNING || echo FAIL-1
kill $DPID; sleep 0.5
$PATCHED_KICAD_CLI daemon status | grep -qE "STALE|NOT RUNNING" || echo FAIL-2

# stop-during-dispatch:
$PATCHED_KICAD_CLI daemon start &
sleep 0.3
$PATCHED_KICAD_CLI --via-daemon pcb export svg --mode-multi -l F.Cu -o /tmp/bench/d $LARGE_BOARD &
sleep 0.05
$PATCHED_KICAD_CLI daemon stop
wait
```

Expected: stop reports "daemon stopped" within 2 s even if dispatch
was mid-flight.

### P12 — BOARD LRU cache

The heart of daemon-throughput benchmark:

```
$PATCHED_KICAD_CLI daemon start &
sleep 0.3

# 15 exports on the same board:
time for fmt in svg pdf gerbers drill pos ipc2581 ipcd356 stackup stats; do
    $PATCHED_KICAD_CLI --via-daemon pcb export $fmt \
        -o /tmp/bench/many/$fmt $LARGE_BOARD >/dev/null 2>&1
done

$PATCHED_KICAD_CLI daemon stop
```

Compare vs same loop against stock (no --via-daemon): expect **>10×**
speedup, plus the BOARD-cache-hit signal in the daemon log.

### P13 — client `--via-daemon` auto-connect

Behavior tests only:

```
# Daemon up:
$PATCHED_KICAD_CLI daemon start &
sleep 0.3
KICAD_CLI_DAEMON=1 $PATCHED_KICAD_CLI --version
# Should print version. Verify by reading daemon log — should show a
# recv() from the client.

# Daemon down:
$PATCHED_KICAD_CLI daemon stop; sleep 0.3
KICAD_CLI_DAEMON=1 $PATCHED_KICAD_CLI --version
# Should still print version (graceful fallback).
```

### P14 — drawing-sheet cache

Under the daemon, with two different boards that share the same
`.kicad_wks` template:

```
$PATCHED_KICAD_CLI daemon start &
sleep 0.3

# First: pays sheet parse.
time $PATCHED_KICAD_CLI --via-daemon pcb export svg -l F.Cu -o /tmp/bench/a $TINY_BOARD
# Second: cached.
time $PATCHED_KICAD_CLI --via-daemon pcb export svg -l F.Cu -o /tmp/bench/b $MED_BOARD
```

Expected: 2nd-call delta relative to boards-with-differing-sheets is
5-20 ms.

### P15 — per-dispatch reset

Robustness test rather than perf. Force a command that mutates the
locale, follow with one that reads it:

```
$PATCHED_KICAD_CLI daemon start &
sleep 0.3

# Command 1: a variant that (deliberately) sets a non-C locale.
LC_ALL=de_DE.UTF-8 KICAD_CLI_DAEMON=1 $PATCHED_KICAD_CLI pcb export svg -l F.Cu -o /tmp/bench/de $TINY_BOARD
# Command 2 in the same session: verify the second call still parses
# floats with '.' decimal separator (not ',' as de_DE expects).
KICAD_CLI_DAEMON=1 $PATCHED_KICAD_CLI pcb export svg --scale 1.5 -l F.Cu -o /tmp/bench/en $TINY_BOARD
```

Expected: no "Invalid scale" error in the second call.

## Overall roll-up

Once all 15 patches are validated, produce a single roll-up:

|                             | stock 9.0.8   | fork (0001-0015)          | speedup    |
|-----------------------------|--------------:|--------------------------:|-----------:|
| `--version`                 | 254 ms        | ??? ms                    | ???×       |
| single `pcb export svg` LG  | 3121 ms       | ??? ms                    | ???×       |
| CI matrix (15 exports)      | 45 s          | ??? s daemon              | ???×       |

Publish to `benchmarks/03-results-fork-vs-stock.md`.

## When numbers disagree with estimates

If a patch delivers *less* than estimated: investigate — maybe the
strace signal isn't where the CPU actually is; maybe the patch is
being masked by another cost. Update the patch's expected-win entry
in `patches/README.md`.

If a patch delivers *more*: also investigate — maybe you accidentally
short-circuited something the caller still needs. Bit-compare outputs.

If a patch causes a regression somewhere: add a
`patches/regressions/*.md` note; keep or drop the patch based on
severity.
