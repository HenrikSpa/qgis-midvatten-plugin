"""Tests for the w_logger_series table and its linkage from w_levels_logger.

Covers:
  * table exists with the expected columns after new_db()
  * series_id on w_levels_logger is nullable (direct SQL inserts without a
    series still succeed)
  * created_at has a DB-level default (direct SQL inserts without created_at
    still succeed)
  * deleting a series cascades to its w_levels_logger rows
  * series with no logger rows can still exist
"""

from unittest import mock

import pytest

from midvatten.test import utils_for_tests
from midvatten.tools.utils import db_utils
from midvatten.tools.utils.db_utils import schema


class WLoggerSeriesMixin:
    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_table_exists_with_expected_columns(self, mock_messagebar):
        tables = schema.get_tables(skip_views=True)
        assert "w_logger_series" in tables

        info = schema.get_table_info("w_logger_series")
        column_names = {row[1] for row in info}
        assert column_names == {
            "id",
            "obsid",
            "source",
            "instrument",
            "description",
            "comment",
        }

        # w_levels_logger gains series_id and created_at, loses source.
        levels_info = schema.get_table_info("w_levels_logger")
        levels_cols = {row[1] for row in levels_info}
        assert "series_id" in levels_cols
        assert "created_at" in levels_cols
        assert "source" not in levels_cols

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_insert_series_and_linked_logger_rows(self, mock_messagebar):
        db_utils.sql_alter_db(
            """INSERT INTO obs_points (obsid) VALUES ('rb1')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_logger_series (obsid, source, description)
               VALUES ('rb1', 'Diver file A', 'Test series')"""
        )
        series_id = db_utils.sql_load_fr_db(
            """SELECT id FROM w_logger_series WHERE obsid = 'rb1'"""
        )[1][0][0]

        dbconn = db_utils.DbConnectionManager()
        try:
            ph = dbconn.placeholder()
            dbconn.execute(
                f"""INSERT INTO w_levels_logger
                    (obsid, date_time, head_cm, series_id, created_at)
                    VALUES ('rb1', '2026-01-01 00:00:00', 100.0, {ph}, '2026-04-17 08:00:00')""",
                (series_id,),
            )
            dbconn.execute(
                f"""INSERT INTO w_levels_logger
                    (obsid, date_time, head_cm, series_id, created_at)
                    VALUES ('rb1', '2026-01-01 01:00:00', 101.0, {ph}, '2026-04-17 08:00:00')""",
                (series_id,),
            )
            dbconn.commit()
        finally:
            dbconn.closedb()

        rows = db_utils.sql_load_fr_db(
            """SELECT l.obsid, l.date_time, l.head_cm, s.source
               FROM w_levels_logger l
               JOIN w_logger_series s ON s.id = l.series_id
               WHERE l.obsid = 'rb1'
               ORDER BY l.date_time"""
        )[1]
        assert [tuple(r) for r in rows] == [
            ("rb1", "2026-01-01 00:00:00", 100.0, "Diver file A"),
            ("rb1", "2026-01-01 01:00:00", 101.0, "Diver file A"),
        ]

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_series_id_is_nullable(self, mock_messagebar):
        # Direct SQL inserts without a series must still work.
        db_utils.sql_alter_db("""INSERT INTO obs_points (obsid) VALUES ('rb2')""")
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, head_cm)
               VALUES ('rb2', '2026-01-01 00:00:00', 50.0)"""
        )
        rows = db_utils.sql_load_fr_db(
            """SELECT obsid, date_time, series_id
               FROM w_levels_logger WHERE obsid = 'rb2'"""
        )[1]
        assert len(rows) == 1
        assert rows[0][0] == "rb2"
        assert rows[0][2] is None

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_created_at_has_default(self, mock_messagebar):
        # Direct SQL insert without created_at should get a non-null value.
        db_utils.sql_alter_db("""INSERT INTO obs_points (obsid) VALUES ('rb3')""")
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, head_cm)
               VALUES ('rb3', '2026-01-01 00:00:00', 50.0)"""
        )
        rows = db_utils.sql_load_fr_db(
            """SELECT created_at FROM w_levels_logger WHERE obsid = 'rb3'"""
        )[1]
        assert len(rows) == 1
        assert rows[0][0] is not None
        assert str(rows[0][0]).strip() != ""

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_cascade_delete_removes_linked_rows(self, mock_messagebar):
        db_utils.sql_alter_db("""INSERT INTO obs_points (obsid) VALUES ('rb4')""")
        db_utils.sql_alter_db(
            """INSERT INTO w_logger_series (obsid, source, description)
               VALUES ('rb4', 'Bad import', 'Revert me')"""
        )
        series_id = db_utils.sql_load_fr_db(
            """SELECT id FROM w_logger_series WHERE obsid = 'rb4'"""
        )[1][0][0]

        dbconn = db_utils.DbConnectionManager()
        try:
            ph = dbconn.placeholder()
            dbconn.execute(
                f"""INSERT INTO w_levels_logger
                    (obsid, date_time, head_cm, series_id)
                    VALUES ('rb4', '2026-01-01 00:00:00', 1.0, {ph})""",
                (series_id,),
            )
            dbconn.execute(
                f"""INSERT INTO w_levels_logger
                    (obsid, date_time, head_cm, series_id)
                    VALUES ('rb4', '2026-01-01 01:00:00', 2.0, {ph})""",
                (series_id,),
            )
            # A second, unrelated row with no series should survive the delete.
            dbconn.execute(
                """INSERT INTO w_levels_logger
                    (obsid, date_time, head_cm)
                    VALUES ('rb4', '2026-01-01 02:00:00', 3.0)"""
            )
            dbconn.commit()
        finally:
            dbconn.closedb()

        db_utils.sql_alter_db(
            f"""DELETE FROM w_logger_series WHERE id = {series_id}"""
        )

        remaining = db_utils.sql_load_fr_db(
            """SELECT date_time, head_cm, series_id FROM w_levels_logger
               WHERE obsid = 'rb4' ORDER BY date_time"""
        )[1]
        assert [tuple(r) for r in remaining] == [
            ("2026-01-01 02:00:00", 3.0, None),
        ]

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_series_without_linked_rows(self, mock_messagebar):
        db_utils.sql_alter_db("""INSERT INTO obs_points (obsid) VALUES ('rb5')""")
        db_utils.sql_alter_db(
            """INSERT INTO w_logger_series (obsid, description)
               VALUES ('rb5', 'Empty series')"""
        )
        rows = db_utils.sql_load_fr_db(
            """SELECT obsid, description FROM w_logger_series WHERE obsid = 'rb5'"""
        )[1]
        assert len(rows) == 1
        assert rows[0][0] == "rb5"
        assert rows[0][1] == "Empty series"


@pytest.mark.spatialite
class TestWLoggerSeriesSpatialite(
    WLoggerSeriesMixin, utils_for_tests.MidvattenTestSpatialiteDbSv
):
    pass


@pytest.mark.postgis
class TestWLoggerSeriesPostgis(
    WLoggerSeriesMixin, utils_for_tests.MidvattenTestPostgisDbSv
):
    pass
