"""Tests for the unified LoggerImport tool — parser unit tests."""

from __future__ import annotations

import pytest
from unittest import mock
from unittest.mock import MagicMock
from collections import OrderedDict

from midvatten.tools.import_logger import (
    DiverOfficeParser,
    LeveloggerParser,
    HoboParser,
    TzConverter,
    filter_dates_from_filedata,
    LoggerImport,
)
from midvatten.tools.utils import common_utils
from midvatten.tools.utils import db_utils
from midvatten.test import utils_for_tests
from midvatten.test.mocks_for_tests import MockUsingReturnValue


@pytest.mark.active
class TestDiverOfficeParser:
    """Unit tests for DiverOfficeParser.parse — ported from TestParseDiverofficeFile."""

    def test_parse_utf8(self):
        file_content = (
            "[Channel identification]\n"
            "Instrument number;123\n"
            "Location;rb1\n"
            "UTC offset (hh:mm);+01:00\n"
            "[data]\n"
            "Date/time;Water head[cm];Temperature[\u00b0C]\n"
            "2016/03/15 10:30:00;1.0;10.0\n"
            "2016/03/15 11:00:00;2.0;11.0\n"
        )
        with common_utils.tempinput(file_content, "utf-8") as f:
            result = DiverOfficeParser.parse(
                path=f,
                charset="utf-8",
                skip_rows_without_water_level=False,
                begindate=None,
                enddate=None,
            )
        filedata, filename, location, utc_offset = result
        assert location == "rb1"
        assert utc_offset == "+01:00"
        assert filedata[0] == ["date_time", "head_cm", "temp_degc", "cond_mscm"]
        assert filedata[1][0] == "2016-03-15 10:30:00"
        assert filedata[1][1] == "1.0"

    def test_parse_cp1252(self):
        file_content = (
            "[Channel identification]\n"
            "Instrument number;123\n"
            "Location;rb1\n"
            "UTC offset (hh:mm);+01:00\n"
            "[data]\n"
            "Date/time;Water head[cm];Temperature[\xb0C]\n"
            "2016/03/15 10:30:00;1.0;10.0\n"
        )
        with common_utils.tempinput(file_content, "cp1252") as f:
            result = DiverOfficeParser.parse(
                path=f,
                charset="cp1252",
                skip_rows_without_water_level=False,
                begindate=None,
                enddate=None,
            )
        filedata, filename, location, utc_offset = result
        assert location == "rb1"
        assert len(filedata) == 2  # header + 1 data row

    @mock.patch("midvatten.tools.import_logger.common_utils.MessagebarAndLog")
    def test_parse_warning_missing_head_cm(self, mock_messagebar):
        """File with only Temperature column — warns and still returns data."""
        file_content = (
            "[Channel identification]\n"
            "Location;rb1\n"
            "[data]\n"
            "Date/time;Temperature[\xb0C]\n"
            "2016/03/15 10:30:00;10.0\n"
        )
        with common_utils.tempinput(file_content, "utf-8") as f:
            result = DiverOfficeParser.parse(
                path=f,
                charset="utf-8",
                skip_rows_without_water_level=False,
                begindate=None,
                enddate=None,
            )
        filedata, filename, location, utc_offset = result
        assert location == "rb1"
        assert mock_messagebar.warning.called

    @mock.patch("midvatten.tools.import_logger.common_utils.MessagebarAndLog")
    def test_parse_get_timezone(self, mock_messagebar):
        """UTC offset is extracted from file header."""
        file_content = (
            "[Channel identification]\n"
            "Location;rb1\n"
            "UTC offset (hh:mm);+02:00\n"
            "[data]\n"
            "Date/time;Water head[cm]\n"
            "2016/03/15 10:30:00;1.0\n"
        )
        with common_utils.tempinput(file_content, "utf-8") as f:
            result = DiverOfficeParser.parse(
                path=f,
                charset="utf-8",
                skip_rows_without_water_level=False,
                begindate=None,
                enddate=None,
            )
        _, _, _, utc_offset = result
        assert utc_offset == "+02:00"


@pytest.mark.active
class TestFilterDatesFromFiledata:
    """Unit tests for filter_dates_from_filedata module-level function."""

    def test_filter_dates_from_filedata(self):
        file_data = [
            ["date_time", "head_cm", "obsid"],
            ["2016-03-15 10:30:00", "1.0", "rb1"],
            ["2016-03-15 11:00:00", "2.0", "rb1"],
            ["2016-04-15 10:30:00", "3.0", "rb2"],
        ]
        last_dates = {"rb1": "2016-03-15 10:30:00"}
        result = filter_dates_from_filedata(file_data, last_dates)
        obsids = [row[2] for row in result[1:]]
        assert "rb2" in obsids
        rb1_rows = [r for r in result[1:] if r[2] == "rb1"]
        assert len(rb1_rows) == 1
        assert rb1_rows[0][0] == "2016-03-15 11:00:00"


