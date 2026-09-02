# GUI test pass for the Midvatten plugin (QGIS 4 / Qt6 in Docker)

Written 2026-09-02. Companion to `docs/GUI_AUTOMATION.md`, which describes the mechanism; this
document is the concrete test plan the user asked for: *create a database, fill it with data, then
exercise every widget and feature and confirm it works as intended.*

## 0. Pipeline status — VERIFIED working

Before planning, the whole chain was run end to end and confirmed:

- Image `midvatten-docs:4.2.2` is built; tutorial DB + project are built in the wiki repo.
- `shoot.py exec` — `import qgis, midvatten, pandas, psycopg2` all succeed; **Qt 6.9.2**; `midvatten`
  resolves from the bind-mounted repo (`/plugin/_pkgroot/midvatten/__init__.py`).
- `shoot.py shoot --figures home_main_window,settings_dock_db` → both `ok`; real PNGs written
  (1600×1000 main window showing the Midvatten menu + toolbar, the tutorial project with all layers
  rendering). Verified by opening the PNG.

So the harness runs. The work below is turning the *screenshot* harness into a *test* harness and
enumerating the tests. Nothing here requires new infrastructure — only assertions on top of the
existing `Context`/`runner.py`/`shoot.py` mechanism.

## 1. Screenshot scene → test: what changes

The existing scenes already drive the GUI like a user (click Browse with a patched picker, select
features, trigger actions, and assert side effects — e.g. `db_utils.py` asserts *exactly one* new
`.zip` after backup). They just don't yet treat "a traceback reached the log" as a failure, and they
capture PNGs rather than assert outcomes. Three additions turn them into tests:

1. **Automatic oracles (the core new piece).** In `runner.py`, before scenes run, install:
   - a `QgsApplication.messageLog().messageReceived` listener that buckets every message by
     `(scene, level)`; any `Qgis.Warning`/`Qgis.Critical` is recorded.
   - `sys.excepthook` + a Qt message handler (`qInstallMessageHandler`) capturing tracebacks and
     `qFatal`/`qCritical` output per scene.
   - an `iface.messageBar()` diff around each scene to catch error-level bar items.
   Any traceback or unexpected Critical = the test fails, regardless of whether a window appeared.

