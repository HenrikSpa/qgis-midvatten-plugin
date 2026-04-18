"""Test refresh_spatialite_layer_statistics() — fix for the 100-row cap.

The bug: on SpatiaLite DBs where ``geometry_columns_statistics`` is missing
a row for a spatial table, QGIS's SpatiaLite provider returns
``featureCount()=0`` and the attribute table caps at 100 rows.
``UpdateLayerStatistics()`` populates the stats row, lifting the cap.
"""

from unittest import mock

import pytest

from midvatten.test import utils_for_tests
from midvatten.tools.utils import db_utils


@pytest.mark.spatialite
class TestRefreshSpatialiteLayerStatistics(
    utils_for_tests.MidvattenTestSpatialiteDbSv
):
    @mock.patch("midvatten.tools.utils.db_utils.helpers.MessagebarAndLog")
    def test_refresh_populates_stats_row_when_missing(self, mock_messagebar):
        """Deleting the stats row and calling refresh must put it back."""
        dbconnection = db_utils.DbConnectionManager()
        try:
            # Insert one point so the stats refresh has something to count.
            dbconnection.execute(
                "INSERT INTO obs_points(obsid, geometry) "
                "VALUES ('rb1', GeomFromText('POINT(1 1)', 3006))"
            )
            # Delete the stats row to simulate the bug state.
            dbconnection.execute(
                "DELETE FROM geometry_columns_statistics "
                "WHERE f_table_name='obs_points'"
            )
            dbconnection.commit()
            rows_before = dbconnection.execute_and_fetchall(
                "SELECT row_count FROM geometry_columns_statistics "
                "WHERE f_table_name='obs_points'"
            )
            assert rows_before == [], (
                "precondition failed: stats row still present"
            )
        finally:
            dbconnection.closedb()

        db_utils.refresh_spatialite_layer_statistics()

        dbconnection = db_utils.DbConnectionManager()
        try:
            rows_after = dbconnection.execute_and_fetchall(
                "SELECT row_count FROM geometry_columns_statistics "
                "WHERE f_table_name='obs_points'"
            )
        finally:
            dbconnection.closedb()

        print(f"{mock_messagebar.mock_calls=}")
        assert rows_after, "stats row was not repopulated"
        assert rows_after[0][0] == 1, (
            f"expected row_count=1, got {rows_after[0][0]}"
        )
