# Patch series overview — 46 patches, grouped by axis

Each row links to a patch under `patches/` and states one primary
axis and one secondary axis when it applies. Numbers are the
engineering estimates from `patches/README.md`; real hyperfine deltas
land in `benchmarks/03-*.md` once a build is available (see
`benchmarks/03-build-blocker-notes.md`).

## A. Startup cost of every `kicad-cli` invocation

Direct impact on `--version`, `--help`, and the fixed-init overhead
of every subcommand.

| # | patch                                                | axis        | estimate         |
|--:|------------------------------------------------------|-------------|------------------|
|  2 | 0002-kicad_cli-defer-LoadGlobalTables                | init        | 20-100 ms        |
|  4 | 0004-kicad_cli-lazy-argparse-subtree                 | init        | 5-20 ms          |
|  5 | 0005-pgm_base-skip-curl-sentry-in-headless           | init        | 10-50 ms         |
|  6 | 0006-singleton-lazy-thread-pool                      | init        | 8 threads spared |
| 17 | 0017-loadglobaltables-once-per-process               | daemon-perf | 30-100 ms/req    |
| 36 | 0036-pgm-skip-python-search-in-headless              | init        | 10-30 ms         |
| 37 | 0037-api-plugin-lazy-schema                          | init        | 10-40 ms + kills stderr warning |
| 38 | 0038-skip-pdf-browser-and-notifications-in-headless  | init        | 5-20 ms          |
| 39 | 0039-minimal-image-handlers-in-headless              | init        | small per-startup + RSS |

Combined estimate on 254 ms `--version`: **~120-350 ms saved** (fresh
CLI startup cost drops toward what `wxWidgets` init + one syscall
sequence actually costs).

## B. Per-invocation board init

Dominant cost on every `pcb …` command past the fixed init above.

| # | patch                                                            | axis        | estimate                  |
|--:|------------------------------------------------------------------|-------------|---------------------------|
|  3 | 0003-board_loader-skip-connectivity-drc-init-for-export          | init        | **~1500 ms**              |
| 14 | 0014-board_loader-drawing-sheet-cache                            | init/daemon | 5-20 ms / board           |
| 16 | 0016-cli-full-init-env-escape                                    | correctness | 0 (safety hatch)          |
| 33 | 0033-netinfo-list-fast-path-when-no-net-chains                   | init        | per-net, small on typical |
| 40 | 0040-getboardforexport-ipcd356-pos                               | init        | ~1-2 s / big board        |
| 41 | 0041-getboardforexport-stats-stackup-gencad                      | init        | ~1-2 s / big board        |
| 42 | 0042-getboardforexport-ipc2581-odb                               | init        | ~1-2 s / big board        |
| 43 | 0043-getboardforexport-3d-exporters                              | init        | ~1-2 s / big board        |
| 44 | 0044-getboardforexport-pcb-render                                | init        | ~1-2 s / big board        |

Every `pcb export …` command **and** `pcb render` now uses the
fast-load path. Only `pcb export bom` (needs sym/fp libraries)
still goes through the full-init `getBoard`.

## C. Schematic-side init

Same pattern as B, on the eeschema side.

| # | patch                                                            | axis   | estimate                        |
|--:|------------------------------------------------------------------|--------|---------------------------------|
| 45 | 0045-schematic-plot-skip-connectivity                            | init   | ~2 s off big-schematic plots    |
| 46 | 0046-sch-upgrade-skip-connectivity                               | init   | same                            |

## D. Plot-time throughput

Per-plot output cost: file writes, stream compression, XML escape.

| # | patch                                                                            | axis        | estimate                |
|--:|----------------------------------------------------------------------------------|-------------|-------------------------|
|  1 | 0001-pcb_plotter-skip-wxSafeYield-in-CLI                                         | plot        | ~1-5 ms / layer         |
| 22 | 0022-plotter-larger-stdio-buffer                                                  | plot        | 5-30 ms / plot          |
| 23 | 0023-svg-xmlesc-fast-path                                                         | svg         | 5-15 ms / svg           |
| 24 | 0024-extend-stdio-buffer-to-gerber-workfile-and-drill                             | gerber/drill| 5-15 ms                 |
| 25 | 0025-pdf-zlib-level-6                                                             | pdf         | **~2-3× faster PDF**    |
| 26 | 0026-pdf-zlib-level-6-image-and-3d-streams                                        | pdf         | more PDF speedup        |
| 31 | 0031-gencad-d356-stdio-buffer                                                     | gencad/d356 | small cumulative        |
| 32 | 0032-more-stdio-buffer-eeschema-netlist-and-pdf-workfile                          | plot/netlist| small cumulative        |

## E. Parser / lexer

