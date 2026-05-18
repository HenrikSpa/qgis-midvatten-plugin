# Logger Import Performance & UX Improvements

**Date:** 2026-05-18
**Status:** Draft

## Problem

Importing DiverOffice CSV files via the logger import dialog is very slow for
databases with large `w_levels_logger` tables (~1.5M rows). An 8200-row file
causes a multi-minute freeze with no progress feedback, followed by an
unnecessary "Foreign keys will be imported silently" confirmation dialog.

### Root cause

`delete_existing_date_times_from_temptable` in `import_data_to_db.py` builds a
correlated `DELETE … WHERE EXISTS` query that applies `strftime('%Y-%m-%d %H:%M',
d.date_time)` to every row in the destination table, preventing SQLite from
using the `(obsid, date_time)` primary-key index. With 1.5M rows this
effectively becomes a full table scan per temp row.

## Changes

### 1. Index-friendly duplicate datetime check

**File:** `tools/import_data_to_db.py` — `delete_existing_date_times_from_temptable`

Replace the `strftime` equality comparison with a range-based comparison that
allows the PK index to be used:

**Current (SQLite):**
```sql
strftime('%Y-%m-%d %H:%M', d.date_time) = strftime('%Y-%m-%d %H:%M', temp.date_time)
```

**Proposed (SQLite):**
```sql
d.date_time >= (substr(temp.date_time, 1, 16) || ':00')
AND d.date_time < (substr(temp.date_time, 1, 16) || ':60')
```

This applies `substr` only to the temp-table side (small) and does an indexed
range scan on `d.date_time` in the destination table (large). The range
`:00`..`:60` covers all possible second values `00`–`59` within the minute.

**PostgreSQL equivalent:**
```sql
d.date_time >= date_trunc('minute', temp.date_time)
AND d.date_time < date_trunc('minute', temp.date_time) + interval '1 minute'
```

Implementation:
- Remove `truncate_to_minute_sql` usage from `delete_existing_date_times_from_temptable`.
- Build the range condition inline, branching on `dbconnection.is_sqlite()` vs
  `dbconnection.is_postgresql()`.
- The semantics are identical: two date_times are duplicates when they fall in
  the same calendar minute.

### 2. Progress feedback during import

**File:** `tools/import_logger/importer.py` — `start_import`
**File:** `tools/import_data_to_db.py` — `general_import`

Add a `QProgressDialog` in the logger importer that reports phases to the user:

**In `start_import()` (importer.py):**
- Create `QProgressDialog("Importing logger data...", "Cancel", 0, 0, self)`
  (indeterminate mode).
- Before the file-parsing loop: set label to "Parsing file 1 of N..."
  and call `QApplication.processEvents()` after each file.
- Before `general_import()`: set label to "Preparing database import..."

**In `general_import()` (import_data_to_db.py):**
- Add an optional `progress_callback: Optional[Callable[[str], None]]` parameter.
- Call it at phase boundaries:
  - `"Creating temporary table..."` before `list_to_table()`
  - `"Checking for duplicate timestamps..."` before `_remove_duplicate_datetimes()`
  - `"Importing rows..."` before `_build_and_execute_insert()`
- The logger importer provides a callback that updates the progress dialog label
  and calls `QApplication.processEvents()`.
- If the progress dialog is cancelled, the callback raises `UserInterruptError`.

This keeps `MidvDataImporter` UI-agnostic (it just calls a function with a
string) while giving the logger importer full control of the dialog.

### 3. Skip FK confirmation for logger imports

**File:** `tools/import_logger/importer.py` — line 846

Pass `skip_confirmation=True` to `general_import()`:

```python
importer.general_import("w_levels_logger", file_to_import_to_db, skip_confirmation=True)
```

Rationale: the obsid is already validated and confirmed in the earlier
`filter_nonexisting_values_and_ask` step. The "Foreign keys will be imported
silently" dialog adds no value for logger imports and confuses users.

## Scope

- Only the logger importer path is changed (DiverOffice, Levelogger, HOBO).
- `MidvDataImporter.general_import()` gets one new optional parameter
  (`progress_callback`); all other callers are unaffected.
- The duplicate datetime fix applies to all importers that use
  `delete_existing_date_times_from_temptable`, which is correct — the
  performance improvement benefits all imports, not just logger data.
- No schema changes. No new dependencies.

## Testing

- Run existing `test/` suite — the duplicate-check semantics must not change.
- Manual test: import an 8200-row DiverOffice CSV into a database with 1.5M
  rows in `w_levels_logger`. Verify:
  - Import completes in seconds, not minutes.
  - Progress dialog appears and updates during import.
  - No "Foreign keys" confirmation dialog appears.
  - Duplicate rows are correctly skipped (same minute = duplicate).
