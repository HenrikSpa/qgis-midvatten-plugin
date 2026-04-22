# Backend Base Class Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move identical `conn`, `cursor`, `commit()`, and `closedb()` boilerplate from both backend subclasses into `Backend` base class, fix `schema` to a class attribute, and add a rollback-before-close to `SQLiteBackend.closedb()`.

**Architecture:** Three files change — `base.py` gains concrete implementations, `sqlite.py` and `postgresql.py` lose the duplicated code. `SQLiteBackend` retains a `closedb()` override that rolls back before closing. No logic changes anywhere else.

**Tech Stack:** Python 3, `abc.ABC`/`abstractmethod`, `sqlite3`, `psycopg2`

---

## Files Modified

| File | Change |
|---|---|
| `tools/utils/db_utils/backends/base.py` | Replace abstract `conn`, `cursor`, `commit`, `closedb` with concrete impls; replace `@property schema` with class attr |
| `tools/utils/db_utils/backends/sqlite.py` | Remove `conn`, `cursor`, `commit`; replace `closedb` with rollback-then-close |
| `tools/utils/db_utils/backends/postgresql.py` | Remove `conn`, `cursor`, `commit`, `closedb`, `schema = "public"` |
| `test/test_db_utils.py` | Add unit test for `SQLiteBackend.closedb()` rollback behaviour |

---

## Task 1: Write failing test for SQLiteBackend.closedb() rollback

**Files:**
- Modify: `test/test_db_utils.py`

- [ ] **Step 1: Add import at top of test file**

Open `test/test_db_utils.py`. After the existing imports add:

```python
from midvatten.tools.utils.db_utils.backends.sqlite import SQLiteBackend
```

- [ ] **Step 2: Append the test class at the bottom of the file**

```python
@pytest.mark.spatialite
class TestSQLiteBackendClosedb:
    def test_closedb_rolls_back_before_close(self):
        """closedb() must call rollback() then close() to discard any lingering transaction."""
        mock_conn = mock.MagicMock()
        mock_conn.cursor.return_value = mock.MagicMock()

        with (
            mock.patch(
                "midvatten.tools.utils.db_utils.backends.sqlite.spatialite_connect",
                return_value=mock_conn,
            ),
            mock.patch("os.path.isfile", return_value=True),
            mock.patch.object(SQLiteBackend, "check_db_is_locked"),
        ):
            backend = SQLiteBackend("/fake/path.db")

        mock_conn.reset_mock()  # discard calls made during __init__
        backend.closedb()

        method_names = [c[0] for c in mock_conn.method_calls]
        assert method_names == ["rollback", "close"], (
            f"Expected ['rollback', 'close'] but got {method_names}"
        )
```

- [ ] **Step 3: Run the test and confirm it FAILS**

```bash
cd /home/hsai1/dev/midv/midvatten
python3 -m pytest test/test_db_utils.py::TestSQLiteBackendClosedb -v
```

Expected: `FAILED — Expected ['rollback', 'close'] but got ['close']`

---

## Task 2: Update base.py

**Files:**
- Modify: `tools/utils/db_utils/backends/base.py`

- [ ] **Step 1: Replace the `schema` property with a class attribute**

Find and remove:
```python
    @property
    def schema(self) -> str:
        """Schema name (e.g. 'public' for PostgreSQL)."""
        return "public"
```

Replace with:
```python
    schema: str = "public"
    """Schema name. Override as a class attribute in subclasses that use a different schema."""
```

- [ ] **Step 2: Replace abstract `conn` and `cursor` with concrete properties**

Find and remove:
```python
    @property
    @abstractmethod
    def conn(self):  # sqlite3.Connection or psycopg2 connection
        pass

    @property
    @abstractmethod
    def cursor(self):  # cursor
        pass
```

Replace with:
```python
    # Subclasses must assign self._conn and self._cursor in __init__.
    @property
    def conn(self):  # sqlite3.Connection or psycopg2 connection
        return self._conn

    @property
    def cursor(self):  # cursor
        return self._cursor
```

- [ ] **Step 3: Replace abstract `commit` and `closedb` with concrete methods**

Find and remove:
```python
    @abstractmethod
    def commit(self) -> None:
        pass

    @abstractmethod
    def closedb(self) -> None:
        pass
```

Replace with:
```python
    def commit(self) -> None:
        self._conn.commit()

    def closedb(self) -> None:
        """Close the database connection. Override in subclasses that need cleanup before close."""
        self._conn.close()
```

