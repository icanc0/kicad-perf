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

- **`patches/`** — 15 patches (0001-0015) applied to KiCad master, all
  `git format-patch` clean. See [`patches/README.md`](patches/README.md)
  for the full table with expected wins and risk notes.
- **`docs/cli-daemon.md`** — quick start for the `kicad-cli daemon`
  socket server (patches 0007-0015). Turns typical CI matrix builds
  from 45 s to 2 s.
- **`analysis/`** — three design docs:
  - `00-hot-paths.md` — first-pass inventory of where kicad-cli
    burns time (structural review).
  - `01-board-load-init.md` — deep dive into
    `initializeLoadedBoard()`, the biggest single fixed cost.
  - `02-daemon-mode-design.md` — full design of the daemon mode,
    now marked MVP-landed.
  - `03-headless-pcbnew-kiface.md` — proposal for splitting
    `_pcbnew.kiface` into a smaller CLI-only kiface (~100-200 ms
    more per invocation).
- **`benchmarks/00-baseline-kicad-9.0.8-aarch64.md`** — real
  `hyperfine` + `strace` numbers on the stock 9.0.8 binary.
- **`benchmarks/01-patch-syntax-check.md`** — `g++ -fsyntax-only`
  proof that all six code-change patches compile clean against real
  system headers.

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
