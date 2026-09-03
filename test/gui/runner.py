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
from qgis.core import Qgis, QgsApplication, QgsProject
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QDateTime, QTimer
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import QApplication, QPushButton, QWidget

import midvatten.tools.create_db_dialogs as create_db_dialogs


def _harness_dir() -> str:
    # QGIS runs this via `--code FILE`, an exec context where __file__ is NOT
    # defined, so the harness dir cannot be derived from __file__ (the wiki
    # runner hardcodes its dir for the same reason). The driver passes it via
    # --harness-dir; default is the Docker mount point for the Qt6 container.
    argv = sys.argv
    if "--harness-dir" in argv:
        return argv[argv.index("--harness-dir") + 1]
    return "/plugin/test/gui"


sys.path.insert(0, _harness_dir())
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

    # -- plots actually drew data (an empty figure must fail) ------------
    settingsdict = plugin.ms.settingsdict
    for action_id, layer, expr, settings in PLOT_CASES:
        try:
            ctx.clear_selections()
            ctx.select_some(layer, expr)
            ctx.activate(layer)
            before = {sip.unwrapinstance(w) for w in QApplication.topLevelWidgets()}
            saved = {k: settingsdict.get(k) for k in settings} if settings else {}
            if settings:
                settingsdict.update(settings)
            cp = ctx.oracles.checkpoint()
            dispatch(action_id)
            ctx.wait(2500)
            if saved:
                settingsdict.update(saved)
            _, tbs = ctx.oracles.since(cp)
            new = [w for w in QApplication.topLevelWidgets()
                   if sip.unwrapinstance(w) not in before and w.isVisible()
                   and w is not ctx.iface.mainWindow()]
            states = [_plot_state(w) for w in new]
            has_canvas = any(s[0] for s in states)
            drew = any(s[1] for s in states)
            if has_canvas:
                # matplotlib plot: an empty figure must fail
                record(action_id, drew and not tbs, f"mpl figure drew data={drew}, windows={len(new)}")
            else:
                # non-matplotlib (QPainter) plot, e.g. stratigraphy: judge by
                # "a window opened and nothing crashed" -- its drawing
                # correctness is covered by that plot's own unit tests.
                record(action_id, bool(new) and not tbs,
                       f"non-mpl plot, window opened={bool(new)}, no traceback={not tbs}")
            ctx.close_tools()
        except Exception:
            record(action_id, False, "exc: " + traceback.format_exc().splitlines()[-1])

    summary = {}
    for r in results:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    return {"results": results, "summary": summary, "opened_urls": opened_urls}


# Insert seconds-truncated twins (length 16, not 19) of existing OW100 instants
# so the duplicate-timestamp detection fires. offset 0 = redundant twin (same
# value), 5 = conflicting twin. Same SQL the wiki logger-editor scene uses.
_INSERT_DUPES = """
INSERT INTO w_levels_logger (obsid, date_time, head_cm, temp_degc, series_id)
SELECT obsid, substr(date_time, 1, 16), head_cm + ?, temp_degc, series_id
FROM (SELECT obsid, date_time, head_cm, temp_degc, series_id
      FROM w_levels_logger WHERE obsid = ? AND length(date_time) = 19
      ORDER BY date_time LIMIT 3 OFFSET ?)
"""


