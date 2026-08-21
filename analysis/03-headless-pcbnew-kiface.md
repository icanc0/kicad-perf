# H8 — headless `_pcbnew_cli.kiface`

Follow-up to `benchmarks/00-baseline-kicad-9.0.8-aarch64.md` and
`analysis/01-board-load-init.md`. Measurement said the largest single
fixed cost in every `kicad-cli pcb …` invocation is loading and
initializing `_pcbnew.kiface`:

|                                     | `kicad-cli --version` | `kicad-cli pcb export svg` (156 KB board) | delta                 |
|-------------------------------------|-----------------------|-------------------------------------------|-----------------------|
| wall                                | 260 ms                | 940 ms                                    | +680 ms               |
| user CPU                            | 200 ms                | 800 ms                                    | +600 ms               |
| max RSS                             | 57 MB                 | 219 MB                                    | +162 MB               |
| minor page faults                   | 4,631                 | 33,961                                    | +29,330               |

The 162 MB of freshly-mapped pages is `_pcbnew.kiface` itself plus the
transitive shared-object closure it pulls in (OpenCascade, Cairo, GLU,
GLM, Pixman, Harfbuzz, Freetype, libgit2, libcurl, protobuf, nng, …).

## The kiface is the whole PCB editor

`_pcbnew.kiface` (the ELF shared object loaded via `KIWAY::ProcessJob`
for the `FACE_PCB` face) contains **everything** the pcbnew GUI does:

- The plot engine (`pcbnew/pcb_plotter.cpp`, `plot_board_layers.cpp`,
  `plotters/plotter_*.cpp`) — this is what `kicad-cli pcb export …`
  actually needs.
- The board loader (`pcbnew/board_loader.cpp`, `pcb_io/*`).
- The DRC engine (`pcbnew/drc/*`, `~50` cpp files).
- The router (`pcbnew/router/*`, ~40 files).
- The zone filler (`pcbnew/zone_filler.cpp`).
- The 3D viewer entry points (`3d-viewer/*` linked in).
- Every dialog under `pcbnew/dialogs/*` (~200 wxFormBuilder classes).
- Every tool under `pcbnew/tools/*` (~40 interactive tool classes).
- The PCB widget palette, layer widget, appearance widget, netlist
  panel, etc.
- The API server proto handlers (`pcbnew/api/api_handler_pcb.cpp`).

For a CLI invocation of `pcb export svg`, the plot engine and the board
loader are needed. Everything else is dead weight — mapped by the
dynamic linker, `.init_array` constructors run (many wxWidgets-heavy
static objects), pages committed to the process, and never referenced
again this run.

## Proposal — `_pcbnew_cli.kiface`

A second kiface target, built from the strict subset of `pcbnew/` that
the CLI paths actually need. Loaded by `kicad-cli` in place of
`_pcbnew.kiface` when `Pgm().IsGUI()` returns false.

### Included

- `pcbnew/board_loader.*`, `pcb_io/**` — the file readers/writers.
- `pcbnew/pcb_plotter.*`, `pcbnew/plot_board_layers.*`,
  `pcbnew/plotters/**` — the plotter.
- `pcbnew/pcbnew_jobs_handler.*` — the CLI-side job router.
- `pcbnew/drc/**` — needed for `kicad-cli pcb drc`.
- `pcbnew/zone_filler.cpp` — used by plot jobs' pre-plot zone fill.
- `pcbnew/exporters/**` — gerber jobfile, drill, gencad, ipc2581,
  ipc-d-356, odb, pos, step (guarded by `KICAD_STEP`), stackup, stats.
- `pcbnew/board.cpp`, `pcbnew/board_item.cpp`, `pcbnew/footprint.cpp`,
  `pcbnew/pad.cpp`, `pcbnew/pcb_track.cpp`, `pcbnew/pcb_shape.cpp`,
  `pcbnew/pcb_text.cpp`, `pcbnew/zone.cpp`, `pcbnew/pcb_marker.cpp` —
  the board model.
- `pcbnew/design_rules_parser.cpp`, `pcbnew/drc_rules_lexer.cpp` — DRC
  input.
- `pcbnew/pcb_shape_utils.cpp`, `pcbnew/pcb_dim_*.cpp` — geometry
  helpers the plotter reaches through.
- The BOARD_DESIGN_SETTINGS + BOARD state that plot/export read.

### Excluded

- All of `pcbnew/dialogs/**`.
- All of `pcbnew/tools/**` except `pcbnew/tools/zone_filler_tool.*`
  (that one is used by `getToolManager()` in the CLI jobs handler for
  `--check-zones`).
