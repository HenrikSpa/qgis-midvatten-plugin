"""FieldForm export hardening: silent-failure cases turned into messages.

FieldForm skips locations whose coordinates are unusable and, over FTP, only
picks up files named locations*.json (each name once). The exporter must
therefore refuse untransformed coordinates and invalid layer CRSs, and steer
the user towards a working file name.
"""

import re
from unittest import mock

import pytest
from qgis.PyQt.QtCore import QMetaType
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsProject,
    QgsVectorLayer,
)

from midvatten.test.utils_for_tests import MidvattenTestBase, create_vectorlayer
from midvatten.tools import export_fieldlogger
from midvatten.tools.export_fieldlogger import ExportToFieldLogger
from midvatten.tools.utils.exceptions import UsageError


@pytest.mark.active
class TestValidateLatlons:
    def test_untransformed_coordinates_raise_with_obsids(self):
        latlons = {
            "ok": (60.5, 15.4),
            "sweref": (6712345.0, 512345.0),
            "lon_only_bad": (59.0, 181.0),
        }
        with pytest.raises(UsageError) as excinfo:
            export_fieldlogger.validate_latlons(latlons)
        msg = str(excinfo.value)
        assert "sweref" in msg and "lon_only_bad" in msg and "ok" not in msg

    def test_wgs84_and_missing_coordinates_pass(self):
        export_fieldlogger.validate_latlons(
            {"a": (60.5, 15.4), "b": (None, None), "c": (-33.9, -70.6)}
        )


@pytest.mark.active
class TestLayerCrs(MidvattenTestBase):
    @mock.patch("midvatten.tools.export_fieldlogger.db_utils.tables_columns")
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_layer_without_valid_crs_raises_usage_error(
        self, mock_messagebar, mock_tables_columns
    ):
        mock_tables_columns.return_value = {}
        vlayer = QgsVectorLayer("Point", "nocrs", "memory")
        vlayer.setCrs(QgsCoordinateReferenceSystem())
        provider = vlayer.dataProvider()
        provider.addAttributes([QgsField("obsid", QMetaType.Type.QString)])
        vlayer.updateFields()
        feature = QgsFeature(vlayer.fields())
        feature["obsid"] = "obsid1"
        feature.setGeometry(QgsGeometry.fromWkt("POINT(6712345.0 512345.0)"))
        provider.addFeatures([feature])
        assert not vlayer.crs().isValid()
        QgsProject.instance().addMapLayer(vlayer)
        mock_ms = mock.MagicMock()
        mock_ms.settingsdict = {}
        exporter = ExportToFieldLogger(None, mock_ms)
        exporter.obslayer.vectorlayer_list.setCurrentIndex(0)

        with pytest.raises(UsageError) as excinfo:
            exporter.obslayer.get_latlon_for_features()
        assert "nocrs" in str(excinfo.value)
        print(f"{mock_messagebar.mock_calls=}")

    @mock.patch("midvatten.tools.export_fieldlogger.db_utils.tables_columns")
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_export_refuses_untransformed_coordinates(
        self, mock_messagebar, mock_tables_columns
    ):
        """A layer whose declared CRS is EPSG:4326 but whose coordinates are
        projected metres must not produce a file FieldForm silently ignores."""
        mock_tables_columns.return_value = {}
        create_vectorlayer(
            [QgsField("obsid", QMetaType.Type.QString)],
            [["obsid1"]],
            geometries=[QgsGeometry.fromWkt("POINT(512345.0 6712345.0)")],
            crs=4326,
        )
        mock_ms = mock.MagicMock()
        mock_ms.settingsdict = {}
        exporter = ExportToFieldLogger(None, mock_ms)
        exporter.obslayer.vectorlayer_list.setCurrentIndex(0)

        with pytest.raises(UsageError) as excinfo:
            exporter.get_latlons()
        assert "obsid1" in str(excinfo.value)

        # Preview and export share get_latlons; both must surface the error as
        # a message-bar notice instead of an uncaught exception.
        exporter.preview()
        exporter.export()
        print(f"{mock_messagebar.mock_calls=}")
        assert mock_messagebar.critical.call_count == 2
        assert "obsid1" in str(mock_messagebar.critical.call_args)


@pytest.mark.active
class TestFieldFormFileName(MidvattenTestBase):
    @mock.patch(
        "midvatten.tools.export_fieldlogger.common_utils.get_save_file_name_no_extension"
    )
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_fieldform_save_dialog_proposes_locations_name(
        self, mock_messagebar, mock_get_save_file_name
    ):
        mock_get_save_file_name.return_value = "/nonexistent-dir/x.json"
        ExportToFieldLogger.write_to_file(
            "{}", filter="json (*.json)", default_name="locations_2026-09-02.json"
        )
        kwargs = mock_get_save_file_name.call_args.kwargs
        assert kwargs["directory"] == "locations_2026-09-02.json"

    def test_fieldform_default_name_matches_ftp_pattern(self):
        name = ExportToFieldLogger.fieldform_default_filename()
        assert re.fullmatch(r"locations_\d{4}-\d{2}-\d{2}\.json", name)

    @mock.patch("midvatten.tools.export_fieldlogger.db_utils.tables_columns")
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_fieldform_radio_tooltip_explains_ftp_naming(
        self, mock_messagebar, mock_tables_columns
    ):
        mock_tables_columns.return_value = {}
        mock_ms = mock.MagicMock()
        mock_ms.settingsdict = {}
        exporter = ExportToFieldLogger(None, mock_ms)
        assert "locations" in exporter.export_as_fieldform.toolTip()
