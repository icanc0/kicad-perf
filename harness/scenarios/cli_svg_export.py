"""Scenario: `kicad-cli pcb export svg --layers F.Cu <board>`.

The primary target of many patches in this series (P3, P22/P23/P24,
P40-P44 for board init; P54-P56 for plot-loop hoists). Uses a real
5 MB fixture from the kicanvas reference project.

Reports: wall_ms (median + stddev from hyperfine), max_rss_kb,
user_ms, sys_ms from rss_sampler summary.
"""

from __future__ import annotations
import json
import os
import subprocess
from pathlib import Path
from typing import Any


DEFAULT_BOARD = (Path.home()
                 / "not-my-projects/kicad-references"
                 / "kicanvas/debug/examples/starfish.kicad_pcb")


def name() -> str:
    return "cli.svg_export"


def description() -> str:
    return "kicad-cli pcb export svg --layers F.Cu <5MB board>"


def run(kicad_cli: Path, ld_library_path: str, work_dir: Path,
        board: Path | None = None,
        hyperfine: str = "hyperfine",
        rss_sampler: str | None = None) -> dict[str, Any]:
    work_dir.mkdir(parents=True, exist_ok=True)
    board = board or DEFAULT_BOARD
    if not board.exists():
        return {"scenario": name(), "binary": str(kicad_cli),
                "error": f"board fixture missing: {board}"}

    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = ld_library_path

    out_svg = work_dir / "out.svg"
    cmd_str = (f"{kicad_cli} pcb export svg --layers F.Cu "
               f"--output {out_svg} {board}")

    hyperfine_json = work_dir / "hyperfine.json"
    hf_cmd = [
        hyperfine, "--warmup", "2", "--min-runs", "5",
        "--export-json", str(hyperfine_json),
        cmd_str,
    ]
    subprocess.run(hf_cmd, env=env, check=True, stdout=subprocess.DEVNULL)
    hf = json.loads(hyperfine_json.read_text())["results"][0]
    wall_median_ms = hf["median"] * 1000.0
    wall_stddev_ms = hf["stddev"] * 1000.0

    result: dict[str, Any] = {
        "scenario": name(),
        "binary": str(kicad_cli),
        "board": str(board),
        "board_size_bytes": board.stat().st_size,
        "wall_median_ms": round(wall_median_ms, 2),
        "wall_stddev_ms": round(wall_stddev_ms, 2),
        "out_svg_bytes": out_svg.stat().st_size if out_svg.exists() else None,
    }

    if rss_sampler:
        rss_csv = work_dir / "rss.csv"
        rss_cmd = [rss_sampler, str(rss_csv), "--"] + cmd_str.split()
        subprocess.run(rss_cmd, env=env, check=True, stdout=subprocess.DEVNULL)
        summary = _parse_rss_summary(rss_csv)
        result.update(summary)
        result["rss_csv"] = str(rss_csv)

    return result


def _parse_rss_summary(csv: Path) -> dict[str, Any]:
    lines = csv.read_text().strip().splitlines()
    if not lines:
        return {}
    last = lines[-1]
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
