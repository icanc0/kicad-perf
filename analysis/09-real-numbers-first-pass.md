# Real head-to-head numbers — first pass

Run 2026-08-23 21:47 on the aarch64 rockchip box, quiet CPU (build
just finished, no other load). 3 hyperfine runs per (binary,
scenario) after 2-3 warmups. RSS sampled at 50 Hz.

## Results

### `cli.version`

|                | wall (median) | user CPU | sys CPU | peak RSS |
|----------------|--------------:|---------:|--------:|---------:|
| stock 9.0.8    |       229 ms  |   168 ms |   66 ms |  57.0 MB |
| patched master |   **153 ms**  |   109 ms |   53 ms |  57.8 MB |
| Δ              |       -76 ms  |   -59 ms |  -13 ms |  +0.8 MB |
| ratio          |      **1.50×**|   1.54×  |    1.25×|    1.014×|

### `cli.svg_export` (5MB starfish board, F.Cu only)

|                | wall (median) | user CPU | sys CPU | peak RSS |
|----------------|--------------:|---------:|--------:|---------:|
| stock 9.0.8    |     1330 ms   |  1409 ms |  275 ms | 245.5 MB |
| patched master | **1013 ms**   |   811 ms |  199 ms | 240.0 MB |
| Δ              |     -317 ms   |  -598 ms |  -76 ms |   -5.5 MB|
| ratio          |     **1.31×** |    1.74× |    1.38×|    1.02× |

## Reading

### Wall time — patches deliver on the primary axis

- `--version` in **153 ms** is the fastest kicad-cli invocation
  I know of; stock's 229 ms fold matches the ~76 ms savings the
  A-group patches (P2, P4-P6, P17, P36-P39, P57) predicted.
- `svg_export` in **1013 ms** on a 5 MB board isn't as dramatic
  a jump as I estimated (I predicted ~350-500 ms based on
  "shave 1500 ms off board init"). See below on why.

### User CPU — patches over-deliver

- `svg_export` user-CPU drops **42%** (1409 → 811 ms). That
  means the wall-time delta is capped by IO more than by CPU;
  patched is more IO-bound than stock relative to CPU.
  The remaining wall time is dominated by (a) SVG file write —
  P22's 128 KB stdio buffer is already active but writing a
  ~940 KB SVG still takes some ms; (b) kicad-cli fixed init.

### Peak RSS — the surprise

I predicted P3 would drop peak RSS by ~120 MB on this board (from
the RSS-curve analysis in `analysis/08`). The real drop is only
**~5.5 MB**. The RSS curve tells us why:

| t   | stock 9.0.8 RSS | patched RSS |
|----:|----------------:|------------:|
|  80 |         12 MB   |      31 MB  |
| 180 |         17 MB   |      59 MB  |
| 590 |         39 MB   |     100 MB  |
| 790 |         52 MB   |     219 MB  |
| 910 |         59 MB   |     224 MB (peak) |
|1000 |         61 MB   |           – |
|3050 |        100 MB   |           – |
|4070 |        221 MB   |           – |
|5010 |        236 MB (peak) |      – |

Patched hits ~224 MB peak in 900 ms; stock reaches the same
level in 4-5 s. The **peak is dominated by the board data
itself** (footprints, pads, tracks, zones as PCB_ITEM instances
with their SHAPE_POLY_SET geometry) — NOT by the connectivity/
DRC/net-class init that P3 skips. My earlier `analysis/08`
misattributed the 220 MB jump; it's actually the parser building
up BOARD_ITEM instances, not a subsequent init phase.

**Corrected mental model:**
- Board load = parser materialises ~220 MB of BOARD_ITEMs
- After parse, stock 9.0.8 additionally runs
  `initializeLoadedBoard()` which builds connectivity graph
  (+15-20 MB), DRC engine (+small), net-class assignments
  (+small), tuning setup (+small). Total additional: ~5-10 MB.
- Patched skips that additional ~5-10 MB and skips the CPU
  time to compute it (~300-400 ms).

**RAM-focused patches queue in `analysis/07` needs re-prioritisation:**

- P60 (SHAPE_POLY_SET dedup across identical footprints)
  becomes the ONLY route to significantly cut peak RSS on
  a boards this size. The ~220 MB of board data has a
  huge dedup opportunity — many identical LED0805 / R0603 /
  C0402 footprints each carry their own polygon copies.

## What this tells us to do next

1. **Land P60 dedup** for real RAM impact. Currently queued;
   promote to top of the list.
2. **Re-run svg_export on a bigger board** (10 MB, 20 MB) —
   the wall-time win may scale, or the IO ceiling may cap it.
3. **Attack the SVG file write** — 940 KB out is <10 ms of IO,
   but SVG-plot's `fmt::print` per-shape may still have room.
4. **Measure daemon-mode svg_export** — the second-invocation
   number is the real CI-workflow answer, and the daemon
   patches (P7-P21) aren't reflected in these one-shot numbers.
