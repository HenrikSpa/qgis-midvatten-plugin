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