def run_loggereditor(ctx: Context, plugin, out: Path) -> dict:
    """Phase 5: the LoggerEditor's critical path -- load a series (plot draws),
    then the duplicate-timestamp workflow: insert seconds-truncated twins into
    the writable DB copy, reload, and assert the Resolve-duplicates banner
    appears and its dialog opens. Runs in its own container (LoggerEditor +
    plots in one process segfaults on teardown, GUI_AUTOMATION §4)."""
    import sqlite3

    results = []
    report_path = out / "gui_test_report.json"
    work_db = str(out / "work.sqlite")
    obsid, other = "OW100", "PW1001"
    dfrom, dto = "2010-12-10 10:10:00", "2012-06-26 10:00:00"

    def record(name, passed, detail):
        results.append({"id": name, "status": "ok" if passed else "FAIL", "detail": detail})
        report_path.write_text(json.dumps({"mode": "loggereditor", "partial": True, "results": results}, indent=2))

    spec = next(s for s in plugin._actions_manifest if s.id == "wlvlloggcalibrate")
    cp = ctx.oracles.checkpoint()
    plugin._dispatch(spec)
    ctx.wait(2000)
    tool = plugin._open_tools.get("wlvlloggcalibrate") or _visible_tool(ctx, "LoggerEditor")
    if tool is None:
        record("open_editor", False, "LoggerEditor did not open")
        return {"results": results, "summary": {"FAIL": 1}}
    tool.resize(1500, 900)

    def load(which, wait=4000):
        combo = tool.combobox_obsid
        idx = next((i for i in range(combo.count()) if combo.itemText(i).split(" ")[0] == which), -1)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        ctx.wait(wait)
        fmt = "yyyy-MM-dd HH:mm:ss"
        tool.from_date_time.setDateTime(QDateTime.fromString(dfrom, fmt))
        tool.to_date_time.setDateTime(QDateTime.fromString(dto, fmt))
        ctx.wait(800)

    # 1. load OW100 series -> the plot must draw the logger data
    load(obsid)
    has_canvas, drew = _plot_state(tool)
    _, tbs = ctx.oracles.since(cp)
    record("load_series", drew and not tbs, f"OW100 loaded, plot drew data={drew}, canvas={has_canvas}")

    # 2. insert duplicate rows into the writable copy (drop the unique index it
    #    would otherwise forbid), then reload the editor to re-read the table.
    try:
        conn = sqlite3.connect(work_db, timeout=30)
        with conn:
            conn.execute("DROP INDEX IF EXISTS uq_w_levels_logger_obsid_dt")
        with conn:
            conn.execute(_INSERT_DUPES, (0.0, obsid, 4000))
            conn.execute(_INSERT_DUPES, (5.0, obsid, 12000))
        conn.close()
        dupes = ctx.db_scalar(
            f"SELECT count(*) FROM w_levels_logger WHERE obsid='{obsid}' AND length(date_time)<>19")
        record("insert_duplicates", (dupes or 0) > 0, f"{dupes} short-timestamp rows inserted")
    except Exception:
        record("insert_duplicates", False, "exc: " + traceback.format_exc().splitlines()[-1])
        dupes = 0

    cp2 = ctx.oracles.checkpoint()
    load(other, 3000)
    load(obsid)

    # 3. the Resolve-duplicates banner/button must appear
    btn = next((b for b in tool.findChildren(QPushButton)
                if b.text().startswith("Resolve duplicates")), None)
    record("duplicate_banner", btn is not None and btn.isVisible(),
           f"resolve button present={btn is not None and (btn.isVisible() if btn else False)}")

    # 4. clicking it opens the Resolve-duplicate-timestamps dialog
    if btn is not None and btn.isVisible():
        btn.click()
        ctx.wait(1200)
        dlg = next((w for w in QApplication.topLevelWidgets()
                    if w.isVisible() and w.windowTitle().startswith("Resolve duplicate timestamps")), None)
        _, tbs2 = ctx.oracles.since(cp2)
        record("resolve_dialog_opens", dlg is not None and not tbs2,
               f"dialog opened={dlg is not None}")
        if dlg is not None:
            ctx.grab(dlg, "loggereditor_resolve_dialog")
            dlg.close()
            ctx.wait(300)
    ctx.close_tools()

    summary = {}
    for r in results:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    return {"results": results, "summary": summary}


