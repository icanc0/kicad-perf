# Series apply-check — all 50 patches land cleanly

Run 2026-08-22 against the fork's base commit `32fcb08d` ("Move about
dialog names to static const lists.").

## Method

```
cd /path/to/kicad
git worktree add /tmp/kicad-verify 32fcb08d
cd /tmp/kicad-verify
git -c user.email=… -c user.name=… am /path/to/kicad-perf/patches/*.patch
```

## Result

```
Applying: P1: pcb_plotter — skip wxSafeYield in CLI (patch 0001)
Applying: P2: kicad_cli — defer LoadGlobalTables to just before dispatch (patch 0002)
Applying: P3: board_loader + pcbnew_jobs_handler — skip connectivity/DRC/class init for plot/export jobs (patch 0003)
Applying: P4: kicad_cli — lazy argparse subtree build (patch 0004)
Applying: P5: pgm_base — skip libcurl + Sentry init in headless (kicad-cli) mode
Applying: P6: singleton — lazy thread-pool creation (skip ~8 clone() per invocation)
Applying: P7: scaffold kicad-cli daemon subcommand (start/stop/status)
Applying: P8: daemon start body — real Unix-socket bind/listen/accept loop
Applying: P9: daemon request+response wire protocol
Applying: P10: extract OnPgmRun dispatch to CLI::RunKicadCliDispatch; daemon uses it
Applying: P11: daemon stop + status via pidfile
Applying: P12: widen m_cliBoard scalar to small (path,mtime) LRU cache
Applying: P13: --via-daemon client-side auto-connect
Applying: P14: board_loader — skip DS_DATA_MODEL::LoadDrawingSheet reload if unchanged
Applying: P15: daemon — per-dispatch reset guard for wxLog + C locale
Applying: P16: KICAD_CLI_FULL_INIT env-var escape hatch for patch 0003
Applying: P17: guard LoadGlobalTables with std::call_once (fix regression under daemon)
Applying: P18: daemon — respond with error frame if client cwd is unreachable
Applying: P19: daemon — cap total request-frame allocation to prevent memory bomb
Applying: P20: daemon — PID-reuse defence in readLivePid
Applying: P21: daemon start — check pidfile before bind (don't clobber running daemon's socket)
Applying: P22: PLOTTER — 128 KB stdio output buffer instead of default 8 KB
Applying: P23: SVG_PLOTTER::XmlEsc fast-path for strings without any XML specials
Applying: P24: extend 128 KB stdio buffering to gerber workFile and excellon drill writer
Applying: P25: PDF_PLOTTER — level-6 zlib compression instead of level-9 for stream
Applying: P26: PDF_PLOTTER — level-6 zlib on the other three compression sites
Applying: P27: KIPLATFORM::IO::SeqFOpen — treat posix_fadvise failure as harmless
Applying: P28: FILE_LINE_READER::ReadLine — use fgets/memchr instead of per-char getc_unlocked
Applying: P29: DSNLEXER — opt-in curSeparator tracking (skip char-append per token by default)
Applying: P30: sexpr_parser — inline whitespace-char test instead of std::string::find
Applying: P31: extend 64 KB stdio buffer to gencad + IPC-D-356 exporters
Applying: P32: bigger stdio buffer for schematic netlist exporters + PDF workFile
Applying: P33: NETINFO_LIST::buildListOfNets — fast-path when nothing to preserve
Applying: P34: DRC_ENGINE::loadImplicitRules — fix copy-paste typo in courtyard constraint init
Applying: P35: drc_engine loadRules — reserve + move-append instead of copy-push_back
Applying: P36: pgm_base — skip FindPythonInterpreter in headless (kicad-cli) mode
Applying: P37: API_PLUGIN_MANAGER — lazy-load api.v1.schema.json out of ctor
Applying: P38: pgm_base — skip ReadPdfBrowserInfos + NotificationsManager::Load in headless
Applying: P39: pgm_base — register only PNG/JPEG/BMP image handlers in headless
Applying: P40: extend getBoardForExport to IPC-D-356 + position-file exporters
Applying: P41: extend getBoardForExport to Stats/Stackup/GenCAD exporters
Applying: P42: extend getBoardForExport to IPC-2581 and ODB++ exporters
Applying: P43: extend getBoardForExport to STEP/GLB/BREP/XAO/VRML/PLY/STL/STEPZ/U3D/3D-PDF
Applying: P44: extend getBoardForExport to pcb render (3D raytrace)
Applying: P45: eeschema JobExportPlot — skip ConnectionGraph::Recalculate on load
Applying: P46: eeschema JobUpgrade — skip ConnectionGraph::Recalculate on load
Applying: P47: NETINFO_LIST::RebuildDisplayNetnames — memoise wxSplit of long names
Applying: P48: SCH_SHEET_LIST::UpdateSymbol/SheetInstanceData — O(N·M) → O(N·log M)
Applying: P49: SCH_SCREEN::PruneOrphaned{Symbol,Sheet}Instances — precompute lookup map
Applying: P50: SCH_SCREENS::PruneOrphaned{Symbol,Sheet}Instances — build lookup once per hierarchy
```

All 50 apply. No 3-way merges, no conflicts, no rejects. The series is
one continuous line built on top of `master` HEAD at 32fcb08d — a
reviewer can pick individual patches, subranges, or the whole set.

## Notes

- Author + committer on every patch is `icanc0 <ai7@vincentxie.net>`.
- Patches are numbered by application order, not by ID collision with
  upstream KiCad's own patch numbering.
- No patch touches a file that a subsequent patch also touches in a
  conflicting way — each series entry is orthogonal to its successors
  up to the same-file follow-up cases explicitly noted (e.g. 0022 →
  0024 → 0031 → 0032 all bump setvbuf on progressively more `wxFopen`
  callsites).
