# kicad-perf

Performance investigation, benchmarks, and patches for **KiCad** — especially the `kicad-cli` render / export path.

> Working repo. Nothing here is upstreamed. Patches target current KiCad master.

## Layout

```
analysis/     findings, hot-path notes, comparisons to other EDA renderers
patches/      .patch files ready to apply against kicad master (git format-patch)
benchmarks/   hyperfine scripts, board fixtures, perf/strace/callgrind runs
scratch/      temporary work, prototypes, disposable
```

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