@pytest.mark.active
class TestLeveloggerParser:
    """Unit tests for LeveloggerParser.parse."""

    def test_parse_basic(self):
        file_content = (
            "Serial_number: 123\n"
            "Location: rb1\n"
            "LEVEL\n"
            "UNIT: cm\n"
            "TEMPERATURE\n"
            "Date;Time;ms;LEVEL;TEMPERATURE\n"
            "2016-03-15;10:30:00;0;1;10\n"
            "2016-03-15;11:00:00;0;2;20\n"
        )
        with common_utils.tempinput(file_content, "utf-8") as f:
            result = LeveloggerParser.parse(
                path=f,
                charset="utf-8",
                skip_rows_without_water_level=False,
                begindate=None,
                enddate=None,
            )
        filedata, filename, location, timezone = result
        assert location == "rb1"
        assert timezone is None
        assert filedata[0] == ["date_time", "head_cm", "temp_degc", "cond_mscm"]
        assert filedata[1][0] == "2016-03-15 10:30:00"
        assert float(filedata[1][1]) == pytest.approx(1.0)

    def test_parse_level_as_m(self):
        """Level unit 'm' is converted to cm (*100)."""
        file_content = (
            "Location: rb1\n"
            "LEVEL\n"
            "UNIT: m\n"
            "TEMPERATURE\n"
            "Date;Time;ms;LEVEL;TEMPERATURE\n"
            "2016-03-15;10:30:00;0;0.01;10\n"
        )
        with common_utils.tempinput(file_content, "utf-8") as f:
            result = LeveloggerParser.parse(
                path=f,
                charset="utf-8",
                skip_rows_without_water_level=False,
                begindate=None,
                enddate=None,
            )
        filedata, _, _, _ = result
        assert float(filedata[1][1]) == pytest.approx(1.0)

    def test_returns_4_tuple(self):
        """LeveloggerParser.parse must always return a 4-tuple."""
        file_content = "Date;Time\n"
        with common_utils.tempinput(file_content, "utf-8") as f:
            result = LeveloggerParser.parse(
                path=f,
                charset="utf-8",
                skip_rows_without_water_level=False,
                begindate=None,
                enddate=None,
            )
        assert len(result) == 4
        assert result[0] == []
        assert result[3] is None


@pytest.mark.active
class TestHoboParser:
    """Unit tests for HoboParser.parse."""

    @mock.patch("midvatten.tools.import_logger.common_utils.MessagebarAndLog")
    def test_parse_utf8(self, mock_messagebar):
        file_content = (
            '"Plot Title: temp"\n'
            '"#","Date Time, GMT+01:00","Temp, \u00b0C (LGR S/N: 1234, SEN S/N: 1234, LBL: Rb1)"\n'
            '1,"07/19/18 10:00:00 fm",4.558\n'
            '2,"07/19/18 11:00:00 fm",4.402\n'
        )
        tz_converter = TzConverter()
        with common_utils.tempinput(file_content, "utf-8") as f:
            result = HoboParser.parse(
                path=f,
                charset="utf-8",
                tz_converter=tz_converter,
                begindate=None,
                enddate=None,
            )
        filedata, filename, location, utc_offset = result  # must be 4-tuple
        assert location == "Rb1"
        assert utc_offset is None
        assert filedata[0] == ["date_time", "head_cm", "temp_degc", "cond_mscm"]
        assert filedata[1][0] == "2018-07-19 10:00:00"
        assert float(filedata[1][2]) == pytest.approx(4.558)

    @mock.patch("midvatten.tools.import_logger.common_utils.MessagebarAndLog")
    def test_parse_convert_tz(self, mock_messagebar):
        """Timezone conversion: GMT+03:00 source → GMT+01:00 target shifts time -2h."""
        file_content = (
            '"Plot Title: temp"\n'
            '"#","Date Time, GMT+03:00","Temp, \u00b0C (LGR S/N: 1234, SEN S/N: 1234, LBL: Rb1)"\n'
            '1,"07/19/18 10:00:00 fm",4.558\n'
        )
        tz_converter = TzConverter()
        tz_converter.target_tz = "GMT+1"
        with common_utils.tempinput(file_content, "utf-8") as f:
            result = HoboParser.parse(
                path=f,
                charset="utf-8",
                tz_converter=tz_converter,
                begindate=None,
                enddate=None,
            )
        filedata, _, _, _ = result
        assert filedata[1][0] == "2018-07-19 08:00:00"

    @mock.patch("midvatten.tools.import_logger.common_utils.MessagebarAndLog")
    def test_parse_always_returns_4_tuple(self, mock_messagebar):
        """HoboParser must return a 4-tuple even on parse failure."""
        file_content = '"Plot Title: temp"\n'
        tz_converter = TzConverter()
        with common_utils.tempinput(file_content, "utf-8") as f:
            result = HoboParser.parse(
                path=f,
                charset="utf-8",
                tz_converter=tz_converter,
                begindate=None,
                enddate=None,
            )
        assert len(result) == 4
        assert result[3] is None


