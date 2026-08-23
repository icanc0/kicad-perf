# kicad-perf

Performance investigation, benchmarks, and patches for **KiCad** — especially the `kicad-cli` render / export path.

> Working repo. Nothing here is upstreamed. Patches target current KiCad master.

## Layout

```
analysis/     findings, hot-path notes, comparisons to other EDA renderers
patches/      .patch files ready to apply against kicad master (git format-patch)
benchmarks/   hyperfine scripts, board fixtures, perf/strace/callgrind runs
docs/         user-facing docs (daemon quick start, ...)
scratch/      wire-protocol reference client, standalone test server, disposable
```

## Highlights

- **`patches/`** — **55 patches (0001-0055)** applied to KiCad master
  (base `32fcb08d`), all `git am` clean. See
  [`patches/README.md`](patches/README.md) for the full table with
  expected wins and risk notes, and
  [`analysis/04-patch-index.md`](analysis/04-patch-index.md) for an
  overview grouped by axis (startup, board init, plot throughput,
  parser/lexer, daemon, hardening, correctness, schematic init).
  Patches 0052-0055 are new post-build fixes: one correctness bug
  in the P4 lazy-argparse patch (surfaced by actually running the
  patched CLI) plus three per-shape/per-pad hoists in the plot loop.
- **On-version real numbers.** Build unblocked in userspace
  (see `benchmarks/03-build-blocker-notes.md`). Head-to-head with
  3 hyperfine runs after warmup on a quiet CPU:

    |                        | stock 9.0.8 | patched master | ratio |
    |------------------------|------------:|---------------:|------:|
    | `--version` wall       |     229 ms  |    **153 ms**  |  1.50×|
    | `--version` user CPU   |     168 ms  |     109 ms     |  1.54×|
    | `svg export` wall      |    1330 ms  |   **1013 ms**  |  1.31×|
    | `svg export` user CPU  |    1409 ms  |     811 ms     |**1.74×**|
    | `svg export` peak RSS  |   245.5 MB  |    240.0 MB    | -5.5 MB|

  User-CPU savings on `svg export` (42%) exceed wall savings (24%)
  — patched is now IO-bound. See
  [`analysis/09-real-numbers-first-pass.md`](analysis/09-real-numbers-first-pass.md)
  for the detailed reading (RSS curve, why the peak-RSS delta is
  small, what to attack next).
- **`docs/cli-daemon.md`** — quick start for the `kicad-cli daemon`
  socket server (patches 0007-0021). Turns typical CI matrix builds
  from **~45 s → ~1.5 s** after the first invocation.
- **`analysis/`** — five docs:
  - `00-hot-paths.md` — first-pass inventory of where kicad-cli
    burns time (structural review).
  - `01-board-load-init.md` — deep dive into
    `initializeLoadedBoard()`, the biggest single fixed cost.
  - `02-daemon-mode-design.md` — full design of the daemon mode,
    now marked MVP-landed.
  - `03-headless-pcbnew-kiface.md` — proposal for splitting
    `_pcbnew.kiface` into a smaller CLI-only kiface (~100-200 ms
    more per invocation).
  - `04-patch-index.md` — the current-state overview of all 46
    patches, grouped by axis.
- **`benchmarks/`** — five docs:
  - `00-baseline-kicad-9.0.8-aarch64.md` — `hyperfine` + `strace`
    on the stock 9.0.8 binary.
  - `01-patch-syntax-check.md` — `g++ -fsyntax-only` proof that
    every code-change patch parses against real system headers.
  - `02-validation-plan.md` — per-patch hyperfine + bit-compare
    recipes for the eventual runtime pass.
  - `03-build-blocker-notes.md` — what stops the full-tree build
    in userspace right now (cmake wxWidgets detection).
  - `04-apply-check.md` — `git am`-clean confirmation on all 46.

## Reference renderers cloned under `../kicad-references/`

- **kicanvas** — WebGL/Canvas 2D KiCad viewer. Fastest render of KiCad boards known. Study its render pipeline.
- **librepcb** — Qt/OpenGL EDA. Different architecture, useful comparison.
- **horizon-eda** — OpenGL EDA. Fast interactive rendering.
- **gerbv** — canonical Gerber viewer, fast SVG/PNG output.
- **PcbDraw** — Python SVG PCB renderer, fast batch renders.
- **KiKit** — KiCad automation, wraps kicad-cli, its issue tracker knows the pain.
- **InteractiveHtmlBom** — fast client-side board render.
- **skidl** — schematic-as-code.
- **atopile** — modern EDA language + backend.
- **tscircuit** — React-based EDA.

## Current status

See `analysis/00-hot-paths.md` for the first pass at where `kicad-cli` burns time.
