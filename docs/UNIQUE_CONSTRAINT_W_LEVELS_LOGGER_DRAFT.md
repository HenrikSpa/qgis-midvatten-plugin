# Draft: UNIQUE constraint on w_levels_logger (obsid, date_time)

## Problem

`w_levels_logger` currently has no database-level uniqueness enforcement on
`(obsid, date_time)`. Duplicate prevention is done at the application level
during import, which is fragile and inconsistent.

An additional pain point: SQLite stores `date_time` as TEXT, so
`'2017-02-01 00:00'` and `'2017-02-01 00:00:00'` are distinct strings even
though they represent the same instant. This caused a bug in `save_to_db()`
(worked around with `datetime(date_time) = datetime(?)`).

## Proposed fix

### SQLite (SpatiaLite)

Expression-based unique index (SQLite does not support expression constraints
inline in CREATE TABLE):

```sql
CREATE UNIQUE INDEX uq_w_levels_logger_obsid_dt
    ON w_levels_logger (obsid, datetime(date_time));
```

`datetime()` normalises both `'2017-02-01 00:00'` and `'2017-02-01 00:00:00'`
to `'2017-02-01 00:00:00'` before comparison, so they correctly collide.

### PostgreSQL (PostGIS)

`date_time` is already a TIMESTAMP column, so a plain unique constraint works:

```sql
ALTER TABLE w_levels_logger
    ADD CONSTRAINT uq_w_levels_logger_obsid_dt UNIQUE (obsid, date_time);
```

## Things to sort out before implementing

### 1. Existing-data migration

Any database with accidental duplicates must have them resolved before the
index can be created. The upgrade script (export-to-spatialite path for SQLite)
needs a de-duplication step — e.g. keep the row with the latest `rowid` and
delete the rest — then create the index.

### 2. Import error handling

Current imports pre-check for duplicates at the application level (in the
import tools). With a DB constraint, inserting a duplicate raises a constraint
violation. Two options:

- **ON CONFLICT** (SQLite): Use `INSERT OR REPLACE` or `INSERT OR IGNORE` on
  the table and drop the pre-check. Simpler and faster.
- **Catch the exception**: Keep pre-check logic but fall back to catching the
  DB exception as a secondary safety net.

The `INSERT OR IGNORE` / `INSERT OR REPLACE` route is cleaner long-term since
it removes the pre-check round-trip. The choice (ignore vs. replace) depends on
the desired semantics per importer.

### 3. Interaction with save_to_db() in LoggerEditor

The workaround added to `save_to_db()` (commit `3b0d099`):
```python
if dbconnection.dbtype == "spatialite":
    dt_eq = f"datetime({ident('date_time')}) = datetime({ph})"
else:
    dt_eq = f"{ident('date_time')} = {ph}"
```
…would become redundant for the uniqueness-checking purpose once the index
exists and normalises incoming data. The WHERE clause workaround could be
removed and replaced with a direct string match against a normalised format —
but only after all existing rows are guaranteed to have the `HH:MM:SS` form
(i.e. after the migration normalises stored strings).

### 4. Schema version bump

Adding the index is a schema change. The DB version constant in
`definitions/db_defs.py` needs incrementing, and the upgrade machinery must
handle the new index creation step.

### 5. PostgreSQL upgrade path

PostgreSQL upgrades are manual per-user (no automated upgrade tool). The
constraint addition needs to be documented in release notes with the SQL to run.

## Files to look at when implementing

- `definitions/create_db.sql` — add the index to the CREATE TABLE block for
  new databases
- `definitions/db_defs.py` — version constants
- `tools/create_db.py` or upgrade path — migration step
- `tools/import_diveroffice.py`, `import_hobologger.py`,
  `import_levelogger.py`, `import_general_csv_gui.py` — import tools that
  currently do application-level duplicate checks; candidates for
  `INSERT OR IGNORE` simplification
- `tools/loggereditor.py` (`save_to_db`) — the `datetime()` workaround may be
  revisable after migration
