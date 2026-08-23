#!/usr/bin/env python3
"""Generate a synthetic hierarchical schematic fixture.

Emits an N-sheet hierarchy with M symbols per sheet, all in KiCad's
current sexp format. Handy for stressing the schematic-load path
(patches P47-P50 target O(N·M) loops there).

Usage:
  gen_hier.py --sheets 100 --syms 20 --out ./hier
"""

from __future__ import annotations
import argparse
import uuid
from pathlib import Path


ROOT_TEMPLATE = """\
(kicad_sch (version 20250114) (generator "gen_hier")
  (uuid {root_uuid})
  (paper "A4")
  {sheet_stanzas}
  (sheet_instances
    (path "/" (page "1"))
    {sheet_instance_stanzas}
  )
)
"""

SHEET_IN_ROOT = """\
  (sheet (at {x} {y}) (size 30 20)
    (uuid {uuid})
    (property "Sheetname" "S{idx:03d}" (at {x} {y_up}))
    (property "Sheetfile" "s{idx:03d}.kicad_sch" (at {x} {y_dn}))
  )
"""

SHEET_INSTANCE = '    (path "/{uuid}" (page "{page}"))'

CHILD_TEMPLATE = """\
(kicad_sch (version 20250114) (generator "gen_hier")
  (uuid {sheet_uuid})
  (paper "A4")
  {symbols}
)
"""

SYMBOL_STANZA = """\
  (symbol (lib_id "Device:R") (at {x} {y} 0)
    (uuid {uuid})
    (property "Reference" "R{ref}" (at {x} {y_up}))
    (property "Value" "10k" (at {x} {y_dn}))
  )
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheets", type=int, default=100)
    ap.add_argument("--syms",   type=int, default=20)
    ap.add_argument("--out",    type=Path, required=True)
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    root_uuid = str(uuid.uuid4())
    sheet_stanzas = []
    sheet_instance_stanzas = []

    for i in range(args.sheets):
        sh_uuid = str(uuid.uuid4())
        x = 20 + (i % 10) * 40
        y = 20 + (i // 10) * 25
        sheet_stanzas.append(SHEET_IN_ROOT.format(
            idx=i, uuid=sh_uuid, x=x, y=y, y_up=y - 2, y_dn=y + 22))
        sheet_instance_stanzas.append(SHEET_INSTANCE.format(uuid=sh_uuid, page=i + 2))

        symbols = []
        ref_base = i * args.syms + 1
        for j in range(args.syms):
            sx = 30 + (j % 5) * 25
            sy = 30 + (j // 5) * 25
            symbols.append(SYMBOL_STANZA.format(
                uuid=str(uuid.uuid4()),
                ref=ref_base + j,
                x=sx, y=sy, y_up=sy - 2, y_dn=sy + 2))
        (args.out / f"s{i:03d}.kicad_sch").write_text(
            CHILD_TEMPLATE.format(sheet_uuid=sh_uuid,
                                  symbols="".join(symbols)))

    (args.out / "root.kicad_sch").write_text(ROOT_TEMPLATE.format(
        root_uuid=root_uuid,
        sheet_stanzas="".join(sheet_stanzas),
        sheet_instance_stanzas="\n".join(sheet_instance_stanzas)))

    # Bare kicad_pro so the eeschema opener finds the project.
    (args.out / "root.kicad_pro").write_text('{"meta":{"version":1}}\n')
    print(f"wrote {args.sheets} sheets × {args.syms} syms = "
          f"{args.sheets * args.syms} symbols into {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
