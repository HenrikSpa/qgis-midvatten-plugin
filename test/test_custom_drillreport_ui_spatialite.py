"""
Tests for DrillreportUi (custom drill report dialog) using SQLite.
"""

import os
import re
from unittest import mock

import pytest
from qgis.PyQt import QtCore

from midvatten.test import utils_for_tests
from midvatten.tools.custom_drillreport import DrillreportUi
from midvatten.tools.utils import db_utils


def _insert_drillreport_test_data(obsids=None):
    """Insert obs_points and stratigraphy for custom drill report tests."""
    if obsids is None:
        obsids = ["OP1", "OP2"]
    for i, oid in enumerate(obsids):
        east = 633466 + i * 100
        north = 711659 + i * 100
        db_utils.sql_alter_db(
            f"""INSERT INTO obs_points (obsid, east, north, h_gs, geometry)
                VALUES ('{oid}', {east}, {north}, {5 + i * 5},
                ST_GeomFromText('POINT({east} {north})', 3006))"""
        )
    for oid in obsids:
        db_utils.sql_alter_db(
            f"""INSERT INTO stratigraphy (obsid, stratid, depthtop, depthbot, geology, geoshort, capacity, development)
                VALUES ('{oid}', 1, 0, 1, 'sand', 'sand', '3', 'j')"""
        )


def _report_path():
    return os.path.join(
        QtCore.QDir.tempPath(), "midvatten_reports", "drill_report.html"
    )


def _normalize_report_html(html):
    """Normalize paths in HTML for reproducible assertions."""
    html = re.sub(
        r'src="[a-zA-ZåäöÅÄÖ0-9/]+midvatten/tools/',
        'src="midvatten/tools/',
        html,
    )
    html = re.sub(
        r"src='[a-zA-ZåäöÅÄÖ0-9/]+midvatten/tools/",
        "src='midvatten/tools/",
        html,
    )
    return html


