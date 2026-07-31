> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-04-22 · modified: 2026-04-22 · archived: 2026-07-31

# Backend Base Class Refactor — Design Spec

**Date:** 2026-04-15
**Branch:** `ai_test`

---

## Context

`SQLiteBackend` and `PostgreSQLBackend` both implement four methods/properties — `conn`, `cursor`, `commit()`, `closedb()` — with byte-for-byte identical bodies. The `schema` attribute is defined as a `@property` in `base.py` returning a hardcoded `"public"` string, while `PostgreSQLBackend` overrides it with a plain class attribute of the same value. These inconsistencies add maintenance surface without any semantic value.

This refactor moves the duplicated items into `Backend` so there is one authoritative implementation and subclasses only define what is genuinely dialect-specific.

`closedb()` is treated specially: the base provides a simple `self._conn.close()` default, and `SQLiteBackend` overrides it to add a rollback-before-close (guarded by try/except) to discard any lingering transaction before closing. This is intentionally explicit — the rollback behavior belongs where it is needed rather than being silently swallowed for all backends via a universal default.

---

## What Changes

### `tools/utils/db_utils/backends/base.py`

1. Replace `@property def schema(self) -> str: return "public"` with a class attribute:
   ```python
   schema: str = "public"
   ```

2. Replace `@property @abstractmethod conn` with a concrete property:
   ```python
   @property
   def conn(self):
       return self._conn
   ```

3. Replace `@property @abstractmethod cursor` with a concrete property:
   ```python
   @property
   def cursor(self):
       return self._cursor
   ```

4. Replace `@abstractmethod commit()` with a concrete method:
   ```python
   def commit(self) -> None:
       self._conn.commit()
   ```

5. Replace `@abstractmethod closedb()` with a concrete method (simple default — no rollback):
   ```python
   def closedb(self) -> None:
       self._conn.close()
   ```

6. Add a comment near `conn`/`cursor` documenting the convention:
   > Subclasses must assign `self._conn` and `self._cursor` in `__init__`.

### `tools/utils/db_utils/backends/sqlite.py`

Remove the following (now inherited from base):
- `conn` property
- `cursor` property
- `commit()` method

**Override `closedb()`** with a rollback-before-close implementation (replacing the current trivial one):
```python
def closedb(self) -> None:
    try:
        self._conn.rollback()
    except Exception:
        pass
    self._conn.close()
```
This discards any lingering transaction before closing the connection, which matters for SQLite's deferred transaction model.

No other changes. `_NUMERIC_DATATYPES` class attribute and `numeric_datatypes()` are untouched.

### `tools/utils/db_utils/backends/postgresql.py`

Remove the following (now inherited from base):
- `conn` property
- `cursor` property
- `commit()` method
- `closedb()` method
- `schema = "public"` class attribute (now the base class attribute is the source of truth)

No other changes.

---

## What Does NOT Change

- `numeric_datatypes()` remains `@abstractmethod` in `base.py` and is implemented independently in each subclass. The `_NUMERIC_DATATYPES` class attribute pattern stays in the subclasses. This preserves the fail-fast `TypeError` at instantiation if a future backend omits `numeric_datatypes()`.
- All other methods in both subclasses are untouched.
- For `PostgreSQLBackend`: behavior is unchanged — `closedb()` is now inherited from base (simple close). PostgreSQL uses `ISOLATION_LEVEL_AUTOCOMMIT` so there are no lingering transactions to roll back.
- For `SQLiteBackend`: `closedb()` gains a rollback-before-close. This is a minor behavioral addition (safe: rollback on a clean connection is a no-op).

---

## Trade-offs Accepted

- `conn` and `cursor` in base will be untyped (return type not annotated), whereas `sqlite.py` previously annotated `conn` as `sqlite3.Connection`. This is a minor loss of static analysis precision, accepted in exchange for removing the boilerplate.
- The `_conn`/`_cursor` contract is now enforced by convention + comment rather than by `@abstractmethod`. A subclass that forgets to set them will raise `AttributeError` at first access rather than `TypeError` at instantiation.

---

## Verification

After implementation:

1. Run the non-PostGIS test suite and confirm 419 passed, 0 failed:
   ```bash
   python3 -m pytest test/ -m spatialite -x
   ```

2. Confirm the redundant attributes/methods are gone from the right places:
   ```bash
   # These should NOT appear in postgresql.py at all:
   grep -n "def commit\|def closedb\|def conn\|def cursor\|schema = " \
       tools/utils/db_utils/backends/postgresql.py

   # sqlite.py should only have closedb (the override), not commit/conn/cursor:
   grep -n "def commit\|def conn\|def cursor" \
       tools/utils/db_utils/backends/sqlite.py
   ```
   Expected: no hits in either case.

3. Confirm `numeric_datatypes` is still abstract in base:
   ```bash
   grep -n "numeric_datatypes" tools/utils/db_utils/backends/base.py
   ```
   Expected: `@abstractmethod` decoration present.
