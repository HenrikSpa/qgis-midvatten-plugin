"""
Tests for CompactWqualReportUi (compact water quality report dialog) using SQLite.
"""

import os
from unittest import mock

from nose.plugins.attrib import attr
from qgis.core import QgsProject, QgsVectorLayer
from qgis.PyQt import QtCore

from midvatten.test import utils_for_tests
from midvatten.tools.utils import db_utils
from midvatten.tools.utils import gui_utils
from midvatten.tools.wqualreport_compact import CompactWqualReportUi


def _insert_wqual_test_data(obsid: str = "WQ1") -> None:
    """Insert obs_points and w_qual_lab for compact water quality report tests."""
    db_utils.sql_alter_db(
        f"""INSERT INTO obs_points (obsid, geometry)
            VALUES ('{obsid}', ST_GeomFromText('POINT(633466 711659)', 3006))"""
    )
    # 10 rows in w_qual_lab: unique (report, parameter), varied reading_num/reading_txt
    wqual_rows = [
        ("R1", "Iron", 123.45, "123.45", "2024-01-15 10:00"),
        ("R2", "Calcium", -42.1, "<0.5", "2024-01-15 10:00"),
        ("R3", "Magnesium", 256.78, "256.78", "2024-01-15 10:00"),
        ("R4", "Sodium", 0.0012, "<0.001", "2024-01-15 10:00"),
        ("R5", "Potassium", -100.5, "-100.5", "2024-01-15 10:00"),
        ("R6", "Chloride", 45.0, "45.0", "2024-01-15 10:00"),
        ("R7", "Sulphate", 312.3456, "<312.35", "2024-01-15 10:00"),
        ("R8", "Bicarbonate", 88.9, "88.9", "2024-01-15 10:00"),
        ("R9", "Nitrate", -200.0, "-200", "2024-01-15 10:00"),
        ("R10", "pH", 7.2, "7.2", "2024-01-15 10:00"),
    ]
    for report, parameter, reading_num, reading_txt, date_time in wqual_rows:
        db_utils.sql_alter_db(
            f"""INSERT INTO w_qual_lab (obsid, report, parameter, reading_num, reading_txt, unit, date_time)
                VALUES ('{obsid}', '{report}', '{parameter}', {reading_num}, '{reading_txt}', 'mg/l', '{date_time}')"""
        )


def _report_path() -> str:
    return os.path.join(
        QtCore.QDir.tempPath(), "midvatten_reports", "w_qual_report.html"
    )


def _create_wqual_lab_layer():
    """Create QgsVectorLayer from w_qual_lab_geom view, select all, add to project."""
    dbconnection = db_utils.DbConnectionManager()
    uri = dbconnection.uri
    uri.setDataSource("", "w_qual_lab_geom", "geometry", "", "rowid")
    dbtype = db_utils.get_dbtype(dbconnection.dbtype)
    vlayer = QgsVectorLayer(uri.uri(), "w_qual_lab_test", dbtype)
    QgsProject.instance().addMapLayer(vlayer)
    feature_ids = [f.id() for f in vlayer.getFeatures()]
    vlayer.selectByIds(feature_ids)
    dbconnection.closedb()
    return vlayer


