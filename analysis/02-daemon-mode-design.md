# H5 — `kicad-cli --daemon` design

The single biggest lever for CI-style workloads that call `kicad-cli`
repeatedly. Measurement (`benchmarks/00-baseline-kicad-9.0.8-aarch64.md`)
established:

- Every `kicad-cli pcb export …` invocation pays **~700-900 ms** of fixed
  init (wx / kiface load / settings / thread pool / …) before touching
  anything board-specific.
- On top of that, **~2.2 s** to parse and initialize the 5.6 MB video
  board (H3 patches remove most of this, but the file I/O + parse remains).

For a CI job that renders one board to a dozen output formats (SVG,
gerbers, drill, position, IPC-2581, IPC-D-356, PDF, stackup, stats, …),
the *same* board is re-parsed and *all* the fixed init is re-run once per
kicad-cli invocation. That's ~15 × 3 s = 45 s of wasted, cache-cold work.

A daemon collapses that to one payment.

## Model

```
$ kicad-cli daemon start [--socket ~/.cache/kicad/cli.sock]
  # long-lived process, listens on the Unix socket
  # exits on SIGTERM, SIGINT, or explicit `kicad-cli daemon stop`

$ kicad-cli --via-daemon pcb export svg …
  # tiny client: connects to socket, marshals argv + cwd + env + stdin,
  # server dispatches through the existing COMMAND stack, streams
  # stdout/stderr back, sends exit code, disconnects.
```

`--via-daemon` (or an env var `KICAD_CLI_DAEMON=1` for wholesale CI
adoption) auto-starts the daemon if the socket is absent, so CI scripts
don't need a separate step.

## Wire protocol

Newline-delimited framing over Unix stream socket. Small dependency
surface — no protobuf, no nng.

Frame types (first byte determines):

| byte | frame            | payload                                                |
|-----:|------------------|--------------------------------------------------------|
|  `>` | request-argv     | JSON `{argv:[…], cwd:"…", env:{…}, stdin_bytes:N}`     |
|  `.` | stdin-chunk      | raw bytes (up to N)                                    |
|  `1` | stdout-chunk     | raw bytes                                              |
|  `2` | stderr-chunk     | raw bytes                                              |
|  `x` | exit             | JSON `{code: 0}`                                       |
|  `?` | server-ping      | (empty; used for liveness checks)                      |

One frame per line: `<type-byte><length-hex><LF><payload><LF>`. Length is
in bytes, hex, no `0x` prefix — same shape as HTTP chunked.

## Server dispatch

The server reuses the existing `commandStack` from `kicad_cli.cpp` as-is:
- Parses the received argv the same way `OnPgmRun` does today.
- Looks up the `CLI::COMMAND*` for the leaf.
- Calls `cliCmd->Perform( Kiway )`.
- Everything the command writes to stdout/stderr is captured (redirected
  file descriptors, or a `REPORTER` subclass that forwards each report as
  a stdout/stderr frame).
- Exit code returned.

`Kiway` is the same singleton the current CLI already uses; no changes
there.

## Board / project cache

Behind the scenes, `PCBNEW_JOBS_HANDLER::m_cliBoard` already caches one
board per process — designed exactly for the daemon case. In daemon
mode:

- **Key** = absolute normalized path + `st_mtim`.
- **Value** = the `std::unique_ptr<BOARD>` currently held.
- On each `getBoard(path)` call, stat the file; on hit, reuse; on miss,
  reload.

Optionally, cache the last N boards (LRU) rather than one — good for the
"render four boards in a loop" workflow.

Same for `getSchematic` (eeschema kiface) and the project settings
manager.

## Files needed

| file                                  | change                                                                            |
|---------------------------------------|-----------------------------------------------------------------------------------|
| `kicad/cli/command_daemon.h`          | new — `class DAEMON_START_COMMAND`, `class DAEMON_STOP_COMMAND`, `class DAEMON_STATUS_COMMAND` |
| `kicad/cli/command_daemon.cpp`        | new — server loop, socket accept, frame parser, dispatcher                        |
| `kicad/cli/command_daemon_client.cpp` | new — client-side helper that packages argv into a request-argv frame and streams |
| `kicad/kicad_cli.cpp`                 | register the three new subcommands; add `--via-daemon` short-circuit at the top of `OnPgmRun` |
| `pcbnew/pcbnew_jobs_handler.cpp`      | swap `m_cliBoard` scalar for a small path+mtime-keyed cache                       |
| `common/settings/settings_manager.cpp`| ensure `SettingsManager::LoadProject` is idempotent w.r.t. re-open of same path   |

