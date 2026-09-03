"""GUI scenario: drive FieldloggerImport to a COMMITTED import (not just the
dialog opening) and assert w_levels / w_qual_field rows actually grew.

The tutorial fieldlogger CSV carries three parameter types: 'level' (->
w_levels), 'temp' and 'cond' (-> w_qual_field). Each parses into its own
ImportMethodChooser row; by default every chooser's import_method is ""
(nothing chosen), so start_import() would warn "must choose at least one
parameter import method" and do nothing -- the existing `coverage`/`fill`
modes never get this far. This scenario sets the import_method (and, for
w_qual_field, the required `parameter` field) on each chooser the way a user
would from the comboboxes, then clicks Start import and asserts the DB
mutated.
"""

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

FIELDLOGGER_PATH = "/wiki/tutorial_data/build/fieldlogger/fieldlogger_tutorial.csv"
TABLES = ("w_levels", "w_qual_field", "w_flow", "comments")


def scenario(ctx, plugin, out):
    import midvatten.tools.utils.midvatten_utils as midvatten_utils

    results = []

    def record(name, passed, detail):
        results.append(
            {"id": name, "status": "ok" if passed else "FAIL", "detail": detail}
        )

    before = {t: ctx.db_count(t) or 0 for t in TABLES}

    orig = midvatten_utils.select_files
    midvatten_utils.select_files = lambda *a, **k: [FIELDLOGGER_PATH]
    cp = ctx.oracles.checkpoint()
    dlg = None
    try:
        spec = next(s for s in plugin._actions_manifest if s.id == "import_fieldlogger")
        plugin._dispatch(spec)
        ctx.wait(2000)
        dlg = visible_tool("FieldloggerImport")
        if dlg is None:
            record("open_dialog", False, "FieldloggerImport window did not open")
        else:
            record(
                "open_dialog",
                True,
                f"{len(dlg.input_fields.parameter_imports)} parameter rows",
            )
            # StaffQuestion.alter_data raises UsageError when its combobox is
            # still on the blank default entry ("staff not given"), which
            # start_import's exception handler swallows silently (no
            # traceback, no message-log entry) -- the import just does
            # nothing. Fill it the way a user would.
            for setting in dlg.settings:
                if hasattr(setting, "staff"):
                    setting.staff = "GUI test agent"
            # Route every parsed parameter: 'level' -> w_levels, everything
            # else ('temp', 'cond') -> w_qual_field, mirroring what a user
            # would pick from each row's combobox.
            for name, chooser in dlg.input_fields.parameter_imports.items():
                chooser.import_method = (
                    "w_levels" if name == "level" else "w_qual_field"
                )
            ctx.wait(300)
            # w_qual_field rows additionally require a non-empty `parameter`
            # name (WQualFieldImportFields.alter_data raises UsageError
            # otherwise); the widget's own combobox is editable.
            for name, chooser in dlg.input_fields.parameter_imports.items():
                fields = chooser.parameter_import_fields
                if fields is not None and hasattr(fields, "parameter"):
                    fields.parameter = name.capitalize()
            ctx.wait(200)
            dlg.close_after_import.setChecked(False)
            dlg.start_import_button.click()
            ctx.wait(3000)
    finally:
        midvatten_utils.select_files = orig

    _, tbs = ctx.oracles.since(cp)
    after = {t: ctx.db_count(t) or 0 for t in TABLES}
    grew = {t: after[t] - before[t] for t in TABLES}
    ok = grew["w_levels"] > 0 and grew["w_qual_field"] > 0 and not tbs
    record(
        "commit_grew_rows",
        ok,
        "; ".join(f"{t} {before[t]}->{after[t]}" for t in TABLES)
        + f"; tracebacks={len(tbs)}",
    )
    if dlg is not None:
        ctx.close_tools()

    summary = {}
    for r in results:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    return {
        "mode": "scenario_import_fieldlogger_full",
        "results": results,
        "summary": summary,
    }


run_scenario(scenario)