2. **`Context` assertion helpers** (add to the copied `Context`):
   - `db_count(table)` / `db_scalar(sql)` — run a query on the open DB via the plugin's own backend.
   - `assert_pristine()` — the invariants from GUI_AUTOMATION §5a (w_levels_logger = 27501, no
     `length(date_time)<>19`, unique index present, w_logger_series = 2, count(level_masl)=7445).
   - `exercise_controls(widget)` — walk `findChildren`: toggle every `QCheckBox`, cycle every
     `QComboBox` through its items, expand every `QTabWidget` page; assert no traceback fired. This is
     the cheap "does clicking anything blow up" sweep.
   - `on_screen(widget)` — assert the window is visible and its rect is inside the screen.
   - `expect_messagebar(level)` — assert the last bar item is at the expected level (turns "a clean
     error message" into a *passing* expectation, distinct from an unexpected one).

3. **Per-test result schema**: `{status: ok|fail, tracebacks: [...], warnings: [...],
   db_deltas: {...}, png: path?}`. On any failure grab a PNG of the offending widget for the report.
   Reuse the `.last_run.json` + `shoot.py` aggregation already in place; add exit-code-1-on-any-fail.

**Home for the code** (GUI_AUTOMATION §5.1): copy `runner.py` + `Context` into the *plugin* repo at
`test/gui/`, keep the Docker recipe, and add a Qt5 host variant that runs the same scenes via
`xvfb-run -a qgis --profiles-path <tmp> --profile shot --code test/gui/runner.py ...` with the plugin
symlinked into a throwaway profile. Same scenes, both Qt builds — this is what catches Qt6 breakage.

## 2. Fixture lifecycle

- **Read-only tests** (open a dialog, exercise controls, plot, report) run against the shared
  tutorial DB and must leave it pristine — `assert_pristine()` at scene end.
- **Mutating tests** (imports, edits, calculators, exports-into-db) either cancel at the progress
  dialog, or run against a *fresh copy* of the DB (`cp tutorial.sqlite $tmp` inside the container),
  or against a from-scratch DB (test group A). Never mutate the shared fixture.
- **One container per test family** (GUI_AUTOMATION §4, §5.6) — LoggerEditor + plots in one process
  segfaults on teardown. `shoot.py` already isolates per scene module; keep that.
- Foreground, explicit 10-min timeout, never backgrounded (GUI_AUTOMATION §4 "Agent hygiene").

## 3. The tests

Grouped by family (= one scene module = one container). IDs below are the real `_actions_manifest`
ids from `tools/generated/actions.txt`.

### A. Create a database and fill it (the user's explicit ask)

The tutorial fixture is *built* headlessly by `build.py` (NewDb + MidvDataImporter). These tests
drive the same thing **through the GUI** and assert the result.

- **A1 — Create new SpatiaLite DB** (`new_db`): patch `QFileDialog.getSaveFileName` → `$tmp/new.sqlite`,
  drive the `NewSpatialiteDbDialog` (CRS, locale), accept. Assert: file exists; schema version =
  current (query `about_db`); core tables present and empty; `add_midvatten_layers` then loads all
  default layers without error.
- **A2 — Create new PostGIS DB** (`new_postgis_db`): `@pytest.mark.postgis`, needs a reachable
  postgres (mind the shared-DB contention note in memory). Optional / skipped if no server.
- **A3 — Fill the fresh A1 DB via each importer**, against the tutorial *source* files:
  - `import_csv`: obs_points, then w_levels, then w_levels_logger (exercise the logger-series
    metadata block). Assert per-table row counts match the source; assert re-import is idempotent
    (no duplicate rows); assert encoding correct (no mojibake — the `returnunicode` firewall).
  - `import_logger`: all four formats (DiverOffice `.MON`, Levelogger `.csv`, Hobo `.csv`, baro→meteo).
    Cycle the format dropdown; run one import; capture the progress dialog; assert w_levels_logger
    grew by the expected count and w_logger_series was created.
  - `import_interlab4`: UTF-16 `.lab` with the deliberate "Unknown site 7" → the **Assign obsids**
    dialog must appear and its rows must be selectable (Qt6 regression, §6). Assert w_qual_lab rows.
  - `import_fieldlogger`: assert w_qual_field / w_levels / w_flow / comments rows.
  - `add_non_essential_tables`, `add_view_obs_points_lines`: run, assert tables/view created.

### B. Every dialog opens and is on-screen (coverage sweep, GUI_AUTOMATION §5.5)

Generic scene iterating `plugin._actions_manifest`: set the minimal preconditions each `ActionSpec`
declares (`needs_selection`, `needs_active_layer`, `critical_layers`), `open_action(id)`, assert a
window appeared **and** `on_screen(it)`, or that a *clean* message-bar error appeared (not a
traceback). Cheap, catches whole classes of Qt6 breakage in one run. Covers all 34 actions.

### C. Exercise the controls in each dialog (no commit)

For each dialog opened in B, `exercise_controls(widget)`: toggle every checkbox, cycle every combo,
click every Browse button with a patched picker, walk every tab. Assert no traceback. This is where
"corrupt tooltips", missing enum flags, and dead handlers surface.

### D. Run each action to completion (happy path) and check the result

- **Edit** — `wlvlcalculate` (calc w_level from manual; assert level_masl written, and **not** a 2099
  default date range, §6); `calculate_aveflow` (needs selection; assert aveflow computed);
  `wlvlloggcalibrate` = the **LoggerEditor sub-suite** (its own module, per §4/§5.6): load OW100
  series, Adjust-level tab, Series tab, Reference-series dock, the **duplicate-timestamp banner** +
  red markers (insert dup rows in try/finally with a pristine pre-check), and the **Resolve
  duplicates** dialog. Assert the resolve flow removes duplicates and restores `assert_pristine()`.
- **Plots** — `plot_timeseries`, `plot_xy`, `plot_stratigraphy`, `plot_section` (Settings tab /
  screens / TEM overlay), `plot_sqlite` (custom + Fix-style-files), `plot_piper`. Each: select the
  documented features, assert a figure window with drawn axes (non-empty), no empty-data error.
  Piper: assert **no legend junk / corrupt labels** (§6).
- **Reports** — `drillreport` (Pz0917), `custom_drillreport`, `waterqualityreport`,
  `waterqualityreportcompact`. Patch `QDesktopServices.openUrl` to capture the HTML path; assert the
  file is written and non-empty; the **compact wqual `.ui`** must open under Qt6 (§6). Load the HTML
  into the plugin's `HtmlDialog` to screenshot on failure.
- **Export** — `export_csv` (patch dir picker; assert one CSV per table written), `export_spatialite`
  (+progress dialog; assert a valid SpatiaLite DB written and round-trips through the importer),
  `export_fieldlogger` (assert FieldForm JSON written; refuses non-WGS84 — recent fix, guard it).
- **DB mgmt / utils** — `vacuum_db`, `zip_db` (exactly one new `.zip`, already done),
  `calculate_db_table_rows`, `load_data_domains`, `load_data_tables`, `load_strat_symbology`,
  `list_of_values_from_selected_features`, `prepare_layers_for_qgis2threejs`, `refresh_spatialite_stats`.
  Each: run, assert its documented side effect and no traceback.

### E. Pin the known Qt6 findings as regression assertions

Turn each bug in GUI_AUTOMATION §6 / `docs/2026-09-02-wiki-findings-for-plugin.md` into an explicit
assertion so a future Qt6/Qt5 change can't silently reintroduce it: compact-wqual `.ui` enum,
Interlab4 row selectability (`ItemIsEnabled`), `addDockWidget` int arg, `plot_piper` persistent-but-
not-a-widget, section-plot enum-into-int setting, calculators' 2099 default range, Piper legend junk.

## 4. Pass / fail oracles (applied to every test)

A test **fails** if any of: a Python traceback reached the log or `sys.excepthook`; an unexpected
`Qgis.Critical` message-bar item appeared; a `assert_pristine()`/DB-invariant check failed; the
expected DB mutation did not happen; a dialog opened off-screen or not at all where one was expected.
Every failure captures a PNG. Exit code 1 if any test failed.

## 5. Execution model & matrix

- Qt6: `docker … midvatten-docs:4.2.2 … xvfb-run … qgis --code test/gui/runner.py` — one container per
  scene module, aggregated by `shoot.py`-style driver.
- Qt5: same scenes on the host QGIS 3.44 via `xvfb-run qgis` + throwaway profile (do **not** repoint
  the shared plugins symlink — memory/CLAUDE.md; use a temp profile with its own symlink).
- CI-shaped output: per-test JSON, aggregate summary, non-zero exit on failure.

## 6. Build sequence (phases)

1. Harness upgrade: copy `runner.py`+`Context` to `test/gui/`; add the message-log/excepthook oracles
   and the `Context` assertion helpers; add exit-code-on-fail. Prove it by re-running the two smoke
   figures as *tests*.
2. Group B (coverage sweep) — cheapest, highest Qt6-breakage yield; run it first to triage.
3. Group A (create + fill) — the user's headline ask; establishes the fresh-DB fixture path.
4. Groups C, D per family, one module at a time (LoggerEditor and plots isolated).
5. Group E regression pins.
6. Qt5 host variant of the same scenes; compare the two matrices.

Estimated first useful signal: after phases 1–2 (harness + coverage sweep) — that alone answers "do
all 34 dialogs still open under Qt6" and reuses code that already exists.

## 7. TODO — generalize the harness to every QGIS plugin under `~/dev`

The natural next step once this works for Midvatten: point the same Docker + Xvfb + QGIS runner at
**every QGIS plugin in the dev folder** and get one Qt6 pass/fail table across all of them. The
oracles (message-log listener, excepthook, on-screen check) are plugin-agnostic already; only the
"what to dispatch and what fixture to load" is plugin-specific.

Plugins found under `~/dev` (dir has `metadata.txt` + a `classFactory` in `__init__.py`):

- `midv/midvatten` — this one (the reference implementation).
- `midv_inventory`, `midv_soil3d`, `qgis_midv_tolkn_plugin`, `dynplot/dynplot`,
  `midv_addons/midv_addons`, `dd/drawdowndiagnistic` — the MIDV in-house plugins; primary targets.
- `Qgis2threejs` — third-party (vendored); lower priority, but a good "does the generic sweep survive
  a plugin we don't control" check.
- (`wt-va-tests/midv_addons` is a worktree/duplicate of `midv_addons` — skip.)

What generalizes vs. what each plugin must supply:

1. **Generic (write once):** the container recipe, the oracle install, `on_screen`/`exercise_controls`,
   the "load plugin → dispatch → assert a window opened and no traceback" loop, per-plugin result JSON,
   one container per plugin so a crash isolates.
2. **Per-plugin adapter (small):** how to enumerate the plugin's actions. Midvatten exposes
   `plugin._actions_manifest` + `plugin._dispatch`; other plugins won't. The generic fallback is to
   iterate the plugin's registered `QAction`s (from its menu/toolbar) and `trigger()` each — no private
   API needed, works for any plugin. Add a manifest hook a plugin *can* provide for richer precondition
   metadata (needs_db/needs_selection/critical_layers), Midvatten-style.
3. **Per-plugin fixture:** most need a project/layers to be meaningful. Start with "open the plugin
   against an empty QGIS and against its own tutorial/demo project if it ships one"; a data-carrying
   plugin (like Midvatten) points at its own built fixture.

Deliverable shape: a `test/gui/` harness promoted to a shared location (or a tiny installable package)
that each plugin repo vendors or references, plus a top-level driver that discovers plugins under a
root, runs each in its own container, and aggregates a single dashboard: *plugin × action ×
{opened, blocked, traceback}* for Qt6 (and the Qt5 host variant). This is the cheapest possible
early-warning system for the whole plugin fleet against future QGIS/Qt upgrades.
