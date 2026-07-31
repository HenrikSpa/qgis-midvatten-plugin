> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-07-20 · modified: 2026-07-20 · archived: 2026-07-31

# Logger Editor Save Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` or `superpowers:subagent-driven-development` to implement this plan task by task. Use `superpowers:using-git-worktrees` before implementation and `simplify` after code changes, as required by `CLAUDE.md`. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make LoggerEditor saves scale with the rows and series actually changed, keep PostgreSQL writes index-assisted and genuinely batched, and remove unnecessary plot/reference-series work after a successful save.

**Architecture:** Compute a raw-row-identity save diff before opening the transaction. Exact row writes use the preserved `date_time_raw` value and the raw `(obsid, date_time)` primary key. Range writes keep normalized-instant semantics through the existing backend `normalized_instant_sql()` abstraction, which matches each backend's expression index. Series cleanup derives a small candidate set from the diff and removes all true orphans with one `DELETE ... NOT EXISTS`. PostgreSQL overrides `executemany()` with Psycopg 2's fast batching helper. The Save button performs a lightweight post-save UI refresh and refreshes reference data only when its configured source can have changed.

**Tech Stack:** Python 3, pandas, PyQt/QGIS, SQLite/SpatiaLite, PostgreSQL/PostGIS, psycopg2, pytest

**Scope:**

- `tools/loggereditor.py` — save-diff preparation, exact/range SQL, series cleanup, post-save refresh
- `tools/utils/db_utils/backends/postgresql.py` — genuine PostgreSQL batch execution
- `test/test_loggereditor_series.py` — orphan cleanup and query-count regressions
- `test/test_loggereditor_dupes.py` — duplicate-boundary and raw-identity regressions
- `test/test_wlevels_calc_calibr.py` — range/fallback saves and Save-button refresh behavior
- `test/test_db_utils_backends.py` or a focused new backend test file — PostgreSQL batching contract

**Non-goals:** No database schema/version change, no change to raw `date_time` storage, no change to duplicate-resolution semantics, and no broad LoggerEditor refactor.

---

## Findings this plan addresses

1. Every save on `series_join` currently performs one `SELECT COUNT(*)` per original series, even if no series data changed.
2. `DbConnectionManager.executemany()` reaches Psycopg 2 `cursor.executemany()`, which is effectively repeated execution rather than a fast batch.
3. PostgreSQL exact and range predicates use `date_time::timestamp`, which does not match either the raw primary key or the `midv_to_instant(date_time)` expression index.
4. One unresolved duplicate forces every changed row into the per-row fallback because duplicate rows are removed before contiguous groups are calculated.
5. Clicking Save always calls full `update_plot()` and marks the reference subplot dirty, although the in-memory main plot already contains the edit.

---

### Task 1: Add structural regression tests for save statement counts

**Files:**

- Modify: `test/test_loggereditor_series.py`
- Modify: `test/test_loggereditor_dupes.py`
- Modify: `test/test_wlevels_calc_calibr.py`

- [ ] **Step 1: Add a recording DB-connection test helper**

Wrap a real `DbConnectionManager` or use a small transaction-capable fake that records `execute`, `execute_and_fetchall`, and `executemany` calls. Keep it local to the logger editor tests unless two files need it; only then extract it to a test helper module.

The helper must preserve transaction and rollback behavior so the test exercises `save_to_db()`, not a copied version of its logic.

- [ ] **Step 2: Write a failing unchanged-series query-count test**

Build an editor with many existing series, change only `level_masl`, save, and assert:

- no `SELECT COUNT(*) ... WHERE series_id = ...` is emitted;
- no series cleanup SQL is emitted when assignments and row presence did not change;
- the level edit is still saved.

Avoid wall-clock assertions. The regression contract is the number and shape of SQL statements.

- [ ] **Step 3: Write a failing candidate-orphan test**

Reassign all rows from two old series to a retained series, save, and assert both candidates are removed by one cleanup statement. Also retain the existing end-state assertions proving referenced series are not deleted.

- [ ] **Step 4: Write failing raw-datetime statement tests**

Cover both `2017-02-01 00:00` and `2017-02-01 00:00:00`. For per-row level and `series_id` updates, assert parameters carry each row's `date_time_raw`, and SQL compares raw `date_time` directly rather than wrapping the column in `datetime()` or `::timestamp`.

- [ ] **Step 5: Write a failing duplicate-boundary grouping test**

Use clean changed rows on both sides of an unresolved twin. Assert the statement builder produces separate safe ranges on each side where a range pattern applies, rather than forcing all clean changes into per-row updates or spanning the twin.

- [ ] **Step 6: Run focused tests and confirm the new assertions fail for the intended reasons**

