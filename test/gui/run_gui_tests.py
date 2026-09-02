#!/usr/bin/env python3
"""Host driver for the Midvatten GUI test pass.

Two toolkits, same runner and scenes:
- Qt6 (default): inside the ``midvatten-docs:4.2.2`` Docker image (QGIS 4.2.2).
- Qt5 (``--host``): the host's own QGIS (3.44 / Qt 5.15) under Xvfb, using a
  throwaway profile with its own plugin symlink -- the shared plugins symlink
  is NEVER touched.

The plugin is read-only in both; the runner copies the tutorial DB to a
writable out dir before opening it, so nothing mutates the shared fixture.

    python3 test/gui/run_gui_tests.py --mode coverage           # Qt6 / Docker
    python3 test/gui/run_gui_tests.py --mode coverage --host    # Qt5 / host

See ``docs/GUI_AUTOMATION.md`` for the mechanism and ``docs/superpowers/plans/
2026-09-02-gui-test-pass-plan.md`` for the plan.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

IMAGE = "midvatten-docs:4.2.2"
PLUGIN = Path(__file__).resolve().parents[2]          # the worktree root
DEFAULT_WIKI = Path("/home/hsai1/dev/qgis-midvatten-plugin.wiki")
XVFB = ["xvfb-run", "-a", "-s", "-screen 0 1600x1000x24"]


def _run_qt6(ns) -> tuple[list[str], dict, object]:
    """Build the Docker command for the Qt6 image. Returns (cmd, env, cleanup)."""
    db = "/wiki/tutorial_data/build/tutorial.sqlite"
    qgis = ["qgis", "--nologo", "--profiles-path", "/work", "--profile", "shot",
            "--code", "/plugin/test/gui/runner.py", "--py-args", "--db", db, "--out", "/out",
            "--mode", ns.mode, "--harness-dir", "/plugin/test/gui", "--"]
    # A unique name so this container is never swept up by an `ancestor=`-filtered
    # `docker kill` from a concurrent agent sharing the same image.
    name = f"midv-gui-test-{os.getpid()}"
    cmd = ["docker", "run", "--rm", "--init", "--name", name,
           "--user", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp",
           "-v", f"{ns.wiki}:/wiki:ro", "-v", f"{ns.plugin}:/plugin:ro",
           "-v", f"{ns.out}:/out", "-w", "/wiki", IMAGE, *XVFB, *qgis]
    return cmd, dict(os.environ), lambda: None


def _run_qt5_host(ns) -> tuple[list[str], dict, object]:
    """Build the host QGIS (Qt5) command under a throwaway profile whose OWN
    plugins/midvatten symlink points at this worktree. The shared QGIS profile
    and its plugins symlink are never touched. Returns (cmd, env, cleanup)."""
    profile_root = Path(tempfile.mkdtemp(prefix="midv-gui-qt5-"))
    plugins_dir = profile_root / "shot" / "python" / "plugins"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "midvatten").symlink_to(ns.plugin)

    db = str(ns.wiki / "tutorial_data/build/tutorial.sqlite")
    harness_dir = str(ns.plugin / "test/gui")
    cmd = [*XVFB, "qgis", "--nologo", "--profiles-path", str(profile_root), "--profile", "shot",
           "--code", str(ns.plugin / "test/gui/runner.py"), "--py-args",
           "--db", db, "--out", str(ns.out), "--mode", ns.mode,
           "--harness-dir", harness_dir, "--"]
    env = dict(os.environ)
    pkgroot = str(ns.plugin / "_pkgroot")
    env["PYTHONPATH"] = pkgroot + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["MPLCONFIGDIR"] = "/tmp/mplcache-host"
    env["QT_LOGGING_RULES"] = "*.debug=false"
    # Exclude ~/.local site-packages: it may carry a NumPy 2.x that shadows the
    # system NumPy 1.x the host QGIS's GDAL/numpy C-extensions were compiled
    # against (crashes QGIS on startup). System numpy 1.26 + pandas 2.1 remain
    # available. Set only in this subprocess's env -- never the user's shell.
    env["PYTHONNOUSERSITE"] = "1"
    # CRITICAL on a Wayland desktop: without this, Qt sees the inherited
    # WAYLAND_DISPLAY and draws on the user's REAL screen, ignoring the headless
    # Xvfb X server xvfb-run set up. Force xcb + drop the Wayland handle so the
    # whole run stays inside Xvfb and never touches the interactive session.
    env.pop("WAYLAND_DISPLAY", None)
    env["QT_QPA_PLATFORM"] = "xcb"
    return cmd, env, lambda: shutil.rmtree(profile_root, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", default="coverage")
    ap.add_argument("--host", action="store_true", help="run on host QGIS (Qt5) instead of Docker (Qt6)")
    ap.add_argument("--plugin", type=Path, default=PLUGIN)
    ap.add_argument("--wiki", type=Path, default=DEFAULT_WIKI)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--timeout", type=int, default=600)
    ns = ap.parse_args(argv)
    if ns.out is None:
        ns.out = PLUGIN / ("test/gui/.out-host" if ns.host else "test/gui/.out")

    ns.out.mkdir(parents=True, exist_ok=True)
    cmd, env, cleanup = (_run_qt5_host(ns) if ns.host else _run_qt6(ns))

    print("+", " ".join(cmd), file=sys.stderr)
    report_file = ns.out / "gui_test_report.json"
    report_file.unlink(missing_ok=True)
    try:
        subprocess.run(cmd, check=True, timeout=ns.timeout, env=env)
    except subprocess.CalledProcessError as e:
        print(f"process exited {e.returncode}", file=sys.stderr)
    except subprocess.TimeoutExpired:
        print(f"process timed out after {ns.timeout}s", file=sys.stderr)
        return 2
    finally:
        cleanup()

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

    # coverage / outputs / fill: a table of per-result rows.
    if report.get("fixture"):
        print(f"fixture: {report.get('fixture')}")
    print()
    for r in report.get("results", []):
        mark = {"ok": "  ok  ", "blocked": "block ", "no-window": "  --  "}.get(r["status"], "FAIL !")
        print(f"[{mark}] {r.get('menu', ''):>7} {r['id']:<34} {r.get('detail', '')}")
    summary = report.get("summary", {})
    print(f"\nsummary: {summary}")
    return 1 if summary.get("FAIL") else 0


if __name__ == "__main__":
    sys.exit(main())
