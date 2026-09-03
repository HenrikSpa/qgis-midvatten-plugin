"""GUI scenario: drive ExportToFieldLogger to completion for BOTH output
formats on the EPSG:3006 tutorial fixture.

- FieldLogger (CSV): obs_points/obs_lines coordinates are read via
  `Transform(geometry, 4326)` in the export SQL regardless of the source
  SRID, so this is expected to always succeed on this fixture.
- FieldForm (.json): same coordinate path, so it is ALSO expected to succeed
  here -- the "FieldForm refuses non-WGS84" behaviour (see
  tools/export_fieldlogger.py's `validate_latlons`, exercised by
  test_export_fieldlogger.py) only bites when locations come from a
  non-WGS84 QGIS *layer* (`obs_from_vlayer`), not from `obs_points` via SQL.
  This scenario uses the default `obs_from_obs_points` source and records
  the ACTUAL outcome rather than assuming either result.

`coverage`/`controls` only prove the window opens; this proves an actual
file is written with real content (or, if refused, that the refusal is the
documented UsageError and not a traceback).
"""

import sys
from pathlib import Path


def _scenarios_dir() -> str:
    # __file__ is NOT defined in a `qgis --code FILE` exec context (see
    # runner.py's _harness_dir()), so this cannot use Path(__file__).
    argv = sys.argv
    if "--harness-dir" in argv:
        return argv[argv.index("--harness-dir") + 1] + "/scenarios"
    return "/plugin/test/gui/scenarios"


sys.path.insert(0, _scenarios_dir())
from _bootstrap import run_scenario, visible_tool  # noqa: E402

from qgis.PyQt import QtWidgets  # noqa: E402


def scenario(ctx, plugin, out):
    results = []

    def record(name, passed, detail):
        results.append(
            {"id": name, "status": "ok" if passed else "FAIL", "detail": detail}
        )

    spec = next(s for s in plugin._actions_manifest if s.id == "export_fieldlogger")
    plugin._dispatch(spec)
    ctx.wait(1500)
    dlg = visible_tool("ExportToFieldLogger")
    if dlg is None:
        record("open_dialog", False, "ExportToFieldLogger window did not open")
        return {
            "mode": "scenario_export_fieldlogger_roundtrip",
            "results": results,
            "summary": {"FAIL": 1},
        }
    record("open_dialog", True, "opened")

    orig_save = QtWidgets.QFileDialog.getSaveFileName

    def populate_locations():
        # ParameterGroup.locations_sublocations_obsids is populated purely
        # from its own obsid-list widget (never auto-filled from
        # obs_from_obs_points), so `restore_default_settings()` alone yields
        # an empty locations box and organize_for_export() skips every
        # group. "Paste selected ids" reads the current obs_points
        # selection -- give it one, then click it for every group, the way
        # a user with a real selection would.
        ctx.clear_selections()
        ctx.select_some(
            "obs_points", "obsid IN ('OW100','PW1001','Pz0917','Pz0918','Pz1005')"
        )
        ctx.activate("obs_points")
        for group in dlg.parameter_groups:
            group.paste_from_selection_button.click()
        ctx.wait(300)

    def do_export(target_path: Path):
        target_path.unlink(missing_ok=True)
        QtWidgets.QFileDialog.getSaveFileName = staticmethod(
            lambda **k: (str(target_path), "")
        )
        cp = ctx.oracles.checkpoint()
        try:
            dlg.export_button.click()
            ctx.wait(2000)
        finally:
            QtWidgets.QFileDialog.getSaveFileName = orig_save
        msgs, tbs = ctx.oracles.since(cp)
        return msgs, tbs

    # -- FieldLogger CSV: obs_points source, default settings -----------
    dlg.export_as_fieldlogger.setChecked(True)
    dlg.parameter_browser.use_fieldlogger()
    dlg.obs_from_obs_points.setChecked(True)
    dlg.restore_default_settings()
    ctx.wait(500)
    populate_locations()
    fl_path = out / "export_fieldlogger.csv"
    msgs, tbs = do_export(fl_path)
    if fl_path.exists():
        content = fl_path.read_text(encoding="utf-8", errors="replace")
        ok = len(content) > 0 and "OW100" in content and not tbs
        record(
            "export_fieldlogger_csv",
            ok,
            f"{len(content)} bytes, has OW100={'OW100' in content}, tracebacks={len(tbs)}",
        )
    else:
        record(
            "export_fieldlogger_csv",
            False,
            f"no file written, tracebacks={len(tbs)}, messages={[m['text'][:120] for m in msgs]}",
        )

    # -- FieldForm json: same source, default FieldForm settings ---------
    dlg.export_as_fieldform.setChecked(True)
    dlg.parameter_browser.use_fieldform()
    dlg.restore_default_settings()
    ctx.wait(500)
    populate_locations()
    ff_path = out / "export_fieldform.json"
    msgs2, tbs2 = do_export(ff_path)
    refused_as_documented = any(
        "WGS84" in m["text"] or "not WGS84" in m["text"] for m in msgs2
    )
    if ff_path.exists():
        content = ff_path.read_text(encoding="utf-8", errors="replace")
        ok = len(content) > 2 and "OW100" in content and not tbs2
        record(
            "export_fieldform_json",
            ok,
            f"{len(content)} bytes, has OW100={'OW100' in content}, tracebacks={len(tbs2)}",
        )
    elif refused_as_documented:
        record(
            "export_fieldform_json",
            True,
            "no file written; refused with the documented non-WGS84 UsageError "
            "(not a traceback) -- see tools/export_fieldlogger.py validate_latlons",
        )
    else:
        record(
            "export_fieldform_json",
            False,
            f"no file written and no documented refusal message; tracebacks={len(tbs2)}, "
            f"messages={[m['text'][:120] for m in msgs2]}",
        )

    ctx.close_tools()

    summary = {}
    for r in results:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    return {
        "mode": "scenario_export_fieldlogger_roundtrip",
        "results": results,
        "summary": summary,
    }


run_scenario(scenario)
