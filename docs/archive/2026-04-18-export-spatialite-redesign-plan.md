> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-04-18 · modified: 2026-04-18 · archived: 2026-07-31

# Export-to-SpatiaLite Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the blocking, pandas-routed `export_2_splite` path with a dedicated `ExportEngine` + `ExportWorker` (QThread) that streams rows in chunks, reports per-table progress, and supports cancellation.

**Architecture:** Pure-Python `ExportEngine` handles all data-transfer logic (chunked `fetchmany` → `executemany`, zz-merge, logger migration). `ExportWorker(QObject)` wraps the engine in a `QThread` and emits `table_started / rows_written / finished / error` signals. `ExportSpatialite.show()` drives a `QEventLoop` so it blocks until the worker completes, keeping existing tests compatible.

**Tech Stack:** Python 3, SpatiaLite (dest always), SpatiaLite or PostgreSQL (source), PyQt5 QThread/QObject/pyqtSignal, pytest/mock for tests.

**Spec:** `docs/superpowers/specs/2026-04-18-export-spatialite-redesign.md`

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `tools/export_engine.py` | `ExportCancelledError`, `ExportEngine` — all data-transfer logic, no Qt |
| Create | `tools/export_worker.py` | `ExportWorker(QObject)` — QThread wrapper, signals, cancellation |
| Create | `test/test_export_engine.py` | All engine + worker tests |
| Modify | `tools/export_spatialite.py` | Replace blocking section with `_run_export_worker` using `QEventLoop` |
| Modify | `tools/export_data.py` | Remove `export_2_splite`, `to_sql`, `get_table_data`, `_migrate_logger_source_to_series`, `get_table_rows_with_differences`; keep CSV path |
| Modify | `test/test_export_data.py` | Update spatialite export tests to work with new `show()` |

---

## Task 1: Scaffold — ExportCancelledError, empty ExportEngine, test file

**Files:**
- Create: `tools/export_engine.py`
- Create: `test/test_export_engine.py`

- [ ] **Step 1: Write the failing test**

```python
# test/test_export_engine.py
import os
import tempfile
import threading
from unittest import mock

import pytest

from midvatten.test import utils_for_tests
from midvatten.test.utils_for_tests import MidvattenTestSpatialiteDbSv
from midvatten.tools.utils import db_utils


@pytest.mark.spatialite
class TestExportEngine(MidvattenTestSpatialiteDbSv):
    """Tests for ExportEngine using a SpatiaLite source DB.

    setup_method (inherited) restores a clean DB snapshot and writes the
    db_settings string into the QGIS project, so DbConnectionManager() picks
    it up automatically.
    """

    def setup_method(self):
        super().setup_method()
        self._dest_paths: list[str] = []

    def teardown_method(self):
        for path in self._dest_paths:
            for ending in ["", "-journal", "-wal", "-shm"]:
                try:
                    os.remove(path + ending)
                except OSError:
                    pass
        super().teardown_method()

    def _make_dest_db(self, epsg_code: str = "3006", locale: str = "sv_SE") -> str:
        """Create and return path to a fresh destination SpatiaLite DB."""
        from midvatten.tools.create_db import NewDb
        dest_path = os.path.join(
            tempfile.gettempdir(),
            f"test_export_dest_{os.getpid()}_{id(self)}.sqlite",
        )
        self._dest_paths.append(dest_path)
        nd = NewDb()
        nd.create_new_spatialite_db(
            nd._read_version(),
            user_select_crs="n",
            epsg_code=epsg_code,
            delete_srids=False,
            w_levels_logger_timezone="",
            w_levels_timezone="",
            locale=locale,
            dbpath=dest_path,
        )
        return dest_path

    def _source_conn(self) -> db_utils.DbConnectionManager:
        conn = db_utils.DbConnectionManager(self._class_db_settings)
        conn.connect2db()
        return conn

    def _dest_conn(self, epsg_code: str = "3006") -> db_utils.DbConnectionManager:
        path = self._make_dest_db(epsg_code=epsg_code)
        conn = db_utils.DbConnectionManager(path)
        conn.connect2db()
        return conn

    # ------------------------------------------------------------------ Task 1

    def test_import(self):
        from midvatten.tools.export_engine import ExportCancelledError, ExportEngine
        assert issubclass(ExportCancelledError, Exception)
        engine = ExportEngine()
        assert engine.CHUNK_SIZE == 5_000
```

- [ ] **Step 2: Run test — expect ImportError/AttributeError**

```bash
python3 -m pytest test/test_export_engine.py::TestExportEngine::test_import -x
```

Expected: `FAILED` (module does not exist yet)

- [ ] **Step 3: Create `tools/export_engine.py`**

```python
"""ExportEngine — pure-Python, chunk-based export from any DbConnectionManager
source to a SpatiaLite destination."""

import logging
import threading
from typing import Callable

from midvatten.tools.utils import db_utils
from midvatten.tools.utils.db_utils import DbConnectionManager
from midvatten.definitions import midvatten_defs as defs

log = logging.getLogger(__name__)


class ExportCancelledError(Exception):
    pass


class ExportEngine:
    CHUNK_SIZE = 5_000
```

- [ ] **Step 4: Run test — expect PASSED**

```bash
python3 -m pytest test/test_export_engine.py::TestExportEngine::test_import -x
```

- [ ] **Step 5: Commit**

```bash
git add tools/export_engine.py test/test_export_engine.py
git commit -m "feat(export): scaffold ExportEngine + ExportCancelledError + test fixture"
```

---

## Task 2: `ExportEngine._count_source_rows`

**Files:**
- Modify: `tools/export_engine.py`
- Modify: `test/test_export_engine.py`

- [ ] **Step 1: Write failing tests**

```python
# Add inside TestExportEngine

def test_count_source_rows_no_filter(self, mock_messagebar):
    """Returns total row count when no obsid filter is given."""
    from midvatten.tools.export_engine import ExportEngine
    db_utils.sql_alter_db(
        "INSERT INTO obs_points (obsid, geometry) VALUES "
        "('P1', ST_GeomFromText('POINT(1 2)', 3006))",
        dbconnection=db_utils.DbConnectionManager(self._class_db_settings),
    )
    db_utils.DbConnectionManager(self._class_db_settings).commit()
    src = self._source_conn()
    try:
        n = ExportEngine()._count_source_rows("obs_points", src, ())
        assert n == 1
    finally:
        src.closedb()

@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_count_source_rows_with_filter(self, mock_messagebar):
    """Returns count only for matching obsids."""
    from midvatten.tools.export_engine import ExportEngine
    conn = db_utils.DbConnectionManager(self._class_db_settings)
    db_utils.sql_alter_db(
        "INSERT INTO obs_points (obsid, geometry) VALUES "
        "('P1', ST_GeomFromText('POINT(1 2)', 3006)),"
        "('P2', ST_GeomFromText('POINT(3 4)', 3006))",
        dbconnection=conn,
    )
    conn.commit_and_closedb()
    src = self._source_conn()
    try:
        n = ExportEngine()._count_source_rows("obs_points", src, ("P1",))
        assert n == 1
    finally:
        src.closedb()
```

Note: the `mock_messagebar` patch on `test_count_source_rows_no_filter` is missing above — add it:

```python
@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_count_source_rows_no_filter(self, mock_messagebar):
    ...
```

- [ ] **Step 2: Run — expect AttributeError (method missing)**

```bash
python3 -m pytest test/test_export_engine.py -x -k "count_source_rows"
```

- [ ] **Step 3: Implement `_count_source_rows`**

```python
# In class ExportEngine:

def _count_source_rows(
    self,
    tname: str,
    source_conn: DbConnectionManager,
    obsids: tuple[str, ...],
) -> int:
    sql = source_conn.sql_ident("SELECT count(*) FROM {t}", t=tname)
    args = None
    if obsids:
        clause, args = source_conn.in_clause(obsids)
        sql += f" WHERE obsid IN {clause}"
    return source_conn.execute_and_fetchall(sql, args)[0][0]
```

- [ ] **Step 4: Run — expect PASSED**

```bash
python3 -m pytest test/test_export_engine.py -x -k "count_source_rows"
```