def run_controls(ctx: Context, plugin, out: Path) -> dict:
    """Group C: dispatch each action, exercise every control in the window/modal
    it opens (toggle checkboxes, cycle combos, walk tabs), and fail on any
    traceback or Critical. Catches controls that crash on interaction, which the
    plain coverage sweep (window merely opened) misses."""
    results = []
    report_path = out / "gui_test_report.json"
    specs = list(plugin._actions_manifest)

    # A reaper that EXERCISES a modal before dismissing it (the coverage reaper
    # only dismisses). Re-entrancy guarded: exercising walks tabs with waits, so
    # the 900ms timer can fire again mid-walk.
    busy = {"in": False}

    def reap():
        if busy["in"]:
            return
        dlg = QApplication.activeModalWidget()
        if dlg is not None:
            busy["in"] = True
            try:
                ctx.exercise_controls(dlg)
            except Exception:
                pass
            ctx._dismiss(dlg)
            busy["in"] = False

    timer = QTimer()
    timer.timeout.connect(reap)
    timer.start(900)

    for i, spec in enumerate(specs):
        (out / "progress.txt").write_text(f"{i + 1}/{len(specs)} {spec.id}\n")
        ctx._prepare(spec)
        cp = ctx.oracles.checkpoint()
        before = {sip.unwrapinstance(w) for w in QApplication.topLevelWidgets()}
        derr = None
        try:
            plugin._dispatch(spec)
        except Exception:
            derr = traceback.format_exc().strip().splitlines()[-1]
        ctx.wait(1500)

        window = None
        persistent = plugin._open_tools.get(spec.id)
        if isinstance(persistent, QWidget) and persistent.isVisible():
            window = persistent
        else:
            new = [w for w in QApplication.topLevelWidgets()
                   if sip.unwrapinstance(w) not in before and w.isVisible()
                   and w is not ctx.iface.mainWindow()]
            if new:
                window = max(new, key=lambda w: w.width() * w.height())
        tally = None
        if window is not None:
            try:
                tally = ctx.exercise_controls(window)
            except Exception:
                pass
            ctx.wait(300)

        msgs, tbs = ctx.oracles.since(cp)
        crit = [m for m in msgs if m["level"] >= int(Qgis.Critical)]
        if derr or tbs:
            status, detail = "FAIL", derr or tbs[-1]["text"].splitlines()[-1]
        elif crit:
            status, detail = "FAIL", "Critical: " + crit[-1]["text"].strip().replace("\n", " ")[:150]
        else:
            status = "ok"
            detail = f"exercised {tally}" if tally else "no window (callback/blocked)"
        results.append({"id": spec.id, "menu": spec.menu, "status": status, "detail": detail})
        report_path.write_text(json.dumps({"mode": "controls", "partial": True, "results": results}, indent=2))
        ctx.close_tools()
        ctx.clear_selections()

    timer.stop()
    summary = {}
    for r in results:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    return {"results": results, "summary": summary}


def run_generic_actions(ctx: Context, plugin, out: Path, menu_title: str = "midvatten") -> dict:
    """Phase 10 (cross-plugin PoC): drive a plugin the GENERIC way -- discover
    its actions from the QGIS menu bar and trigger() each -- with NO dependency
    on Midvatten's private `_actions_manifest`. This is the reusable core for
    generalizing the harness to the other ~/dev plugins: only "which menu" is
    plugin-specific. Proven here against Midvatten's own menu."""
    def leaf_actions(menu):
        found = []
        for act in menu.actions():
            if act.isSeparator():
                continue
            sub = act.menu()
            if sub is not None:
                found.extend(leaf_actions(sub))
            elif act.text():
                found.append(act)
        return found

    menubar = ctx.iface.mainWindow().menuBar()
    plugin_menu = next((a.menu() for a in menubar.actions()
                        if a.menu() is not None and menu_title in a.text().lower()), None)
    if plugin_menu is None:
        return {"results": [], "summary": {"FAIL": 1},
                "error": f"no menu matching {menu_title!r} in the menu bar"}

    actions = leaf_actions(plugin_menu)
    ctx.install_modal_reaper()  # dismiss any modal a triggered action opens
    results = []
    report_path = out / "gui_test_report.json"
    for i, act in enumerate(actions):
        (out / "progress.txt").write_text(f"{i + 1}/{len(actions)} {act.text()}\n")
        # Minimal generic preconditions: a broadly-useful selection.
        ctx.clear_selections()
        if ctx.default_selection is not None:
            ctx.select_some(*ctx.default_selection)
            ctx.activate(ctx.default_selection[0])
        cp = ctx.oracles.checkpoint()
        try:
            act.trigger()
        except Exception:
            derr = traceback.format_exc().strip().splitlines()[-1]
        else:
            derr = None
        ctx.wait(1200)
        _, tbs = ctx.oracles.since(cp)
        crit = [m for m in ctx.oracles.since(cp)[0] if m["level"] >= int(Qgis.Critical)]
        status = "FAIL" if (derr or tbs) else ("blocked" if crit else "ok")
        detail = derr or (tbs[-1]["text"].splitlines()[-1] if tbs else
                          ("warn: " + crit[-1]["text"][:80] if crit else "triggered, no traceback"))
        results.append({"id": act.text().replace("&", ""), "status": status, "detail": detail})
        report_path.write_text(json.dumps({"mode": "generic_actions", "partial": True, "results": results}, indent=2))
        ctx.close_tools()
        ctx.clear_selections()

    summary = {}
    for r in results:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    return {"results": results, "summary": summary, "n_actions_discovered": len(actions)}


