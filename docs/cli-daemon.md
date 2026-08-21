# `kicad-cli daemon` — quick start

A long-lived `kicad-cli` server that collapses the ~700-3000 ms
startup cost of every `kicad-cli` invocation to a one-time payment.
On CI-style workflows that run many exports on the same board(s), the
daemon usually turns a 30-60 s job into a 2-5 s job.

**Status:** MVP landed as patches 0007-0015 in this repo. Not yet
merged upstream. Needs a build from this fork.

## Install (after applying the patches)

```
cd /path/to/kicad
git checkout -b perf-batch
git am /path/to/kicad-perf/patches/*.patch
mkdir build && cd build
cmake -GNinja ..
ninja kicad-cli
```

## Start it

Foreground (blocks the terminal, useful for logs):

```
kicad-cli daemon start
# kicad-cli daemon listening on /run/user/1000/kicad-cli.sock (pid 12345)
```

Background it yourself (there is no `--detach` yet):

```
nohup kicad-cli daemon start >kicad-cli-daemon.log 2>&1 &
disown
```

Or under a service manager (systemd `--user` unit example):

```
[Unit]
Description=kicad-cli daemon

[Service]
ExecStart=/usr/local/bin/kicad-cli daemon start
Restart=on-failure

[Install]
WantedBy=default.target
```

Check it's up:

```
$ kicad-cli daemon status
kicad-cli daemon: RUNNING (pid 12345, socket /run/user/1000/kicad-cli.sock)
```

## Route your kicad-cli calls to it

Either add `--via-daemon` to each invocation, **or** set the env var
once:

```
export KICAD_CLI_DAEMON=1
```

Then every `kicad-cli` call transparently uses the daemon when it is
reachable, and falls back to in-process dispatch when it is not — no
CI script changes needed.

```
$ time kicad-cli pcb export svg -l F.Cu -o out board.kicad_pcb
real    0m3.121s   # stock: cold every call
$ export KICAD_CLI_DAEMON=1
$ time kicad-cli pcb export svg -l F.Cu -o out board.kicad_pcb
real    0m3.100s   # first daemon call: warm-up
$ time kicad-cli pcb export svg -l F.Cu -o out board.kicad_pcb
real    0m0.048s   # ← 65× faster
```

## Socket location

Default: `$XDG_RUNTIME_DIR/kicad-cli.sock`, `chmod 0600` (this-user-only).
Fallback: `/tmp/kicad-cli-$UID.sock`.

Override with `--socket PATH` on any daemon subcommand, and
`--daemon-socket=PATH` on client-side calls:

```
kicad-cli daemon start --socket /var/run/kicad/cli.sock
kicad-cli --via-daemon --daemon-socket=/var/run/kicad/cli.sock pcb export svg …
```

## Stop it

```
$ kicad-cli daemon stop
daemon stopped (pid 12345).
```

Sends `SIGTERM`, polls up to 2 s for the pidfile at
`$SOCKET.pid` to disappear.

`SIGINT` (`Ctrl-C`) in the foreground terminal does the same.

## What actually runs faster (and what doesn't)

Big wins:
- **Repeated exports on the same board.** The parsed BOARD (up to 4 in
  LRU cache) plus the pcbnew kiface stays hot in memory. Second-and-later
  calls skip: kiface load + wxWidgets init + BOARD parse + connectivity
  build + DRC engine init.
- **CI matrix builds.** 15 gerber/drill/pos/pdf calls on one board:
  stock ~45 s, daemon ~2 s after the first call.

No change:
- `kicad-cli --version` / `--help`: the client short-circuits these
  before reaching the daemon.
- First call: pays the full init cost (someone has to). Subsequent
  calls are cheap.

Small wins:
- `pcb drc` after a `pcb export` for the same board: DRC engine may
  already be initialized in cache; save a chunk.

## Trust model

- Socket is `0600` and lives per-`$USER`; no other local user can
  reach it. Nothing over a network.
- A single daemon per `(user, socket path)`. `daemon start` refuses
  to double-bind if another live daemon is at the same path.
- Only one dispatch runs at a time (single-in-flight in the MVP).
  Requests queue on the socket.

## Known limits (as of MVP)

- Single-in-flight; parallel requests queue.
- `daemon start` runs in the foreground; no `--detach`.
- Auto-restart on process crash needs an external supervisor
  (systemd, s6, `run` script, ...).
- BOARD cache is invalidated by mtime; users editing the file while
  the daemon serves a query see the *new* file (this is what you
  want) but there's a race — if you edit *and* run in the same
  millisecond, the cache might hand back the old parse. In practice
  never seen.

## Files it writes

- `$SOCKET` — the Unix socket itself.
- `$SOCKET.pid` — the daemon's PID. Removed on clean exit.

## Troubleshooting

**"connect: no such file or directory"** — daemon not running. Start
it, or `unset KICAD_CLI_DAEMON` to force in-process dispatch.

**"daemon start: another daemon (pid X) is already running"** —
`daemon status` first; if it says STALE, remove `$SOCKET.pid` and
retry.

**"daemon: RUNNING but socket not accepting"** — the daemon process
is alive but has fallen off the accept loop. Send `SIGTERM` (via
`daemon stop`) and start a fresh one. Filing an upstream bug is
appreciated.

**Output doesn't appear** — check that the client got response frames
via `strace -e trace=recvfrom kicad-cli --via-daemon …`. If frames
arrive but content is empty, the daemon captured no stdio; that's a
bug in either the command or the daemon's `StdioCapture`.

## Reference protocol

For scripting a non-kicad client (build automation, IDE integration,
CI orchestration):

- See [`scratch/kicad_cli_daemon_client.py`](../scratch/kicad_cli_daemon_client.py)
  — a 100-line Python reference client.
- Wire protocol spec is at the top of
  [`kicad/cli/command_daemon.cpp`](../patches/0009-cli-daemon-wire-protocol.patch)
  in this repo's patch series (search for "Wire protocol").