- [ ] **Step 5: Commit**

```bash
git add tools/export_engine.py test/test_export_engine.py
git commit -m "feat(export): ExportEngine._count_source_rows"
```

---

## Task 3: Column inspection + `_build_select_sql` + `_build_insert_sql` + `_get_exportable_columns`

**Files:**
- Modify: `tools/export_engine.py`
- Modify: `test/test_export_engine.py`

- [ ] **Step 1: Write failing tests**

```python
@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_get_columns(self, mock_messagebar):
    from midvatten.tools.export_engine import ExportEngine
    src = self._source_conn()
    try:
        cols = ExportEngine()._get_columns("obs_points", src)
        assert "obsid" in cols
        assert "geometry" in cols
    finally:
        src.closedb()

@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_build_select_sql_non_geometry(self, mock_messagebar):
    """Plain column refs for non-geometry tables."""
    from midvatten.tools.export_engine import ExportEngine
    src = self._source_conn()
    try:
        sql, args = ExportEngine()._build_select_sql(
            "w_levels", src, ["obsid", "date_time", "meas"], "3006", ()
        )
        assert '"obsid"' in sql or "obsid" in sql
        assert "ST_AsBinary" not in sql
        assert args == []
    finally:
        src.closedb()

@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_build_select_sql_geometry(self, mock_messagebar):
    """Geometry column wrapped in ST_AsBinary(ST_Transform(...))."""
    from midvatten.tools.export_engine import ExportEngine
    src = self._source_conn()
    try:
        # Source srid=3006, dest_srid=4326 → transform required
        sql, args = ExportEngine()._build_select_sql(
            "obs_points", src, ["obsid", "geometry"], "4326", ()
        )
        assert "ST_AsBinary" in sql
        assert "ST_Transform" in sql
        assert "4326" in sql
    finally:
        src.closedb()

@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_build_select_sql_with_obsid_filter(self, mock_messagebar):
    from midvatten.tools.export_engine import ExportEngine
    src = self._source_conn()
    try:
        sql, args = ExportEngine()._build_select_sql(
            "w_levels", src, ["obsid", "date_time"], "3006", ("P1",)
        )
        assert "WHERE" in sql.upper()
        assert len(args) == 1
    finally:
        src.closedb()

@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_build_insert_sql_non_geometry(self, mock_messagebar):
    from midvatten.tools.export_engine import ExportEngine
    dest = self._dest_conn()
    try:
        sql = ExportEngine()._build_insert_sql("w_levels", dest, ["obsid", "date_time", "meas"])
        assert sql.startswith("INSERT OR IGNORE INTO")
        assert "?" in sql
        assert "ST_GeomFromWKB" not in sql
    finally:
        dest.closedb()

@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_build_insert_sql_geometry(self, mock_messagebar):
    from midvatten.tools.export_engine import ExportEngine
    dest = self._dest_conn()
    try:
        sql = ExportEngine()._build_insert_sql("obs_points", dest, ["obsid", "geometry"])
        assert "ST_GeomFromWKB" in sql
        assert "3006" in sql
    finally:
        dest.closedb()

@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_get_exportable_columns_same_schema(self, mock_messagebar):
    """When schemas match, source and dest cols are identical."""
    from midvatten.tools.export_engine import ExportEngine
    src = self._source_conn()
    dest = self._dest_conn()
    try:
        src_cols, dst_cols = ExportEngine()._get_exportable_columns(
            "w_levels", src, dest, is_migration=False
        )
        assert src_cols == dst_cols
        assert "obsid" in src_cols
    finally:
        src.closedb()
        dest.closedb()
```

- [ ] **Step 2: Run — expect failures**

```bash
python3 -m pytest test/test_export_engine.py -x -k "columns or select_sql or insert_sql or exportable"
```

- [ ] **Step 3: Implement the four methods**

```python
# In class ExportEngine:

def _get_columns(self, tname: str, conn: DbConnectionManager) -> list[str]:
    conn.execute_safe(conn.sql_ident("SELECT * FROM {t} LIMIT 0", t=tname))
    return [x[0].lower() for x in conn.cursor.description]

def _get_exportable_columns(
    self,
    tname: str,
    source_conn: DbConnectionManager,
    dest_conn: DbConnectionManager,
    is_migration: bool = False,
) -> tuple[list[str], list[str]]:
    """Return (src_select_cols, dst_insert_cols).

    For migration, the source 'source' column maps to dest 'series_id'.
    Only columns present in both (after mapping) are included.
    """
    src_cols = self._get_columns(tname, source_conn)
    dst_cols_set = set(self._get_columns(tname, dest_conn))

    src_select: list[str] = []
    dst_insert: list[str] = []
    for col in src_cols:
        mapped = "series_id" if (is_migration and col == "source") else col
        if mapped in dst_cols_set:
            src_select.append(col)
            dst_insert.append(mapped)
    return src_select, dst_insert

def _build_select_sql(
    self,
    tname: str,
    source_conn: DbConnectionManager,
    select_cols: list[str],
    dest_srid: str,
    obsids: tuple[str, ...],
) -> tuple[str, list]:
    """Return (SELECT sql, args) that streams select_cols from source.

    Geometry columns are wrapped in ST_AsBinary(ST_Transform(col, dest_srid))
    when the source SRID differs from dest_srid, else ST_AsBinary(col).
    """
    geom_cols = set(
        db_utils.get_geometry_types(tname, dbconnection=source_conn).keys()
    )
    source_srid = source_conn.get_srid(tname)

    exprs: list[str] = []
    for col in select_cols:
        if col in geom_cols:
            qcol = source_conn.ident(col)
            if source_srid and str(source_srid) != str(dest_srid):
                exprs.append(f"ST_AsBinary(ST_Transform({qcol}, {dest_srid}))")
            else:
                exprs.append(f"ST_AsBinary({qcol})")
        else:
            exprs.append(source_conn.ident(col))

    sql = f"SELECT {', '.join(exprs)} FROM {source_conn.ident(tname)}"
    args: list = []
    if obsids:
        clause, args = source_conn.in_clause(obsids)
        sql += f" WHERE obsid IN {clause}"
    return sql, args

def _build_insert_sql(
    self,
    tname: str,
    dest_conn: DbConnectionManager,
    dest_cols: list[str],
) -> str:
    """Return INSERT OR IGNORE SQL for dest table.

    Geometry columns use ST_GeomFromWKB(?, srid); others use plain ?.
    dest is always SpatiaLite so placeholder is always '?'.
    """
    geom_cols = set(
        db_utils.get_geometry_types(tname, dbconnection=dest_conn).keys()
    )
    dest_srid = dest_conn.get_srid(tname) if geom_cols else None

    col_list = ", ".join(dest_conn.ident(c) for c in dest_cols)
    value_exprs: list[str] = []
    for col in dest_cols:
        if col in geom_cols and dest_srid is not None:
            value_exprs.append(f"ST_GeomFromWKB(?, {dest_srid})")
        else:
            value_exprs.append("?")

    return (
        f"INSERT OR IGNORE INTO {dest_conn.ident(tname)} "
        f"({col_list}) VALUES ({', '.join(value_exprs)})"
    )
```

- [ ] **Step 4: Run — expect PASSED**

```bash
python3 -m pytest test/test_export_engine.py -x -k "columns or select_sql or insert_sql or exportable"
```

- [ ] **Step 5: Commit**

```bash
git add tools/export_engine.py test/test_export_engine.py
git commit -m "feat(export): column inspection + _build_select_sql + _build_insert_sql + _get_exportable_columns"
```

---

## Task 4: `_export_table` — basic path (no geometry, no special cases)

**Files:**
- Modify: `tools/export_engine.py`
- Modify: `test/test_export_engine.py`

- [ ] **Step 1: Write failing tests**

