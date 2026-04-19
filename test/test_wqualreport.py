"""Integration tests for Wqualreport — tests the full user-triggered flow."""

import io
import os
from unittest import mock

import pytest
from qgis.core import QgsProject, QgsVectorLayer

from midvatten.test import utils_for_tests
from midvatten.tools.utils import db_utils
from midvatten.tools.wqualreport import Wqualreport
from midvatten.tools.wqualreport_core import report_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_wqual_data(obsid: str = "OBS1") -> None:
    # report PK is (report, parameter); embed obsid to avoid collision across test calls
    db_utils.sql_alter_db(
        f"""INSERT INTO obs_points (obsid, geometry)
            VALUES ('{obsid}', ST_GeomFromText('POINT(0 0)', 3006))"""
    )
    rows = [
        (f"{obsid}_R1", "Iron", "mg/l", "1.5", "2024-01-01 10:00"),
        (f"{obsid}_R1", "Calcium", "mg/l", "120.0", "2024-01-01 10:00"),
        (f"{obsid}_R2", "Iron", "mg/l", "2.0", "2024-06-01 10:00"),
        (f"{obsid}_R2", "Calcium", "mg/l", "130.0", "2024-06-01 10:00"),
    ]
    for report, param, unit, reading_txt, date_time in rows:
        db_utils.sql_alter_db(
            f"""INSERT INTO w_qual_lab
                    (obsid, report, parameter, unit, reading_txt, date_time)
                VALUES
                    ('{obsid}', '{report}', '{param}', '{unit}', '{reading_txt}', '{date_time}')"""
        )


def _make_obs_points_layer() -> QgsVectorLayer:
    dbconnection = db_utils.DbConnectionManager()
    uri = dbconnection.uri
    uri.setDataSource("", "obs_points", "geometry", "", "rowid")
    dbtype = db_utils.get_dbtype(dbconnection.dbtype)
    vlayer = QgsVectorLayer(uri.uri(), "obs_points_test", dbtype)
    QgsProject.instance().addMapLayer(vlayer)
    feature_ids = [f.id() for f in vlayer.getFeatures()]
    vlayer.selectByIds(feature_ids)
    dbconnection.closedb()
    return vlayer


def _default_settingsdict() -> dict:
    return {
        "wqualtable": "w_qual_lab",
        "wqual_paramcolumn": "parameter",
        "wqual_valuecolumn": "reading_txt",
        "wqual_date_time_format": "YYYY-MM-DD",
        "wqual_unitcolumn": "unit",
        "wqual_sortingcolumn": "",
        "database": "",
    }


# ---------------------------------------------------------------------------
# Integration test — full user flow
# ---------------------------------------------------------------------------


