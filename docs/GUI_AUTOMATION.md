# Driving the Midvatten GUI from an agent (QGIS 4 / Qt6 in Docker)

Written 2026-09-02 after the wiki 2.0.0 rebuild (the release was labelled 1.9.0 during the work), where every plugin dialog was opened, filled and
screenshotted by scripts running inside a real QGIS. The same mechanism can drive a full GUI test pass.
The working code lives in the wiki repo, `/home/hsai1/dev/qgis-midvatten-plugin.wiki/tools/screenshots/`
(`Dockerfile`, `shoot.py`, `runner.py`, `scenes/*.py`, `manifest.toml`); this note explains the mechanism and
the pitfalls so it can be reused or ported.

## 1. Why this setup

- QGIS 4.x (Qt6) is not packaged for Ubuntu noble, and it conflicts with the host's QGIS 3.44 (Qt5). The
  official Docker image `qgis/qgis:4.2.2` (QGIS 4.2.2, Qt 6.9.2, PyQt 6.9.1, Python 3.13, spatialite 5.1,
  psycopg2, matplotlib, pytest) gives a clean Qt6 QGIS without touching the host. The host QGIS stays the Qt5
  test bed.
- Unit tests (`pytest test/`) instantiate dialogs against a dummy iface and cannot see layout, docking,
  menus, message bar or modal flows. Running the real `qgis` binary with the plugin loaded does.
- The plugin exposes everything needed without private hacks: `plugin._actions_manifest` (list of
  `ActionSpec`: id, label, menu, tool_class/callback, needs_db, critical_layers, needs_selection,
  needs_active_layer, persistent, toolbar) and `plugin._dispatch(spec)`, which runs exactly the checks and
  code a menu click runs.

## 2. Environment recipe (verified)

Dockerfile (wiki repo `tools/screenshots/Dockerfile`):

```dockerfile
FROM qgis/qgis:4.2.2
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends python3-pyqt6.qtwebengine xvfb zip \
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir --break-system-packages pandas
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONPATH=/usr/share/qgis/python:/plugin/_pkgroot:/wiki \
    QT_LOGGING_RULES="*.debug=false" MPLCONFIGDIR=/tmp/mplcache
RUN mkdir -p /work/profiles/shot/python/plugins && ln -s /plugin /work/profiles/shot/python/plugins/midvatten \
 && chmod -R a+rwx /work
RUN mkdir -p /tmp/.X11-unix && chmod 1777 /tmp/.X11-unix
```

Facts behind each line:
- The image lacks `pandas` and `python3-pyqt6.qtwebengine`; the plugin imports both
  (`tools/utils/dialog_utils.py` falls back to `QWebEngineView`).
- `PYTHONPATH` must *prepend* to the image's own `/usr/share/qgis/python`, or bare `python3` cannot
  `import qgis`. `/plugin/_pkgroot` makes `import midvatten` resolve from the bind-mounted repo (the
  `_pkgroot/midvatten -> ..` symlink convention already used by the test suite).
- The plugin is mounted read-only at `/plugin` and symlinked into a scripted QGIS profile under `/work`.
- `/tmp/.X11-unix` must exist and be world-writable, because the container runs as the host uid (so output
  files are owned by the user) and Xvfb otherwise fails silently and `xvfb-run` waits forever.
- `MPLCONFIGDIR` silences matplotlib's cache warning under `HOME=/tmp`.

Container invocation (host side, `shoot.py container_cmd`):

```
docker run --rm --init --user $(id -u):$(id -g) -e HOME=/tmp \
  -v <wiki or work repo>:/wiki -v /home/hsai1/dev/midv/midvatten:/plugin:ro -w /wiki midvatten-docs:4.2.2 \
  xvfb-run -a -s "-screen 0 1600x1000x24" \
  qgis --nologo --profiles-path /work --profile shot --code /wiki/tools/screenshots/runner.py \
       --py-args --db /wiki/tutorial_data/build/tutorial.sqlite --project /wiki/tutorial_data/build/midvatten_tutorial.qgz \
                 --out /wiki/images/2.0.0 --figures a,b --
```

- `--init` is required: without a PID-1 reaper `xvfb-run`'s readiness handshake hangs.
- The `qgis` binary refuses `QT_QPA_PLATFORM=offscreen` ("non-interactive mode not supported"); Xvfb is the
  way. 1600x1000 fits every dialog once the LoggerEditor is resized to 1500x900.