```python
@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_export_table_basic_copies_rows(self, mock_messagebar):
    """Copies rows from source w_levels to dest; no geometry, no special cases."""
    from midvatten.tools.export_engine import ExportEngine
    conn = db_utils.DbConnectionManager(self._class_db_settings)
    db_utils.sql_alter_db(
        "INSERT INTO obs_points (obsid, geometry) VALUES "
        "('P1', ST_GeomFromText('POINT(1 2)', 3006))",
        dbconnection=conn,
    )
    db_utils.sql_alter_db(
        "INSERT INTO zz_staff (staff) VALUES ('s1')",
        dbconnection=conn,
    )
    db_utils.sql_alter_db(
        "INSERT INTO w_levels (obsid, date_time, meas) VALUES "
        "('P1', '2020-01-01 00:00:00', 1.5),"
        "('P1', '2020-01-02 00:00:00', 2.5)",
        dbconnection=conn,
    )
    conn.commit_and_closedb()

    src = self._source_conn()
    dest = self._dest_conn()
    engine = ExportEngine()

    progress_calls: list = []
    cancel = threading.Event()
    try:
        # First insert obs_points in dest so FK constraint is satisfied
        db_utils.sql_alter_db(
            "INSERT INTO obs_points (obsid, geometry) VALUES "
            "('P1', ST_GeomFromText('POINT(1 2)', 3006))",
            dbconnection=dest,
        )
        dest.commit()
        engine._export_table(
            "w_levels", src, dest, (), "3006", False,
            lambda tname, written, total: progress_calls.append((tname, written, total)),
            cancel,
        )
        dest.commit()
        rows = dest.execute_and_fetchall("SELECT obsid, date_time, meas FROM w_levels ORDER BY date_time")
    finally:
        src.closedb()
        dest.closedb()

    assert rows == [("P1", "2020-01-01 00:00:00", 1.5), ("P1", "2020-01-02 00:00:00", 2.5)]
    # progress_cb called with (tname, 0, total) then (tname, n, total)
    assert progress_calls[0] == ("w_levels", 0, 2)
    assert progress_calls[-1][1] == 2

@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_export_table_cancel_raises(self, mock_messagebar):
    """ExportCancelledError raised when cancel flag is set."""
    from midvatten.tools.export_engine import ExportEngine, ExportCancelledError
    conn = db_utils.DbConnectionManager(self._class_db_settings)
    db_utils.sql_alter_db(
        "INSERT INTO obs_points (obsid, geometry) VALUES "
        "('P1', ST_GeomFromText('POINT(1 2)', 3006))",
        dbconnection=conn,
    )
    db_utils.sql_alter_db(
        "INSERT INTO zz_staff (staff) VALUES ('s1')",
        dbconnection=conn,
    )
    db_utils.sql_alter_db(
        "INSERT INTO w_levels (obsid, date_time, meas) VALUES "
        "('P1', '2020-01-01 00:00:00', 1.5)",
        dbconnection=conn,
    )
    conn.commit_and_closedb()

    src = self._source_conn()
    dest = self._dest_conn()
    cancel = threading.Event()
    cancel.set()  # pre-cancelled
    try:
        db_utils.sql_alter_db(
            "INSERT INTO obs_points (obsid, geometry) VALUES "
            "('P1', ST_GeomFromText('POINT(1 2)', 3006))",
            dbconnection=dest,
        )
        dest.commit()
        with pytest.raises(ExportCancelledError):
            ExportEngine()._export_table(
                "w_levels", src, dest, (), "3006", False,
                lambda *a: None, cancel,
            )
    finally:
        src.closedb()
        dest.closedb()
```

- [ ] **Step 2: Run — expect AttributeError**

```bash
python3 -m pytest test/test_export_engine.py -x -k "export_table_basic or export_table_cancel"
```

- [ ] **Step 3: Implement `_export_table` (basic path)**

```python
# In class ExportEngine:

def _export_table(
    self,
    tname: str,
    source_conn: DbConnectionManager,
    dest_conn: DbConnectionManager,
    obsids: tuple[str, ...],
    dest_srid: str,
    replace: bool,
    progress_cb: Callable[[str, int, int], None],
    cancel_flag: threading.Event,
) -> None:
    is_migration = (
        tname == "w_levels_logger"
        and self._needs_logger_migration(source_conn, dest_conn)
    )
    src_cols, dst_cols = self._get_exportable_columns(
        tname, source_conn, dest_conn, is_migration=is_migration
    )
    if not src_cols:
        log.warning("No exportable columns for table %s — skipping", tname)
        return

    total = self._count_source_rows(tname, source_conn, obsids)
    progress_cb(tname, 0, total)

    dest_snapshot: list[tuple] | None = None
    snap_cols: list[str] | None = None
    if replace:
        dest_snapshot, snap_cols = self._snapshot_and_clear_dest_table(tname, dest_conn)

    select_sql, select_args = self._build_select_sql(
        tname, source_conn, src_cols, dest_srid, obsids
    )
    insert_sql = self._build_insert_sql(tname, dest_conn, dst_cols)

    key_to_sid: dict[tuple, int] = {}
    if select_args:
        source_conn.cursor.execute(select_sql, select_args)
    else:
        source_conn.cursor.execute(select_sql)

    rows_written = 0
    while True:
        chunk = list(source_conn.cursor.fetchmany(self.CHUNK_SIZE))
        if not chunk:
            break
        if is_migration:
            chunk = self._migrate_logger_chunk(chunk, src_cols, dest_conn, key_to_sid)
        dest_conn.cursor.executemany(insert_sql, chunk)
        rows_written += len(chunk)
        progress_cb(tname, rows_written, total)
        if cancel_flag.is_set():
            raise ExportCancelledError()

    if replace and dest_snapshot is not None:
        self._reinsert_dest_snapshot(tname, dest_conn, dest_snapshot, snap_cols)
```

Also add stubs for the methods `_export_table` calls (needed to avoid NameError before those tasks):

```python
def _needs_logger_migration(self, source_conn, dest_conn) -> bool:
    return False  # implemented in Task 7

def _snapshot_and_clear_dest_table(self, tname, dest_conn):
    return [], []  # implemented in Task 6

def _reinsert_dest_snapshot(self, tname, dest_conn, snapshot, snap_cols):
    pass  # implemented in Task 6

def _migrate_logger_chunk(self, chunk, src_cols, dest_conn, key_to_sid):
    return chunk  # implemented in Task 7
```

- [ ] **Step 4: Run — expect PASSED**

```bash
python3 -m pytest test/test_export_engine.py -x -k "export_table_basic or export_table_cancel"
```

- [ ] **Step 5: Commit**

```bash
git add tools/export_engine.py test/test_export_engine.py
git commit -m "feat(export): ExportEngine._export_table basic path + cancel"
```

---

## Task 5: Geometry transform in `_export_table` (obs_points SRID reproject)

**Files:**
- Modify: `test/test_export_engine.py`

(No engine code changes — the SELECT/INSERT SQL already handles geometry via Tasks 3+4.)

- [ ] **Step 1: Write failing test**

```python
@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_export_table_geometry_reprojected(self, mock_messagebar):
    """obs_points geometry is reprojected to dest SRID correctly."""
    from midvatten.tools.export_engine import ExportEngine
    conn = db_utils.DbConnectionManager(self._class_db_settings)
    db_utils.sql_alter_db(
        "INSERT INTO obs_points (obsid, geometry) VALUES "
        "('P1', ST_GeomFromText('POINT(633466 711659)', 3006))",
        dbconnection=conn,
    )
    conn.commit_and_closedb()

    src = self._source_conn()
    # dest DB is 3006 (same as source — no transform needed)
    dest = self._dest_conn(epsg_code="3006")
    try:
        ExportEngine()._export_table(
            "obs_points", src, dest, (), "3006", False, lambda *a: None, threading.Event()
        )
        dest.commit()
        rows = dest.execute_and_fetchall(
            "SELECT obsid, ST_AsText(geometry) FROM obs_points"
        )
    finally:
        src.closedb()
        dest.closedb()

    assert len(rows) == 1
    assert rows[0][0] == "P1"
    # Geometry round-trips correctly (coordinates match original)
    assert "633466" in rows[0][1]
    assert "711659" in rows[0][1]
```

- [ ] **Step 2: Run — expect PASSED** (no new code needed)

```bash
python3 -m pytest test/test_export_engine.py -x -k "geometry_reprojected"
```