Estimated LOC: ~500 for the daemon; ~50 for cache widening.

## Safety concerns

1. **Concurrent requests** — the server accepts one client at a time in
   the MVP. `KIWAY::ProcessJob` is not proved re-entrant. Serialize.
   Later: parallel dispatch behind a per-command mutex, or fork worker
   subprocesses.
2. **State leakage** — if command A mutates a global, command B sees it.
   `LOCALE_IO` scope guard, `wxLog` sinks, and `Pgm().SetLocale()` are all
   suspect. Add per-request `RESET` scope guard that snapshots and
   restores.
3. **Memory** — long-lived process accumulates cached boards. LRU cap
   (default 8) + periodic scan.
4. **Signals** — daemon must survive `SIGPIPE` (client aborted) and
   handle `SIGTERM` / `SIGINT` cleanly (drain in-flight requests,
   `Kiway.OnKiwayEnd()`, exit).
5. **Auth** — Unix socket is `chmod 0600 $USER`; permission model = POSIX
   file perms. No cross-user access. Explicit refusal if socket path is
   world-writable.
6. **Socket lifecycle** — pidfile beside the socket. On start, if pidfile
   points to a live process, error out. On stop, unlink both.

## Expected impact

Cold first invocation: unchanged (paying full init + parse).
Second invocation onwards, same board: ~50-150 ms (client round-trip +
dispatch), vs ~3 s stock. **20-60× faster.**

For a CI job doing 15 exports on one board:
- Stock: 15 × 3.0 s = 45 s.
- Patched (with H3 applied): 15 × ~1.5 s = 22 s.
- Daemon: first call 3.0 s + 14 × 0.1 s = **4.4 s**. **10× faster than H3
  alone.**

## Rollout

1. Land the daemon command as opt-in only (`--via-daemon` flag / env var
   must be set). No default behavior change.
2. Document under `docs/cli-daemon.md`.
3. After ~1 stable release, consider auto-daemon: `kicad-cli` detects an
   existing socket and switches transparently.

## Non-goals

- Not a general-purpose IPC. The existing `kicad-cli api-server` is that.
  This is specifically a fast-path for CLI-shaped work.
- Not a network daemon — Unix socket only.
- Not a multi-user daemon — per-`$USER` socket.

## Status — MVP landed as patches 0007-0013

| patch  | what landed                                                                                     |
|--------|-------------------------------------------------------------------------------------------------|
| 0007   | scaffold `kicad-cli daemon {start,stop,status}` subcommand tree + CMake entry                   |
| 0008   | `daemon start` real socket bind/listen/accept loop, SIGINT/SIGTERM clean shutdown               |
| 0009   | request/response wire protocol (KCLI/STAT magic + argc/args/cwd/exit/out/err)                   |
| 0010   | dispatch integration — extract `OnPgmRun` body into `CLI::RunKicadCliDispatch()`, daemon calls it with per-client cwd chdir + stdio fd redirect |
| 0011   | pidfile-based `daemon stop` (SIGTERM + poll) and `daemon status` (RUNNING/STALE/NOT RUNNING with socket probe) |
| 0012   | widen `m_cliBoard` scalar cache to a 4-slot (path,mtime,forExport)-keyed LRU deque              |
| 0013   | client-side `--via-daemon` / `KICAD_CLI_DAEMON=1` auto-connect in `PGM_KICAD::OnPgmRun`         |

Wire protocol was validated end-to-end with a standalone C server
(`scratch/wire_protocol_test_server.c`) + Python client
(`scratch/kicad_cli_daemon_client.py`) before the real dispatch landed
— argv[0..6] and cwd round-trip cleanly, response deserialization
returns the expected exit code and captured stdout.

## Still open

- Runtime end-to-end validation against a real built kicad-cli — waiting
  on a working full-tree build (see `benchmarks/00-baseline-…` for the
  dep-chase blocker).
- `LOCALE_IO` and `wxLog` sinks are process-global; second dispatch of
  a command that stashed state may leak into the next request. Needs a
  scope-guard sweep in `RunKicadCliDispatch()`.
- `SETTINGS_MANAGER::LoadProject()` idempotency — currently the CLI
  path loads a project per request; the daemon should reuse an
  already-loaded PROJECT* when the same path comes back.
- Concurrent requests: MVP is single-in-flight. Follow-up: per-command
  mutex or worker-subprocess fanout.
- `daemon start --detach` so users can shell start without needing to
  background it themselves.
