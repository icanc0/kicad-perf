# Patch series

Applied against KiCad `master` HEAD as of 2026-08-21.
Each patch is a `git format-patch` output — `git am` or `git apply` clean.

| # | patch                                                                            | scope                                                                                                       | expected win               | risk    |
|---|----------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------|----------------------------|---------|
| 1 | `0001-pcb_plotter-skip-wxSafeYield-in-CLI.patch`                                 | gate `wxSafeYield()` on `Pgm().IsGUI()` in the per-layer plot loop                                          | ~1-5 ms per layer, CLI     | trivial |
| 2 | `0002-kicad_cli-defer-LoadGlobalTables.patch`                                    | move `LoadGlobalTables()` out of `OnPgmInit`, run just before `cliCmd->Perform()`                           | 20-100 ms on `--version`/`--help`/arg-err   | low     |
| 3 | `0003-board_loader-skip-connectivity-drc-init-for-export.patch`                  | fine-grained `BOARD_LOADER::OPTIONS` flags; new `getBoardForExport()` skips connectivity/DRC/class/tuning for plot/gerber/drill/dxf/ps/pdf/png/svg | **~2 s on 5.6 MB board plot** — the biggest single win | **medium** — must audit that plot codepaths never touch DRC engine / connectivity |
| 4 | `0004-kicad_cli-lazy-argparse-subtree.patch`                                     | scan argv for the top-level cmd; only build that subtree of argparse. Full tree still built for --help / unknown-cmd | ~5-20 ms per invocation    | low     |
| 5 | `0005-pgm_base-skip-curl-sentry-in-headless.patch`                               | gate `KICAD_CURL::Init()`, `SENTRY::Init()`, and Sentry `AddTag` on `!aHeadless`                             | ~10-50 ms per CLI invocation | low     |
| 6 | `0006-singleton-lazy-thread-pool.patch`                                          | `KICAD_SINGLETON` stops eagerly spawning N worker threads; `std::call_once`-guarded `EnsureThreadPool()` runs on first task submission | **avoid 8 clone()+join() per invocation**, esp. for `--version` / `--help` / small exports | low-medium — must never take a raw pointer to the pool before first submit |
| 7 | `0007-cli-daemon-scaffold.patch`                                                | new `kicad-cli daemon {start,stop,status}` verb + subcommands (all currently stub-print "not yet implemented"). Argparse plumbing + CMake entry only, so follow-up patches for the socket/dispatcher/cache have somewhere to land. | 0 today; unlocks 10-60× via daemon | trivial |
| 8 | `0008-cli-daemon-socket-server-body.patch`                                       | fill in `daemon start`: default `$XDG_RUNTIME_DIR/kicad-cli.sock`, `bind()+chmod(0600)+listen()`, SIGINT/SIGTERM clean-exit, `accept4()` loop, per-client stub. Dispatcher lands next. | 0 today; unlocks daemon | low — well-scoped POSIX socket code |
| 9 | `0009-cli-daemon-wire-protocol.patch`                                            | length-prefixed binary request/response framing (KCLI/STAT magic + argc + args + cwd for req; exit + stdout + stderr for resp). Validated end-to-end with a standalone C server + Python client (`scratch/wire_protocol_test_server.c`, `scratch/kicad_cli_daemon_client.py`) — argv[0..6] + cwd round-trip clean. | 0 today; unlocks daemon dispatch | low — pure framing, no kicad state touched |
| 10 | `0010-cli-daemon-dispatch-integration.patch`                                    | extract `PGM_KICAD::OnPgmRun`'s argparse+dispatch body into a new `CLI::RunKicadCliDispatch(argc, argv)` (new `cli/dispatch.h`). Daemon `handleOneClient` chdir()s to request cwd, dup2()s stdout/stderr into pipes, calls `RunKicadCliDispatch`, packages exit + captures back into response frame. This closes the daemon MVP loop end-to-end. | **10-60× on CI-style multi-invocation workloads** | medium — first invocation of `Perform()` on the same command twice must be safe; global state (LOCALE_IO, wxLog sinks) needs a follow-up sweep |
| 11 | `0011-cli-daemon-stop-status-pidfile.patch`                                    | pidfile at `$SOCKET.pid`; `daemon stop` sends SIGTERM and polls for exit; `daemon status` reports RUNNING/STALE/NOT RUNNING and probes `connect()` on the socket. `daemon start` refuses when a live daemon is already at the same path. | 0 today; makes daemon operable | low |
| 12 | `0012-pcbnew-board-cache-lru.patch`                                             | replace `m_cliBoard` scalar with a 4-slot `std::deque<CACHED_BOARD>` LRU keyed on (abs path, mtime, forExport flag). Under the daemon, a 'render four boards' loop stops paying parse+init per board per output format. mtime check picks up user edits with no explicit flush. | **daemon: 3-10× extra speedup on repeated-board workflows**; direct CLI: no change (cache holds at most 1 entry per invocation) | low |
| 13 | `0013-cli-via-daemon-client.patch`                                              | new `CLI::TryRunViaDaemon()` — engaged by `--via-daemon` argv flag or `KICAD_CLI_DAEMON=1` env var. Marshals argv+cwd to the daemon socket, streams stdout/stderr back, exits with the daemon's status. Graceful fallback to in-process dispatch on any local failure (missing socket, ECONN, protocol error) so CI scripts can set the env var unconditionally. | 0 today; unlocks daemon for users | low |
| 14 | `0014-board_loader-drawing-sheet-cache.patch`                                   | tiny (path, mtime) static in `initializeLoadedBoard()` — skip `DS_DATA_MODEL::LoadDrawingSheet` reparse if the last load already put the same file in the singleton. | 0 direct CLI; ~5-20 ms per board under the daemon when the whole batch shares one drawing sheet | trivial |
| 15 | `0015-daemon-per-dispatch-reset.patch`                                          | `PerDispatchReset` RAII around each daemon `handleOneClient` — snapshot + restore `wxLog::GetActiveTarget()` and `setlocale(LC_ALL, nullptr)`. Stops a command that stashes a temporary log sink from leaking it into the next request. | robustness, not perf | trivial |
| 16 | `0016-cli-full-init-env-escape.patch`                                           | `KICAD_CLI_FULL_INIT=1` env-var routes `getBoardForExport` back through the standard full-init `getBoard`. Escape hatch for the narrow class of legacy/hand-edited boards whose zone net_codes need post-parse fixup (see `analysis/01-board-load-init.md` caveat). | 0 today; makes 0003 safe to enable by default | trivial |
| 17 | `0017-loadglobaltables-once-per-process.patch`                                  | wrap the deferred `LoadGlobalTables()` in `std::call_once`. Fixes a regression from 0002 + 0010: under the daemon the tables were being re-parsed on every request, wiping the whole point of 0002. | daemon: recovers ~30-100 ms per request | trivial |
| 18 | `0018-daemon-error-on-chdir-fail.patch`                                         | `handleOneClient` was silently ignoring `chdir()` errors. Now the client gets a specific error frame ("cannot chdir to client cwd '/path': No such file or directory") instead of a mysterious "board file does not exist" from the dispatcher. | robustness | trivial |
| 19 | `0019-daemon-cap-request-alloc.patch`                                           | wire-protocol reader was capped per-arg (4 MB) but not cumulatively — a peer could ask for 4096 args × 4 MB = 16 GB alloc. New per-arg cap 1 MB and cumulative-request cap `kMaxFrame` (4 MB). | security / DoS hardening | trivial |
| 20 | `0020-daemon-pid-reuse-defence.patch`                                           | `readLivePid` used only `kill(pid, 0)` — succeeds for ANY live same-user process, so a recycled PID would make `daemon stop` SIGTERM an unrelated process. Add a `/proc/<pid>/comm` prefix check for `kicad-cli`. | security | trivial |
| 21 | `0021-daemon-check-pidfile-before-bind.patch`                                   | `daemon start` was calling `bindListen` before the pidfile check. `bindListen` unlinks any existing socket first, so an accidental double-start would silently destroy the running daemon's socket file (clients then get ECONNREFUSED, running daemon still alive but unreachable). Reorder: pidfile check → bind. | robustness | trivial |
| 22 | `0022-plotter-larger-stdio-buffer.patch`                                         | `PLOTTER::OpenFile` was using stdio's default 4-8 KB buffer. All plotters (Gerber, SVG, PS, DXF, PDF) push tens of thousands of short lines through `fprintf`/`fmt::println` — every ~800 lines flushed to a `write()` syscall. `setvbuf(_IOFBF, 128 KB)` collapses that. | ~5-30 ms per plot | trivial |
| 23 | `0023-svg-xmlesc-fast-path.patch`                                                | `SVG_PLOTTER::XmlEsc` iterated char-by-char even when no XML special chars existed (99% of net names, refdes, layer titles). Add `find_first_of` fast-path that returns the original wxString unmodified when nothing needs escaping. | ~5-15 ms per big SVG plot; more with lots of text | trivial |
| 24 | `0024-extend-stdio-buffer-to-gerber-workfile-and-drill.patch`                    | 0022 buffered PLOTTER::OpenFile. GERBER_PLOTTER swaps in its own temp workFile after that, and EXCELLON_WRITER opens .drl files with wxFopen directly — both bypassed 0022. Add matching `setvbuf` in those spots. | small, cumulative with 0022 | trivial |
| 25 | `0025-pdf-zlib-level-6.patch`                                                     | PDF stream compression was `wxZ_BEST_COMPRESSION` (zlib level 9) — 5× slower than level 6 for maybe 1-2% smaller output. Drop to `wxZ_DEFAULT_COMPRESSION` (level 6). | **~2-3× faster PDF export**; 5-10% larger .pdf files | low — visible file size delta |
| 26 | `0026-pdf-zlib-level-6-image-and-3d-streams.patch`                               | 0025 only covered the page-content stream. Three more PDF sites still used level 9 (image XObject, SMask, 3D model attachment). Convert all three. | more of the PDF-export speedup on boards with images / 3D-PDF | low |
| 27 | `0027-kiplatform-fadvise-not-fatal.patch`                                        | `KIPLATFORM::IO::SeqFOpen` was closing a successfully-opened file if `posix_fadvise()` returned any error. Every `FILE_LINE_READER` caller (board load, footprint load, drawing sheet load, DRC rules, netlist) then threw the wrong error. fadvise is advisory — ignore its failures. | correctness / usability — fixes 'Unable to open %s' errors on FUSE / network / VM overlays where fadvise isn't supported | trivial |
| 28 | `0028-line-reader-fgets-fast-path.patch`                                          | `FILE_LINE_READER::ReadLine` looped one char at a time via `getc_unlocked` + a bounds-check pair. Rewrite to grow the buffer and use `fgets` — glibc calls memchr internally (vectorised) to scan for `\n`, 8-16× faster than the per-char loop. | ~50-100 ms on board-load for a big .kicad_pcb | low — same visible semantics |
| 29 | `0029-dsnlexer-opt-in-separator-tracking.patch`                                   | `DSNLEXER::NextTok` was char-appending each whitespace byte into `curSeparator` on every token. Only `DRC_RULES_PARSER` reads that string. Make it opt-in via `SetTrackSeparator(true)` in the DRC parser ctor. | ~10-30 ms on board-load; more on token-dense files | trivial |
| 30 | `0030-sexpr-parser-inline-whitespace-test.patch`                                  | `SEXPR::PARSER::parseString` was calling `whitespaceCharacters.find(*it) != npos` (linear scan over 7 chars) for every input byte. Replace with an inlined switch. | small but per-byte; noticeable on schematic parse | trivial |
| 31 | `0031-gencad-d356-stdio-buffer.patch`                                             | Extend 0022's `setvbuf` pattern to two more wxFopen callers that were still on default BUFSIZ: GenCAD writer, IPC-D-356 writer. | small cumulative | trivial |
| 32 | `0032-more-stdio-buffer-eeschema-netlist-and-pdf-workfile.patch`                  | Extends the setvbuf pattern to five more direct-fopen writers: eeschema's cadstar/orcadpcb2/pads/allegro netlist exporters, plus PDF_PLOTTER's temp workFile used to accumulate one page before compression. | small cumulative | trivial |
| 33 | `0033-netinfo-list-fast-path-when-no-net-chains.patch`                            | `NETINFO_LIST::buildListOfNets` always built three `unordered_map<int,…>` reserved for `GetNetCount()`, populated them from all nets, Clear()d, then restored — to preserve `(net_chains ...)` data that only exists on a small minority of boards. Add a one-pass detector; if nothing to preserve, skip the whole dance. | small on typical boards; the win is per-net so scales with net count | trivial |
| 34 | `0034-drc-engine-fix-courtyard-init-typo.patch`                                   | DRC_ENGINE::loadImplicitRules had `holeToHoleConstraint.Value().SetMin(0)` inside the "courtyard" block — copy-paste from the earlier hole block, writing to the wrong local. Was a no-op; courtyardClearanceConstraint was added with default value. Behaviour unchanged today (default is 0) but the intent needed to be explicit. | correctness | trivial |
| 35 | `0035-drc-engine-bulk-move-rules.patch`                                           | `loadRules` was appending each rule via `m_rules.push_back(rule)` — copy-append of a shared_ptr, so two atomic refcount ops per rule. Reserve + `push_back(std::move(rule))` collapses to a move. | micro | trivial |
| 36 | `0036-pgm-skip-python-search-in-headless.patch`                                   | `PGM_BASE::InitPgm` unconditionally called `PYTHON_MANAGER::FindPythonInterpreter()` when no interpreter was cached — up to 3 synchronous fork/exec calls (`which -a python3`, `which -a python`). Guard on `!aHeadless`. | ~10-30 ms per kicad-cli startup | trivial |
| 37 | `0037-api-plugin-lazy-schema.patch`                                              | `API_PLUGIN_MANAGER` ctor parsed `api.v1.schema.json` into a `JSON_SCHEMA_VALIDATOR` — dozens of ms of JSON parse and the "schemas/api.v1.schema.json not found" stderr warning at every kicad-cli startup. Move to lazy `ensureSchemaLoaded()` triggered from `ReloadPlugins()`. | ~10-40 ms per kicad-cli startup; kills the stderr warning too | low |
| 38 | `0038-skip-pdf-browser-and-notifications-in-headless.patch`                       | Two more GUI-only init calls in InitPgm: `ReadPdfBrowserInfos` (probes for PDF viewer commands so the GUI menu can offer them) and `NotificationsManager::Load` (parses persisted notifications for the GUI panel). Guard on `!aHeadless`. | small; ~5-20 ms per kicad-cli startup | trivial |
| 39 | `0039-minimal-image-handlers-in-headless.patch`                                   | `wxInitAllImageHandlers()` registers 11+ image codecs (GIF, TIFF, TGA, XPM, PCX, PNM, IFF, ANI, ICO, PICT, XBM …). Headless kicad-cli only reads/writes PNG/JPEG (embedded, pcb render) and BMP (bitmap2component). Register just the three in headless. | small per-startup + smaller RSS | trivial |
| 40 | `0040-getboardforexport-ipcd356-pos.patch`                                        | Extend 0003's export-only board load path to two more read-only-over-geometry exporters that still used full-init `getBoard()`: IPC-D-356 test-point netlist, position file. | ~1-2 s on big boards, same as 0003 | low |
| 41 | `0041-getboardforexport-stats-stackup-gencad.patch`                               | Same treatment for Stats, Stackup, and GenCAD exporters. All three walk geometry / stackup metadata only — none touch connectivity or DRC engine (verified). | ~1-2 s on big boards, same as 0003 | low |
| 42 | `0042-getboardforexport-ipc2581-odb.patch`                                       | Same treatment for IPC-2581 and ODB++ exporters. Audited pcbnew/pcb_io/{ipc2581,odbpp}/ — zero GetConnectivity or m_DRCEngine references. | ~1-2 s on big boards, same as 0003 | low |
| 43 | `0043-getboardforexport-3d-exporters.patch`                                       | All JobExportStep-routed formats (STEP, GLB, BREP, XAO, VRML, PLY, STL, STEPZ, U3D, 3D-PDF) walk board-outline geometry + footprint 3D model paths only. Audited pcbnew/exporters/step/: no connectivity/DRC/component-class deps. | ~1-2 s on big-board 3D export | medium — 3D path is complex; verify a sample STEP round-trips |
| 44 | `0044-getboardforexport-pcb-render.patch`                                        | pcb render 3D raytrace also walks board outline + footprint 3D models only. Audited 3d-viewer/: no connectivity/DRC/component-class refs. | ~1-2 s off the fixed-init portion of pcb render | medium — same audit-required note as 0043 |
| 45 | `0045-schematic-plot-skip-connectivity.patch`                                    | `EESCHEMA_HELPERS::LoadSchematic` already exposed an `aCalculateConnectivity` bool but the CLI never threaded it through. Add a two-arg `getSchematic` and pass `false` from `JobExportPlot` (svg/pdf/ps/dxf/hpgl/png). ERC/BOM/netlist still get full init. | connectivity+dangling-ends+annotate skipped — noticeable on big schematics | medium — plot code must not read ConnectionGraph |

