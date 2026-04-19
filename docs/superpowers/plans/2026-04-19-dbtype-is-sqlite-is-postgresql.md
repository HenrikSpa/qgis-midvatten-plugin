# dbtype → is_sqlite() / is_postgresql() Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all scattered `dbconnection.dbtype == "spatialite"` / `"postgis"` string comparisons with typed `is_sqlite()` / `is_postgresql()` predicate methods, following the Strategy pattern already established in the codebase.

**Architecture:** Add `is_sqlite() → False` and `is_postgresql() → False` to the `Backend` ABC; each concrete subclass overrides only its own method to return `True`. `DbConnectionManager` delegates both predicates to its backend. All call sites replace string comparisons with the appropriate predicate call. The `dbtype` string attribute is **kept** on backends (still serialised into db_settings) and the `create_backend()` factory string comparisons are **kept** (they parse the settings string — that is correct). `get_dbtype()` in helpers is also kept (it maps strings for QgsVectorLayer, not a type check).

**Tech Stack:** Python 3, existing `backends/base.py` ABC, `backends/sqlite.py`, `backends/postgresql.py`, `connection.py` (`DbConnectionManager`), pytest.

---

## File map

| File | Change |
|---|---|
| `tools/utils/db_utils/backends/base.py` | Add `is_sqlite()` and `is_postgresql()` returning `False` |
| `tools/utils/db_utils/backends/sqlite.py` | Override `is_sqlite() → True` |
| `tools/utils/db_utils/backends/postgresql.py` | Override `is_postgresql() → True` |
| `tools/utils/db_utils/connection.py` | Delegate `is_postgresql()` to backend; add `is_sqlite()` |
| `tools/utils/db_utils/sqlfile.py` | Replace `dbtype` string param with `is_sqlite: bool` in private helpers |
| `tools/utils/db_utils/schema.py` | 5 instances |
| `tools/utils/db_utils/execution.py` | 1 instance |
| `tools/utils/db_utils/helpers.py` | 2 instances (`get_last_insert_id`, `refresh_spatialite_layer_statistics`) |
| `tools/create_db.py` | 1 instance |
| `tools/loggereditor.py` | 1 instance |
| `tools/import_data_to_db.py` | 4 instances |
| `tools/import_interlab4.py` | 1 instance |
| `tools/utils/midvatten_utils.py` | 1 instance |
| `tools/strat_symbology.py` | 5 instances |
| `tools/sectionplot/data.py` | 2 instances |
| `tools/sectionplot/painters.py` | 1 instance |
| `tools/prepareforqgis2threejs.py` | 1 instance |
| `test/test_db_utils.py` | New tests for `is_sqlite()` / `is_postgresql()` |

---

### Task 1: Add predicate methods to Backend hierarchy and DbConnectionManager

**Files:**
- Modify: `tools/utils/db_utils/backends/base.py`
- Modify: `tools/utils/db_utils/backends/sqlite.py`
- Modify: `tools/utils/db_utils/backends/postgresql.py`
- Modify: `tools/utils/db_utils/connection.py`
- Test: `test/test_db_utils.py`

- [ ] **Step 1: Verify baseline passes**

```bash
cd /path/to/worktree   # .worktrees/dbtype-is-sqlite-is-postgresql or similar
python3 -m pytest test/ -x -q --tb=no -m spatialite 2>&1 | tail -4
```

Expected: all pass, 0 failures.

- [ ] **Step 2: Write failing tests**

Open `test/test_db_utils.py` and find the class `TestDbUtils` (or a spatialite-marked class). Add at the end of it:

```python
@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_is_sqlite_returns_true_for_spatialite(self, mock_messagebar):
    conn = db_utils.DbConnectionManager(self._class_db_settings)
    conn.connect2db()
    try:
        assert conn.is_sqlite() is True
        assert conn.is_postgresql() is False
    finally:
        conn.closedb()
```

Then find the postgis-marked test class and add:

```python
@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_is_postgresql_returns_true_for_postgis(self, mock_messagebar):
    conn = db_utils.DbConnectionManager(self._class_db_settings)
    conn.connect2db()
    try:
        assert conn.is_postgresql() is True
        assert conn.is_sqlite() is False
    finally:
        conn.closedb()
```