- `--code FILE` runs a Python file after the GUI is up; `--py-args ... --` passes arguments through to
  `sys.argv`. The profile is throwaway, so nothing leaks between runs.
- Results go through a JSON file written by the script, never stdout (QGIS floods stdout/stderr).

## 3. Runner mechanics (`runner.py`)

1. `QTimer.singleShot(3000, main)` — do nothing until the main window exists.
2. `qgis.utils.loadPlugin("midvatten"); qgis.utils.startPlugin("midvatten")` — the plugin is *not*
   auto-enabled from a hand-written `QGIS3.ini`; start it explicitly. `qgis.utils.plugins["midvatten"]` is the
   plugin object.
3. Open the database the way the Settings dock does:
   `QgsProject.instance().writeEntry("Midvatten", "database", json.dumps({"spatialite": {"dbpath": path}}))`
   then `plugin.ms.load_settings()`. Reading a `.qgz` afterwards resets that entry, so write it again.
4. Resize/maximise the main window, build a `Context`, run scene modules, write `.last_run.json`
   (`{figure: "ok" | "error: ..."}`), then `QgsApplication.instance().quit()` with an `os._exit(0)`
   fallback 5 s later — QGIS regularly hangs on teardown after all work is done.

`Context` (the whole API a scene needs):

| Method | What it does |
|---|---|
| `wait(ms)` | Local `QEventLoop` + `QTimer`; never `time.sleep` (blocks painting and signals). |
| `layer(name)`, `select(layer, expr)`, `activate(layer)` | Project layer lookup, `selectByExpression`, `iface.setActiveLayer`. |
| `open_action(id)` | Finds the `ActionSpec`, calls `plugin._dispatch(spec)`, waits 1.5 s, returns the tool: persistent tools from `plugin._open_tools`, others by diffing `QApplication.topLevelWidgets()` before/after. Key the diff on `sip.unwrapinstance(w)` — `id()` of PyQt wrappers is reused between calls and misses new windows. |
| `grab(widget, name, compose=False)` | `widget.grab()` renders the widget's own paint tree (right for dialogs/docks/tabs). `compose=True` grabs screen pixels for the widget rect and errors if it is off-screen — only for popups drawn as separate windows (an open QMenu). |
| `grab_modal(name, delay_ms=800, close="reject")` | For tools that call `dialog.exec()`: schedule a `QTimer` before triggering; it grabs `QApplication.activeModalWidget()` and closes it. |
| `find_child(widget, objectName)` | `findChild`; on miss raises with the list of available object names — the fastest way to discover a dialog's controls. |
| `close_tools()` | Rejects/closes every visible top-level window except the main window. Docked widgets are not top-level — hide them explicitly. |

A scene module defines `FIGURES: list[str]` and `scene(ctx)`; `manifest.toml` maps each figure to its scene
module and the page that must reference it. Errors in one scene are accounted per figure and never abort
the run.

## 4. Patterns that were needed (reuse them)

- **File pickers:** monkeypatch the function the dialog calls, in the module it imports it from, and restore
  in `finally`: `midvatten_utils.select_files = lambda *a, **k: [path]`,
  `export_data.QFileDialog.getExistingDirectory = lambda *a, **k: "/tmp/x"`,
  `create_db_dialogs.QFileDialog.getSaveFileName = lambda *a, **k: ("/tmp/x.sqlite", "")`; then `.click()` the
  real Browse button. Never write private `_attrs` of a dialog — you would test your own state, not the code.
- **Progress dialogs:** hook `QProgressDialog.show` to capture/inspect the instant it appears; a fixed wait
  is unreliable.
