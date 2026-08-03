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

- Mock `MessagebarAndLog` in tests: `@mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")` with param name `mock_messagebar` (production code calls it module-qualified via `message_utils`, so this single target intercepts everything)
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

### Imports

- Import from the specific source module, not the aggregators: use
  `string_utils`, `message_utils`, `layer_utils`, `dialog_utils`, `exceptions`
  directly — not `common_utils.X` / `midvatten_utils.X` re-exports.
- The `common_utils` / `midvatten_utils` re-export blocks and the `db_utils.X`
  names exist ONLY as the midv_addons public API. Do not add new in-repo call
  sites through them; do not remove them either.