Run:

```bash
python3 -m pytest \
  test/test_loggereditor_series.py \
  test/test_loggereditor_dupes.py \
  test/test_wlevels_calc_calibr.py \
  -m spatialite -x -v
```

Expected: existing tests pass up to the new structural regressions; new tests fail on the current query loop, normalized exact predicate, and global duplicate fallback.

- [ ] **Step 7: Commit the failing tests**

```bash
git add test/test_loggereditor_series.py test/test_loggereditor_dupes.py test/test_wlevels_calc_calibr.py
git commit -m "test(loggereditor): capture save performance regressions"
```

---

### Task 2: Make exact writes use raw row identity and preserve range batching around duplicates

**Files:**

- Modify: `tools/loggereditor.py` — `save_to_db()` diff preparation and `_compute_update_statements()`
- Test: `test/test_loggereditor_dupes.py`
- Test: `test/test_wlevels_calc_calibr.py`

- [ ] **Step 1: Prepare changed rows by `date_time_raw`**

During the compute stage, build the level and series diffs with `date_time_raw` as the unique row identity. Preserve each row's parsed instant and its position in the full buffer. Do not format a parsed `DatetimeIndex` back into a new timestamp string for exact updates.

The prepared exact-update tuple is:

```python
(new_value, obsid, date_time_raw)
```

This must be used for both `level_masl` and `series_id` updates.

- [ ] **Step 2: Use the raw primary key for exact writes**

Build one backend-neutral predicate:

```sql
WHERE obsid = <ph> AND date_time = <ph>
```

This matches the `(obsid, date_time)` primary key and also distinguishes raw duplicate twins. Deletions already follow this pattern and remain unchanged.

- [ ] **Step 3: Build contiguous groups from full-buffer positions**

Pass the original full-buffer row positions to `_compute_update_statements()`. Split whenever positions are non-consecutive. Because unresolved twin rows retain positions in the full buffer, clean rows on opposite sides form different groups automatically.

Remove `force_per_row=has_dups`. A duplicate should block only a range that would cross its position; it must not disable range optimization for unrelated clean periods.

- [ ] **Step 4: Match range predicates to normalized expression indexes**

Obtain the normalized column expression from:

```python
dbconnection.normalized_instant_sql(ident("date_time"))
```

Use it on the column side of `BETWEEN`:

- SQLite: `datetime(date_time) BETWEEN datetime(?) AND datetime(?)`
- PostgreSQL: `midv_to_instant(date_time) BETWEEN %s::timestamp AND %s::timestamp`

Do not duplicate backend function names inside LoggerEditor; use the existing abstraction.

- [ ] **Step 5: Run focused save tests**

Run:

```bash
python3 -m pytest \
  test/test_loggereditor_dupes.py \
  test/test_wlevels_calc_calibr.py \
  -m spatialite -x -v
```

Expected: raw-precision, duplicate safety, delete-twin, trend, range, undo/redo, and failure-stage tests pass.

- [ ] **Step 6: Run PostgreSQL logger editor tests when the test database is available**

Run:

```bash
python3 -m pytest \
  test/test_loggereditor_dupes.py \
  test/test_wlevels_calc_calibr.py \
  -m postgis -x -v
```

Expected: same persistence results as SpatiaLite. If PostgreSQL is unavailable locally, record that explicitly and leave the suite for CI; do not silently treat it as verified.

- [ ] **Step 7: Commit**

```bash
git add tools/loggereditor.py test/test_loggereditor_dupes.py test/test_wlevels_calc_calibr.py
git commit -m "perf(loggereditor): use indexed raw identities on save"
```

---

### Task 3: Replace per-series orphan polling with one candidate cleanup

**Files:**

- Modify: `tools/loggereditor.py` — series diff and orphan cleanup in `save_to_db()`
- Test: `test/test_loggereditor_series.py`

- [ ] **Step 1: Compute candidate orphan IDs before the transaction**

Candidates are existing positive series IDs that may have lost references because of:

- `series_id` reassignment;
- logger-row deletion;
- an explicit removal from `_series_buf`, if that state is reachable.

Derive the candidates from the original and current raw-row diff. Do not scan every key in `_original_series_buf` during the write stage. Exclude negative temporary IDs.

- [ ] **Step 2: Delete candidates with one guarded statement**

After row assignments/deletions have been written, issue no statement when the candidate set is empty. Otherwise execute one parameterized statement shaped as:

```sql
DELETE FROM w_logger_series AS s
WHERE s.id IN (<bound candidate ids>)
  AND NOT EXISTS (
      SELECT 1
      FROM w_levels_logger AS l
      WHERE l.series_id = s.id
  )
```

