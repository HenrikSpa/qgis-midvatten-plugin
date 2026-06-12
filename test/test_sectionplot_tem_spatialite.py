"""End-to-end TEM rendering tests against a real SpatiaLite database.

These tests insert synthetic tem_data (see test/synthetic_tem_data.py) into a
real Midvatten SpatiaLite database, build a real SectionPlotFigure via the
normal plot_section/draw_plot path, and then run the actual
painters.paint_tem rendering. This exercises the full
read -> parse_tem_number_list -> pcolormesh chain that the unit tests only
cover at the parser level.

The key backward-compatibility claim verified here: tem_data written as numpy
scalar reprs (np.float64(...)) renders byte-identically to the documented
[1.0, 4.0, 5.0] format, and nan/inf tokens are accepted by the parser.
"""

import os
import shutil
from unittest import mock

import numpy as np
import pytest
from qgis.core import QgsProject, QgsVectorLayer

from midvatten.test import utils_for_tests
from midvatten.test.synthetic_tem_data import synthetic_soundings
from midvatten.tools.sectionplot import painters as _painters
from midvatten.tools.utils import db_utils

# Faithful TEM display settings (paint_tem reads these keys directly, no .get).
TEM_SETTINGS = {
    "secplot_tem_shading": "nearest",
    "secplot_tem_vmin": "",
    "secplot_tem_vmax": "",
    "secplot_tem_snap": False,
    "secplot_tem_rasterized": False,
    "secplot_tem_edgecolors": "",
    "secplot_tem_colormap": "jet",
    "secplot_tem_norm": "log",
    "secplot_tem_alpha_above_doi": 1.0,
    "secplot_tem_alpha_below_doi": 0.3,
    "secplot_tem_data_fit": False,
}


