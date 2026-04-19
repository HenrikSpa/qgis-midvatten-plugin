# test/test_export_engine.py
import gc
import os
import tempfile
import threading
from unittest import mock

import pytest

from midvatten.test.utils_for_tests import (
    MidvattenTestPostgisDbSv,
    MidvattenTestSpatialiteDbSv,
)
from midvatten.tools.utils import db_utils


class _ExportDestMixin:
    """Shared SpatiaLite-destination helpers for ExportEngine test classes."""

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
        gc.collect()
        super().teardown_method()

    def _make_dest_db(self, epsg_code: str = "3006", locale: str = "sv_SE") -> str:
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

    def _dest_conn(self, epsg_code: str = "3006") -> db_utils.DbConnectionManager:
        path = self._make_dest_db(epsg_code=epsg_code)
        conn = db_utils.DbConnectionManager(path)
        conn.connect2db()
        return conn


@pytest.mark.spatialite
class TestExportEngine(_ExportDestMixin, MidvattenTestSpatialiteDbSv):
    """Tests for ExportEngine using a SpatiaLite source DB."""

    def _source_conn(self) -> db_utils.DbConnectionManager:
        conn = db_utils.DbConnectionManager(self._class_db_settings)
        conn.connect2db()
        return conn

    # ------------------------------------------------------------------ Task 1

    def test_import(self):
        from midvatten.tools.export_engine import ExportCancelledError, ExportEngine

        assert issubclass(ExportCancelledError, Exception)
        engine = ExportEngine()
        assert engine.CHUNK_SIZE == 5_000

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_count_source_rows_no_filter(self, mock_messagebar):
        """Returns total row count when no obsid filter is given."""
        from midvatten.tools.export_engine import ExportEngine

        conn = db_utils.DbConnectionManager(self._class_db_settings)
        db_utils.sql_alter_db(
            "INSERT INTO obs_points (obsid, geometry) VALUES "
            "('P1', ST_GeomFromText('POINT(1 2)', 3006))",
            dbconnection=conn,
        )
        conn.commit_and_closedb()
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
                "w_levels", src, ["obsid", "date_time", "meas"], "3006", (), set()
            )
            assert "obsid" in sql
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
            sql, args = ExportEngine()._build_select_sql(
                "obs_points", src, ["obsid", "geometry"], "4326", (), {"geometry"}
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
                "w_levels", src, ["obsid", "date_time"], "3006", ("P1",), set()
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
            sql = ExportEngine()._build_insert_sql(
                "w_levels", dest, ["obsid", "date_time", "meas"]
            )
            assert sql.upper().startswith("INSERT OR IGNORE INTO")
            assert "?" in sql
            assert "ST_GeomFromWKB" not in sql
        finally:
            dest.closedb()

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_build_insert_sql_geometry(self, mock_messagebar):
        from midvatten.tools.export_engine import ExportEngine

        dest = self._dest_conn()
        try:
            sql = ExportEngine()._build_insert_sql(
                "obs_points", dest, ["obsid", "geometry"]
            )
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
            # Insert obs_points in dest so FK constraint is satisfied
            db_utils.sql_alter_db(
                "INSERT INTO obs_points (obsid, geometry) VALUES "
                "('P1', ST_GeomFromText('POINT(1 2)', 3006))",
                dbconnection=dest,
            )
            dest.commit()
            engine._export_table(
                "w_levels",
                src,
                dest,
                (),
                "3006",
                False,
                lambda tname, written, total: progress_calls.append(
                    (tname, written, total)
                ),
                cancel,
            )
            dest.commit()
            rows = dest.execute_and_fetchall(
                "SELECT obsid, date_time, meas FROM w_levels ORDER BY date_time"
            )
        finally:
            src.closedb()
            dest.closedb()

        assert rows == [
            ("P1", "2020-01-01 00:00:00", 1.5),
            ("P1", "2020-01-02 00:00:00", 2.5),
        ]
        # progress_cb called with (tname, 0, total) first then (tname, n, total)
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
                    "w_levels",
                    src,
                    dest,
                    (),
                    "3006",
                    False,
                    lambda *a: None,
                    cancel,
                )
        finally:
            src.closedb()
            dest.closedb()

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_export_table_geometry_reprojected(self, mock_messagebar):
        """obs_points geometry is exported correctly via ST_AsBinary/ST_GeomFromWKB."""
        from midvatten.tools.export_engine import ExportEngine

        conn = db_utils.DbConnectionManager(self._class_db_settings)
        db_utils.sql_alter_db(
            "INSERT INTO obs_points (obsid, geometry) VALUES "
            "('P1', ST_GeomFromText('POINT(633466 711659)', 3006))",
            dbconnection=conn,
        )
        conn.commit_and_closedb()

        src = self._source_conn()
        dest = self._dest_conn(epsg_code="3006")
        try:
            ExportEngine()._export_table(
                "obs_points",
                src,
                dest,
                (),
                "3006",
                False,
                lambda *a: None,
                threading.Event(),
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
        # Coordinates preserved
        assert "633466" in rows[0][1]
        assert "711659" in rows[0][1]

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_zz_merge_source_overrides_dest(self, mock_messagebar):
        """Source row wins over matching dest row."""
        from midvatten.tools.export_engine import ExportEngine

        # Source DB has a customised zz_staff row
        conn = db_utils.DbConnectionManager(self._class_db_settings)
        conn.execute("DELETE FROM zz_staff")
        conn.execute("INSERT INTO zz_staff (staff, name) VALUES ('s1', 'Source Name')")
        conn.commit_and_closedb()

        src = self._source_conn()
        dest = self._dest_conn()
        # Dest has a row with same PK but different name
        dest.execute("DELETE FROM zz_staff")
        dest.execute(
            "INSERT INTO zz_staff (staff, name) VALUES ('s1', 'Old Dest Name')"
        )
        dest.commit()

        try:
            ExportEngine()._export_table(
                "zz_staff",
                src,
                dest,
                None,
                "3006",
                True,
                lambda *a: None,
                threading.Event(),
            )
            dest.commit()
            rows = dest.execute_and_fetchall(
                "SELECT staff, name FROM zz_staff WHERE staff = 's1'"
            )
        finally:
            src.closedb()
            dest.closedb()

        # Source name wins
        assert rows == [("s1", "Source Name")]

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_zz_merge_dest_only_row_survives(self, mock_messagebar):
        """A dest-only row (not in source) is preserved after merge."""
        from midvatten.tools.export_engine import ExportEngine

        conn = db_utils.DbConnectionManager(self._class_db_settings)
        conn.execute("DELETE FROM zz_staff")
        conn.execute(
            "INSERT INTO zz_staff (staff, name) VALUES ('src_only', 'Source Person')"
        )
        conn.commit_and_closedb()

        src = self._source_conn()
        dest = self._dest_conn()
        dest.execute("DELETE FROM zz_staff")
        dest.execute(
            "INSERT INTO zz_staff (staff, name) VALUES ('src_only', 'Source Person')"
        )
        dest.execute(
            "INSERT INTO zz_staff (staff, name) VALUES ('dest_only', 'Dest Person')"
        )
        dest.commit()

        try:
            ExportEngine()._export_table(
                "zz_staff",
                src,
                dest,
                None,
                "3006",
                True,
                lambda *a: None,
                threading.Event(),
            )
            dest.commit()
            units = {
                r[0] for r in dest.execute_and_fetchall("SELECT staff FROM zz_staff")
            }
        finally:
            src.closedb()
            dest.closedb()

        assert "src_only" in units
        assert "dest_only" in units

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
        """Old-schema source (source col) → w_logger_series rows created, series_id mapped."""
        from midvatten.tools.export_engine import ExportEngine

        # Build old-schema source DB: w_levels_logger with 'source' text col instead of 'series_id'
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

            # Export obs_points first (FK requirement)
            ExportEngine()._export_table(
                "obs_points",
                src,
                dest,
                (),
                "3006",
                False,
                lambda *a: None,
                threading.Event(),
            )
            dest.commit()
            ExportEngine()._export_table(
                "w_levels_logger",
                src,
                dest,
                (),
                "3006",
                False,
                lambda *a: None,
                threading.Event(),
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
            # P1/fileA rows share the same series_id
            p1a_ids = dest.execute_and_fetchall(
                "SELECT series_id FROM w_levels_logger"
                " WHERE obsid='P1' AND date_time IN"
                " ('2020-01-01 00:00:00', '2020-01-01 01:00:00')"
                " ORDER BY date_time"
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
        assert p1a_ids[0][0] == p1a_ids[1][0]  # same series_id for same (obsid, source)

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_export_full_round_trip(self, mock_messagebar):
        """Full export: data in source appears in dest."""
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
        finally:
            src.closedb()
            dest.closedb()

        assert ("P1",) in obsids
        assert ("P1", "2020-01-01 00:00:00", 1.5) in wlevel
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
            obsids = {
                r[0] for r in dest.execute_and_fetchall("SELECT obsid FROM obs_points")
            }
            wlevel_obsids = {
                r[0] for r in dest.execute_and_fetchall("SELECT obsid FROM w_levels")
            }
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
            ExportEngine().export(
                source_conn=src,
                dest_conn=dest,
                obsid_points=(),
                obsid_lines=(),
                dest_srid="3006",
                progress_cb=lambda *a: None,
                cancel_flag=threading.Event(),
            )
            integrity_violations = dest.execute_and_fetchall("PRAGMA foreign_key_check")
        finally:
            src.closedb()
            dest.closedb()

        assert integrity_violations == []

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

    # ------------------------------------------------------------------ Critical fix

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    @mock.patch("midvatten.tools.utils.db_utils.export_bytea_as_bytes")
    def test_worker_calls_export_bytea_as_bytes(self, mock_bytea, mock_messagebar):
        """ExportWorker calls export_bytea_as_bytes on the source connection."""
        from qgis.PyQt.QtCore import QEventLoop, QThread

        from midvatten.tools.export_worker import ExportWorker

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

        loop = QEventLoop()
        worker.finished.connect(loop.quit)
        worker.error.connect(loop.quit)
        thread.start()
        loop.exec_()
        thread.wait()

        assert mock_bytea.call_count == 1

    # ------------------------------------------------------------------ Row-count warning

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    @mock.patch("midvatten.tools.export_engine.log")
    def test_export_table_warns_on_pk_conflict(self, mock_log, mock_messagebar):
        """Logs a warning when INSERT OR IGNORE silently drops a row due to PK conflict."""
        from midvatten.tools.export_engine import ExportEngine

        conn = db_utils.DbConnectionManager(self._class_db_settings)
        db_utils.sql_alter_db(
            "INSERT INTO obs_points (obsid, geometry) VALUES "
            "('P1', ST_GeomFromText('POINT(1 2)', 3006))",
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
        db_utils.sql_alter_db(
            "INSERT INTO obs_points (obsid, geometry) VALUES "
            "('P1', ST_GeomFromText('POINT(1 2)', 3006))",
            dbconnection=dest,
        )
        # Same PK row already in dest — will be ignored by INSERT OR IGNORE
        db_utils.sql_alter_db(
            "INSERT INTO w_levels (obsid, date_time, meas) VALUES "
            "('P1', '2020-01-01 00:00:00', 9.9)",
            dbconnection=dest,
        )
        dest.commit()

        try:
            ExportEngine()._export_table(
                "w_levels",
                src,
                dest,
                (),
                "3006",
                False,
                lambda *a: None,
                threading.Event(),
            )
        finally:
            src.closedb()
            dest.closedb()

        warning_calls = [
            call
            for call in mock_log.warning.call_args_list
            if "skip" in str(call).lower() or "ignor" in str(call).lower()
        ]
        assert warning_calls, "Expected a warning about skipped/ignored rows"

    # ------------------------------------------------------------------ Cross-CRS coverage

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_export_table_cross_crs_reprojection(self, mock_messagebar):
        """Exports geometry from SRID 3006 source into a SRID 4326 dest via WGS84 intermediate."""
        from midvatten.tools.export_engine import ExportEngine

        conn = db_utils.DbConnectionManager(self._class_db_settings)
        db_utils.sql_alter_db(
            "INSERT INTO obs_points (obsid, geometry) VALUES "
            "('P1', ST_GeomFromText('POINT(633466 711659)', 3006))",
            dbconnection=conn,
        )
        conn.commit_and_closedb()

        src = self._source_conn()
        dest = self._dest_conn(epsg_code="4326")
        try:
            ExportEngine()._export_table(
                "obs_points",
                src,
                dest,
                (),
                "4326",
                False,
                lambda *a: None,
                threading.Event(),
            )
            dest.commit()
            rows = dest.execute_and_fetchall(
                "SELECT obsid, ST_SRID(geometry), ST_AsText(geometry) FROM obs_points"
            )
        finally:
            src.closedb()
            dest.closedb()

        assert len(rows) == 1
        assert rows[0][0] == "P1"
        assert rows[0][1] == 4326
        # SWEREF99TM coordinates must NOT appear in the WGS84 result
        wkt = rows[0][2]
        assert "633466" not in wkt

    # ------------------------------------------------------------------ obs_lines filter

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_export_obsid_lines_filter(self, mock_messagebar):
        """Only the selected obs_lines obsids are exported."""
        from midvatten.tools.export_engine import ExportEngine

        conn = db_utils.DbConnectionManager(self._class_db_settings)
        db_utils.sql_alter_db(
            "INSERT INTO obs_lines (obsid, geometry) VALUES "
            "('L1', ST_GeomFromText('LINESTRING(0 0, 1 1)', 3006)),"
            "('L2', ST_GeomFromText('LINESTRING(2 2, 3 3)', 3006))",
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
                obsid_points=(),
                obsid_lines=("L1",),
                dest_srid="3006",
                progress_cb=lambda *a: None,
                cancel_flag=threading.Event(),
            )
            obsids = {
                r[0] for r in dest.execute_and_fetchall("SELECT obsid FROM obs_lines")
            }
        finally:
            src.closedb()
            dest.closedb()

        assert obsids == {"L1"}

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_export_empty_selection_exports_all_obs_points_and_lines(
        self, mock_messagebar
    ):
        """Empty obsid_points/obsid_lines → all obs_points and obs_lines are exported."""
        from midvatten.tools.export_engine import ExportEngine

        conn = db_utils.DbConnectionManager(self._class_db_settings)
        db_utils.sql_alter_db(
            "INSERT INTO obs_points (obsid, geometry) VALUES "
            "('P1', ST_GeomFromText('POINT(1 2)', 3006)),"
            "('P2', ST_GeomFromText('POINT(3 4)', 3006))",
            dbconnection=conn,
        )
        db_utils.sql_alter_db(
            "INSERT INTO obs_lines (obsid, geometry) VALUES "
            "('L1', ST_GeomFromText('LINESTRING(0 0, 1 1)', 3006)),"
            "('L2', ST_GeomFromText('LINESTRING(2 2, 3 3)', 3006))",
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
                obsid_points=(),
                obsid_lines=(),
                dest_srid="3006",
                progress_cb=lambda *a: None,
                cancel_flag=threading.Event(),
            )
            point_obsids = {
                r[0] for r in dest.execute_and_fetchall("SELECT obsid FROM obs_points")
            }
            line_obsids = {
                r[0] for r in dest.execute_and_fetchall("SELECT obsid FROM obs_lines")
            }
        finally:
            src.closedb()
            dest.closedb()

        assert point_obsids == {"P1", "P2"}
        assert line_obsids == {"L1", "L2"}


# ---------------------------------------------------------------------------
# PostGIS source → SpatiaLite dest


@pytest.mark.postgis
class TestExportEnginePostgisSource(_ExportDestMixin, MidvattenTestPostgisDbSv):
    """ExportEngine tests using a PostGIS source database."""

    def _source_conn(self) -> db_utils.DbConnectionManager:
        conn = db_utils.DbConnectionManager(self._class_db_settings)
        conn.connect2db()
        db_utils.export_bytea_as_bytes(conn)
        return conn

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_postgis_source_basic_data_exported(self, mock_messagebar):
        """Non-geometry data from PostGIS source arrives in SpatiaLite dest."""
        from midvatten.tools.export_engine import ExportEngine

        db_utils.sql_alter_db(
            "INSERT INTO obs_points (obsid, geometry) VALUES "
            "('P1', ST_GeomFromText('POINT(633466 711659)', 3006))"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels (obsid, date_time, meas) VALUES "
            "('P1', '2020-01-01 00:00:00', 1.5)"
        )

        dest_path = self._make_dest_db()
        src = self._source_conn()
        dest = db_utils.DbConnectionManager(dest_path)
        dest.connect2db()

        try:
            ExportEngine().export(
                source_conn=src,
                dest_conn=dest,
                obsid_points=(),
                obsid_lines=(),
                dest_srid="3006",
                progress_cb=lambda *a: None,
                cancel_flag=threading.Event(),
            )
            wlevel = dest.execute_and_fetchall(
                "SELECT obsid, date_time, meas FROM w_levels"
            )
        finally:
            src.closedb()
            dest.closedb()

        assert ("P1", "2020-01-01 00:00:00", 1.5) in wlevel

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_postgis_source_geometry_exported(self, mock_messagebar):
        """Geometry from PostGIS source is correctly transferred to SpatiaLite dest."""
        from midvatten.tools.export_engine import ExportEngine

        db_utils.sql_alter_db(
            "INSERT INTO obs_points (obsid, geometry) VALUES "
            "('P1', ST_GeomFromText('POINT(633466 711659)', 3006))"
        )

        dest_path = self._make_dest_db(epsg_code="3006")
        src = self._source_conn()
        dest = db_utils.DbConnectionManager(dest_path)
        dest.connect2db()

        try:
            ExportEngine().export(
                source_conn=src,
                dest_conn=dest,
                obsid_points=(),
                obsid_lines=(),
                dest_srid="3006",
                progress_cb=lambda *a: None,
                cancel_flag=threading.Event(),
            )
            rows = dest.execute_and_fetchall(
                "SELECT obsid, ST_AsText(geometry) FROM obs_points"
            )
        finally:
            src.closedb()
            dest.closedb()

        assert len(rows) == 1
        assert rows[0][0] == "P1"
        assert "633466" in rows[0][1]

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_postgis_source_obsid_filter(self, mock_messagebar):
        """ObsId filter works correctly with PostGIS source."""
        from midvatten.tools.export_engine import ExportEngine

        db_utils.sql_alter_db(
            "INSERT INTO obs_points (obsid, geometry) VALUES "
            "('P1', ST_GeomFromText('POINT(1 2)', 3006)),"
            "('P2', ST_GeomFromText('POINT(3 4)', 3006))"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels (obsid, date_time, meas) VALUES "
            "('P1', '2020-01-01 00:00:00', 1.0),"
            "('P2', '2020-01-01 00:00:00', 2.0)"
        )

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
            obsids = {
                r[0] for r in dest.execute_and_fetchall("SELECT obsid FROM obs_points")
            }
            wlevel_obsids = {
                r[0] for r in dest.execute_and_fetchall("SELECT obsid FROM w_levels")
            }
        finally:
            src.closedb()
            dest.closedb()

        assert obsids == {"P1"}
        assert wlevel_obsids == {"P1"}
