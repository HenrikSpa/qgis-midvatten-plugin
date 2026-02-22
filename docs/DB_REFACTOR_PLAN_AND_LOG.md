# Database refactor – plan and implementation log

## Decisions (from user)

1. Use suggested architecture (backend interface, factory, DbConnectionManager as facade).
2. Use suggested layout: `tools/utils/db_utils/` with connection.py, backends/base.py, backends/sqlite.py, backends/postgresql.py, execution.py, schema.py, dialect.py, helpers.py, sqlfile.py. The package is the single entry point (no separate re-export shim).
3. **Option A**: Keep keys `"spatialite"` and `"postgis"` in db_settings and SQL file keywords; map to SQLiteBackend/PostgreSQLBackend in code only.
4. Merge PostGisDBConnectorMod into PostgreSQLBackend (no separate connector class unless clearly better).
5. Execute functions: single `sql: str` only; parameter argument named `args` (optional sequence); no batch/multiple SQL – callers use loops.
6. Implement both:
   - **A)** Backend/dialect methods for dialect-specific SQL in code.
   - **B)** SQL file dialect prefixes: support both `SPATIALITE`/`POSTGIS` and `SQLITE`/`POSTGRESQL`; strip matching prefix; transform line by backend type.
7. Use implementation order and file-touch list from original plan; run tests in prescribed order.

---

## Implementation order

1. db_utils/dialect.py – ident, sql_ident, in_clause, sql_literal, sql_literal_list, UnsafeIdentifierError
2. db_utils/backends/base.py – Backend protocol/ABC
3. db_utils/backends/sqlite.py – SQLiteBackend
4. db_utils/backends/postgresql.py – PostgreSQLBackend (connector merged)
5. db_utils/connection.py – factory + DbConnectionManager
6. db_utils/execution.py – execute(sql, args=None, commit=False), sql_load_fr_db, sql_alter_db
7. db_utils/schema.py – get_tables, get_table_info, get_foreign_keys, get_geometry_types, etc.
8. db_utils/helpers.py – cast_date_time_as_epoch, cast_null, backup_db, get_srid_name, etc.
9. db_utils/sqlfile.py – execute_sqlfile (SPATIALITE/POSTGIS + SQLITE/POSTGRESQL)
10. db_utils/__init__.py – public exports (package is the single entry point)
11. Tests and i18n

---

## Log: Done

- Created `tools/utils/db_utils/` package (formerly db/) with: errors.py, settings.py, dialect.py, backends/base.py, backends/sqlite.py, backends/postgresql.py, connection.py, execution.py, schema.py, helpers.py, sqlfile.py, __init__.py.
- Merged PostGisDBConnectorMod into PostgreSQLBackend; Option A (keep "spatialite"/"postgis" keys); execute*(sql, args) only; both A (backend methods) and B (SQLITE/POSTGRESQL + SPATIALITE/POSTGIS in sqlfile).
- Removed `tools/utils/db_utils.py` shim and renamed package `tools/utils/db/` → `tools/utils/db_utils/` so existing `db_utils` imports use the package directly.
- Fixed circular imports (DatabaseLockedError → db/errors.py; get_postgis_connections → db/settings.py).
- test_db_utils_spatialite: 10 pass, 1 fail (test_in_clause_does_not_expand_scope – investigate DB/connection sharing in test).
- Fixed test_in_clause_does_not_expand_scope: root cause was DbConnectionManager unwrapping single-element tuple args to a single value (e.g. ("P1",) → "P1"), so sqlite3 received two bindings. Fixed by only unwrapping when args is a list of one row (all_args=[(v1,..)]), not when args is a tuple.
- Exported sqlite_internal_tables and postgis_internal_tables from db package and db_utils (for test_create_*_db.py).
- Ran create-DB tests, db_utils (spatialite + postgis), test_midvatten_utils, test_midvatten_defs_spatialite/postgis: all pass. Applied ruff format. Fixed type hints in db_utils/ (List/Tuple/Dict → list/tuple/dict); removed unused Dict from connection.py.
- Added MessagebarAndLog mock and mock_calls print to TestSqlInjectionHardening per testing rules.
- Fixed get_srid_name for PostGIS: use srtext and extract short name (PROJCS/GEOGCS first quoted part); PostGIS has no ref_sys_name column (test_drillreport_postgis now passes).

---

## Log: Remaining

- Run full test suite to confirm all pass.
- Optional: resolve remaining ruff in db_utils/ (UP031 percent format, W291 trailing whitespace) if project style requires.
- Optional: update i18n if user-facing strings change (e.g. "spatialite" → "SQLite" in messages).

---

## How to continue (for a new agent)

If context is full, continue as follows:

1. Open this file: `docs/DB_REFACTOR_PLAN_AND_LOG.md`. Read the "Log: Done" and "Log: Remaining" sections.
2. Run tests from repo root:  
   `nosetests3 test/test_create_spatialite_db.py test/test_create_postgis_db.py --failure-detail --with-doctest --nologcapture --stop`  
   then `test_db_utils_*.py`, then `test_midvatten_utils*.py`, then the rest. Fix any failures.
3. Continue from the first unchecked item in "Log: Remaining". Prefer completing one module at a time (e.g. finish all of db_utils/schema.py, then helpers.py, then sqlfile.py).
4. After each logical chunk, update "Log: Done" and "Log: Remaining" in this file.
5. The package `tools/utils/db_utils/` is the single entry point; ensure every public name used by the codebase is exported from `midvatten.tools.utils.db_utils` (use grep on the codebase for imports from db_utils to get the list).
