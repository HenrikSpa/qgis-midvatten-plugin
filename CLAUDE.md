# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Midvatten is a QGIS Python plugin for managing hydrogeological observational data (boreholes, water levels, seismic data, etc.) stored in SQLite (SpatiaLite) or PostgreSQL (PostGIS) databases. It provides tools for data import/export, visualization (time series, section plots, piper diagrams, stratigraphy), and reporting.

## Common Commands

```bash
# Run full test suite
python3 -m pytest test/

# Run tests, stop on first failure
python3 -m pytest test/ -x

# Run a single test file
python3 -m pytest test/test_create_spatialite_db.py -x

# Run a single test class or method
python3 -m pytest test/test_export_data.py::TestExportClass::test_method -x

# Run only SpatiaLite or PostGIS backend tests
python3 -m pytest test/ -m spatialite
python3 -m pytest test/ -m postgis

# Lint and format
ruff check --fix .
ruff format .

# Security scan
.venv/bin/python3 -m bandit -r .
```

**Use `python3`, not `python`.**

**Test run order** (when diagnosing failures): run `test_create_*_db.py` first (DB creation), then `test_db_utils*.py` / `test_midvatten_utils*.py`, then specific tests, then the full suite.

## Architecture

### Plugin Entry Point

`__init__.py` defines `classFactory(iface)` which returns `midvatten_plugin.Midvatten(iface)`. The `Midvatten` class builds all plugin actions via `initGui()`, which calls `_make_actions()` to produce a list of `ActionSpec` entries. Each action is dispatched through a single `_dispatch(spec)` method that handles precondition checking, persistent-window reuse, and tool invocation.

### Database Abstraction Layer (`tools/utils/db_utils/`)

Strategy pattern with abstract base + concrete backends:

- **`backends/base.py`** — `Backend` ABC: common interface (`execute`, `execute_and_fetchall`, `commit`, `closedb`)
- **`backends/sqlite.py`** — `SQLiteBackend` (SpatiaLite, `?` placeholders)
- **`backends/postgresql.py`** — `PostgreSQLBackend` (PostGIS, `%s` placeholders, `psycopg2.sql.Composable` support)
- **`connection.py`** — `DbConnectionManager` facade and `create_backend()` factory
- **`dialect.py`** — `ident()` for safe SQL identifier quoting, `sql_literal()` for values
- **`helpers.py`** — Domain helpers (`cast_null`, `backup_db`, etc.)
- **`schema.py`** — Schema introspection (`get_tables`, `get_table_info`)

### Tool Modules (`tools/`)

Each feature is a standalone module. Major categories:

- **Import**: `import_diveroffice.py`, `import_fieldlogger.py`, `import_general_csv_gui.py`, `import_hobologger.py`, `import_interlab4.py`, `import_levelogger.py` — all inherit from `MidvDataImporter` in `import_data_to_db.py`
- **Visualization**: `customplot.py` (time series), `sectionplot.py` (geological sections), `loggereditor.py` (logger editor), `piper.py` (piper diagrams), `stratigraphy.py`
- **Export/Reports**: `export_data.py`, `export_fieldlogger.py`, `drillreport.py`, `wqualreport.py`
- **DB management**: `create_db.py`, `loadlayers.py`

### Shared Utilities (`tools/utils/`)

- **`common_utils.py`** — `MessagebarAndLog` (user messaging), exceptions, file I/O
- **`midvatten_utils.py`** — Domain-specific utilities; re-exports functions from `db_utils/helpers.py` for backward compatibility
- **`gui_utils.py`** — PyQt widget helpers
- **`date_utils.py`** — Date parsing and timezone handling

### Definitions (`definitions/`)

- **`midvatten_defs.py`** — Global constants (table names, columns, defaults)
- **`db_defs.py`** — Database version constants
- **`create_db.sql`** / `insert_datadomain.sql` — Schema and lookup data
- **`*.qml`** — QGIS layer styling files

## Workflow Requirements

- Before starting any implementation task, always invoke the `superpowers:using-git-worktrees` skill to set up an isolated worktree.
- After making any code changes, always invoke the `simplify` skill to review and clean up the changed code.

## Critical Rules

### SQL Safety

Never build SQL queries with Python string concatenation. Always use:
- `ident(name)` from `db_utils/dialect.py` to safely quote table/column identifiers
- DB-API parameter binding (`?` for SQLite, `%s` for PostgreSQL) for values
- `execute()` which handles both `str` and `psycopg2.sql.Composable`

### Database Schema

Never change database schemas (table names, column names, views) unless explicitly asked.

### Test Import Isolation (worktrees)

The repo contains `_pkgroot/midvatten` (a relative symlink → `..`) and a root `conftest.py` that inserts `_pkgroot/` into `sys.path`. This lets every git worktree resolve `import midvatten` from its own directory without touching the shared QGIS plugins symlink.

**Never repoint `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/midvatten`.** It is not needed for tests and repointing it corrupts imports in other agents running concurrently.

Before running tests in an existing worktree that predates this fix, merge `ai_test` to get `_pkgroot/` and `conftest.py`:
```bash
git merge ai_test
```

### Testing Conventions

- Mock `MessagebarAndLog` in tests: `@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")` with param name `mock_messagebar`
- Print `mock_messagebar.mock_calls` before assert groups to surface hidden errors
- Don't print asserted values to stdout (pytest shows assertion details on failure)
- Never change test reference data unless explicitly told to — find the real bug instead
- Mark tests with `@pytest.mark.spatialite` or `@pytest.mark.postgis`
- Tests use `gc.collect()` in teardown to break PyQt/QGIS reference cycles that lock SQLite files

### Code Style

- PEP 8 with ruff: CapWords for classes, snake_case for functions/variables, UPPER_CASE for constants
- Add type hints to function/method arguments
- Run `ruff check --fix .` and `ruff format .` after Python code modifications
- User-facing strings must use `QCoreApplication.translate("context", "text")`