- [ ] **Step 4: Verify no syntax errors**

```bash
cd /home/hsai1/dev/midv/midvatten
python3 -c "from midvatten.tools.utils.db_utils.backends.base import Backend; print('OK')"
```

Expected: `OK`

---

## Task 3: Update sqlite.py

**Files:**
- Modify: `tools/utils/db_utils/backends/sqlite.py`

- [ ] **Step 1: Remove the `conn` property**

Find and remove:
```python
    @property
    def conn(self) -> Connection:
        return self._conn

```

- [ ] **Step 2: Remove the `cursor` property**

Find and remove:
```python
    @property
    def cursor(self):
        return self._cursor

```

- [ ] **Step 3: Remove the `commit` method**

Find and remove:
```python
    def commit(self) -> None:
        self._conn.commit()

```

- [ ] **Step 4: Replace the `closedb` method with rollback-before-close**

Find and remove:
```python
    def closedb(self) -> None:
        self._conn.close()
```

Replace with:
```python
    def closedb(self) -> None:
        try:
            self._conn.rollback()
        except Exception:
            pass
        self._conn.close()
```

- [ ] **Step 5: Verify no syntax errors**

```bash
cd /home/hsai1/dev/midv/midvatten
python3 -c "from midvatten.tools.utils.db_utils.backends.sqlite import SQLiteBackend; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Run the new test — it should now pass**

```bash
python3 -m pytest test/test_db_utils.py::TestSQLiteBackendClosedb -v
```

Expected: `PASSED`

---

## Task 4: Update postgresql.py

**Files:**
- Modify: `tools/utils/db_utils/backends/postgresql.py`

- [ ] **Step 1: Remove `schema = "public"` class attribute**

Find and remove this line (near the top of the class, below `dbtype = "postgis"`):
```python
    schema = "public"
```

- [ ] **Step 2: Remove the `conn` property**

Find and remove:
```python
    @property
    def conn(self):
        return self._conn

```

- [ ] **Step 3: Remove the `cursor` property**

Find and remove:
```python
    @property
    def cursor(self):
        return self._cursor

```

- [ ] **Step 4: Remove the `commit` method**

Find and remove:
```python
    def commit(self) -> None:
        self._conn.commit()

```

- [ ] **Step 5: Remove the `closedb` method**

Find and remove:
```python
    def closedb(self) -> None:
        self._conn.close()

```

- [ ] **Step 6: Verify no syntax errors**

```bash
cd /home/hsai1/dev/midv/midvatten
python3 -c "from midvatten.tools.utils.db_utils.backends.postgresql import PostgreSQLBackend; print('OK')"
```

Expected: `OK`

---

## Task 5: Run full test suite and verify

**Files:** None modified.

- [ ] **Step 1: Run the spatialite suite**

```bash
cd /home/hsai1/dev/midv/midvatten
python3 -m pytest test/ -m spatialite -x -q
```

Expected: `419 passed, 0 failed` (223 deselected PostGIS tests)

- [ ] **Step 2: Confirm removed methods are gone from subclasses**

```bash
grep -n "def commit\|def conn\|def cursor\|def closedb\|schema = " \
    tools/utils/db_utils/backends/postgresql.py
```

Expected: no output.

```bash
grep -n "def commit\|def conn\|def cursor" \
    tools/utils/db_utils/backends/sqlite.py
```

Expected: no output. (`closedb` should still appear — that's the override.)

- [ ] **Step 3: Confirm `schema` is a class attribute in base, not a property**

```bash
grep -n "schema" tools/utils/db_utils/backends/base.py | head -5
```

Expected: a class attribute line like `schema: str = "public"`, no `@property`.

- [ ] **Step 4: Commit**

```bash
git add tools/utils/db_utils/backends/base.py \
        tools/utils/db_utils/backends/sqlite.py \
        tools/utils/db_utils/backends/postgresql.py \
        test/test_db_utils.py
git commit -m "Refactor: hoist conn/cursor/commit/closedb boilerplate into Backend base class

- schema is now a class attribute (was @property returning hardcoded string)
- conn, cursor are concrete properties in base (subclasses set _conn/_cursor in __init__)
- commit() and closedb() are concrete in base; no behavior change for PostgreSQL
- SQLiteBackend.closedb() now rolls back before closing to discard lingering transactions
- numeric_datatypes() remains @abstractmethod (fail-fast contract preserved)"
```