- [ ] **Step 3: Run tests to confirm RED**

```bash
python3 -m pytest test/test_db_utils.py -x -q --tb=short -m spatialite -k "is_sqlite"
```

Expected: `AttributeError: 'DbConnectionManager' object has no attribute 'is_sqlite'`

- [ ] **Step 4: Add `is_sqlite()` and `is_postgresql()` to `Backend` base**

In `tools/utils/db_utils/backends/base.py`, after the `dbtype: str` class variable and before the `conn` property, add:

```python
def is_sqlite(self) -> bool:
    """Return True if this is a SQLite (SpatiaLite) backend."""
    return False

def is_postgresql(self) -> bool:
    """Return True if this is a PostgreSQL (PostGIS) backend."""
    return False
```

- [ ] **Step 5: Override in `SQLiteBackend`**

In `tools/utils/db_utils/backends/sqlite.py`, add after the `dbtype = "spatialite"` line:

```python
def is_sqlite(self) -> bool:
    return True
```

- [ ] **Step 6: Override in `PostgreSQLBackend`**

In `tools/utils/db_utils/backends/postgresql.py`, add after the `dbtype = "postgis"` line:

```python
def is_postgresql(self) -> bool:
    return True
```

- [ ] **Step 7: Update `DbConnectionManager`**

In `tools/utils/db_utils/connection.py`, replace the existing `is_postgresql()` method (which currently uses `isinstance`):

```python
# OLD (remove):
def is_postgresql(self) -> bool:
    """Return True if the backend is PostgreSQL (PostGIS)."""
    from midvatten.tools.utils.db_utils.backends.postgresql import PostgreSQLBackend

    return isinstance(self._backend, PostgreSQLBackend)

# NEW (replace with):
def is_sqlite(self) -> bool:
    """Return True if the backend is SQLite (SpatiaLite)."""
    return self._backend.is_sqlite()

def is_postgresql(self) -> bool:
    """Return True if the backend is PostgreSQL (PostGIS)."""
    return self._backend.is_postgresql()
```

Place `is_sqlite()` just before `is_postgresql()` for logical grouping.

- [ ] **Step 8: Run tests to confirm GREEN**

```bash
python3 -m pytest test/test_db_utils.py -x -q --tb=short -m "spatialite or postgis" -k "is_sqlite or is_postgresql"
```

Expected: both tests pass.

- [ ] **Step 9: Run full spatialite suite to confirm no regressions**

```bash
python3 -m pytest test/ -x -q --tb=short -m spatialite 2>&1 | tail -4
```

Expected: same pass count as baseline, 0 failures.

- [ ] **Step 10: Commit**

```bash
git add tools/utils/db_utils/backends/base.py \
        tools/utils/db_utils/backends/sqlite.py \
        tools/utils/db_utils/backends/postgresql.py \
        tools/utils/db_utils/connection.py \
        test/test_db_utils.py
git commit -m "feat(db): add is_sqlite()/is_postgresql() predicates to Backend + DbConnectionManager"
```

---

### Task 2: Replace dbtype checks in db_utils internals

**Files:**
- Modify: `tools/utils/db_utils/sqlfile.py` (lines 24, 38, 67)
- Modify: `tools/utils/db_utils/schema.py` (lines 26, 73, 147, 213, 229)
- Modify: `tools/utils/db_utils/execution.py` (line 66)
- Modify: `tools/utils/db_utils/helpers.py` (lines 44, 480)

- [ ] **Step 1: Fix `sqlfile.py`**

The two private functions currently accept `dbtype: str`. Change them to accept `is_sqlite: bool`:

