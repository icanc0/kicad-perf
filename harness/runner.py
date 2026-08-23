#!/usr/bin/env python3
"""Runner: walk {binary × scenario × N} and emit a comparison report.

Reads binaries.toml, scenarios.toml (or accepts overrides from argv),
runs each scenario against each binary, writes per-run JSON to
reports/<stamp>/raw/<binary>__<scenario>__<i>.json, then renders a
Markdown summary comparing binaries side by side.

Rejects any scenario driver that doesn't declare its axes.
"""

from __future__ import annotations
import argparse
import datetime as dt
import importlib.util
import json
import statistics
import sys
from pathlib import Path
from typing import Any


HARNESS = Path(__file__).resolve().parent
COLLECTORS = HARNESS / "collectors"
DEFAULT_RSS_SAMPLER = COLLECTORS / "rss_sampler"


def load_scenario(py_path: Path):
    spec = importlib.util.spec_from_file_location(py_path.stem, py_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    for required in ("name", "run"):
        if not hasattr(mod, required):
            raise ValueError(f"{py_path}: missing '{required}' attribute")
    return mod


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Reduce per-run rows to median values on numeric axes.

    Any axis that isn't a number across every row is passed through
    from the first row.
    """
    if not rows:
        return {}
    keys = rows[0].keys()
    out: dict[str, Any] = {}
    for k in keys:
        vals = [r.get(k) for r in rows]
        numeric = [v for v in vals if isinstance(v, (int, float))]
        if len(numeric) == len(vals) and numeric:
            out[k] = round(statistics.median(numeric), 2)
        else:
            out[k] = vals[0]
    out["run_count"] = len(rows)
    return out


def render_markdown(all_results: dict[str, list[dict[str, Any]]]) -> str:
    """Render a Markdown comparison table across binaries.

    all_results: {scenario_name: [ {binary_label, ..axes}, ... ]}
    """
    out = ["# kicad-perf harness report", "",
           f"Generated {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}", ""]

    for scenario, rows in all_results.items():
        out.append(f"## {scenario}")
        out.append("")
        # Numeric axes we care about, in a stable order.
        axes = ["wall_median_ms", "wall_stddev_ms", "wall_ms",
                "user_ms", "sys_ms", "max_rss_kb"]
        header = ["binary"] + axes
        out.append("| " + " | ".join(header) + " |")
        out.append("|" + "|".join(["---"] * len(header)) + "|")
        for r in rows:
            cells = [r.get("binary_label", "?")]
            for ax in axes:
                v = r.get(ax)
                cells.append("" if v is None else str(v))
            out.append("| " + " | ".join(cells) + " |")
        out.append("")

        # Regression alarm: if the last binary has a wall_median_ms
        # ≥ 1.05x the first, flag it.
        if len(rows) >= 2 and rows[0].get("wall_median_ms") and rows[-1].get("wall_median_ms"):
            first = rows[0]["wall_median_ms"]
            last  = rows[-1]["wall_median_ms"]
            if last >= first * 1.05:
                out.append(f"> ⚠  wall regression: {rows[-1]['binary_label']} "
                           f"{last} ms ≥ 1.05× {rows[0]['binary_label']} {first} ms")
                out.append("")

    return "\n".join(out) + "\n"


def parse_binaries(spec: str) -> list[tuple[str, Path, str]]:
    """Parse `label=binary_path[|LD_LIBRARY_PATH]` entries."""
    out = []
    for line in spec.split(";"):
        line = line.strip()
        if not line:
            continue
        label, _, rest = line.partition("=")
        binary, _, ldp = rest.partition("|")
        out.append((label.strip(),
                    Path(binary.strip()).resolve(),
                    ldp.strip()))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--binaries", required=True,
                    help=("Semicolon-separated list of "
                          "'label=<binary_path>[|<LD_LIBRARY_PATH>]'."))
    ap.add_argument("--scenarios", required=True,
                    help="Comma-separated scenario module names or paths.")
    ap.add_argument("--runs", type=int, default=1,
                    help="Number of runs per (binary, scenario). "
                         "Wall/RSS axes are aggregated with median.")
    ap.add_argument("--out-dir", type=Path,
                    default=HARNESS / "reports"
                         / dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d-%H%M"))
    ap.add_argument("--rss-sampler", default=str(DEFAULT_RSS_SAMPLER))
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = args.out_dir / "raw"
    raw_dir.mkdir(exist_ok=True)

    binaries = parse_binaries(args.binaries)
    if not binaries:
        print("no binaries", file=sys.stderr)
        return 2

    scenarios = []
    for s in args.scenarios.split(","):
        s = s.strip()
        p = Path(s)
        if not p.exists():
            p = HARNESS / "scenarios" / f"{s}.py"
        if not p.exists():
            print(f"scenario not found: {s}", file=sys.stderr)
            return 2
        scenarios.append(load_scenario(p))

    per_scenario: dict[str, list[dict[str, Any]]] = {}
    for scen in scenarios:
        rows_this_scen: list[dict[str, Any]] = []
        for label, binary, ldp in binaries:
            print(f"== {scen.name()}  ×  {label} ==", flush=True)
            runs: list[dict[str, Any]] = []
            for i in range(args.runs):
                wd = raw_dir / f"{label}__{scen.name()}__{i}"
                r = scen.run(binary, ldp, wd, rss_sampler=args.rss_sampler)
                (wd / "result.json").write_text(json.dumps(r, indent=2))
                runs.append(r)
            summ = summarise(runs)
            summ["binary_label"] = label
            summ["binary"] = str(binary)
            rows_this_scen.append(summ)
        per_scenario[scen.name()] = rows_this_scen

    report_md = args.out_dir / "report.md"
    report_md.write_text(render_markdown(per_scenario))
    print(f"\nReport: {report_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
