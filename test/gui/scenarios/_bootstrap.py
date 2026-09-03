"""Shared bootstrap for standalone GUI scenario scripts under test/gui/scenarios/.

These scenarios extend the coverage of ``test/gui/runner.py`` (Part B of the
2026-09 GUI hardening pass) without editing ``runner.py`` or ``harness.py``.
Each scenario is its own ``qgis --code FILE`` entrypoint, run in its own Qt6
container, e.g.::

    docker run --rm --init --name <unique> ... midvatten-docs:4.2.2 \\
      xvfb-run -a -s "-screen 0 1600x1000x24" \\
      qgis --nologo --profiles-path /work --profile shot \\
           --code /plugin/test/gui/scenarios/import_fieldlogger_full.py \\
           --py-args --db /wiki/tutorial_data/build/tutorial.sqlite --out /out \\
                     --harness-dir /plugin/test/gui --

This module mirrors the setup ``runner.py``'s ``main()`` does (load the
plugin, copy the fixture DB to a writable location, open it, load the
default layers) so a scenario file only has to define ``scenario(ctx,
plugin, out) -> dict`` and call ``run_scenario(scenario)``.
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

DEFAULT_SELECTION = (
    "obs_points",
    "obsid IN ('OW100','PW1001','Pz0917','Pz0918','Pz1005')",
)


def harness_dir() -> str:
    # Same rationale as runner.py: __file__ is not defined in a `--code`
    # exec context, so the harness dir must come from argv.
    argv = sys.argv
    if "--harness-dir" in argv:
        return argv[argv.index("--harness-dir") + 1]
    return "/plugin/test/gui"


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="")
    ap.add_argument("--out", default="/out")
    ap.add_argument("--harness-dir", default="/plugin/test/gui")
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


def _load_default_layers(ctx, plugin) -> None:
    for action_id in ("add_midvatten_layers", "load_data_domains", "load_data_tables"):
        spec = next((s for s in plugin._actions_manifest if s.id == action_id), None)
        if spec is None:
            continue
        try:
            plugin._dispatch(spec)
            ctx.wait(1500)
        except Exception:
            pass


def _bootstrap_and_run(ns, scenario_fn) -> None:
    sys.path.insert(0, harness_dir())
    from harness import Context, Oracles  # noqa: E402  (only importable inside QGIS)

    out = Path(ns.out)
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {}

    def phase(name: str) -> None:
        (out / "phase.txt").write_text(name + "\n")

    try:
        # Report tools open HTML via the system browser; neutralise it like
        # runner.py does so Xvfb never spawns a hanging helper.
        opened_urls: list[str] = []
        QDesktopServices.openUrl = staticmethod(
            lambda url: (opened_urls.append(url.toString()), True)[1]
        )

        phase("start_plugin")
        plugin = start_plugin()
        oracles = Oracles()
        oracles.install()
        mw = qgis.utils.iface.mainWindow()
        mw.resize(1600, 1000)
        mw.showMaximized()
        ctx = Context(
            plugin, qgis.utils.iface, out, oracles, default_selection=DEFAULT_SELECTION
        )
        ctx.wait(2000)

        phase("copy_db")
        work_db = out / "work.sqlite"
        shutil.copy(ns.db, work_db)
        phase("open_database")
        open_database(plugin, str(work_db))
        phase("load_layers")
        _load_default_layers(ctx, plugin)

        phase("scenario")
        result = scenario_fn(ctx, plugin, out) or {}
        report.update(result)
        report["opened_urls"] = opened_urls
        report["oracle_totals"] = {
            "messages": len(oracles.messages),
            "tracebacks": len(oracles.tracebacks),
        }
    except Exception:
        report["error"] = traceback.format_exc()
    (out / "gui_test_report.json").write_text(json.dumps(report, indent=2))
    QTimer.singleShot(500, QgsApplication.instance().quit)
    QTimer.singleShot(5000, lambda: os._exit(0))


def run_scenario(scenario_fn) -> None:
    """Schedule the bootstrap + scenario the same way runner.py schedules
    main(): 3s after the main window exists."""

    def main() -> None:
        ns = parse_args()
        _bootstrap_and_run(ns, scenario_fn)

    QTimer.singleShot(3000, main)


def visible_tool(class_name: str):
    """Return the visible top-level widget whose class name matches, else None."""
    from qgis.PyQt.QtWidgets import QApplication

    for w in QApplication.topLevelWidgets():
        if type(w).__name__ == class_name and w.isVisible():
            return w
    return None
