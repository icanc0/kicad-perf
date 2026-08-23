# heaptrack profile — `kicad-cli --version` on stock 9.0.8

Captured 2026-08-23 on aarch64 (Debian bookworm) with heaptrack 1.4.0
against the extracted `kicad_9.0.8+dfsg-1~bpo12+1_arm64.deb`. All
numbers reflect stock 9.0.8; the patched-master profile will land
under `06-heaptrack-patched-master-version.md` once that binary is
built.

## Top-line

| metric                          | value       |
|---------------------------------|------------:|
| total runtime                   | 3.71 s      |
| allocation calls                | 447,223     |
| allocation rate                 | 120,642 /s  |
| temporary allocations           | 6,888       |
| **peak heap** consumption       | **6.81 MB** |
| peak RSS (incl. heaptrack)      | 61.30 MB    |
| memory "leaked" at exit         | 695 KB      |

## Top peak-memory consumers (aggregated)

```
3.78 MB / 149,105 calls   libwx_baseu-3.2   (all-of-wxBase noise)
1.44 MB /   9,880 calls   wxMsgCatalog::CreateFromFile
                          ← wxFileTranslationsLoader::LoadCatalog
                          ← wxTranslations::AddCatalog
                          ← PGM_BASE::SetLanguage
                          ← PGM_BASE::InitPgm
1.05 MB /  10,124 calls   (same path, second AddCatalog)
```

## The finding

Roughly **1 MB of allocations for a command that prints "9.0.8\n".**
The whole cost sits inside `wxTranslations::AddCatalog("kicad")`:
loading the compiled `.mo` translation file to make `_(...)`
translated strings available. `kicad-cli --version`, and every
`kicad-cli pcb export …` / `sch export …` command, never actually
prints a translated string — the CLI's output is programmatic.

`_(...)` inside kicommon is safe when no catalog is loaded: gettext's
runtime returns the source-English literal.

## The fix (patch 0057)

`common/pgm_base.cpp`: gate `m_locale->AddCatalog( dictionaryName )`
on `IsGUI()` — skip it in kicad-cli mode. Both `SetLanguage()` and
`SetDefaultLanguage()` are patched.

Expected impact:

- **-1 MB peak heap** during CLI startup
- **-10 000 allocation calls** during CLI startup
- **~5-15 ms wall time** from the translation-catalog IO path

Will be verified with a same-heaptrack-recipe run against
patched-master once that binary is built.

## Other opportunities from this profile

- `wxUILocale::InitLanguagesDB` (486 temp allocs) enumerates every
  known language just to find the system default. Not fixable in
  KiCad — it's inside wxWidgets. Filed as a known bounce.
- `wxFileName::FileExists` (247 temp allocs) inside
  `wxFileTranslationsLoader::GetAvailableTranslations` — probes for
  translation files. Redundant when we've skipped AddCatalog; the
  next investigation is whether we can also skip the enumeration.
- 33,927 calls at 12.30 KB peak = a lot of tiny per-call short-lived
  temp allocs elsewhere in wxBase. Individually small but worth
  auditing when profiling `pcb export svg` where every plotted
  shape may hit these.

## Reproducing

```
$ export PATH=$HOME/local/wx-root/usr/bin:$PATH
$ export LD_LIBRARY_PATH=$HOME/local/kicad-root/usr/lib/aarch64-linux-gnu:$HOME/local/wx-root/usr/lib/aarch64-linux-gnu:$LD_LIBRARY_PATH
$ heaptrack -o /tmp/ht-9 $HOME/local/kicad-root/usr/bin/kicad-cli --version
$ heaptrack_print /tmp/ht-9.gz | less
```

Raw capture archived at
`harness/reports/2026-08-23-heaptrack-9.0.8-version.gz` (in the
repo, ~200 KB compressed).