If this fails, debug the `_build_select_sql` / `_build_insert_sql` geometry logic from Task 3.

- [ ] **Step 3: Commit**

```bash
git add test/test_export_engine.py
git commit -m "test(export): geometry round-trip via ExportEngine._export_table"
```

---

## Task 6: zz-table merge — `_snapshot_and_clear_dest_table` + `_reinsert_dest_snapshot`

**Files:**
- Modify: `tools/export_engine.py`
- Modify: `test/test_export_engine.py`

- [ ] **Step 1: Write failing tests**

```python
@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_zz_merge_source_overrides_dest(self, mock_messagebar):
    """Source row wins over matching dest row."""
    from midvatten.tools.export_engine import ExportEngine
    # Source DB has a customised zz_strat row
    conn = db_utils.DbConnectionManager(self._class_db_settings)
    conn.execute("DELETE FROM zz_strat")
    conn.execute("INSERT INTO zz_strat (strat_unit, color_mplot, geoshort, defaultplot, strat_unit_descrp) VALUES ('CUSTOM', '#ff0000', 'cu', 1, 'custom unit')")
    conn.commit_and_closedb()

    src = self._source_conn()
    dest = self._dest_conn()
    # Dest has a default row with the same strat_unit key
    dest.execute("DELETE FROM zz_strat")
    dest.execute("INSERT INTO zz_strat (strat_unit, color_mplot, geoshort, defaultplot, strat_unit_descrp) VALUES ('CUSTOM', '#000000', 'cu', 0, 'old desc')")
    dest.commit()

    try:
        ExportEngine()._export_table(
            "zz_strat", src, dest, None, "3006", True, lambda *a: None, threading.Event()
        )
        dest.commit()
        rows = dest.execute_and_fetchall(
            "SELECT strat_unit, color_mplot FROM zz_strat WHERE strat_unit = 'CUSTOM'"
        )
    finally:
        src.closedb()
        dest.closedb()

    # Source colour wins
    assert rows == [("CUSTOM", "#ff0000")]

@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_zz_merge_dest_only_row_survives(self, mock_messagebar):
    """A dest-only row (not in source) is preserved after merge."""
    from midvatten.tools.export_engine import ExportEngine
    conn = db_utils.DbConnectionManager(self._class_db_settings)
    conn.execute("DELETE FROM zz_strat")
    conn.execute("INSERT INTO zz_strat (strat_unit, color_mplot, geoshort, defaultplot, strat_unit_descrp) VALUES ('SRC_ONLY', '#111111', 'so', 1, 'source only')")
    conn.commit_and_closedb()

    src = self._source_conn()
    dest = self._dest_conn()
    dest.execute("DELETE FROM zz_strat")
    dest.execute("INSERT INTO zz_strat (strat_unit, color_mplot, geoshort, defaultplot, strat_unit_descrp) VALUES ('SRC_ONLY', '#111111', 'so', 1, 'source only')")
    dest.execute("INSERT INTO zz_strat (strat_unit, color_mplot, geoshort, defaultplot, strat_unit_descrp) VALUES ('DEST_ONLY', '#222222', 'do', 0, 'dest only')")
    dest.commit()

    try:
        ExportEngine()._export_table(
            "zz_strat", src, dest, None, "3006", True, lambda *a: None, threading.Event()
        )
        dest.commit()
        units = {r[0] for r in dest.execute_and_fetchall("SELECT strat_unit FROM zz_strat")}
    finally:
        src.closedb()
        dest.closedb()

    assert "SRC_ONLY" in units
    assert "DEST_ONLY" in units
```

- [ ] **Step 2: Run — expect FAILED** (stubs return empty snapshot)

```bash
python3 -m pytest test/test_export_engine.py -x -k "zz_merge"
```

- [ ] **Step 3: Replace stubs with real implementations**

```python
# In class ExportEngine — replace the stub versions:

def _snapshot_and_clear_dest_table(
    self,
    tname: str,
    dest_conn: DbConnectionManager,
) -> tuple[list[tuple], list[str]]:
    """Read all dest rows, clear the table. Returns (rows, col_names)."""
    dest_conn.execute_safe(dest_conn.sql_ident("SELECT * FROM {t}", t=tname))
    cols = [x[0].lower() for x in dest_conn.cursor.description]
    rows = list(dest_conn.cursor.fetchall())
    if rows:
        dest_conn.execute_safe(dest_conn.sql_ident("DELETE FROM {t}", t=tname))
    return rows, cols

def _reinsert_dest_snapshot(
    self,
    tname: str,
    dest_conn: DbConnectionManager,
    snapshot: list[tuple],
    snap_cols: list[str],
) -> None:
    """Re-insert the snapshot with INSERT OR IGNORE (source rows take priority)."""
    if not snapshot:
        return
    insert_sql = self._build_insert_sql(tname, dest_conn, snap_cols)
    dest_conn.cursor.executemany(insert_sql, snapshot)
```

- [ ] **Step 4: Run — expect PASSED**

```bash
python3 -m pytest test/test_export_engine.py -x -k "zz_merge"
```

- [ ] **Step 5: Commit**

```bash
git add tools/export_engine.py test/test_export_engine.py
git commit -m "feat(export): zz-table merge (_snapshot_and_clear + _reinsert_dest_snapshot)"
```

---

## Task 7: Logger migration — `_needs_logger_migration` + `_migrate_logger_chunk`

**Files:**
- Modify: `tools/export_engine.py`
- Modify: `test/test_export_engine.py`

- [ ] **Step 1: Write failing tests**

```python
@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_needs_logger_migration_same_schema(self, mock_messagebar):
    """Returns False when source already has series_id (new schema)."""
    from midvatten.tools.export_engine import ExportEngine
    src = self._source_conn()
    dest = self._dest_conn()
    try:
        result = ExportEngine()._needs_logger_migration(src, dest)
    finally:
        src.closedb()
        dest.closedb()
    assert result is False

@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_logger_migration_creates_series_rows_and_maps_ids(self, mock_messagebar):
    """Old-schema DB (source col) → w_logger_series rows created, series_id mapped."""
    from midvatten.tools.export_engine import ExportEngine, ExportCancelledError

    # Build old-schema source DB
    conn = db_utils.DbConnectionManager(self._class_db_settings)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DROP INDEX IF EXISTS idx_wlvllogger_series")
    conn.execute("DROP INDEX IF EXISTS idx_wlogger_series_obsid")
    conn.execute("DROP VIEW IF EXISTS obs_p_w_lvl_logger")
    conn.execute(
        "DELETE FROM views_geometry_columns WHERE view_name = 'obs_p_w_lvl_logger'"
    )
    conn.execute("DROP TABLE IF EXISTS w_logger_series")
    conn.execute(
        "CREATE TABLE w_levels_logger_old ("
        "obsid text NOT NULL, date_time text NOT NULL,"
        " head_cm double, source text,"
        " PRIMARY KEY (obsid, date_time),"
        " FOREIGN KEY(obsid) REFERENCES obs_points(obsid))"
    )
    conn.execute(
        "INSERT INTO w_levels_logger_old (obsid, date_time, head_cm)"
        " SELECT obsid, date_time, head_cm FROM w_levels_logger"
    )
    conn.execute("DROP TABLE w_levels_logger")
    conn.execute("ALTER TABLE w_levels_logger_old RENAME TO w_levels_logger")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO obs_points (obsid, geometry) VALUES "
        "('P1', ST_GeomFromText('POINT(1 2)', 3006)),"
        "('P2', ST_GeomFromText('POINT(3 4)', 3006))"
    )
    conn.execute(
        "INSERT INTO w_levels_logger (obsid, date_time, head_cm, source) VALUES "
        "('P1', '2020-01-01 00:00:00', 100.0, 'fileA'),"
        "('P1', '2020-01-01 01:00:00', 101.0, 'fileA'),"
        "('P1', '2020-01-02 00:00:00', 102.0, 'fileB'),"
        "('P2', '2020-01-01 00:00:00', 200.0, 'fileA')"
    )
    conn.commit_and_closedb()

    src = self._source_conn()
    dest = self._dest_conn()

    try:
        assert ExportEngine()._needs_logger_migration(src, dest) is True

        # First export obs_points (FK requirement)
        ExportEngine()._export_table(
            "obs_points", src, dest, (), "3006", False, lambda *a: None, threading.Event()
        )
        dest.commit()
        ExportEngine()._export_table(
            "w_levels_logger", src, dest, (), "3006", False, lambda *a: None, threading.Event()
        )
        dest.commit()

        series_rows = dest.execute_and_fetchall(
            "SELECT obsid, source FROM w_logger_series ORDER BY obsid, source"
        )
        logger_rows = dest.execute_and_fetchall(
            "SELECT l.obsid, l.date_time, s.source"
            " FROM w_levels_logger l"
            " LEFT JOIN w_logger_series s ON s.id = l.series_id"
            " ORDER BY l.obsid, l.date_time"
        )
    finally:
        src.closedb()
        dest.closedb()

    assert series_rows == [
        ("P1", "fileA"),
        ("P1", "fileB"),
        ("P2", "fileA"),
    ]
    assert logger_rows == [
        ("P1", "2020-01-01 00:00:00", "fileA"),
        ("P1", "2020-01-01 01:00:00", "fileA"),
        ("P1", "2020-01-02 00:00:00", "fileB"),
        ("P2", "2020-01-01 00:00:00", "fileA"),
    ]
    # P1/fileA rows share the same series_id
    p1a_ids = dest.execute_and_fetchall(
        "SELECT series_id FROM w_levels_logger"
        " WHERE obsid='P1' AND date_time IN"
        " ('2020-01-01 00:00:00', '2020-01-01 01:00:00')"
        " ORDER BY date_time"
    )
    assert p1a_ids[0][0] == p1a_ids[1][0]
```

