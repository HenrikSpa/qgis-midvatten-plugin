"""GUI scenario: drive Interlab4Import to a FULL committed import, including
the "Assign obsids" dialog, and assert w_qual_lab rows grew.

The tutorial fixture's w_qual_lab is pre-seeded (via csv/w_qual_lab.csv,
not through this importer) with the SAME reports the tutorial .lab file
carries, including the report build.py deliberately leaves obsid-unresolved
("Unknown site 7" -> report 101210028881). So on the pristine fixture,
`skip_imported_reports` (default True) finds every report already imported
and there is nothing left to drive -- the ObsidAssignmentDialog never
appears. This scenario deletes those pre-seeded w_qual_lab rows from the
writable DB copy first, to reproduce the "first time importing this file"
state the docs describe, then drives the real workflow: click Start import,
wait for the (window-modal, so NOT QApplication.activeModalWidget()) "Assign
obsids" dialog to appear among the top-level widgets, fill every row via the
dialog's own public `set_obsid_value()`, click Apply, then assert the commit
landed in the DB.

`fill` mode's `interlab4_parse_and_select` only proves the Qt6 selectable-row
fix (parses the file, selects rows) -- it never clicks Start import, so it
never reaches this dialog.
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
from _bootstrap import run_scenario, visible_tool  # noqa: E402

from qgis.PyQt.QtCore import QTimer  # noqa: E402
from qgis.PyQt.QtWidgets import QApplication  # noqa: E402

LAB_PATH = "/wiki/tutorial_data/build/lab/interlab4_tutorial.lab"
FALLBACK_OBSID = "OW100"  # any obsid already present in obs_points
# The four reports this .lab file carries (tools/tutorial_data/build.py),
# pre-seeded into w_qual_lab via csv/w_qual_lab.csv so the fixture already
# has "real" data without depending on this importer.
SEEDED_REPORTS = ("10019035935", "100311010236", "1011010236", "101210028881")


def _wait_for_assign_dialog(retries=40):
    """Poll for the "Assign obsids" window (window-modal: not reachable via
    QApplication.activeModalWidget()) and drive it once found."""
    state = {"left": retries, "seen": False}

    def poll():
        dlg = next(
            (
                w
                for w in QApplication.topLevelWidgets()
                if w.isVisible() and w.windowTitle().startswith("Assign obsids")
            ),
            None,
        )
        if dlg is not None:
            state["seen"] = True
            filled = 0
            for visual_row in range(dlg.table.rowCount()):
                item = dlg.table.item(visual_row, 4)  # _COL_OBSID
                if item is not None and not item.text().strip():
                    dlg.set_obsid_value(visual_row, FALLBACK_OBSID)
                    filled += 1
            dlg.apply_button.click()
            state["filled"] = filled
            return
        state["left"] -= 1
        if state["left"] > 0:
            QTimer.singleShot(200, poll)

    QTimer.singleShot(300, poll)
    return state


def scenario(ctx, plugin, out):
    import midvatten.tools.utils.midvatten_utils as midvatten_utils

    results = []

    def record(name, passed, detail):
        results.append(
            {"id": name, "status": "ok" if passed else "FAIL", "detail": detail}
        )

    # Reproduce "first time importing this file": remove the pre-seeded rows
    # for these reports from the writable copy so skip_imported_reports
    # (left at its default True) has something new to parse, including the
    # deliberately obsid-unresolved one.
    work_db = str(out / "work.sqlite")
    conn = sqlite3.connect(work_db, timeout=30)
    placeholders = ",".join("?" for _ in SEEDED_REPORTS)
    with conn:
        conn.execute(
            f"DELETE FROM w_qual_lab WHERE report IN ({placeholders})", SEEDED_REPORTS
        )
    conn.close()
    before = ctx.db_count("w_qual_lab") or 0
    record(
        "seed_removed",
        True,
        f"w_qual_lab after removing {len(SEEDED_REPORTS)} seeded reports: {before}",
    )

    orig = midvatten_utils.select_files
    midvatten_utils.select_files = lambda *a, **k: [LAB_PATH]
    cp = ctx.oracles.checkpoint()
    dlg = None
    try:
        spec = next(s for s in plugin._actions_manifest if s.id == "import_interlab4")
        plugin._dispatch(spec)
        ctx.wait(1500)
        dlg = visible_tool("Interlab4Import")
        if dlg is None:
            record("open_dialog", False, "Interlab4Import window did not open")
        else:
            dlg.select_files_button.click()  # parse -> build table -> selectAll()
            ctx.wait(1500)
            parsed_keys = sorted((getattr(dlg, "all_lab_results", {}) or {}).keys())
            record(
                "parse",
                len(parsed_keys) > 0,
                f"{len(parsed_keys)} lablitteras parsed: {parsed_keys}",
            )

            state = _wait_for_assign_dialog()
            dlg.start_import_button.click()  # -> ObsidAssignmentDialog.exec() -> driven above -> commit
            ctx.wait(4000)
            record(
                "assign_dialog_driven",
                state["seen"],
                f"'Assign obsids' dialog seen={state['seen']}, rows filled={state.get('filled', 0)}",
            )
    finally:
        midvatten_utils.select_files = orig

    _, tbs = ctx.oracles.since(cp)
    after = ctx.db_count("w_qual_lab") or 0
    ok = after > before and not tbs
    record(
        "commit_grew_rows", ok, f"w_qual_lab {before}->{after}, tracebacks={len(tbs)}"
    )
    if dlg is not None:
        ctx.close_tools()

    summary = {}
    for r in results:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    return {
        "mode": "scenario_import_interlab4_commit",
        "results": results,
        "summary": summary,
    }


run_scenario(scenario)
