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
from qgis.PyQt.QtWidgets import QApplication, QPushButton

import midvatten.tools.create_db_dialogs as create_db_dialogs

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


def _drive_modal_accept(ctx: Context, before_click=None):
    """Schedule a driver that, once a modal is up, optionally runs before_click
    (e.g. click a Browse button whose picker has been patched) and then accepts
    it. Used by outputs mode, which must accept modals a global reaper would
    reject -- so outputs mode runs without the reaper installed."""
    def drive():
        dlg = QApplication.activeModalWidget()
        if dlg is None:
            QTimer.singleShot(200, drive)
            return
        if before_click is not None:
            before_click(dlg)
        dlg.accept()
    QTimer.singleShot(500, drive)


def _click_browse(dlg) -> None:
    for button in dlg.findChildren(QPushButton):
        if "rowse" in button.text().lower():
            button.click()
            break


def run_outputs(ctx: Context, plugin, out: Path, opened_urls: list) -> dict:
    """Group D: run each output-producing tool to completion and assert the
    real artifact -- files written, HTML produced, DB mutated -- not merely
    that a window opened. No global modal reaper: each tool's modal is driven
    to *acceptance* by _drive_modal_accept."""
    results = []
    report_path = out / "gui_test_report.json"

    def dispatch(action_id):
        plugin._dispatch(next(s for s in plugin._actions_manifest if s.id == action_id))

    def record(name, passed, detail):
        results.append({"id": name, "status": "ok" if passed else "FAIL", "detail": detail})
        report_path.write_text(json.dumps({"mode": "outputs", "partial": True,
                                            "results": results}, indent=2))

    def read_html(url: str) -> str:
        path = url[len("file://"):] if url.startswith("file://") else url
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    # -- export_csv: writes one CSV per table into the chosen folder ----
    try:
        import midvatten.tools.export_data as export_data
        csv_dir = out / "export_csv"
        shutil.rmtree(csv_dir, ignore_errors=True)
        csv_dir.mkdir()
        ctx.clear_selections()
        ctx.select_some("obs_points", "obsid IN ('OW100','PW1001','Pz0917')")
        ctx.activate("obs_points")
        orig = export_data.QFileDialog.getExistingDirectory
        export_data.QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: str(csv_dir))
        cp = ctx.oracles.checkpoint()
        _drive_modal_accept(ctx, _click_browse)
        try:
            dispatch("export_csv")
        finally:
            ctx.wait(2500)
            export_data.QFileDialog.getExistingDirectory = orig
        _, tbs = ctx.oracles.since(cp)
        obs_csv = csv_dir / "obs_points.csv"
        ok = obs_csv.exists() and obs_csv.stat().st_size > 0 and not tbs
        record("export_csv", ok, f"{len(list(csv_dir.glob('*.csv')))} csv files, "
               f"obs_points.csv={'present' if obs_csv.exists() else 'MISSING'}")
    except Exception:
        record("export_csv", False, "exc: " + traceback.format_exc().splitlines()[-1])

    # -- export_spatialite: writes a valid SpatiaLite DB (round-trip) ----
    try:
        import midvatten.tools.create_db_dialogs as cdd
        spatialite_out = out / "export.sqlite"
        for p in out.glob("export.sqlite*"):
            p.unlink()
        orig = cdd.QFileDialog.getSaveFileName
        cdd.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(spatialite_out), ""))
        cp = ctx.oracles.checkpoint()
        _drive_modal_accept(ctx, _click_browse)
        try:
            dispatch("export_spatialite")
        finally:
            ctx.wait(8000)  # config dialog + two progress dialogs + the export
            cdd.QFileDialog.getSaveFileName = orig
        _, tbs = ctx.oracles.since(cp)
        rows = None
        if spatialite_out.exists():
            open_database(plugin, str(spatialite_out))
            ctx.wait(300)
            rows = ctx.db_count("obs_points")
        ok = spatialite_out.exists() and rows is not None and not tbs
        record("export_spatialite", ok, f"file={'yes' if spatialite_out.exists() else 'no'}, "
               f"obs_points rows={rows}")
    except Exception:
        record("export_spatialite", False, "exc: " + traceback.format_exc().splitlines()[-1])
    finally:
        # restore the working fixture as the active DB for the report checks
        open_database(plugin, str(out / "work.sqlite"))
        ctx.wait(300)

    # -- reports: HTML written to the path handed to (patched) openUrl ---
    for action_id, obsid_expr, needle in [
        ("drillreport", "obsid IN ('Pz0917')", "Pz0917"),
        ("waterqualityreport", "obsid IN ('Pz0917','Pz0918','Pz1005')", "Pz0917"),
    ]:
        try:
            ctx.clear_selections()
            ctx.select_some("obs_points", obsid_expr)
            ctx.activate("obs_points")
            n_before = len(opened_urls)
            cp = ctx.oracles.checkpoint()
            dispatch(action_id)
            ctx.wait(2500)
            _, tbs = ctx.oracles.since(cp)
            new_urls = opened_urls[n_before:]
            html = read_html(new_urls[-1]) if new_urls else ""
            ok = bool(html) and needle in html and not tbs
            record(action_id, ok, f"html {len(html)} bytes, "
                   f"{'has' if needle in html else 'MISSING'} {needle}")
        except Exception:
            record(action_id, False, "exc: " + traceback.format_exc().splitlines()[-1])

    summary = {}
    for r in results:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    return {"results": results, "summary": summary, "opened_urls": opened_urls}