Use `dbconnection.in_clause()` or `dbconnection.placeholders()` and bound values; do not interpolate IDs. Keep the operation inside the existing transaction.

The `NOT EXISTS` guard is mandatory: a candidate still referenced outside the edited buffer must survive.

- [ ] **Step 3: Preserve in-memory metadata consistency**

Only remove a candidate from `_series_buf` after the database confirms it is orphaned, or return deleted IDs where supported. If cross-backend `RETURNING` handling would complicate this, first derive which candidates have no references with one set-based query, then perform one set-based delete and update the buffer from that result. Never restore the per-ID loop.

- [ ] **Step 4: Run series tests**

Run:

```bash
python3 -m pytest test/test_loggereditor_series.py -m spatialite -x -v
```

Expected: new, assign, edit, undo/redo, orphan cleanup, failure rollback, and no-op series-save tests all pass.

- [ ] **Step 5: Commit**

```bash
git add tools/loggereditor.py test/test_loggereditor_series.py
git commit -m "perf(loggereditor): clean orphan series in one query"
```

---

### Task 4: Make PostgreSQL `executemany()` genuinely batch network work

**Files:**

- Modify: `tools/utils/db_utils/backends/postgresql.py`
- Test: `test/test_db_utils_backends.py` or create `test/test_db_utils_executemany.py`

- [ ] **Step 1: Write a failing PostgreSQL backend unit test**

Construct `PostgreSQLBackend` via `__new__`, attach a mock cursor, patch `psycopg2.extras.execute_batch`, and assert `backend.executemany(sql, params)` delegates to `execute_batch` with a bounded page size. Add an empty-parameter test that performs no cursor call.

Also assert exceptions are logged through `Backend.log_execute_error` and re-raised, preserving the base contract.

- [ ] **Step 2: Override `PostgreSQLBackend.executemany()`**

Import `psycopg2.extras` and implement the PostgreSQL override with `execute_batch`. Use a named module constant for the page size (for example 500 or 1000) so it is testable and tunable. Keep SQLite on native `cursor.executemany()`.

Do not move this optimization into LoggerEditor: all callers of the database facade should receive the correct backend behavior.

- [ ] **Step 3: Run backend unit tests**

Run:

```bash
python3 -m pytest test/test_db_utils_executemany.py -x -v
```

Use the actual filename chosen in Step 1.

- [ ] **Step 4: Run existing DB utility tests**

Run:

```bash
python3 -m pytest test/test_db_utils.py test/test_db_utils_backends.py -x -v
```

Omit a nonexistent file from the command rather than creating an empty compatibility file.

- [ ] **Step 5: Commit**

```bash
git add tools/utils/db_utils/backends/postgresql.py test/test_db_utils_executemany.py
git commit -m "perf(db): batch PostgreSQL executemany calls"
```

Adjust the test path in `git add` if Step 1 extends an existing file.

---

### Task 5: Replace the full post-save replot with a dependency-aware refresh

**Files:**

- Modify: `tools/loggereditor.py` — `_on_save_clicked()`, successful-save bookkeeping, and a small post-save helper
- Test: `test/test_wlevels_calc_calibr.py`
- Test: `test/test_loggereditor_refseries.py` if reference dependency logic is extracted there

- [ ] **Step 1: Write failing Save-button refresh tests**

Assert that a successful `_on_save_clicked()`:

- does not call full `update_plot()`;
- leaves the already-updated main plot data intact;
- refreshes title/history/Series UI state;
- redraws the reference subplot only when a configured reference series reads `w_levels_logger`;
- does not redraw unrelated reference tables;
- does nothing after a failed save.

- [ ] **Step 2: Add a lightweight `_refresh_after_save()` helper**

Move post-save UI-only work into one helper. Recompute line-key/cache state only if temporary series IDs were remapped and that state is required for interaction correctness. Prefer updating those internal IDs directly over clearing/rebuilding axes.

- [ ] **Step 3: Make reference invalidation dependency-aware**

Remove the unconditional `self._ref_subplot_dirty = True` from successful save bookkeeping. Mark and redraw the reference subplot only when at least one configured reference series uses `w_levels_logger`, the only table this editor writes.

If the reference configuration lacks a valid `table` key, treat it as unrelated and let existing configuration validation handle it; do not make Save fail.

- [ ] **Step 4: Run plot and reference-series tests**

Run:

```bash
python3 -m pytest \
  test/test_wlevels_calc_calibr.py \
  test/test_loggereditor_refseries.py \
  test/test_loggereditor_plot_interaction.py \
  -m spatialite -x -v
```

Expected: Save no longer performs a full plot rebuild, while explicit Update Plot, option toggles, selection, and reference refresh controls retain existing behavior.

