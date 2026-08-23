"""Scenario: `kicad-cli --version`.

The cheapest sanity-check scenario. Measures the fixed CLI startup
cost, which is what patches P2/P4/P5/P17/P36-P39 target directly.

Reports: wall_ms (from hyperfine), max_rss_kb (from rss_sampler),
user_ms, sys_ms, cpu_ratio.
"""

from __future__ import annotations
import json
import subprocess
from pathlib import Path
from typing import Any


def name() -> str:
    return "cli.version"


def description() -> str:
    return "kicad-cli --version — fixed startup cost"


def run(kicad_cli: Path, ld_library_path: str, work_dir: Path,
        hyperfine: str = "hyperfine",
        rss_sampler: str | None = None) -> dict[str, Any]:
    """Run the scenario; return a dict of measured axes.

    Args:
      kicad_cli: absolute path to the kicad-cli binary to measure
      ld_library_path: colon-joined LD_LIBRARY_PATH the binary needs
      work_dir: where to drop hyperfine.json and rss.csv
      hyperfine: hyperfine binary (must be on PATH)
      rss_sampler: rss_sampler binary path; None disables that axis
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    hyperfine_json = work_dir / "hyperfine.json"
    rss_csv = work_dir / "rss.csv"

    import os
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = ld_library_path

    # Wall-time axis: hyperfine with warmup + min-runs.
    hf_cmd = [
        hyperfine, "--warmup", "3", "--min-runs", "10",
        "--export-json", str(hyperfine_json),
        f"{kicad_cli} --version",
    ]
    subprocess.run(hf_cmd, env=env, check=True, stdout=subprocess.DEVNULL)
    hf = json.loads(hyperfine_json.read_text())["results"][0]
    wall_median_ms = hf["median"] * 1000.0
    wall_stddev_ms = hf["stddev"] * 1000.0

    result: dict[str, Any] = {
        "scenario": name(),
        "binary": str(kicad_cli),
        "wall_median_ms": round(wall_median_ms, 2),
        "wall_stddev_ms": round(wall_stddev_ms, 2),
        "hyperfine_json": str(hyperfine_json),
    }

    # RAM axis: one rss_sampler run (RSS curve doesn't need N runs; the
    # summary values (max_rss) are stable across runs for this scenario).
    if rss_sampler:
        rss_cmd = [rss_sampler, str(rss_csv), "--", str(kicad_cli), "--version"]
        subprocess.run(rss_cmd, env=env, check=True, stdout=subprocess.DEVNULL)
        summary = _parse_rss_summary(rss_csv)
        result.update(summary)
        result["rss_csv"] = str(rss_csv)

    return result


def _parse_rss_summary(csv: Path) -> dict[str, Any]:
    """Read the SUMMARY line at the tail of rss_sampler's CSV."""
    text = csv.read_text().strip().splitlines()
    if not text:
        return {}
    last = text[-1]
    if not last.startswith("SUMMARY"):
        return {}
    out: dict[str, Any] = {}
    for field in last.split(",")[1:]:
        k, _, v = field.partition("=")
        try:
            out[k] = int(v)
        except ValueError:
            out[k] = v
    return out


if __name__ == "__main__":
    # Ad-hoc CLI: python scenarios/cli_version.py <kicad_cli> [<ld_lib_path>]
    import sys
    if len(sys.argv) < 2:
        print("usage: cli_version.py <kicad_cli> [<ld_library_path>]")
        raise SystemExit(2)
    cli = Path(sys.argv[1]).resolve()
    ldp = sys.argv[2] if len(sys.argv) > 2 else ""
    wd = Path("/tmp") / f"cli_version_{cli.name}"
    r = run(cli, ldp, wd, rss_sampler=str(Path(__file__).parent.parent
                                          / "collectors" / "rss_sampler"))
    print(json.dumps(r, indent=2))