class TemSpatialiteMixin:
    """Real DB + section line, with synthetic tem_data insertion helpers."""

    def setup_method(self):
        super().setup_method()
        self.midvatten.ms.settingsdict["secplot_loaded_template"] = ""
        self.midvatten.ms.settingsdict["secplot_templates"] = ""
        self.midvatten.ms.settingsdict["secplotlocation"] = 0

    def _insert_line_and_points(self):
        db_utils.sql_alter_db(
            """INSERT INTO obs_lines (obsid, geometry)
               VALUES ('L1', ST_GeomFromText('LINESTRING(0 0, 100 0)', 3006))"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO obs_points (obsid, geometry, h_gs, length)
               VALUES ('P1', ST_GeomFromText('POINT(20 0)', 3006), 50.0, 5.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO obs_points (obsid, geometry, h_gs, length)
               VALUES ('P2', ST_GeomFromText('POINT(80 0)', 3006), 48.0, 6.0)"""
        )

    def _insert_tem(self, inversion_name, fmt):
        for row in synthetic_soundings("L1", inversion_name, n_positions=5, fmt=fmt):
            db_utils.sql_alter_db(
                """INSERT INTO tem_data
                   (obsid, inversion_name, length, elevation, data_fit, doi,
                    thickness, resistivity, comment)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                all_args=(
                    row["obsid"],
                    row["inversion_name"],
                    row["length"],
                    row["elevation"],
                    row["data_fit"],
                    row["doi"],
                    row["thickness"],
                    row["resistivity"],
                    row["comment"],
                ),
            )

    def _create_vlayer(self):
        dbconnection = db_utils.DbConnectionManager()
        uri = dbconnection.uri
        uri.setDataSource("", "obs_lines", "geometry", "", "obsid")
        dbtype = db_utils.get_dbtype(dbconnection.dbtype)
        self.vlayer = QgsVectorLayer(uri.uri(), "TestLayer", dbtype)
        QgsProject.instance().addMapLayer(self.vlayer)
        self.vlayer.selectByIds([f.id() for f in self.vlayer.getFeatures()])
        dbconnection.closedb()

    def _build_figure(self):
        """Drive plot_section/draw_plot to get a real figure with line_feature."""

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
            secplot = self.midvatten.sectionplot
            secplot.drillstop.setText("")
            secplot.draw_plot()
            return secplot

        return _run()

    def _render_tem(self, secplot, inversion_name, mock_messagebar):
        settingsdict = dict(self.midvatten.ms.settingsdict)
        settingsdict.update(TEM_SETTINGS)
        settingsdict["secplot_tem_model_name"] = inversion_name
        dbconnection = secplot.dbconnection or db_utils.DbConnectionManager()
        before = len(secplot.figure.plot_handles)
        _painters.paint_tem(
            secplot.figure,
            dbconnection,
            settingsdict,
            secplot.secplot_templates.loaded_template,
        )
        return secplot.figure.plot_handles[before:]


@pytest.mark.spatialite
class TestTemRenderSpatialite(
    TemSpatialiteMixin,
    utils_for_tests.MidvattenTestSpatialiteDbSv,
):
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_plain_format_renders_pcolormesh(self, mock_messagebar):
        """The documented [1.0, 4.0, 5.0] format renders a TEM mesh cleanly."""
        self._insert_line_and_points()
        self._insert_tem("PlainModel", fmt="plain")
        self._create_vlayer()

        secplot = self._build_figure()
        new_handles = self._render_tem(secplot, "PlainModel", mock_messagebar)

        print(f"{mock_messagebar.mock_calls=}")
        # A QuadMesh (pcolormesh) artist must have been added.
        assert any(type(h).__name__ == "QuadMesh" for h in new_handles), [
            type(h).__name__ for h in new_handles
        ]
        assert not mock_messagebar.warning.called
        assert not mock_messagebar.critical.called

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_numpy_repr_renders_identically_to_plain(self, mock_messagebar):
        """np.float64(...) reprs must produce the same mesh data as plain text."""
        self._insert_line_and_points()
        self._insert_tem("PlainModel", fmt="plain")
        self._insert_tem("NumpyModel", fmt="numpy_repr")
        self._create_vlayer()

        secplot = self._build_figure()

        plain_mesh = [
            h
            for h in self._render_tem(secplot, "PlainModel", mock_messagebar)
            if type(h).__name__ == "QuadMesh"
        ]
        numpy_mesh = [
            h
            for h in self._render_tem(secplot, "NumpyModel", mock_messagebar)
            if type(h).__name__ == "QuadMesh"
        ]

        assert plain_mesh and numpy_mesh
        # The color (resistivity) arrays must be element-for-element identical.
        plain_z = np.ma.filled(plain_mesh[0].get_array(), np.nan).astype(float)
        numpy_z = np.ma.filled(numpy_mesh[0].get_array(), np.nan).astype(float)
        np.testing.assert_array_equal(plain_z, numpy_z)
        assert not mock_messagebar.critical.called

    def test_nan_inf_tokens_are_parsed(self):
        """nan/inf serialisations (old eval could not parse these) now parse."""
        rows = synthetic_soundings("L1", "NanInfModel", n_positions=5, fmt="nan_inf")
        last = rows[-1]  # the sounding with a nan thickness and inf resistivity
        thickness = _painters.parse_tem_number_list(last["thickness"], "thickness")
        resistivity = _painters.parse_tem_number_list(
            last["resistivity"], "resistivity"
        )
        assert any(np.isnan(v) for v in thickness)
        assert any(np.isinf(v) for v in resistivity)

    @pytest.mark.skipif(
        not os.environ.get("MIDV_DUMP_TEM_DB"),
        reason="set MIDV_DUMP_TEM_DB=<path> to export a demo SpatiaLite DB",
    )
    def test_export_demo_db(self):
        """Write a ready-to-open Midvatten SpatiaLite DB with synthetic TEM data.

        Run with: MIDV_DUMP_TEM_DB=/abs/path.sqlite python3 -m pytest \
            test/test_sectionplot_tem_spatialite.py::TestTemRenderSpatialite::test_export_demo_db
        Then open it in QGIS, run the Section plot on line L1, and pick the
        TEM model in the section-plot dialog.
        """
        self._insert_line_and_points()
        self._insert_tem("PlainModel", fmt="plain")
        self._insert_tem("NumpyModel", fmt="numpy_repr")
        self._insert_tem("NanInfModel", fmt="nan_inf")
        dest = os.environ["MIDV_DUMP_TEM_DB"]
        db_utils.DbConnectionManager().closedb()  # flush pending writes
        shutil.copy(self.TEMP_DBPATH, dest)
        assert os.path.getsize(dest) > 0