def run_create_db(ctx: Context, plugin, out: Path) -> dict:
    """Group A (create half): drive the real New-SpatiaLite-DB dialog to build a
    fresh empty database, then assert the plugin can create, open and load it.

    The dialog is driven like a user -- the native save-picker is patched and the
    dialog's own Browse button clicked, then OK pressed -- rather than writing its
    private widgets. No global modal reaper here: this mode drives its one modal
    itself and must accept (not reject) it."""
    target = out / f"created_{os.getpid()}.sqlite"
    target.unlink(missing_ok=True)
    orig_picker = create_db_dialogs.QFileDialog.getSaveFileName
    create_db_dialogs.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(target), ""))

    driven = {"ok": False}

    def drive():
        dlg = QApplication.activeModalWidget()
        if dlg is None:
            QTimer.singleShot(200, drive)
            return
        for button in dlg.findChildren(QPushButton):
            if "rowse" in button.text().lower():
                button.click()  # runs _browse_path -> patched picker -> path field
                break
        driven["ok"] = True
        dlg.accept()

    cp = ctx.oracles.checkpoint()
    QTimer.singleShot(500, drive)
    spec = next(s for s in plugin._actions_manifest if s.id == "new_db")
    try:
        plugin._dispatch(spec)  # blocks in dialog.exec() until drive() accepts
    finally:
        ctx.wait(2500)
        create_db_dialogs.QFileDialog.getSaveFileName = orig_picker

    # new_db() set the freshly-built DB as the active one; point the harness's
    # connection at it explicitly, then assert the schema.
    open_database(plugin, str(target))
    ctx.wait(500)
    _, tbs = ctx.oracles.since(cp)
    description = ctx.db_scalar("SELECT description FROM about_db LIMIT 1")

    load_spec = next((s for s in plugin._actions_manifest if s.id == "add_midvatten_layers"), None)
    if load_spec is not None:
        plugin._dispatch(load_spec)
        ctx.wait(1500)

    checks = {
        "dialog_driven_and_accepted": driven["ok"],
        "db_file_created": target.exists(),
        "about_db_version_present": bool(description and "Midvatten" in str(description)),
        "core_tables_present": ctx.db_count("obs_points") is not None
        and ctx.db_count("w_levels") is not None,
        "obs_points_empty": ctx.db_count("obs_points") == 0,
        "layers_loadable": ctx.layer("obs_points") is not None,
        "no_tracebacks": len(tbs) == 0,
    }
    status = "ok" if all(checks.values()) else "FAIL"
    return {"status": status, "checks": checks, "target": str(target),
            "about_db": str(description)}


def main() -> None:
    ns = parse_args()
    out = Path(ns.out)
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {"mode": ns.mode}

    def phase(name: str) -> None:
        (out / "phase.txt").write_text(name + "\n")

    try:
        # Report tools open HTML in the system browser; under Xvfb that can
        # spawn a helper that hangs. Neutralise it and record the URLs instead.
        opened_urls: list[str] = []
        QDesktopServices.openUrl = staticmethod(lambda url: (opened_urls.append(url.toString()), True)[1])

        phase("start_plugin")
        plugin = start_plugin()
        oracles = Oracles()
        oracles.install()
        mw = qgis.utils.iface.mainWindow()
        mw.resize(1600, 1000)
        mw.showMaximized()
        ctx = Context(plugin, qgis.utils.iface, out, oracles, default_selection=DEFAULT_SELECTION)
        ctx.wait(2000)

        if ns.mode in ("coverage", "outputs"):
            phase("copy_db")
            # Work on a writable copy so the shared fixture stays pristine.
            work_db = out / "work.sqlite"
            shutil.copy(ns.db, work_db)
            phase("open_database")
            open_database(plugin, str(work_db))
            phase("load_layers")
            report["fixture"] = load_layers(ctx, plugin, out)
            if ns.mode == "coverage":
                ctx.install_modal_reaper()  # outputs drives its modals to accept
                phase("sweep")
                report.update(run_coverage(ctx, plugin, out))
                report["opened_urls"] = opened_urls
            else:
                phase("outputs")
                report.update(run_outputs(ctx, plugin, out, opened_urls))
        elif ns.mode == "create_db":
            phase("create_db")
            report.update(run_create_db(ctx, plugin, out))
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