@attr(status="on")
class TestCompactWqualReportUi(utils_for_tests.MidvattenTestSpatialiteDbSv):
    """Tests for CompactWqualReportUi (compact water quality report)."""

    @mock.patch("midvatten.tools.wqualreport_compact.open_report_in_browser")
    @mock.patch(
        "midvatten.tools.wqualreport_compact.common_utils.getselectedobjectnames"
    )
    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    @mock.patch("qgis.utils.iface", autospec=True)
    def test_ok_button_generates_html_from_sql_table(
        self, mock_iface, mock_messagebar, mock_getselected, mock_openurl
    ):
        _insert_wqual_test_data("WQ1")
        mock_getselected.return_value = ["WQ1"]
        with mock.patch(
            "midvatten.tools.wqualreport_compact.common_utils.get_stored_settings",
            return_value={},
        ):
            ui = CompactWqualReportUi(self.iface.mainWindow(), self.midvatten.ms)
        ui.from_sql_table.setChecked(True)
        gui_utils.set_combobox(ui.sql_table, "w_qual_lab", add_if_not_exists=False)
        gui_utils.set_combobox(ui.data_column, "reading_txt", add_if_not_exists=False)
        ui.wqualreport()
        print(f"{mock_messagebar.mock_calls=}")
        assert mock_openurl.called
        reportpath = _report_path()
        assert os.path.isfile(reportpath)
        with open(reportpath, encoding="utf-8") as f:
            report = f.read()
        assert "WQ1" in report
        assert "Iron" in report
        assert "Calcium" in report
        assert "mg/l" in report

    @mock.patch("midvatten.tools.wqualreport_compact.open_report_in_browser")
    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    @mock.patch("qgis.utils.iface", autospec=True)
    def test_ok_button_generates_html_from_active_layer(
        self, mock_iface, mock_messagebar, mock_openurl
    ):
        _insert_wqual_test_data("WQ1")
        vlayer = _create_wqual_lab_layer()
        mock_iface.activeLayer.return_value = vlayer
        with mock.patch(
            "midvatten.tools.wqualreport_compact.common_utils.get_stored_settings",
            return_value={},
        ):
            ui = CompactWqualReportUi(self.iface.mainWindow(), self.midvatten.ms)
        ui.from_active_layer.setChecked(True)
        ui.set_columns_from_activelayer()
        gui_utils.set_combobox(ui.data_column, "reading_txt", add_if_not_exists=False)
        ui.wqualreport()
        print(f"{mock_messagebar.mock_calls=}")
        assert mock_openurl.called
        reportpath = _report_path()
        assert os.path.isfile(reportpath)
        with open(reportpath, encoding="utf-8") as f:
            report = f.read()
        assert "WQ1" in report
        assert "Iron" in report
        assert "mg/l" in report

    @mock.patch("midvatten.tools.wqualreport_compact.open_report_in_browser")
    @mock.patch(
        "midvatten.tools.wqualreport_compact.common_utils.getselectedobjectnames"
    )
    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    @mock.patch("qgis.utils.iface", autospec=True)
    def test_combobox_data_column_affects_export(
        self, mock_iface, mock_messagebar, mock_getselected, mock_openurl
    ):
        _insert_wqual_test_data("WQ1")
        mock_getselected.return_value = ["WQ1"]
        with mock.patch(
            "midvatten.tools.wqualreport_compact.common_utils.get_stored_settings",
            return_value={},
        ):
            ui = CompactWqualReportUi(self.iface.mainWindow(), self.midvatten.ms)
        ui.from_sql_table.setChecked(True)
        gui_utils.set_combobox(ui.sql_table, "w_qual_lab", add_if_not_exists=False)
        gui_utils.set_combobox(ui.data_column, "reading_txt", add_if_not_exists=False)
        ui.wqualreport()
        with open(_report_path(), encoding="utf-8") as f:
            report_txt = f.read()
        assert "<0.5" in report_txt or "0.5" in report_txt
        gui_utils.set_combobox(ui.data_column, "reading_num", add_if_not_exists=False)
        ui.wqualreport()
        with open(_report_path(), encoding="utf-8") as f:
            report_num = f.read()
        assert "-42.1" in report_num or "123.45" in report_num
        print(f"{mock_messagebar.mock_calls=}")

    @mock.patch("midvatten.tools.wqualreport_compact.open_report_in_browser")
    @mock.patch(
        "midvatten.tools.wqualreport_compact.common_utils.getselectedobjectnames"
    )
    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    @mock.patch("qgis.utils.iface", autospec=True)
    def test_radio_empty_row_between_tables(
        self, mock_iface, mock_messagebar, mock_getselected, mock_openurl
    ):
        _insert_wqual_test_data("WQ1")
        mock_getselected.return_value = ["WQ1"]
        with mock.patch(
            "midvatten.tools.wqualreport_compact.common_utils.get_stored_settings",
            return_value={},
        ):
            ui = CompactWqualReportUi(self.iface.mainWindow(), self.midvatten.ms)
        ui.from_sql_table.setChecked(True)
        gui_utils.set_combobox(ui.sql_table, "w_qual_lab", add_if_not_exists=False)
        ui.empty_row_between_tables.setChecked(True)
        ui.page_break_between_tables.setChecked(False)
        ui.wqualreport()
        print(f"{mock_messagebar.mock_calls=}")
        with open(_report_path(), encoding="utf-8") as f:
            report = f.read()
        assert "empty_row_between_tables" in report

    @mock.patch("midvatten.tools.wqualreport_compact.open_report_in_browser")
    @mock.patch(
        "midvatten.tools.wqualreport_compact.common_utils.getselectedobjectnames"
    )
    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    @mock.patch("qgis.utils.iface", autospec=True)
    def test_radio_page_break_between_tables(
        self, mock_iface, mock_messagebar, mock_getselected, mock_openurl
    ):
        _insert_wqual_test_data("WQ1")
        mock_getselected.return_value = ["WQ1"]
        with mock.patch(
            "midvatten.tools.wqualreport_compact.common_utils.get_stored_settings",
            return_value={},
        ):
            ui = CompactWqualReportUi(self.iface.mainWindow(), self.midvatten.ms)
        ui.from_sql_table.setChecked(True)
        gui_utils.set_combobox(ui.sql_table, "w_qual_lab", add_if_not_exists=False)
        ui.page_break_between_tables.setChecked(True)
        ui.wqualreport()
        print(f"{mock_messagebar.mock_calls=}")
        with open(_report_path(), encoding="utf-8") as f:
            report = f.read()
        assert "page-break-before" in report

    @mock.patch("midvatten.tools.wqualreport_compact.open_report_in_browser")
    @mock.patch(
        "midvatten.tools.wqualreport_compact.common_utils.getselectedobjectnames"
    )
    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    @mock.patch("qgis.utils.iface", autospec=True)
    def test_line_edit_num_data_cols_affects_export(
        self, mock_iface, mock_messagebar, mock_getselected, mock_openurl
    ):
        _insert_wqual_test_data("WQ1")
        mock_getselected.return_value = ["WQ1"]
        with mock.patch(
            "midvatten.tools.wqualreport_compact.common_utils.get_stored_settings",
            return_value={},
        ):
            ui = CompactWqualReportUi(self.iface.mainWindow(), self.midvatten.ms)
        ui.from_sql_table.setChecked(True)
        gui_utils.set_combobox(ui.sql_table, "w_qual_lab", add_if_not_exists=False)
        ui.num_data_cols.setText("3")
        ui.rowheader_colwidth_percent.setText("25")
        ui.wqualreport()
        print(f"{mock_messagebar.mock_calls=}")
        reportpath = _report_path()
        assert os.path.isfile(reportpath)
        with open(reportpath, encoding="utf-8") as f:
            report = f.read()
        assert "WQ1" in report
        assert "25" in report or "25%" in report

    @mock.patch(
        "midvatten.tools.wqualreport_compact.common_utils.get_stored_settings",
        return_value={},
    )
    def test_sql_table_populates_data_column(self, mock_get_stored):
        _insert_wqual_test_data("WQ1")
        ui = CompactWqualReportUi(self.iface.mainWindow(), self.midvatten.ms)
        ui.from_sql_table.setChecked(True)
        gui_utils.set_combobox(ui.sql_table, "w_qual_lab", add_if_not_exists=False)
        ui.set_columns_from_sql_layer()
        data_col_items = [
            ui.data_column.itemText(i) for i in range(ui.data_column.count())
        ]
        assert "reading_txt" in data_col_items
        assert "reading_num" in data_col_items
        assert "parameter" in data_col_items

    @mock.patch(
        "midvatten.tools.wqualreport_compact.common_utils.getselectedobjectnames"
    )
    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    @mock.patch("qgis.utils.iface", autospec=True)
    def test_date_time_as_columns_without_sort_shows_message(
        self, mock_iface, mock_messagebar, mock_getselected
    ):
        _insert_wqual_test_data("WQ1")
        mock_getselected.return_value = ["WQ1"]
        with mock.patch(
            "midvatten.tools.wqualreport_compact.common_utils.get_stored_settings",
            return_value={},
        ):
            ui = CompactWqualReportUi(self.iface.mainWindow(), self.midvatten.ms)
        ui.from_sql_table.setChecked(True)
        gui_utils.set_combobox(ui.sql_table, "w_qual_lab", add_if_not_exists=False)
        ui.date_time_as_columns.setChecked(True)
        gui_utils.set_combobox(ui.sort1, "", add_if_not_exists=False)
        gui_utils.set_combobox(ui.sort2, "", add_if_not_exists=False)
        gui_utils.set_combobox(ui.sort3, "", add_if_not_exists=False)
        ui.wqualreport()
        print(f"{mock_messagebar.mock_calls=}")
        mock_messagebar.critical.assert_called()

    @mock.patch(
        "midvatten.tools.wqualreport_compact.qgis.PyQt.QtWidgets.QInputDialog.getText"
    )
    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_update_settings_from_string(self, mock_messagebar, mock_gettext):
        mock_gettext.return_value = (
            "{'num_data_cols': '5', 'rowheader_colwidth_percent': '20', "
            "'from_sql_table': True, 'data_column': 'reading_num'}",
            True,
        )
        with mock.patch(
            "midvatten.tools.wqualreport_compact.common_utils.get_stored_settings",
            return_value={},
        ):
            ui = CompactWqualReportUi(self.iface.mainWindow(), self.midvatten.ms)
        ui.push_button_update_from_string.clicked.emit()
        print(f"{mock_messagebar.mock_calls=}")
        assert ui.num_data_cols.text() == "5"
        assert ui.rowheader_colwidth_percent.text() == "20"

    @mock.patch(
        "midvatten.tools.wqualreport_compact.common_utils.get_stored_settings",
        return_value={},
    )
    def test_save_and_restore_stored_settings(self, mock_get_stored):
        _insert_wqual_test_data("WQ1")
        ui1 = CompactWqualReportUi(self.iface.mainWindow(), self.midvatten.ms)
        ui1.num_data_cols.setText("7")
        ui1.rowheader_colwidth_percent.setText("30")
        ui1.from_sql_table.setChecked(True)
        gui_utils.set_combobox(ui1.sql_table, "w_qual_lab", add_if_not_exists=False)
        gui_utils.set_combobox(ui1.data_column, "reading_num", add_if_not_exists=False)
        ui1.save_stored_settings(ui1.save_attrnames)
        stored = dict(ui1.stored_settings)
        ui2 = CompactWqualReportUi(self.iface.mainWindow(), self.midvatten.ms)
        ui2.update_from_stored_settings(stored)
        assert ui2.num_data_cols.text() == "7"
        assert ui2.rowheader_colwidth_percent.text() == "30"
        assert ui2.data_column.currentText() == "reading_num"

    @mock.patch("midvatten.tools.wqualreport_compact.open_report_in_browser")
    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    @mock.patch("qgis.utils.iface", autospec=True)
    def test_from_active_layer_no_layer_shows_error(
        self, mock_iface, mock_messagebar, mock_openurl
    ):
        mock_iface.activeLayer.return_value = None
        with mock.patch(
            "midvatten.tools.wqualreport_compact.common_utils.get_stored_settings",
            return_value={},
        ):
            ui = CompactWqualReportUi(self.iface.mainWindow(), self.midvatten.ms)
        ui.from_active_layer.blockSignals(True)
        ui.from_active_layer.setChecked(True)
        ui.from_active_layer.blockSignals(False)
        gui_utils.set_combobox(ui.data_column, "reading_txt", add_if_not_exists=False)
        ui.wqualreport()
        print(f"{mock_messagebar.mock_calls=}")
        mock_messagebar.critical.assert_called()
