# Baseline — kicad-cli 9.0.8, aarch64, Debian bookworm-backports

`kicad-cli 9.0.8+dfsg-1~bpo12+1`, extracted from the Debian backports .deb into
`~/local/kicad-root` (no system install; wrapper at `~/local/bin/kicad-cli`
sets `LD_LIBRARY_PATH` and `XDG_DATA_DIRS`). All measurements are on this box:

- ARM64 (Rockchip RK3588)
- 8 cores, 32 GB RAM
- Linux 6.1.43-15-rk2312

Tool: `hyperfine 1.20.0`, 3 runs after 1 warmup. `strace -c` for syscall
counts, `/usr/bin/time -v` for RSS.

## Wall-clock summary (representative)

| operation                                                | wall (mean)   | notes |
|----------------------------------------------------------|---------------|-------|
| `kicad-cli --version`                                    | **254 ms**    | prints one string. |
| `kicad-cli --help`                                       | 266 ms        | prints help. |
| `kicad-cli pcb --help`                                   | 262 ms        | prints subcommand help. |
| `kicad-cli pcb export svg` — ecc83 (156 KB board), 1 layer | **936 ms**  | tiny board. |
| `kicad-cli pcb export svg` — video (5.6 MB board), 1 layer | 3121 ms    | 33× bigger board. |
| `kicad-cli pcb export svg` — video, 6 layers               | 3277 ms    | +6× layers = +156 ms. |
| `kicad-cli pcb export gerbers` — video, full stack         | 3610 ms    | |
| `kicad-cli pcb export drill` — video                       | 3006 ms    | pure text output; still 3 s. |
| `kicad-cli pcb export pdf` — video, 1 layer                | 3383 ms    | |

## Key takeaways

### 1. `--version` costs 254 ms and does 5,873 syscalls

`strace -c kicad-cli --version`:

```
% time     seconds  usecs/call     calls    errors syscall
------ ----------- ----------- --------- --------- ----------------
 31.67    0.019692           5      3322      2075 newfstatat   ← 63% miss rate
 22.89    0.014232          29       485           mmap         ← dynamic linker
  9.86    0.006128          19       316       143 openat       ← 45% miss rate
  7.64    0.004748          17       270           mprotect
  7.49    0.004656          17       265           munmap
  ...
 total   0.054241                  5873      2237
```

- Only 54 ms is in-kernel; the other 200 ms is user-CPU-side.
- Peak RSS 57 MB just to print a version string.
- 4,631 minor page faults (fresh anon-mapping churn).

### 2. Multi-layer SVG is almost free once startup is paid

`svg-6layers` beats `svg-1layer` by only **156 ms** even though it produces 6
files. So per-layer cost on this board is ~26 ms. **Fixed setup is ~3 s.**
Consequence: parallelizing the per-layer plot loop (proposed H4) can save at
most **~130 ms out of 3.3 s** on a 6-layer plot. Real wins are on the fixed
side.

### 3. Board-size scan (single-layer SVG, same fixed init)

| board                    | size    | wall     | delta vs ecc83 |
|--------------------------|--------:|---------:|---------------:|
| `ecc83-pp.kicad_pcb`     | 156 KB  | 936 ms   | —              |
| `video.kicad_pcb`        | 5.6 MB  | 3121 ms  | +2185 ms       |

Fixed init ≈ **700-900 ms**, remainder scales sub-linearly with board size
(the video board is 36× bigger, adds 3.3× wall time). So load + parse +
build-index of a 5.6 MB board eats ~2.2 s.

### 4. Even `drill` — pure text output — takes 3 s

The drill exporter doesn't render anything. It reads the board, walks the
holes, writes `.drl` text files. Wall 3.0 s on the video board. Same fixed
setup as everything else. Says the fixed cost is *not* in the plotter.

### 5. `--version` vs small SVG: 680 ms delta = pcbnew.kiface load + BOARD parse + init

`/usr/bin/time -v`:

|                       | `--version` | `svg-1layer` (156 KB board) |
|-----------------------|------------:|----------------------------:|
| wall                  | 260 ms      | 940 ms                      |
| user CPU              | 200 ms      | 800 ms                      |
| sys CPU               | 40 ms       | 130 ms                      |
| max RSS               | 57 MB       | **219 MB**                  |
| minor page faults     | 4,631       | 33,961                      |

Loading pcbnew.kiface + parsing a tiny board + init adds:

- **+600 ms user CPU**
- **+162 MB RSS**
- **+29,330 page faults**

That is the single biggest chunk of "fixed cost" and it applies to every
`pcb` subcommand. The kiface is a full shared library containing the entire
PCB editor's plotting/DRC/geometry engine.

### 6. 73 % of syscall time in `futex` during SVG export

For `svg-1layer` on video board (17,932 syscalls total):

```
 73.83    0.199135          18     10968        58 futex   ← 199 ms in futex alone
  6.48    0.017470          25       674           mmap
  5.78    0.015580           4      3535      2160 newfstatat
```

10,968 futex ops = intense thread synchronization. Given the KiCad thread
pool is spun up at init (visible at `kicad_cli.cpp:661` on shutdown), and the
plot loop is single-threaded per PCB_PLOTTER::Plot, this is almost certainly
libc's malloc arena locking + wxWidgets internal mutexes, not real
parallelism.

## What this reprioritizes vs `analysis/00-hot-paths.md`

Reading the source suggested H1 (LoadGlobalTables) and H2 (argparse tree) as
top wins. The bench says those are minor next to:

- **H5** (persistent kicad-cli daemon) → biggest lever. 3 s of every
  invocation is fixed. A daemon that keeps pcbnew.kiface loaded and BOARDs
  cached brings all of that to zero after the first call.
- **A new item H8** (below): the pcbnew.kiface shared library is huge
  because it drags in the whole PCB editor. A kicad-cli-only kiface with the
  DRC / plot / export subset, no GUI code, no drawing tools, no dialog
  code — probably 30-50 MB smaller and 200-400 ms faster to load and init.
- **H4** (parallel layer plot) is a 130 ms win on a 3.3 s job. Do it, but
  don't lead with it.

## Files

- `baseline.json` — full hyperfine JSON output for the multi-op run.
- `baseline.md` — hyperfine markdown table.
- `sizes.json` — board-size scan.
- `version.strace`, `svg.strace` — openat traces.

## Reproducing

```
export PATH=~/local/bin:$PATH
mkdir -p /tmp/bench-out
hyperfine --warmup 1 --runs 3 \
  'kicad-cli --version' \
  'kicad-cli pcb export svg --mode-multi -l F.Cu -o /tmp/bench-out/svg1 /path/to/board.kicad_pcb'
```
