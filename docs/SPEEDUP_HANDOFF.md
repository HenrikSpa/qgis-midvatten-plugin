# Test Speedup — Session Handoff

## What was done

`test/utils_for_tests.py` was rewritten to use class-level database setup instead of
per-test setup. The key changes:

### SQLite (`MidvattenTestSpatialiteDbSv`, `MidvattenTestSpatialiteDbEn`)
- `setup_class()`: calls `new_db()` ONCE, then snapshots the DB into an in-memory
  `sqlite3.connect(':memory:')` via `sqlite3.Connection.backup()`.
- `setup_method()`: restores the file from the snapshot (microseconds) + reinits QGIS
  plugin + writes QgsProject settings.
- `teardown_method()`: closes plots, clears QgsProject. Does NOT delete the DB file.
- `teardown_class()`: closes snapshot, deletes DB file.
- `remove_db()` overridden to no-op (file is class-managed).

### PostgreSQL (`MidvattenTestPostgisDbSv`, `MidvattenTestPostgisDbEn`)
- `setup_class()`: DROP SCHEMA + CREATE SCHEMA + CREATE EXTENSION + `new_postgis_db()`
  ONCE, then snapshots all reference tables (`_REFERENCE_TABLES`) into a Python dict.
- `setup_method()`: TRUNCATE all tables (data + reference) CASCADE, re-insert reference
  data from snapshot using multi-row INSERT (one INSERT per table), reinit QGIS plugin,
  write QgsProject settings.
- `teardown_method()`: closes plots, clears QgsProject.
- `teardown_class()`: writes QgsProject settings (needed since teardown_method clears them),
  then DROP SCHEMA + CREATE SCHEMA.

### New constants added to `utils_for_tests.py`
- `_DATA_TABLES`: 17 user-data tables.
- `_REFERENCE_TABLES`: 9 reference tables (`about_db` + all `zz_*` tables).

### New files created
- `test/conftest.py`: pins PostGIS tests to a single xdist worker via `xdist_group`.
- `pytest.ini`: `xdist_group` mark registered.

---

## Benchmarks

| Test class | Backend | Old | New | Speedup |
|---|---|---|---|---|
| `TestWflowImportPostgis` (3 tests) | PostgreSQL | 11.93 s | 5.42 s | 2.2× |
| `TestCustomPlot` (29 tests) | SQLite | 27.71 s | 16.59 s | 1.7× |

---

## Tests verified passing (new code, current session)

- `test_create_spatialite_db.py`: 23/23 ✅
- `test_calclvl.py`, `test_wlevels_calc_calibr.py`, `test_drillreport.py`, `test_db_utils.py`: 80/80 ✅
- `test_import_fieldlogger_backends.py`, `test_import_interlab4_backends.py`,
  `test_import_diveroffice_backends.py`, `test_export_data.py`: 101/102 ✅
  (1 pre-existing failure: `TestExportSpatialite::test_export_spatialite_zz_tables`)

## Tests NOT yet run in this session

- `test_import_data_to_db.py` — large file, was running but context limit hit
- `test_wlevels_calc_calibr.py` — may have already been run (covered above)
- Any other test files in `test/` directory

---

## Known pre-existing failures (NOT caused by these changes)

Confirmed via `git stash` + run + `git stash pop`:

1. `TestExportSpatialite::test_export_spatialite_zz_tables` — color value mismatch,
   already failing before changes.
2. `TestWlevelsImportOldWlevelsPostgis::test_w_level_import_from_csvlayer` — got `None`
   instead of `-999.0`. User confirmed this test was old/unneeded and **removed it** from
   `test/test_import_data_to_db.py`.

---

## Instructions for the next session

### To continue validation:

```bash
# Run the full test suite
python3 -m pytest test/ -q 2>&1 | tail -30

# Or just the file that wasn't finished:
python3 -m pytest test/test_import_data_to_db.py -q 2>&1 | tail -20

# To check against baseline (old code):
git stash
python3 -m pytest test/ -q 2>&1 | tail -5
git stash pop
```

### What to look for:
- Any new FAILED tests (not in the known pre-existing list above) indicate a regression.
- The total pass count should be equal to or higher than baseline (user removed one test).
- `TestExportSpatialite::test_export_spatialite_zz_tables` failing is expected.

### Key files modified:
- `test/utils_for_tests.py` — all base class definitions (primary change)
- `test/conftest.py` — new file (xdist worker grouping)
- `pytest.ini` — xdist_group mark registration
- `test/test_import_data_to_db.py` — user removed one failing test (not this session)

### To use parallel execution (optional, needs install):
```bash
pip install pytest-xdist
python3 -m pytest test/ -n auto -q
```
PostgreSQL tests are pinned to a single worker automatically via `conftest.py` and the
`@pytest.mark.postgis` markers.

### Architecture notes for debugging:
- `MidvattenTestSpatialiteDbSv.setup_method()` calls `MidvattenTestBase.setup_method(self)`
  **directly** (not via `super()`), to bypass `MidvattenTestSpatialiteNotCreated.setup_method()`
  which would create a new temp DB file.
- `teardown_class()` for PostgreSQL must restore QgsProject settings before calling
  `sql_alter_db("DROP SCHEMA public CASCADE;")` because `teardown_method()` clears QgsProject.
- `remove_db()` is overridden to a no-op in the `DbSv`/`DbEn` classes; file lifecycle is
  managed by `setup_class`/`teardown_class`.
