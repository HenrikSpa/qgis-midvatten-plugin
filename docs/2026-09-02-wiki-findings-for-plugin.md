# Plugin findings from the wiki 2.0.0 rebuild (2026-09-02)

Collected while documenting and screenshotting every dialog of plugin 2.0.0 — developed as the 1.9.0 beta series (branch `ai_test`, commit 14bdd65a) in
QGIS 4.2.2 / Qt 6.9 (Docker `qgis/qgis:4.2.2`). Nothing here was changed in the plugin; each item is for the
release agent to judge. Ordered by severity.

> **Status 2026-09-03 (checked against ai_test 05d6b7d4):** fixed in the meantime — #1 compact report combo enum (208f0505),
> #2 Interlab4 row selection (f0f06cf2), #3 addDockWidget int (eaa964b6), section-plot dock area (208f0505),
> #9 Piper legend junk (bacb964b), #12 dead wiki links (bacb964b), #14 Swedish-only cleaning notice (667856cf),
> the PostgreSQL upgrade SQL now sets the about_db 2.0.0 marker and adds screen.diam_* (8f307d29, 62390c9c),
> and the "Add non-essential data tables" action was removed (0e27c744). Still open: #4 second-dispatch errors
> (plot_piper persistent, secplotlocation enum) unless covered by the GUI test pass, #5 pytest collection under
> PyQt6, #6 psycopg2 in requirements.txt, #7 metadata about= wording, #8 2099 date defaults, #10 clipped
> LoggerEditor labels, #11 corrupt tooltips, #13 Piper progress-dialog changelog claim (still no dialog in
> tools/piper.py), #15–#18 docs/schema notes, #19 segfault.

## Release-relevant under Qt6
1. **Compact water quality report cannot open on Qt6.** `ui/compact_w_qual_report.ui` references the Qt5-only
   `QComboBox::AdjustToMinimumContentsLength`; `setupUi()` raises under PyQt6 (tools/wqualreport_compact.py).
   The wiki screenshot scene aliases the enum; real QGIS 4 users get a traceback.
2. **Interlab4 metadata table rows cannot be selected on Qt6.** Items are created `ItemIsSelectable` without
   `ItemIsEnabled` (tools/import_interlab4.py ~1365–1373); `selectAll()`/row selection never registers, so
   "Start import" sees no selected lablitteras.
3. **`QMainWindow.addDockWidget` called with a plain int** (midvsettingsdialog.py:148 via midvatten_defs.py:108);
   PyQt6 requires the `Qt.DockWidgetArea` enum. The Settings dock fails to dock on Qt6.
4. **Second dispatch errors:** `plot_piper` is `persistent=True` in `_make_actions` but the tool is not a QWidget
   (AttributeError on second open); section plot stores a Qt enum in the `secplotlocation` int setting
   (TypeError on reopen).
5. **pytest under PyQt6 fails at collection**: the test bootstrap creates `QgsApplication` before
   `QtWebEngineWidgets` is imported (`ImportError: QtWebEngineWidgets must be imported or
   Qt.AA_ShareOpenGLContexts must be set before a QCoreApplication instance is created`). Import
   `qgis.PyQt.QtWebEngineWidgets` (or set the attribute) in the test conftest before the app is created.

## Dependencies / qpip
6. **Remove `psycopg2` from `requirements.txt`.** psycopg2 ships with every official QGIS distribution
   (Debian/Ubuntu `python3-qgis` depends on `python3-psycopg2`; the qgis.org Docker image, OSGeo4W and the
   macOS bundle include it) — verified on this host (2.9.11 from apt) and in `qgis/qgis:4.2.2`. qpip ignores
   the `# Optional` comment and offers to `pip install psycopg2` to every user; on Linux that needs libpq
   headers and a compiler and ends in "Command failed". The plugin already degrades to SpatiaLite-only when
   the import fails, so nothing else is needed. (Added in db7ce915 "declare psycopg2".)
7. `metadata.txt` `about=` and README say the qpip dialog has an "Install" button to click. qpip 1.5.1 shows
   per-package **Install <package>** / **Do nothing** actions, **Ignore all** / **Default actions** buttons and
   **OK**. Suggested `about=` wording: "Requires the Python packages numpy, pandas and matplotlib. The qpip
   helper plugin (installed with Midvatten) offers to install them on first start — leave the preselected
   actions and press OK. Details: https://github.com/henrikspa/qgis-midvatten-plugin/wiki/Installation#python-packages-and-the-qpip-helper".

## Behaviour / UI
8. `calc_lvl_dialog.ui` and `calc_aveflow_dialog.ui` default **From:** to 2099-01-01, so out of the box both
   calculators select no rows and still report success.
9. `PiperPlot.add_legend` passes every `ax.lines` entry as a legend handle → `_child0…_childN` junk entries
   in the legend. Filter labels starting with `_`.
10. Duplicate-timestamp banner label in the LoggerEditor is clipped by the left panel's 360 px `maximumSize`;
    the head line uses the lightest grey of the palette; the reference-series dock entry text is clipped.
11. Four tooltips in `ui/calibr_logger_dialog_integrated.ui` contain literal `</property><property name="text">`.
12. `tools/wqualreport_compact.py:78` links the dialog's "(manual)" to the old jkall wiki URL
    (`…/jkall/qgis-midvatten-plugin/wiki/5.-Plots-and-reports`). `loadlayers.py:155` and
    `midvatten_utils.py:408–419` also link the old jkall "upgrade" anchor; `midvatten_utils.py:471` mentions F7.
13. `metadata.txt` changelog claims a progress dialog with Cancel for Piper plots; `tools/piper.py` has none
    (only a waiting cursor). Drop the claim or add the dialog.
14. i18n: the `w_qual_lab` cleaning notice and its log summary are Swedish-only strings.
15. ~~`docs/LOGGER_SERIES_MIGRATION.md` says DB version 1.10.0; `definitions/db_defs.py` is 1.11.1.~~ **RESOLVED 2026-09-03:** the DB version *is* the plugin version (about_db stamps `Midvatten plugin X.Y.Z`); `db_defs.latest_database_version()` is now `2.0.0`. `LOGGER_SERIES_MIGRATION.md` still uses the old `1.10.0` / `version X.Y.Z` scheme (wrong marker format) and needs its own rewrite — tracked separately.

## Schema
16. `screen.obsid` FK has no `ON DELETE/UPDATE CASCADE`, unlike every other child table (create_db.sql:167).
17. `definitions/create_db_extra_data_tables.sql` is legacy backfill (its tables are standard now) and its
    `w_qual_logger` unique index differs from create_db.sql; `midvatten_defs.py` "extra_data_tables" omits tem_data.
18. `midv_to_instant()` is defined inline in `tools/create_db.py`, not in `insert_functions_postgis*.sql`.

## Segfault (environment)
19. Running the LoggerEditor and the plot tools in one QGIS process under Xvfb/Qt6 segfaults on teardown; the
    wiki pipeline isolates scenes per container. Not diagnosed.

20. **Done 2026-09-03 (9b3c464b, Henrik's request):** LoggerEditor `reset_settings` now sets **From** one millisecond before the first reading when the series has no calculated `level_masl`, so **Calculate** covers the whole series without widening the period by hand. Calibrated case unchanged.
