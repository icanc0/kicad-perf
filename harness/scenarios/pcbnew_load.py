"""Scenario: pcbnew loads a board and reaches interactive.

Drives pcbnew under Xvfb, opens a supplied .kicad_pcb, waits for the
window to become interactive, then closes.

Reports: wall_ms, max_rss_kb, user_ms, sys_ms; RSS curve CSV path
for after-the-fact inspection.
"""

from __future__ import annotations
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


HARNESS = Path(__file__).resolve().parent.parent


def name() -> str:
    return "pcbnew.load"


def description() -> str:
    return "pcbnew opens a .kicad_pcb under Xvfb — time to interactive + peak RAM"


def _find_xvfb(env_path: str) -> str | None:
    for p in env_path.split(":"):
        c = Path(p) / "Xvfb"
        if c.is_file() and os.access(c, os.X_OK):
            return str(c)
    return None


def _find_xdotool(env_path: str) -> str | None:
    for p in env_path.split(":"):
        c = Path(p) / "xdotool"
        if c.is_file() and os.access(c, os.X_OK):
            return str(c)
    return None


def run(pcbnew_binary: Path, ld_library_path: str, work_dir: Path,
        board_fixture: Path | None = None,
        rss_sampler: str | None = None,
        display: str = ":98",
        interactive_wait_s: float = 8.0) -> dict[str, Any]:
    """Run pcbnew under a scratch Xvfb; open the given board fixture.

    board_fixture defaults to the starfish board from kicanvas.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    if board_fixture is None:
        board_fixture = Path.home() / (
            "not-my-projects/kicad-references/"
            "kicanvas/debug/examples/starfish.kicad_pcb"
        )

    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = ld_library_path
    env["DISPLAY"] = display

    xvfb = _find_xvfb(env.get("PATH", "")) \
        or _find_xvfb(str(Path.home() / "local/wx-root/usr/bin"))
    if xvfb is None:
        return {"scenario": name(), "error": "Xvfb not found"}
    xdo = _find_xdotool(env.get("PATH", "")) \
        or _find_xdotool(str(Path.home() / "local/wx-root/usr/bin"))

    # Launch Xvfb.
    xvfb_log = work_dir / "xvfb.log"
    xvfb_proc = subprocess.Popen(
        [xvfb, display, "-screen", "0", "1920x1080x24"],
        stdout=xvfb_log.open("wb"), stderr=subprocess.STDOUT,
    )
    time.sleep(0.5)  # let Xvfb bind

    try:
        # Sample RSS during a controlled pcbnew run.
        rss_csv = work_dir / "rss.csv"
        pcb_log = work_dir / "pcbnew.log"

        # Compose the child command. The rss_sampler wrapper handles
        # timing; pcbnew opens the board and we kill it after
        # interactive_wait_s.
        pcb_cmd = [str(pcbnew_binary), str(board_fixture)]
        if rss_sampler:
            full_cmd = [rss_sampler, str(rss_csv), "--"] + pcb_cmd
        else:
            full_cmd = pcb_cmd

        t0 = time.monotonic()
        pcb_proc = subprocess.Popen(
            full_cmd, env=env,
            stdout=pcb_log.open("wb"), stderr=subprocess.STDOUT,
        )

        # Wait for the pcbnew window to appear, then hold briefly for
        # first-paint completion, then close cleanly with a WM_DELETE.
        window_id: str | None = None
        deadline = time.monotonic() + interactive_wait_s
        while time.monotonic() < deadline:
            if xdo:
                r = subprocess.run(
                    [xdo, "search", "--sync", "--onlyvisible",
                     "--name", "Pcbnew"],
                    env=env, capture_output=True, text=True, timeout=1,
                )
                if r.returncode == 0 and r.stdout.strip():
                    window_id = r.stdout.strip().split()[0]
                    break
            time.sleep(0.1)

        if window_id:
            # Let it finish first paint.
            time.sleep(1.5)
            subprocess.run(
                [xdo, "windowkill", window_id],
                env=env, capture_output=True, timeout=2,
            )

        pcb_proc.wait(timeout=interactive_wait_s + 5)
        wall_ms = int((time.monotonic() - t0) * 1000)

        result: dict[str, Any] = {
            "scenario": name(),
            "binary": str(pcbnew_binary),
            "board_fixture": str(board_fixture),
            "wall_ms_observed": wall_ms,
            "window_appeared": window_id is not None,
            "rss_csv": str(rss_csv) if rss_sampler else None,
            "pcbnew_log": str(pcb_log),
        }
        if rss_csv.exists():
            result.update(_parse_rss_summary(rss_csv))
        return result

    finally:
        xvfb_proc.terminate()
        try:
            xvfb_proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            xvfb_proc.kill()


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
