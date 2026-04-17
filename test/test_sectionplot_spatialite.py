"""
/***************************************************************************
 Integration tests for the sectionplot package (Step 1 of T6).

 Tests focus on:
   1. The basic draw pipeline (stratigraphy + water level)
   2. The legend rebuild path (update_legend after artists are added)
                             -------------------
        begin                : 2026-04-15
        copyright            : (C) 2026 by joskal (HenrikSpa)
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

import pytest
from qgis.core import QgsProject, QgsVectorLayer

from midvatten.test import utils_for_tests
from midvatten.tools.sectionplot import get_legend_items_labels
from midvatten.tools.utils import db_utils, gui_utils


# ---------------------------------------------------------------------------
# Shared helper mixin
# ---------------------------------------------------------------------------


class SectionPlotIntegrationMixin:
    """Set up a minimal section-line + obs_points environment for draw tests."""

    def setup_method(self):
        super().setup_method()
        self.midvatten.ms.settingsdict["secplot_loaded_template"] = ""
        self.midvatten.ms.settingsdict["secplot_templates"] = ""
        self.midvatten.ms.settingsdict["secplotlocation"] = 0

    def _insert_line_and_points(self):
        db_utils.sql_alter_db(
            """INSERT INTO obs_lines (obsid, geometry)
               VALUES ('L1', ST_GeomFromText(
                   'LINESTRING(0 0, 10 0)', 3006))"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO obs_points (obsid, geometry, h_gs, length)
               VALUES ('P1', ST_GeomFromText('POINT(2 0)', 3006), 10.0, 5.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO obs_points (obsid, geometry, h_gs, length)
               VALUES ('P2', ST_GeomFromText('POINT(8 0)', 3006), 12.0, 6.0)"""
        )

    def _insert_stratigraphy(self):
        db_utils.sql_alter_db(
            """INSERT INTO stratigraphy (obsid, stratid, depthtop, depthbot, geoshort)
               VALUES ('P1', 1, 0.0, 2.0, 'sand')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO stratigraphy (obsid, stratid, depthtop, depthbot, geoshort)
               VALUES ('P2', 1, 0.0, 3.0, 'gravel')"""
        )

    def _insert_w_levels(self):
        db_utils.sql_alter_db(
            """INSERT INTO w_levels (obsid, date_time, meas, h_toc, level_masl)
               VALUES ('P1', '2020-01-01 00:00:00', '1', '10', '9')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels (obsid, date_time, meas, h_toc, level_masl)
               VALUES ('P2', '2020-01-01 00:00:00', '2', '12', '10')"""
        )

    def _create_vlayer(self):
        dbconnection = db_utils.DbConnectionManager()
        uri = dbconnection.uri
        uri.setDataSource("", "obs_lines", "geometry", "", "obsid")
        dbtype = db_utils.get_dbtype(dbconnection.dbtype)
        self.vlayer = QgsVectorLayer(uri.uri(), "TestLayer", dbtype)
        QgsProject.instance().addMapLayer(self.vlayer)
        feature_ids = [f.id() for f in self.vlayer.getFeatures()]
        self.vlayer.selectByIds(feature_ids)

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    @mock.patch("midvatten.tools.sectionplot.common_utils.MessagebarAndLog")
    def test_draw_stratigraphy_pipeline(self, mock_messagebar):
        """Basic draw pipeline: stratigraphy bars are rendered without errors.

        Verifies that draw_plot() completes, figure.plot_handles is populated,
        and no warnings or errors are logged.
        """
        self._insert_line_and_points()
        self._insert_stratigraphy()
        self._create_vlayer()

        @mock.patch("midvatten.tools.sectionplot.common_utils.find_layer")
        @mock.patch(
            "midvatten.tools.sectionplot.common_utils.get_selected_object_names",
            autospec=True,
        )
        @mock.patch("qgis.utils.iface", autospec=True)
        def _run(mock_iface, mock_getselected, mock_findlayer):
            mock_iface.mapCanvas.return_value.currentLayer.return_value = self.vlayer
            self.iface.mapCanvas.return_value.currentLayer.return_value = self.vlayer
            mock_findlayer.return_value.isEditable.return_value = False
            mock_getselected.return_value = ("P1", "P2")
            mock_iface.mapCanvas.return_value.layerCount.return_value = 0

            self.midvatten.plot_section()
            secplot = self.midvatten.sectionplot
            secplot.plot_stratigraphy.setChecked(True)
            secplot.drillstop.setText("")
            secplot.draw_plot()
            return secplot

        secplot = _run()

        print(f"{mock_messagebar.mock_calls=}")
        # Draw must complete without warnings or critical errors.
        assert not mock_messagebar.warning.called
        assert not mock_messagebar.critical.called

        # Stratigraphy should produce at least one plot handle.
        assert len(secplot.figure.plot_handles) >= 1

        # Obsids must be positioned.
        assert set(secplot.figure.obsids_x_position.keys()) == {"P1", "P2"}

    @mock.patch("midvatten.tools.sectionplot.common_utils.MessagebarAndLog")
    def test_draw_stratigraphy_and_water_level_pipeline(self, mock_messagebar):
        """Draw pipeline with both stratigraphy bars and a water-level date.

        Verifies that the combined stratigraphy + water-level path completes
        cleanly and populates the expected plot handles.
        """
        self._insert_line_and_points()
        self._insert_stratigraphy()
        self._insert_w_levels()
        self._create_vlayer()

        @mock.patch("midvatten.tools.sectionplot.common_utils.find_layer")
        @mock.patch(
            "midvatten.tools.sectionplot.common_utils.get_selected_object_names",
            autospec=True,
        )
        @mock.patch("qgis.utils.iface", autospec=True)
        def _run(mock_iface, mock_getselected, mock_findlayer):
            mock_iface.mapCanvas.return_value.currentLayer.return_value = self.vlayer
            self.iface.mapCanvas.return_value.currentLayer.return_value = self.vlayer
            mock_findlayer.return_value.isEditable.return_value = False
            mock_getselected.return_value = ("P1", "P2")
            mock_iface.mapCanvas.return_value.layerCount.return_value = 0

            self.midvatten.plot_section()
            secplot = self.midvatten.sectionplot
            secplot.plot_stratigraphy.setChecked(True)
            gui_utils.set_combobox(secplot.wlvltable, "w_levels")
            secplot.datetime.append("2020-01-01")
            secplot.drillstop.setText("")
            secplot.draw_plot()
            return secplot

        secplot = _run()

        print(f"{mock_messagebar.mock_calls=}")
        assert not mock_messagebar.warning.called
        assert not mock_messagebar.critical.called

        # Should have both stratigraphy handles and a water-level line handle.
        assert len(secplot.figure.plot_handles) >= 2

    @mock.patch("midvatten.tools.sectionplot.common_utils.MessagebarAndLog")
    def test_legend_rebuild_after_artists_added(self, mock_messagebar):
        """Legend rebuild path: update_legend populates an actual legend object.

        After draw_plot() completes with create_legend checked, calling
        update_legend() explicitly should rebuild the legend on ax_main and
        the legend must contain exactly as many entries as get_legend_items_labels
        returns (i.e. bars are excluded via skip_legend=True).
        """
        self._insert_line_and_points()
        self._insert_stratigraphy()
        self._create_vlayer()

        @mock.patch("midvatten.tools.sectionplot.common_utils.find_layer")
        @mock.patch(
            "midvatten.tools.sectionplot.common_utils.get_selected_object_names",
            autospec=True,
        )
        @mock.patch("qgis.utils.iface", autospec=True)
        def _run(mock_iface, mock_getselected, mock_findlayer):
            mock_iface.mapCanvas.return_value.currentLayer.return_value = self.vlayer
            self.iface.mapCanvas.return_value.currentLayer.return_value = self.vlayer
            mock_findlayer.return_value.isEditable.return_value = False
            mock_getselected.return_value = ("P1", "P2")
            mock_iface.mapCanvas.return_value.layerCount.return_value = 0

            self.midvatten.plot_section()
            secplot = self.midvatten.sectionplot
            secplot.plot_stratigraphy.setChecked(True)
            secplot.create_legend.setChecked(True)
            secplot.drillstop.setText("")
            secplot.draw_plot()
            return secplot

        secplot = _run()

        print(f"{mock_messagebar.mock_calls=}")
        assert not mock_messagebar.warning.called
        assert not mock_messagebar.critical.called

        # Call update_legend explicitly to confirm the legend rebuild path works.
        secplot.update_legend(from_navbar=False, fig=secplot.figure)

        # The legend should now be present on the axes.
        leg = secplot.figure.ax_main.get_legend()
        assert leg is not None, "Legend must be present after update_legend()"

        # Number of legend handles must match get_legend_items_labels output.
        expected_handles, expected_labels = get_legend_items_labels(
            secplot.figure.plot_handles
        )
        try:
            actual_handles = getattr(leg, "legend_handles", None) or leg.legendHandles
        except AttributeError:
            actual_handles = leg.get_lines() + leg.get_patches()
        assert len(actual_handles) == len(expected_handles), (
            f"Legend handle count mismatch: got {len(actual_handles)}, "
            f"expected {len(expected_handles)}"
        )


# ---------------------------------------------------------------------------
# Concrete test class (spatialite only — no PostGIS available in CI)
# ---------------------------------------------------------------------------


@pytest.mark.spatialite
class TestSectionPlotSpatialiteIntegration(
    SectionPlotIntegrationMixin,
    utils_for_tests.MidvattenTestSpatialiteDbSv,
):
    pass