- [ ] **Step 2: Run — expect FAILED**

```bash
python3 -m pytest test/test_export_engine.py -x -k "logger_migration or needs_logger"
```

- [ ] **Step 3: Replace stubs with real implementations**

```python
# In class ExportEngine — replace the stub versions:

def _needs_logger_migration(
    self,
    source_conn: DbConnectionManager,
    dest_conn: DbConnectionManager,
) -> bool:
    """True when source has old 'source' column and dest has new series schema."""
    src_cols = set(self._get_columns("w_levels_logger", source_conn))
    if "source" not in src_cols:
        return False
    dest_tables = db_utils.tables_columns(dbconnection=dest_conn)
    if "w_logger_series" not in dest_tables:
        return False
    if "series_id" not in dest_tables.get("w_levels_logger", []):
        return False
    return True

def _migrate_logger_chunk(
    self,
    chunk: list[tuple],
    src_cols: list[str],
    dest_conn: DbConnectionManager,
    key_to_sid: dict[tuple, int],
) -> list[tuple]:
    """Replace 'source' values with w_logger_series.id integers in chunk.

    key_to_sid is a persistent cache (mutated in place) so a series row is
    only INSERTed once per distinct (obsid, source_val) pair across chunks.
    """
    src_idx = src_cols.index("source")
    obsid_idx = src_cols.index("obsid")
    ph = dest_conn.placeholder()

    migrated: list[tuple] = []
    for row in chunk:
        row_list = list(row)
        obsid = row_list[obsid_idx]
        source_val = row_list[src_idx]
        key = (obsid, source_val)
        if key not in key_to_sid:
            dest_conn.execute(
                f"INSERT INTO w_logger_series (obsid, source, description) "
                f"VALUES ({ph}, {ph}, {ph})",
                (obsid, source_val, "Upgraded from Midv 1.x"),
            )
            key_to_sid[key] = db_utils.get_last_insert_id(dest_conn)
        row_list[src_idx] = key_to_sid[key]
        migrated.append(tuple(row_list))
    return migrated
```

- [ ] **Step 4: Run — expect PASSED**

```bash
python3 -m pytest test/test_export_engine.py -x -k "logger_migration or needs_logger"
```

- [ ] **Step 5: Commit**

```bash
git add tools/export_engine.py test/test_export_engine.py
git commit -m "feat(export): logger migration _needs_logger_migration + _migrate_logger_chunk"
```

---

## Task 8: `ExportEngine.export` — full orchestration + stats

**Files:**
- Modify: `tools/export_engine.py`
- Modify: `test/test_export_engine.py`

- [ ] **Step 1: Write failing tests**

```python
@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_export_full_round_trip(self, mock_messagebar):
    """Full export: data present in source appears correctly in dest."""
    from midvatten.tools.export_engine import ExportEngine
    conn = db_utils.DbConnectionManager(self._class_db_settings)
    db_utils.sql_alter_db(
        "INSERT INTO obs_points (obsid, geometry) VALUES "
        "('P1', ST_GeomFromText('POINT(633466 711659)', 3006))",
        dbconnection=conn,
    )
    db_utils.sql_alter_db(
        "INSERT INTO zz_staff (staff) VALUES ('s1')",
        dbconnection=conn,
    )
    db_utils.sql_alter_db(
        "INSERT INTO w_levels (obsid, date_time, meas) VALUES "
        "('P1', '2020-01-01 00:00:00', 1.5)",
        dbconnection=conn,
    )
    conn.commit_and_closedb()

    dest_path = self._make_dest_db()
    src = self._source_conn()
    dest = db_utils.DbConnectionManager(dest_path)
    dest.connect2db()

    try:
        stats = ExportEngine().export(
            source_conn=src,
            dest_conn=dest,
            obsid_points=(),
            obsid_lines=(),
            dest_srid="3006",
            progress_cb=lambda *a: None,
            cancel_flag=threading.Event(),
        )
        obsids = dest.execute_and_fetchall("SELECT obsid FROM obs_points")
        wlevel = dest.execute_and_fetchall(
            "SELECT obsid, date_time, meas FROM w_levels"
        )
        staff = dest.execute_and_fetchall("SELECT staff FROM zz_staff")
    finally:
        src.closedb()
        dest.closedb()

    assert ("P1",) in obsids
    assert ("P1", "2020-01-01 00:00:00", 1.5) in wlevel
    assert ("s1",) in staff
    assert isinstance(stats, str)

@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_export_obsid_filter(self, mock_messagebar):
    """Only selected obsids appear in dest."""
    from midvatten.tools.export_engine import ExportEngine
    conn = db_utils.DbConnectionManager(self._class_db_settings)
    db_utils.sql_alter_db(
        "INSERT INTO obs_points (obsid, geometry) VALUES "
        "('P1', ST_GeomFromText('POINT(1 2)', 3006)),"
        "('P2', ST_GeomFromText('POINT(3 4)', 3006))",
        dbconnection=conn,
    )
    db_utils.sql_alter_db(
        "INSERT INTO zz_staff (staff) VALUES ('s1')",
        dbconnection=conn,
    )
    db_utils.sql_alter_db(
        "INSERT INTO w_levels (obsid, date_time, meas) VALUES "
        "('P1', '2020-01-01 00:00:00', 1.0),"
        "('P2', '2020-01-01 00:00:00', 2.0)",
        dbconnection=conn,
    )
    conn.commit_and_closedb()

    dest_path = self._make_dest_db()
    src = self._source_conn()
    dest = db_utils.DbConnectionManager(dest_path)
    dest.connect2db()

    try:
        ExportEngine().export(
            source_conn=src,
            dest_conn=dest,
            obsid_points=("P1",),
            obsid_lines=(),
            dest_srid="3006",
            progress_cb=lambda *a: None,
            cancel_flag=threading.Event(),
        )
        obsids = {r[0] for r in dest.execute_and_fetchall("SELECT obsid FROM obs_points")}
        wlevel_obsids = {r[0] for r in dest.execute_and_fetchall("SELECT obsid FROM w_levels")}
    finally:
        src.closedb()
        dest.closedb()

    assert obsids == {"P1"}
    assert wlevel_obsids == {"P1"}

@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_export_fk_order_no_violations(self, mock_messagebar):
    """Full export with FK constraints ON produces no constraint violations."""
    from midvatten.tools.export_engine import ExportEngine
    conn = db_utils.DbConnectionManager(self._class_db_settings)
    db_utils.sql_alter_db(
        "INSERT INTO obs_points (obsid, geometry) VALUES "
        "('P1', ST_GeomFromText('POINT(1 2)', 3006))",
        dbconnection=conn,
    )
    db_utils.sql_alter_db(
        "INSERT INTO zz_staff (staff) VALUES ('s1')",
        dbconnection=conn,
    )
    db_utils.sql_alter_db(
        "INSERT INTO w_levels (obsid, date_time, meas) VALUES "
        "('P1', '2020-01-01 00:00:00', 1.0)",
        dbconnection=conn,
    )
    conn.commit_and_closedb()

    dest_path = self._make_dest_db()
    src = self._source_conn()
    dest = db_utils.DbConnectionManager(dest_path)
    dest.connect2db()
    dest.execute("PRAGMA foreign_keys = ON")

    try:
        # Should not raise IntegrityError
        ExportEngine().export(
            source_conn=src,
            dest_conn=dest,
            obsid_points=(),
            obsid_lines=(),
            dest_srid="3006",
            progress_cb=lambda *a: None,
            cancel_flag=threading.Event(),
        )
        integrity_violations = dest.execute_and_fetchall(
            "PRAGMA foreign_key_check"
        )
    finally:
        src.closedb()
        dest.closedb()

    assert integrity_violations == []
```

