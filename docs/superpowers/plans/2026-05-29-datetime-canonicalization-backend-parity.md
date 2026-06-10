# date_time Duplicate-Rule Backend Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make SpatiaLite and PostGIS enforce one identical "duplicate reading" rule — one row per `(obsid[, extra keys], normalized-second instant)` — **without changing how `date_time` is stored** (precision preserved exactly as observed).

**Architecture:** `date_time` stays raw text on both backends (a date-only `'2015-06-01'` is stored verbatim, never padded). Uniqueness is enforced on a *normalized expression* of `date_time`, not on stored text. SpatiaLite already does this (`datetime(date_time)`); the fix gives PostgreSQL the same semantics via an `IMMUTABLE` safe-normalize function that returns `NULL` on unparseable input (mirroring SQLite's `datetime()→NULL`, so malformed dates escape uniqueness on both backends instead of erroring). The import-time dedup is corrected from minute-granularity to the same normalized-second instant.

**Tech Stack:** Python 3, SQLite/SpatiaLite (expression indexes), PostgreSQL/PostGIS (IMMUTABLE plpgsql function + expression indexes), psycopg2, pandas, pytest.

---

## Background: what's wrong and what we decided (read before implementing)

`date_time` is `text` on **both** backends and is **stored raw** (import does not normalize it — verified). Today three layers disagree on "duplicate":

| Layer | Rule | `00:00` vs `00:00:00` | `00:00` vs `00:00:01` |
|---|---|---|---|
| Import dedup (`delete_existing_date_times_from_temptable`) | same **minute** (`substr(date_time,1,16)`) | dup | **dup (wrong)** |
| SpatiaLite unique indexes | normalized **second** (`datetime(date_time)`) | dup | distinct |
| PostGIS unique indexes | **exact text** (raw `date_time`) | **distinct (wrong)** | distinct |

**Target rule (user decision):** one reading per normalized **second** instant on both backends. `00:00` ≡ `00:00:00` (must not coexist); `00:00` ≠ `00:00:01` (do NOT truncate seconds).

**Decisions made:**
- **Storage is NOT canonicalized** (Option 1). `date_time` is stored exactly as observed; precision (date-only / unknown-time, e.g. `w_qual_lab`, old manual readings) is preserved. Normalization happens only inside the uniqueness check. This is what SpatiaLite already does — PostGIS must catch up.
- **All seven unique indexes stay on both backends.** External (non-Midvatten) queries rely on them. Under this design they are *not* redundant with the primary keys, because they index a *normalized* expression the raw-text PK does not provide.
- **Malformed dates** (`datetime()`/safe-normalize → NULL): leave stored value raw; they escape uniqueness (NULLs are distinct in a unique index) on **both** backends — identical behavior. Report counts during migration; never drop.
- **Collision-resolution during migration:** keep the **earliest** row per instant (lowest `ctid`/`ROWID`) — the project's existing precedent (`export_spatialite.py` already states "keep only the earliest duplicate row per timestamp").

**Why this is mostly a PostgreSQL fix:** SpatiaLite already stores raw + dedups on `datetime(date_time)`. The asymmetry is that PostGIS indexes raw text. So the core work is: (1) give PG a normalized expression index with the same NULL-on-garbage semantics, (2) fix the import dedup granularity, (3) migrate existing PG data.

**Affected tables (all keep their index; only the PG expression changes; SQLite unchanged):**
- `w_levels`, `w_levels_logger`, `comments` — `(obsid, <norm>(date_time))`
- `w_flow` — `(obsid, flowtype, instrumentid, <norm>(date_time))`
- `meteo` — `(obsid, parameter, instrumentid, <norm>(date_time))`
- `w_qual_field` — `(obsid, parameter, <norm>(date_time), COALESCE(unit,'<NULL>'))`
- `w_qual_logger` — `(obsid, parameter, instrument, <norm>(date_time), COALESCE(unit,'<NULL>'))`

where `<norm>` is `datetime` on SQLite and `midv_to_instant` (new) on PG.

**Raw-storage in-place is safe** (verified): no FK references these tables by `(obsid, date_time)`; the one PG view joining on `date_time` (`w_lvls_last_geom`) compares the column to itself; in-code `date_time = ?` lookups use DB-sourced values. **Honor this caveat:** any code comparing a stored `date_time` to an externally-supplied string must normalize that string the same way before comparing.

**Acceptance gate:** a cross-backend parity test — the same import file yields identical row state on SpatiaLite and PostGIS — plus a regression: `00:00` ≡ `00:00:00` deduped; `00:00:01` preserved distinct; a date-only value stored verbatim (not padded) yet still deduped against an explicit-midnight value.

---

## File Structure

- `tools/utils/date_utils.py` — already has `to_YmdHMS`; add `instant_key()` (None on unparseable) used by the import dedup to compute a comparison key **without** mutating stored values.
- `tools/import_data_to_db.py` — (a) in-file dedup must compare on the normalized instant key, not raw text; (b) `delete_existing_date_times_from_temptable` must compare on the normalized expression at second precision, not `substr` minute.
- `definitions/create_db.sql` — add the PG `midv_to_instant` function (POSTGIS section); change the 7 POSTGIS `uq_*` indexes to use it; SpatiaLite lines unchanged.
- `definitions/db_defs.py` — bump `latest_database_version()`.
- `definitions/upgrade_postgresql_<ver>.sql` — new PG upgrade: create function, report collisions/malformed, dedup keep-earliest, drop old raw indexes, create normalized indexes, verification gate.
- `tools/export_spatialite.py` — SpatiaLite path already dedups on `datetime()`; no change required (verify only).
- `test/test_datetime_parity.py` — new cross-backend parity + regression tests.
- `test/test_import_data_to_db.py`, `test/test_date_utils.py` — extend.

---

## Task 1: `instant_key()` helper (normalized comparison key, never stored)

**Files:**
- Modify: `tools/utils/date_utils.py` (after `to_YmdHMS`, ~line 94)
- Test: `test/test_date_utils.py`

- [ ] **Step 1: Write the failing test**

```python
# test/test_date_utils.py
from midvatten.tools.utils import date_utils

def test_instant_key():
    # Same instant -> same key (so 00:00 and 00:00:00 dedup); different second -> different key.
    assert date_utils.instant_key("2015-01-01 00:00") == date_utils.instant_key("2015-01-01 00:00:00")
    assert date_utils.instant_key("2015-01-01 00:00") != date_utils.instant_key("2015-01-01 00:00:01")
    # date-only normalizes to start-of-day instant (matches SQLite datetime())
    assert date_utils.instant_key("2015-06-01") == date_utils.instant_key("2015-06-01 00:00:00")
    # unparseable / empty -> None (escapes uniqueness, like datetime()->NULL)
    assert date_utils.instant_key("garbage") is None
    assert date_utils.instant_key(None) is None
    assert date_utils.instant_key("") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest test/test_date_utils.py::test_instant_key -v`
Expected: FAIL with `AttributeError: ... has no attribute 'instant_key'`

- [ ] **Step 3: Write minimal implementation**

```python
# tools/utils/date_utils.py
def instant_key(value: Union[str, datetime.datetime, datetime.date, None]) -> Union[str, None]:
    """Normalized second-precision instant used ONLY for duplicate detection.

    Returns '%Y-%m-%d %H:%M:%S' or None for empty/unparseable input. This value
    is never stored — date_time is kept exactly as observed. It mirrors SQLite
    datetime(): same instant -> same key; unparseable -> None (escapes uniqueness).
    """
    if value is None or value == "":
        return None
    return to_YmdHMS(value)  # already returns '%Y-%m-%d %H:%M:%S' or None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest test/test_date_utils.py::test_instant_key -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/utils/date_utils.py test/test_date_utils.py
git commit -m "feat: add instant_key normalized duplicate-detection helper"
```

---

## Task 2: In-file import dedup must compare on the normalized instant (storage stays raw)

**Files:**
- Modify: `tools/import_data_to_db.py` — `list_to_table_using_pandas`, the `drop_duplicates` block (~lines 680-686)
- Test: `test/test_import_data_to_db.py` (DeleteExistingDateTimesFromTemptableMixin — both backends)

**Why:** the in-file dedup currently drops duplicates on raw `primary_keys_for_concat` values, so `00:00` and `00:00:00` in the *same file* survive as two rows and then collide on the unique index (insert error). Dedup must use the normalized instant for the *key*, while leaving the stored `date_time` raw.

- [ ] **Step 1: Write the failing test**

```python
# test/test_import_data_to_db.py (in DeleteExistingDateTimesFromTemptableMixin)
@mock.patch("midvatten.tools.import_data_to_db.common_utils.Askuser", mock.MagicMock())
@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_in_file_same_instant_dedups_keeps_raw(self, mock_messagebar):
    db_utils.sql_alter_db("""INSERT INTO obs_points (obsid) VALUES ('rb1')""")
    file_data = [
        ["obsid", "date_time", "level_masl"],
        ["rb1", "2015-01-01 00:00", "1"],     # same instant as next -> one survives
        ["rb1", "2015-01-01 00:00:00", "2"],
        ["rb1", "2015-01-01 00:00:01", "3"],  # distinct second -> kept
    ]
    self.importinstance.general_import(dest_table="w_levels_logger", file_data=file_data)
    rows = db_utils.sql_load_fr_db(
        "SELECT date_time FROM w_levels_logger WHERE obsid='rb1' ORDER BY date_time")[1]
    print(mock_messagebar.mock_calls)
    vals = [r[0] for r in rows]
    # exactly two rows; the surviving same-instant row keeps its RAW text (not padded)
    assert len(vals) == 2
    assert "2015-01-01 00:00:01" in vals
    assert "2015-01-01 00:00" in vals or "2015-01-01 00:00:00" in vals
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest "test/test_import_data_to_db.py::TestDeleteExistingDateTimesFromTemptableSpatialite::test_in_file_same_instant_dedups_keeps_raw" -v`
Expected: FAIL — either three rows present, or a unique-constraint error from the same-instant pair.

- [ ] **Step 3: Implement**

Add module-level import:
```python
# tools/import_data_to_db.py (top imports)
from midvatten.tools.utils.date_utils import instant_key
```

Replace the `drop_duplicates` block in `list_to_table_using_pandas` (~lines 680-686):
```python
        if primary_keys_for_concat:
            len_before = len(df)
            # Dedup on the normalized instant for date_time so '00:00' and
            # '00:00:00' collapse, WITHOUT changing the stored (raw) value.
            subset = list(primary_keys_for_concat)
            if "date_time" in subset and "date_time" in df.columns:
                df["_instant_key"] = df["date_time"].map(instant_key)
                subset = ["_instant_key" if c == "date_time" else c for c in subset]
            df = df.drop_duplicates(subset=subset, keep="first", ignore_index=True)
            df = df.drop(columns=["_instant_key"], errors="ignore")
            len_after = len(df)
            numskipped = len_before - len_after
```

- [ ] **Step 4: Run to verify it passes (both backends)**

Run: `python3 -m pytest "test/test_import_data_to_db.py::TestDeleteExistingDateTimesFromTemptableSpatialite::test_in_file_same_instant_dedups_keeps_raw" -v`
Expected: PASS (Postgis variant verified in CI).

- [ ] **Step 5: Commit**

```bash
git add tools/import_data_to_db.py test/test_import_data_to_db.py
git commit -m "fix: dedup same-instant rows in-file while preserving raw date_time"
```

---

## Task 3: `delete_existing_date_times_from_temptable` — second-instant, not minute

**Files:**
- Modify: `tools/import_data_to_db.py` — `delete_existing_date_times_from_temptable` (lines ~724-763)
- Test: `test/test_import_data_to_db.py`

**Why:** the current `substr(date_time,1,16)` range is minute-granularity (wrongly merges `00:00:00` and `00:00:30`). Compare on the same normalized expression the unique index uses, so it is correct *and* index-assisted.

- [ ] **Step 1: Add failing regression test**

```python
@mock.patch("midvatten.tools.import_data_to_db.common_utils.Askuser", mock.MagicMock())
def test_delete_existing_keeps_distinct_seconds(self):
    db_utils.sql_alter_db("""INSERT INTO obs_points (obsid) VALUES ('o1')""")
    db_utils.sql_alter_db(
        "INSERT INTO w_levels (obsid, date_time, level_masl) VALUES ('o1', '2016-01-01 00:00:00', '1')")
    file_data = [["obsid", "date_time", "level_masl"], ["o1", "2016-01-01 00:00:01", "2"]]
    dbconnection = db_utils.DbConnectionManager()
    try:
        self.importinstance.list_to_table(dbconnection, "w_levels", file_data, ["obsid", "date_time"])
        rows_deleted = self.importinstance.delete_existing_date_times_from_temptable(
            ["obsid", "date_time"], "w_levels", dbconnection)
    finally:
        dbconnection.closedb()
    assert rows_deleted == 0   # different second is NOT a duplicate
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest "test/test_import_data_to_db.py::TestDeleteExistingDateTimesFromTemptableSpatialite::test_delete_existing_keeps_distinct_seconds" -v`
Expected: FAIL — minute-range logic deletes the `00:00:01` row.

- [ ] **Step 3: Implement — normalized-expression equality per backend**

Add a backend method that returns the normalization SQL for a column expression (mirrors the index), in `backends/base.py` + both backends:
```python
# base.py (abstract)
@abstractmethod
def normalized_instant_sql(self, col_expr: str) -> str:
    """SQL expression normalizing a date_time column to a comparable second instant."""
    raise NotImplementedError
# sqlite.py
def normalized_instant_sql(self, col_expr: str) -> str:
    return f"datetime({col_expr})"
# postgresql.py
def normalized_instant_sql(self, col_expr: str) -> str:
    return f"midv_to_instant({col_expr})"   # function created by schema/migration
```
Expose it through the `DbConnectionManager` facade in `connection.py`:
```python
def normalized_instant_sql(self, col_expr: str) -> str:
    return self._backend.normalized_instant_sql(col_expr)
```
Rewrite the method body:
```python
    def delete_existing_date_times_from_temptable(
        self, primary_keys: List[str], dest_table: str, dbconnection: DbConnectionManager,
    ) -> int:
        """Delete temp rows already present in dest at the same normalized instant.

        date_time is compared via the backend's normalized-instant expression
        (the same one the unique index uses), so duplicates are detected at
        second precision and the expression index assists the lookup. Other
        primary-key columns are compared by exact identity.
        """
        temp_ident = dbconnection.ident(self.temptable_name)
        dest_ident = (
            dbconnection.ident(f"{dbconnection.schema}.{dest_table}")
            if dbconnection.is_postgresql() else dbconnection.ident(dest_table)
        )
        conditions = []
        for pk in primary_keys:
            q = dbconnection.ident(pk)
            if pk == "date_time":
                conditions.append(
                    f"{dbconnection.normalized_instant_sql(f'd.{q}')} "
                    f"= {dbconnection.normalized_instant_sql(f'{temp_ident}.{q}')}"
                )
            else:
                conditions.append(f"d.{q} = {temp_ident}.{q}")
        sql = (
            f"DELETE FROM {temp_ident} WHERE EXISTS ("
            f"SELECT 1 FROM {dest_ident} d WHERE {' AND '.join(conditions)})"
        )
        dbconnection.execute(sql)
        return dbconnection.cursor.rowcount
```

- [ ] **Step 4: Run the mixin (both backends)**

Run: `python3 -m pytest "test/test_import_data_to_db.py::TestDeleteExistingDateTimesFromTemptableSpatialite" -v`
Expected: PASS. Update any existing test that encoded the old minute-merge behavior (the change to second precision is intentional per the chosen rule).

- [ ] **Step 5: Commit**

```bash
git add tools/import_data_to_db.py tools/utils/db_utils/backends/base.py tools/utils/db_utils/backends/sqlite.py tools/utils/db_utils/backends/postgresql.py tools/utils/db_utils/connection.py test/test_import_data_to_db.py
git commit -m "fix: import dedup compares normalized second-instant via backend expression"
```

---

## Task 4: PG `midv_to_instant` function + unified PG indexes in `create_db.sql`

**Files:**
- Modify: `definitions/create_db.sql` — add `POSTGIS` function before the index block; change the 7 `POSTGIS` `uq_*`/`*_unique_index_null` lines (171-380 region) to use `midv_to_instant(date_time)`. **Leave all SPATIALITE lines unchanged.**
- Modify: `definitions/db_defs.py` — bump `latest_database_version()`.
- Test: `test/test_create_spatialite_db.py` (SQLite unchanged — should still pass as-is).

- [ ] **Step 1: Add the PG safe-normalize function (POSTGIS-only line in create_db.sql)**

```sql
POSTGIS CREATE OR REPLACE FUNCTION midv_to_instant(t text) RETURNS timestamp AS $$ BEGIN RETURN t::timestamp; EXCEPTION WHEN others THEN RETURN NULL; END; $$ LANGUAGE plpgsql IMMUTABLE;
```
Notes: `timestamp` (no tz) keeps it `IMMUTABLE` (indexable); the exception handler returns `NULL` on unparseable input, mirroring SQLite `datetime()→NULL` so malformed rows escape uniqueness on both backends. (Must be a single line if the SQL-file executor is line-based; verify against `execute_sqlfile` handling, and use the `merge_newlines` path if multi-line is needed.)

- [ ] **Step 2: Change the 7 POSTGIS index lines to use the function**

```sql
POSTGIS CREATE UNIQUE INDEX uq_w_levels_obsid_dt ON w_levels (obsid, midv_to_instant(date_time));
POSTGIS CREATE UNIQUE INDEX uq_w_levels_logger_obsid_dt ON w_levels_logger (obsid, midv_to_instant(date_time));
POSTGIS CREATE UNIQUE INDEX uq_comments_obsid_dt ON comments (obsid, midv_to_instant(date_time));
POSTGIS CREATE UNIQUE INDEX uq_w_flow_obsid_dt ON w_flow (obsid, flowtype, instrumentid, midv_to_instant(date_time));
POSTGIS CREATE UNIQUE INDEX uq_meteo_obsid_dt ON meteo (obsid, parameter, instrumentid, midv_to_instant(date_time));
POSTGIS CREATE UNIQUE INDEX w_qual_field_unit_unique_index_null ON w_qual_field (obsid, parameter, midv_to_instant(date_time), COALESCE(unit, '<NULL>'));
POSTGIS CREATE UNIQUE INDEX w_qual_logger_unit_unique_index_null ON w_qual_logger (obsid, parameter, instrument, midv_to_instant(date_time), COALESCE(unit, '<NULL>'));
```

- [ ] **Step 3: Bump DB version**

In `definitions/db_defs.py`, increment `latest_database_version()` (read current value; keep the existing format).

- [ ] **Step 4: Verify SQLite schema unaffected**

Run: `python3 -m pytest test/test_create_spatialite_db.py -x`
Expected: PASS unchanged (no SpatiaLite lines were touched).

- [ ] **Step 5: Commit**

```bash
git add definitions/create_db.sql definitions/db_defs.py
git commit -m "feat: PG midv_to_instant + normalized unique indexes (parity with SQLite)"
```

---

## Task 5: PostgreSQL upgrade script (function, dedup, reindex, gate)

**Files:**
- Create: `definitions/upgrade_postgresql_<newver>.sql` (model on `upgrade_postgresql_ai_test.sql`)

Order (idempotent; safe to re-run):

- [ ] **Step 1: Create the function** (same `CREATE OR REPLACE ... midv_to_instant` as Task 4 Step 1).

- [ ] **Step 2: Report (RAISE NOTICE), do not destroy**
For each affected table, report (a) same-instant collision groups and (b) malformed (`midv_to_instant IS NULL`) counts:
```sql
DO $$ DECLARE c bigint; BEGIN
  SELECT count(*) INTO c FROM (
    SELECT 1 FROM w_levels_logger GROUP BY obsid, midv_to_instant(date_time)
    HAVING count(*) > 1 AND midv_to_instant(date_time) IS NOT NULL) s;
  RAISE NOTICE 'w_levels_logger same-instant collision groups: %', c;
  SELECT count(*) INTO c FROM w_levels_logger
   WHERE date_time IS NOT NULL AND date_time <> '' AND midv_to_instant(date_time) IS NULL;
  RAISE NOTICE 'w_levels_logger malformed (left raw, escape uniqueness): %', c;
END $$;
-- repeat per affected table with its key columns
```

- [ ] **Step 3: Drop the old raw indexes**
```sql
DROP INDEX IF EXISTS uq_w_levels_obsid_dt;
DROP INDEX IF EXISTS uq_w_levels_logger_obsid_dt;
DROP INDEX IF EXISTS uq_comments_obsid_dt;
DROP INDEX IF EXISTS uq_w_flow_obsid_dt;
DROP INDEX IF EXISTS uq_meteo_obsid_dt;
DROP INDEX IF EXISTS w_qual_field_unit_unique_index_null;
DROP INDEX IF EXISTS w_qual_logger_unit_unique_index_null;
```

- [ ] **Step 4: De-duplicate, keep earliest `ctid`** (storage stays raw; we only delete extra rows)
```sql
DELETE FROM w_levels_logger a USING w_levels_logger b
WHERE a.obsid = b.obsid
  AND midv_to_instant(a.date_time) IS NOT NULL
  AND midv_to_instant(a.date_time) = midv_to_instant(b.date_time)
  AND a.ctid > b.ctid;
-- repeat per table, adding the extra key columns (flowtype/instrumentid/parameter/instrument,
-- and COALESCE(unit,'<NULL>') for w_qual_field / w_qual_logger) to the match condition
```

- [ ] **Step 5: Create the normalized indexes** (same 7 as Task 4 Step 2, with `IF NOT EXISTS`).

- [ ] **Step 6: Verification gate** (must return zero rows or the migration is incomplete)
```sql
SELECT 'w_levels_logger', obsid, midv_to_instant(date_time), count(*)
FROM w_levels_logger WHERE midv_to_instant(date_time) IS NOT NULL
GROUP BY obsid, midv_to_instant(date_time) HAVING count(*) > 1;
-- repeat per table (full key set)
```

- [ ] **Step 7: Commit**

```bash
git add definitions/upgrade_postgresql_<newver>.sql
git commit -m "feat: PG upgrade — midv_to_instant, dedup keep-earliest, normalized indexes"
```

---

## Task 6: SpatiaLite upgrade path — verify only

**Files:** `tools/export_spatialite.py`

- [ ] **Step 1:** Confirm `_DT_DUPLICATE_CHECKS` (lines 18-29) already lists all 7 tables with `datetime(date_time)` expressions and that the export keeps the earliest duplicate. No code change expected — storage stays raw and the SQLite indexes are already normalized.
- [ ] **Step 2:** Run existing export tests: `python3 -m pytest test/test_export_spatialite.py -q`. Expected: PASS. Only act if a test reveals the export does not already dedup at `datetime()` granularity.

---

## Task 7: Cross-backend parity acceptance test + regression

**Files:** Create `test/test_datetime_parity.py`

- [ ] **Step 1: Write the tests** (a mixin run against both `MidvattenTestSpatialiteDbSvImportInstance` and the Postgis equivalent)

```python
# Import ONE file containing: a same-instant pair ('2015-01-01 00:00' / '2015-01-01 00:00:00'),
# a distinct second ('2015-01-01 00:00:01'), a date-only value ('2015-02-02'), and a malformed
# value ('not a date'), into w_levels_logger.
#
# Assertions:
#  1. The resulting row set (obsid, date_time, measurements) is IDENTICAL on both backends
#     (compare utils_for_tests.create_test_string output to one shared reference).
#  2. The same-instant pair collapsed to exactly one row whose date_time is the RAW survivor
#     (e.g. '2015-01-01 00:00' or '...00:00:00' — NOT a forced '...00:00:00' rewrite of a
#     date-only value).
#  3. '2015-01-01 00:00:01' is present (distinct second).
#  4. '2015-02-02' is stored verbatim (date-only, not padded).
#  5. The malformed row is stored verbatim and not deduped against anything.
#  6. Re-importing the same file changes nothing (idempotent).
```

- [ ] **Step 2: Run (SpatiaLite locally, Postgis in CI)**

Run: `python3 -m pytest test/test_datetime_parity.py -v`
Expected: PASS on both markers — this is the acceptance gate.

- [ ] **Step 3: Commit**

```bash
git add test/test_datetime_parity.py
git commit -m "test: cross-backend date_time duplicate-rule parity"
```

---

## Task 8: Full regression + docs

- [ ] **Step 1:** `python3 -m pytest test/test_create_spatialite_db.py test/test_db_utils.py test/test_midvatten_utils_db.py test/test_import_data_to_db.py test/test_export_spatialite.py test/test_datetime_parity.py -q` → all pass (investigate any failure as a real regression; do not edit reference data to mask it).
- [ ] **Step 2:** `ruff check --fix . && ruff format .` → clean (pre-existing repo-wide style findings excepted).
- [ ] **Step 3:** Document: PostgreSQL DBs must run the new upgrade script; SpatiaLite DBs upgrade via export-to-spatialite (already dedups); `date_time` is stored as observed (never padded); duplicates are now "one reading per obsid per second" on both backends; malformed dates are kept raw and excluded from the uniqueness rule.
- [ ] **Step 4:** Commit docs.

---

## Risks / notes for the executor

- **Engine agreement on well-formed formats:** SQLite `datetime()` and PG `midv_to_instant` (`::timestamp`) must classify the *actual* stored formats into the same instants. For values Midvatten imports this holds; the Task-5 Step-2 report surfaces any legacy format where PG yields NULL (or a different instant) so it can be handled before the index is trusted. If a problematic legacy format is found, normalize those specific values with a one-off Python pass using `to_YmdHMS` (single source of truth) rather than diverging the SQL.
- **`execute_sqlfile` line handling:** the `midv_to_instant` function body and any multi-statement DDL must survive the SQL-file executor (it is line-oriented with optional `merge_newlines`). Keep the function on one line or route through the `merge_newlines` path; verify with a created-DB test.
- **Index usability:** the import dedup and lookups must call `datetime(date_time)` / `midv_to_instant(date_time)` exactly as the index defines them, or the planner won't use the expression index. Keep the expression text in one place per backend (`normalized_instant_sql`).
