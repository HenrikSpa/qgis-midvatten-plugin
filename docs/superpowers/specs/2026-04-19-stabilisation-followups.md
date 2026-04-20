# Stabilisation follow-ups (deferred)

Notes from the 2026-04-19 risk-based triage of `ai_test`. Each item is a real convention violation that was judged low-severity-and-deferrable during the stabilisation pass. Pick them up as dedicated follow-ups.

## F1 — `cast_date_time_as_epoch(date_time=...)` embeds the date literal

**Files:**
- `tools/utils/db_utils/backends/sqlite.py:221` — `date_time = f"'{date_time}'"`
- `tools/utils/db_utils/backends/postgresql.py:255` — same pattern

**Why it matters:** Every caller of `cast_date_time_as_epoch(date_time=...)` (notably `tools/loggereditor.py` `adjust_trend_func`) inherits a convention violation: a date string is baked into SQL rather than passed via a placeholder. Not exploitable today because the only callers feed it `long_dateformat(qdatetime.toPyDateTime())` — Qt `QDateTimeEdit` cannot produce an unsafe string — but it violates "never build SQL queries with Python string concatenation".

**Why not fixed in the stabilisation pass:** The helper returns `str` (a SQL fragment). Making it safe means either:

- (a) change the signature to `(sql, args)` and plumb the extra arg through every caller, or
- (b) compute the epoch client-side via Qt/Python and pass as a float — but SQLite's `strftime('%s', …)` and PostgreSQL's `extract(epoch from …::timestamp)` both interpret a naive date string as UTC, while Qt's `QDateTime.toSecsSinceEpoch()` converts `Qt.LocalTime` to UTC epoch. A drop-in switch shifts trend-correction timestamps by the user's TZ offset.

**Recommended approach:** option (a). Add a pinned test first that locks down current TZ behavior (pick one fixed datetime + one non-UTC tz), then change the signature, then run the same test to confirm no drift.

## F2 — Export engine SRID values are not parameter-bound

**File:** `tools/export_engine.py:65, 104, 107`

**Example:**
```python
exprs.append(f"ST_AsBinary(ST_Transform({qcol}, {wkb_srid}))")
# …
f"ST_Transform(ST_GeomFromWKB(?, {effective_wkb_srid}), {dest_srid})"
```

**Why it matters:** SRIDs are integers read from the DB schema (`source_conn.get_srid()`). In practice always int-valued and safe; in principle a compromised schema could inject SQL. Also a convention violation.

**Why not fixed:** Parameterizing inside a spatial function call (`ST_Transform(…, ?)`) is awkward and the backend-level test coverage for that is thin. Prefer a targeted fix with a round-trip test per backend once the SRID-pipeline has a test harness.

**Recommended approach:** coerce to `int()` at the boundary where the SRID leaves `get_srid()` (belt-and-braces sanitisation), then separately move to `%s`/`?` bindings with per-backend tests.

## F3 — Export engine snapshot/clear/reinsert is not wrapped in `transaction()`

**File:** `tools/export_engine.py:219-260` (`_snapshot_and_clear_dest_table` + `_reinsert_dest_snapshot`) and the per-table loop in `export()` at lines 317-335.

**Why it matters:** For each table the flow is: snapshot → DELETE (with PRAGMA foreign_keys OFF/ON) → insert source rows → reinsert snapshot → `dest_conn.commit()`. The whole sequence is uncommitted between the DELETE and the final commit. Safety today relies on SQLite's default non-autocommit mode plus `SQLiteBackend.closedb()` calling `rollback()` before close. A future refactor that changes either would silently make this unsafe (on PostgreSQL dests the helper uses SQLite only — this is SpatiaLite-specific — but the principle still applies).

**Why not fixed in the stabilisation pass:** The work crosses two private methods with code in between (`_export_table`'s chunk loop runs between snapshot and reinsert). Wrapping each table's cycle in `transaction()` means removing the per-table `commit()` and making sure the PRAGMA `foreign_keys = OFF` window behaves correctly inside a transaction (on SQLite, `PRAGMA foreign_keys` is a no-op inside a transaction, which silently changes semantics).

**Recommended approach:** pin current behavior with an integration test that exports a table that has FK references to another table snapshot, then wrap the per-table cycle in `transaction()` and remove the PRAGMA+commit pair.