- **Blocking prompts:** know which controls trigger modal questions (e.g. LoggerImport's "Confirm each logger
  obsid before import" asks per obsid; the general CSV import asks before dropping rows). Either pre-set the
  control or answer the modal via `grab_modal`-style timers. A forgotten modal freezes the run until the
  container is killed.
- **Selections and state:** every scene selects what it needs and clears selections/docks afterwards; a
  later scene inherits whatever you leave (the Settings dock and the section-plot `secplotlocation` setting
  bit us).
- **Big windows:** `tool.resize(1500, 900)` before grabbing; the LoggerEditor's designer size does not fit.
- **Popups:** `combo.showPopup(); ctx.grab(combo.view().window(), ...)`.
- **Web views:** report tools open HTML in the system browser via `QDesktopServices.openUrl`; patch
  `openUrl` to capture the path, then load it into the plugin's own `HtmlDialog` if you need to see it.
- **Data hygiene:** imports mutate the database; either capture the progress dialog and cancel, or rebuild
  the dataset afterwards (`tools/tutorial_data/build.py`) and assert row counts. Scenes that must insert
  test rows (duplicate-timestamp banner) do it in a `try/finally` with a pre-flight "DB is pristine" check.
- **One process per tool family:** running the LoggerEditor scenes and the plot scenes in one QGIS process
  segfaults on teardown; `shoot.py shoot --all` runs one container per scene module and aggregates.
- **Agent hygiene:** run every container command in the foreground with an explicit timeout (10 min is
  enough for one scene); never Monitor/background — three implementers stalled waiting for notifications
  that never arrive. `docker ps` / `docker kill` if a container is stuck.

## 5. Reusing this for a full GUI test pass

Design that follows directly from the above (not implemented yet):

1. **Harness:** copy `runner.py` + `Context` into the plugin repo (e.g. `test/gui/runner.py`), keep the
   Docker recipe, add a Qt5 variant that runs the same runner on the host
   (`xvfb-run -a qgis --profiles-path <tmp> --profile shot --code runner.py --py-args ... --`, plugin symlinked
   into the temporary profile) so both Qt builds are covered by the same scenes.
2. **Fixture:** the tutorial dataset described in section 5a — enough rows in every table to make every tool take its happy path.
3. **Scenes as tests:** one module per menu action. Each: set the preconditions from the `ActionSpec`
   (`needs_selection`, `needs_active_layer`, `critical_layers`), `open_action(id)`, assert a window appeared
   and is on-screen, exercise every control found via `find_child` (toggle checkboxes, cycle combos, click
   Browse with a patched picker, run the action), close it, and assert no Python traceback reached the QGIS
   log. Capture a PNG on failure for the report.
4. **Automatic oracles:** install a `qgis.core.QgsApplication.messageLog()` listener and a `sys.excepthook`
   that store every WARNING/CRITICAL message and traceback per scene; treat "any traceback" as a failure.
   Diff `iface.messageBar()` items for unexpected error levels. Check the DB row counts before/after each
   scene against the expected mutation.
5. **Coverage sweep:** a generic scene that iterates `plugin._actions_manifest`, dispatches each action
   with the minimal preconditions, and reports which open a window, which show a message-bar error, and
   which raise — cheap and catches whole classes of Qt6 breakage.
6. **Exit criteria:** per-scene JSON (ok / error / traceback text), exit code 1 on any error, one container
   per scene so a crash isolates.

## 5a. Test data: the tutorial dataset

Built for the wiki, but designed to exercise every tool, so it is the fixture for GUI tests too.

**Where it is**
- Wiki repo, committed: `tutorial_data/midvatten_tutorial_data_2.0.0.zip` (1.5 MB, 29 files) and the vendored
  2016 source CSVs under `tutorial_data/source/` (EPSG 4326, the old Midvatten example site in Dalarna).
- Wiki repo, built output (gitignored): `tutorial_data/build/` — `tutorial.sqlite`, `midvatten_tutorial.qgz`,
  `csv/`, `logger/`, `lab/`, `fieldlogger/`, `tem/`, `images/`, `dem/`. This is what the runner mounts
  (`--db /wiki/tutorial_data/build/tutorial.sqlite --project /wiki/tutorial_data/build/midvatten_tutorial.qgz`).
- Builder: `tools/tutorial_data/build.py` (runs inside the container because it uses the plugin's own
  `NewDb` and `MidvDataImporter`), writers for the native formats in `tools/tutorial_data/writers.py`
  (round-trip tested through the plugin's parsers in `tools/tutorial_data/tests/`), and
  `tools/tutorial_data/check_project.py` (extracts the zip to a temp dir and asserts all layers and the
  Screens relation are valid — the "does it work anywhere" test).

**Rebuild from scratch (about 5 minutes):**
```
python3 tools/screenshots/shoot.py exec -- python3 tools/tutorial_data/build.py     # tutorial.sqlite + files
python3 tools/screenshots/shoot.py shoot --figures getting_started_layers_panel --project ""   # writes the .qgz
python3 tools/screenshots/shoot.py pack                                             # the zip
python3 tools/screenshots/shoot.py exec -- python3 tools/tutorial_data/check_project.py
```

**What the database contains** (schema 2.0.0, locale `en_US`, EPSG 3006, site datum ~316 m a.s.l.;
the 2016 outlier OW100 sits at 41.7 m):

| Table | Rows | Notes for tests |
|---|---|---|
| obs_points | 69 | dug wells, drilled wells, piezometers (`Pz*`), production wells (`PW*`), river gauge; `h_toc`/`h_gs` set |
| obs_lines | 5 | `vlf01`, `vlf02` (VLF), `S1`–`S3` (synthetic seismic lines through the site) |
| w_levels | 7447 | 2009-10 to 2012-11; `h_toc` and `level_masl` precomputed for 7445 rows |
| w_levels_logger / w_logger_series | 27501 / 2 | `OW100` (DiverOffice, serial V1234), `PW1001` (Levelogger 2050123); no null `series_id`; unique index `uq_w_levels_logger_obsid_dt` |
| stratigraphy | 422 | 64 points; geology codes match `zz_strat` |
| screen | 63 | one screen per well with length > 3 m; `screenshort` cycles JWS / PVC solid / stainless / default (styled by `zz_screen_plots`) |
| w_qual_lab / w_qual_field | 1732 / 145 | 32 points with lab data, e.g. `Pz0917`, `Pz0918`, `Pz1005` (Piper-relevant parameters) |
| w_flow / meteo | 626 / 118 | `PW1001` flow readings; `PW1002` precipitation |
| seismic_data / vlf_data | 254 / 78 | along `S1`–`S3` and `vlf01`/`vlf02` |
| tem_data / profile_images | 12 / 1 | inversion `tutorial_inversion` and image alias `resistivity`, both on `vlf02`, path relative to the DB folder |
| comments, s_qual_lab, w_qual_logger, spatial_history | 0 | empty — add rows in a scene if a test needs them |

**Native import files** (all synthesized from the same readings, so imports are idempotent):
`logger/OW100_diveroffice.MON`, `logger/BARO1_diveroffice_baro.MON` (→ meteo), `logger/PW1001_levelogger.csv`,
`logger/PW1002_hobo.csv` (temperature only), `lab/interlab4_tutorial.lab` (UTF-16; one deliberately unknown
site "Unknown site 7" to trigger the Assign obsids dialog), `fieldlogger/fieldlogger_tutorial.csv`,
`csv/*.csv` (one per populated table, incl. `screen.csv`), `tem/tem_vlf02.csv`, `dem/dem_3006.tif`.

**Keeping it pristine between scenes:** imports mutate the DB. Either cancel at the progress dialog, or
rebuild afterwards. Cheap invariants to assert after a scene: `w_levels_logger` = 27501 rows, no rows with
`length(date_time) <> 19`, the unique index present, `w_logger_series` = 2, `count(level_masl)` in
`w_levels` = 7445, and no stray files in `tutorial_data/build/` (backups land next to the DB).
`scenes/logger_editor.py` shows the pattern: pre-flight check, insert test rows, `finally` cleanup.

**Caveats:** `OW100` has no screen; `PW1001` is the point to use for form/Screens figures. The seismic
lines, TEM model, DEM and profile image are synthetic and only geometrically consistent, not geologically
meaningful. Stratigraphy dropped 6 and w_qual_field 3 source rows that the plugin's importer rejects as
duplicates — that is the importer's behaviour, not data loss to fix.

## 6. Problems found this way (all reported in `docs/2026-09-02-wiki-findings-for-plugin.md`)

Qt6: compact water-quality report `.ui` uses a Qt5-only enum (dialog cannot open); Interlab4 table rows are
not selectable (`ItemIsEnabled` missing); `addDockWidget` called with an int; `plot_piper` marked persistent
but not a widget; section plot writes an enum into an int setting; pytest collection order vs
`QtWebEngineWidgets`. General: calculators default to 2099 date ranges; Piper legend junk; corrupt tooltips;
dead wiki links in dialogs; Swedish-only strings. All were found by opening dialogs the way a user does.
