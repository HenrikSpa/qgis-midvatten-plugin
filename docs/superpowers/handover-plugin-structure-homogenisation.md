# Handover: Plugin Structure Homogenisation

**Branch:** `plugin-structure-homogenisation`
**Worktree:** `/home/hsai1/dev/midv/midvatten/.worktrees/plugin-structure-homogenisation`
**Date:** 2026-04-16

---

## What this refactor does

Replaces ~40 scattered handler methods in `midvatten_plugin.py` with:
- A declarative `_ACTIONS: list[ActionSpec]` manifest (one entry per plugin action)
- A single `_dispatch(spec)` method that handles all precondition checking, persistent-window reuse, and tool invocation
- Every tool class getting a uniform `__init__(self, iface, ms)` + `show() -> None` interface

**Key documents:**
- Spec: `docs/superpowers/specs/2026-04-16-plugin-structure-homogenisation-design.md`
- Plan: `docs/superpowers/plans/2026-04-16-plugin-structure-homogenisation.md`

---

## Current status

### ✅ Done

| Task | Description | Commits |
|------|-------------|---------|
| Task 1 | `test/test_plugin_dispatcher.py` — pins precondition behaviour | `1a64221` |
| Task 2A | `CalculateAveflow`, `StratSymbology`, `ValuesFromSelectedFeaturesGui` → `(iface, ms)` + `show()` | `21c37c2` |
| Task 2B | `DrillreportUi`, `CompactWqualReportUi`, `ExportToFieldLogger` → `(iface, ms)` + `show()` | `5445b73` |
| Task 2C | `PiperPlot`, `TimeSeriesPlot`, `XYPlot`, `Stratigraphy`, `CalculateLevel` → `(iface, ms)` + `show()` | `dd957fe` |
| Task 2D | All importers: base class + `DiverofficeImport`/`LeveloggerImport`/`HobologgerImport`/`FieldloggerImport`/`GeneralCsvImportGui`/`Interlab4Import` | `0de60ec`, `2462cfd` |
| Task 2E | `Drillreport`, `Wqualreport`, `PrepareForQgis2Threejs` — move work to `show()` | `c61c110`, `7138ff2` |
| Task 2F | `LoggerEditor`, `CustomPlot` — persistent windows | `be05ae0` |
| Task 2G | `SectionPlot` — absorb 157-line `plot_section()` validation + fix QGIS symlink + update all test call sites | `1089ab6`, `b5ce99d` |
| Task 2H | `ExportData` — move obsid selection + folder dialog into `ExportData.show()`; `ID_obs_points/ID_obs_lines` initialised in `__init__` | `54c5a0e`, `ce54717` |
| Task 2I | `NewDb` — add `show_sqlite()` / `show_postgis()` with `_read_version()` using `QSettings`; `LoadLayers` stays callback-driven | `400c62c` |
| Tasks 3+4+5 | `ActionSpec` dataclass + `_dispatch()` + `_make_actions()` manifest (35 entries) + delete ~40 handler methods + `tool_registry.py` deleted | `1a53a0a`, `30d90cd` |
| Task 6 | `ExportSpatialite` class extracted to `tools/export_spatialite.py`; `critical_layers` restored to full 5-group union | `47f15ed` |

**Important infrastructure note (discovered in Task 2G):** The QGIS plugin symlink at `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/midvatten` was pointing to the main repo instead of the worktree. It has been updated to point to the worktree so that `from midvatten.tools.X import Y` in tests correctly imports worktree code. All test files with old-style constructor calls were updated in `b5ce99d`.

### ✅ All tasks complete

The implementation plan is fully executed. The remaining cleanup items are:
- Update `CLAUDE.md` "Plugin Entry Point" section (still references `tool_registry.add_plugin_action()`)
- Manual smoke test in QGIS (one action per menu category)
- Merge branch into `ai_test` / `master`

---

## How to execute

Use **Subagent-Driven Development**: dispatch one fresh subagent per task, then run spec + code-quality reviews before moving on.

**Execution pattern for each task:**
1. Read the task from `docs/superpowers/plans/2026-04-16-plugin-structure-homogenisation.md`
2. Dispatch implementer subagent with full task text + context below
3. Run spec compliance reviewer (`superpowers:code-reviewer`)
4. Run code quality reviewer (`superpowers:code-reviewer`)
5. Fix any issues, re-review, then mark done and move to next task

---

## Context for every implementer subagent

Include this in every subagent prompt:

> **Worktree:** `/home/hsai1/dev/midv/midvatten/.worktrees/plugin-structure-homogenisation`
> **Branch:** `plugin-structure-homogenisation`
>
> **Transformation rule (Phase 1, Tasks 2A–2I):**
> - `__init__(self, iface, ms)` — `iface` is QGIS interface, `ms` is `MidvSettings`
> - Constructor must be **cheap**: no DB queries, no dialogs, no Matplotlib figures
> - `show(self) -> None` — deferred work goes here; modal dialogs call `self.exec()` inside `show()`
>
> **Code style:**
> - All imports at **module level** — never inside functions (PEP 8)
> - `ruff check --fix . && ruff format .` after every change
> - Use `python3` not `python`
>
> **Test command:** `python3 -m pytest test/ -x -m spatialite -q`
> **Baseline:** 321 spatialite tests pass (319 original + 2 from Task 1)

---

## Key decisions already made

- `sectionplot` is now a **package** at `tools/sectionplot/`; class is in `tools/sectionplot/_sectionplot.py`
- `customplot` is now a **package** at `tools/customplot/`; class is in `tools/customplot/_customplot.py`
- `tools/base_importer.py` exists — importers inherit from it
- `LoadLayers` stays unchanged (used via `callback=` in ActionSpec, not `tool_class=`)
- `NewDb` gets `show_sqlite()` and `show_postgis()` methods that read `verno` from `metadata.txt` internally
- `ExportToFieldLogger`, `CustomPlot`, `SectionPlot`, `LoggerEditor`, `PiperPlot` are **persistent** windows (`persistent=True` in ActionSpec)
- The `export_spatialite()` plugin handler becomes `tools/export_spatialite.py::ExportSpatialite` class (Task 6)
- `tool_registry.py` is deleted in Task 5 (its logic folds into the `initGui()` loop)

---

## Notes on tricky tasks

**Task 2D (importers):** Read `tools/import_data_to_db.py` base class first — if the base class defines `__init__(parent, msettings)`, update it first and subclasses may inherit the fix automatically. Check `LeveloggerImport` and `HobologgerImport` — they inherit from `DiverofficeImport`.

**Task 2E (immediately-executing tools):** `Drillreport` and `Wqualreport` currently do ALL their work in `__init__`. Move that body to a `_run_report()` private method; `show()` calls it after fetching obsids/layer from `iface`.

**Task 2G (SectionPlot):** Read the full `plot_section()` method in `midvatten_plugin.py` (lines ~1296–1453). Move all validation logic into `SectionPlot.show()`. Substitutions: `self.ms` → `self._ms`, `self.sectionplot.create_new_plot(...)` → `self.create_new_plot(...)`.

**Task 4 (_ACTIONS list):** Icon filenames in the plan are best-guess. Read each existing handler's `self.add_action(...)` call in `midvatten_plugin.py` to get the exact icon filename and translated label string before writing the ActionSpec entry.

**Tasks 3–5 (plugin rewrite):** Run the full test suite (`python3 -m pytest test/ -x`) after Task 5, not just spatialite. Also check `wc -l midvatten_plugin.py` — expect below 500 lines after Task 5.
