> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-04-22 · modified: 2026-04-22 · archived: 2026-07-31

# Code-Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix four issues found in the post-merge code review of the `ai_test` branch.

**Architecture:** Two SQL-safety fixes in `sectionplot/data.py`, one missing test class for the DiverOffice Baro import path, and one clarifying comment in `_sectionplot.py`. No schema changes.

**Tech Stack:** Python 3, pytest, psycopg2, SpatiaLite (via `ident()` from `db_utils/dialect.py`).

---

## Background

These issues were found by reviewing commits from the last 5 days. None are regressions that break existing tests, but two violate the project SQL-safety rules and one leaves the Baro import path untested.

**SQL safety rule:** identifiers must be quoted with `ident()` from `midvatten.tools.utils.db_utils.dialect`. Never inject identifier names via Python string formatting. Values must use DB-API parameter binding (`?` for SQLite, `%s` for PostgreSQL).

---

## Files Modified

- **Modify:** `tools/sectionplot/data.py` — import `ident`, fix strat_key SQLite path, fix seismic SQL
- **Modify:** `tools/sectionplot/_sectionplot.py` — add one explanatory comment
- **Modify:** `test/test_import_logger.py` — add `TestLoggerImportBaroSpatialite` class

---

## Task 1: Fix `strat_key` SQL safety in `data.py`

**Files:**
- Modify: `tools/sectionplot/data.py:1-20` (imports) and `:214-220` (SQLite format call)

The SQLite path of `get_plot_data_bars()` substitutes `strat_key` via raw Python `.format()`. The PostgreSQL path already uses `Identifier(strat_key)`. Both paths must use a safe identifier quoter.

- [ ] **Step 1: Add `ident` import to `data.py`**

Open `tools/sectionplot/data.py`. After the existing imports block (after line 19, the `from midvatten.tools.utils.string_utils import returnunicode as ru` line), add:

```python
from midvatten.tools.utils.db_utils.dialect import ident
```

- [ ] **Step 2: Fix the SQLite `.format()` call**

In `get_plot_data_bars()` (around line 214–220), change:

```python
            if dbconnection.dbtype == "spatialite":
                _sql = sql.format(
                    ph=dbconnection.placeholder(),
                    strat_key=strat_key,
                    condition=condition,
                    subtypes=dbconnection.placeholders(len(subtypes)),
                )
```

to:

```python
            if dbconnection.dbtype == "spatialite":
                _sql = sql.format(
                    ph=dbconnection.placeholder(),
                    strat_key=ident(strat_key),
                    condition=condition,
                    subtypes=dbconnection.placeholders(len(subtypes)),
                )
```

- [ ] **Step 3: Run the sectionplot tests to confirm nothing broke**

```bash
python3 -m pytest test/test_sectionplot*.py -x -q
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add tools/sectionplot/data.py
git commit -m "fix(sectionplot): use ident() for strat_key on SQLite path in get_plot_data_bars"
```

---

## Task 2: Fix seismic SQL identifier safety in `data.py`

**Files:**
- Modify: `tools/sectionplot/data.py` around line 388–405

The seismic query uses `%s` Python string formatting to inject column/table names. All these names are hardcoded constants, so there is no injection risk in practice, but the project convention is to use `ident()` for all identifier substitutions.

- [ ] **Step 1: Rewrite the seismic SQL block**

Find the block that begins with:
```python
    x = "length"
    y1_column = SEISMIC_Y1_COLUMN
    ...
    if line_layer and line_layer.name() == "obs_lines":
        sql = (
            r"""select %s as x, %s as y1, %s as y2, %s as y3 from %s where obsid=%s"""  # noqa: UP031
            % (
                x,
                y1_column,
                y2_column,
                y3_column,
                table,
                dbconnection.placeholder(),
            )
        )
```

Replace it with:

```python
    x = "length"
    y1_column = SEISMIC_Y1_COLUMN
    y2_column = SEISMIC_Y2_COLUMN
    y3_column = SEISMIC_Y3_COLUMN
    table = "seismic_data"
    if line_layer and line_layer.name() == "obs_lines":
        sql = (
            f"SELECT {ident(x)} AS x, {ident(y1_column)} AS y1,"
            f" {ident(y2_column)} AS y2, {ident(y3_column)} AS y3"
            f" FROM {ident(table)} WHERE obsid={dbconnection.placeholder()}"
        )
```

Note: `ident` was already imported in Task 1, so no new import needed.

- [ ] **Step 2: Run the sectionplot tests**