def run_dbutils(ctx: Context, plugin, out: Path) -> dict:
    """Phase 6: assert the DB-management / utility callback actions' real side
    effects (not just that dispatch returned). Backup/view/vacuum/stats run on
    the writable tutorial copy; add_non_essential_tables runs on a FRESH empty
    DB (on the full fixture it correctly fails -- the tables already exist)."""
    results = []
    report_path = out / "gui_test_report.json"

    def record(name, passed, detail):
        results.append({"id": name, "status": "ok" if passed else "FAIL", "detail": detail})
        report_path.write_text(json.dumps({"mode": "dbutils", "partial": True, "results": results}, indent=2))

    def dispatch(action_id):
        plugin._dispatch(next(s for s in plugin._actions_manifest if s.id == action_id))

    def obj_exists(kind, name):
        return (ctx.db_scalar(
            f"SELECT count(*) FROM sqlite_master WHERE type='{kind}' AND name='{name}'") or 0) > 0

    # -- zip_db: writes exactly one new backup .zip next to the open DB ---
    try:
        before = set(out.glob("*.zip"))
        cp = ctx.oracles.checkpoint()
        dispatch("zip_db")
        ctx.wait(1000)
        _, tbs = ctx.oracles.since(cp)
        new_zips = set(out.glob("*.zip")) - before
        record("zip_db", len(new_zips) == 1 and not tbs, f"{len(new_zips)} new .zip written")
        for z in new_zips:
            z.unlink()
    except Exception:
        record("zip_db", False, "exc: " + traceback.format_exc().splitlines()[-1])

    # -- add_view_obs_points_lines: creates view_obs_points / view_obs_lines --
    try:
        cp = ctx.oracles.checkpoint()
        dispatch("add_view_obs_points_lines")
        ctx.wait(800)
        _, tbs = ctx.oracles.since(cp)
        ok = obj_exists("view", "view_obs_points") and obj_exists("view", "view_obs_lines") and not tbs
        record("add_view_obs_points_lines", ok, f"view_obs_points exists={obj_exists('view', 'view_obs_points')}")
    except Exception:
        record("add_view_obs_points_lines", False, "exc: " + traceback.format_exc().splitlines()[-1])

    # -- vacuum_db: runs, DB stays queryable ----------------------------
    for action_id in ("vacuum_db", "refresh_spatialite_stats", "calculate_db_table_rows"):
        try:
            rows_before = ctx.db_count("obs_points")
            cp = ctx.oracles.checkpoint()
            dispatch(action_id)
            ctx.wait(1200)
            _, tbs = ctx.oracles.since(cp)
            rows_after = ctx.db_count("obs_points")
            crit = [m for m in ctx.oracles.since(cp)[0] if m["level"] >= int(Qgis.Critical)]
            ok = not tbs and not crit and rows_after == rows_before
            record(action_id, ok, f"ran, obs_points {rows_before}->{rows_after}, no traceback={not tbs}")
        except Exception:
            record(action_id, False, "exc: " + traceback.format_exc().splitlines()[-1])

    # (add_non_essential_tables was removed from the menu -- the tables it made
    # are now in create_db.sql, so it only ever errored on modern DBs. The
    # function is kept for midv_addons but is no longer a dispatchable action.)

    summary = {}
    for r in results:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    return {"results": results, "summary": summary}


def _create_fresh_db(ctx: Context, plugin, out: Path) -> tuple[Path, bool]:
    """Drive the real New-SpatiaLite-DB dialog to build a fresh empty database,
    set it as the active DB, and load its default layers. Returns (path, driven).

    The dialog is driven like a user -- the native save-picker is patched and the
    dialog's own Browse button clicked, then OK pressed -- never writing its
    private widgets. No global reaper: this drives its one modal to acceptance."""
    target = out / f"created_{os.getpid()}.sqlite"
    for p in out.glob("created_*.sqlite"):
        p.unlink()
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

    QTimer.singleShot(500, drive)
    spec = next(s for s in plugin._actions_manifest if s.id == "new_db")
    try:
        plugin._dispatch(spec)  # blocks in dialog.exec() until drive() accepts
    finally:
        ctx.wait(2500)
        create_db_dialogs.QFileDialog.getSaveFileName = orig_picker

    # new_db() set the freshly-built DB as active; point the harness's connection
    # at it explicitly, then load the default + data-domain layers from it.
    open_database(plugin, str(target))
    ctx.wait(500)
    for action_id in ("add_midvatten_layers", "load_data_domains"):
        load_spec = next((s for s in plugin._actions_manifest if s.id == action_id), None)
        if load_spec is not None:
            plugin._dispatch(load_spec)
            ctx.wait(1200)
    return target, driven["ok"]


