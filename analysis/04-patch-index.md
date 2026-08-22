# Patch series overview — 30 patches, grouped by axis

Each row links to a patch under `patches/` and states one primary
axis and one secondary axis when it applies. Numbers are the
engineering estimates from `patches/README.md`; real hyperfine deltas
land in `benchmarks/03-*.md` once a build is available (see
`benchmarks/03-build-blocker-notes.md`).

## A. Startup cost of every `kicad-cli` invocation

Direct impact on `--version`, `--help`, and the fixed-init overhead
of every `pcb export …` call.

| # | patch                                                | axis   | estimate         |
|--:|------------------------------------------------------|--------|------------------|
|  2 | 0002-kicad_cli-defer-LoadGlobalTables                | init   | 20-100 ms        |
|  4 | 0004-kicad_cli-lazy-argparse-subtree                 | init   | 5-20 ms          |
|  5 | 0005-pgm_base-skip-curl-sentry-in-headless           | init   | 10-50 ms         |
|  6 | 0006-singleton-lazy-thread-pool                      | init   | 8 threads spared |

Combined estimate on 254 ms `--version`: ≈ **65-180 ms** saved.

## B. Per-invocation board init

Dominant cost on every `pcb export …` past the fixed init above.

| # | patch                                                 | axis        | estimate            |
|--:|-------------------------------------------------------|-------------|---------------------|
|  3 | 0003-board_loader-skip-connectivity-drc-init-for-export | init      | **~1500 ms**        |
| 14 | 0014-board_loader-drawing-sheet-cache                 | init/daemon | 5-20 ms / board     |
| 16 | 0016-cli-full-init-env-escape                         | correctness | 0 (safety)          |

Combined estimate on 3.1 s big-board svg export: ≈ **1.5-2 s** saved.

## C. Plot-time throughput

Per-plot output cost: file writes, stream compression, XML escape.

| # | patch                                                            | axis        | estimate                |
|--:|------------------------------------------------------------------|-------------|-------------------------|
|  1 | 0001-pcb_plotter-skip-wxSafeYield-in-CLI                         | plot        | ~1-5 ms / layer         |
| 22 | 0022-plotter-larger-stdio-buffer                                  | plot        | 5-30 ms / plot          |
| 23 | 0023-svg-xmlesc-fast-path                                         | svg         | 5-15 ms / svg           |
| 24 | 0024-extend-stdio-buffer-to-gerber-workfile-and-drill             | gerber/drill| 5-15 ms                 |
| 25 | 0025-pdf-zlib-level-6                                             | pdf         | **~2-3× faster PDF**    |
| 26 | 0026-pdf-zlib-level-6-image-and-3d-streams                        | pdf         | further pdf speedup     |

Combined on a big PDF plot: **2-3× on the compression phase** plus
~50 ms of misc.

## D. Parser / lexer

Board load (~2 s on a 5 MB board) is dominated by tokenisation.

| # | patch                                                            | axis    | estimate           |
|--:|------------------------------------------------------------------|---------|--------------------|
| 27 | 0027-kiplatform-fadvise-not-fatal                                | correct | fixes false failure|
| 28 | 0028-line-reader-fgets-fast-path                                 | parse   | 50-100 ms / board  |
| 29 | 0029-dsnlexer-opt-in-separator-tracking                          | parse   | 10-30 ms / board   |
| 30 | 0030-sexpr-parser-inline-whitespace-test                         | parse   | small, per-byte    |

Combined on parsing the 5.6 MB video board: ≈ **~80-150 ms**.

## E. `kicad-cli daemon` — MVP (patches 0007-0013)

Long-lived server so CI matrix builds pay per-invocation cost once,
not per invocation.

| # | patch                                                     | axis   | rôle                                 |
|--:|-----------------------------------------------------------|--------|--------------------------------------|
|  7 | 0007-cli-daemon-scaffold                                  | daemon | subcommand tree scaffolding          |
|  8 | 0008-cli-daemon-socket-server-body                        | daemon | bind/listen/accept + signal handling |
|  9 | 0009-cli-daemon-wire-protocol                             | daemon | length-prefixed frame parser/writer  |
| 10 | 0010-cli-daemon-dispatch-integration                      | daemon | route request through argparse+cmds  |
| 11 | 0011-cli-daemon-stop-status-pidfile                       | daemon | pidfile-based lifecycle              |
| 12 | 0012-pcbnew-board-cache-lru                               | daemon | 4-entry (path,mtime) BOARD cache     |
| 13 | 0013-cli-via-daemon-client                                | daemon | `--via-daemon` / `KICAD_CLI_DAEMON`  |

Full-cycle CI (15 exports on one board): **~45 s → ~2 s** cold, then
50 ms per follow-up call.

## F. Daemon hardening (patches 0015-0021)

Follow-ups to E, all found by branch-sweep passes.

| # | patch                                                | axis        | rôle                                                |
|--:|------------------------------------------------------|-------------|-----------------------------------------------------|
| 15 | 0015-daemon-per-dispatch-reset                       | robustness  | wxLog + locale scope-guard per dispatch             |
| 17 | 0017-loadglobaltables-once-per-process               | daemon-perf | avoid re-parsing sym/fp tables per request          |
| 18 | 0018-daemon-error-on-chdir-fail                      | usability   | client sees a real error, not "board not found"    |
| 19 | 0019-daemon-cap-request-alloc                        | security    | cumulative-frame cap, prevents 16 GB alloc          |
| 20 | 0020-daemon-pid-reuse-defence                        | security    | /proc/comm check before SIGTERM to a foreign pid    |
| 21 | 0021-daemon-check-pidfile-before-bind                | robustness  | don't unlink running daemon's socket on double-start|

## Cross-references

- **Design docs:** `analysis/00-hot-paths.md`, `analysis/01-board-load-init.md`,
  `analysis/02-daemon-mode-design.md`, `analysis/03-headless-pcbnew-kiface.md`.
- **User docs:** `docs/cli-daemon.md`.
- **Benchmarks:** `benchmarks/00-baseline-kicad-9.0.8-aarch64.md`,
  `benchmarks/01-patch-syntax-check.md`, `benchmarks/02-validation-plan.md`,
  `benchmarks/03-build-blocker-notes.md`.
- **Reference client:** `scratch/kicad_cli_daemon_client.py`,
  `scratch/wire_protocol_test_server.c` (validates the wire protocol
  without needing a KiCad build).

## Combined expected win (very rough)

|                                        | stock 9.0.8 | with A-D patches | with A-F (daemon)    |
|----------------------------------------|-------------|------------------|----------------------|
| `--version`                            | 254 ms      | ~120 ms          | N/A (client short-circuits)|
| `pcb export svg` — 156 KB board        | 940 ms      | ~450 ms          | first ~450, 2nd+ ~50 |
| `pcb export svg` — 5.6 MB board        | 3121 ms     | ~1000 ms         | first ~1000, 2nd+ ~50|
| `pcb export pdf` — 5.6 MB board        | 3383 ms     | ~900 ms          | first ~900, 2nd+ ~50 |
| CI: 15 exports on 5.6 MB board         | ~45 s       | ~15 s            | ~1.7 s               |
