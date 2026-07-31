> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-04-18 · modified: 2026-04-18 · archived: 2026-07-31

# Export-to-SpatiaLite Redesign

**Date:** 2026-04-18
**Status:** Approved for implementation

## Problem

`ExportData.export_2_splite` hangs for 5–10 minutes on large databases. Root cause: every table is processed by routing all rows through Python (`execute_and_fetchall` → pandas DataFrame → `executemany` into in-memory temp table → `INSERT INTO dest SELECT FROM temp`). There are no `QApplication.processEvents()` calls within per-table processing, so the Qt main thread is fully blocked. The progress dialog spinner never animates.

## Goal

- Export completes without blocking the UI
- Progress dialog shows table name and row count per table
- Export is cancellable
- Code is purpose-built for export (not routed through import machinery)
- Works for both SpatiaLite and PostgreSQL source databases

---

## Architecture

### New files

| File | Purpose |
|---|---|
| `tools/export_engine.py` | `ExportEngine` — pure data-transfer logic, no Qt |
| `tools/export_worker.py` | `ExportWorker(QObject)` — runs engine in a QThread, emits signals |

### Changed files

| File | Change |
|---|---|
| `tools/export_spatialite.py` | Replace blocking `export_2_splite` call with QThread setup and signal wiring |
| `tools/export_data.py` | `export_2_splite`, `to_sql`, `get_table_data`, `_migrate_logger_source_to_series`, `get_table_rows_with_differences` removed; `write_data` and `to_csv` kept (CSV export path shares `write_data`); `ExportData` retained |

---

## ExportEngine (`tools/export_engine.py`)

Pure Python, no Qt imports. Stateless — takes connections and parameters, yields progress events via a callback.

```python
class ExportEngine:
    CHUNK_SIZE = 5_000

    def export(
        self,
        source_conn: DbConnectionManager,
        dest_conn: DbConnectionManager,
        obsid_points: tuple[str, ...],
        obsid_lines: tuple[str, ...],
        dest_srid: str,
        progress_cb: Callable[[str, int, int], None],  # (table, rows_written, total)
        cancel_flag: threading.Event,
    ) -> str:
        """Run full export. Returns stats string. Raises ExportCancelledError if cancelled."""
```

### Per-table loop

For each table in the export sequence:

1. **Count source rows** — `SELECT count(*) FROM table [WHERE obsid IN (...)]` → used as `total` in progress callback
2. **Execute streaming SELECT** — same geometry transform SQL as today: `ST_AsBinary(ST_Transform(geom, dest_srid))` for geometry columns; plain column references otherwise
3. **Chunk loop** — `cursor.fetchmany(CHUNK_SIZE)` until exhausted:
   - For `w_levels_logger` with migration (see below): transform chunk in Python before writing
   - Write chunk: `dest_conn.cursor.executemany(INSERT_SQL, rows)`
   - Call `progress_cb(tname, rows_written_so_far, total)`
   - Check `cancel_flag.is_set()` → raise `ExportCancelledError`
4. `dest_conn.commit()` after each table

### zz-table merge (replace=True)

For tables in the `data_domains` category:

1. Snapshot current dest rows: `SELECT * FROM dest_table` → list (small)
2. `DELETE FROM dest_table`
3. Stream-insert source rows as normal
4. Re-insert snapshot with `INSERT OR IGNORE` (dest-only rows survive; source rows already present are skipped)

This preserves default lookup rows seeded by `create_db.sql` / `insert_datadomain.sql` while giving source data priority.

### FK topological ordering

Tables are exported in this fixed sequence — each group is in dependency order so no FK constraint fires:

1. `data_domains` — `zz_*` tables (no FKs into data tables), `replace=True`
2. `obs_points` category — `obs_points` first (PKs), then dependent tables in declared order
3. `obs_lines` category — `obs_lines` first
4. `extra_data_tables`
5. `interlab4_import_table`
6. `delete_srids(dest_conn, dest_srid)` + `dest_conn.vacuum()`

**Rule:** the table lists from `midvatten_defs.get_subset_of_tables_fr_db` must never be reordered.

### Midv 1.x migration (w_levels_logger.source → w_logger_series)

Triggered when: source `w_levels_logger` has a `source` column AND dest has `w_logger_series` + `w_levels_logger.series_id`.