## Expected combined win (theoretical, not yet measured)

Applying 0001-0006 to `kicad-cli --version` on the aarch64 baseline (254 ms):

  254 ms
  -  ~5 ms  (0004: no full argparse tree)
  -  ~30 ms (0002: no LoadGlobalTables)
  -  ~20 ms (0005: no curl / no Sentry)
  -  ~15 ms (0006: no eager thread pool)
  ────────
  ≈ 180 ms  (~30 % faster)

For `kicad-cli pcb export svg` on the 5.6 MB video board (3121 ms):

  3121 ms
  -  ~30 ms (0002 + 0004 + 0005 + 0006, same as above)
  -  ~1500 ms (0003: no BuildConnectivity / DRC init / class sync on big board)
  -  ~5 ms   (0001, per layer)
  ────────
  ≈ 1600 ms  (~48 % faster)

**These are engineering estimates**, not measured — pending a full-tree kicad
build (see `benchmarks/00-baseline-*.md` for why the build is currently on
hold; deps chase is expensive in userspace).

## Not-yet-a-patch (design docs)

- **H5 daemon mode** (`kicad-cli --daemon`) — biggest remaining lever. One
  long-lived process, per-request BOARD cache keyed by path+mtime, Unix
  socket. Estimated: post-first-invocation, wall-clock drops from ~1.6 s to
  under 100 ms.
- **H8 headless pcbnew.kiface** — split the plotter / DRC / exporter code out
  of the pcbnew kiface, so `kicad-cli` links only what it needs. Estimated:
  -100 to -300 ms per CLI invocation (kiface load + init).
- **Per-layer parallel plot** — dropped for now; measurement showed
  incremental cost per extra layer is ~26 ms, so the max parallelization win
  on a 6-layer plot is ~130 ms out of 3 s. Land later.

## How to apply

```
cd /path/to/kicad-source
git checkout -b perf-batch1
git am /path/to/kicad-perf/patches/*.patch
```

or individually:

```
git apply --index /path/to/kicad-perf/patches/0003-*.patch
```