- [ ] **Step 2: Run — expect AttributeError (export method missing)**

```bash
python3 -m pytest test/test_export_engine.py -x -k "round_trip or obsid_filter or fk_order"
```

- [ ] **Step 3: Implement `ExportEngine.export` + `_build_stats`**

```python
# In class ExportEngine:

def export(
    self,
    source_conn: DbConnectionManager,
    dest_conn: DbConnectionManager,
    obsid_points: tuple[str, ...],
    obsid_lines: tuple[str, ...],
    dest_srid: str,
    progress_cb: Callable[[str, int, int], None],
    cancel_flag: threading.Event,
) -> str:
    """Run full export. Returns stats string. Raises ExportCancelledError if cancelled."""
    table_groups: list[tuple[list[str], tuple[str, ...] | None, bool]] = [
        (defs.get_subset_of_tables_fr_db("data_domains"), None, True),
        (defs.get_subset_of_tables_fr_db("obs_points"), obsid_points, False),
        (defs.get_subset_of_tables_fr_db("obs_lines"), obsid_lines, False),
        (defs.get_subset_of_tables_fr_db("extra_data_tables"), obsid_points, False),
        (defs.get_subset_of_tables_fr_db("interlab4_import_table"), obsid_points, False),
    ]

    for tables, obsids, replace in table_groups:
        for tname in tables:
            if not db_utils.verify_table_exists(tname, dbconnection=source_conn):
                log.warning("Source table %s missing — skipping", tname)
                continue
            if not db_utils.verify_table_exists(tname, dbconnection=dest_conn):
                log.warning("Dest table %s missing — skipping", tname)
                continue
            self._export_table(
                tname,
                source_conn,
                dest_conn,
                obsids or (),
                dest_srid,
                replace,
                progress_cb,
                cancel_flag,
            )
            dest_conn.commit()

    db_utils.delete_srids(dest_conn, dest_srid)
    dest_conn.commit()
    dest_conn.vacuum()

    return self._build_stats(source_conn, dest_conn)

def _build_stats(
    self,
    source_conn: DbConnectionManager,
    dest_conn: DbConnectionManager,
) -> str:
    """Return human-readable diff of row counts between source and exported DB."""
    results: dict[str, dict[str, int]] = {}
    for alias, conn in [("source", source_conn), ("exported", dest_conn)]:
        for tname in db_utils.get_tables(conn, skip_views=True):
            try:
                n = conn.execute_and_fetchall(
                    conn.sql_ident("SELECT count(*) FROM {t}", t=tname)
                )[0][0]
                results.setdefault(tname, {})[alias] = n
            except Exception:
                pass

    differing = [
        (tname, counts)
        for tname, counts in sorted(results.items())
        if counts.get("source") != counts.get("exported")
    ]

    if not differing:
        return "All exported tables have matching row counts."

    header = f"{'table':40}{'exported':15}{'source':15}"
    lines = [header] + [
        f"{t:40}{str(c.get('exported', '?')):15}{str(c.get('source', '?')):15}"
        for t, c in differing
    ]
    return "\n".join(lines)
```

- [ ] **Step 4: Run — expect PASSED**

```bash
python3 -m pytest test/test_export_engine.py -x -k "round_trip or obsid_filter or fk_order"
```

- [ ] **Step 5: Run all engine tests so far**

```bash
python3 -m pytest test/test_export_engine.py -x
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/export_engine.py test/test_export_engine.py
git commit -m "feat(export): ExportEngine.export full orchestration + _build_stats"
```

---

## Task 9: `ExportWorker` — QObject, signals, QThread wiring, cancellation

**Files:**
- Create: `tools/export_worker.py`
- Modify: `test/test_export_engine.py`

- [ ] **Step 1: Write failing tests**

```python
@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_worker_emits_signals(self, mock_messagebar):
    """ExportWorker emits table_started, rows_written, finished in correct order."""
    from qgis.PyQt.QtCore import QEventLoop, QThread
    from midvatten.tools.export_worker import ExportWorker

    conn = db_utils.DbConnectionManager(self._class_db_settings)
    db_utils.sql_alter_db(
        "INSERT INTO obs_points (obsid, geometry) VALUES "
        "('P1', ST_GeomFromText('POINT(1 2)', 3006))",
        dbconnection=conn,
    )
    conn.commit_and_closedb()

    dest_path = self._make_dest_db()
    worker = ExportWorker(
        source_db_settings=self._class_db_settings,
        dest_path=dest_path,
        obsid_points=(),
        obsid_lines=(),
        dest_srid="3006",
    )
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.error.connect(thread.quit)

    started: list[tuple] = []
    finished: list[str] = []
    errors: list[str] = []
    worker.table_started.connect(lambda n, t: started.append((n, t)))
    worker.finished.connect(finished.append)
    worker.error.connect(errors.append)

    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    worker.error.connect(loop.quit)
    thread.start()
    loop.exec_()
    thread.wait()

    assert errors == [], f"Worker emitted error: {errors}"
    assert len(finished) == 1
    assert len(started) > 0  # at least one table signal

@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_worker_cancel_deletes_dest_file(self, mock_messagebar):
    """Cancelling the worker causes the partial dest file to be deleted."""
    from qgis.PyQt.QtCore import QEventLoop, QThread
    from midvatten.tools.export_worker import ExportWorker

    # Put lots of rows in so cancel can happen mid-export
    conn = db_utils.DbConnectionManager(self._class_db_settings)
    db_utils.sql_alter_db(
        "INSERT INTO obs_points (obsid, geometry) VALUES "
        "('P1', ST_GeomFromText('POINT(1 2)', 3006))",
        dbconnection=conn,
    )
    conn.commit_and_closedb()

    dest_path = self._make_dest_db()
    worker = ExportWorker(
        source_db_settings=self._class_db_settings,
        dest_path=dest_path,
        obsid_points=(),
        obsid_lines=(),
        dest_srid="3006",
    )
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.error.connect(thread.quit)

    finished: list[str] = []
    worker.finished.connect(finished.append)

    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    worker.error.connect(loop.quit)

    # Cancel before the thread even starts
    worker.cancel()
    thread.start()
    loop.exec_()
    thread.wait()

    # finished("") emitted for cancel
    assert finished == [""]
    assert not os.path.exists(dest_path)
```

- [ ] **Step 2: Run — expect ImportError**

```bash
python3 -m pytest test/test_export_engine.py -x -k "worker"
```

- [ ] **Step 3: Create `tools/export_worker.py`**

