# test/test_export_engine.py
import gc
import os
import tempfile
import threading
from unittest import mock

import pytest

from midvatten.test.utils_for_tests import MidvattenTestSpatialiteDbSv
from midvatten.tools.utils import db_utils


@pytest.mark.spatialite
class TestExportEngine(MidvattenTestSpatialiteDbSv):
    """Tests for ExportEngine using a SpatiaLite source DB."""

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
                "w_levels", src, ["obsid", "date_time", "meas"], "3006", ()
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
