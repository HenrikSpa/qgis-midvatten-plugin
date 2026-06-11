"""
/***************************************************************************
 Integration tests verifying that each SectionPlot widget/setting actually
 changes the figure output as intended.

 ONE shared database (class-level snapshot with pre-inserted test data).
 ONE shared data setup. Each test changes one widget and asserts on the figure.

                             -------------------
        begin                : 2026-04-18
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

import sqlite3 as _sqlite3
from unittest import mock

import pytest
from qgis.core import QgsProject, QgsVectorLayer
from qgis.utils import spatialite_connect

from midvatten.test import utils_for_tests
from midvatten.tools.utils import db_utils, gui_utils

_LEGEND_FILTER = frozenset(("frame", "_nolegend_", ""))


def _non_frame_handles(secplot):
    return [
        h for h in secplot.figure.plot_handles if h.get_label() not in _LEGEND_FILTER
    ]


# ---------------------------------------------------------------------------
# Mixin that adds a vlayer and drives plot_section() with the three patches
# ---------------------------------------------------------------------------


class SectionPlotWidgetEffectsMixin:
    """
    One shared database (with test data pre-inserted), one vlayer.
    Each test calls _run_base_plot() to initialise the SectionPlot, then
    tweaks one widget and calls draw_plot() before asserting.
    """

    # ------------------------------------------------------------------
    # Class-level setup: extend the base snapshot with test data
    # ------------------------------------------------------------------

    @classmethod
    def setup_class(cls):
        """Create the DB once, insert test data, overwrite the snapshot."""
        super().setup_class()

        # Insert test data into the live DB file while spatialite is available.
        src = spatialite_connect(
            cls._class_dbpath,
            detect_types=_sqlite3.PARSE_DECLTYPES | _sqlite3.PARSE_COLNAMES,
        )
        src.executescript("""
            INSERT INTO obs_lines (obsid, geometry)
            VALUES ('L1', ST_GeomFromText('LINESTRING(0 0, 100 0)', 3006));

            INSERT INTO obs_points (obsid, geometry, h_gs, length, drillstop)
            VALUES ('P1', ST_GeomFromText('POINT(20 0)', 3006), 10.0, 8.0, 'berg');

            INSERT INTO obs_points (obsid, geometry, h_gs, length, drillstop)
            VALUES ('P2', ST_GeomFromText('POINT(80 0)', 3006), 12.0, 10.0, NULL);

            INSERT INTO stratigraphy
                (obsid, stratid, depthtop, depthbot, geoshort, geology,
                 capacity, development, comment)
            VALUES
                ('P1', 1, 0.0, 4.0, 'Berg', 'Granite', '3', 'G', ''),
                ('P1', 2, 4.0, 8.0, 'Lera', 'Clay', '0', 'N', ''),
                ('P2', 1, 0.0, 5.0, 'Sand', 'Sandy gravel', '4', 'G', '');

            INSERT INTO w_levels (obsid, date_time, meas, h_toc, level_masl)
            VALUES
                ('P1', '2020-01-01 00:00:00', 2.0, NULL, 8.0),
                ('P2', '2020-01-01 00:00:00', 3.0, NULL, 9.0);

            INSERT INTO screen (obsid, screenid, depthtop, depthbot, screenshort)
            VALUES
                ('P1', 1, 2.0, 5.0, 'JWS'),
                ('P2', 1, 3.0, 7.0, 'PVC');
        """)
        src.commit()

        # Overwrite the in-memory snapshot so every test restores with data.
        cls._class_snapshot.close()
        cls._class_snapshot = _sqlite3.connect(":memory:")
        src.backup(cls._class_snapshot)
        src.close()

    # ------------------------------------------------------------------
    # Per-test setup
    # ------------------------------------------------------------------

    def setup_method(self):
        super().setup_method()
        self.midvatten.ms.settingsdict["secplot_loaded_template"] = ""
        self.midvatten.ms.settingsdict["secplot_templates"] = ""
        self.midvatten.ms.settingsdict["secplotlocation"] = 0
        self.vlayer = None

    def _create_vlayer(self):
        """Build a QgsVectorLayer from obs_lines and select all features."""
        dbconnection = db_utils.DbConnectionManager()
        uri = dbconnection.uri
        uri.setDataSource("", "obs_lines", "geometry", "", "obsid")
        dbtype = db_utils.get_dbtype(dbconnection.dbtype)
        self.vlayer = QgsVectorLayer(uri.uri(), "TestLayer", dbtype)
        QgsProject.instance().addMapLayer(self.vlayer)
        feature_ids = [f.id() for f in self.vlayer.getFeatures()]
        self.vlayer.selectByIds(feature_ids)
        dbconnection.closedb()

    def _run_base_plot(self, mock_messagebar):
        """
        Run plot_section() through the three mandatory patches and return the
        live SectionPlot instance.  Stratigraphy and drillstop are intentionally
        left unconfigured here — individual tests apply their own widget settings
        after receiving the secplot object, then call draw_plot() themselves.

        Note: create_new_plot() already calls draw_plot() once internally.
        Tests that need a fresh draw_plot() call do so after tweaking widgets.
        """
        self._create_vlayer()

        @mock.patch("midvatten.tools.utils.layer_utils.find_layer")
        @mock.patch(
            "midvatten.tools.utils.layer_utils.get_selected_object_names",
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
            return self.midvatten.sectionplot

        return _run()

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    @mock.patch("midvatten.tools.sectionplot.common_utils.MessagebarAndLog")
    def test_legend_on(self, mock_messagebar):
        """Widget: create_legend — checked → legend is present on ax_main."""
        secplot = self._run_base_plot(mock_messagebar)
        secplot.create_legend.setChecked(True)
        secplot.plot_stratigraphy.setChecked(True)
        secplot.drillstop.setText("")
        secplot.draw_plot()

        assert not mock_messagebar.critical.called
        leg = secplot.figure.ax_main.get_legend()
        assert leg is not None, "Legend must be present when create_legend is checked"

    @mock.patch("midvatten.tools.sectionplot.common_utils.MessagebarAndLog")
    def test_legend_off(self, mock_messagebar):
        """Widget: create_legend — unchecked → no legend on ax_main."""
        secplot = self._run_base_plot(mock_messagebar)
        secplot.create_legend.setChecked(False)
        secplot.plot_stratigraphy.setChecked(True)
        secplot.drillstop.setText("")
        secplot.draw_plot()

        assert not mock_messagebar.critical.called
        leg = secplot.figure.ax_main.get_legend()
        assert leg is None, "Legend must be absent when create_legend is unchecked"

    @mock.patch("midvatten.tools.sectionplot.common_utils.MessagebarAndLog")
    def test_stratigraphy_on(self, mock_messagebar):
        """Widget: plot_stratigraphy — checked → plot_handles contains stratigraphy geoshorts."""
        secplot = self._run_base_plot(mock_messagebar)
        secplot.plot_stratigraphy.setChecked(True)
        secplot.hydrology_radio_button.setChecked(False)
        secplot.drillstop.setText("")
        secplot.draw_plot()

        assert not mock_messagebar.critical.called
        assert len(secplot.figure.plot_handles) > 0, (
            "plot_handles must be populated when stratigraphy is on"
        )
        labels = {h.get_label() for h in secplot.figure.plot_handles}
        # Labels are stored as lowercase versions of the geoshort values.
        strat_geoshorts = {"berg", "lera", "sand"}
        assert labels & strat_geoshorts, (
            f"Expected at least one stratigraphy geoshort label in {labels}"
        )

    @mock.patch("midvatten.tools.sectionplot.common_utils.MessagebarAndLog")
    def test_stratigraphy_off(self, mock_messagebar):
        """Widget: radio_button (None) — selected → no geological bars in plot_handles.

        There are three radio buttons in the 'Layers' group: Geology, Hydrology, None.
        Selecting 'None' (radio_button) deactivates both stratigraphy and hydrology,
        producing an empty plot_handles list (no bars, no frame).
        """
        secplot = self._run_base_plot(mock_messagebar)
        # Select the "None" radio button to turn off both stratigraphy and hydrology.
        secplot.radio_button.setChecked(True)
        secplot.drillstop.setText("")
        # Also disable screens so only the stratigraphy-off effect is tested.
        # (The default screensplotmode was changed to "behind" after this test was
        # written, so we must set it explicitly here to isolate the assertion.)
        secplot.screens_mode_combo.setCurrentText("None")
        secplot.draw_plot()

        assert not mock_messagebar.critical.called
        # With no stratigraphy, no w_levels date, no hydrology, and no screens,
        # plot_handles should have no geological or hydro bars.  (A "frame" handle
        # may still appear; filter to non-frame/non-nolegend entries only.)
        non_frame_handles = _non_frame_handles(secplot)
        assert len(non_frame_handles) == 0, (
            f"Expected no non-frame plot handles, got: {[h.get_label() for h in non_frame_handles]}"
        )

    @mock.patch("midvatten.tools.sectionplot.common_utils.MessagebarAndLog")
    def test_hydrology_on(self, mock_messagebar):
        """Widget: hydrology_radio_button — checked → hydrology capacity bars appear in plot_handles."""
        secplot = self._run_base_plot(mock_messagebar)
        # Checking hydrology_radio_button automatically unchecks plot_stratigraphy.
        secplot.hydrology_radio_button.setChecked(True)
        secplot.drillstop.setText("")
        secplot.draw_plot()

        assert not mock_messagebar.critical.called
        assert len(secplot.figure.plot_handles) > 0, (
            "plot_handles must be populated when hydrology is on"
        )

    @mock.patch("midvatten.tools.sectionplot.common_utils.MessagebarAndLog")
    def test_labels_on(self, mock_messagebar):
        """Widget: labels_check_box — checked → obsid text annotations appear on ax_main.

        obsid_annotation holds position data (always populated when obs_points exist).
        The labels_check_box controls whether paint_obsids renders actual text
        annotations via ax_main.annotate(), which appear in ax_main.texts.
        """
        secplot = self._run_base_plot(mock_messagebar)
        secplot.labels_check_box.setChecked(True)
        secplot.plot_stratigraphy.setChecked(True)
        secplot.drillstop.setText("")
        secplot.draw_plot()

        assert not mock_messagebar.critical.called
        # Text annotations for obsid labels appear in ax_main.texts.
        label_texts = [t.get_text() for t in secplot.figure.ax_main.texts]
        assert len(label_texts) > 0, (
            "ax_main.texts must be non-empty when labels_check_box is checked"
        )
        # At least one of our obsids should appear as a label.
        assert any(t in ("P1", "P2") for t in label_texts), (
            f"Expected obsid labels in ax_main.texts, got: {label_texts}"
        )

    @mock.patch("midvatten.tools.sectionplot.common_utils.MessagebarAndLog")
    def test_labels_off(self, mock_messagebar):
        """Widget: labels_check_box — unchecked → no obsid text annotations on ax_main.

        obsid_annotation holds position data (always populated when obs_points exist).
        When labels_check_box is unchecked, paint_obsids does NOT call ax_main.annotate(),
        so ax_main.texts remains empty even though obsid_annotation has data.
        """
        secplot = self._run_base_plot(mock_messagebar)
        secplot.labels_check_box.setChecked(False)
        secplot.plot_stratigraphy.setChecked(True)
        secplot.drillstop.setText("")
        secplot.draw_plot()

        assert not mock_messagebar.critical.called
        # When labels are off, ax_main.texts should contain no obsid label annotations.
        label_texts = [t.get_text() for t in secplot.figure.ax_main.texts]
        assert not any(t in ("P1", "P2") for t in label_texts), (
            f"Expected no obsid labels in ax_main.texts when labels_check_box is unchecked, "
            f"got: {label_texts}"
        )

    @mock.patch("midvatten.tools.sectionplot.common_utils.MessagebarAndLog")
    def test_bar_width_changes(self, mock_messagebar):
        """Widget: barwidthdouble_spin_box — higher value → wider bar patches."""
        secplot = self._run_base_plot(mock_messagebar)
        secplot.plot_stratigraphy.setChecked(True)
        secplot.drillstop.setText("")

        # First draw with a narrow bar width.
        secplot.barwidthdouble_spin_box.setValue(2.0)
        secplot.draw_plot()
        narrow_patches = list(secplot.figure.ax_main.patches)
        narrow_widths = [
            abs(p.get_width()) for p in narrow_patches if p.get_width() != 0
        ]

        assert not mock_messagebar.critical.called
        assert narrow_widths, "Expected bar patches after stratigraphy draw"

        # Second draw with a wide bar width.
        secplot.barwidthdouble_spin_box.setValue(30.0)
        secplot.draw_plot()
        wide_patches = list(secplot.figure.ax_main.patches)
        wide_widths = [abs(p.get_width()) for p in wide_patches if p.get_width() != 0]

        assert wide_widths, "Expected bar patches after second draw"
        assert max(wide_widths) > max(narrow_widths), (
            f"Wide bar ({max(wide_widths)}) should be wider than narrow bar ({max(narrow_widths)})"
        )

    @mock.patch("midvatten.tools.sectionplot.common_utils.MessagebarAndLog")
    def test_screen_bars_on(self, mock_messagebar):
        """Widget: screens_mode_combo — 'Behind' → screen bars appear in plot_handles."""
        secplot = self._run_base_plot(mock_messagebar)
        # Use the "None" radio button to deactivate both stratigraphy and hydrology.
        secplot.radio_button.setChecked(True)
        secplot.drillstop.setText("")

        # Draw without screens first to get a baseline.
        secplot.screens_mode_combo.setCurrentText("None")
        secplot.draw_plot()
        handles_without_screens = len(secplot.figure.plot_handles)

        # Now enable screens.
        secplot.screens_mode_combo.setCurrentText("Behind")
        secplot.draw_plot()
        handles_with_screens = len(secplot.figure.plot_handles)

        assert not mock_messagebar.critical.called
        assert handles_with_screens > handles_without_screens, (
            f"Screen bars should add to plot_handles: "
            f"without={handles_without_screens}, with={handles_with_screens}"
        )

    @mock.patch("midvatten.tools.sectionplot.common_utils.MessagebarAndLog")
    def test_screen_bars_off(self, mock_messagebar):
        """Widget: screens_mode_combo — 'None' → screen bars absent from plot_handles."""
        secplot = self._run_base_plot(mock_messagebar)
        # Use the "None" radio button to deactivate both stratigraphy and hydrology.
        secplot.radio_button.setChecked(True)
        secplot.drillstop.setText("")
        secplot.screens_mode_combo.setCurrentText("None")
        secplot.draw_plot()

        assert not mock_messagebar.critical.called
        # No stratigraphy, no hydrology, no screens → no non-frame handles.
        non_frame_handles = _non_frame_handles(secplot)
        assert len(non_frame_handles) == 0, (
            f"Expected no screen bars when mode is None, got: "
            f"{[h.get_label() for h in non_frame_handles]}"
        )

    @mock.patch("midvatten.tools.sectionplot.common_utils.MessagebarAndLog")
    def test_water_level_plotted(self, mock_messagebar):
        """Widget: wlvltable + datetime — w_levels date → water level line in plot_handles."""
        secplot = self._run_base_plot(mock_messagebar)
        secplot.plot_stratigraphy.setChecked(False)
        secplot.drillstop.setText("")
        gui_utils.set_combobox(secplot.wlvltable, "w_levels")
        secplot.datetime.clear()
        secplot.datetime.append("2020-01-01")
        secplot.draw_plot()

        assert not mock_messagebar.critical.called
        # A water-level line should appear in plot_handles.
        wlvl_handles = _non_frame_handles(secplot)
        assert len(wlvl_handles) >= 1, (
            "Expected at least one water-level handle in plot_handles"
        )

    @mock.patch("midvatten.tools.sectionplot.common_utils.MessagebarAndLog")
    def test_drillstop_shows_bar(self, mock_messagebar):
        """Widget: drillstop — non-empty pattern with matching data → drillstop handle in plot_handles.

        drillstops are computed once in create_new_plot() using ms.settingsdict['secplotdrillstop'].
        We pre-set that key to '%berg%' BEFORE calling _run_base_plot() so create_new_plot()
        finds P1.drillstop='berg' (lower() LIKE match) and populates self.drillstops.
        draw_plot() then paints the drillstop bar when secplotdrillstop != '' and drillstops non-empty.
        """
        # Pre-set the drillstop key so create_new_plot() uses it when computing drillstops.
        self.midvatten.ms.settingsdict["secplotdrillstop"] = "%berg%"
        secplot = self._run_base_plot(mock_messagebar)
        secplot.plot_stratigraphy.setChecked(True)
        secplot.drillstop.setText("%berg%")
        secplot.draw_plot()

        assert not mock_messagebar.critical.called
        drillstop_handles = [
            h
            for h in secplot.figure.plot_handles
            if "drillstop" in h.get_label().lower()
        ]
        assert len(drillstop_handles) >= 1, (
            "Expected a drillstop handle in plot_handles when pattern matches data"
        )

    @mock.patch("midvatten.tools.sectionplot.common_utils.MessagebarAndLog")
    def test_drillstop_no_match(self, mock_messagebar):
        """Widget: drillstop — empty string → drillstop bar suppressed even when drillstops exist.

        drillstops are computed in create_new_plot() and cached on self.drillstops.
        Pre-set secplotdrillstop so drillstops is populated. Then set drillstop widget
        to '' in the test draw — draw_plot() guards painting with secplotdrillstop != ''
        so the bar is suppressed even though self.drillstops is non-empty.
        """
        # Pre-set the drillstop key so create_new_plot() populates self.drillstops.
        self.midvatten.ms.settingsdict["secplotdrillstop"] = "%berg%"
        secplot = self._run_base_plot(mock_messagebar)
        secplot.plot_stratigraphy.setChecked(True)
        # Empty string → secplotdrillstop == '' → paint_drill_stop is skipped.
        secplot.drillstop.setText("")
        secplot.draw_plot()

        assert not mock_messagebar.critical.called
        drillstop_handles = [
            h
            for h in secplot.figure.plot_handles
            if "drillstop" in h.get_label().lower()
        ]
        assert len(drillstop_handles) == 0, (
            "Expected no drillstop handles when drillstop text is empty"
        )

    @mock.patch("midvatten.tools.sectionplot.common_utils.MessagebarAndLog")
    def test_include_views_off_no_views_in_combo(self, mock_messagebar):
        """Widget: include_views_check_box — unchecked → wlvltable combo has no view names."""
        secplot = self._run_base_plot(mock_messagebar)
        secplot.include_views_check_box.setChecked(False)
        secplot.fill_wlvltable(include_views=False)

        assert not mock_messagebar.critical.called
        combo_items = [
            secplot.wlvltable.itemText(i) for i in range(secplot.wlvltable.count())
        ]
        # SpatiaLite views start with 'v_' by convention.
        view_items = [item for item in combo_items if item.startswith("v_")]
        assert len(view_items) == 0, (
            f"Expected no views in wlvltable when include_views is False, "
            f"got: {view_items}"
        )

    @mock.patch("midvatten.tools.sectionplot.common_utils.MessagebarAndLog")
    def test_bar_width_factor_screen_width(self, mock_messagebar):
        """Widget: screen_width_factor_spin — higher factor → wider screen bar patches.

        screen_bars are computed once in create_new_plot() only when
        screensplotmode != 'none'.  Pre-set that key so create_new_plot()
        fetches the screen data from the DB; then toggle width_factor to compare.
        """
        # Pre-set screensplotmode so create_new_plot() fetches screen_bars.
        self.midvatten.ms.settingsdict["screensplotmode"] = "behind"
        secplot = self._run_base_plot(mock_messagebar)
        # Use the "None" radio button to deactivate both stratigraphy and hydrology.
        secplot.radio_button.setChecked(True)
        secplot.drillstop.setText("")
        secplot.screens_mode_combo.setCurrentText("Behind")

        # secplotbw defaults to 0 when loaded from an empty QgsProject; set it
        # explicitly so barwidth is non-zero and screen bars are visible.
        secplot.barwidthdouble_spin_box.setValue(5.0)

        # Draw with a narrow screen width factor.
        narrow_factor = 0.2
        secplot.screen_width_factor_spin.setValue(narrow_factor)
        secplot.draw_plot()
        narrow_patches = list(secplot.figure.ax_main.patches)
        narrow_widths = sorted(
            [abs(p.get_width()) for p in narrow_patches if p.get_width() != 0]
        )

        assert not mock_messagebar.critical.called
        assert narrow_widths, "Expected screen bar patches with screens mode=Behind"

        # Draw with a wide screen width factor.
        wide_factor = 5.0
        secplot.screen_width_factor_spin.setValue(wide_factor)
        secplot.draw_plot()
        wide_patches = list(secplot.figure.ax_main.patches)
        wide_widths = sorted(
            [abs(p.get_width()) for p in wide_patches if p.get_width() != 0]
        )

        assert wide_widths, "Expected screen bar patches after second draw"
        assert max(wide_widths) > max(narrow_widths), (
            f"Larger width factor ({wide_factor}) should produce wider bars than smaller factor ({narrow_factor}): "
            f"max_wide={max(wide_widths)}, max_narrow={max(narrow_widths)}"
        )


# ---------------------------------------------------------------------------
# Concrete test class (spatialite only — no PostGIS available in CI)
# ---------------------------------------------------------------------------


@pytest.mark.spatialite
class TestSectionPlotWidgetEffects(
    SectionPlotWidgetEffectsMixin,
    utils_for_tests.MidvattenTestSpatialiteDbSv,
):
    pass