@pytest.mark.spatialite
class TestLoggerImportDiverOfficeSpatialite(utils_for_tests.MidvattenTestSpatialiteDbSv):
    """Integration tests for LoggerImport with DiverOffice format."""

    def test_basic_diveroffice_import(self):
        """Three files, three obsids (only rb1 exists) — two are added via NotFoundQuestion."""
        files = [
            "\n".join([
                "Location=rb1",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/03/15 10:30:00,1,10",
                "2016/03/15 11:00:00,11,101",
            ]),
            "\n".join([
                "Location=rb2",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/04/15 10:30:00,2,20",
                "2016/04/15 11:00:00,21,201",
            ]),
            "\n".join([
                "Location=rb3",
                "Date/time,Water head[cm],Temperature[\u00b0C],Conductivity[mS/cm]",
                "2016/05/15 10:30:00,3,30,5",
                "2016/05/15 11:00:00,31,301,6",
            ]),
        ]
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")

        with common_utils.tempinput(files[0], "utf-8") as f1, \
             common_utils.tempinput(files[1], "utf-8") as f2, \
             common_utils.tempinput(files[2], "utf-8") as f3:
            filenames = [f1, f2, f3]

            @mock.patch("midvatten.tools.import_data_to_db.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.import_data_to_db.common_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch("midvatten.tools.import_data_to_db.common_utils.pop_up_info", autospec=True)
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(self, filenames, mock_select_files, mock_popup,
                     mock_iface, mock_askuser, mock_notfound):
                mock_notfound.return_value.answer = "ok"
                mock_notfound.return_value.value = "rb1"
                mock_notfound.return_value.reuse_column = "location"
                mock_select_files.return_value = filenames

                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = LoggerImport(self.iface, ms)
                importer.load_gui()
                importer.format_combo.setCurrentText(LoggerImport.FORMAT_DIVEROFFICE)
                importer.select_files()
                importer.start_import(
                    files=importer.files,
                    skip_rows_without_water_level=importer.skip_rows.checked,
                    confirm_names=importer.confirm_names.checked,
                    import_all_data=importer.import_all_data.checked,
                )

            _run(self, filenames)

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment "
                "FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = (
            r"(True, [(rb1, 2016-03-15 10:30:00, 1.0, 10.0, None, None, None), "
            r"(rb1, 2016-03-15 11:00:00, 11.0, 101.0, None, None, None), "
            r"(rb1, 2016-04-15 10:30:00, 2.0, 20.0, None, None, None), "
            r"(rb1, 2016-04-15 11:00:00, 21.0, 201.0, None, None, None), "
            r"(rb1, 2016-05-15 10:30:00, 3.0, 30.0, 5.0, None, None), "
            r"(rb1, 2016-05-15 11:00:00, 31.0, 301.0, 6.0, None, None)])"
        )
        assert test_string == reference_string

    def test_filter_dates_diveroffice(self):
        """When import_all_data is False, only data newer than last DB date is imported."""
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm) "
            "VALUES ('rb1', '2016-03-15 10:30:00', 1)"
        )
        file_content = "\n".join([
            "Location=rb1",
            "Date/time,Water head[cm],Temperature[\u00b0C]",
            "2016/03/15 10:30:00,1,10",
            "2016/03/15 11:00:00,11,101",
        ])
        with common_utils.tempinput(file_content, "utf-8") as f:
            @mock.patch("midvatten.tools.import_data_to_db.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.import_data_to_db.common_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch("midvatten.tools.import_data_to_db.common_utils.pop_up_info", autospec=True)
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(self, filename, mock_select_files, mock_popup,
                     mock_iface, mock_askuser, mock_notfound):
                mock_notfound.return_value.answer = "ok"
                mock_notfound.return_value.value = "rb1"
                mock_notfound.return_value.reuse_column = "location"
                mock_select_files.return_value = [filename]

                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = LoggerImport(self.iface, ms)
                importer.load_gui()
                importer.format_combo.setCurrentText(LoggerImport.FORMAT_DIVEROFFICE)
                importer.import_all_data.checked = False
                importer.select_files()
                importer.start_import(
                    files=importer.files,
                    skip_rows_without_water_level=importer.skip_rows.checked,
                    confirm_names=importer.confirm_names.checked,
                    import_all_data=importer.import_all_data.checked,
                )

            _run(self, f)

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm FROM w_levels_logger ORDER BY date_time"
            )
        )
        reference_string = (
            r"(True, [(rb1, 2016-03-15 10:30:00, 1.0), "
            r"(rb1, 2016-03-15 11:00:00, 11.0)])"
        )
        assert test_string == reference_string


