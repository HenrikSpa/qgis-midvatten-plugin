"""GUI scenario: prove wlvlcalculate (CalculateLevel) and calculate_aveflow
(CalculateAveflow) actually MUTATE the writable DB copy, not merely that
their dialog opens (which is all `coverage`/`controls` check).

Both dialogs call `self.exec()` from `show()`, so `plugin._dispatch(spec)`
blocks the calling thread until the dialog closes. A QTimer scheduled before
the dispatch grabs `QApplication.activeModalWidget()` once it appears, drives
the real widgets (date range + the "all"/"selected" button), and the click
handler itself closes the dialog -- exactly the path a user takes.

- wlvlcalculate: NULL an existing w_levels.level_masl value first, run
  "Calculate all", assert it was recomputed to h_toc - meas.
- calculate_aveflow: delete the existing Aveflow rows for PW1001 (which were
  derived from its Accvol readings), run "Calculate selected" with PW1001
  selected, assert Aveflow rows were regenerated.
"""

import sqlite3
import sys


def _scenarios_dir() -> str:
    # __file__ is NOT defined in a `qgis --code FILE` exec context (see
    # runner.py's _harness_dir()), so this cannot use Path(__file__).
    argv = sys.argv
    if "--harness-dir" in argv:
        return argv[argv.index("--harness-dir") + 1] + "/scenarios"
    return "/plugin/test/gui/scenarios"


sys.path.insert(0, _scenarios_dir())
from _bootstrap import run_scenario  # noqa: E402

from qgis.PyQt.QtCore import QDateTime, QTimer  # noqa: E402
from qgis.PyQt.QtWidgets import QApplication  # noqa: E402

WIDE_FROM = "2000-01-01 00:00:00"
WIDE_TO = "2099-01-01 00:00:00"
FMT = "yyyy-MM-dd HH:mm:ss"


def _wait_for_modal(class_name, drive, retries=40):
    """Poll every 200ms (up to ~8s) for a modal of the given class, then call
    drive(dlg). Self-reschedules; never blocks the event loop."""
    state = {"left": retries}

    def poll():
        dlg = QApplication.activeModalWidget()
        if dlg is not None and type(dlg).__name__ == class_name:
            drive(dlg)
            return
        state["left"] -= 1
        if state["left"] > 0:
            QTimer.singleShot(200, poll)

    QTimer.singleShot(300, poll)