- [ ] **Step 5: Commit**

```bash
git add tools/loggereditor.py test/test_wlevels_calc_calibr.py test/test_loggereditor_refseries.py
git commit -m "perf(loggereditor): avoid full redraw after save"
```

Only add `test/test_loggereditor_refseries.py` if it changed.

---

### Task 6: Verify correctness and performance characteristics

**Files:**

- Modify if needed: `metadata.txt`
- No schema files

- [ ] **Step 1: Run the full LoggerEditor suite**

Run:

```bash
python3 -m pytest \
  test/test_wlevels_calc_calibr.py \
  test/test_loggereditor_series.py \
  test/test_loggereditor_dupes.py \
  test/test_loggereditor_resolve_ui.py \
  test/test_loggereditor_separation.py \
  test/test_loggereditor_refseries.py \
  test/test_loggereditor_plot_limits.py \
  test/test_loggereditor_plot_interaction.py \
  -m spatialite -x -v
```

- [ ] **Step 2: Run database creation and DB utility tests**

Per repository test order, run:

```bash
python3 -m pytest test/test_create_spatialite_db.py -x -v
python3 -m pytest test/test_db_utils.py test/test_midvatten_utils_db.py -x -v
```

- [ ] **Step 3: Verify query plans on PostgreSQL**

On a representative PostgreSQL database, capture `EXPLAIN (ANALYZE, BUFFERS)` for:

1. an exact raw update predicate (`obsid = ... AND date_time = ...`), expected to use the primary key;
2. a normalized range predicate using `midv_to_instant(date_time)`, expected to use `uq_w_levels_logger_obsid_dt` for a selective range;
3. candidate orphan cleanup, expected to use `idx_wlvllogger_series` inside `NOT EXISTS`.

Planner choices on tiny fixtures are not acceptance failures; use representative cardinality and report the actual plan.

- [ ] **Step 4: Record a non-flaky performance comparison**

Use a diagnostic fixture or script outside the production plugin to record:

- unchanged save with 1, 100, and 1000 series: series-cleanup statement count remains zero;
- reassignment orphaning many series: one cleanup statement;
- trend save of many rows: PostgreSQL batch pages grow as `ceil(changed_rows / page_size)` rather than one network exchange per row;
- one unresolved twin plus two large clean ranges: two range updates, not `N` exact updates;
- Save-button path: zero full `update_plot()` calls.

Report statement counts as the acceptance criterion. Treat elapsed time as supporting evidence only.

- [ ] **Step 5: Lint and format changed files**

Run:

```bash
ruff check --fix \
  tools/loggereditor.py \
  tools/utils/db_utils/backends/postgresql.py \
  test/test_loggereditor_series.py \
  test/test_loggereditor_dupes.py \
  test/test_wlevels_calc_calibr.py \
  test/test_loggereditor_refseries.py \
  test/test_db_utils_executemany.py
ruff format \
  tools/loggereditor.py \
  tools/utils/db_utils/backends/postgresql.py \
  test/test_loggereditor_series.py \
  test/test_loggereditor_dupes.py \
  test/test_wlevels_calc_calibr.py \
  test/test_loggereditor_refseries.py \
  test/test_db_utils_executemany.py
```

Adjust paths to the files actually changed.

- [ ] **Step 6: Run the required simplify review**

Invoke the repository-required `simplify` skill. Apply only behavior-preserving cleanup, then rerun the focused suites affected by any cleanup.

- [ ] **Step 7: Update release notes if this branch is release-bound**

Add a concise `metadata.txt` entry covering faster LoggerEditor saves on series-heavy and PostgreSQL datasets. Do not claim measured timings unless reproduced in Step 4.

- [ ] **Step 8: Final commit**

```bash
git add metadata.txt
git commit -m "docs: note logger editor save performance improvements"
```

Skip this commit if release-note changes are not wanted or `metadata.txt` did not change.

---

## Acceptance criteria

- A level-only save performs no orphan queries when no series references changed.
- Any number of orphan candidates is handled set-wise, without a per-series `COUNT(*)` loop.
- Exact level and `series_id` updates target `(obsid, date_time_raw)` and can use the raw primary key.
- PostgreSQL range writes use `midv_to_instant(date_time)` and match the normalized expression index.
- Unresolved duplicates remain untouched; they split unsafe ranges but do not disable range optimization elsewhere.
- PostgreSQL repeated writes use fast batch pages; SQLite behavior remains unchanged.
- Clicking Save does not rebuild the main plot and only refreshes reference data that can depend on `w_levels_logger`.
- Existing save atomicity, rollback reporting, undo/redo, temporary-series ID remapping, and cross-backend datetime semantics remain intact.