```python
# OLD:
def _strip_dialect_prefix(line: str, dbtype: str) -> str:
    if dbtype == "spatialite":
        for kw in _SQLITE_KEYWORDS:
            ...
    else:
        for kw in _POSTGRESQL_KEYWORDS:
            ...

def _line_is_for_other_dialect(line: str, dbtype: str) -> bool:
    upper = line.strip().upper()
    if dbtype == "spatialite":
        return any(upper.startswith(kw) for kw in _POSTGRESQL_KEYWORDS)
    return any(upper.startswith(kw) for kw in _SQLITE_KEYWORDS)

# In execute_sqlfile():
    dbtype = dbconnection.dbtype
    lines = [
        _strip_dialect_prefix(line, dbtype)
        for line in lines
        if ... and not _line_is_for_other_dialect(line, dbtype)
    ]

# NEW:
def _strip_dialect_prefix(line: str, is_sqlite: bool) -> str:
    if is_sqlite:
        for kw in _SQLITE_KEYWORDS:
            if line.strip().upper().startswith(kw):
                return lstrip(kw, line.strip()).strip()
    else:
        for kw in _POSTGRESQL_KEYWORDS:
            if line.strip().upper().startswith(kw):
                return lstrip(kw, line.strip()).strip()
    return line.strip()

def _line_is_for_other_dialect(line: str, is_sqlite: bool) -> bool:
    upper = line.strip().upper()
    if is_sqlite:
        return any(upper.startswith(kw) for kw in _POSTGRESQL_KEYWORDS)
    return any(upper.startswith(kw) for kw in _SQLITE_KEYWORDS)

# In execute_sqlfile():
    is_sqlite = dbconnection.is_sqlite()
    lines = [
        _strip_dialect_prefix(line, is_sqlite)
        for line in lines
        if ... and not _line_is_for_other_dialect(line, is_sqlite)
    ]
```

- [ ] **Step 2: Fix `schema.py`**

Replace all five occurrences of `dbconnection.dbtype == "spatialite"`:

```python
# Line 26 — get_tables():
# OLD: if dbconnection.dbtype == "spatialite":
# NEW: if dbconnection.is_sqlite():

# Line 73 — get_table_info():
# OLD: if dbconnection.dbtype == "spatialite":
# NEW: if dbconnection.is_sqlite():

# Line 147 — get_geometry_types() or similar:
# OLD: if dbconnection.dbtype == "spatialite":
# NEW: if dbconnection.is_sqlite():

# Line 213:
# OLD: if dbconnection.dbtype == "spatialite":
# NEW: if dbconnection.is_sqlite():

# Line 229:
# OLD: if dbconnection.dbtype == "spatialite":
# NEW: if dbconnection.is_sqlite():
```

Read the file first to see exact context, then make changes preserving surrounding logic.

- [ ] **Step 3: Fix `execution.py` line 66**

```python
# OLD: if dbconnection.dbtype == "spatialite":
# NEW: if dbconnection.is_sqlite():
```

- [ ] **Step 4: Fix `helpers.py` lines 44 and 480**

```python
# helpers.py:44 — get_last_insert_id():
# OLD: if dbconnection.dbtype == "spatialite":
# NEW: if dbconnection.is_sqlite():

# helpers.py:480 — refresh_spatialite_layer_statistics():
# OLD: if dbconnection.dbtype != "spatialite":
# NEW: if not dbconnection.is_sqlite():
```

Leave `get_dbtype()` at line 77–81 **unchanged** — it maps strings for QgsVectorLayer and is not a type predicate.

- [ ] **Step 5: Run spatialite suite**

```bash
python3 -m pytest test/ -x -q --tb=short -m spatialite 2>&1 | tail -4
```

Expected: same pass count, 0 failures.

- [ ] **Step 6: Commit**

```bash
git add tools/utils/db_utils/sqlfile.py \
        tools/utils/db_utils/schema.py \
        tools/utils/db_utils/execution.py \
        tools/utils/db_utils/helpers.py
git commit -m "refactor(db): replace dbtype string checks with is_sqlite()/is_postgresql() in db_utils internals"
```

---

### Task 3: Replace dbtype checks in tool modules

**Files:**
- Modify: `tools/utils/db_utils/helpers.py` — already done in Task 2
- Modify: `tools/create_db.py` (line 275)
- Modify: `tools/loggereditor.py` (line 219)
- Modify: `tools/import_data_to_db.py` (lines 506, 531, 668, 726)
- Modify: `tools/import_interlab4.py` (line 978)
- Modify: `tools/utils/midvatten_utils.py` (line 515)
- Modify: `tools/strat_symbology.py` (lines 651, 689, 698, 794, 805)
- Modify: `tools/sectionplot/data.py` (lines 92, 215)
- Modify: `tools/sectionplot/painters.py` (line 1070)
- Modify: `tools/prepareforqgis2threejs.py` (line 174)

