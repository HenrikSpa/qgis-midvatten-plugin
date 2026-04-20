# Stabilisation follow-ups (deferred)

Notes from the 2026-04-19 risk-based triage of `ai_test`. Each item is a real convention violation that was judged low-severity-and-deferrable during the stabilisation pass. Pick them up as dedicated follow-ups.

## F1 — DONE — cast_date_time_as_epoch now returns (sql, args)

Resolved on branch `stabilisation-followups` via two commits:

- `75f4935` — pin UTC interpretation of the literal path and the column path in `test/test_cast_date_time_as_epoch.py` so any TZ drift would fail fast (both backends: naive `"2024-06-15 12:00:00"` must produce epoch `1718452800`).
- `43147b7` — change `Backend.cast_date_time_as_epoch(date_time=...)` on both `SQLiteBackend` and `PostgreSQLBackend` (plus the `DbConnectionManager` facade and the `db_utils.helpers` wrapper) to return `(sql_fragment, args)`. In column mode the fragment embeds no value and `args` is empty; in literal mode the fragment holds the backend placeholder and `args` is a 1-tuple carrying the user-provided date string. Callers in `tools/loggereditor.py` (`update_level_masl_from_level_masl`, `update_level_masl_from_head`, `delete_range`-style path, and `adjust_trend_func`) now splice both the fragment and its args into the composed SQL, so the date literal is parameter-bound instead of concatenated.

No TZ semantics were changed — the pinned tests pass before and after the refactor.

## F2 — DONE — Export engine SRID values are parameter-bound

Resolved on branch `stabilisation-followups` via two commits (two-step defence as recommended):

- `22b05af` — **boundary coercion.** Both backends now explicitly coerce the raw schema value to `int` at the return of `get_srid()` (`tools/utils/db_utils/backends/sqlite.py`, `postgresql.py`). A compromised schema that returns a non-numeric string now raises `ValueError` before the value can reach any SQL string; `None` (non-spatial table or NULL cell) is preserved. New test `test/test_get_srid_coercion.py` pins this: string coercion, None preservation, and injection rejection, for both backends.
- `5f74128` — **parameter binding.** `tools/export_engine.py` no longer interpolates SRIDs into SQL. `_build_select_sql` now emits `ST_AsBinary(ST_Transform(<col>, <ph>))` and prepends the SRID to the returned args list. `_build_insert_sql` now emits `?`-only forms `ST_GeomFromWKB(?, ?)` and `ST_Transform(ST_GeomFromWKB(?, ?), ?)`, and returns a `(sql, geom_srid_slots)` pair; callers run `_expand_chunk_with_geom_srids` to splice the SRID value(s) into each chunk row at the correct position before `executemany`. Verified empirically that SpatiaLite accepts `?` inside both spatial functions (regression-guard test `test_export_engine_srid_placeholder_binding`).

Net effect: no SRID value reaches SQL as an interpolated substring from either backend.

## F2 original notes (kept for history)

**File:** `tools/export_engine.py:65, 104, 107`

**Example:**
```python
exprs.append(f"ST_AsBinary(ST_Transform({qcol}, {wkb_srid}))")
# …
f"ST_Transform(ST_GeomFromWKB(?, {effective_wkb_srid}), {dest_srid})"
```

**Why it matters:** SRIDs are integers read from the DB schema (`source_conn.get_srid()`). In practice always int-valued and safe; in principle a compromised schema could inject SQL. Also a convention violation.

**Why not fixed in the stabilisation pass:** Parameterizing inside a spatial function call (`ST_Transform(…, ?)`) is awkward and the backend-level test coverage for that is thin. Prefer a targeted fix with a round-trip test per backend once the SRID-pipeline has a test harness.

**Recommended approach:** coerce to `int()` at the boundary where the SRID leaves `get_srid()` (belt-and-braces sanitisation), then separately move to `%s`/`?` bindings with per-backend tests.

## F3 — DONE — Export engine snapshot/clear/reinsert wrapped in `transaction()`

Resolved on branch `f3-export-transaction` via two commits:

- `2d7b5ee` — pin the FK-referenced zz_* snapshot/clear invariant with `test_export_preserves_fk_referenced_zz_snapshot`. The test seeds the dest DB with a `CustomFlow` row in `zz_flowtype` and a `w_flow` row that FK-references it (neither present in source), runs `ExportEngine.export()`, and asserts that both the source's default `zz_flowtype` rows and the dest's `CustomFlow` row are present after the export, the `w_flow` row is still intact, and `PRAGMA foreign_key_check` returns no violations. The test passes against the pre-refactor code (the `PRAGMA foreign_keys = OFF/ON` window around DELETE satisfies the invariant) and continues to pass after the refactor — this is the invariant pinned across the switch.
- `f1c5195` — replace the `PRAGMA foreign_keys = OFF/ON` window in `_snapshot_and_clear_dest_table` with `PRAGMA defer_foreign_keys = ON` inside a per-table `dest_conn.transaction()` block in `ExportEngine.export`. `delete_srids` now runs inside its own `transaction()` block; `VACUUM` stays outside per the `transaction()` contract. Per-table `dest_conn.commit()` calls are removed — the context manager handles the commit on exit. Two SQLite quirks shape the block: `defer_foreign_keys` is only honored inside an open transaction (outside one it silently resets to OFF), and Python's sqlite3 deferred-isolation mode does not issue `BEGIN` until the first DML — so the block issues `BEGIN` explicitly before setting the pragma. The pragma also auto-resets at every COMMIT/ROLLBACK, which is why each table's cycle gets its own transaction rather than one outer transaction.

Net effect: every lookup-table snapshot/clear/reinsert runs atomically with FK enforcement active but deferred to COMMIT, so any data row that FK-references a `zz_*` lookup row stays satisfied across the DELETE step without disabling FK enforcement. Full spatialite suite: 428 passed, 0 failed.