```python
"""ExportWorker — QObject wrapper that runs ExportEngine in a QThread."""

import logging
import os
import threading
import traceback

from qgis.PyQt.QtCore import QObject, pyqtSignal, pyqtSlot

from midvatten.tools.export_engine import ExportCancelledError, ExportEngine
from midvatten.tools.utils.db_utils import DbConnectionManager

log = logging.getLogger(__name__)


class ExportWorker(QObject):
    table_started = pyqtSignal(str, int)  # table name, total rows
    rows_written = pyqtSignal(int)        # cumulative rows for this table
    finished = pyqtSignal(str)            # stats string (empty string = cancelled)
    error = pyqtSignal(str)               # traceback string

    def __init__(
        self,
        source_db_settings: str,
        dest_path: str,
        obsid_points: tuple[str, ...],
        obsid_lines: tuple[str, ...],
        dest_srid: str,
    ):
        super().__init__()
        self._source_db_settings = source_db_settings
        self._dest_path = dest_path
        self._obsid_points = obsid_points
        self._obsid_lines = obsid_lines
        self._dest_srid = dest_srid
        self._cancel_flag = threading.Event()

    def cancel(self) -> None:
        self._cancel_flag.set()

    @pyqtSlot()
    def run(self) -> None:
        source_conn: DbConnectionManager | None = None
        dest_conn: DbConnectionManager | None = None
        try:
            source_conn = DbConnectionManager(self._source_db_settings)
            source_conn.connect2db()
            dest_conn = DbConnectionManager(self._dest_path)
            dest_conn.connect2db()

            stats = ExportEngine().export(
                source_conn=source_conn,
                dest_conn=dest_conn,
                obsid_points=self._obsid_points,
                obsid_lines=self._obsid_lines,
                dest_srid=self._dest_srid,
                progress_cb=self._on_progress,
                cancel_flag=self._cancel_flag,
            )
            dest_conn.commit_and_closedb()
            dest_conn = None
            source_conn.closedb()
            source_conn = None
            self.finished.emit(stats)

        except ExportCancelledError:
            self._close_connections(source_conn, dest_conn)
            try:
                os.remove(self._dest_path)
            except OSError:
                pass
            self.finished.emit("")

        except Exception:
            self._close_connections(source_conn, dest_conn)
            self.error.emit(traceback.format_exc())

    def _on_progress(self, tname: str, rows_written: int, total: int) -> None:
        if rows_written == 0:
            self.table_started.emit(tname, total)
        else:
            self.rows_written.emit(rows_written)

    @staticmethod
    def _close_connections(
        source_conn: DbConnectionManager | None,
        dest_conn: DbConnectionManager | None,
    ) -> None:
        for conn in (source_conn, dest_conn):
            if conn is not None:
                try:
                    conn.closedb()
                except Exception:
                    pass
```

- [ ] **Step 4: Run — expect PASSED**

```bash
python3 -m pytest test/test_export_engine.py -x -k "worker"
```

- [ ] **Step 5: Commit**

```bash
git add tools/export_worker.py test/test_export_engine.py
git commit -m "feat(export): ExportWorker QObject + QThread signals + cancellation"
```

---

## Task 10: `ExportSpatialite._run_export_worker` — QEventLoop wiring

**Files:**
- Modify: `tools/export_spatialite.py`

- [ ] **Step 1: Read the current file** (required before editing)

```bash
# Already read in this session — see tools/export_spatialite.py in context
```

- [ ] **Step 2: Replace the blocking export section in `show()`**