- [ ] **Step 1: Fix `create_db.py` line 275**

```python
# OLD: if dbconnection.dbtype != "postgis":
# NEW: if not dbconnection.is_postgresql():
```

- [ ] **Step 2: Fix `loggereditor.py` line 219**

```python
# OLD: if dbconnection.dbtype == "spatialite":
# NEW: if dbconnection.is_sqlite():
```

- [ ] **Step 3: Fix `import_data_to_db.py` — 4 instances**

Read the file around lines 506, 531, 668, 726. Make these substitutions:

```python
# Line 506:
# OLD: if dbconnection.dbtype.lower() == "postgis":
# NEW: if dbconnection.is_postgresql():

# Line 531:
# OLD: if dbconnection.dbtype != "postgis"
# NEW: if not dbconnection.is_postgresql()

# Line 668:
# OLD: if dbconnection.dbtype == "spatialite":
# NEW: if dbconnection.is_sqlite():

# Line 726:
# OLD: if dbconnection.dbtype.lower() == "postgis"
# NEW: if dbconnection.is_postgresql()
```

- [ ] **Step 4: Fix `import_interlab4.py` line 978**

```python
# OLD: if dbconnection.dbtype == "postgis"
# NEW: if dbconnection.is_postgresql()
```

- [ ] **Step 5: Fix `midvatten_utils.py` line 515**

```python
# OLD: if dbconnection.dbtype != "spatialite":
# NEW: if not dbconnection.is_sqlite():
```

- [ ] **Step 6: Fix `strat_symbology.py` — 5 instances (lines 651, 689, 698, 794, 805)**

```python
# All five:
# OLD: if dbconnection.dbtype == "spatialite":
# NEW: if dbconnection.is_sqlite():
```

- [ ] **Step 7: Fix `sectionplot/data.py` — 2 instances**

```python
# Line 92:
# OLD: if dbconnection.dbtype == "postgis":
# NEW: if dbconnection.is_postgresql():

# Line 215:
# OLD: if dbconnection.dbtype == "spatialite":
# NEW: if dbconnection.is_sqlite():
```

- [ ] **Step 8: Fix `sectionplot/painters.py` line 1070**

```python
# OLD: if dbconnection.dbtype == "spatialite":
# NEW: if dbconnection.is_sqlite():
```

- [ ] **Step 9: Fix `prepareforqgis2threejs.py` line 174**

```python
# OLD: if self.dbconnection.dbtype == "spatialite":
# NEW: if self.dbconnection.is_sqlite():
```

- [ ] **Step 10: Run spatialite + postgis suites**

```bash
python3 -m pytest test/ -x -q --tb=short -m "spatialite or postgis" 2>&1 | tail -4
```

Expected: same pass counts, 0 failures.

- [ ] **Step 11: Verify no dbtype string comparisons remain (excluding factory and get_dbtype)**

```bash
grep -rn 'dbtype\s*==\|dbtype\s*!=' --include="*.py" tools/ \
  | grep -v "create_backend\|get_dbtype\|dbtype =\|dbtype:\|# "
```

Expected: only `connection.py` factory lines and `sqlfile.py` (none after Task 2 changes). Zero hits in tool modules.

- [ ] **Step 12: Run ruff**

```bash
ruff check --fix tools/ && ruff format tools/
```

- [ ] **Step 13: Commit**

```bash
git add tools/create_db.py \
        tools/loggereditor.py \
        tools/import_data_to_db.py \
        tools/import_interlab4.py \
        tools/utils/midvatten_utils.py \
        tools/strat_symbology.py \
        tools/sectionplot/data.py \
        tools/sectionplot/painters.py \
        tools/prepareforqgis2threejs.py
git commit -m "refactor(tools): replace dbtype string checks with is_sqlite()/is_postgresql() across tool modules"
```
