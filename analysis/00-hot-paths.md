# kicad-cli hot-path inventory — pass 1

Source read against KiCad `master` at HEAD as of 2026-08-21.
Nothing in this pass has been measured on a running binary; these are structural
red flags from reading the code. Numbers land in `benchmarks/` once a build is
available. Order = strongest suspicion of wasted work first.

## H1. `LoadGlobalTables()` runs on *every* invocation

`kicad/kicad_cli.cpp:529` — `PGM_KICAD::OnPgmInit()`:

```cpp
    GetLibraryManager().LoadGlobalTables();
```

This is called from `APP_KICAD_CLI::OnInit()` **before argv is even parsed**, so
`kicad-cli --version`, `kicad-cli --help`, `kicad-cli pcb export gerbers`,
`kicad-cli gerber info`, `kicad-cli pcb drc` — none of which need the global
symbol / footprint / design-block tables — pay for it.

What `LIBRARY_MANAGER::LoadGlobalTables()` does
(`common/libraries/library_manager.cpp:568`):

1. Locks `m_adaptersMutex`, walks every registered adapter and calls
   `GlobalTablesChanged()`.
2. `loadTables()` — parses the sym-lib-table, fp-lib-table, design-block-table
   files from the user's settings dir.
3. Reads `KICAD_SETTINGS` (`kicad` app settings JSON).
4. Reads `${3RD_PARTY}` env var, and if `m_PcmLibAutoAdd`, `wxDir::Traverse()`
   the packages dir under the user's home (**disk scan on every invocation**).
5. If `m_PcmLibAutoRemove`, walks the sym/fp/design-block tables checking
   `wxFileName::Exists()` for every PCM-managed row (**per-row stat calls**).
6. Writes tables back to disk if any rows were pruned.

**Every kicad-cli invocation stats the PCM dir tree.** For a user with the PCM
enabled and dozens of installed libraries, this is measurable startup overhead
that does nothing for any command whose job doesn't touch libraries.

**Fix (drafted, `patches/0001-*.patch`):** move `LoadGlobalTables()` off
`OnPgmInit` and onto a lazy accessor. The commands that need it
(`pcb export bom`, `pcb export ipc2581`, some import paths) call it explicitly
on the manager the first time they consult a library. This mirrors what
`panel_fp_lib_table.cpp` / `panel_sym_lib_table.cpp` already do — they call
`LoadGlobalTables({LIBRARY_TABLE_TYPE::FOOTPRINT})` scoped to the type they
need.

## H2. argparse tree is built with all 60+ subcommands for every invocation

`kicad/kicad_cli.cpp:547-550`:

```cpp
    for( COMMAND_ENTRY& entry : commandStack )
    {
        recurseArgParserBuild( argParser, entry );
    }
```

Every invocation walks `commandStack` (60+ leaf commands, each with 10-30
arguments), calling `add_subparser` and `add_argument` — every argument
constructs a `std::string` help text (translated via `_(...)`), and the whole
tree is discarded once the subcommand is chosen. `kicad-cli --version` builds
the entire tree only to discard it.

The command objects themselves are static globals (`static CLI::…Cmd{};`
lines 143-228), and their ctors run at program load (before `main`) invoking
`_(...)` on every help string — so gettext is warmed up before argv is even
inspected.

**Fix candidate:** two-tier parse. Do a fast argv scan for the first token
that names a top-level command (`pcb`, `sch`, `sym`, `fp`, `gerber`,
`jobset`, `mergetool`, `import`, `version`). Build the argparse subtree only
for that command. Fall back to the full tree only when the fast scan doesn't
match, or when `--help` is at the top level.

Estimated saving: skips ~59 subcommand-parser constructions per invocation.

## H3. `wxSafeYield()` inside the per-layer plot loop

`pcbnew/pcb_plotter.cpp:311`:

```cpp
        pageNum++;
        wxSafeYield(); // displays report message.
    }
```

`wxSafeYield()` pumps the wx event loop. In the CLI there is no event loop
and no UI to update — this is unconditional wasted work per layer. For a
6-layer board plotted to SVG multi-mode, that's 6× a full yield cycle for no
observable output.

**Fix (drafted, `patches/0002-*.patch`):** guard with `if( Pgm().IsGUI() )`
(the same signal `PCBNEW_JOBS_HANDLER::getBoard` already uses to branch on
CLI vs GUI at line 546).

## H4. Per-layer plot loop is sequential

`pcbnew/pcb_plotter.cpp:153` — `for( size_t i = 0; i < layersToPlot.size(); i++ )`.

Each iteration:

