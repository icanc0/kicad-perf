# RSS curve — `pcb export svg` on stock 9.0.8 (5 MB board)

Captured 2026-08-23 by the harness (`rss_sampler` at 50 Hz) against
`starfish.kicad_pcb` (4.7 MB, from kicanvas fixtures).

## Curve

```
t (ms)   RSS (MB)   phase
    0     0.1       exec
  182    17.1       wxWidgets init begins
 1001    61.4       wxWidgets/GTK/pango loaded
 2021    67.9       board file open + first parse pages
 3045   100.4       parse tokenization complete, board partly built
 4070   220.8       ← ~120 MB jump: connectivity + DRC + net-class + tuning init
 5008   236.0       peak: SVG rendered
```

## Reading

The **~120 MB step at t=3-4s** is the load-side setup that patch
P3 skips for the export path (see
`analysis/01-board-load-init.md`). It's not the parser and it's
not the plot: it's `initializeLoadedBoard()`'s connectivity graph
build, DRC engine load, net-class assignment, and tuning-pattern
init — none of which any `pcb export svg` command actually needs.

## Predicted patched curve

If P3+P40-P44 are working as designed, the patched-master run
should show:

- Same 0-3s shape (init and parse are unchanged)
- **No 120 MB jump between t=3s and t=4s** — RSS should plateau
  near ~100-120 MB through end of plot
- Peak RSS closer to ~130 MB instead of 236 MB
- Wall time cut proportionally

## Test method (runnable when patched-master lands)

```
$ cd ~/not-my-projects/kicad-perf/harness
$ ./run_full.sh          # runs cli.version + cli.svg_export
$ head -30 reports/*/report.md | tail
```

The predicted deltas above become concrete numbers in a report row.
The claim that P3 saves 120 MB of peak RSS on this board size stands
or falls on that measurement.