def run_create_db(ctx: Context, plugin, out: Path) -> dict:
    """Group A (create half): build a fresh DB and assert its schema."""
    cp = ctx.oracles.checkpoint()
    target, driven = _create_fresh_db(ctx, plugin, out)
    _, tbs = ctx.oracles.since(cp)
    description = ctx.db_scalar("SELECT description FROM about_db LIMIT 1")
    checks = {
        "dialog_driven_and_accepted": driven,
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


def run_fill(ctx: Context, plugin, out: Path, csv_dir: Path) -> dict:
    """Group A (fill half): create a fresh empty DB, then drive the real general
    CSV importer to load tutorial CSVs into it and assert the row counts.

    Each import means two nested modals -- the file-load sub-dialog, then the
    row-drop YesNo confirmation -- both of which must be ACCEPTED (a reject
    cancels the import), so a smart accept-driver runs for the duration of the
    import instead of the reject-reaper. Column mapping is automatic because the
    tutorial CSV headers equal the DB column names (import_general_csv_gui.py
    prefills a ColumnEntry whose db_column matches a file header)."""
    results = []
    report_path = out / "gui_test_report.json"

    def record(name, passed, detail):
        results.append({"id": name, "status": "ok" if passed else "FAIL", "detail": detail})
        report_path.write_text(json.dumps({"mode": "fill", "partial": True, "results": results}, indent=2))

    cp0 = ctx.oracles.checkpoint()
    target, driven = _create_fresh_db(ctx, plugin, out)
    record("create_fresh_db", driven and target.exists() and ctx.db_count("obs_points") == 0,
           f"created {target.name}, obs_points={ctx.db_count('obs_points')}")

    import midvatten.tools.utils.midvatten_utils as midvatten_utils

    def start_accept_driver():
        """Accept whatever modal comes up during an import: the file-load
        sub-dialog (after driving its Browse via the patched picker) then the
        YesNo row-drop confirmation. Returns a stop() so its self-rearming timer
        does not linger and swallow the NEXT import's file-load dialog."""
        control = {"active": True}

        def drive():
            if not control["active"]:
                return
            dlg = QApplication.activeModalWidget()
            if dlg is not None:
                cls = type(dlg).__name__
                if "FileLoad" in cls or "CsvFile" in cls:
                    for b in dlg.findChildren(QPushButton):
                        if "rowse" in b.text().lower():
                            b.click()
                            break
                dlg.accept()
            QTimer.singleShot(150, drive)

        QTimer.singleShot(300, drive)
        return lambda: control.__setitem__("active", False)

    # obs_points first (root table, no obsid FK ask), then w_levels (references it).
    for table, csv_name, min_rows in [("obs_points", "obs_points.csv", 60),
                                      ("w_levels", "w_levels.csv", 1000)]:
        try:
            csv_path = str(csv_dir / csv_name)
            before = ctx.db_count(table) or 0
            orig = midvatten_utils.select_files
            midvatten_utils.select_files = lambda *a, **k: [csv_path]
            cp = ctx.oracles.checkpoint()
            spec = next(s for s in plugin._actions_manifest if s.id == "import_csv")
            plugin._dispatch(spec)
            dlg = _visible_tool(ctx, "GeneralCsvImportGui")
            if dlg is None:
                record(f"import_{table}", False, "importer window did not open")
                continue
            stop = start_accept_driver()
            dlg.select_file_button.click()   # -> file-load modal -> accepted by driver
            ctx.wait(2500)
            dlg.table_chooser.import_method = table   # auto-maps matching columns
            ctx.wait(600)
            dlg.start_import_button.click()  # -> YesNo confirm -> accepted by driver
            ctx.wait(3000)
            stop()
            midvatten_utils.select_files = orig
            _, tbs = ctx.oracles.since(cp)
            after = ctx.db_count(table) or 0
            ok = after - before >= min_rows and not tbs
            record(f"import_{table}", ok, f"{table} {before}->{after} rows (>= {min_rows})")
            ctx.close_tools()
        except Exception:
            midvatten_utils.select_files = orig
            record(f"import_{table}", False, "exc: " + traceback.format_exc().splitlines()[-1])

    # -- import_logger (DiverOffice .MON -> w_levels_logger + a new series) ---
    try:
        logger_path = str(csv_dir.parent / "logger" / "OW100_diveroffice.MON")
        wll_before = ctx.db_count("w_levels_logger") or 0
        series_before = ctx.db_count("w_logger_series") or 0
        orig = midvatten_utils.select_files
        midvatten_utils.select_files = lambda *a, **k: [logger_path]
        cp = ctx.oracles.checkpoint()
        spec = next(s for s in plugin._actions_manifest if s.id == "import_logger")
        plugin._dispatch(spec)
        dlg = _visible_tool(ctx, "LoggerImport")
        if dlg is None:
            record("import_logger", False, "LoggerImport window did not open")
        else:
            dlg.format_combo.setCurrentText("DiverOffice")
            ctx.wait(300)
            stop = start_accept_driver()  # dismiss the progress/info dialogs
            dlg.select_files_button.click()
            ctx.wait(1200)
            dlg.confirm_names.checked = False  # OW100 exists -> resolve silently
            dlg.start_import_button.click()
            ctx.wait(4000)
            stop()
            ctx.close_tools()
        midvatten_utils.select_files = orig
        _, tbs = ctx.oracles.since(cp)
        wll_after = ctx.db_count("w_levels_logger") or 0
        series_after = ctx.db_count("w_logger_series") or 0
        ok = wll_after > wll_before and series_after > series_before and not tbs
        record("import_logger", ok,
               f"w_levels_logger {wll_before}->{wll_after}, w_logger_series {series_before}->{series_after}")
    except Exception:
        midvatten_utils.select_files = orig
        record("import_logger", False, "exc: " + traceback.format_exc().splitlines()[-1])

    # -- import_interlab4: parse the .lab and confirm rows are SELECTABLE ----
    # (the table items must carry ItemIsEnabled, else selectAll() selects
    # nothing on Qt6 and the importer can't read a selection -- a Qt6 bug).
    try:
        lab_path = str(csv_dir.parent / "lab" / "interlab4_tutorial.lab")
        orig = midvatten_utils.select_files
        midvatten_utils.select_files = lambda *a, **k: [lab_path]
        cp = ctx.oracles.checkpoint()
        spec = next(s for s in plugin._actions_manifest if s.id == "import_interlab4")
        plugin._dispatch(spec)
        dlg = _visible_tool(ctx, "Interlab4Import")
        parsed = selected = 0
        if dlg is not None:
            dlg.skip_imported_reports.setChecked(False)
            dlg.select_files_button.click()  # parse -> build table -> selectAll()
            ctx.wait(1500)
            parsed = len(getattr(dlg, "all_lab_results", {}) or {})
            table = getattr(getattr(dlg, "metadata_filter", None), "table", None)
            if table is not None:
                selected = len({it.row() for it in table.selectedItems()})
            ctx.close_tools()
        midvatten_utils.select_files = orig
        _, tbs = ctx.oracles.since(cp)
        ok = parsed > 0 and selected > 0 and not tbs
        record("interlab4_parse_and_select", ok,
               f"parsed {parsed} lablitteras, {selected} rows selectable (Qt6 flag fix)")
    except Exception:
        midvatten_utils.select_files = orig
        record("interlab4_parse_and_select", False, "exc: " + traceback.format_exc().splitlines()[-1])

    # idempotency: re-importing obs_points must not duplicate rows.
    try:
        csv_path = str(csv_dir / "obs_points.csv")
        before = ctx.db_count("obs_points") or 0
        orig = midvatten_utils.select_files
        midvatten_utils.select_files = lambda *a, **k: [csv_path]
        spec = next(s for s in plugin._actions_manifest if s.id == "import_csv")
        plugin._dispatch(spec)
        dlg = _visible_tool(ctx, "GeneralCsvImportGui")
        if dlg is not None:
            stop = start_accept_driver()
            dlg.select_file_button.click()
            ctx.wait(2500)
            dlg.table_chooser.import_method = "obs_points"
            ctx.wait(600)
            dlg.start_import_button.click()
            ctx.wait(3000)
            stop()
            ctx.close_tools()
        midvatten_utils.select_files = orig
        after = ctx.db_count("obs_points") or 0
        record("import_obs_points_idempotent", after == before, f"obs_points {before}->{after} (no dupes)")
    except Exception:
        midvatten_utils.select_files = orig
        record("import_obs_points_idempotent", False, "exc: " + traceback.format_exc().splitlines()[-1])

    _, tbs_total = ctx.oracles.since(cp0)
    summary = {}
    for r in results:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    return {"results": results, "summary": summary, "target": str(target),
            "total_tracebacks": len(tbs_total)}


def _visible_tool(ctx: Context, class_name: str):
    """Return the visible top-level widget whose class name matches, else None."""
    for w in QApplication.topLevelWidgets():
        if type(w).__name__ == class_name and w.isVisible():
            return w
    return None


def _plot_state(widget) -> tuple[bool, bool]:
    """Inspect a plot window: returns (has_mpl_canvas, drew_data).

    has_mpl_canvas is True if a matplotlib FigureCanvas (child with both .figure
    and .draw) is present; drew_data is True if any of its axes drew lines,
    collections, patches or images. The stratigraphy plot renders with a custom
    QPainter.paintEvent instead of matplotlib, so it has no canvas -- there
    drew_data cannot be introspected and the caller judges by "opened cleanly"."""
    has_canvas = False
    for child in widget.findChildren(QWidget):
        fig = getattr(child, "figure", None)
        if fig is not None and hasattr(child, "draw") and hasattr(fig, "get_axes"):
            has_canvas = True
            for ax in fig.get_axes():
                if ax.lines or ax.collections or ax.patches or getattr(ax, "images", []):
                    return True, True
    return has_canvas, False


# obsid selections + settings that make each plot draw real data (from the wiki
# tutorial figures). Settings are written the way the Settings dock's slots do.
PLOT_CASES = [
    ("plot_timeseries", "obs_points", "obsid IN ('Pz0903','Pz0915','Pz0916')",
     {"tstable": "w_levels", "tscolumn": "level_masl", "tsdotmarkers": 0, "tsstepplot": 0}),
    ("plot_xy", "obs_lines", "obsid IN ('S1','S2','S3')",
     {"xytable": "seismic_data", "xy_xcolumn": "length", "xy_y1column": "ground",
      "xy_y2column": "bedrock", "xy_y3column": "", "xydotmarkers": 0}),
    ("plot_stratigraphy", "obs_points", "obsid IN ('Pz0903','Pz0905','Pz0917','Pz0918')", None),
    ("plot_piper", "obs_points", "obsid IN ('OW100','PW1001','PW1002','Pz0905','Pz0917','Pz1016','RG 1')",
     {"piper_cl": "Cl", "piper_hco3": "Alcalinity, HCO3", "piper_so4": "SO4", "piper_na": "Na",
      "piper_k": "K", "piper_ca": "Ca", "piper_mg": "Mg", "piper_markers": "type"}),
]


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

        if ns.mode in ("coverage", "outputs", "controls", "loggereditor", "dbutils", "generic_actions"):
            phase("copy_db")
            # Work on a writable copy so the shared fixture stays pristine.
            work_db = out / "work.sqlite"
            shutil.copy(ns.db, work_db)
            phase("open_database")
            open_database(plugin, str(work_db))
            phase("load_layers")
            report["fixture"] = load_layers(ctx, plugin, out)
            if ns.mode == "coverage":
                ctx.install_modal_reaper()  # outputs/controls install their own
                phase("sweep")
                report.update(run_coverage(ctx, plugin, out))
                report["opened_urls"] = opened_urls
            elif ns.mode == "controls":
                phase("controls")
                report.update(run_controls(ctx, plugin, out))
            elif ns.mode == "loggereditor":
                phase("loggereditor")
                report.update(run_loggereditor(ctx, plugin, out))
            elif ns.mode == "dbutils":
                phase("dbutils")
                report.update(run_dbutils(ctx, plugin, out))
            elif ns.mode == "generic_actions":
                phase("generic_actions")
                report.update(run_generic_actions(ctx, plugin, out))
            else:
                phase("outputs")
                report.update(run_outputs(ctx, plugin, out, opened_urls))
        elif ns.mode == "create_db":
            phase("create_db")
            report.update(run_create_db(ctx, plugin, out))
        elif ns.mode == "fill":
            phase("fill")
            csv_dir = Path(ns.db).parent / "csv"
            report.update(run_fill(ctx, plugin, out, csv_dir))
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
