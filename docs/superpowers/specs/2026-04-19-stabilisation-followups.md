# Stabilisation follow-ups (deferred)

Notes from the 2026-04-19 risk-based triage of `ai_test`. Each item is a real convention violation that was judged low-severity-and-deferrable during the stabilisation pass. Pick them up as dedicated follow-ups.

## F1 — DONE — cast_date_time_as_epoch now returns (sql, args)

Resolved on branch `stabilisation-followups` via two commits:

- `75f4935` — pin UTC interpretation of the literal path and the column path in `test/test_cast_date_time_as_epoch.py` so any TZ drift would fail fast (both backends: naive `"2024-06-15 12:00:00"` must produce epoch `1718452800`).
- `43147b7` — change `Backend.cast_date_time_as_epoch(date_time=...)` on both `SQLiteBackend` and `PostgreSQLBackend` (plus the `DbConnectionManager` facade and the `db_utils.helpers` wrapper) to return `(sql_fragment, args)`. In column mode the fragment embeds no value and `args` is empty; in literal mode the fragment holds the backend placeholder and `args` is a 1-tuple carrying the user-provided date string. Callers in `tools/loggereditor.py` (`update_level_masl_from_level_masl`, `update_level_masl_from_head`, `delete_range`-style path, and `adjust_trend_func`) now splice both the fragment and its args into the composed SQL, so the date literal is parameter-bound instead of concatenated.

No TZ semantics were changed — the pinned tests pass before and after the refactor.

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