```bash
python3 -m pytest test/test_sectionplot*.py -x -q
```

Expected: all pass.

- [ ] **Step 3: Run ruff**

```bash
ruff check --fix tools/sectionplot/data.py
ruff format tools/sectionplot/data.py
```

- [ ] **Step 4: Commit**

```bash
git add tools/sectionplot/data.py
git commit -m "fix(sectionplot): use ident() for seismic column/table names in get_seismic_data"
```

---

## Task 3: Add explanatory comment to `_sectionplot.py` E402 block

**Files:**
- Modify: `tools/sectionplot/_sectionplot.py:44-46`

The file has a `uic.loadUiType(...)` call at line 44 which must precede the imports that follow. Ruff flags those imports as E402 (module-level import not at top of file). A `# noqa: E402` suppressor is present but without explanation. A future developer may "clean up" the suppressor and break the module.

- [ ] **Step 1: Add a one-line explanation comment**

In `tools/sectionplot/_sectionplot.py`, directly above the first `# noqa: E402` import (around line 46), add:

```python
# These imports must follow uic.loadUiType() above because loading the UI type
# registers Qt classes that the imports below depend on at import time.
```

The block already looks like:
```python
Ui_SecPlotDock = uic.loadUiType(ui_path("secplotdockwidget.ui"))[0]

from matplotlib.widgets import Slider  # noqa: E402
```

Change to:
```python
Ui_SecPlotDock = uic.loadUiType(ui_path("secplotdockwidget.ui"))[0]

# These imports must follow uic.loadUiType() above because loading the UI type
# registers Qt classes that the imports below depend on at import time.
from matplotlib.widgets import Slider  # noqa: E402
```

- [ ] **Step 2: Commit**

```bash
git add tools/sectionplot/_sectionplot.py
git commit -m "docs(sectionplot): explain why E402 imports follow uic.loadUiType call"
```

---

## Task 4: Add DiverOffice Baro → meteo integration test

**Files:**
- Modify: `test/test_import_logger.py` — append `TestLoggerImportBaroSpatialite` class

The parser and pivot helper are unit-tested, but the full `start_import()` path for the Baro format (including `zz_meteoparam` seeding and `general_import("meteo", ...)`) has no test.

- [ ] **Step 1: Write the failing test**

Find the end of `test/test_import_logger.py`. Add the following class after the last class definition:

```python
@pytest.mark.spatialite
class TestLoggerImportBaroSpatialite(utils_for_tests.MidvattenTestSpatialiteDbSv):
    """Integration test for LoggerImport with DiverOffice Baro format.

    Verifies the full start_import() path: parse → pivot → seed zz_meteoparam
    → general_import into meteo table.
    """

    # Minimal baro .mon file with pressure and temperature channels
    _BARO_MON = (
        "[Logger settings]\n"
        "  Serial number           =..00-DA123  219.\n"
        "  Instrument number       =          UTC+1     \n"
        "  Location                =Rb1Baro\n"
        "  Number of channels      =2\n"
        "[Channel 1]\n"
        "  Identification          =PRESSURE\n"
        "[Channel 2]\n"
        "  Identification          =TEMPERATURE\n"
        "[data]\n"
        "2\n"
        "2023/10/05 13:00:00.0      978.667       9.470\n"
        "2023/10/05 14:00:00.0      979.100      10.000\n"
    )

    @mock.patch("midvatten.tools.import_logger.common_utils.MessagebarAndLog")
    def test_baro_import_inserts_into_meteo(self, mock_messagebar):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('Rb1Baro')")

        with common_utils.tempinput(self._BARO_MON, "utf-8", suffix=".mon") as f:

            @mock.patch(
                "midvatten.tools.import_data_to_db.common_utils.NotFoundQuestion"
            )
            @mock.patch("midvatten.tools.import_data_to_db.common_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.import_data_to_db.common_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(
                self,
                filename,
                mock_select_files,
                mock_popup,
                mock_iface,
                mock_askuser,
                mock_notfound,
            ):
                mock_notfound.return_value.answer = "ok"
                mock_notfound.return_value.value = "Rb1Baro"
                mock_notfound.return_value.reuse_column = "location"
                mock_select_files.return_value = [filename]

                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = LoggerImport(self.iface, ms)
                importer.load_gui()
                importer.format_combo.setCurrentText(LoggerImport.FORMAT_DIVEROFFICE_BARO)
                importer.select_files()
                importer.start_import(
                    files=importer.files,
                    skip_rows_without_water_level=False,
                    confirm_names=importer.confirm_names.checked,
                    import_all_data=importer.import_all_data.checked,
                )

            _run(self, f)

        print(mock_messagebar.mock_calls)

        # zz_meteoparam must be seeded with the 'pressure' parameter
        meteoparam_result = db_utils.sql_load_fr_db(
            "SELECT parameter FROM zz_meteoparam WHERE parameter='pressure'"
        )
        assert meteoparam_result[0] is True
        assert len(meteoparam_result[1]) == 1, (
            "Expected 'pressure' to be seeded into zz_meteoparam"
        )

        # meteo table must contain two rows (one per timestamp)
        meteo_result = db_utils.sql_load_fr_db(
            "SELECT obsid, parameter, date_time, reading_num, unit"
            " FROM meteo WHERE obsid='Rb1Baro' AND parameter='pressure'"
            " ORDER BY date_time"
        )
        assert meteo_result[0] is True
        rows = meteo_result[1]
        assert len(rows) == 2, f"Expected 2 pressure rows in meteo, got: {rows}"
        assert rows[0][2] == "2023-10-05 13:00:00"
        assert rows[0][4] == "cmH2O"

    @mock.patch("midvatten.tools.import_logger.common_utils.MessagebarAndLog")
    def test_baro_import_does_not_write_to_wlevels_logger(self, mock_messagebar):
        """Baro data must go to meteo only, not to w_levels_logger."""
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('Rb1Baro')")

        with common_utils.tempinput(self._BARO_MON, "utf-8", suffix=".mon") as f:

            @mock.patch(
                "midvatten.tools.import_data_to_db.common_utils.NotFoundQuestion"
            )
            @mock.patch("midvatten.tools.import_data_to_db.common_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.import_data_to_db.common_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(
                self,
                filename,
                mock_select_files,
                mock_popup,
                mock_iface,
                mock_askuser,
                mock_notfound,
            ):
                mock_notfound.return_value.answer = "ok"
                mock_notfound.return_value.value = "Rb1Baro"
                mock_notfound.return_value.reuse_column = "location"
                mock_select_files.return_value = [filename]

                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = LoggerImport(self.iface, ms)
                importer.load_gui()
                importer.format_combo.setCurrentText(LoggerImport.FORMAT_DIVEROFFICE_BARO)
                importer.select_files()
                importer.start_import(
                    files=importer.files,
                    skip_rows_without_water_level=False,
                    confirm_names=importer.confirm_names.checked,
                    import_all_data=importer.import_all_data.checked,
                )

            _run(self, f)

        print(mock_messagebar.mock_calls)

        wlevels_result = db_utils.sql_load_fr_db(
            "SELECT COUNT(*) FROM w_levels_logger WHERE obsid='Rb1Baro'"
        )
        assert wlevels_result[0] is True
        assert wlevels_result[1][0][0] == 0, (
            "Baro import must not write to w_levels_logger"
        )
```

- [ ] **Step 2: Run the new tests to confirm they currently fail**

```bash
python3 -m pytest test/test_import_logger.py::TestLoggerImportBaroSpatialite -x -v 2>&1 | tail -30
```

Expected: PASS (these tests exercise existing functionality — if they FAIL, that reveals a real bug to investigate before proceeding).

- [ ] **Step 3: If tests fail, investigate and fix the importer**

If `test_baro_import_inserts_into_meteo` fails, read the traceback carefully. Common causes:
- `obs_points` row not found for the baro location (check that `NotFoundQuestion.return_value.value` matches the location in the file)
- `general_import` rejects the meteo rows (check column names in `_pivot_baro_to_meteo` output against the `meteo` table schema)
- `zz_meteoparam` FK violation (check `_BARO_METEO_PARAMS` contains `"pressure"`)

- [ ] **Step 4: Run the full non-PostGIS test suite**

```bash
python3 -m pytest test/ -m spatialite -x -q 2>&1 | tail -10
```

Expected: all pass (no regressions).

- [ ] **Step 5: Commit**

```bash
git add test/test_import_logger.py
git commit -m "test(import-logger): add integration tests for DiverOffice Baro → meteo import path"
```

---

## Final verification

- [ ] **Run full non-PostGIS suite**

```bash
python3 -m pytest test/ -m spatialite -q
```

Expected: all pass.

- [ ] **Run ruff**

```bash
ruff check --fix tools/sectionplot/data.py tools/sectionplot/_sectionplot.py
ruff format tools/sectionplot/data.py tools/sectionplot/_sectionplot.py
```
