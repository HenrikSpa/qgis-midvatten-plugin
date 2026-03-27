# Refactor Assessment (2026-03-26)

Comparison of current `ai_test` branch against pre-refactor commit `ad377a3`.

## What the refactor achieved

### SQL Safety (major win)
The old `db_utils.py` had 8+ SQL injection vectors — table names interpolated via
`%` formatting. The new `dialect.py` with `ident()`, `sql_literal()`, and
`UnsafeIdentifierError` is well-designed. 31 call sites now use validated identifier
quoting. This alone justifies the refactor.

### DB Backend Strategy Pattern (good)
Old: monolithic `db_utils.py` (1,338 lines) mixing SQLite/PostgreSQL with if/else.
New: `base.py` ABC + `sqlite.py`/`postgresql.py` backends, `connection.py` facade.
Clean separation of concerns.

### Test Infrastructure (good)
Old: 42 duplicated test files (21 spatialite + 21 postgis, copy-pasted).
New: mixin classes share test logic, file count reduced from 54 to 46 while
adding ~2,100 lines of actual test content. The `gc.collect()` teardown fix
solved real SQLite file-locking bugs.

### Utility module split (partial)
`string_utils.py`, `file_utils.py`, `message_utils.py`, `dialog_utils.py`,
`exceptions.py`, `layer_utils.py` — each has clear domain responsibility.
However, `common_utils.py` still re-exports everything, so coupling did not
actually decrease.

## What still needs work

### 1. Monster methods
57 methods exceed 80 lines. Worst offenders:

| Method | File | Lines |
|--------|------|-------|
| `general_import()` | `import_data_to_db.py` | 421 |
| `initGui()` | `midvatten_plugin.py` | 381 |
| `__init__()` | `export_fieldlogger.py` | 308 |
| `strat_symbology()` | `strat_symbology.py` | 274 |
| `start_import()` | `import_diveroffice.py` | 264 |
| `createsingleplotobject()` | `customplot.py` | 261 |

### 2. `returnunicode`/`ru` wrapper (183 occurrences in 52 files)
Originally added to prevent crashes when non-UTF8 text appeared in error
messages. In Python 3, most call sites are no-ops. However, the safety net
for encoding edge cases (external data, file content, DB values) should be
preserved at system boundaries. See plan for strategy.

### 3. `dbtype` string branching not fully polymorphic
`helpers.py` has 19 occurrences of `dbconnection.dbtype == "spatialite"` —
the exact pattern the Strategy pattern was supposed to eliminate. These should
become backend methods.

### 4. `common_utils.py` re-exports defeat the module split
All 52 names from split modules are re-imported into `common_utils.py`.
Callers haven't been migrated. The split provides file-level organization
but no actual decoupling.

### 5. Style inconsistencies
- 21 camelCase method names in our own code (14 in `stratigraphy.py`)
- 6 files with zero type hints (~245 functions)
- Three import styles for `qgis.PyQt`
- Three string formatting styles coexist
- 9 classes inherit QMainWindow but call QDialog.__init__()
- 6 mutable default arguments (`={}`)
- 4 `== None` instead of `is None`

### 6. Debug prints in production code
30+ `print()` calls intended for development only. These should not go to
`MessagebarAndLog` (which shows messages to users). They should either be
removed or use Python's `logging` module at DEBUG level.

### 7. Cursor pairing bugs
100+ manually paired `start/stop_waiting_cursor` calls with mismatched counts
in multiple files. A context manager would eliminate this bug class.

### 8. Dead code
16 confirmed dead methods, 5 unused imports, 40+ commented-out code blocks.

### 9. Code volume grew
| Component | Old | New | Change |
|-----------|-----|-----|--------|
| `db_utils` | 1,338 | 2,483 | +85% |
| `common_utils` | 1,424 | 2,144 | +50% |
| `midvatten_plugin.py` | 1,065 | 1,759 | +65% |

Some growth is justified (safety code, test infra), but the utils layer
grew 50-85% while function count barely changed.