- All of `pcbnew/router/**` (interactive routing).
- The 3D viewer (`3d-viewer/**`) — unless the split kiface also serves
  `kicad-cli pcb render`. First cut: leave `pcb render` on the full
  kiface. Users doing 3D renders in CI are rare and their wall-time is
  dominated by the raytracer anyway.
- `pcbnew/widgets/**`, `pcbnew/menubar_footprint_*.cpp`,
  `pcbnew/menubar_pcb_*.cpp`.
- `pcbnew/api/api_handler_pcb.cpp` (the proto server) — served by the
  full kiface in api-server mode.

### Link edges

- Still links against `common`, `kicommon`, `kimath`.
- Drops `wx_gtk3u_stc`, `wx_gtk3u_propgrid`, `wx_gtk3u_richtext`,
  `wx_gtk3u_html`, `wx_gtk3u_aui`, `wx_gtk3u_adv`, `wx_gtk3u_gl` from
  its link line (needed only by dialogs / GUI widgets).
- Drops libGLU, libglm-heavy paths, most of OpenCascade (all 5 dev
  packages). Keeps just what board load + geometry + plot need.

## Dispatch

Two options, in increasing order of surgery:

1. **Runtime dispatch** — `KIWAY::ProcessJob` for `FACE_PCB` picks
   between `_pcbnew.kiface` and `_pcbnew_cli.kiface` based on
   `Pgm().IsGUI()`. Minimal touch. Downside: both kifaces linked, both
   symlinked, packaging carries both.

2. **Build-time selection** — `kicad-cli` binary links a `KIFACE`
   trampoline that resolves to the CLI kiface exclusively. Interactive
   apps still get the full kiface. Cleaner runtime, needs CMake to
   build two flavors of the CLI job dispatcher.

Recommend (1) first, then (2) if the split proves stable.

## Expected win

- `_pcbnew_cli.kiface` estimated size: 30-50 MB smaller than
  `_pcbnew.kiface` (currently ~150 MB with debug info, ~35 MB stripped
  on aarch64). At runtime, that's ~50-80 MB fewer RSS pages committed
  per invocation.
- Fewer `.init_array` constructors → 100-200 ms less of static-init
  cost on ARM. On x86_64 with fewer templates instantiated the win is
  smaller (~50-100 ms) but still real.
- Fewer transitive `.so` opens → fewer newfstatat/mmap syscalls (the
  strace showed 3,535 newfstatat on a small SVG export, most of them
  during library load).

Combined with the existing patches (0002-0006 which cut ~80 ms of
kicad-cli-level init and 0003 which cuts ~2 s of board init on big
boards):

| workload                             | stock 9.0.8   | + patches 0001-0006 | + H8 CLI-kiface   | + daemon (H5, patches 0007-0013)               |
|--------------------------------------|--------------:|--------------------:|------------------:|-----------------------------------------------:|
| `--version`                          | 254 ms        | ~180 ms             | ~100 ms           | N/A (client doesn't hit daemon for `--version`) |
| `pcb export svg` — 156 KB board      | 940 ms        | ~700 ms             | ~500 ms           | first call ~500 ms; 2nd+ ~50 ms                |
| `pcb export svg` — 5.6 MB board      | 3120 ms       | ~1600 ms            | ~1400 ms          | first call ~1400 ms; 2nd+ ~50 ms               |
| CI job: 15 exports on 5.6 MB board   | ~45 s         | ~24 s               | ~21 s             | ~2.1 s (60ms × 14 + 1.4 s first)              |

## Cost

- ~2000 LOC of `CMakeLists.txt` and file-inclusion pruning.
- A `KIFACE_PCBNEW_CLI` class that reuses `PCBNEW_JOBS_HANDLER`
  verbatim.
- Careful audit that no `#include`d header from the "included" list
  transitively drags in a `wx_stc.h` or a dialog. `pcb_edit_frame.h` is
  a landmine — it includes the tool manager, action registry, layer
  manager, everything. If any CLI-path header includes it, breaking
  the split.
- Long-term maintenance: two build targets to keep in sync.

## Risk

- Users doing complex `pcb render` in headless CI might notice
  regressions if we accidentally shift them from full to CLI kiface.
  Guard the switch on the argv leaf, not just `Pgm().IsGUI()` —
  something like `if( leafCmd->NeedsFullKiface() )` on the CLI COMMAND
  base class, default true, override false on the geometry-only jobs.

## Order

Do this after landing patches 0001-0013 and getting real numbers from
the full-tree build. Without the measurement, H8 is speculative — the
100-200 ms guess is an estimate from the size delta, not a measurement.

## Not tackled here

- Splitting `_eeschema.kiface` the same way. Eeschema's plot / erc / bom
  paths have the same shape; same argument applies. Once H8 pattern is
  proven on pcbnew, `_eeschema_cli.kiface` is a mechanical copy.
