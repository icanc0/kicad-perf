# Harness design

The harness is three parts glued by JSON:

1. **Instrumentation surface** — thin shims/side-cars that expose an
   axis (wall / CPU / RAM / GPU / UI frame) as a stream of samples
   written to a file the runner owns.
2. **Scenario drivers** — one Python file per action. Each driver
   describes the action, launches the target binary under the
   requested instrumentation, and returns per-axis summary numbers.
3. **Runner + report** — walks the {binary × scenario × run-index}
   product, invokes each scenario driver, collates JSON, produces the
   comparison table plus the raw-sample archive.

## Design principles

- **Every metric is a signal from a real run.** No estimates in the
  report — if we couldn't measure it, the cell is blank, not
  interpolated.
- **The runner never assumes anything is installed.** Every
  side-car probes for its dependency and downgrades gracefully.
  A cell is missing, not fabricated.
- **Scenarios are deterministic.** Same fixture, same argv, same
  environment, same starting mouse position. Random-order driving
  is a separate mode used only for fuzz-scale UI stress.
- **Warm-up is explicit.** Every scenario does ≥ 2 warmup runs,
  then ≥ 5 measured runs. Numbers reported are median + IQR, not
  mean (skew resistance).
- **Isolation from CPU freq drift.** Runner prints
  `/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor` at
  start and warns if not `performance`. Bench numbers labelled
  with governor + kernel + wall clock so future comparisons can
  correct.

## Instrumentation surface

### rss_sampler (C, 300 lines)

Fork/exec target under a controlling process that:
- Opens `/proc/<pid>/statm` and `/proc/<pid>/status` on the child.
- Every 20 ms reads {`VmRSS`, `RssAnon`, `RssShmem`, `RssFile`,
  `VmPeak`, `VmSwap`} and appends `t_ms,vm_rss_kb,rss_anon_kb,…` to
  a CSV whose path is passed as argv.
- When the child exits, appends a `SUMMARY,exit=<n>,rusage_max_kb=<>`
  row using `wait4`'s rusage.

Why not just `getrusage`: peak alone loses the shape. Curves let us
see whether the memory rises steadily (leak/cache growth) or spikes
during a specific operation.

### gl_shim (C, ~200 lines, `LD_PRELOAD`)

Overrides `glDrawArrays`, `glDrawElements`, `glDrawElementsBaseVertex`,
`glDispatchCompute`, `glBufferData`, `glBufferSubData`. Each call
resolves the real symbol via `dlsym(RTLD_NEXT, …)`, increments a
per-call counter, and forwards. On process exit (`__attribute__((destructor))`)
writes `KI_GL_SHIM_OUT` (env-var path) a JSON blob of
`{"draws":…,"vertices":…,"bytes_uploaded":…,"frames":…}`.
Frames counted by hooking `glXSwapBuffers`/`eglSwapBuffers`.

### perf_stat_wrapper.sh

If `perf` is on the PATH and `perf_event_paranoid<=2`, wraps the
command in `perf stat -x, -o <csv> -e cycles,instructions,cache-references,cache-misses,branch-misses,task-clock`.
Otherwise prints `perf unavailable` on stderr and exits transparently.

### hyperfine_wrap.sh

Runs `hyperfine --warmup 3 --min-runs 10 --export-json <out>` around
each command; emits the raw JSON for the report renderer.

### KI_PERF_TRACE

An optional in-process scope-timer already envisioned for the code
tree (patch series pending). Each function of interest opens a scope
that prints `{name, t_start_us, t_end_us, thread}`. When
`KI_PERF_TRACE=1` is set and `KI_PERF_TRACE_OUT` points at a file, we
get a flat Chrome-tracing-compatible timeline. This is the most
faithful CPU-source-of-truth attribution and lands as a dedicated
patch after the harness proves useful.

## Scenarios

Each Python file exports:

```python
def name() -> str: ...
def prepare(env: HarnessEnv) -> None: ...       # copy fixtures, warmup, …
def run(env: HarnessEnv) -> ScenarioResult: ...
```

`ScenarioResult` carries {wall_ms, peak_rss_kb, cycles, insns, ipc,
draws, vertices, bytes_uploaded, ui_fps_median, ui_fps_p99, notes}.
Missing axes are `None` (report renders as blank).

### UI drivers

xdotool via Xvfb (both userspace-extracted). Each driver:
1. Launches Xvfb :99 with fixed resolution 1920x1080.
2. `export DISPLAY=:99`.
3. Spawns the target binary with `LD_PRELOAD=./gl_shim.so
   KI_UI_FRAME_TRACE=1 KI_PERF_TRACE=1` under `rss_sampler`.
4. Uses `xdotool sleep-and-search` until the window title matches
   (KiCad sets the title reliably), then sends the scripted events.
5. Waits for a synthetic "done" signal — for kicad-cli that's exit;
   for pcbnew/eeschema that's either a title change, a file-write
   watch (fixture output file mtime), or a fixed post-action idle
   period with the rss_sampler curve stabilised.

Deterministic waits — no `sleep 5 "just to be sure"`.

### Comparison across binaries

Same scenario, three binaries:
- `~/local/bin/kicad-cli` (stock 9.0.8, extracted from Debian deb)
- `~/not-my-projects/kicad-stock/build-stock/kicad/kicad-cli` (stock master @32fcb08d)
- `~/not-my-projects/kicad/build-mini/kicad/kicad-cli` (patched master; this repo's series)

Runner iterates scenarios × binaries, records N samples, computes
median+IQR per axis, writes report.

## Report

Two artifacts per run:

- `reports/YYYY-MM-DD-hhmm/report.md` — the comparison table + a
  narrative summary + regression alarms.
- `reports/YYYY-MM-DD-hhmm/raw/` — all sample CSVs and JSONs from
  the collectors, addressable by scenario+binary+run-index so any
  cell can be inspected.

The renderer also writes `reports/latest.html` — a small static page
with sparkline SVGs for the RSS curves and per-scenario bar charts,
so a human doesn't have to open JSON.

## What we haven't decided yet

- **Continuous integration**: cron-triggered? On-push? Once the
  patched-master build stabilizes, running the harness on every
  merge into `main` catches perf regressions the same way tests
  catch correctness regressions. Deferred until we have baseline
  numbers.
- **GPU on headed hosts**: this box doesn't have any GPU tools;
  moving the harness to a Linux desktop with an actual GPU is a
  known follow-up.
- **Multi-thread contention**: no threads-oriented axis yet
  (thread wait time, futex contention). Adding once we can
  measure the current baseline.