Board load (~2 s on a 5 MB board) is dominated by tokenisation.

| # | patch                                                            | axis    | estimate           |
|--:|------------------------------------------------------------------|---------|--------------------|
| 27 | 0027-kiplatform-fadvise-not-fatal                                | correct | fixes false failure|
| 28 | 0028-line-reader-fgets-fast-path                                 | parse   | 50-100 ms / board  |
| 29 | 0029-dsnlexer-opt-in-separator-tracking                          | parse   | 10-30 ms / board   |
| 30 | 0030-sexpr-parser-inline-whitespace-test                         | parse   | small, per-byte    |

## F. `kicad-cli daemon` — MVP (patches 0007-0013)

Long-lived server so CI matrix builds pay per-invocation cost once,
not per invocation.

| # | patch                                                     | axis   | rôle                                 |
|--:|-----------------------------------------------------------|--------|--------------------------------------|
|  7 | 0007-cli-daemon-scaffold                                  | daemon | subcommand tree + CMake              |
|  8 | 0008-cli-daemon-socket-server-body                        | daemon | bind/listen/accept + signal handling |
|  9 | 0009-cli-daemon-wire-protocol                             | daemon | length-prefixed frame parser/writer  |
| 10 | 0010-cli-daemon-dispatch-integration                      | daemon | route request through argparse+cmds  |
| 11 | 0011-cli-daemon-stop-status-pidfile                       | daemon | pidfile-based lifecycle              |
| 12 | 0012-pcbnew-board-cache-lru                               | daemon | 4-entry (path,mtime) BOARD cache     |
| 13 | 0013-cli-via-daemon-client                                | daemon | `--via-daemon` / `KICAD_CLI_DAEMON`  |

Full-cycle CI (15 exports on one board): **~45 s → ~2 s** cold, then
50 ms per follow-up call.

## G. Daemon hardening (patches 0015, 0018-0021)

Follow-ups to F, all found by branch-sweep passes.

| # | patch                                                | axis        | rôle                                                |
|--:|------------------------------------------------------|-------------|-----------------------------------------------------|
| 15 | 0015-daemon-per-dispatch-reset                       | robustness  | wxLog + locale scope-guard per dispatch             |
| 18 | 0018-daemon-error-on-chdir-fail                      | usability   | client sees a real error, not "board not found"    |
| 19 | 0019-daemon-cap-request-alloc                        | security    | cumulative-frame cap, prevents 16 GB alloc          |
| 20 | 0020-daemon-pid-reuse-defence                        | security    | /proc/comm check before SIGTERM to a foreign pid    |
| 21 | 0021-daemon-check-pidfile-before-bind                | robustness  | don't unlink running daemon's socket on double-start|

## H. Correctness / cleanup

| # | patch                                        | axis        | note                                           |
|--:|----------------------------------------------|-------------|------------------------------------------------|
| 34 | 0034-drc-engine-fix-courtyard-init-typo     | correctness | copy-paste bug; harmless today, footgun tomorrow |
| 35 | 0035-drc-engine-bulk-move-rules             | micro       | reserve + move-append instead of copy push_back  |

## Cross-references

- **Design docs:** `analysis/00-hot-paths.md`, `analysis/01-board-load-init.md`,
  `analysis/02-daemon-mode-design.md`, `analysis/03-headless-pcbnew-kiface.md`.
- **User docs:** `docs/cli-daemon.md`.
- **Benchmarks:** `benchmarks/00-baseline-kicad-9.0.8-aarch64.md`,
  `benchmarks/01-patch-syntax-check.md`, `benchmarks/02-validation-plan.md`,
  `benchmarks/03-build-blocker-notes.md`.
- **Reference client / test harness:** `scratch/kicad_cli_daemon_client.py`,
  `scratch/wire_protocol_test_server.c` (validates the wire protocol
  without needing a KiCad build).

## Combined expected win (very rough)

|                                        | stock 9.0.8 | with A-E patches | with A-G (daemon)    |
|----------------------------------------|-------------|------------------|----------------------|
| `--version`                            | 254 ms      | ~90 ms           | N/A (client short-circuits)|
| `pcb export svg` — 156 KB board        | 940 ms      | ~350 ms          | first ~350, 2nd+ ~50 |
| `pcb export svg` — 5.6 MB board        | 3121 ms     | ~800 ms          | first ~800, 2nd+ ~50 |
| `pcb export pdf` — 5.6 MB board        | 3383 ms     | ~700 ms          | first ~700, 2nd+ ~50 |
| `pcb render` — video demo              | multi-second| ~1-2 s off init  | first ~cold, 2nd+ ~50 (data only) |
| CI: 15 exports on 5.6 MB board         | ~45 s       | ~12 s            | ~1.5 s               |
