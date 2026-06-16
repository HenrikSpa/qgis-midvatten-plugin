# Clarify import duplicate-removal messages

**Date:** 2026-06-16
**Branch:** `import-dup-messages` (from `ai_test`)
**File:** `tools/import_data_to_db.py` (+ tests)

## Problem

`MidvDataImporter.general_import` removes rows in **two distinct processes**, but the
user-facing messages don't make clear which one caused a removal:

1. **In-file duplicates** — `list_to_table_using_pandas` drops rows that duplicate an
   earlier row *within the imported file* (same primary key, `date_time` normalized to
   the second). Reported as a vague *"N nr of duplicate rows in file was skipped"*.
2. **Already in the database** — `delete_existing_date_times_from_temptable` removes temp
   rows whose `(obsid, datetime(date_time))` already exists in the destination table.
   Reported as *"Skipped N rows with duplicate date_time but of different date format…"*,
   which never mentions the database and is misleading.

A user importing into a non-empty `w_levels` saw "duplicates removed" and could find no
duplicates in their CSV — because the removed rows were duplicates of rows **already in
the DB**, not within the file.

### Latent counting bug

The Process-2 message currently uses `len(removed_rownumbers)` =
`all_rows − rows_surviving_in_temptable`, which **conflates both causes** (in-file dups
were already gone from the temp table). So today's "already-duplicate" count is inflated
by the in-file dups. The reword requires separating the counts at the source.

## Design

Thread two precise, non-overlapping counts up to `general_import`:

- `in_file_dups` — exact `numskipped` from `list_to_table_using_pandas` (already computed;
  return it instead of swallowing it). Also return the dropped original row-numbers so
  Process 2's "subset of skipped rows" excludes them.
- `already_in_db` — exact `cursor.rowcount` from `delete_existing_date_times_from_temptable`.

### New wording

**Process 1 — duplicated within the file** (`list_to_table`):
- Bar: `"%s rows skipped (duplicated within the file)"`
- Log: `"%s rows were skipped because they are duplicated within the imported file itself
  (same primary key, e.g. obsid + date_time). The database was not involved for these."`

**Process 2 — already in the database** (`_remove_duplicate_datetimes`):
- Log: `"%s rows were skipped because a row with the same primary key already exists in the
  database table %s (date_time matched to the second). Subset of skipped rows:\n%s"`
- Confirmation-dialog line: `"%s rows already exist in the database and were skipped."`
- All-removed bar: `"Nothing imported to %s: every row already exists in the database."`

**Final summary** (`general_import`) — parenthetical breakdown built from non-zero clauses:
> `"5 rows imported, 3 excluded for table w_levels (2 already existed in the database, 1
> duplicated within the file). See log message panel for details."`

Any remainder (`nr_excluded − in_file_dups − already_in_db`, e.g. not-null filtering) is
appended as `"N for other reasons"` only when > 0. If both dedup counts are 0, fall back
to the current simple "X imported and Y excluded" message.

## Scope guardrails

- No DB schema changes.
- The confirmation dialog's existing "X out of Y" line stays; its per-cause detail now
  comes from the reworded Process-2 line via `import_messages`.
- `list_to_table`'s new return value is additive — existing callers (tests) ignore it.
- All user-facing strings via `QCoreApplication.translate("midv_data_importer", …)`.

## Tests (`test_import_data_to_db.py`)

- in-file-dups-only → in-file message fires; summary says "duplicated within the file";
  no DB clause.
- already-in-DB-only → DB message fires; summary says "already existed in the database";
  no in-file clause.
- both present → both counts correct and both clauses in the summary.
