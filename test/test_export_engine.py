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