@pytest.mark.spatialite
class TestWqualreportSpatialite(utils_for_tests.MidvattenTestSpatialiteDbSv):
    @mock.patch("midvatten.tools.wqualreport.open_report_in_browser")
    @mock.patch("midvatten.tools.wqualreport.common_utils.start_waiting_cursor")
    @mock.patch("midvatten.tools.wqualreport.common_utils.stop_waiting_cursor")
    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_show_generates_html_with_selected_obsid(
        self, mock_messagebar, mock_stop, mock_start, mock_openurl
    ):
        """show() with a selected obs_point generates an HTML file with
        parameter names and values for that obsid."""
        _insert_wqual_data("OBS1")
        layer = _make_obs_points_layer()

        mock_iface = mock.MagicMock()
        mock_iface.activeLayer.return_value = layer
        self.midvatten.ms.settingsdict.update(_default_settingsdict())

        report = Wqualreport(mock_iface, self.midvatten.ms)
        report.show()

        print(f"{mock_messagebar.mock_calls=}")

        reportpath = report_path()
        assert os.path.isfile(reportpath), "HTML report was not created"
        with open(reportpath, encoding="utf-8") as f:
            html = f.read()

        assert "OBS1" in html
        assert "Iron" in html
        assert "Calcium" in html
        assert "mg/l" in html
        assert mock_openurl.called

    @mock.patch("midvatten.tools.wqualreport.open_report_in_browser")
    @mock.patch("midvatten.tools.wqualreport.common_utils.start_waiting_cursor")
    @mock.patch("midvatten.tools.wqualreport.common_utils.stop_waiting_cursor")
    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_show_two_obsids_both_appear_in_report(
        self, mock_messagebar, mock_stop, mock_start, mock_openurl
    ):
        """When two obs_points are selected, both appear in the HTML report."""
        _insert_wqual_data("OBS1")
        _insert_wqual_data("OBS2")
        layer = _make_obs_points_layer()

        mock_iface = mock.MagicMock()
        mock_iface.activeLayer.return_value = layer
        self.midvatten.ms.settingsdict.update(_default_settingsdict())

        report = Wqualreport(mock_iface, self.midvatten.ms)
        report.show()

        print(f"{mock_messagebar.mock_calls=}")

        reportpath = report_path()
        assert os.path.isfile(reportpath)
        with open(reportpath, encoding="utf-8") as f:
            html = f.read()

        assert "OBS1" in html
        assert "OBS2" in html

    # -----------------------------------------------------------------------
    # Secondary: helper-method tests to cover branches not reachable via show()
    # -----------------------------------------------------------------------

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_get_data_returns_correct_shape(self, mock_messagebar):
        """get_data() returns a list with nr_header_rows + n_params rows."""
        _insert_wqual_data("OBS1")

        mock_iface = mock.MagicMock()
        report = Wqualreport(mock_iface, self.midvatten.ms)
        report.settingsdict = _default_settingsdict()

        dbconn = db_utils.DbConnectionManager()
        try:
            table = report.get_data(obsid="OBS1", dbconnection=dbconn)
        finally:
            dbconn.closedb()

        print(f"{mock_messagebar.mock_calls=}")
        assert table is not False
        assert len(table) == 4  # 2 headers + 2 params
        assert len(table[0]) == 3  # label + 2 date columns
        assert table[0][0] == "obsid"
        assert table[1][0] == "date_time"
        assert table[0][1] == "OBS1"

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_get_data_no_parameters_returns_false(self, mock_messagebar):
        """get_data() returns False when obsid has no rows in w_qual_lab."""
        db_utils.sql_alter_db(
            "INSERT INTO obs_points (obsid, geometry)"
            " VALUES ('EMPTY', ST_GeomFromText('POINT(0 0)', 3006))"
        )
        mock_iface = mock.MagicMock()
        report = Wqualreport(mock_iface, self.midvatten.ms)
        report.settingsdict = _default_settingsdict()

        dbconn = db_utils.DbConnectionManager()
        try:
            result = report.get_data(obsid="EMPTY", dbconnection=dbconn)
        finally:
            dbconn.closedb()

        print(f"{mock_messagebar.mock_calls=}")
        assert result is False

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_get_data_with_sorting_column_has_three_header_rows(self, mock_messagebar):
        """When wqual_sortingcolumn is set, nr_header_rows == 3."""
        _insert_wqual_data("OBS1")

        mock_iface = mock.MagicMock()
        report = Wqualreport(mock_iface, self.midvatten.ms)
        report.settingsdict = {
            **_default_settingsdict(),
            "wqual_sortingcolumn": "report",
        }

        dbconn = db_utils.DbConnectionManager()
        try:
            table = report.get_data(obsid="OBS1", dbconnection=dbconn)
        finally:
            dbconn.closedb()

        print(f"{mock_messagebar.mock_calls=}")
        assert table is not False
        assert table[2][0] == "report"  # third header row label
        assert len(table) == 5  # 3 headers + 2 params

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_write_html_report_uses_th_for_headers_td_for_data(self, mock_messagebar):
        """write_html_report() uses <th> for header rows and <td> for data rows."""
        _insert_wqual_data("OBS1")

        mock_iface = mock.MagicMock()
        report = Wqualreport(mock_iface, self.midvatten.ms)
        report.settingsdict = _default_settingsdict()

        dbconn = db_utils.DbConnectionManager()
        try:
            table = report.get_data(obsid="OBS1", dbconnection=dbconn)
        finally:
            dbconn.closedb()

        buf = io.StringIO()
        report.write_html_report(table, buf)
        html = buf.getvalue()

        print(f"{mock_messagebar.mock_calls=}")
        assert "<th>" in html
        assert "<td>" in html
        assert "Iron" in html
        assert "Calcium" in html
