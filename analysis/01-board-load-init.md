# Where the "3 seconds per PCB command" actually goes

Follow-up to `00-hot-paths.md` and `benchmarks/00-baseline-kicad-9.0.8-aarch64.md`.

Numbers say fixed cost per `pcb export …` invocation is ~3 s on the 5.6 MB
video demo board, and only ~940 ms on a 156 KB board — so ~2 s of that
scales with the board.

Reading `pcbnew/board_loader.cpp:106` (`initializeLoadedBoard`) explains the
scaling: every `getBoard()` call in `pcbnew_jobs_handler.cpp` runs, in this
order:

1. `DS_DATA_MODEL::LoadDrawingSheet` — sheet template load.
2. Rebuild `ENUM_MAP<PCB_LAYER_ID>` (linear scan on every layer, twice).
3. **Instantiate `DRC_ENGINE`** and `InitEngine( rules )` — reads and
   compiles `.kicad_dru`. Board with a big rules file pays here.
4. `ResolveDRCExclusions( true )` — walks exclusion state.
5. **`BuildConnectivity()`** — full ratsnest graph.
   *This is the top single cost on any non-trivial board.* It walks every
   track / via / pad, builds spatial indices, computes net → item maps.
6. `BuildListOfNets()`, `SynchronizeNetsAndNetClasses(true)`.
7. **`SynchronizeComponentClasses()`** — walks every footprint applying
   project-level class rules.
8. `SynchronizeTuningProfileProperties()`.

Steps 3, 4, 5, 6, 7, 8 are all required for interactive PCB editing, DRC,
and BOM-style jobs. They are **entirely wasted** for the plot / export
commands, which only walk geometry:

- `svg`, `pdf`, `png`, `dxf`, `ps` — call into `PCB_PLOTTER::Plot` →
  `PlotBoardLayers` → `PLOTTER::PlotItem` per drawable. Reads
  `GetPageSettings`, `GetDesignSettings`, `GetLayerName`. Doesn't touch
  connectivity or DRC.
- `gerbers`, `drill`, `gencad`, `ipc2581`, `ipcd356`, `stackup`, `stats` —
  same. Gerber X2 attributes need the *net name*, which is already stored on
  each PCB_TRACK. It doesn't need the connectivity graph.

Consequence: `patches/0003-board_loader-skip-…patch` — the biggest single
patch in this repo so far. Adds seven `bool` flags to
`BOARD_LOADER::OPTIONS` (all default true → no callsite churn), gates the
corresponding steps in `initializeLoadedBoard`, and gives
`PCBNEW_JOBS_HANDLER` a new `getBoardForExport()` helper that turns them all
off.

## Expected impact

- Small board (`ecc83-pp.kicad_pcb`, 156 KB): ~940 ms → ~700 ms (guess).
  Small win — the board is tiny so connectivity build is fast.
- Big board (`video.kicad_pcb`, 5.6 MB): ~3.1 s → **~1.5-1.8 s (guess)**.
  Half the runtime, because connectivity/DRC/class-sync scale with the
  number of items on the board.

Actual measurements land in `benchmarks/01-after-patch-0003.md` once the
patch builds.

## Follow-ups this uncovers

- `ENUM_MAP<PCB_LAYER_ID>` rebuild in step 2 is O(layers²) in the worst
  case (`Choices().Clear()` then per-layer `Undefined()` scan and two
  `Map()` inserts). It's small (60 layers) so probably ignorable, but
  worth a look with callgrind.

- `LoadDrawingSheet` step 1 opens and parses the sheet template. If the
  board uses the default sheet, this could be shared across boards in the
  same process (cache on `DS_DATA_MODEL`).

- The DRC engine holds a shared_ptr to a compiled rules AST. Once we skip
  DRC init for plot jobs, `BOARD_DESIGN_SETTINGS::m_DRCEngine` is `nullptr`
  during plot. Nothing in the plot path dereferences it — verified by
  grepping `m_DRCEngine` under `pcbnew/plotters/` and `pcbnew/pcb_plotter*`
  (no hits). A follow-up wants a `wxCHECK_MSG( m_DRCEngine, … )` around any
  path that could hit it while a plot job is in flight, to catch a future
  regression.

## Why upstream might resist

Fine-grained flags are ugly, and preemptively lazy-loading in
`BOARD::GetConnectivity()` (build on first access) is cleaner. That works,
but breaks the invariant "if you got a BOARD*, it has a live connectivity
graph" — which some interactive code relies on for immediate ratsnest
draw. Fine-grained flags default-true respect that invariant; the CLI opts
out explicitly.
