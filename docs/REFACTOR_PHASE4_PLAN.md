# Phase 4: Parametrize spatialite/postgis tests – Plan

## Objective

Replace duplicated test pairs (`test_*_spatialite.py` and `test_*_postgis.py`) with single, backend-parametrized test modules so the same test logic runs for both Spatialite and PostGIS, reducing duplication and drift.

## Current state

- **Base classes** in `test/utils_for_tests.py`:
  - Spatialite: `MidvattenTestSpatialiteNotCreated`, `MidvattenTestSpatialiteDbSv`, `MidvattenTestSpatialiteDbEn`, `MidvattenTestSpatialiteDbSvImportInstance`
  - PostGIS: `MidvattenTestPostgisNotCreated`, `MidvattenTestPostgisDbSv`, `MidvattenTestPostgisDbEn`, `MidvattenTestPostgisDbSvImportInstance`
- **Test pairs** (e.g. `test_drillreport_spatialite.py` / `test_drillreport_postgis.py`) share almost identical test code; only the base class differs.
- Some tests may have **backend-specific assertions** (e.g. SRID/CRS strings, skip conditions when PostGIS is unavailable). These must be handled via the backend parameter or small helpers.

## Approach

1. **Introduce a backend-parametrization mechanism** in `test/utils_for_tests.py`:
   - Option A: A parametrized base (e.g. `MidvattenTestParametrizedDbSv`) that accepts `backend in ("spatialite", "postgis")` and mixes in or delegates to the correct setup (temp SQLite file + `new_db()` vs PostGIS connection + schema reset).
   - Option B: Nose test generators or a shared helper that yields test cases for each backend so the same test method runs twice with different setup.
   - Keep existing base classes working during the transition so existing tests do not break.

2. **Merge one test pair at a time** (e.g. start with `test_drillreport_spatialite.py` / `test_drillreport_postgis.py`):
   - Create a single module (e.g. `test/test_drillreport.py`) that uses the new parametrized base.
   - Move the common test logic into one test class/method, parametrized by backend.
   - Where assertions differ per backend, use the backend parameter to select expected values or skip (e.g. `if backend == "postgis": expected = REF_POSTGIS` or a helper returning the right reference).
   - Remove or deprecate the old `test_drillreport_spatialite.py` and `test_drillreport_postgis.py` once the new test passes for both backends.

3. **Repeat** for other pairs (e.g. `test_db_utils_*`, `test_import_diveroffice_*`, `test_stratigraphy_*`, etc.), following the project's test order (create-db tests first, then others per `.cursor/skills/run-nosetests/SKILL.md`).

4. **Constraints**:
   - Do not change database schema (see `.cursor/rules/database-sql-rules/rule-not-modify-database-schema.mdc`).
   - Follow testing rules: mock `MessagebarAndLog`, patch at point of use, print `mock_messagebar.mock_calls` before assert groups where required; do not change reference data unless the test intent changes.
   - Run after each merge: `nosetests3 test/test_create_spatialite_db.py test/test_create_postgis_db.py --failure-detail --with-doctest --nologcapture --stop` then the affected tests and full suite as needed.

## Test pairs to consider (non-exhaustive)

- test_create_spatialite_db.py / test_create_postgis_db.py (likely need special handling; create-db flow differs)
- test_drillreport_spatialite.py / test_drillreport_postgis.py
- test_db_utils_spatialite.py / test_db_utils_postgis.py
- test_stratigraphy_spatialite.py / test_stratigraphy_postgis.py
- test_import_diveroffice_spatialite.py / test_import_diveroffice_postgis.py
- test_export_data_spatialite.py / test_export_data_postgis.py
- test_midvatten_utils_spatialite.py / test_midvatten_utils_postgis.py
- test_midvatten_defs_spatialite.py / test_midvatten_defs_postgis.py
- …and other *_spatialite.py / *_postgis.py pairs under `test/`

## Deliverables

- Updated `test/utils_for_tests.py` with a clear parametrization mechanism.
- At least one merged, parametrized test module (e.g. `test_drillreport.py`) that runs for both spatialite and postgis.
- This plan file updated with a short log of what was done and what remains (e.g. "Drillreport merged; db_utils next").
- Optional: brief note in `docs/REFACTOR_PLAN.md` under "Log: Remaining" or "Log: Done" for Phase 4 progress.

## Log (update as work progresses)

- (none yet)
