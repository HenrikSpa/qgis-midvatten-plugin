"""Runs inside QGIS via ``qgis --code runner.py --py-args ... --``.

Loads the Midvatten plugin, opens a *writable copy* of the tutorial database,
loads the plugin's own layer sets from it, then runs the requested mode. The
only mode implemented so far is ``coverage`` -- the section-5.5 sweep that
dispatches every action in ``plugin._actions_manifest`` and classifies whether
it opened a window, showed a message-bar error, or raised.

Results (and any screenshots) are written under ``--out`` as JSON; QGIS floods
stdout/stderr, so nothing is trusted there.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import traceback
from pathlib import Path

import qgis.utils
from qgis.core import QgsApplication, QgsProject
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtGui import QDesktopServices

# QGIS runs this via `--code FILE`, an exec context where __file__ is NOT
# defined -- so the harness directory is the fixed container mount point, not a
# path derived from __file__ (the wiki runner hardcodes its dir for the same
# reason). run_gui_tests.py always mounts this worktree at /plugin.
HERE = "/plugin/test/gui"
sys.path.insert(0, HERE)
from harness import Context, Oracles  # noqa: E402

LOAD_ACTIONS = ["add_midvatten_layers", "load_data_domains", "load_data_tables"]

# A broadly-useful selection for the tutorial DB: obsids that carry logger,
# flow and lab data, so most needs_selection plot/report tools take their happy
# path. This is Midvatten fixture knowledge, kept out of the shared harness.
DEFAULT_SELECTION = ("obs_points", "obsid IN ('OW100','PW1001','Pz0917','Pz0918','Pz1005')")


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="")
    ap.add_argument("--out", default="/out")
    ap.add_argument("--mode", default="coverage")
    argv = [a for a in sys.argv[1:] if a != "--"]
    return ap.parse_args(argv)


def start_plugin():
    qgis.utils.loadPlugin("midvatten")
    qgis.utils.startPlugin("midvatten")
    return qgis.utils.plugins["midvatten"]


def open_database(plugin, dbpath: str) -> None:
    settings = json.dumps({"spatialite": {"dbpath": dbpath}})
    QgsProject.instance().writeEntry("Midvatten", "database", settings)
    plugin.ms.load_settings()


def load_layers(ctx: Context, plugin, out: Path | None = None) -> dict[str, int | None]:
    for action_id in LOAD_ACTIONS:
        if out is not None:
            (out / "phase.txt").write_text(f"load:{action_id}\n")
        spec = next((s for s in plugin._actions_manifest if s.id == action_id), None)
        if spec is None:
            continue
        try:
            plugin._dispatch(spec)
            ctx.wait(1500)
        except Exception:
            pass
    return {
        "obs_points_layer": 1 if ctx.layer("obs_points") is not None else 0,
        "obs_points_rows": ctx.db_count("obs_points"),
        "w_levels_logger_rows": ctx.db_count("w_levels_logger"),
    }


def run_coverage(ctx: Context, plugin, out: Path) -> dict:
    """Sweep every action. Writes the report after each one so a hang on action
    N+1 still leaves N results on disk and names the action that hung."""
    results = []
    summary: dict[str, int] = {}
    progress = out / "gui_test_report.json"
    specs = list(plugin._actions_manifest)
    for i, spec in enumerate(specs):
        # Record intent before dispatching, so a hard hang points at the culprit.
        (out / "progress.txt").write_text(f"{i + 1}/{len(specs)} dispatching {spec.id}\n")
        try:
            result = ctx.sweep_action(spec)
        except Exception:
            result = {
                "id": spec.id, "label": spec.label, "menu": spec.menu,
                "status": "FAIL", "detail": "harness error: " + traceback.format_exc().splitlines()[-1],
            }
        results.append(result)
        summary[result["status"]] = summary.get(result["status"], 0) + 1
        # Rewrite the full report each step so a hang on N+1 leaves N on disk.
        progress.write_text(json.dumps({"mode": "coverage", "partial": True,
                                        "results": results, "summary": summary}, indent=2))
    return {"results": results, "summary": summary}


def main() -> None:
    ns = parse_args()
    out = Path(ns.out)
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {"mode": ns.mode}

    def phase(name: str) -> None:
        (out / "phase.txt").write_text(name + "\n")

    try:
        phase("copy_db")
        # Work on a writable copy so the shared fixture stays pristine.
        work_db = out / "work.sqlite"
        shutil.copy(ns.db, work_db)

        # Report tools open HTML in the system browser; under Xvfb that can
        # spawn a helper that hangs. Neutralise it and record the URLs instead.
        opened_urls: list[str] = []
        QDesktopServices.openUrl = staticmethod(lambda url: (opened_urls.append(url.toString()), True)[1])

        phase("start_plugin")
        plugin = start_plugin()
        oracles = Oracles()
        oracles.install()

        phase("open_database")
        open_database(plugin, str(work_db))
        mw = qgis.utils.iface.mainWindow()
        mw.resize(1600, 1000)
        mw.showMaximized()

        ctx = Context(plugin, qgis.utils.iface, out, oracles, default_selection=DEFAULT_SELECTION)
        ctx.install_modal_reaper()
        ctx.wait(2000)
        phase("load_layers")
        report["fixture"] = load_layers(ctx, plugin, out)
        phase("sweep")

        if ns.mode == "coverage":
            report.update(run_coverage(ctx, plugin, out))
            report["opened_urls"] = opened_urls
        else:
            report["error"] = f"unknown mode {ns.mode!r}"

        report["oracle_totals"] = {
            "messages": len(oracles.messages),
            "tracebacks": len(oracles.tracebacks),
        }
    except Exception:
        report["error"] = traceback.format_exc()
    (out / "gui_test_report.json").write_text(json.dumps(report, indent=2))
    QTimer.singleShot(500, QgsApplication.instance().quit)
    QTimer.singleShot(5000, lambda: os._exit(0))


QTimer.singleShot(3000, main)