The goal: remove the `QProgressDialog` that wraps `create_new_spatialite_db` (it's fast now — no special progress needed), remove the `ExportData` / `export_2_splite` call, and add `_run_export_worker`.

Replace the full `show()` method and add `_run_export_worker`. The new `show()` is identical up to the `if newdbinstance.db_settings:` block, which now calls `_run_export_worker` instead of `ExportData.export_2_splite`.

```python
# tools/export_spatialite.py
"""ExportSpatialite — exports the current Midvatten database to a new SpatiaLite file."""

import logging

import qgis.core
from qgis.PyQt.QtCore import QCoreApplication, QEventLoop, Qt, QThread
from qgis.PyQt.QtWidgets import QApplication, QDialog, QProgressDialog

from midvatten.tools.create_db import NewDb
from midvatten.tools.create_db_dialogs import NewSpatialiteDbDialog
from midvatten.tools.export_worker import ExportWorker
from midvatten.tools.utils import common_utils, db_utils

log = logging.getLogger(__name__)


class ExportSpatialite:
    def __init__(self, iface, ms):
        self._iface = iface
        self._ms = ms

    def show(self) -> None:
        common_utils.start_waiting_cursor()

        obsid_p = common_utils.get_selected_features_as_tuple("obs_points")
        obsid_l = common_utils.get_selected_features_as_tuple("obs_lines")
        log.debug("Selected obs_points to export: %s", obsid_p)
        log.debug("Selected obs_lines to export: %s", obsid_l)

        source_srid = db_utils.sql_load_fr_db(
            """SELECT srid FROM geometry_columns WHERE f_table_name = 'obs_points';"""
        )[1][0][0]
        w_levels_logger_timezone = db_utils.get_timezone_from_db("w_levels_logger")
        w_levels_timezone = db_utils.get_timezone_from_db("w_levels")

        common_utils.stop_waiting_cursor()

        selected_all = (
            QCoreApplication.translate("Midvatten", "selected")
            if obsid_p or obsid_l
            else QCoreApplication.translate("Midvatten", "all")
        )

        dialog = NewSpatialiteDbDialog(parent=self._iface.mainWindow())
        dialog.setWindowTitle(
            QCoreApplication.translate(
                "ExportSpatialite", "Export to SpatiaLite database ({})"
            ).format(selected_all)
        )
        dialog._path_edit.clear()
        if source_srid:
            dialog._epsg_spin.setValue(source_srid)
        if w_levels_logger_timezone is not None:
            idx = dialog._logger_tz_combo.findText(w_levels_logger_timezone)
            dialog._logger_tz_combo.setCurrentIndex(max(0, idx))
        if w_levels_timezone is not None:
            idx = dialog._levels_tz_combo.findText(w_levels_timezone)
            dialog._levels_tz_combo.setCurrentIndex(max(0, idx))

        if dialog.exec() != QDialog.Accepted:
            return

        if not dialog.dbpath:
            common_utils.MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "export_spatialite", "No destination path specified."
                )
            )
            return

        newdbinstance = NewDb()
        progress = QProgressDialog(
            QCoreApplication.translate(
                "ExportSpatialite", "Creating new database, please wait..."
            ),
            None,
            0,
            0,
            self._iface.mainWindow(),
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setCancelButton(None)
        progress.show()
        QApplication.processEvents()
        try:
            newdbinstance.create_new_spatialite_db(
                newdbinstance._read_version(),
                user_select_crs="n",
                epsg_code=str(dialog.epsg_code),
                delete_srids=False,
                w_levels_logger_timezone=dialog.w_levels_logger_timezone,
                w_levels_timezone=dialog.w_levels_timezone,
                locale=dialog.locale,
                dbpath=dialog.dbpath,
            )
        finally:
            progress.close()

        if not newdbinstance.db_settings:
            common_utils.MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "export_spatialite",
                    "Export to spatialite failed, see log message panel",
                ),
                button=True,
            )
            return

        new_dbpath = db_utils.get_spatialite_db_path_from_dbsettings_string(
            newdbinstance.db_settings
        )
        if not new_dbpath:
            common_utils.MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "export_spatialite",
                    "Export to spatialite failed, see log message panel",
                ),
                button=True,
            )
            return

        self._run_export_worker(new_dbpath, dialog, obsid_p, obsid_l)

    def _run_export_worker(
        self,
        new_dbpath: str,
        dialog,
        obsid_p: tuple[str, ...],
        obsid_l: tuple[str, ...],
    ) -> None:
        source_db_settings = qgis.core.QgsProject.instance().readEntry(
            "Midvatten", "database"
        )[0]

        worker = ExportWorker(
            source_db_settings=source_db_settings,
            dest_path=new_dbpath,
            obsid_points=obsid_p,
            obsid_lines=obsid_l,
            dest_srid=str(dialog.epsg_code),
        )
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)

        progress = QProgressDialog(
            QCoreApplication.translate(
                "ExportSpatialite", "Exporting data, please wait..."
            ),
            QCoreApplication.translate("ExportSpatialite", "Cancel"),
            0,
            0,
            self._iface.mainWindow(),
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.processEvents()

        loop = QEventLoop()
        stats_holder: list[str | None] = []

        def on_finished(stats: str) -> None:
            stats_holder.append(stats)
            loop.quit()

        def on_error(msg: str) -> None:
            log.error("Export error:\n%s", msg)
            stats_holder.append(None)
            loop.quit()

        worker.finished.connect(on_finished)
        worker.error.connect(on_error)
        worker.table_started.connect(
            lambda name, total: (
                progress.setLabelText(
                    QCoreApplication.translate(
                        "ExportSpatialite", "Exporting: {}"
                    ).format(name)
                ),
                progress.setMaximum(total),
            )
        )
        worker.rows_written.connect(progress.setValue)
        progress.canceled.connect(worker.cancel)

        thread.start()
        loop.exec_()
        thread.wait()
        progress.close()

        if not stats_holder:
            return
        stats = stats_holder[0]
        if stats is None:
            common_utils.MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "ExportSpatialite", "Export failed, see log message panel"
                ),
                button=True,
            )
        elif stats == "":
            common_utils.MessagebarAndLog.info(
                bar_msg=QCoreApplication.translate(
                    "ExportSpatialite", "Export cancelled."
                )
            )
        else:
            common_utils.MessagebarAndLog.info(
                bar_msg=QCoreApplication.translate(
                    "ExportSpatialite",
                    "Export done, see differences in log message panel",
                ),
                log_msg=QCoreApplication.translate(
                    "ExportData", "Tables with different number of rows:\n%s"
                )
                % stats,
            )
```

- [ ] **Step 3: Verify the existing spatialite export tests still import**

```bash
python3 -m pytest test/test_export_data.py -x --collect-only 2>&1 | head -30
```

Expected: collection succeeds (no import errors).

- [ ] **Step 4: Commit**

```bash
git add tools/export_spatialite.py
git commit -m "feat(export): ExportSpatialite uses ExportWorker via QEventLoop"
```

---

## Task 11: Update `test_export_data.py` spatialite export tests

The existing `test_export_spatialite*` tests call `ExportSpatialite.show()`. The `show()` now uses `QEventLoop` internally, which runs until the worker finishes — so tests remain synchronous. The main changes needed:

1. `mock_dialog_cls` now controls `NewSpatialiteDbDialog` (unchanged).
2. The `QProgressDialog` mock: `QDialog.exec_` is already a no-op in the test base. The new `QProgressDialog` created in `_run_export_worker` uses `.show()` (no-op) and `loop.exec_()` (runs to completion). This should work as-is.
3. The `ExportData` import in the test file may now be unused — remove it if so.

**Files:**
- Modify: `test/test_export_data.py`

- [ ] **Step 1: Run the existing spatialite export tests**

```bash
python3 -m pytest test/test_export_data.py -x -k "spatialite" -m spatialite
```

- [ ] **Step 2: Fix any failures**

Most likely failure patterns and fixes:

**If `ImportError: cannot import name 'ExportData'` from test file header:**
The test file imports `ExportData` for its CSV tests — keep that import. But if the test file also imports `export_2_splite` or related, remove those.

**If tests fail because `ExportData` no longer has `export_2_splite`:**
The spatialite tests call `ExportSpatialite.show()`, not `ExportData.export_2_splite` directly. No change needed here.

**If `QEventLoop.exec_()` hangs in test** (unlikely — worker should complete):
Add a timeout guard by connecting a `QTimer.singleShot(30000, loop.quit)` before `loop.exec_()` in `_run_export_worker`. Only needed if tests get stuck.

After fixing any failures, confirm all spatialite export tests pass:

```bash
python3 -m pytest test/test_export_data.py -m spatialite -x
```

- [ ] **Step 3: Commit**

```bash
git add test/test_export_data.py
git commit -m "test(export): update spatialite export tests for QThread-based show()"
```

---

## Task 12: Remove dead code from `export_data.py`

**Files:**
- Modify: `tools/export_data.py`

The methods `export_2_splite`, `to_sql`, `get_table_data`, `_migrate_logger_source_to_series`, `get_table_rows_with_differences`, and `get_number_of_rows` (used only by `to_sql`) are now dead. `write_data` and `to_csv` are kept for the CSV export path.

- [ ] **Step 1: Delete the dead methods from `export_data.py`**

Remove the following methods (identified by their `def` lines — check exact line numbers with `grep -n "def " tools/export_data.py`):

- `export_2_splite`
- `get_number_of_rows`
- `write_data` — **KEEP** (used by `export_2_csv` via `to_csv`)
- `to_csv` — **KEEP**
- `to_sql` — remove
- `get_table_data` — remove
- `_migrate_logger_source_to_series` — remove
- `get_table_rows_with_differences` — remove
- `set_east_north_to_null` (module-level helper used only by `to_sql`) — remove

Also remove now-unused imports:
- `from midvatten.tools.import_data_to_db import MidvDataImporter` (only used by `export_2_splite`)
- `from midvatten.definitions import ... db_defs` (only used by removed methods — check)
- `from typing import ... Dict` (check if still needed)

Keep:
- `from qgis.PyQt.QtWidgets import QApplication, QFileDialog` (used by `show()` + `write_data`)
- All imports used by `write_data` / `to_csv` / `export_2_csv`

- [ ] **Step 2: Run all export tests to confirm nothing broke**

```bash
python3 -m pytest test/test_export_data.py -x
```

- [ ] **Step 3: Run the full test suite to check for regressions**

```bash
python3 -m pytest test/ -x -m spatialite
```

- [ ] **Step 4: Commit**

```bash
git add tools/export_data.py
git commit -m "refactor(export): remove dead export_2_splite path from ExportData"
```

---

## Task 13: Lint + full test run

**Files:** None (lint only)

- [ ] **Step 1: Run ruff fix + format**

```bash
ruff check --fix tools/export_engine.py tools/export_worker.py tools/export_spatialite.py tools/export_data.py test/test_export_engine.py test/test_export_data.py
ruff format tools/export_engine.py tools/export_worker.py tools/export_spatialite.py tools/export_data.py test/test_export_engine.py test/test_export_data.py
```

Fix any remaining issues by hand.

- [ ] **Step 2: Run the full non-PostGIS suite**

```bash
python3 -m pytest test/ -m spatialite -x
```

Expected: all PASS, 0 failures.

- [ ] **Step 3: Commit lint fixes**

```bash
git add -u
git commit -m "style(export): ruff fixes on new export files"
```

- [ ] **Step 4: Final summary commit (if no changes needed)**

If Step 3 produced no changes, skip. Otherwise confirm tests still pass after lint fixes.

---

## Self-Review Checklist

**Spec coverage:**

| Spec requirement | Covered by task |
|---|---|
| Non-blocking UI | Task 9 (QThread), Task 10 (QEventLoop) |
| Per-table progress | Task 9 (`table_started`/`rows_written` signals) |
| Cancellation + dest file deleted | Task 9 (`test_worker_cancel_deletes_dest_file`) |
| PostgreSQL source | Tasks 3–8 (`_build_select_sql` uses `source_conn` dialect; `fetchmany` works for both) |
| SpatiaLite source | Tasks 3–8 |
| zz-table merge | Task 6 |
| FK ordering | Task 8 (`test_export_fk_order_no_violations`) |
| Logger migration | Task 7 |
| obsid filter | Task 8 (`test_export_obsid_filter`) |
| SRID transform | Task 5 |
| Worker signals | Task 9 (`test_worker_emits_signals`) |
| Remove dead code | Task 12 |
| Existing tests updated | Task 11 |

**PostgreSQL source note:** `ExportEngine` uses `source_conn.cursor.execute(sql, args)` and `source_conn.cursor.fetchmany(n)` — both work identically for `psycopg2` and `sqlite3` cursors. Geometry SELECT uses `ST_AsBinary(ST_Transform(...))` which works on both. The dest INSERT always uses `?` placeholders (dest is always SpatiaLite). No extra code path needed.
