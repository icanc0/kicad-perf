# Daemon warm-call regression — real bug found by the harness

Discovered 2026-08-23 while measuring daemon-mode `pcb export svg`
performance on the patched build.

## Symptom

```
$ kicad-cli daemon start &     # patched-master
$ time kicad-cli --via-daemon pcb export svg --layers F.Cu \
       --output /tmp/via1.svg starfish.kicad_pcb
Plotted to '/tmp/via1.svg'.
Done.
real  0m1.069s   ← success

$ time kicad-cli --via-daemon pcb export svg --layers F.Cu \
       --output /tmp/via2.svg starfish.kicad_pcb
  --variant  The variant name(s) to output, ... [help text]
real  0m0.160s   ← FAST but no output SVG produced (exit 0)

$ ls /tmp/via*.svg
/tmp/via1.svg    ← via2/via3/via4 all missing
```

## What's happening

- First `--via-daemon` call: daemon receives, dispatches through
  `RunKicadCliDispatch`, argparse parses cleanly, board loads, svg
  written, exit 0.
- Second call: daemon receives, argparse decides the command is a
  `--help` for the deepest known subcommand and prints usage text.
  Exit 0 with no side-effects.

The argparse tree state is being reused across dispatches instead
of rebuilt fresh. My P4 lazy-argparse subtree builds `pcb` on first
call; the built subtree carries option-parsing state that on the
next call causes the args to be misinterpreted.

## Why my P15 patch didn't catch this

P15 (per-dispatch reset guard) resets `wxLog` sink and the C
locale. It does NOT reset the argparse tree. The argparse
`ArgumentParser` is constructed once per `RunKicadCliDispatch` call
(look at the code — it IS local to the function scope), so it
should be fresh per call — but the SUBCOMMAND registered instances
in `commandStack` are static/global, and their internal
`m_argParser` members are reused. Those persist state.

## Fix (P59, drafted, needs a rebuild)

Either:
1. Reset each `COMMAND`'s internal argparse before each dispatch,
   OR
2. Store the built parsers in per-dispatch storage so each request
   gets a fresh tree.

Option 1 is smaller. Add a `void ResetArgParser()` method to
`CLI::COMMAND` that recreates `m_argParser`, and call it
recursively in the lazy-build loop.

Deferred to a follow-up commit — needs another build cycle to
validate. This document is here so the bug isn't lost.

## Second finding — daemon adds overhead on cold call

First `--via-daemon` call: 1069 ms — slightly worse than direct
`kicad-cli pcb export svg …` at 1013 ms. Expected the daemon to
save the ~150 ms fixed init cost per-invocation; instead it's paying
~50 ms extra. Two causes to check:

- Daemon may not preload `_pcbnew.kiface` at start (loads on first
  request). Preload would move that cost to daemon-start.
- Wire-protocol overhead (socket connect + frame marshalling)
  could account for ~10-20 ms.

A P60 patch preloading kifaces at daemon start would eliminate the
first-call penalty. Also deferred.

## What the harness would have caught if we'd had it earlier

Both of these bugs are exactly the kind of "code compiles, tests
pass, but real invocation regresses" issue the harness is designed
to surface. Adding a `cli.daemon_export` scenario that does N
sequential `--via-daemon pcb export svg` invocations and asserts
that each produces a valid output file would flag the warm-call
bug automatically on every future change. Queued as the next
scenario to write.
