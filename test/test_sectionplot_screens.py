#! /usr/bin/env python
"""
Tests for the screen-interval plotting feature in SectionPlot.

Covers:
  - get_screen_plot_data(): correct bars dict shape, heights, bottoms
  - graceful-skip when `screen` table is absent (older DBs)
"""

from unittest import mock

import pytest

from midvatten.test import utils_for_tests
from midvatten.tools.utils import db_utils


class GetScreenPlotDataMixin:
    """Tests for SectionPlot.get_screen_plot_data()."""

    def _insert_obs_points(self):
        db_utils.sql_alter_db(
            """INSERT INTO obs_points (obsid, h_gs)
               VALUES ('P1', 100.0)"""
        )

    def _insert_screen_data(self):
        db_utils.sql_alter_db(
            """INSERT INTO screen (obsid, screenid, depthtop, depthbot, screenshort)
               VALUES ('P1', 1, 2.0, 5.0, 'JWS')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO screen (obsid, screenid, depthtop, depthbot, screenshort)
               VALUES ('P1', 2, 8.0, 12.0, 'PVC solid')"""
        )

    def _make_secplot(self):
        """Instantiate a minimal SectionPlot connected to the test DB."""
        from midvatten.tools.sectionplot import SectionPlot

        self.midvatten.ms.settingsdict["secplot_loaded_template"] = ""
        self.midvatten.ms.settingsdict["secplot_templates"] = ""
        self.midvatten.ms.settingsdict["secplotlocation"] = 0
        secplot = SectionPlot(self.iface, self.midvatten.ms)
        secplot.dbconnection = db_utils.DbConnectionManager()
        secplot.z_data = {"P1": {"z": 100.0, "barheight": 20.0, "bottom": 80.0}}
        return secplot

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_get_screen_plot_data_basic(self, mock_messagebar):
        """get_screen_plot_data returns correct keys, heights, and bottoms."""
        self._insert_obs_points()
        self._insert_screen_data()

        secplot = self._make_secplot()
        try:
            bars = secplot.get_screen_plot_data({"P1": 1.0})
        finally:
            secplot.dbconnection.closedb()

        print(f"{mock_messagebar.mock_calls=}")

        assert set(bars.keys()) == {"jws", "pvc solid"}

        # JWS: depthtop=2, depthbot=5 → height=3, bottom=100-5=95
        assert bars["jws"]["x"] == [1.0]
        assert bars["jws"]["height"] == [3.0]
        assert bars["jws"]["bottom"] == [95.0]

        # PVC solid: depthtop=8, depthbot=12 → height=4, bottom=100-12=88
        assert bars["pvc solid"]["x"] == [1.0]
        assert bars["pvc solid"]["height"] == [4.0]
        assert bars["pvc solid"]["bottom"] == [88.0]

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_get_screen_plot_data_graceful_skip_no_table(self, mock_messagebar):
        """get_screen_plot_data returns {} silently when screen table is absent."""
        self._insert_obs_points()

        secplot = self._make_secplot()
        try:
            # Drop the screen table to simulate an older DB.
            secplot.dbconnection.execute("DROP TABLE screen")
            bars = secplot.get_screen_plot_data({"P1": 1.0})
        finally:
            secplot.dbconnection.closedb()

        print(f"{mock_messagebar.mock_calls=}")

        assert bars == {}
        assert not mock_messagebar.critical.called

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_get_screen_plot_data_empty_obsids(self, mock_messagebar):
        """get_screen_plot_data returns {} for empty obsids_x_position."""
        secplot = self._make_secplot()
        try:
            bars = secplot.get_screen_plot_data({})
        finally:
            secplot.dbconnection.closedb()

        assert bars == {}

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_get_screen_plot_data_skips_null_depths(self, mock_messagebar):
        """Rows with NULL depthtop or depthbot are silently skipped."""
        self._insert_obs_points()
        # Insert a row with NULL depthbot — should be skipped.
        db_utils.sql_alter_db(
            """INSERT INTO screen (obsid, screenid, depthtop, depthbot, screenshort)
               VALUES ('P1', 3, 1.0, NULL, 'JWS')"""
        )
        # Insert a valid row.
        db_utils.sql_alter_db(
            """INSERT INTO screen (obsid, screenid, depthtop, depthbot, screenshort)
               VALUES ('P1', 4, 2.0, 5.0, 'JWS')"""
        )

        secplot = self._make_secplot()
        try:
            bars = secplot.get_screen_plot_data({"P1": 1.0})
        finally:
            secplot.dbconnection.closedb()

        print(f"{mock_messagebar.mock_calls=}")

        # Only the valid row should appear (1 entry for jws).
        assert set(bars.keys()) == {"jws"}
        assert len(bars["jws"]["x"]) == 1
        assert bars["jws"]["height"] == [3.0]
        assert bars["jws"]["bottom"] == [95.0]

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_get_screen_plot_data_skips_obsid_not_in_z_data(self, mock_messagebar):
        """Obsids absent from z_data are skipped defensively."""
        self._insert_obs_points()
        self._insert_screen_data()

        secplot = self._make_secplot()
        # Clear z_data so P1 is not present.
        secplot.z_data = {}
        try:
            bars = secplot.get_screen_plot_data({"P1": 1.0})
        finally:
            secplot.dbconnection.closedb()

        assert bars == {}


# ---------------------------------------------------------------------------
# Concrete test class (spatialite only)
# ---------------------------------------------------------------------------


@pytest.mark.spatialite
class TestGetScreenPlotDataSpatialite(
    GetScreenPlotDataMixin,
    utils_for_tests.MidvattenTestSpatialiteDbSv,
):
    pass