Per chunk:
1. Collect distinct `(obsid, source_val)` pairs not yet in `key_to_sid` cache
2. Bulk-insert new `w_logger_series` rows for those pairs; populate cache with returned ids
3. Replace `source` column values with `series_id` integers in the chunk before writing to dest

The `key_to_sid` cache persists across chunks for the full table export.

---

## ExportWorker (`tools/export_worker.py`)

```python
class ExportWorker(QObject):
    table_started = pyqtSignal(str, int)   # table name, total rows
    rows_written  = pyqtSignal(int)        # cumulative rows for this table
    finished      = pyqtSignal(str)        # stats string
    error         = pyqtSignal(str)        # error message

    def __init__(self, source_db_settings, dest_path, obsid_points,
                 obsid_lines, dest_srid): ...
    # Note: w_levels_logger_timezone, w_levels_timezone, locale are used by
    # create_new_spatialite_db (called before the worker starts) — not passed here.

    @pyqtSlot()
    def run(self): ...

    def cancel(self): ...  # sets threading.Event
```

`run()`:
1. Creates source + dest `DbConnectionManager` instances **inside the worker thread** (Qt requires objects with connections to be created in the thread that uses them for SQLite; psycopg2 connections are also not thread-safe to share)
2. Calls `ExportEngine.export(...)` with a progress callback that emits `table_started` / `rows_written`
3. On success: emits `finished(stats)`
4. On `ExportCancelledError`: deletes the partial dest file, emits `finished("")`
5. On other exception: emits `error(traceback)`

---

## ExportSpatialite changes (`tools/export_spatialite.py`)

Replace the blocking section:

```python
# OLD
exportinstance.export_2_splite(new_dbpath, str(dialog.epsg_code))

# NEW
self._run_export_worker(new_dbpath, dialog, obsid_p, obsid_l)
```

`_run_export_worker`:
1. Creates `QProgressDialog` with cancel button and a reasonable max (sum of source row counts, or 0 for indeterminate initially)
2. Creates `ExportWorker`, moves it to a `QThread`
3. Connects signals:
   - `table_started(name, total)` → update dialog label + set maximum
   - `rows_written(n)` → `dialog.setValue(n)`
   - `finished(stats)` → show stats in message bar, close dialog, quit thread
   - `error(msg)` → show critical message bar, close dialog, quit thread
   - `dialog.canceled()` → `worker.cancel()`
4. Starts thread; dialog `exec()` blocks until worker emits `finished` or `error`

---

## Error handling

| Scenario | Behaviour |
|---|---|
| Cancel mid-export | Worker deletes partial dest file; `finished("")` emitted; message bar: "Export cancelled" |
| Source table missing | Log warning, skip table, continue |
| Dest table missing | Log critical, emit `error` |
| FK violation | Caught by `executemany`; logged; that chunk skipped with warning |
| Any unhandled exception | `error(traceback)` emitted; dest file left for inspection |

---

## Tests

All tests in `test/test_export_engine.py` (new file). PostgreSQL variants marked `@pytest.mark.postgis`.

| Test | Covers |
|---|---|
| `test_basic_round_trip` | Small spatialite DB exports and re-imports cleanly |
| `test_obsid_filter` | Only selected obsids appear in dest |
| `test_srid_transform` | Geometry reprojected correctly |
| `test_zz_merge_source_priority` | Source row overrides matching dest default row |
| `test_zz_merge_dest_only_row_survives` | Dest-only default rows are kept |
| `test_logger_migration_source_to_series` | Old `source` column mapped to `w_logger_series` + `series_id` |
| `test_cancellation_deletes_dest_file` | Cancel flag → dest file absent after worker run |
| `test_fk_order_no_constraint_violations` | Full export with FK constraints ON raises no errors |
| `test_worker_signals` | `table_started`, `rows_written`, `finished` emitted in order |
| `test_postgres_source_basic` *(postgis)* | Same as `test_basic_round_trip` with PostgreSQL source |
| `test_postgres_source_logger_migration` *(postgis)* | Migration with PostgreSQL source |

Tests in `test_export_data.py` that exercise `ExportSpatialite.show()` end-to-end will need to be updated — `show()` now delegates to the worker, so tests must either mock the worker or drive the QThread event loop. The coverage goals remain the same; only the test plumbing changes.

---

## What is NOT changed

- `ExportData.to_csv` and CSV export path — untouched
- `create_new_spatialite_db` — untouched
- `midvatten_defs.get_subset_of_tables_fr_db` table lists — order must be preserved
- Database schema — no changes
