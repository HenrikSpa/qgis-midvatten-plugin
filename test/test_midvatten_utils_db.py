"""
/***************************************************************************
 This part of the Midvatten plugin tests the module that handles often used
 utilities.

                             -------------------
        begin                : 2016-03-08
        copyright            : (C) 2016 by joskal (HenrikSpa)
        email                : groundwatergis [at] gmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

from unittest import mock
from unittest.mock import call
import pytest

from midvatten.test import utils_for_tests
from midvatten.test.utils_for_tests import create_test_string
from midvatten.tools.utils import db_utils, midvatten_utils


class GetFunctionsMixin:
    def test_get_last_logger_dates(self):
        db_utils.sql_alter_db("""INSERT INTO obs_points (obsid) VALUES ('rb1')""")
        db_utils.sql_alter_db("""INSERT INTO obs_points (obsid) VALUES ('rb2')""")
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time) VALUES ('rb1', '2015-01-01 00:00')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time) VALUES ('rb1', '2015-01-01 00:00:00')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time) VALUES ('rb1', '2014-01-01 00:00:00')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time) VALUES ('rb2', '2013-01-01 00:00:00')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time) VALUES ('rb2', '2016-01-01 00:00')"""
        )

        test_string = create_test_string(db_utils.get_last_logger_dates())
        reference_string = (
            """{rb1: [(2015-01-01 00:00:00)], rb2: [(2016-01-01 00:00)]}"""
        )
        assert test_string == reference_string


class CalculateDbTableRowsMixin:
    @mock.patch("midvatten.tools.utils.db_utils.helpers.MessagebarAndLog")
    def test_get_db_statistics(self, mock_messagebar):
        """
        Test that calculate_db_table_rows can be run without major error
        :param mock_iface:
        :return:
        """
        db_utils.calculate_db_table_rows()

        assert len(str(mock_messagebar.mock_calls[0])) > 1500 and "about_db" in str(
            mock_messagebar.mock_calls[0]
        )


class WarnAboutOldDatabaseMixin:
    @mock.patch("midvatten.tools.utils.midvatten_utils.latest_database_version")
    @mock.patch("midvatten.tools.utils.midvatten_utils.MessagebarAndLog")
    def test_warn_about_old_database(self, mock_messagebar, mock_latest_version):
        mock_latest_version.return_value = "999.999.999"
        midvatten_utils.warn_about_old_database()
        print(f"{mock_messagebar.mock_calls=}")
        assert (
            call.info(
                bar_msg="The database version appears to be older than 999.999.999. An upgrade is suggested! See https://github.com/jkall/qgis-midvatten-plugin/wiki/6.-Database-management#upgrade-database",
                duration=4,
            )
            in mock_messagebar.mock_calls
        )

    @mock.patch("midvatten.tools.utils.midvatten_utils.latest_database_version")
    @mock.patch("midvatten.tools.utils.midvatten_utils.MessagebarAndLog")
    def test_warn_about_old_database_not_old(
        self, mock_messagebar, mock_latest_version
    ):
        mock_latest_version.return_value = "0.0.1"
        midvatten_utils.warn_about_old_database()
        print(f"{mock_messagebar.mock_calls=}")
        assert not mock_messagebar.mock_calls

    @mock.patch("midvatten.tools.utils.midvatten_utils.latest_database_version")
    @mock.patch("midvatten.tools.utils.midvatten_utils.MessagebarAndLog")
    def test_warn_about_view_obs_points_missing_assert_no_msg(
        self, mock_messagebar, mock_latest_version
    ):
        mock_latest_version.return_value = "0.0.1"
        midvatten_utils.warn_about_old_database()
        assert not mock_messagebar.mock_calls

    @mock.patch("midvatten.tools.utils.midvatten_utils.latest_database_version")
    @mock.patch("midvatten.tools.utils.midvatten_utils.MessagebarAndLog")
    def test_warn_about_view_obs_lines_missing_assert_no_msg(
        self, mock_messagebar, mock_latest_version
    ):
        mock_latest_version.return_value = "0.0.1"
        midvatten_utils.warn_about_old_database()
        assert not mock_messagebar.mock_calls


class AddViewObsPointsObsLinesMixin:
    expected_views_message = "Views not added for PostGIS databases (not needed)!"

    @mock.patch("midvatten.tools.utils.midvatten_utils.MessagebarAndLog")
    def test_add_view_obs_points_obs_lines(self, mock_messagebar):
        midvatten_utils.add_view_obs_points_obs_lines()
        print(f"{mock_messagebar.mock_calls=}")
        assert mock_messagebar.mock_calls == [
            call.info(bar_msg=self.expected_views_message)
        ]


@pytest.mark.postgis
class TestGetFunctionsPostgis(
    GetFunctionsMixin, utils_for_tests.MidvattenTestPostgisDbSv
):
    pass


@pytest.mark.spatialite
class TestGetFunctionsSpatialite(
    GetFunctionsMixin, utils_for_tests.MidvattenTestSpatialiteDbSv
):
    pass


@pytest.mark.postgis
class TestCalculateDbTableRowsPostgis(
    CalculateDbTableRowsMixin, utils_for_tests.MidvattenTestPostgisDbSv
):
    pass


@pytest.mark.spatialite
class TestCalculateDbTableRowsSpatialite(
    CalculateDbTableRowsMixin, utils_for_tests.MidvattenTestSpatialiteDbSv
):
    pass


@pytest.mark.postgis
class TestWarnAboutOldDatabasePostgis(
    WarnAboutOldDatabaseMixin, utils_for_tests.MidvattenTestPostgisDbSv
):
    pass


@pytest.mark.spatialite
class TestWarnAboutOldDatabaseSpatialite(
    WarnAboutOldDatabaseMixin, utils_for_tests.MidvattenTestSpatialiteDbSv
):
    pass


@pytest.mark.postgis
class TestAddViewObsPointsObsLinesPostgis(
    AddViewObsPointsObsLinesMixin, utils_for_tests.MidvattenTestPostgisDbSv
):
    pass


@pytest.mark.spatialite
class TestAddViewObsPointsObsLinesSpatialite(
    AddViewObsPointsObsLinesMixin, utils_for_tests.MidvattenTestSpatialiteDbSv
):
    expected_views_message = 'Views added. Please reload layers (Midvatten>Load default db-layers to qgis or "F7").'