- computes `plotSequence` for this layer,
- `StartPlotBoard` — creates a plotter, opens the output file,
- `PlotBoardLayers( m_board, plotter, plotSequence, m_plotOpts )` — the actual
  render pass over the board geometry, filtered to layers in `plotSequence`,
- `PlotInteractiveLayer` — interactive PDF layer if applicable,
- `plotter->EndPlot()`, delete plotter.

For SVG multi-mode, DXF non-multi-layered, PS, PNG, and Gerber, each layer's
output is an **independent file** and its plot pass is a **read-only** walk of
`m_board`. Nothing in the loop writes back to `m_board` for those formats.
This loop is embarrassingly parallel.

PDF single-mode is not (shared pageful output state), and Gerber with a
`jobfile_writer` needs synchronised access to `AddGbrFile`.

**Fix candidate:** feed independent-per-layer formats through
`GetKiCadThreadPool()` (already exists — teardown calls it at
`kicad_cli.cpp:661`). Chunk = one layer. Requires: making the read path over
`m_board` const-safe (audit `PlotBoardLayers` and everything it reaches).
Zone fill runs *before* the plot loop (line 1440 in jobs handler for SVG), so
zone state is stable by the time layers start.

## H5. `BOARD` fully re-parsed if user shells kicad-cli twice

`getBoard()` at `pcbnew/pcbnew_jobs_handler.cpp:498` caches into
`m_cliBoard` inside a single process, so `jobset run` in one process is fine.
But a shell script like `kicad-cli pcb export svg … && kicad-cli pcb export
drill …` re-parses the board file each time, plus repeats every hit taken in
H1 and H2.

**Fix candidate (biggest):** a `kicad-cli --daemon` / socket mode. One long
lived process, per-request board cache keyed by absolute path + mtime, replies
over a Unix socket. Adjacent to the already-existing
`command_api_server.cpp`. Would give CI users near-instant `kicad-cli` calls
after the first.

Even short of that, a *file-based* cache — hash the board file, cache the
parsed BOARD as a fast binary blob (flatbuffers / cap'n proto) keyed by hash
in `$XDG_CACHE_HOME/kicad/board-cache/` — would remove the re-parse cost.

## H6. Per-command wx / kiface init overhead

Every invocation goes through `wxAppConsole` construction (`IMPLEMENT_APP_CONSOLE(APP_KICAD_CLI)`),
`KIPLATFORM::ENV::Init()`, `KIPLATFORM::APP::Init()`, `PGM_BASE::InitPgm()`,
`SETTINGS_MANAGER` init, `LIBGIT_BACKEND` init, `GetKiCadThreadPool()` warmup.

Some of this is unavoidable for actual work, but:

- **`LIBGIT_BACKEND` init** is only useful for commands that touch VCS
  (`git-mergedriver`, `mergetool`, VCS text-eval in the drawing sheet). Move
  it lazy.
- **`SETTINGS_MANAGER`** loads and validates the user's JSON settings for
  every invocation. `--version` and `--help` don't need it — guard on the
  parsed subcommand.
- **`GetKiCadThreadPool()` teardown** at `OnPgmExit` calls `.purge()` and
  `.wait()` even when the CLI never dispatched to the pool. Harmless if
  empty, but skippable when we know we didn't use it.

Micro, but each saves single-digit ms and adds up at CI scale.

## H7. `magic_enum::enum_names<T>()` called per help build

`command_pcb_render.cpp:64-108` — `enumString<T>()` and `enumChoices<T>()` are
called at ctor time for each of `SIDE`, `BG_STYLE`, `QUALITY`. `magic_enum` is
a header-only compile-time trick, so this is cheap — noting it here so we
don't chase it unnecessarily.

## What's next

- Build kicad from source (deps are heavy; need a build environment).
- Once built, measure H1-H6 with `hyperfine` on `kicad-cli --version` and on
  `pcb export svg` for a representative board (`demos/pic_programmer/` in the
  kicad tree makes a decent fixture).
- Land H3 (trivial) first. Then H1 (small refactor). Then H2 (mechanical but
  wider). H4 needs an audit before it's safe.

## Cross-reference: what other renderers do differently

- **kicanvas** parses `.kicad_pcb` in TypeScript, holds the parsed tree in
  memory, and renders with Canvas2D. No wxWidgets, no gettext, no plugin
  system. Startup is a JS module load.
- **PcbDraw** shells out to KiCad's Python API and processes SVGs — but
  memoises intermediate results aggressively.
- **gerbv** is a single C process with GTK — trivial startup, direct Cairo
  output. This is the shape kicad-cli aspires to when it's just doing SVG.
