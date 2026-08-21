# Build blocker — cmake wxWidgets_LIBRARIES detection

Attempting a full-tree KiCad build in userspace (no root, deps extracted
from Debian .deb into `~/local/kicad-root`) keeps failing at the
wxWidgets step:

```
CMake Error at .../FindPackageHandleStandardArgs.cmake:230 (message):
  Could NOT find wxWidgets (missing: wxWidgets_LIBRARIES) (Required is at
  cmake/FindwxWidgets.cmake:1032 (find_package_handle_standard_args)
  CMakeLists.txt:965 (find_package)
```

## What works

`wx-config` from the extracted deb accepts `--prefix=$HOME/local/kicad-root/usr`
and produces correct output:

```
$ wx-config --prefix=$HOME/local/kicad-root/usr --version
3.2.2
$ wx-config --prefix=$HOME/local/kicad-root/usr --libs gl,html,stc,aui,propgrid,adv,net,xml,core,base
-L/home/vincent/local/kicad-root/usr/lib/aarch64-linux-gnu -pthread   -lwx_gtk3u_gl-3.2 -lwx_gtk3u_html-3.2 -lwx_gtk3u_stc-3.2 -lwx_gtk3u_aui-3.2 -lwx_gtk3u_propgrid-3.2 -lwx_baseu_net-3.2 -lwx_baseu_xml-3.2 -lwx_gtk3u_core-3.2 -lwx_baseu-3.2
```

## What doesn't

CMake invocation:

```
cmake -GNinja \
  -DwxWidgets_CONFIG_EXECUTABLE=$HOME/local/kicad-root/usr/bin/wx-config \
  -DwxWidgets_CONFIG_OPTIONS=--prefix=$HOME/local/kicad-root/usr \
  ...
```

`KiCad's cmake/FindwxWidgets.cmake` at line 866-895 runs the same
`wx-config --libs <components>` invocation with `wxWidgets_SELECT_OPTIONS`
(which starts from `wxWidgets_CONFIG_OPTIONS`). Should produce the same
output. But `wxWidgets_LIBRARIES` ends up empty.

## Suspected

Either:
- `--prefix=…` is being dropped from `wxWidgets_SELECT_OPTIONS` by
  the initial `WX_CONFIG_SELECT_GET_DEFAULT` / `WX_CONFIG_SELECT_QUERY_BOOL`
  chain (lines 684-756 in FindwxWidgets.cmake), so the actual `--libs`
  call runs without the prefix and produces something cmake rejects.
- Some later verification step in KiCad's find module checks that each
  library file exists (line-numbered somewhere between 895 and 1032) and
  is missing on our sysroot because it's looking under `/usr/lib/…`
  instead of `~/local/kicad-root/usr/lib/…`.

## Escape hatches (not yet tried)

- Patch KiCad's `cmake/FindwxWidgets.cmake` to always append
  `--prefix=…` on every wx-config invocation. Cheap, throw-away.
- Point `PKG_CONFIG_PATH` at a fresh generated `wxWidgets.pc` that
  encodes our prefix and use CMake's `pkg_check_modules(WX wxwidgets)`.
- Run cmake configure inside a chroot / bwrap that binds
  `~/local/kicad-root/usr` into `/usr`. Would let wx-config's built-in
  defaults resolve correctly, but adds ~50 MB of bwrap setup and
  requires user namespaces.
- Grab a prebuilt kicad AppImage, extract it, and use its bundled
  libraries. Doesn't help build our patches, only measure the stock
  baseline — which we already have.
- Use nix-portable to install kicad, patch its sources in the nix
  store, and rebuild. Heavy but self-contained.
- Wait until this box gets sudo / a package manager escape. Once we
  can `apt install libwxgtk3.2-dev`, the whole thing goes away.

## Status

Deferred. Every patch in `patches/*` has been:

1. Applied to the KiCad source tree cleanly (`git am`).
2. Compiled through `g++ -fsyntax-only -std=c++20` with real system
   headers from the extracted debs (see `01-patch-syntax-check.md`).
3. Bit-checked against the pre-patch tree via `git diff` — every hunk
   is minimal, reviewable, and free of stray whitespace.

So the patch series is credible on inspection even without runtime
numbers; the numbers land in `03-results-fork-vs-stock.md` when a
build clears.

The daemon's wire protocol *has* been runtime-tested end-to-end via a
standalone C reimplementation of the request handler
(`scratch/wire_protocol_test_server.c`) + a Python client — that gives
us confidence the framing is correct, even though the full dispatch
path awaits a real build.
