#!/usr/bin/env python3
"""Host driver for the Midvatten GUI test pass (Docker + QGIS 4.2.2/Qt6 + Xvfb).

Runs ``test/gui/runner.py`` inside the ``midvatten-docs:4.2.2`` image against the
plugin code in this worktree, using the wiki repo's built tutorial database as
the fixture. The plugin is mounted read-only; the runner copies the DB to a
writable ``/out`` before opening it, so nothing mutates the shared fixture.

    python3 test/gui/run_gui_tests.py --mode coverage

See ``docs/GUI_AUTOMATION.md`` for the mechanism and ``docs/superpowers/plans/
2026-09-02-gui-test-pass-plan.md`` for the plan.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

IMAGE = "midvatten-docs:4.2.2"
PLUGIN = Path(__file__).resolve().parents[2]          # the worktree root
DEFAULT_WIKI = Path("/home/hsai1/dev/qgis-midvatten-plugin.wiki")
DEFAULT_DB = "/wiki/tutorial_data/build/tutorial.sqlite"
RUNNER = "/plugin/test/gui/runner.py"
XVFB = ["xvfb-run", "-a", "-s", "-screen 0 1600x1000x24"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", default="coverage")
    ap.add_argument("--plugin", type=Path, default=PLUGIN)
    ap.add_argument("--wiki", type=Path, default=DEFAULT_WIKI)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=PLUGIN / "test/gui/.out")
    ap.add_argument("--timeout", type=int, default=600)
    ns = ap.parse_args(argv)

    ns.out.mkdir(parents=True, exist_ok=True)
    qgis = ["qgis", "--nologo", "--profiles-path", "/work", "--profile", "shot",
            "--code", RUNNER, "--py-args", "--db", ns.db, "--out", "/out",
            "--mode", ns.mode, "--"]
    # A unique name so this container is never swept up by an `ancestor=`-filtered
    # `docker kill` from a concurrent agent sharing the same image.
    name = f"midv-gui-test-{os.getpid()}"
    cmd = ["docker", "run", "--rm", "--init", "--name", name,
           "--user", f"{os.getuid()}:{os.getgid()}",
           "-e", "HOME=/tmp",
           "-v", f"{ns.wiki}:/wiki:ro",
           "-v", f"{ns.plugin}:/plugin:ro",
           "-v", f"{ns.out}:/out",
           "-w", "/wiki", IMAGE, *XVFB, *qgis]

    print("+", " ".join(cmd), file=sys.stderr)
    report_file = ns.out / "gui_test_report.json"
    report_file.unlink(missing_ok=True)
    try:
        subprocess.run(cmd, check=True, timeout=ns.timeout)
    except subprocess.CalledProcessError as e:
        print(f"container exited {e.returncode}", file=sys.stderr)
    except subprocess.TimeoutExpired:
        print(f"container timed out after {ns.timeout}s", file=sys.stderr)
        return 2

    if not report_file.exists():
        print("no report produced", file=sys.stderr)
        return 2
    report = json.loads(report_file.read_text())
    if "error" in report:
        print("runner error:\n" + report["error"], file=sys.stderr)
        return 2

    print(f"\noracle totals: {report.get('oracle_totals')}")

    # create_db mode: a single result with a checks dict.
    if "checks" in report:
        print(f"target: {report.get('target')}\nabout_db: {report.get('about_db')}\n")
        for name, passed in report["checks"].items():
            print(f"[{'  ok  ' if passed else 'FAIL !'}] {name}")
        print(f"\nstatus: {report.get('status')}")
        return 1 if report.get("status") != "ok" else 0

    # coverage mode: a table of per-action results.
    print(f"fixture: {report.get('fixture')}\n")
    for r in report.get("results", []):
        mark = {"ok": "  ok  ", "blocked": "block ", "no-window": "  --  "}.get(r["status"], "FAIL !")
        print(f"[{mark}] {r['menu']:>7} {r['id']:<34} {r.get('detail', '')}")
    summary = report.get("summary", {})
    print(f"\nsummary: {summary}")
    return 1 if summary.get("FAIL") else 0


if __name__ == "__main__":
    sys.exit(main())