@pytest.mark.spatialite
class TestLoggerImportLeveloggerSpatialite(utils_for_tests.MidvattenTestSpatialiteDbSv):
    """Integration tests for LoggerImport with Levelogger format."""

    def test_basic_levelogger_import(self):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        file_content = "\n".join([
            "Serial_number: 123",
            "Location: rb1",
            "LEVEL",
            "UNIT: cm",
            "TEMPERATURE",
            "Date;Time;ms;LEVEL;TEMPERATURE",
            "2016-03-15;10:30:00;0;1;10",
            "2016-03-15;11:00:00;0;11;101",
        ])
        with common_utils.tempinput(file_content, "cp1252") as f:
            @mock.patch("midvatten.tools.import_data_to_db.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.import_data_to_db.common_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch("midvatten.tools.import_data_to_db.common_utils.pop_up_info", autospec=True)
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(self, filename, mock_select_files, mock_popup,
                     mock_iface, mock_askuser, mock_notfound):
                mock_notfound.return_value.answer = "ok"
                mock_notfound.return_value.value = "rb1"
                mock_notfound.return_value.reuse_column = "location"
                mock_select_files.return_value = [filename]

                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = LoggerImport(self.iface, ms)
                importer.load_gui()
                importer.format_combo.setCurrentText(LoggerImport.FORMAT_LEVELOGGER)
                importer.select_files()
                importer.start_import(
                    files=importer.files,
                    skip_rows_without_water_level=importer.skip_rows.checked,
                    confirm_names=importer.confirm_names.checked,
                    import_all_data=importer.import_all_data.checked,
                )

            _run(self, f)

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc FROM w_levels_logger ORDER BY date_time"
            )
        )
        reference_string = (
            r"(True, [(rb1, 2016-03-15 10:30:00, 1.0, 10.0), "
            r"(rb1, 2016-03-15 11:00:00, 11.0, 101.0)])"
        )
        assert test_string == reference_string


@pytest.mark.spatialite
class TestLoggerImportHoboSpatialite(utils_for_tests.MidvattenTestSpatialiteDbSv):
    """Integration tests for LoggerImport with HOBO format (also tests the 4-tuple bug fix)."""

    @mock.patch("midvatten.tools.import_logger.common_utils.MessagebarAndLog")
    def test_basic_hobo_import(self, mock_messagebar):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('Rb1')")
        file_content = (
            '"Plot Title: temp"\n'
            '"#","Date Time, GMT+01:00","Temp, \u00b0C (LGR S/N: 1234, SEN S/N: 1234, LBL: Rb1)"\n'
            '1,"07/19/18 10:00:00 fm",4.558\n'
            '2,"07/19/18 11:00:00 fm",4.402\n'
        )
        with common_utils.tempinput(file_content, "utf-8") as f:
            @mock.patch("midvatten.tools.import_data_to_db.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.import_data_to_db.common_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch("midvatten.tools.import_data_to_db.common_utils.pop_up_info", autospec=True)
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(self, filename, mock_select_files, mock_popup,
                     mock_iface, mock_askuser, mock_notfound):
                mock_notfound.return_value.answer = "ok"
                mock_notfound.return_value.value = "Rb1"
                mock_notfound.return_value.reuse_column = "location"
                mock_select_files.return_value = [filename]

                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = LoggerImport(self.iface, ms)
                importer.load_gui()
                importer.format_combo.setCurrentText(LoggerImport.FORMAT_HOBO)
                importer.select_files()
                importer.start_import(
                    files=importer.files,
                    skip_rows_without_water_level=False,
                    confirm_names=importer.confirm_names.checked,
                    import_all_data=importer.import_all_data.checked,
                )

            _run(self, f)

        result = db_utils.sql_load_fr_db(
            "SELECT obsid, date_time, temp_degc FROM w_levels_logger ORDER BY date_time"
        )
        assert result[0] is True
        assert len(result[1]) == 2
        assert result[1][0][0] == "Rb1"
        assert result[1][0][1] == "2018-07-19 10:00:00"
        assert abs(result[1][0][2] - 4.558) < 0.001
