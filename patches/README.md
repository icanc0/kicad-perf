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
 (theoretical, not yet measured)

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