def scenario(ctx, plugin, out):
    results = []

    def record(name, passed, detail):
        results.append(
            {"id": name, "status": "ok" if passed else "FAIL", "detail": detail}
        )

    work_db = str(out / "work.sqlite")

    # ---------------------------------------------------------------
    # 1. wlvlcalculate: NULL one level_masl, recompute, assert it changed.
    # ---------------------------------------------------------------
    try:
        conn = sqlite3.connect(work_db, timeout=30)
        row = conn.execute(
            "SELECT obsid, date_time, meas, level_masl FROM w_levels "
            "WHERE level_masl IS NOT NULL AND meas IS NOT NULL LIMIT 1"
        ).fetchone()
        if row is None:
            record(
                "wlvlcalculate", False, "no w_levels row with level_masl to null out"
            )
        else:
            obsid, date_time, meas, old_level_masl = row
            with conn:
                conn.execute(
                    "UPDATE w_levels SET level_masl = NULL WHERE obsid = ? AND date_time = ?",
                    (obsid, date_time),
                )
            conn.close()

            nulled = ctx.db_scalar(
                f"SELECT level_masl FROM w_levels WHERE obsid='{obsid}' AND date_time='{date_time}'"
            )
            record(
                "null_seed",
                nulled is None,
                f"{obsid}@{date_time} level_masl nulled (was {old_level_masl})",
            )

            def drive_calc_level(dlg):
                dlg.from_date_time.setDateTime(QDateTime.fromString(WIDE_FROM, FMT))
                dlg.to_date_time.setDateTime(QDateTime.fromString(WIDE_TO, FMT))
                dlg.overwrite_prev.setChecked(False)  # only fill the NULL we just made
                dlg.push_button_all.click()  # -> calc() -> UPDATE ... -> self.close()

            ctx.activate("obs_points")
            cp = ctx.oracles.checkpoint()
            _wait_for_modal("CalculateLevel", drive_calc_level)
            spec = next(s for s in plugin._actions_manifest if s.id == "wlvlcalculate")
            plugin._dispatch(spec)  # blocks until the driver closes the dialog
            ctx.wait(1000)
            _, tbs = ctx.oracles.since(cp)

            recomputed = ctx.db_scalar(
                f"SELECT level_masl FROM w_levels WHERE obsid='{obsid}' AND date_time='{date_time}'"
            )
            ok = (
                recomputed is not None
                and abs(float(recomputed) - float(old_level_masl)) < 1e-6
                and not tbs
            )
            record(
                "wlvlcalculate",
                ok,
                f"{obsid}@{date_time} level_masl NULL -> {recomputed} (expected {old_level_masl}), "
                f"tracebacks={len(tbs)}",
            )
    except Exception:
        import traceback

        record(
            "wlvlcalculate", False, "exc: " + traceback.format_exc().splitlines()[-1]
        )

    # ---------------------------------------------------------------
    # 2. calculate_aveflow: delete PW1001's Aveflow rows, recompute from
    #    Accvol, assert they were regenerated.
    # ---------------------------------------------------------------
    try:
        obsid = "PW1001"
        deleted = (
            ctx.db_scalar(
                f"SELECT count(*) FROM w_flow WHERE obsid='{obsid}' AND flowtype='Aveflow'"
            )
            or 0
        )
        conn = sqlite3.connect(work_db, timeout=30)
        with conn:
            conn.execute(
                "DELETE FROM w_flow WHERE obsid = ? AND flowtype = 'Aveflow'", (obsid,)
            )
        conn.close()
        after_delete = (
            ctx.db_scalar(
                f"SELECT count(*) FROM w_flow WHERE obsid='{obsid}' AND flowtype='Aveflow'"
            )
            or 0
        )
        record(
            "delete_seed",
            after_delete == 0,
            f"{deleted} Aveflow rows deleted for {obsid}",
        )

        def drive_calc_aveflow(dlg):
            dlg.from_date_time.setDateTime(QDateTime.fromString(WIDE_FROM, FMT))
            dlg.to_date_time.setDateTime(QDateTime.fromString(WIDE_TO, FMT))
            dlg.push_button_selected.click()  # -> calc_aveflow() -> general_import -> self.close()

        ctx.clear_selections()
        ctx.select_some("obs_points", f"obsid='{obsid}'")
        ctx.activate("obs_points")
        cp2 = ctx.oracles.checkpoint()
        _wait_for_modal("CalculateAveflow", drive_calc_aveflow)
        spec = next(s for s in plugin._actions_manifest if s.id == "calculate_aveflow")
        plugin._dispatch(spec)  # blocks until the driver closes the dialog
        ctx.wait(2000)
        _, tbs2 = ctx.oracles.since(cp2)

        regenerated = (
            ctx.db_scalar(
                f"SELECT count(*) FROM w_flow WHERE obsid='{obsid}' AND flowtype='Aveflow'"
            )
            or 0
        )
        ok = regenerated > 0 and not tbs2
        record(
            "calculate_aveflow",
            ok,
            f"{obsid} Aveflow rows 0 -> {regenerated} (originally {deleted}), tracebacks={len(tbs2)}",
        )
    except Exception:
        import traceback

        record(
            "calculate_aveflow",
            False,
            "exc: " + traceback.format_exc().splitlines()[-1],
        )

    ctx.close_tools()
    ctx.clear_selections()

    summary = {}
    for r in results:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    return {"mode": "scenario_calc_mutation", "results": results, "summary": summary}


run_scenario(scenario)