@pytest.mark.spatialite
class TestDrillreportUi(utils_for_tests.MidvattenTestSpatialiteDbSv):
    """Tests for DrillreportUi (custom drill report)."""

    @mock.patch("midvatten.tools.custom_drillreport.QDesktopServices.openUrl")
    @mock.patch("midvatten.tools.utils.layer_utils.get_selected_object_names")
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    @mock.patch("qgis.utils.iface", autospec=True)
    def test_ok_button_generates_html(
        self, mock_iface, mock_messagebar, mock_getselected, mock_openurl
    ):
        _insert_drillreport_test_data(["OP1"])
        mock_getselected.return_value = ["OP1"]
        with mock.patch(
            "midvatten.tools.custom_drillreport.common_utils.get_stored_settings",
            return_value={},
        ):
            ui = DrillreportUi(self.iface, self.midvatten.ms)
        ui.drillreport()
        print(f"{mock_messagebar.mock_calls=}")
        assert mock_openurl.called
        reportpath = _report_path()
        assert os.path.isfile(reportpath)
        with open(reportpath, encoding="utf-8") as f:
            report = _normalize_report_html(f.read())
        assert "OP1" in report
        assert "sand" in report
        assert "0" in report and "1" in report

    @mock.patch("midvatten.tools.utils.layer_utils.get_selected_object_names")
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    @mock.patch("qgis.utils.iface", autospec=True)
    def test_no_selection_shows_message(
        self, mock_iface, mock_messagebar, mock_getselected
    ):
        mock_getselected.return_value = []
        with mock.patch(
            "midvatten.tools.custom_drillreport.common_utils.get_stored_settings",
            return_value={},
        ):
            ui = DrillreportUi(self.iface, self.midvatten.ms)
        ui.drillreport()
        print(f"{mock_messagebar.mock_calls=}")
        mock_messagebar.critical.assert_called_once()
        call_args = mock_messagebar.critical.call_args
        assert "obsid" in str(call_args).lower() or "select" in str(call_args).lower()

    @mock.patch(
        "midvatten.tools.custom_drillreport.common_utils.get_stored_settings",
        return_value={},
    )
    def test_cancel_button_closes(self, mock_get_stored):
        ui = DrillreportUi(self.iface, self.midvatten.ms)
        ui.push_button_cancel.clicked.emit()
        assert not ui.isVisible()

    @mock.patch("midvatten.tools.custom_drillreport.QDesktopServices.openUrl")
    @mock.patch("midvatten.tools.utils.layer_utils.get_selected_object_names")
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    @mock.patch("qgis.utils.iface", autospec=True)
    def test_checkboxes_affect_export(
        self, mock_iface, mock_messagebar, mock_getselected, mock_openurl
    ):
        _insert_drillreport_test_data(["OP1"])
        mock_getselected.return_value = ["OP1"]
        with mock.patch(
            "midvatten.tools.custom_drillreport.common_utils.get_stored_settings",
            return_value={},
        ):
            ui = DrillreportUi(self.iface, self.midvatten.ms)
        ui.empty_row_between_obsids.setChecked(True)
        ui.drillreport()
        print(f"{mock_messagebar.mock_calls=}")
        with open(_report_path(), encoding="utf-8") as f:
            report = f.read()
        assert "empty_row_between_obsids" in report

    @mock.patch("midvatten.tools.custom_drillreport.QDesktopServices.openUrl")
    @mock.patch("midvatten.tools.utils.layer_utils.get_selected_object_names")
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    @mock.patch("qgis.utils.iface", autospec=True)
    def test_plain_text_metadata_columns_affect_export(
        self, mock_iface, mock_messagebar, mock_getselected, mock_openurl
    ):
        _insert_drillreport_test_data(["OP1"])
        mock_getselected.return_value = ["OP1"]
        with mock.patch(
            "midvatten.tools.custom_drillreport.common_utils.get_stored_settings",
            return_value={},
        ):
            ui = DrillreportUi(self.iface, self.midvatten.ms)
        ui.general_metadata.setPlainText("obsid\nh_gs")
        ui.geo_metadata.setPlainText("east\nnorth")
        ui.strat_columns.setPlainText("depth\ngeology\ngeoshort")
        ui.drillreport()
        print(f"{mock_messagebar.mock_calls=}")
        with open(_report_path(), encoding="utf-8") as f:
            report = f.read()
        assert "OP1" in report
        assert "sand" in report
        assert "633466" in report or "east" in report.lower()

    @mock.patch("midvatten.tools.custom_drillreport.QDesktopServices.openUrl")
    @mock.patch("midvatten.tools.utils.layer_utils.get_selected_object_names")
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    @mock.patch("qgis.utils.iface", autospec=True)
    def test_line_edit_headers_affect_export(
        self, mock_iface, mock_messagebar, mock_getselected, mock_openurl
    ):
        _insert_drillreport_test_data(["OP1"])
        mock_getselected.return_value = ["OP1"]
        with mock.patch(
            "midvatten.tools.custom_drillreport.common_utils.get_stored_settings",
            return_value={},
        ):
            ui = DrillreportUi(self.iface, self.midvatten.ms)
        ui.general_metadata_header.setText("Custom general")
        ui.geo_metadata_header.setText("Custom geo")
        ui.drillreport()
        print(f"{mock_messagebar.mock_calls=}")
        with open(_report_path(), encoding="utf-8") as f:
            report = f.read()
        assert "Custom general" in report
        assert "Custom geo" in report

    @mock.patch("midvatten.tools.custom_drillreport.QDesktopServices.openUrl")
    @mock.patch("midvatten.tools.utils.layer_utils.get_selected_object_names")
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    @mock.patch("qgis.utils.iface", autospec=True)
    def test_decimal_separator_affect_export(
        self, mock_iface, mock_messagebar, mock_getselected, mock_openurl
    ):
        _insert_drillreport_test_data(["OP1"])
        mock_getselected.return_value = ["OP1"]
        with mock.patch(
            "midvatten.tools.custom_drillreport.common_utils.get_stored_settings",
            return_value={},
        ):
            ui = DrillreportUi(self.iface, self.midvatten.ms)
        ui.decimal_separator.setText(",")
        ui.general_metadata.setPlainText("h_gs")
        ui.strat_columns.setPlainText("depth")
        ui.drillreport()
        print(f"{mock_messagebar.mock_calls=}")
        with open(_report_path(), encoding="utf-8") as f:
            report = f.read()
        assert "5,0" in report or "0,0" in report or "1,0" in report

    @mock.patch(
        "midvatten.tools.custom_drillreport.qgis.PyQt.QtWidgets.QInputDialog.getText"
    )
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_update_settings_from_string(self, mock_messagebar, mock_gettext):
        mock_gettext.return_value = (
            (
                "{'header_in_table': False, 'skip_empty': True, "
                "'include_comments': False, 'empty_row_between_obsids': True, "
                "'general_metadata_header': 'MyHeader'}"
            ),
            True,
        )
        with mock.patch(
            "midvatten.tools.custom_drillreport.common_utils.get_stored_settings",
            return_value={},
        ):
            ui = DrillreportUi(self.iface, self.midvatten.ms)
        ui.push_button_update_from_string.clicked.emit()
        print(f"{mock_messagebar.mock_calls=}")
        assert ui.header_in_table.isChecked() is False
        assert ui.skip_empty.isChecked() is True
        assert ui.include_comments.isChecked() is False
        assert ui.empty_row_between_obsids.isChecked() is True
        assert ui.general_metadata_header.text() == "MyHeader"

    @mock.patch(
        "midvatten.tools.custom_drillreport.common_utils.get_stored_settings",
        return_value={},
    )
    def test_save_and_restore_stored_settings(self, mock_get_stored):
        ui1 = DrillreportUi(self.iface, self.midvatten.ms)
        ui1.general_metadata_header.setText("SavedHeader")
        ui1.header_in_table.setChecked(False)
        ui1.skip_empty.setChecked(True)
        ui1.save_stored_settings()
        stored = dict(ui1.stored_settings)
        ui2 = DrillreportUi(self.iface, self.midvatten.ms)
        ui2.update_from_stored_settings(stored)
        assert ui2.general_metadata_header.text() == "SavedHeader"
        assert ui2.header_in_table.isChecked() is False
        assert ui2.skip_empty.isChecked() is True
