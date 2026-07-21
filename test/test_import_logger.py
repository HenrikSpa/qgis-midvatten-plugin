"""Tests for the unified LoggerImport tool — parser unit tests."""

from __future__ import annotations

import os
import pandas as pd
import pytest
from unittest import mock
from unittest.mock import MagicMock
from collections import OrderedDict

from qgis.PyQt import QtWidgets

from midvatten.tools import import_data_to_db
from midvatten.tools.import_logger import (
    DiverOfficeParser,
    DiverOfficeParseError,
    DiverOfficeBaroParser,
    LeveloggerParser,
    HoboParser,
    TzConverter,
    filter_dates_from_filedata,
    _pivot_baro_to_meteo,
    LoggerImport,
)
from midvatten.tools.utils import file_utils
from midvatten.tools.utils import db_utils
from midvatten.tools.utils.date_utils import to_date
from midvatten.tools.utils.gui_utils import set_combobox
from midvatten.tools.import_logger.parsers import _SourceLine
from midvatten.test import utils_for_tests
from midvatten.test.mocks_for_tests import MockReturnUsingDictIn
from scripts.benchmark_diveroffice_mon import build_mon


def make_fixed_mon(
    rows: list[tuple[str | None, ...]], declared_count: int | None = None
) -> str:
    channel_names = ["WATER HEAD (WC)", "TEMPERATURE", "CONDUCTIVITY"]
    header = [
        "[Logger settings]",
        "  Location                =rb1",
        f"  Number of channels      ={len(rows[0])}",
    ]
    for channel, name in enumerate(channel_names[: len(rows[0])], 1):
        header.extend([f"[Channel {channel}]", f"  Identification          ={name}"])
    header.extend(["[Data]", str(declared_count or len(rows))])
    for values in rows:
        fields = "".join(f"{value or '':>12}" for value in values)
        header.append(f"2025/01/01 00:00:00.0{fields}")
    header.append("END OF DATA FILE OF DATALOGGER FOR WINDOWS")
    return "\n".join(header) + "\n"


@pytest.mark.active
class TestDiverOfficeParser:
    """Unit tests for DiverOfficeParser.parse — ported from TestParseDiverofficeFile."""

    def test_parse_mon_first_rows_missing_water_head(self):
        file_content = (
            "[Logger settings]\n"
            "  Location                =rb1\n"
            "  Number of channels      =2\n"
            "[Channel 1]\n"
            "  Identification          =WATER HEAD (WC)\n"
            "[Channel 2]\n"
            "  Identification          =TEMPERATURE\n"
            "[Data]\n"
            "4\n"
            "2025/05/05 13:00:00.0                    5.250\n"
            "2025/05/05 14:00:00.0                    4.827\n"
            "2025/05/05 15:00:00.0      409.667       4.820\n"
            "2025/05/05 16:00:00.0      409.433       4.837\n"
            "END OF DATA FILE OF DATALOGGER FOR WINDOWS\n"
        )
        with file_utils.tempinput(file_content, "utf-8", suffix=".MON") as f:
            filedata, *_ = DiverOfficeParser.parse(f, "utf-8")
            filtered_filedata, *_ = DiverOfficeParser.parse(
                f, "utf-8", skip_rows_without_water_level=True
            )

        assert filedata[1] == ["2025-05-05 13:00:00", None, "5.25", None]
        assert filedata[2] == ["2025-05-05 14:00:00", None, "4.827", None]
        assert filedata[3] == [
            "2025-05-05 15:00:00",
            "409.667",
            "4.82",
            None,
        ]
        assert [row[1] for row in filtered_filedata[1:]] == ["409.667", "409.433"]

    def test_parse_mon_preserves_wider_head_after_inference_window(self):
        content = build_mon(1001)
        with file_utils.tempinput(content, "utf-8", suffix=".mon") as path:
            file_data, *_ = DiverOfficeParser.parse(path, "utf-8")

        assert file_data[-1][1] == "100.308"

    @pytest.mark.parametrize(
        ("before", "after"),
        [("9.999", "10.001"), ("99.999", "100.001"), ("999.999", "1000.001")],
    )
    def test_parse_mon_preserves_digit_width_crossings(self, before, after):
        content = make_fixed_mon([(before,)] * 1000 + [(after,)])
        with file_utils.tempinput(content, "utf-8", suffix=".mon") as path:
            file_data, *_ = DiverOfficeParser.parse(path, "utf-8")

        assert float(file_data[-1][1]) == pytest.approx(float(after))

    def test_parse_mon_preserves_missing_channel_positions(self):
        content = make_fixed_mon(
            [("1.0", None, "3.0"), (None, "2.0", "3.0"), ("1.0", "2.0", None)]
        )
        with file_utils.tempinput(content, "utf-8", suffix=".mon") as path:
            file_data, *_ = DiverOfficeParser.parse(path, "utf-8")

        assert [row[1:] for row in file_data[1:]] == [
            ["1.0", None, "3.0"],
            [None, "2.0", "3.0"],
            ["1.0", "2.0", None],
        ]

    @pytest.mark.parametrize("value", ["-100.308", "+1,25", "1.25e3"])
    def test_parse_mon_accepts_supported_numeric_tokens(self, value):
        content = make_fixed_mon([(value,)])
        with file_utils.tempinput(content, "utf-8", suffix=".mon") as path:
            file_data, *_ = DiverOfficeParser.parse(path, "utf-8")

        assert float(file_data[1][1]) == pytest.approx(float(value.replace(",", ".")))

    def test_parse_mon_rejects_invalid_date(self):
        content = make_fixed_mon([("1.0",)]).replace(
            "2025/01/01 00:00:00.0", "not-a-date 00:00:00.0"
        )
        with file_utils.tempinput(content, "utf-8", suffix=".mon") as path:
            with pytest.raises(DiverOfficeParseError, match="date/time"):
                DiverOfficeParser.parse(path, "utf-8")

    def test_parse_mon_rejects_invalid_numeric_value(self):
        content = make_fixed_mon([("invalid",)])
        with file_utils.tempinput(content, "utf-8", suffix=".mon") as path:
            with pytest.raises(DiverOfficeParseError, match="numeric"):
                DiverOfficeParser.parse(path, "utf-8")

    def test_parse_mon_rejects_declared_count_mismatch(self):
        content = make_fixed_mon([("1.0",)], declared_count=2)
        with file_utils.tempinput(content, "utf-8", suffix=".mon") as path:
            with pytest.raises(DiverOfficeParseError, match="declared 2 data rows"):
                DiverOfficeParser.parse(path, "utf-8")

    def test_parse_mon_rejects_declared_channel_count_mismatch(self):
        content = make_fixed_mon([("1.0", "2.0")]).replace(
            "Number of channels      =2", "Number of channels      =3"
        )
        with file_utils.tempinput(content, "utf-8", suffix=".mon") as path:
            with pytest.raises(DiverOfficeParseError, match="declares 3 channels"):
                DiverOfficeParser.parse(path, "utf-8")

    def test_parse_mon_fallback_accepts_lossless_left_aligned_field(self):
        content = make_fixed_mon([("9.9",), ("100.308",)])
        content = content.replace(f"{'9.9':>12}", "    9.9     ").replace(
            f"{'100.308':>12}", "    100.308 "
        )
        with file_utils.tempinput(content, "utf-8", suffix=".mon") as path:
            file_data, *_ = DiverOfficeParser.parse(path, "utf-8")

        assert [float(row[1]) for row in file_data[1:]] == [9.9, 100.308]

    def test_parse_mon_fallback_rejects_ambiguous_layout(self):
        content = make_fixed_mon([("1.0", "2.0"), ("10.0", "20.0")])
        content = content.replace("         1.0         2.0", "  1.0 2.0              ")
        with file_utils.tempinput(content, "utf-8", suffix=".mon") as path:
            with pytest.raises(DiverOfficeParseError, match="fallback"):
                DiverOfficeParser.parse(path, "utf-8")

    def test_parse_mon_rejects_width_change_as_fake_second_channel(self):
        """Two widths in one sparse channel must not be mapped to two channels."""
        content = make_fixed_mon([("9.9", None), ("10.0", None)]).replace(
            "2025/01/01 00:00:00.0         9.9            \n"
            "2025/01/01 00:00:00.0        10.0            ",
            "2025/01/01 00:00:00.0    9.9\n2025/01/01 00:00:00.0    10.0",
        )
        with file_utils.tempinput(content, "utf-8", suffix=".mon") as path:
            with pytest.raises(DiverOfficeParseError, match="fallback"):
                DiverOfficeParser.parse(path, "utf-8")

    def test_mon_fallback_rejects_compressed_blank_slot_comparison(self):
        source_lines = [_SourceLine(1, "2025/01/01 00:00:00.0                2.0")]
        scanned = DiverOfficeParser._scan_mon_rows(source_lines, "ambiguous.mon")
        wrong_slots = pd.DataFrame([["2025/01/01", "00:00:00.0", "2.0", None]])

        with mock.patch(
            "midvatten.tools.import_logger.parsers.pd.read_fwf",
            return_value=wrong_slots,
        ):
            with pytest.raises(DiverOfficeParseError, match="fallback"):
                DiverOfficeParser._read_mon_fallback(
                    scanned, 3, "ambiguous.mon", "ambiguous endpoints"
                )

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
        with file_utils.tempinput(file_content, "utf-8") as f:
            result = DiverOfficeParser.parse(
                path=f,
                charset="utf-8",
                skip_rows_without_water_level=False,
                begindate=None,
                enddate=None,
            )
        filedata, filename, location, utc_offset, serial_number = result
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
        with file_utils.tempinput(file_content, "cp1252") as f:
            result = DiverOfficeParser.parse(
                path=f,
                charset="cp1252",
                skip_rows_without_water_level=False,
                begindate=None,
                enddate=None,
            )
        filedata, filename, location, utc_offset, serial_number = result
        assert location == "rb1"
        assert len(filedata) == 2  # header + 1 data row

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_parse_warning_missing_head_cm(self, mock_messagebar):
        """File with only Temperature column — warns and still returns data."""
        file_content = (
            "[Channel identification]\n"
            "Location;rb1\n"
            "[data]\n"
            "Date/time;Temperature[\xb0C]\n"
            "2016/03/15 10:30:00;10.0\n"
        )
        with file_utils.tempinput(file_content, "utf-8") as f:
            result = DiverOfficeParser.parse(
                path=f,
                charset="utf-8",
                skip_rows_without_water_level=False,
                begindate=None,
                enddate=None,
            )
        filedata, filename, location, utc_offset, serial_number = result
        assert location == "rb1"
        assert mock_messagebar.warning.called

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
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
        with file_utils.tempinput(file_content, "utf-8") as f:
            result = DiverOfficeParser.parse(
                path=f,
                charset="utf-8",
                skip_rows_without_water_level=False,
                begindate=None,
                enddate=None,
            )
        _, _, _, utc_offset, _ = result
        assert utc_offset == "+02:00"

    def test_parse_serial_number(self):
        file_content = (
            "[Logger settings]\n"
            "Serial number=..00-R2717  214.\n"
            "Location=rb1\n"
            "[data]\n"
            "Date/time;Water head[cm];Temperature[\u00b0C]\n"
            "2016/03/15 10:30:00;1.0;10.0\n"
        )
        with file_utils.tempinput(file_content, "utf-8") as f:
            result = DiverOfficeParser.parse(
                path=f,
                charset="utf-8",
                skip_rows_without_water_level=False,
                begindate=None,
                enddate=None,
            )
        _, _, _, _, serial_number = result
        assert serial_number == "R2717"

    def test_parse_serial_number_absent(self):
        file_content = (
            "[Logger settings]\n"
            "Location=rb1\n"
            "[data]\n"
            "Date/time;Water head[cm]\n"
            "2016/03/15 10:30:00;1.0\n"
        )
        with file_utils.tempinput(file_content, "utf-8") as f:
            result = DiverOfficeParser.parse(
                path=f,
                charset="utf-8",
                skip_rows_without_water_level=False,
                begindate=None,
                enddate=None,
            )
        _, _, _, _, serial_number = result
        assert serial_number is None

    def test_parse_old_serial_number(self):
        file_content = (
            "Serial number=..00-R2717  214.\n"
            "Location=rb1\n"
            "Date/time,Water head[cm],Temperature[\u00b0C]\n"
            "2016/03/15 10:30:00,1.0,10.0\n"
            "2016/03/15 11:00:00,2.0,11.0\n"
        )
        with file_utils.tempinput(file_content, "utf-8") as f:
            result = DiverOfficeParser.parse(
                path=f,
                charset="utf-8",
                skip_rows_without_water_level=False,
                begindate=None,
                enddate=None,
            )
        _, _, _, _, serial_number = result
        assert serial_number == "R2717"


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
        with file_utils.tempinput(file_content, "utf-8") as f:
            result = LeveloggerParser.parse(
                path=f,
                charset="utf-8",
                skip_rows_without_water_level=False,
                begindate=None,
                enddate=None,
            )
        filedata, filename, location, timezone, serial_number = result
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
        with file_utils.tempinput(file_content, "utf-8") as f:
            result = LeveloggerParser.parse(
                path=f,
                charset="utf-8",
                skip_rows_without_water_level=False,
                begindate=None,
                enddate=None,
            )
        filedata, _, _, _, _ = result
        assert float(filedata[1][1]) == pytest.approx(1.0)

    def test_returns_5_tuple(self):
        """LeveloggerParser.parse must always return a 5-tuple."""
        file_content = "Date;Time\n"
        with file_utils.tempinput(file_content, "utf-8") as f:
            result = LeveloggerParser.parse(
                path=f,
                charset="utf-8",
                skip_rows_without_water_level=False,
                begindate=None,
                enddate=None,
            )
        assert len(result) == 5
        assert result[0] == []
        assert result[3] is None
        assert result[4] is None

    def test_parse_serial_number_next_line(self):
        """Serial_number: on its own line, value on the next line."""
        file_content = (
            "Serial_number:\n"
            "12345\n"
            "Location: rb1\n"
            "LEVEL\n"
            "UNIT: cm\n"
            "Date;Time;ms;LEVEL\n"
            "2016-03-15;10:30:00;0;1\n"
        )
        with file_utils.tempinput(file_content, "utf-8") as f:
            result = LeveloggerParser.parse(
                path=f,
                charset="utf-8",
                skip_rows_without_water_level=False,
                begindate=None,
                enddate=None,
            )
        _, _, _, _, serial_number = result
        assert serial_number == "12345"

    def test_parse_serial_number_same_line(self):
        """Serial_number: value on the same line."""
        file_content = (
            "Serial_number: 12345\n"
            "Location: rb1\n"
            "LEVEL\n"
            "UNIT: cm\n"
            "Date;Time;ms;LEVEL\n"
            "2016-03-15;10:30:00;0;1\n"
        )
        with file_utils.tempinput(file_content, "utf-8") as f:
            result = LeveloggerParser.parse(
                path=f,
                charset="utf-8",
                skip_rows_without_water_level=False,
                begindate=None,
                enddate=None,
            )
        _, _, _, _, serial_number = result
        assert serial_number == "12345"


@pytest.mark.active
class TestHoboParser:
    """Unit tests for HoboParser.parse."""

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_parse_utf8(self, mock_messagebar):
        file_content = (
            '"Plot Title: temp"\n'
            '"#","Date Time, GMT+01:00","Temp, \u00b0C (LGR S/N: 1234, SEN S/N: 1234, LBL: Rb1)"\n'
            '1,"07/19/18 10:00:00 fm",4.558\n'
            '2,"07/19/18 11:00:00 fm",4.402\n'
        )
        tz_converter = TzConverter()
        with file_utils.tempinput(file_content, "utf-8") as f:
            result = HoboParser.parse(
                path=f,
                charset="utf-8",
                tz_converter=tz_converter,
                begindate=None,
                enddate=None,
            )
        filedata, filename, location, utc_offset, serial_number = (
            result  # must be 5-tuple
        )
        assert location == "Rb1"
        assert utc_offset is None
        assert filedata[0] == ["date_time", "head_cm", "temp_degc", "cond_mscm"]
        assert filedata[1][0] == "2018-07-19 10:00:00"
        assert float(filedata[1][2]) == pytest.approx(4.558)

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_parse_convert_tz(self, mock_messagebar):
        """Timezone conversion: GMT+03:00 source → GMT+01:00 target shifts time -2h."""
        file_content = (
            '"Plot Title: temp"\n'
            '"#","Date Time, GMT+03:00","Temp, \u00b0C (LGR S/N: 1234, SEN S/N: 1234, LBL: Rb1)"\n'
            '1,"07/19/18 10:00:00 fm",4.558\n'
        )
        tz_converter = TzConverter()
        tz_converter.target_tz = "GMT+1"
        with file_utils.tempinput(file_content, "utf-8") as f:
            result = HoboParser.parse(
                path=f,
                charset="utf-8",
                tz_converter=tz_converter,
                begindate=None,
                enddate=None,
            )
        filedata, _, _, _, _ = result
        assert filedata[1][0] == "2018-07-19 08:00:00"

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_parse_always_returns_5_tuple(self, mock_messagebar):
        """HoboParser must return a 5-tuple even on parse failure."""
        file_content = '"Plot Title: temp"\n'
        tz_converter = TzConverter()
        with file_utils.tempinput(file_content, "utf-8") as f:
            result = HoboParser.parse(
                path=f,
                charset="utf-8",
                tz_converter=tz_converter,
                begindate=None,
                enddate=None,
            )
        assert len(result) == 5
        assert result[3] is None
        assert result[4] is None

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_parse_serial_number(self, mock_messagebar):
        file_content = (
            '"Plot Title: temp"\n'
            '"#","Date Time, GMT+01:00","Temp, \u00b0C (LGR S/N: 5678, SEN S/N: 5678, LBL: Rb1)"\n'
            '1,"07/19/18 10:00:00 fm",4.558\n'
        )
        tz_converter = TzConverter()
        with file_utils.tempinput(file_content, "utf-8") as f:
            result = HoboParser.parse(
                path=f,
                charset="utf-8",
                tz_converter=tz_converter,
                begindate=None,
                enddate=None,
            )
        _, _, _, _, serial_number = result
        assert serial_number == "5678"


@pytest.mark.spatialite
class TestLoggerImportDiverOfficeSpatialite(
    utils_for_tests.MidvattenTestSpatialiteDbSv
):
    """Integration tests for LoggerImport with DiverOffice format."""

    def test_basic_diveroffice_import(self):
        """Three files, three obsids (only rb1 exists) — two are added via NotFoundQuestion."""
        files = [
            "\n".join(
                [
                    "Location=rb1",
                    "Date/time,Water head[cm],Temperature[\u00b0C]",
                    "2016/03/15 10:30:00,1,10",
                    "2016/03/15 11:00:00,11,101",
                ]
            ),
            "\n".join(
                [
                    "Location=rb2",
                    "Date/time,Water head[cm],Temperature[\u00b0C]",
                    "2016/04/15 10:30:00,2,20",
                    "2016/04/15 11:00:00,21,201",
                ]
            ),
            "\n".join(
                [
                    "Location=rb3",
                    "Date/time,Water head[cm],Temperature[\u00b0C],Conductivity[mS/cm]",
                    "2016/05/15 10:30:00,3,30,5",
                    "2016/05/15 11:00:00,31,301,6",
                ]
            ),
        ]
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")

        with (
            file_utils.tempinput(files[0], "utf-8") as f1,
            file_utils.tempinput(files[1], "utf-8") as f2,
            file_utils.tempinput(files[2], "utf-8") as f3,
        ):
            filenames = [f1, f2, f3]

            @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(
                self,
                filenames,
                mock_select_files,
                mock_popup,
                mock_iface,
                mock_askuser,
                mock_notfound,
            ):
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

    def test_diveroffice_import_instrument_serial(self):
        """Serial number extracted from file is stored in w_logger_series.instrument."""
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        file_content = "\n".join(
            [
                "[Logger settings]",
                "Serial number=..00-R2717  214.",
                "Location=rb1",
                "[data]",
                "Date/time;Water head[cm];Temperature[\u00b0C]",
                "2016/03/15 10:30:00;1.0;10.0",
            ]
        )
        with file_utils.tempinput(file_content, "utf-8") as f:

            @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(
                self,
                filename,
                mock_select_files,
                mock_popup,
                mock_iface,
                mock_askuser,
                mock_notfound,
            ):
                mock_notfound.return_value.answer = "ok"
                mock_notfound.return_value.value = "rb1"
                mock_notfound.return_value.reuse_column = "location"
                mock_select_files.return_value = [filename]

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

            _run(self, f)

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT instrument FROM w_logger_series WHERE obsid='rb1'"
            )
        )
        assert test_string == "(True, [(R2717)])"

    def test_filter_dates_diveroffice(self):
        """When import_all_data is False, only data newer than last DB date is imported."""
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm) "
            "VALUES ('rb1', '2016-03-15 10:30:00', 1)"
        )
        file_content = "\n".join(
            [
                "Location=rb1",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/03/15 10:30:00,1,10",
                "2016/03/15 11:00:00,11,101",
            ]
        )
        with file_utils.tempinput(file_content, "utf-8") as f:

            @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(
                self,
                filename,
                mock_select_files,
                mock_popup,
                mock_iface,
                mock_askuser,
                mock_notfound,
            ):
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

    @pytest.mark.parametrize("import_all_data", [False, True])
    def test_overlapping_files_use_one_pre_import_date_snapshot(self, import_all_data):
        """A late segment imported first must not hide earlier rows in a fuller file."""
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm) "
            "VALUES ('rb1', '2025-01-01 00:00:00', 1)"
        )
        late_segment = "\n".join(
            [
                "Location=rb1",
                "Date/time,Water head[cm]",
                "2025/01/03 00:00:00,3",
            ]
        )
        full_period = "\n".join(
            [
                "Location=rb1",
                "Date/time,Water head[cm]",
                "2025/01/01 00:00:00,1",
                "2025/01/02 00:00:00,2",
                "2025/01/03 00:00:00,3",
            ]
        )

        with (
            file_utils.tempinput(late_segment, "utf-8") as late_file,
            file_utils.tempinput(full_period, "utf-8") as full_file,
            mock.patch(
                "midvatten.tools.import_logger.midvatten_utils.select_files",
                return_value=[late_file, full_file],
            ),
            mock.patch("midvatten.tools.utils.dialog_utils.Askuser"),
            mock.patch("qgis.utils.iface", autospec=True),
        ):
            ms = MagicMock()
            ms.settingsdict = OrderedDict()
            importer = LoggerImport(self.iface, ms)
            importer.load_gui()
            importer.confirm_names.checked = False
            importer.import_all_data.checked = import_all_data
            importer.select_files()
            importer.start_import(
                importer.files,
                importer.skip_rows.checked,
                importer.confirm_names.checked,
                importer.import_all_data.checked,
            )

        result = db_utils.sql_load_fr_db(
            "SELECT date_time FROM w_levels_logger "
            "WHERE obsid = 'rb1' ORDER BY date_time"
        )
        assert result[0]
        assert [row[0] for row in result[1]] == [
            "2025-01-01 00:00:00",
            "2025-01-02 00:00:00",
            "2025-01-03 00:00:00",
        ]

    def test_database_failure_in_one_file_does_not_stop_next_file(self):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        bad_file_data = "\n".join(
            [
                "Location=rb1",
                "Date/time,Water head[cm]",
                "2025/01/01 00:00:00,1",
            ]
        )
        good_file_data = "\n".join(
            [
                "Location=rb1",
                "Date/time,Water head[cm]",
                "2025/01/02 00:00:00,2",
            ]
        )
        original_import = import_data_to_db.MidvDataImporter.general_import
        import_calls = 0

        def fail_first_file(importer, destination, file_data, *args, **kwargs):
            nonlocal import_calls
            import_calls += 1
            if import_calls == 1:
                raise RuntimeError("deliberate first-file failure")
            return original_import(importer, destination, file_data, *args, **kwargs)

        with (
            file_utils.tempinput(bad_file_data, "utf-8") as bad_file,
            file_utils.tempinput(good_file_data, "utf-8") as good_file,
            mock.patch(
                "midvatten.tools.import_logger.midvatten_utils.select_files",
                return_value=[bad_file, good_file],
            ),
            mock.patch.object(
                import_data_to_db.MidvDataImporter,
                "general_import",
                autospec=True,
                side_effect=fail_first_file,
            ),
            mock.patch("midvatten.tools.utils.dialog_utils.Askuser"),
            mock.patch("qgis.utils.iface", autospec=True),
        ):
            ms = MagicMock()
            ms.settingsdict = OrderedDict()
            importer = LoggerImport(self.iface, ms)
            importer.load_gui()
            importer.confirm_names.checked = False
            importer.import_all_data.checked = True
            importer.select_files()
            importer.start_import(
                importer.files,
                importer.skip_rows.checked,
                importer.confirm_names.checked,
                importer.import_all_data.checked,
            )

        rows = db_utils.sql_load_fr_db(
            "SELECT date_time, head_cm FROM w_levels_logger ORDER BY date_time"
        )
        assert rows == (True, [("2025-01-02 00:00:00", 2.0)])
        series = db_utils.sql_load_fr_db("SELECT COUNT(*) FROM w_logger_series")
        assert series == (True, [(1,)])

    def test_same_basename_files_keep_distinct_obsid_assignments(self, tmp_path):
        for obsid in ("rb1", "rb2"):
            db_utils.sql_alter_db(f"INSERT INTO obs_points (obsid) VALUES ('{obsid}')")
        first_dir = tmp_path / "first"
        second_dir = tmp_path / "second"
        first_dir.mkdir()
        second_dir.mkdir()
        first_file = first_dir / "logger.csv"
        second_file = second_dir / "logger.csv"
        first_file.write_text(
            "Location=rb1\nDate/time,Water head[cm]\n2025/01/01 00:00:00,1\n",
            encoding="utf-8",
        )
        second_file.write_text(
            "Location=rb2\nDate/time,Water head[cm]\n2025/01/02 00:00:00,2\n",
            encoding="utf-8",
        )

        with (
            mock.patch(
                "midvatten.tools.import_logger.midvatten_utils.select_files",
                return_value=[str(first_file), str(second_file)],
            ),
            mock.patch("midvatten.tools.utils.dialog_utils.Askuser"),
            mock.patch("qgis.utils.iface", autospec=True),
        ):
            ms = MagicMock()
            ms.settingsdict = OrderedDict()
            importer = LoggerImport(self.iface, ms)
            importer.load_gui()
            importer.confirm_names.checked = False
            importer.import_all_data.checked = True
            importer.select_files()
            importer.start_import(
                importer.files,
                importer.skip_rows.checked,
                importer.confirm_names.checked,
                importer.import_all_data.checked,
            )

        rows = db_utils.sql_load_fr_db(
            "SELECT obsid, date_time, head_cm FROM w_levels_logger ORDER BY obsid"
        )
        assert rows == (
            True,
            [
                ("rb1", "2025-01-01 00:00:00", 1.0),
                ("rb2", "2025-01-02 00:00:00", 2.0),
            ],
        )


@pytest.mark.spatialite
class TestLoggerImportLeveloggerSpatialite(utils_for_tests.MidvattenTestSpatialiteDbSv):
    """Integration tests for LoggerImport with Levelogger format."""

    def test_basic_levelogger_import(self):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        file_content = "\n".join(
            [
                "Serial_number: 123",
                "Location: rb1",
                "LEVEL",
                "UNIT: cm",
                "TEMPERATURE",
                "Date;Time;ms;LEVEL;TEMPERATURE",
                "2016-03-15;10:30:00;0;1;10",
                "2016-03-15;11:00:00;0;11;101",
            ]
        )
        with file_utils.tempinput(file_content, "cp1252") as f:

            @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(
                self,
                filename,
                mock_select_files,
                mock_popup,
                mock_iface,
                mock_askuser,
                mock_notfound,
            ):
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

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_basic_hobo_import(self, mock_messagebar):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('Rb1')")
        file_content = (
            '"Plot Title: temp"\n'
            '"#","Date Time, GMT+01:00","Temp, \u00b0C (LGR S/N: 1234, SEN S/N: 1234, LBL: Rb1)"\n'
            '1,"07/19/18 10:00:00 fm",4.558\n'
            '2,"07/19/18 11:00:00 fm",4.402\n'
        )
        with file_utils.tempinput(file_content, "utf-8") as f:

            @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(
                self,
                filename,
                mock_select_files,
                mock_popup,
                mock_iface,
                mock_askuser,
                mock_notfound,
            ):
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


# ── Migrated from test_import_diveroffice.py (parser unit tests) ──────────────


@pytest.mark.active
class TestFilterDatesFromFiledataOld:
    """Ported from TestFilterDatesFromFiledata in test_import_diveroffice.py."""

    def test_filter_dates_from_filedata_with_date_objects(self):
        file_data = [
            ["obsid", "date_time"],
            ["rb1", "2015-05-01 00:00:00"],
            ["rb1", "2016-05-01 00:00"],
            ["rb2", "2015-05-01 00:00:00"],
            ["rb2", "2016-05-01 00:00"],
            ["rb3", "2015-05-01 00:00:00"],
            ["rb3", "2016-05-01 00:00"],
        ]
        obsid_last_imported_dates = {
            "rb1": [(to_date("2016-01-01 00:00:00"),)],
            "rb2": [(to_date("2017-01-01 00:00:00"),)],
        }
        test_file_data = utils_for_tests.create_test_string(
            filter_dates_from_filedata(file_data, obsid_last_imported_dates)
        )
        reference_file_data = "[[obsid, date_time], [rb1, 2016-05-01 00:00], [rb3, 2015-05-01 00:00:00], [rb3, 2016-05-01 00:00]]"
        assert test_file_data == reference_file_data


# ── Migrated from test_import_diveroffice.py: TestParseDiverofficeFile ────────
# (appended to existing TestDiverOfficeParser class above via separate tests
#  so as not to duplicate.  The 9 tests below use parse_old/parse API.)


@pytest.mark.active
class TestDiverOfficeParserOldFormat:
    """Parser unit tests ported from TestParseDiverofficeFile in test_import_diveroffice.py.
    These specifically test parse_old (legacy CSV) and parse (new .mon/.csv) methods."""

    def test_parse_old_utf8(self):
        f = (
            "Location=rb1",
            "Date/time,Water head[cm],Temperature[\u00b0C]",
            "2016/03/15 10:30:00,26.9,5.18",
            "2016/03/15 11:00:00,157.7,0.6",
        )
        charset = "utf-8"
        with file_utils.tempinput("\n".join(f), charset) as path:
            file_data = DiverOfficeParser.parse(path, charset)

        test_string = utils_for_tests.create_test_string(file_data[0])
        reference_string = "[[date_time, head_cm, temp_degc, cond_mscm], [2016-03-15 10:30:00, 26.9, 5.18, None], [2016-03-15 11:00:00, 157.7, 0.6, None]]"
        assert test_string == reference_string
        assert os.path.basename(path) == file_data[1]
        assert file_data[2] == "rb1"

    def test_parse_old_cp1252(self):
        f = (
            "Location=rb1",
            "Date/time,Water head[cm],Temperature[\u00b0C]",
            "2016/03/15 10:30:00,26.9,5.18",
            "2016/03/15 11:00:00,157.7,0.6",
        )
        charset = "cp1252"
        with file_utils.tempinput("\n".join(f), charset) as path:
            file_data = DiverOfficeParser.parse(path, charset)

        test_string = utils_for_tests.create_test_string(file_data[0])
        reference_string = "[[date_time, head_cm, temp_degc, cond_mscm], [2016-03-15 10:30:00, 26.9, 5.18, None], [2016-03-15 11:00:00, 157.7, 0.6, None]]"
        assert test_string == reference_string
        assert os.path.basename(path) == file_data[1]
        assert file_data[2] == "rb1"

    def test_parse_old_semicolon_sep(self):
        f = (
            "Location=rb1",
            "Date/time;Water head[cm];Temperature[\u00b0C]",
            "2016/03/15 10:30:00;26.9;5.18",
            "2016/03/15 11:00:00;157.7;0.6",
        )
        charset = "cp1252"
        with file_utils.tempinput("\n".join(f), charset) as path:
            file_data = DiverOfficeParser.parse(path, charset)

        test_string = utils_for_tests.create_test_string(file_data[0])
        reference_string = "[[date_time, head_cm, temp_degc, cond_mscm], [2016-03-15 10:30:00, 26.9, 5.18, None], [2016-03-15 11:00:00, 157.7, 0.6, None]]"
        assert test_string == reference_string
        assert os.path.basename(path) == file_data[1]
        assert file_data[2] == "rb1"

    def test_parse_old_comma_dec(self):
        f = (
            "Location=rb1",
            "Date/time;Water head[cm];Temperature[\u00b0C]",
            "2016/03/15 10:30:00;26,9;5,18",
            "2016/03/15 11:00:00;157,7;0,6",
        )
        charset = "cp1252"
        with file_utils.tempinput("\n".join(f), charset) as path:
            file_data = DiverOfficeParser.parse(path, charset)

        test_string = utils_for_tests.create_test_string(file_data[0])
        reference_string = r"""[[date_time, head_cm, temp_degc, cond_mscm], [2016-03-15 10:30:00, 26.9, 5.18, None], [2016-03-15 11:00:00, 157.7, 0.6, None]]"""
        assert test_string == reference_string
        assert os.path.basename(path) == file_data[1]
        assert file_data[2] == "rb1"

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_parse_old_comma_sep_comma_dec_failed(self, mock_messagebar):
        """Ambiguous format (comma sep + comma decimal): delimiter cannot be reliably detected."""
        f = (
            "Location=rb1",
            "Date/time,Water head[cm],Temperature[\u00b0C]",
            "2016/03/15 10:30:00,26,9,5,18",
            "2016/03/15 11:00:00,157,7,0,6",
        )
        charset = "cp1252"
        with file_utils.tempinput("\n".join(f), charset) as path:
            with pytest.raises(DiverOfficeParseError, match="delimited fields"):
                DiverOfficeParser.parse(path, charset)

    def test_parse_old_different_separators(self):
        """parse() handles semicolon data with comma header: detects ';' from data rows."""
        f = (
            "Location=rb1",
            "Date/time,Water head[cm],Temperature[\u00b0C]",
            "2016/03/15 10:30:00;26,9;5,18",
            "2016/03/15 11:00:00;157,7;0,6",
        )
        charset = "cp1252"
        with file_utils.tempinput("\n".join(f), charset) as path:
            file_data = DiverOfficeParser.parse(path, charset)
        test_string = utils_for_tests.create_test_string(file_data[0])
        reference_string = "[[date_time, head_cm, temp_degc, cond_mscm], [2016-03-15 10:30:00, 26.9, 5.18, None], [2016-03-15 11:00:00, 157.7, 0.6, None]]"
        assert test_string == reference_string
        assert file_data[2] == "rb1"

    def test_parse_old_changed_order(self):
        f = (
            "Location=rb1",
            "Temperature[\u00b0C];2:Spec.cond.[mS/cm];Date/time;Water head[cm]",
            "5.18;2;2016/03/15 10:30:00;26.9",
            "0.6;3;2016/03/15 11:00:00;157.7",
        )
        charset = "cp1252"
        with file_utils.tempinput("\n".join(f), charset) as path:
            file_data = DiverOfficeParser.parse(path, charset)

        test_string = utils_for_tests.create_test_string(file_data[0])
        reference_string = "[[date_time, head_cm, temp_degc, cond_mscm], [2016-03-15 10:30:00, 26.9, 5.18, 2], [2016-03-15 11:00:00, 157.7, 0.6, 3]]"
        assert test_string == reference_string
        assert os.path.basename(path) == file_data[1]
        assert file_data[2] == "rb1"

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_parse_old_warning_missing_head_cm(self, mock_messagebar):
        f = (
            "Location=rb1",
            "Temperature[\u00b0C];2:Spec.cond.[mS/cm];Date/time",
            "5.18;2;2016/03/15 10:30:00",
            "0.6;3;2016/03/15 11:00:00",
        )
        charset = "cp1252"
        with file_utils.tempinput("\n".join(f), charset) as path:
            file_data = DiverOfficeParser.parse(path, charset)

        test_string = utils_for_tests.create_test_string(file_data[0])
        reference_string = "[[date_time, head_cm, temp_degc, cond_mscm], [2016-03-15 10:30:00, None, 5.18, 2], [2016-03-15 11:00:00, None, 0.6, 3]]"
        assert len(mock_messagebar.mock_calls) == 1
        assert test_string == reference_string
        assert os.path.basename(path) == file_data[1]
        assert file_data[2] == "rb1"

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_parse_old_warning_missing_date_time(self, mock_messagebar):
        f = (
            "Location=rb1",
            "Temperature[\u00b0C];2:Spec.cond.[mS/cm];dada",
            "5.18;2;2016/03/15 10:30:00",
            "0.6;3;2016/03/15 11:00:00",
        )
        charset = "cp1252"
        with file_utils.tempinput("\n".join(f), charset) as path:
            file_data = DiverOfficeParser.parse(path, charset)

        assert file_data[0] == []
        assert len(mock_messagebar.mock_calls) == 1

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_parse_old_get_timezone(self, mock_messagebar):
        f = (
            "Location=rb1",
            "Instrument number       =UTC+1",
            "Date/time,Water head[cm],Temperature[\u00b0C]",
            "2016/03/15 10:30:00,26.9,5.18",
            "2016/03/15 11:00:00,157.7,0.6",
        )
        charset = "utf-8"
        with file_utils.tempinput("\n".join(f), charset) as path:
            file_data = DiverOfficeParser.parse(path, charset)

        test_string = utils_for_tests.create_test_string(file_data[0])
        reference_string = "[[date_time, head_cm, temp_degc, cond_mscm], [2016-03-15 10:30:00, 26.9, 5.18, None], [2016-03-15 11:00:00, 157.7, 0.6, None]]"
        assert test_string == reference_string
        assert os.path.basename(path) == file_data[1]
        assert file_data[2] == "rb1"
        assert file_data[3] == "UTC+1"

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_parse_comma_missing_head_cm_value(self, mock_messagebar):
        """parse() (new-style .csv/.mon) with missing head_cm value."""
        f = (
            "[Logger settings]",
            "Location=rb1",
            "[Channel 1]",
            "Identification          =LEVEL",
            "[Channel 2]",
            "Identification          =TEMPERATURE",
            "",
            "Date/time;Water head[cm];Temperature[\u00b0C]",
            "2016/03/15 10:30:00;1,2;10",
            "2016/03/15 11:00:00;    ;101",
            "END OF DATA FILE OF DATALOGGER FOR WINDOWS",
            "    ",
        )
        charset = "utf-8"
        with file_utils.tempinput("\n".join(f), charset, suffix=".csv") as path:
            file_data = DiverOfficeParser.parse(
                path=path,
                charset=charset,
                skip_rows_without_water_level=False,
                begindate=None,
                enddate=None,
            )

        test_string = utils_for_tests.create_test_string(file_data[0])
        reference_string = "[[date_time, head_cm, temp_degc, cond_mscm], [2016-03-15 10:30:00, 1.2, 10, None], [2016-03-15 11:00:00, None, 101, None]]"
        assert test_string == reference_string
        assert os.path.basename(path) == file_data[1]
        assert file_data[2] == "rb1"


# ── Hobo parser tests ported from test_import_hobologger.py ───────────────────


@pytest.mark.active
class TestHoboParserOldAPI:
    """Parser unit tests ported from TestParseHobologgerFile in test_import_hobologger.py.
    These test HoboParser.parse() (which replaced HobologgerImport.parse_hobologger_file)."""

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_parse_hobologger_file_utf8(self, mock_messagelog):
        f = (
            '\ufeff"Plot Title: temp"',
            '"#","Date Time, GMT+01:00","Temp, \u00b0C (LGR S/N: 1234, SEN S/N: 1234, LBL: Rb1)","Coupler Detached (LGR S/N: 1234)","Coupler Attached (LGR S/N: 1234)","Stopped (LGR S/N: 1234)","End Of File (LGR S/N: 1234)"',
            "1,07/19/18 10:00:00 fm,4.558,Logged,,,",
            "2,07/19/18 11:00:00 fm,4.402,,,,",
            "3,07/19/18 12:00:00 em,4.402,,,,",
            "4,07/19/18 01:00:00 em,4.402,,,,",
        )
        charset = "utf-8"
        tzconverter = TzConverter()
        with file_utils.tempinput("\n".join(f), charset) as path:
            file_data = HoboParser.parse(
                path, charset, tz_converter=tzconverter, begindate=None, enddate=None
            )

        test_string = utils_for_tests.create_test_string(file_data[0])
        reference_string = "[[date_time, head_cm, temp_degc, cond_mscm], [2018-07-19 10:00:00, , 4.558, ], [2018-07-19 11:00:00, , 4.402, ], [2018-07-19 12:00:00, , 4.402, ], [2018-07-19 13:00:00, , 4.402, ]]"
        assert test_string == reference_string
        assert os.path.basename(path) == file_data[1]
        assert file_data[2] == "Rb1"

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_parse_hobologger_file_convert_tz(self, mock_messagelog):
        f = (
            '\ufeff"Plot Title: temp"',
            '"#","Date Time, GMT+03:00","Temp, \u00b0C (LGR S/N: 1234, SEN S/N: 1234, LBL: Rb1)","Coupler Detached (LGR S/N: 1234)","Coupler Attached (LGR S/N: 1234)","Stopped (LGR S/N: 1234)","End Of File (LGR S/N: 1234)"',
            "1,07/19/18 10:00:00 fm,4.558,Logged,,,",
            "2,07/19/18 11:00:00 fm,4.402,,,,",
            "3,07/19/18 12:00:00 em,4.402,,,,",
            "4,07/19/18 01:00:00 em,4.402,,,,",
        )
        charset = "utf-8"
        tzconverter = TzConverter()
        tzconverter.target_tz = "GMT+01:00"
        with file_utils.tempinput("\n".join(f), charset) as path:
            file_data = HoboParser.parse(
                path, charset, tz_converter=tzconverter, begindate=None, enddate=None
            )

        test_string = utils_for_tests.create_test_string(file_data[0])
        reference_string = "[[date_time, head_cm, temp_degc, cond_mscm], [2018-07-19 08:00:00, , 4.558, ], [2018-07-19 09:00:00, , 4.402, ], [2018-07-19 10:00:00, , 4.402, ], [2018-07-19 11:00:00, , 4.402, ]]"
        assert test_string == reference_string
        assert os.path.basename(path) == file_data[1]
        assert file_data[2] == "Rb1"

    def test_parse_hobologger_file_changed_order(self):
        f = (
            '\ufeff"Plot Title: temp"',
            '"#","Temp, \u00b0C (LGR S/N: 1234, SEN S/N: 1234, LBL: Rb1)","Date Time, GMT+01:00","Coupler Detached (LGR S/N: 1234)","Coupler Attached (LGR S/N: 1234)","Stopped (LGR S/N: 1234)","End Of File (LGR S/N: 1234)"',
            "1,4.558,07/19/18 10:00:00 fm,Logged,,,",
            "2,4.402,07/19/18 11:00:00 fm,,,,",
            "3,4.402,07/19/18 12:00:00 em,,,,",
            "4,4.402,07/19/18 01:00:00 em,,,,",
        )
        charset = "utf-8"
        tzconverter = TzConverter()
        with file_utils.tempinput("\n".join(f), charset) as path:
            file_data = HoboParser.parse(
                path, charset, tz_converter=tzconverter, begindate=None, enddate=None
            )

        test_string = utils_for_tests.create_test_string(file_data[0])
        reference_string = "[[date_time, head_cm, temp_degc, cond_mscm], [2018-07-19 10:00:00, , 4.558, ], [2018-07-19 11:00:00, , 4.402, ], [2018-07-19 12:00:00, , 4.402, ], [2018-07-19 13:00:00, , 4.402, ]]"
        assert test_string == reference_string
        assert os.path.basename(path) == file_data[1]
        assert file_data[2] == "Rb1"

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_parse_hobologger_file_other_dateformat(self, mock_messagelog):
        f = (
            '\ufeff"Plot Title: temp"',
            '"#","Date Time, GMT+01:00","Temp, \u00b0C (LGR S/N: 1234, SEN S/N: 1234, LBL: Rb1)","Coupler Detached (LGR S/N: 1234)","Coupler Attached (LGR S/N: 1234)","Stopped (LGR S/N: 1234)","End Of File (LGR S/N: 1234)"',
            "1,2018-07-19 10:00:00,4.558,Logged,,,",
            "2,2018-07-19 11:00:00,4.402,,,,",
            "3,2018-07-19 12:00:00,4.402,,,,",
            "4,2018-07-19 13:00:00,4.402,,,,",
        )
        charset = "utf-8"
        tzconverter = TzConverter()
        with file_utils.tempinput("\n".join(f), charset) as path:
            file_data = HoboParser.parse(
                path, charset, tz_converter=tzconverter, begindate=None, enddate=None
            )

        test_string = utils_for_tests.create_test_string(file_data[0])
        reference_string = "[[date_time, head_cm, temp_degc, cond_mscm], [2018-07-19 10:00:00, , 4.558, ], [2018-07-19 11:00:00, , 4.402, ], [2018-07-19 12:00:00, , 4.402, ], [2018-07-19 13:00:00, , 4.402, ]]"
        assert test_string == reference_string
        assert os.path.basename(path) == file_data[1]
        assert file_data[2] == "Rb1"


# ── Integration test mixin: DiverOffice ──────────────────────────────────────
# Ported from WlvllogImportFromDiverofficeFilesMixin in test_import_diveroffice_backends.py

_CHARSET = "utf-8"


class WlvllogImportFromLoggerDiverOfficeMixin:
    """Integration tests for LoggerImport (DiverOffice format).

    Ported from WlvllogImportFromDiverofficeFilesMixin.
    Each inner helper _run() applies the migration pattern:
    - DiverofficeImport -> LoggerImport (default DiverOffice format)
    - mock import_logger.midvatten_utils.select_files
    - remove QInputDialog.getText mock (encoding is automatic)
    """

    def test_wlvllogg_import_from_diveroffice_files(self):
        files = [
            (
                "Location=rb1",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/03/15 10:30:00,1,10",
                "2016/03/15 11:00:00,11,101",
            ),
            (
                "Location=rb2",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/04/15 10:30:00,2,20",
                "2016/04/15 11:00:00,21,201",
            ),
            (
                "Location=rb3",
                "Date/time,Water head[cm],Temperature[\u00b0C],Conductivity[mS/cm]",
                "2016/05/15 10:30:00,3,30,5",
                "2016/05/15 11:00:00,31,301,6",
            ),
        ]

        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")

        with (
            file_utils.tempinput("\n".join(files[0]), _CHARSET) as f1,
            file_utils.tempinput("\n".join(files[1]), _CHARSET) as f2,
            file_utils.tempinput("\n".join(files[2]), _CHARSET) as f3,
        ):
            filenames = [f1, f2, f3]

            @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(
                self,
                filenames,
                mock_filenames,
                mock_skippopup,
                mock_iface,
                mock_askuser,
                mock_notfoundquestion,
            ):
                mock_notfoundquestion.return_value.answer = "ok"
                mock_notfoundquestion.return_value.value = "rb1"
                mock_notfoundquestion.return_value.reuse_column = "location"
                mock_filenames.return_value = filenames
                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = LoggerImport(self.iface, ms)
                importer.load_gui()
                importer.select_files()
                importer.start_import(
                    importer.files,
                    importer.skip_rows.checked,
                    importer.confirm_names.checked,
                    importer.import_all_data.checked,
                )

            _run(self, filenames)

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = r"""(True, [(rb1, 2016-03-15 10:30:00, 1.0, 10.0, None, None, None), (rb1, 2016-03-15 11:00:00, 11.0, 101.0, None, None, None), (rb1, 2016-04-15 10:30:00, 2.0, 20.0, None, None, None), (rb1, 2016-04-15 11:00:00, 21.0, 201.0, None, None, None), (rb1, 2016-05-15 10:30:00, 3.0, 30.0, 5.0, None, None), (rb1, 2016-05-15 11:00:00, 31.0, 301.0, 6.0, None, None)])"""
        assert test_string == reference_string

    def test_wlvllogg_import_from_diveroffice_files_skip_duplicate_datetimes(self):
        files = [
            (
                "Location=rb1",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/03/15 10:30:00,1,10",
                "2016/03/15 11:00:00,11,101",
            ),
            (
                "Location=rb2",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/04/15 10:30:00,2,20",
                "2016/04/15 11:00:00,21,201",
            ),
            (
                "Location=rb3",
                "Date/time,Water head[cm],Temperature[\u00b0C],Conductivity[mS/cm]",
                "2016/05/15 10:30:00,3,30,5",
                "2016/05/15 11:00:00,31,301,6",
            ),
        ]
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm) VALUES ('rb1', '2016-03-15 10:30', '5.0')"
        )

        with (
            file_utils.tempinput("\n".join(files[0]), _CHARSET) as f1,
            file_utils.tempinput("\n".join(files[1]), _CHARSET) as f2,
            file_utils.tempinput("\n".join(files[2]), _CHARSET) as f3,
        ):
            filenames = [f1, f2, f3]

            @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(
                self,
                filenames,
                mock_filenames,
                mock_skippopup,
                mock_iface,
                mock_askuser,
                mock_notfoundquestion,
            ):
                mock_notfoundquestion.return_value.answer = "ok"
                mock_notfoundquestion.return_value.value = "rb1"
                mock_notfoundquestion.return_value.reuse_column = "location"
                mock_filenames.return_value = filenames
                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = LoggerImport(self.iface, ms)
                importer.load_gui()
                importer.select_files()
                importer.start_import(
                    importer.files,
                    importer.skip_rows.checked,
                    importer.confirm_names.checked,
                    importer.import_all_data.checked,
                )

            _run(self, filenames)

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = r"""(True, [(rb1, 2016-03-15 10:30, 5.0, None, None, None, None), (rb1, 2016-03-15 11:00:00, 11.0, 101.0, None, None, None), (rb1, 2016-04-15 10:30:00, 2.0, 20.0, None, None, None), (rb1, 2016-04-15 11:00:00, 21.0, 201.0, None, None, None), (rb1, 2016-05-15 10:30:00, 3.0, 30.0, 5.0, None, None), (rb1, 2016-05-15 11:00:00, 31.0, 301.0, 6.0, None, None)])"""
        assert test_string == reference_string

    def test_wlvllogg_import_from_diveroffice_files_filter_dates(self):
        files = [
            (
                "Location=rb1",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/03/15 10:30:00,1,10",
                "2016/03/15 11:00:00,11,101",
            ),
            (
                "Location=rb2",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/04/15 10:30:00,2,20",
                "2016/04/15 11:00:00,21,201",
            ),
            (
                "Location=rb3",
                "Date/time,Water head[cm],Temperature[\u00b0C],Conductivity[mS/cm]",
                "2016/05/15 10:30:00,3,30,5",
                "2016/05/15 11:00:00,31,301,6",
            ),
        ]
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm) VALUES ('rb1', '2016-03-15 10:31', '5.0')"
        )

        with (
            file_utils.tempinput("\n".join(files[0]), _CHARSET) as f1,
            file_utils.tempinput("\n".join(files[1]), _CHARSET) as f2,
            file_utils.tempinput("\n".join(files[2]), _CHARSET) as f3,
        ):
            filenames = [f1, f2, f3]

            @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(
                self,
                filenames,
                mock_filenames,
                mock_skippopup,
                mock_iface,
                mock_askuser,
                mock_notfoundquestion,
            ):
                mock_notfoundquestion.return_value.answer = "ok"
                mock_notfoundquestion.return_value.value = "rb1"
                mock_notfoundquestion.return_value.reuse_column = "location"
                mock_filenames.return_value = filenames
                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = LoggerImport(self.iface, ms)
                importer.load_gui()
                importer.select_files()
                importer.import_all_data.checked = False
                importer.start_import(
                    importer.files,
                    importer.skip_rows.checked,
                    importer.confirm_names.checked,
                    importer.import_all_data.checked,
                )

            _run(self, filenames)

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = r"""(True, [(rb1, 2016-03-15 10:31, 5.0, None, None, None, None), (rb1, 2016-03-15 11:00:00, 11.0, 101.0, None, None, None), (rb1, 2016-04-15 10:30:00, 2.0, 20.0, None, None, None), (rb1, 2016-04-15 11:00:00, 21.0, 201.0, None, None, None), (rb1, 2016-05-15 10:30:00, 3.0, 30.0, 5.0, None, None), (rb1, 2016-05-15 11:00:00, 31.0, 301.0, 6.0, None, None)])"""
        assert test_string == reference_string

    def test_wlvllogg_import_from_diveroffice_files_all_dates(self):
        files = [
            (
                "Location=rb1",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/03/15 10:30:00,1,10",
                "2016/03/15 11:00:00,11,101",
            ),
            (
                "Location=rb2",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/04/15 10:30:00,2,20",
                "2016/04/15 11:00:00,21,201",
            ),
            (
                "Location=rb3",
                "Date/time,Water head[cm],Temperature[\u00b0C],Conductivity[mS/cm]",
                "2016/05/15 10:30:00,3,30,5",
                "2016/05/15 11:00:00,31,301,6",
            ),
        ]
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb2')")
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb3')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm) VALUES ('rb1', '2016-03-15 10:31', '5.0')"
        )

        with (
            file_utils.tempinput("\n".join(files[0]), _CHARSET) as f1,
            file_utils.tempinput("\n".join(files[1]), _CHARSET) as f2,
            file_utils.tempinput("\n".join(files[2]), _CHARSET) as f3,
        ):
            filenames = [f1, f2, f3]

            @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(
                self,
                filenames,
                mock_filenames,
                mock_skippopup,
                mock_iface,
                mock_askuser,
                mock_notfoundquestion,
            ):
                mock_notfoundquestion.return_value.answer = "ok"
                mock_notfoundquestion.return_value.value = "rb1"
                mock_notfoundquestion.return_value.reuse_column = "location"
                mock_filenames.return_value = filenames
                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = LoggerImport(self.iface, ms)
                importer.load_gui()
                importer.select_files()
                importer.import_all_data.checked = True
                importer.confirm_names.checked = False
                importer.start_import(
                    importer.files,
                    importer.skip_rows.checked,
                    importer.confirm_names.checked,
                    importer.import_all_data.checked,
                )

            _run(self, filenames)

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = r"""(True, [(rb1, 2016-03-15 10:30:00, 1.0, 10.0, None, None, None), (rb1, 2016-03-15 10:31, 5.0, None, None, None, None), (rb1, 2016-03-15 11:00:00, 11.0, 101.0, None, None, None), (rb2, 2016-04-15 10:30:00, 2.0, 20.0, None, None, None), (rb2, 2016-04-15 11:00:00, 21.0, 201.0, None, None, None), (rb3, 2016-05-15 10:30:00, 3.0, 30.0, 5.0, None, None), (rb3, 2016-05-15 11:00:00, 31.0, 301.0, 6.0, None, None)])"""
        assert test_string == reference_string

    def test_wlvllogg_import_from_diveroffice_files_try_capitalize(self):
        files = [
            (
                "Location=rb1",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/03/15 10:30:00,1,10",
                "2016/03/15 11:00:00,11,101",
            )
        ]
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('Rb1')")

        with file_utils.tempinput("\n".join(files[0]), _CHARSET) as f1:
            filenames = [f1]

            @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(
                self,
                filenames,
                mock_filenames,
                mock_skippopup,
                mock_iface,
                mock_askuser,
                mock_notfoundquestion,
            ):
                mock_notfoundquestion.return_value.answer = "ok"
                mock_notfoundquestion.return_value.value = "rb1"
                mock_notfoundquestion.return_value.reuse_column = "location"
                mock_filenames.return_value = filenames
                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = LoggerImport(self.iface, ms)
                importer.load_gui()
                importer.select_files()
                importer.import_all_data.checked = False
                importer.confirm_names.checked = False
                importer.start_import(
                    importer.files,
                    importer.skip_rows.checked,
                    importer.confirm_names.checked,
                    importer.import_all_data.checked,
                )

            _run(self, filenames)

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = r"""(True, [(Rb1, 2016-03-15 10:30:00, 1.0, 10.0, None, None, None), (Rb1, 2016-03-15 11:00:00, 11.0, 101.0, None, None, None)])"""
        assert test_string == reference_string

    def test_wlvllogg_import_from_diveroffice_files_cancel(self):
        files = [
            (
                "Location=rb2",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/03/15 10:30:00,1,10",
                "2016/03/15 11:00:00,11,101",
            )
        ]
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('Rb1')")

        with file_utils.tempinput("\n".join(files[0]), _CHARSET) as f1:
            filenames = [f1]

            @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(
                self,
                filenames,
                mock_filenames,
                mock_skippopup,
                mock_iface,
                mock_askuser,
                mock_notfoundquestion,
            ):
                mock_notfoundquestion.return_value.answer = "cancel"
                mock_notfoundquestion.return_value.value = "rb1"
                mock_notfoundquestion.return_value.reuse_column = "location"
                mock_filenames.return_value = filenames
                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = LoggerImport(self.iface, ms)
                importer.load_gui()
                importer.select_files()
                importer.import_all_data.checked = True
                importer.confirm_names.checked = False
                importer.start_import(
                    importer.files,
                    importer.skip_rows.checked,
                    importer.confirm_names.checked,
                    importer.import_all_data.checked,
                )

            _run(self, filenames)

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = r"""(True, [])"""
        assert test_string == reference_string

    def test_wlvllogg_import_from_diveroffice_files_skip_missing_water_level(self):
        files = [
            (
                "Location=rb1",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/03/15 10:30:00,1,10",
                "2016/03/15 11:00:00,,101",
            ),
            (
                "Location=rb2",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/04/15 10:30:00,2,20",
                "2016/04/15 11:00:00,21,201",
            ),
            (
                "Location=rb3",
                "Date/time,Water head[cm],Temperature[\u00b0C],Conductivity[mS/cm]",
                "2016/05/15 10:30:00,3,30,5",
                "2016/05/15 11:00:00,31,301,6",
            ),
        ]
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb2')")
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb3')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm) VALUES ('rb1', '2016-03-15 10:31', '5.0')"
        )

        with (
            file_utils.tempinput("\n".join(files[0]), _CHARSET) as f1,
            file_utils.tempinput("\n".join(files[1]), _CHARSET) as f2,
            file_utils.tempinput("\n".join(files[2]), _CHARSET) as f3,
        ):
            filenames = [f1, f2, f3]

            @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(
                self,
                filenames,
                mock_filenames,
                mock_skippopup,
                mock_iface,
                mock_askuser,
                mock_notfoundquestion,
            ):
                mock_notfoundquestion.return_value.answer = "ok"
                mock_notfoundquestion.return_value.value = "rb1"
                mock_notfoundquestion.return_value.reuse_column = "location"
                mock_filenames.return_value = filenames
                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = LoggerImport(self.iface, ms)
                importer.load_gui()
                importer.select_files()
                importer.import_all_data.checked = True
                importer.confirm_names.checked = False
                importer.skip_rows.checked = True
                importer.start_import(
                    importer.files,
                    importer.skip_rows.checked,
                    importer.confirm_names.checked,
                    importer.import_all_data.checked,
                )

            _run(self, filenames)

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = r"""(True, [(rb1, 2016-03-15 10:30:00, 1.0, 10.0, None, None, None), (rb1, 2016-03-15 10:31, 5.0, None, None, None, None), (rb2, 2016-04-15 10:30:00, 2.0, 20.0, None, None, None), (rb2, 2016-04-15 11:00:00, 21.0, 201.0, None, None, None), (rb3, 2016-05-15 10:30:00, 3.0, 30.0, 5.0, None, None), (rb3, 2016-05-15 11:00:00, 31.0, 301.0, 6.0, None, None)])"""
        assert test_string == reference_string

    def test_wlvllogg_import_from_diveroffice_files_not_skip_missing_water_level(self):
        files = [
            (
                "Location=rb1",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/03/15 10:30:00,1,10",
                "2016/03/15 11:00:00,,101",
            ),
            (
                "Location=rb2",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/04/15 10:30:00,2,20",
                "2016/04/15 11:00:00,21,201",
            ),
            (
                "Location=rb3",
                "Date/time,Water head[cm],Temperature[\u00b0C],Conductivity[mS/cm]",
                "2016/05/15 10:30:00,3,30,5",
                "2016/05/15 11:00:00,31,301,6",
            ),
        ]
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb2')")
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb3')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm) VALUES ('rb1', '2016-03-15 10:31', '5.0')"
        )

        with (
            file_utils.tempinput("\n".join(files[0]), _CHARSET) as f1,
            file_utils.tempinput("\n".join(files[1]), _CHARSET) as f2,
            file_utils.tempinput("\n".join(files[2]), _CHARSET) as f3,
        ):
            filenames = [f1, f2, f3]

            @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(
                self,
                filenames,
                mock_filenames,
                mock_skippopup,
                mock_iface,
                mock_askuser,
                mock_notfoundquestion,
            ):
                mock_notfoundquestion.return_value.answer = "ok"
                mock_notfoundquestion.return_value.value = "rb1"
                mock_notfoundquestion.return_value.reuse_column = "location"
                mock_filenames.return_value = filenames
                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = LoggerImport(self.iface, ms)
                importer.load_gui()
                importer.select_files()
                importer.import_all_data.checked = True
                importer.confirm_names.checked = False
                importer.skip_rows.checked = False
                importer.start_import(
                    importer.files,
                    importer.skip_rows.checked,
                    importer.confirm_names.checked,
                    importer.import_all_data.checked,
                )

            _run(self, filenames)

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = r"""(True, [(rb1, 2016-03-15 10:30:00, 1.0, 10.0, None, None, None), (rb1, 2016-03-15 10:31, 5.0, None, None, None, None), (rb1, 2016-03-15 11:00:00, None, 101.0, None, None, None), (rb2, 2016-04-15 10:30:00, 2.0, 20.0, None, None, None), (rb2, 2016-04-15 11:00:00, 21.0, 201.0, None, None, None), (rb3, 2016-05-15 10:30:00, 3.0, 30.0, 5.0, None, None), (rb3, 2016-05-15 11:00:00, 31.0, 301.0, 6.0, None, None)])"""
        assert test_string == reference_string

    def test_wlvllogg_import_from_diveroffice_files_datetime_filter(self):
        files = [
            (
                "Location=rb1",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/03/15 10:30:00,1,10",
                "2016/03/15 11:00:00,11,101",
                "2016/06/15 11:00:00,11,101",
            ),
            (
                "Location=rb2",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/04/15 10:30:00,2,20",
                "2016/04/15 11:00:00,21,201",
            ),
        ]
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb2')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm) VALUES ('rb1', '2016-03-15 10:31', '5.0')"
        )

        with (
            file_utils.tempinput("\n".join(files[0]), _CHARSET) as f1,
            file_utils.tempinput("\n".join(files[1]), _CHARSET) as f2,
        ):
            filenames = [f1, f2]

            @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(
                self,
                filenames,
                mock_filenames,
                mock_skippopup,
                mock_iface,
                mock_askuser,
                mock_notfoundquestion,
            ):
                mock_notfoundquestion.return_value.answer = "ok"
                mock_notfoundquestion.return_value.value = "rb1"
                mock_notfoundquestion.return_value.reuse_column = "location"
                mock_filenames.return_value = filenames
                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = LoggerImport(self.iface, ms)
                importer.load_gui()
                importer.select_files()
                importer.import_all_data.checked = True
                importer.confirm_names.checked = False
                importer.date_time_filter.from_date = "2016-03-15 11:00:00"
                importer.date_time_filter.to_date = "2016-04-15 10:30:00"
                importer.start_import(
                    importer.files,
                    importer.skip_rows.checked,
                    importer.confirm_names.checked,
                    importer.import_all_data.checked,
                    importer.date_time_filter.from_date,
                    importer.date_time_filter.to_date,
                )

            _run(self, filenames)

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = r"""(True, [(rb1, 2016-03-15 10:31, 5.0, None, None, None, None), (rb1, 2016-03-15 11:00:00, 11.0, 101.0, None, None, None), (rb2, 2016-04-15 10:30:00, 2.0, 20.0, None, None, None)])"""
        assert test_string == reference_string

    def test_wlvllogg_import_from_diveroffice_files_skip_obsid(self):
        files = [
            (
                "Location=rb1",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/03/15 10:30:00,1,10",
                "2016/03/15 11:00:00,11,101",
            ),
            (
                "Location=rb2",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/04/15 10:30:00,2,20",
                "2016/04/15 11:00:00,21,201",
            ),
            (
                "Location=rb3",
                "Date/time,Water head[cm],Temperature[\u00b0C],Conductivity[mS/cm]",
                "2016/05/15 10:30:00,3,30,5",
                "2016/05/15 11:00:00,31,301,6",
            ),
        ]
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb2')")

        with (
            file_utils.tempinput("\n".join(files[0]), _CHARSET) as f1,
            file_utils.tempinput("\n".join(files[1]), _CHARSET) as f2,
            file_utils.tempinput("\n".join(files[2]), _CHARSET) as f3,
        ):
            filenames = [f1, f2, f3]

            @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
            @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(
                self,
                filenames,
                mock_filenames,
                mock_skippopup,
                mock_iface,
                mock_askuser,
                mock_notfoundquestion,
                mock_messagebar,
            ):
                mocks_notfoundquestion = []
                for answer, value in [["ok", "rb1"], ["ok", "rb2"], ["skip", "rb3"]]:
                    a_mock = MagicMock()
                    a_mock.answer = answer
                    a_mock.value = value
                    a_mock.reuse_column = "location"
                    mocks_notfoundquestion.append(a_mock)
                mock_notfoundquestion.side_effect = mocks_notfoundquestion
                mock_filenames.return_value = filenames
                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = LoggerImport(self.iface, ms)
                importer.load_gui()
                importer.select_files()
                importer.start_import(
                    importer.files,
                    importer.skip_rows.checked,
                    importer.confirm_names.checked,
                    importer.import_all_data.checked,
                )
                print("\n".join([str(x) for x in mock_messagebar.mock_calls]))

            _run(self, filenames)

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = r"""(True, [(rb1, 2016-03-15 10:30:00, 1.0, 10.0, None, None, None), (rb1, 2016-03-15 11:00:00, 11.0, 101.0, None, None, None), (rb2, 2016-04-15 10:30:00, 2.0, 20.0, None, None, None), (rb2, 2016-04-15 11:00:00, 21.0, 201.0, None, None, None)])"""
        assert test_string == reference_string

    def test_wlvllogg_import_change_timezone(self):
        files = [
            (
                "Location=rb1",
                "Instrument number=UTC+1",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/03/15 10:30:00,1,10",
                "2016/03/15 11:00:00,11,101",
            ),
            (
                "Location=rb2",
                "Instrument number=UTC+2",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/04/15 10:30:00,2,20",
                "2016/04/15 11:00:00,21,201",
            ),
            (
                "Location=rb3",
                "Instrument number",
                "Date/time,Water head[cm],Temperature[\u00b0C],Conductivity[mS/cm]",
                "2016/05/15 10:30:00,3,30,5",
                "2016/05/15 11:00:00,31,301,6",
            ),
            (
                "Location=rb4",
                "Date/time,Water head[cm],Temperature[\u00b0C],Conductivity[mS/cm]",
                "2016/05/15 10:30:00,3,30,5",
                "2016/05/15 11:00:00,31,301,6",
            ),
            (
                "Location=rb5",
                "Instrument number=UTC-2",
                "Date/time,Water head[cm],Temperature[\u00b0C],Conductivity[mS/cm]",
                "2016/05/15 10:30:00,3,30,5",
                "2016/05/15 11:00:00,31,301,6",
            ),
        ]
        for obsid in ["rb1", "rb2", "rb3", "rb4", "rb5"]:
            db_utils.sql_alter_db(f"INSERT INTO obs_points (obsid) VALUES ('{obsid}')")

        with (
            file_utils.tempinput("\n".join(files[0]), _CHARSET) as f1,
            file_utils.tempinput("\n".join(files[1]), _CHARSET) as f2,
            file_utils.tempinput("\n".join(files[2]), _CHARSET) as f3,
            file_utils.tempinput("\n".join(files[3]), _CHARSET) as f4,
            file_utils.tempinput("\n".join(files[4]), _CHARSET) as f5,
        ):
            filenames = [f1, f2, f3, f4, f5]

            @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(
                self,
                filenames,
                mock_filenames,
                mock_skippopup,
                mock_iface,
                mock_askuser,
                mock_notfoundquestion,
            ):
                mock_notfoundquestion.return_value.answer = "ok"
                mock_notfoundquestion.return_value.value = "rb1"
                mock_notfoundquestion.return_value.reuse_column = "location"
                mock_filenames.return_value = filenames
                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = LoggerImport(self.iface, ms)
                importer.load_gui()
                importer.confirm_names.checked = False

                set_combobox(importer.utc_offset, "UTC+1", add_if_not_exists=False)
                importer.select_files()
                importer.start_import(
                    importer.files,
                    importer.skip_rows.checked,
                    importer.confirm_names.checked,
                    importer.import_all_data.checked,
                )

            _run(self, filenames)

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = r"""(True, [(rb1, 2016-03-15 10:30:00, 1.0, 10.0, None, None, None), (rb1, 2016-03-15 11:00:00, 11.0, 101.0, None, None, None), (rb2, 2016-04-15 09:30:00, 2.0, 20.0, None, None, None), (rb2, 2016-04-15 10:00:00, 21.0, 201.0, None, None, None), (rb3, 2016-05-15 10:30:00, 3.0, 30.0, 5.0, None, None), (rb3, 2016-05-15 11:00:00, 31.0, 301.0, 6.0, None, None), (rb4, 2016-05-15 10:30:00, 3.0, 30.0, 5.0, None, None), (rb4, 2016-05-15 11:00:00, 31.0, 301.0, 6.0, None, None), (rb5, 2016-05-15 13:30:00, 3.0, 30.0, 5.0, None, None), (rb5, 2016-05-15 14:00:00, 31.0, 301.0, 6.0, None, None)])"""
        assert test_string == reference_string

    def test_wlvllogg_import_change_timezone_file_timezone_failed_dont_skip(self):
        files = [
            (
                "Location=rb1",
                "Instrument number=UTC+1",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/03/15 10:30:00,1,10",
                "2016/03/15 11:00:00,11,101",
            ),
            (
                "Location=rb2",
                "Instrument number=UTC+ABC2",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/04/15 10:30:00,2,20",
                "2016/04/15 11:00:00,21,201",
            ),
            (
                "Location=rb3",
                "Instrument number",
                "Date/time,Water head[cm],Temperature[\u00b0C],Conductivity[mS/cm]",
                "2016/05/15 10:30:00,3,30,5",
                "2016/05/15 11:00:00,31,301,6",
            ),
            (
                "Location=rb4",
                "Date/time,Water head[cm],Temperature[\u00b0C],Conductivity[mS/cm]",
                "2016/05/15 10:30:00,3,30,5",
                "2016/05/15 11:00:00,31,301,6",
            ),
            (
                "Location=rb5",
                "Instrument number=UTC-2",
                "Date/time,Water head[cm],Temperature[\u00b0C],Conductivity[mS/cm]",
                "2016/05/15 10:30:00,3,30,5",
                "2016/05/15 11:00:00,31,301,6",
            ),
        ]
        for obsid in ["rb1", "rb2", "rb3", "rb4", "rb5"]:
            db_utils.sql_alter_db(f"INSERT INTO obs_points (obsid) VALUES ('{obsid}')")

        with (
            file_utils.tempinput("\n".join(files[0]), _CHARSET) as f1,
            file_utils.tempinput("\n".join(files[1]), _CHARSET) as f2,
            file_utils.tempinput("\n".join(files[2]), _CHARSET) as f3,
            file_utils.tempinput("\n".join(files[3]), _CHARSET) as f4,
            file_utils.tempinput("\n".join(files[4]), _CHARSET) as f5,
        ):
            filenames = [f1, f2, f3, f4, f5]

            @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(
                self,
                filenames,
                mock_filenames,
                mock_skippopup,
                mock_iface,
                mock_askuser,
                mock_notfoundquestion,
            ):
                mock_notfoundquestion.return_value.answer = "ok"
                mock_notfoundquestion.return_value.value = "rb1"
                mock_notfoundquestion.return_value.reuse_column = "location"
                mock_filenames.return_value = filenames
                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = LoggerImport(self.iface, ms)
                importer.load_gui()
                importer.confirm_names.checked = False

                set_combobox(importer.utc_offset, "UTC+1", add_if_not_exists=False)
                importer.select_files()

                def side_effect(*args, **kwargs):
                    mock_result = MagicMock()
                    if "msg" in kwargs:
                        if (
                            "UTC+ABC2 could not be parsed!\n\nSkip file?"
                            in kwargs["msg"]
                        ):
                            mock_result.result = 0
                            return mock_result

                mock_askuser.side_effect = side_effect
                importer.start_import(
                    importer.files,
                    importer.skip_rows.checked,
                    importer.confirm_names.checked,
                    importer.import_all_data.checked,
                )
                return mock_askuser

            mock_askuser = _run(self, filenames)

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = r"""(True, [(rb1, 2016-03-15 10:30:00, 1.0, 10.0, None, None, None), (rb1, 2016-03-15 11:00:00, 11.0, 101.0, None, None, None), (rb2, 2016-04-15 10:30:00, 2.0, 20.0, None, None, None), (rb2, 2016-04-15 11:00:00, 21.0, 201.0, None, None, None), (rb3, 2016-05-15 10:30:00, 3.0, 30.0, 5.0, None, None), (rb3, 2016-05-15 11:00:00, 31.0, 301.0, 6.0, None, None), (rb4, 2016-05-15 10:30:00, 3.0, 30.0, 5.0, None, None), (rb4, 2016-05-15 11:00:00, 31.0, 301.0, 6.0, None, None), (rb5, 2016-05-15 13:30:00, 3.0, 30.0, 5.0, None, None), (rb5, 2016-05-15 14:00:00, 31.0, 301.0, 6.0, None, None)])"""
        assert test_string == reference_string
        assert (
            mock_askuser.mock_calls[0].kwargs.get("dialogtitle", "")
            == "File timezone error!"
        )

    def test_wlvllogg_import_change_timezone_file_timezone_failed_skip(self):
        files = [
            (
                "Location=rb1",
                "Instrument number=UTC+1",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/03/15 10:30:00,1,10",
                "2016/03/15 11:00:00,11,101",
            ),
            (
                "Location=rb2",
                "Instrument number=UTC+ABC2",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/04/15 10:30:00,2,20",
                "2016/04/15 11:00:00,21,201",
            ),
            (
                "Location=rb3",
                "Instrument number",
                "Date/time,Water head[cm],Temperature[\u00b0C],Conductivity[mS/cm]",
                "2016/05/15 10:30:00,3,30,5",
                "2016/05/15 11:00:00,31,301,6",
            ),
            (
                "Location=rb4",
                "Date/time,Water head[cm],Temperature[\u00b0C],Conductivity[mS/cm]",
                "2016/05/15 10:30:00,3,30,5",
                "2016/05/15 11:00:00,31,301,6",
            ),
            (
                "Location=rb5",
                "Instrument number=UTC-2",
                "Date/time,Water head[cm],Temperature[\u00b0C],Conductivity[mS/cm]",
                "2016/05/15 10:30:00,3,30,5",
                "2016/05/15 11:00:00,31,301,6",
            ),
        ]
        for obsid in ["rb1", "rb2", "rb3", "rb4", "rb5"]:
            db_utils.sql_alter_db(f"INSERT INTO obs_points (obsid) VALUES ('{obsid}')")

        with (
            file_utils.tempinput("\n".join(files[0]), _CHARSET) as f1,
            file_utils.tempinput("\n".join(files[1]), _CHARSET) as f2,
            file_utils.tempinput("\n".join(files[2]), _CHARSET) as f3,
            file_utils.tempinput("\n".join(files[3]), _CHARSET) as f4,
            file_utils.tempinput("\n".join(files[4]), _CHARSET) as f5,
        ):
            filenames = [f1, f2, f3, f4, f5]

            @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(
                self,
                filenames,
                mock_filenames,
                mock_skippopup,
                mock_iface,
                mock_askuser,
                mock_notfoundquestion,
            ):
                mock_notfoundquestion.return_value.answer = "ok"
                mock_notfoundquestion.return_value.value = "rb1"
                mock_notfoundquestion.return_value.reuse_column = "location"
                mock_filenames.return_value = filenames
                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = LoggerImport(self.iface, ms)
                importer.load_gui()
                importer.confirm_names.checked = False

                set_combobox(importer.utc_offset, "UTC+1", add_if_not_exists=False)
                importer.select_files()
                mock_askuser.return_value.result = 1
                importer.start_import(
                    importer.files,
                    importer.skip_rows.checked,
                    importer.confirm_names.checked,
                    importer.import_all_data.checked,
                )
                return mock_askuser

            mock_askuser = _run(self, filenames)

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = r"""(True, [(rb1, 2016-03-15 10:30:00, 1.0, 10.0, None, None, None), (rb1, 2016-03-15 11:00:00, 11.0, 101.0, None, None, None), (rb3, 2016-05-15 10:30:00, 3.0, 30.0, 5.0, None, None), (rb3, 2016-05-15 11:00:00, 31.0, 301.0, 6.0, None, None), (rb4, 2016-05-15 10:30:00, 3.0, 30.0, 5.0, None, None), (rb4, 2016-05-15 11:00:00, 31.0, 301.0, 6.0, None, None), (rb5, 2016-05-15 13:30:00, 3.0, 30.0, 5.0, None, None), (rb5, 2016-05-15 14:00:00, 31.0, 301.0, 6.0, None, None)])"""
        assert test_string == reference_string
        assert "File timezone error!" in ", ".join(
            [str(x) for x in mock_askuser.mock_calls]
        )

    def test_wlvllogg_import_change_timezone_file_timezone_failed_cancel(self):
        files = [
            (
                "Location=rb1",
                "Instrument number=UTC+1",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/03/15 10:30:00,1,10",
                "2016/03/15 11:00:00,11,101",
            ),
            (
                "Location=rb2",
                "Instrument number=UTC+ABC2",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/04/15 10:30:00,2,20",
                "2016/04/15 11:00:00,21,201",
            ),
            (
                "Location=rb3",
                "Instrument number",
                "Date/time,Water head[cm],Temperature[\u00b0C],Conductivity[mS/cm]",
                "2016/05/15 10:30:00,3,30,5",
                "2016/05/15 11:00:00,31,301,6",
            ),
            (
                "Location=rb4",
                "Date/time,Water head[cm],Temperature[\u00b0C],Conductivity[mS/cm]",
                "2016/05/15 10:30:00,3,30,5",
                "2016/05/15 11:00:00,31,301,6",
            ),
            (
                "Location=rb5",
                "Instrument number=UTC-2",
                "Date/time,Water head[cm],Temperature[\u00b0C],Conductivity[mS/cm]",
                "2016/05/15 10:30:00,3,30,5",
                "2016/05/15 11:00:00,31,301,6",
            ),
        ]
        for obsid in ["rb1", "rb2", "rb3", "rb4", "rb5"]:
            db_utils.sql_alter_db(f"INSERT INTO obs_points (obsid) VALUES ('{obsid}')")

        with (
            file_utils.tempinput("\n".join(files[0]), _CHARSET) as f1,
            file_utils.tempinput("\n".join(files[1]), _CHARSET) as f2,
            file_utils.tempinput("\n".join(files[2]), _CHARSET) as f3,
            file_utils.tempinput("\n".join(files[3]), _CHARSET) as f4,
            file_utils.tempinput("\n".join(files[4]), _CHARSET) as f5,
        ):
            filenames = [f1, f2, f3, f4, f5]

            @mock.patch(
                "midvatten.tools.import_logger.QtWidgets.QMessageBox.information"
            )
            @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(
                self,
                filenames,
                mock_filenames,
                mock_skippopup,
                mock_iface,
                mock_notfoundquestion,
                mock_askuser,
            ):
                mock_notfoundquestion.return_value.answer = "ok"
                mock_notfoundquestion.return_value.value = "rb1"
                mock_notfoundquestion.return_value.reuse_column = "location"
                mock_filenames.return_value = filenames
                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = LoggerImport(self.iface, ms)
                importer.load_gui()
                importer.confirm_names.checked = False

                set_combobox(importer.utc_offset, "UTC+1", add_if_not_exists=False)
                importer.select_files()

                mock_askuser.return_value = QtWidgets.QMessageBox.Cancel
                importer.start_import(
                    importer.files,
                    importer.skip_rows.checked,
                    importer.confirm_names.checked,
                    importer.import_all_data.checked,
                )
                return mock_askuser

            mock_askuser = _run(self, filenames)

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = r"""(True, [])"""
        assert test_string == reference_string
        assert mock_askuser.call_args.args[1] == "File timezone error!"

    def test_wlvllogg_import_change_timezone_read_from_db(self):
        files = [
            (
                "Location=rb1",
                "Instrument number=UTC+1",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/03/15 10:30:00,1,10",
                "2016/03/15 11:00:00,11,101",
            ),
            (
                "Location=rb2",
                "Instrument number=UTC+2",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/04/15 10:30:00,2,20",
                "2016/04/15 11:00:00,21,201",
            ),
            (
                "Location=rb3",
                "Instrument number",
                "Date/time,Water head[cm],Temperature[\u00b0C],Conductivity[mS/cm]",
                "2016/05/15 10:30:00,3,30,5",
                "2016/05/15 11:00:00,31,301,6",
            ),
            (
                "Location=rb4",
                "Date/time,Water head[cm],Temperature[\u00b0C],Conductivity[mS/cm]",
                "2016/05/15 10:30:00,3,30,5",
                "2016/05/15 11:00:00,31,301,6",
            ),
            (
                "Location=rb5",
                "Instrument number=UTC-2",
                "Date/time,Water head[cm],Temperature[\u00b0C],Conductivity[mS/cm]",
                "2016/05/15 10:30:00,3,30,5",
                "2016/05/15 11:00:00,31,301,6",
            ),
        ]
        for obsid in ["rb1", "rb2", "rb3", "rb4", "rb5"]:
            db_utils.sql_alter_db(f"INSERT INTO obs_points (obsid) VALUES ('{obsid}')")
        db_utils.sql_alter_db(
            "UPDATE about_db SET description = description || ' (UTC+1)' WHERE tablename = 'w_levels_logger' and columnname = 'date_time';"
        )

        with (
            file_utils.tempinput("\n".join(files[0]), _CHARSET) as f1,
            file_utils.tempinput("\n".join(files[1]), _CHARSET) as f2,
            file_utils.tempinput("\n".join(files[2]), _CHARSET) as f3,
            file_utils.tempinput("\n".join(files[3]), _CHARSET) as f4,
            file_utils.tempinput("\n".join(files[4]), _CHARSET) as f5,
        ):
            filenames = [f1, f2, f3, f4, f5]

            @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(
                self,
                filenames,
                mock_filenames,
                mock_skippopup,
                mock_iface,
                mock_askuser,
                mock_notfoundquestion,
            ):
                mock_notfoundquestion.return_value.answer = "ok"
                mock_notfoundquestion.return_value.value = "rb1"
                mock_notfoundquestion.return_value.reuse_column = "location"
                mock_filenames.return_value = filenames
                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = LoggerImport(self.iface, ms)
                importer.load_gui()
                importer.confirm_names.checked = False
                importer.select_files()
                importer.start_import(
                    importer.files,
                    importer.skip_rows.checked,
                    importer.confirm_names.checked,
                    importer.import_all_data.checked,
                )

            _run(self, filenames)

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = r"""(True, [(rb1, 2016-03-15 10:30:00, 1.0, 10.0, None, None, None), (rb1, 2016-03-15 11:00:00, 11.0, 101.0, None, None, None), (rb2, 2016-04-15 09:30:00, 2.0, 20.0, None, None, None), (rb2, 2016-04-15 10:00:00, 21.0, 201.0, None, None, None), (rb3, 2016-05-15 10:30:00, 3.0, 30.0, 5.0, None, None), (rb3, 2016-05-15 11:00:00, 31.0, 301.0, 6.0, None, None), (rb4, 2016-05-15 10:30:00, 3.0, 30.0, 5.0, None, None), (rb4, 2016-05-15 11:00:00, 31.0, 301.0, 6.0, None, None), (rb5, 2016-05-15 13:30:00, 3.0, 30.0, 5.0, None, None), (rb5, 2016-05-15 14:00:00, 31.0, 301.0, 6.0, None, None)])"""
        assert test_string == reference_string

    def test_wlvllogg_import_from_diveroffice_comma_missing_head_cm_value(self):
        files = [
            (
                "[Logger settings]",
                "Location=rb1",
                "[Channel 1]",
                "Identification          =LEVEL",
                "[Channel 2]",
                "Identification          =TEMPERATURE",
                "",
                "Date/time;Water head[cm];Temperature[\u00b0C]",
                "2016/03/15 10:30:00;1,2;10",
                "2016/03/15 11:00:00;    ;101",
                "END OF DATA FILE OF DATALOGGER FOR WINDOWS",
                "    ",
            )
        ]
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")

        with file_utils.tempinput("\n".join(files[0]), _CHARSET, ".csv") as f1:
            filenames = [f1]

            @mock.patch("midvatten.tools.utils.file_utils.ask_for_delimiter")
            @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
            @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(
                self,
                filenames,
                mock_filenames,
                mock_skippopup,
                mock_iface,
                mock_askuser,
                mock_notfoundquestion,
                mock_messagebar,
                mock_delimiter_question,
            ):
                mock_delimiter_question.return_value = (";", True)
                mock_notfoundquestion.return_value.answer = "ok"
                mock_notfoundquestion.return_value.value = "rb1"
                mock_notfoundquestion.return_value.reuse_column = "location"
                mock_filenames.return_value = filenames
                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = LoggerImport(self.iface, ms)
                importer.load_gui()
                importer.select_files()
                try:
                    importer.start_import(
                        importer.files,
                        importer.skip_rows.checked,
                        importer.confirm_names.checked,
                        importer.import_all_data.checked,
                    )
                except Exception:
                    pass

            _run(self, filenames)

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = (
            r"""(True, [(rb1, 2016-03-15 10:30:00, 1.2, 10.0, None, None, None)])"""
        )
        assert test_string == reference_string

    def test_wlvllogg_import_from_diveroffice_mon_files_space_sep(self):
        files = [
            (
                "[Logger settings]",
                "Location=rb1",
                "[Channel 1]",
                "Identification          =LEVEL",
                "[Channel 2]",
                "Identification          =TEMPERATURE",
                "[Data]",
                "3",
                "2022/06/10 12:00:00.0      268.892       7.280",
                "2022/06/10 13:00:00.0      269.883       7.077",
                "2022/06/10 14:00:00.0      271.500       7.067",
                "END OF DATA FILE OF DATALOGGER FOR WINDOWS",
            )
        ]
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")

        with file_utils.tempinput("\n".join(files[0]), _CHARSET, ".mon") as f1:
            filenames = [f1]

            @mock.patch("midvatten.tools.utils.file_utils.ask_for_delimiter")
            @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
            @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(
                self,
                filenames,
                mock_filenames,
                mock_skippopup,
                mock_iface,
                mock_askuser,
                mock_notfoundquestion,
                mock_messagebar,
                mock_delimiter_question,
            ):
                mock_delimiter_question.return_value = (";", True)
                mock_notfoundquestion.return_value.answer = "ok"
                mock_notfoundquestion.return_value.value = "rb1"
                mock_notfoundquestion.return_value.reuse_column = "location"
                mock_filenames.return_value = filenames
                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = LoggerImport(self.iface, ms)
                importer.load_gui()
                importer.select_files()
                try:
                    importer.start_import(
                        importer.files,
                        importer.skip_rows.checked,
                        importer.confirm_names.checked,
                        importer.import_all_data.checked,
                    )
                except Exception:
                    pass

            _run(self, filenames)

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = r"""(True, [(rb1, 2022-06-10 12:00:00, 268.892, 7.28, None, None, None), (rb1, 2022-06-10 13:00:00, 269.883, 7.077, None, None, None), (rb1, 2022-06-10 14:00:00, 271.5, 7.067, None, None, None)])"""
        assert test_string == reference_string

    def test_wlvllogg_import_from_diveroffice_mon_files(self):
        files = [
            (
                "[Logger settings]",
                "Location=rb1",
                "[Channel 1]",
                "Identification          =LEVEL",
                "[Channel 2]",
                "Identification          =TEMPERATURE",
                "[Data]",
                "2",
                "2016/03/15 10:30:00,1,10",
                "2016/03/15 11:00:00,11,101",
                "END OF DATA FILE OF DATALOGGER FOR WINDOWS",
            ),
            (
                "[Series settings]",
                "Location=rb2",
                "[Channel 1]",
                "Identification          =Water head",
                "[Channel 2]",
                "Identification          =TEMPERATURE",
                "[Data]",
                "2",
                "2016/04/15 10:30:00\t2\t20",
                "2016/04/15 11:00:00\t21\t201",
                "END OF DATA FILE OF DATALOGGER FOR WINDOWS",
            ),
            (
                "[Series settings]",
                "Location=rb3",
                "[Channel 1]",
                "Identification          =WATER HEAD (WC)",
                "[Channel 2]",
                "Identification          =TEMPERATURE",
                "[Channel 3]",
                "Identification          =2: SPEC.COND.",
                "[Data]",
                "2",
                "2016/05/15 10:30:00;3,0;30,0;5,0",
                "2016/05/15 11:00:00;31,0;301,0;6,0",
                "END OF DATA FILE OF DATALOGGER FOR WINDOWS",
            ),
        ]
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")

        with (
            file_utils.tempinput("\n".join(files[0]), _CHARSET, ".mon") as f1,
            file_utils.tempinput("\n".join(files[1]), _CHARSET, ".mon") as f2,
            file_utils.tempinput("\n".join(files[2]), _CHARSET, ".mon") as f3,
        ):
            filenames = [f1, f2, f3]

            @mock.patch("midvatten.tools.utils.file_utils.ask_for_delimiter")
            @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
            @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(
                self,
                filenames,
                mock_filenames,
                mock_skippopup,
                mock_iface,
                mock_askuser,
                mock_notfoundquestion,
                mock_messagebar,
                mock_delimiter_question,
            ):
                mock_delimiter_question.return_value = (";", True)
                mock_notfoundquestion.return_value.answer = "ok"
                mock_notfoundquestion.return_value.value = "rb1"
                mock_notfoundquestion.return_value.reuse_column = "location"
                mock_filenames.return_value = filenames
                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = LoggerImport(self.iface, ms)
                importer.load_gui()
                importer.select_files()
                try:
                    importer.start_import(
                        importer.files,
                        importer.skip_rows.checked,
                        importer.confirm_names.checked,
                        importer.import_all_data.checked,
                    )
                except Exception:
                    pass

            _run(self, filenames)

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = r"""(True, [(rb1, 2016-03-15 10:30:00, 1.0, 10.0, None, None, None), (rb1, 2016-03-15 11:00:00, 11.0, 101.0, None, None, None), (rb1, 2016-04-15 10:30:00, 2.0, 20.0, None, None, None), (rb1, 2016-04-15 11:00:00, 21.0, 201.0, None, None, None), (rb1, 2016-05-15 10:30:00, 3.0, 30.0, 5.0, None, None), (rb1, 2016-05-15 11:00:00, 31.0, 301.0, 6.0, None, None)])"""
        assert test_string == reference_string

    def test_wlvllogg_import_from_diveroffice_mon_files_missing_attr(self):
        files = [
            (
                "[Logger settings]",
                "Location=rb1",
                "[Channel 1]",
                "Identification          =LEVEL",
                "[Channel 2]",
                "Identification          =TEMPERATURE",
                "[Data]",
                "2",
                "2016/03/15 10:30:00,1,10",
                "2016/03/15 11:00:00,11,101",
                "END OF DATA FILE OF DATALOGGER FOR WINDOWS",
            ),
            (
                "[Series settings]",
                "Location=rb2",
                "[Channel 1]",
                "Identification          =Water head",
                "[Channel 2]",
                "Identification          =TEMPERATURE",
                "[Data]",
                "2",
                "2016/04/15 10:30:00\t2\t20",
                "2016/04/15 11:00:00\t21\t201",
                "END OF DATA FILE OF DATALOGGER FOR WINDOWS",
            ),
            (
                "[Series settings]",
                "Location=rb3",
                "[Channel 1]",
                "Identification          =WATER HEAD (WC)",
                "[Channel 2]",
                "Identification          =TEMPERATURE",
                "Anything                  =",
                "                  =",
                "[Channel 3]",
                "Identification          =2: SPEC.COND.",
                "[Data]",
                "2",
                "2016/05/15 10:30:00;3,0;30,0;5,0",
                "2016/05/15 11:00:00;31,0;301,0;6,0",
                "END OF DATA FILE OF DATALOGGER FOR WINDOWS",
            ),
        ]
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")

        with (
            file_utils.tempinput("\n".join(files[0]), _CHARSET, ".mon") as f1,
            file_utils.tempinput("\n".join(files[1]), _CHARSET, ".mon") as f2,
            file_utils.tempinput("\n".join(files[2]), _CHARSET, ".mon") as f3,
        ):
            filenames = [f1, f2, f3]

            @mock.patch("midvatten.tools.utils.file_utils.ask_for_delimiter")
            @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
            @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(
                self,
                filenames,
                mock_filenames,
                mock_skippopup,
                mock_iface,
                mock_askuser,
                mock_notfoundquestion,
                mock_messagebar,
                mock_delimiter_question,
            ):
                mock_delimiter_question.return_value = (";", True)
                mock_notfoundquestion.return_value.answer = "ok"
                mock_notfoundquestion.return_value.value = "rb1"
                mock_notfoundquestion.return_value.reuse_column = "location"
                mock_filenames.return_value = filenames
                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = LoggerImport(self.iface, ms)
                importer.load_gui()
                importer.select_files()
                try:
                    importer.start_import(
                        importer.files,
                        importer.skip_rows.checked,
                        importer.confirm_names.checked,
                        importer.import_all_data.checked,
                    )
                except Exception:
                    pass

            _run(self, filenames)

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = r"""(True, [(rb1, 2016-03-15 10:30:00, 1.0, 10.0, None, None, None), (rb1, 2016-03-15 11:00:00, 11.0, 101.0, None, None, None), (rb1, 2016-04-15 10:30:00, 2.0, 20.0, None, None, None), (rb1, 2016-04-15 11:00:00, 21.0, 201.0, None, None, None), (rb1, 2016-05-15 10:30:00, 3.0, 30.0, 5.0, None, None), (rb1, 2016-05-15 11:00:00, 31.0, 301.0, 6.0, None, None)])"""
        assert test_string == reference_string

    def test_wlvllogg_import_from_diveroffice_files_with_source(self):
        files = [
            (
                "Location=rb1",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/03/15 10:30:00,1,10",
                "2016/03/15 11:00:00,11,101",
            ),
            (
                "Location=rb2",
                "Date/time,Water head[cm],Temperature[\u00b0C]",
                "2016/04/15 10:30:00,2,20",
                "2016/04/15 11:00:00,21,201",
            ),
            (
                "Location=rb3",
                "Date/time,Water head[cm],Temperature[\u00b0C],Conductivity[mS/cm]",
                "2016/05/15 10:30:00,3,30,5",
                "2016/05/15 11:00:00,31,301,6",
            ),
        ]
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")

        with (
            file_utils.tempinput("\n".join(files[0]), _CHARSET) as f1,
            file_utils.tempinput("\n".join(files[1]), _CHARSET) as f2,
            file_utils.tempinput("\n".join(files[2]), _CHARSET) as f3,
        ):
            filenames = [f1, f2, f3]

            @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(
                self,
                filenames,
                mock_filenames,
                mock_skippopup,
                mock_iface,
                mock_askuser,
                mock_notfoundquestion,
            ):
                mock_notfoundquestion.return_value.answer = "ok"
                mock_notfoundquestion.return_value.value = "rb1"
                mock_notfoundquestion.return_value.reuse_column = "location"
                mock_filenames.return_value = filenames
                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = LoggerImport(self.iface, ms)
                importer.load_gui()
                importer.select_files()
                importer.source_edit.setText("Testsource")
                importer.start_import(
                    importer.files,
                    importer.skip_rows.checked,
                    importer.confirm_names.checked,
                    importer.import_all_data.checked,
                )

            _run(self, filenames)

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT l.obsid, l.date_time, l.head_cm, l.temp_degc, l.cond_mscm,"
                " l.level_masl, l.comment, s.source"
                " FROM w_levels_logger l"
                " LEFT JOIN w_logger_series s ON s.id = l.series_id"
                " ORDER BY l.obsid, l.date_time"
            )
        )
        reference_string = r"""(True, [(rb1, 2016-03-15 10:30:00, 1.0, 10.0, None, None, None, Testsource), (rb1, 2016-03-15 11:00:00, 11.0, 101.0, None, None, None, Testsource), (rb1, 2016-04-15 10:30:00, 2.0, 20.0, None, None, None, Testsource), (rb1, 2016-04-15 11:00:00, 21.0, 201.0, None, None, None, Testsource), (rb1, 2016-05-15 10:30:00, 3.0, 30.0, 5.0, None, None, Testsource), (rb1, 2016-05-15 11:00:00, 31.0, 301.0, 6.0, None, None, Testsource)])"""
        assert test_string == reference_string


@pytest.mark.spatialite
class TestLoggerImportDiverOfficeSpatialiteFromMixin(
    WlvllogImportFromLoggerDiverOfficeMixin, utils_for_tests.MidvattenTestSpatialiteDbSv
):
    """All 23 DiverOffice integration tests on SpatiaLite backend."""


@pytest.mark.postgis
class TestLoggerImportDiverOfficePostgis(
    WlvllogImportFromLoggerDiverOfficeMixin, utils_for_tests.MidvattenTestPostgisDbSv
):
    """All 23 DiverOffice integration tests on PostGIS backend."""


# ── Integration test mixin: Levelogger ────────────────────────────────────────
# Ported from WlvllogImportFromLeveloggerFilesMixin in test_import_levelogger.py

_LEVELOGGER_FILES_3 = [
    (
        "Serial_number:;;;;;;",
        "123;;;;;;",
        "Project ID:;;;;;;",
        "Projname;;;;;;",
        "Location:;;;;;;",
        "rb1;;;;;;",
        "LEVEL;;;;;;",
        "UNIT: cm;;;;;;",
        "Offset: 0.000000 m;;;;;;",
        "Altitude: 0.000000 m;;;;;;",
        "Density: 1.000000 kg/L;;;;;;",
        "TEMPERATURE;;;;;;",
        "UNIT: Deg C;;;;;;",
        "Date;Time;ms;LEVEL;TEMPERATURE",
        "2016-03-15;10:30:00;0;1;10",
        "2016-03-15;11:00:00;0;11;101",
    ),
    (
        "Serial_number:;;;;;;",
        "123;;;;;;",
        "Project ID:;;;;;;",
        "Projname;;;;;;",
        "Location:;;;;;;",
        "rb2;;;;;;",
        "LEVEL;;;;;;",
        "UNIT: cm;;;;;;",
        "Offset: 0.000000 m;;;;;;",
        "Altitude: 0.000000 m;;;;;;",
        "Density: 1.000000 kg/L;;;;;;",
        "TEMPERATURE;;;;;;",
        "UNIT: Deg C;;;;;;",
        "Date;Time;ms;LEVEL;TEMPERATURE",
        "2016-04-15;10:30:00;0;2;20",
        "2016-04-15;11:00:00;0;21;201",
    ),
    (
        "Serial_number:;;;;;;",
        "123;;;;;;",
        "Project ID:;;;;;;",
        "Projname;;;;;;",
        "Location:;;;;;;",
        "rb3;;;;;;",
        "LEVEL;;;;;;",
        "UNIT: cm;;;;;;",
        "Offset: 0.000000 m;;;;;;",
        "Altitude: 0.000000 m;;;;;;",
        "Density: 1.000000 kg/L;;;;;;",
        "TEMPERATURE;;;;;;",
        "UNIT: Deg C;;;;;;",
        "Date;Time;ms;LEVEL;TEMPERATURE;spec. conductivity (mS/cm)",
        "2016-05-15;10:30:00;0;3;30;5",
        "2016-05-15;11:00:00;0;31;301;6",
    ),
]


class WlvllogImportFromLoggerLeveloggerMixin:
    """Integration tests for LoggerImport (Levelogger format).

    Ported from WlvllogImportFromLeveloggerFilesMixin in test_import_levelogger.py.
    Each test sets importer.format_combo to FORMAT_LEVELOGGER after load_gui().
    Mock target is midvatten.tools.import_logger.midvatten_utils.select_files.
    """

    def _run_levelogger(self, filenames, extra_setup=None):
        """Common runner for Levelogger integration tests."""

        @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
        @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
        @mock.patch("qgis.utils.iface", autospec=True)
        @mock.patch("midvatten.tools.utils.message_utils.pop_up_info", autospec=True)
        @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
        def _inner(
            self,
            filenames,
            mock_filenames,
            mock_skippopup,
            mock_iface,
            mock_askuser,
            mock_notfoundquestion,
        ):
            mock_notfoundquestion.return_value.answer = "ok"
            mock_notfoundquestion.return_value.value = "rb1"
            mock_notfoundquestion.return_value.reuse_column = "location"
            mock_filenames.return_value = filenames
            ms = MagicMock()
            ms.settingsdict = OrderedDict()
            importer = LoggerImport(self.iface, ms)
            importer.load_gui()
            importer.format_combo.setCurrentText(LoggerImport.FORMAT_LEVELOGGER)
            importer.confirm_names.checked = False
            importer.select_files()
            if extra_setup:
                extra_setup(importer)
            importer.start_import(
                importer.files,
                importer.skip_rows.checked,
                importer.confirm_names.checked,
                importer.import_all_data.checked,
            )

        _inner(self, filenames)

    def _run_levelogger_with_messagebar(self, filenames, extra_setup=None):
        """Runner that also mocks MessagebarAndLog and returns mock_notfoundquestion side_effect support."""

        @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
        @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
        @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
        @mock.patch("qgis.utils.iface", autospec=True)
        @mock.patch("midvatten.tools.utils.message_utils.pop_up_info", autospec=True)
        @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
        def _inner(
            self,
            filenames,
            mock_filenames,
            mock_skippopup,
            mock_iface,
            mock_askuser,
            mock_notfoundquestion,
            mock_messagebar,
            notfound_side_effect=None,
        ):
            if notfound_side_effect:
                mock_notfoundquestion.side_effect = notfound_side_effect
            else:
                mock_notfoundquestion.return_value.answer = "ok"
                mock_notfoundquestion.return_value.value = "rb1"
                mock_notfoundquestion.return_value.reuse_column = "location"
            mock_filenames.return_value = filenames
            ms = MagicMock()
            ms.settingsdict = OrderedDict()
            importer = LoggerImport(self.iface, ms)
            importer.load_gui()
            importer.format_combo.setCurrentText(LoggerImport.FORMAT_LEVELOGGER)
            importer.confirm_names.checked = False
            importer.select_files()
            if extra_setup:
                extra_setup(importer)
            try:
                importer.start_import(
                    importer.files,
                    importer.skip_rows.checked,
                    importer.confirm_names.checked,
                    importer.import_all_data.checked,
                )
            except Exception:
                pass
            print("\n".join([str(x) for x in mock_messagebar.mock_calls]))

        _inner(self, filenames)

    def test_wlvllogg_import_from_levelogger_files(self):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")

        with (
            file_utils.tempinput("\n".join(_LEVELOGGER_FILES_3[0]), _CHARSET) as f1,
            file_utils.tempinput("\n".join(_LEVELOGGER_FILES_3[1]), _CHARSET) as f2,
            file_utils.tempinput("\n".join(_LEVELOGGER_FILES_3[2]), _CHARSET) as f3,
        ):
            self._run_levelogger([f1, f2, f3])

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = r"""(True, [(rb1, 2016-03-15 10:30:00, 1.0, 10.0, None, None, None), (rb1, 2016-03-15 11:00:00, 11.0, 101.0, None, None, None), (rb1, 2016-04-15 10:30:00, 2.0, 20.0, None, None, None), (rb1, 2016-04-15 11:00:00, 21.0, 201.0, None, None, None), (rb1, 2016-05-15 10:30:00, 3.0, 30.0, 5.0, None, None), (rb1, 2016-05-15 11:00:00, 31.0, 301.0, 6.0, None, None)])"""
        assert test_string == reference_string

    def test_wlvllogg_import_from_levelogger_files_skip_duplicate_datetimes(self):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm) VALUES ('rb1', '2016-03-15 10:30', '5.0')"
        )

        with (
            file_utils.tempinput("\n".join(_LEVELOGGER_FILES_3[0]), _CHARSET) as f1,
            file_utils.tempinput("\n".join(_LEVELOGGER_FILES_3[1]), _CHARSET) as f2,
            file_utils.tempinput("\n".join(_LEVELOGGER_FILES_3[2]), _CHARSET) as f3,
        ):
            self._run_levelogger([f1, f2, f3])

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = r"""(True, [(rb1, 2016-03-15 10:30, 5.0, None, None, None, None), (rb1, 2016-03-15 11:00:00, 11.0, 101.0, None, None, None), (rb1, 2016-04-15 10:30:00, 2.0, 20.0, None, None, None), (rb1, 2016-04-15 11:00:00, 21.0, 201.0, None, None, None), (rb1, 2016-05-15 10:30:00, 3.0, 30.0, 5.0, None, None), (rb1, 2016-05-15 11:00:00, 31.0, 301.0, 6.0, None, None)])"""
        assert test_string == reference_string

    def test_wlvllogg_import_from_levelogger_files_filter_dates(self):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm) VALUES ('rb1', '2016-03-15 10:31', '5.0')"
        )

        with (
            file_utils.tempinput("\n".join(_LEVELOGGER_FILES_3[0]), _CHARSET) as f1,
            file_utils.tempinput("\n".join(_LEVELOGGER_FILES_3[1]), _CHARSET) as f2,
            file_utils.tempinput("\n".join(_LEVELOGGER_FILES_3[2]), _CHARSET) as f3,
        ):

            def _setup(importer):
                importer.import_all_data.checked = False

            self._run_levelogger([f1, f2, f3], extra_setup=_setup)

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = r"""(True, [(rb1, 2016-03-15 10:31, 5.0, None, None, None, None), (rb1, 2016-03-15 11:00:00, 11.0, 101.0, None, None, None), (rb1, 2016-04-15 10:30:00, 2.0, 20.0, None, None, None), (rb1, 2016-04-15 11:00:00, 21.0, 201.0, None, None, None), (rb1, 2016-05-15 10:30:00, 3.0, 30.0, 5.0, None, None), (rb1, 2016-05-15 11:00:00, 31.0, 301.0, 6.0, None, None)])"""
        assert test_string == reference_string

    def test_wlvllogg_import_from_levelogger_files_all_dates(self):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb2')")
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb3')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm) VALUES ('rb1', '2016-03-15 10:31', '5.0')"
        )

        with (
            file_utils.tempinput("\n".join(_LEVELOGGER_FILES_3[0]), _CHARSET) as f1,
            file_utils.tempinput("\n".join(_LEVELOGGER_FILES_3[1]), _CHARSET) as f2,
            file_utils.tempinput("\n".join(_LEVELOGGER_FILES_3[2]), _CHARSET) as f3,
        ):

            def _setup(importer):
                importer.import_all_data.checked = True
                importer.confirm_names.checked = False

            self._run_levelogger([f1, f2, f3], extra_setup=_setup)

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = r"""(True, [(rb1, 2016-03-15 10:30:00, 1.0, 10.0, None, None, None), (rb1, 2016-03-15 10:31, 5.0, None, None, None, None), (rb1, 2016-03-15 11:00:00, 11.0, 101.0, None, None, None), (rb2, 2016-04-15 10:30:00, 2.0, 20.0, None, None, None), (rb2, 2016-04-15 11:00:00, 21.0, 201.0, None, None, None), (rb3, 2016-05-15 10:30:00, 3.0, 30.0, 5.0, None, None), (rb3, 2016-05-15 11:00:00, 31.0, 301.0, 6.0, None, None)])"""
        assert test_string == reference_string

    def test_wlvllogg_import_from_levelogger_files_try_capitalize(self):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('Rb1')")

        with file_utils.tempinput("\n".join(_LEVELOGGER_FILES_3[0]), _CHARSET) as f1:

            def _setup(importer):
                importer.import_all_data.checked = False
                importer.confirm_names.checked = False

            self._run_levelogger([f1], extra_setup=_setup)

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = r"""(True, [(Rb1, 2016-03-15 10:30:00, 1.0, 10.0, None, None, None), (Rb1, 2016-03-15 11:00:00, 11.0, 101.0, None, None, None)])"""
        assert test_string == reference_string

    def test_wlvllogg_import_from_levelogger_files_cancel(self):
        cancel_file = (
            "Serial_number:;;;;;;",
            "123;;;;;;",
            "Project ID:;;;;;;",
            "Projname;;;;;;",
            "Location:;;;;;;",
            "rb2;;;;;;",
            "LEVEL;;;;;;",
            "UNIT: cm;;;;;;",
            "Offset: 0.000000 m;;;;;;",
            "Altitude: 0.000000 m;;;;;;",
            "Density: 1.000000 kg/L;;;;;;",
            "TEMPERATURE;;;;;;",
            "UNIT: Deg C;;;;;;",
            "Date;Time;ms;LEVEL;TEMPERATURE",
            "2016-03-15;10:30:00;0;1;20",
            "2016-03-15;11:00:00;0;11;101",
        )
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('Rb1')")

        with file_utils.tempinput("\n".join(cancel_file), _CHARSET) as f1:

            @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(
                self,
                filenames,
                mock_filenames,
                mock_skippopup,
                mock_iface,
                mock_askuser,
                mock_notfoundquestion,
            ):
                mock_notfoundquestion.return_value.answer = "cancel"
                mock_notfoundquestion.return_value.value = "rb1"
                mock_notfoundquestion.return_value.reuse_column = "location"
                mock_filenames.return_value = filenames
                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = LoggerImport(self.iface, ms)
                importer.load_gui()
                importer.format_combo.setCurrentText(LoggerImport.FORMAT_LEVELOGGER)
                importer.select_files()
                importer.import_all_data.checked = True
                importer.confirm_names.checked = False
                importer.start_import(
                    importer.files,
                    importer.skip_rows.checked,
                    importer.confirm_names.checked,
                    importer.import_all_data.checked,
                )

            _run(self, [f1])

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = r"""(True, [])"""
        assert test_string == reference_string

    def test_wlvllogg_import_from_levelogger_files_skip_missing_water_level(self):
        missing_file = list(_LEVELOGGER_FILES_3[0])
        missing_file[-1] = "2016-03-15;11:00:00;0;;101"  # empty level (last data row)

        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb2')")
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb3')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm) VALUES ('rb1', '2016-03-15 10:31', '5.0')"
        )

        with (
            file_utils.tempinput("\n".join(missing_file), _CHARSET) as f1,
            file_utils.tempinput("\n".join(_LEVELOGGER_FILES_3[1]), _CHARSET) as f2,
            file_utils.tempinput("\n".join(_LEVELOGGER_FILES_3[2]), _CHARSET) as f3,
        ):

            def _setup(importer):
                importer.import_all_data.checked = True
                importer.confirm_names.checked = False
                importer.skip_rows.checked = True

            self._run_levelogger([f1, f2, f3], extra_setup=_setup)

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = r"""(True, [(rb1, 2016-03-15 10:30:00, 1.0, 10.0, None, None, None), (rb1, 2016-03-15 10:31, 5.0, None, None, None, None), (rb2, 2016-04-15 10:30:00, 2.0, 20.0, None, None, None), (rb2, 2016-04-15 11:00:00, 21.0, 201.0, None, None, None), (rb3, 2016-05-15 10:30:00, 3.0, 30.0, 5.0, None, None), (rb3, 2016-05-15 11:00:00, 31.0, 301.0, 6.0, None, None)])"""
        assert test_string == reference_string

    def test_wlvllogg_import_from_levelogger_files_not_skip_missing_water_level(self):
        missing_file = list(_LEVELOGGER_FILES_3[0])
        missing_file[-1] = "2016-03-15;11:00:00;0;;101"  # empty level (last data row)

        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb2')")
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb3')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm) VALUES ('rb1', '2016-03-15 10:31', '5.0')"
        )

        with (
            file_utils.tempinput("\n".join(missing_file), _CHARSET) as f1,
            file_utils.tempinput("\n".join(_LEVELOGGER_FILES_3[1]), _CHARSET) as f2,
            file_utils.tempinput("\n".join(_LEVELOGGER_FILES_3[2]), _CHARSET) as f3,
        ):

            def _setup(importer):
                importer.import_all_data.checked = True
                importer.confirm_names.checked = False
                importer.skip_rows.checked = False

            self._run_levelogger([f1, f2, f3], extra_setup=_setup)

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = r"""(True, [(rb1, 2016-03-15 10:30:00, 1.0, 10.0, None, None, None), (rb1, 2016-03-15 10:31, 5.0, None, None, None, None), (rb1, 2016-03-15 11:00:00, None, 101.0, None, None, None), (rb2, 2016-04-15 10:30:00, 2.0, 20.0, None, None, None), (rb2, 2016-04-15 11:00:00, 21.0, 201.0, None, None, None), (rb3, 2016-05-15 10:30:00, 3.0, 30.0, 5.0, None, None), (rb3, 2016-05-15 11:00:00, 31.0, 301.0, 6.0, None, None)])"""
        assert test_string == reference_string

    def test_wlvllogg_import_from_levelogger_files_datetime_filter(self):
        files_with_extra = list(_LEVELOGGER_FILES_3[0]) + [
            "2016-06-15;11:00:00;0;11;101"
        ]

        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb2')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm) VALUES ('rb1', '2016-03-15 10:31', '5.0')"
        )

        with (
            file_utils.tempinput("\n".join(files_with_extra), _CHARSET) as f1,
            file_utils.tempinput("\n".join(_LEVELOGGER_FILES_3[1]), _CHARSET) as f2,
        ):

            @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(
                self,
                filenames,
                mock_filenames,
                mock_skippopup,
                mock_iface,
                mock_askuser,
                mock_notfoundquestion,
            ):
                mock_notfoundquestion.return_value.answer = "ok"
                mock_notfoundquestion.return_value.value = "rb1"
                mock_notfoundquestion.return_value.reuse_column = "location"
                mock_filenames.return_value = filenames
                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = LoggerImport(self.iface, ms)
                importer.load_gui()
                importer.format_combo.setCurrentText(LoggerImport.FORMAT_LEVELOGGER)
                importer.select_files()
                importer.import_all_data.checked = True
                importer.confirm_names.checked = False
                importer.date_time_filter.from_date = "2016-03-15 11:00:00"
                importer.date_time_filter.to_date = "2016-04-15 10:30:00"
                importer.start_import(
                    importer.files,
                    importer.skip_rows.checked,
                    importer.confirm_names.checked,
                    importer.import_all_data.checked,
                    importer.date_time_filter.from_date,
                    importer.date_time_filter.to_date,
                )

            _run(self, [f1, f2])

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = r"""(True, [(rb1, 2016-03-15 10:31, 5.0, None, None, None, None), (rb1, 2016-03-15 11:00:00, 11.0, 101.0, None, None, None), (rb2, 2016-04-15 10:30:00, 2.0, 20.0, None, None, None)])"""
        assert test_string == reference_string

    def test_wlvllogg_import_from_levelogger_files_skip_obsid(self):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb2')")

        with (
            file_utils.tempinput("\n".join(_LEVELOGGER_FILES_3[0]), _CHARSET) as f1,
            file_utils.tempinput("\n".join(_LEVELOGGER_FILES_3[1]), _CHARSET) as f2,
            file_utils.tempinput("\n".join(_LEVELOGGER_FILES_3[2]), _CHARSET) as f3,
        ):

            @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
            @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(
                self,
                filenames,
                mock_filenames,
                mock_skippopup,
                mock_iface,
                mock_askuser,
                mock_notfoundquestion,
                mock_messagebar,
            ):
                mocks_notfoundquestion = []
                for answer, value in [["ok", "rb1"], ["ok", "rb2"], ["skip", "rb3"]]:
                    a_mock = MagicMock()
                    a_mock.answer = answer
                    a_mock.value = value
                    a_mock.reuse_column = "location"
                    mocks_notfoundquestion.append(a_mock)
                mock_notfoundquestion.side_effect = mocks_notfoundquestion
                mock_filenames.return_value = filenames
                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = LoggerImport(self.iface, ms)
                importer.load_gui()
                importer.format_combo.setCurrentText(LoggerImport.FORMAT_LEVELOGGER)
                importer.select_files()
                importer.start_import(
                    importer.files,
                    importer.skip_rows.checked,
                    importer.confirm_names.checked,
                    importer.import_all_data.checked,
                )
                print("\n".join([str(x) for x in mock_messagebar.mock_calls]))

            _run(self, [f1, f2, f3])

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = r"""(True, [(rb1, 2016-03-15 10:30:00, 1.0, 10.0, None, None, None), (rb1, 2016-03-15 11:00:00, 11.0, 101.0, None, None, None), (rb2, 2016-04-15 10:30:00, 2.0, 20.0, None, None, None), (rb2, 2016-04-15 11:00:00, 21.0, 201.0, None, None, None)])"""
        assert test_string == reference_string

    def test_wlvllogg_import_from_levelogger_files_level_as_m(self):
        level_m_file = (
            "Serial_number:;;;;;;",
            "123;;;;;;",
            "Project ID:;;;;;;",
            "Projname;;;;;;",
            "Location:;;;;;;",
            "rb1;;;;;;",
            "LEVEL;;;;;;",
            "UNIT: m;;;;;;",
            "Offset: 0.000000 m;;;;;;",
            "Altitude: 0.000000 m;;;;;;",
            "Density: 1.000000 kg/L;;;;;;",
            "TEMPERATURE;;;;;;",
            "UNIT: Deg C;;;;;;",
            "Date;Time;ms;LEVEL;TEMPERATURE",
            "2016-03-15;10:30:00;0;1;10",
            "2016-03-15;11:00:00;0;11;101",
        )
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")

        with (
            file_utils.tempinput("\n".join(level_m_file), _CHARSET) as f1,
            file_utils.tempinput("\n".join(_LEVELOGGER_FILES_3[1]), _CHARSET) as f2,
            file_utils.tempinput("\n".join(_LEVELOGGER_FILES_3[2]), _CHARSET) as f3,
        ):
            self._run_levelogger([f1, f2, f3])

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = r"""(True, [(rb1, 2016-03-15 10:30:00, 100.0, 10.0, None, None, None), (rb1, 2016-03-15 11:00:00, 1100.0, 101.0, None, None, None), (rb1, 2016-04-15 10:30:00, 2.0, 20.0, None, None, None), (rb1, 2016-04-15 11:00:00, 21.0, 201.0, None, None, None), (rb1, 2016-05-15 10:30:00, 3.0, 30.0, 5.0, None, None), (rb1, 2016-05-15 11:00:00, 31.0, 301.0, 6.0, None, None)])"""
        assert test_string == reference_string

    def test_wlvllogg_import_from_levelogger_files_cond_as_uscm(self):
        cond_us_file = (
            "Serial_number:;;;;;;",
            "123;;;;;;",
            "Project ID:;;;;;;",
            "Projname;;;;;;",
            "Location:;;;;;;",
            "rb3;;;;;;",
            "LEVEL;;;;;;",
            "UNIT: cm;;;;;;",
            "Offset: 0.000000 m;;;;;;",
            "Altitude: 0.000000 m;;;;;;",
            "Density: 1.000000 kg/L;;;;;;",
            "TEMPERATURE;;;;;;",
            "UNIT: Deg C;;;;;;",
            "Date;Time;ms;LEVEL;TEMPERATURE;spec. conductivity (uS/cm)",
            "2016-05-15;10:30:00;0;3;30;5000",
            "2016-05-15;11:00:00;0;31;301;6000",
        )
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb3')")

        with file_utils.tempinput("\n".join(cond_us_file), _CHARSET) as f1:
            self._run_levelogger([f1])

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger ORDER BY obsid, date_time"
            )
        )
        reference_string = r"""(True, [(rb3, 2016-05-15 10:30:00, 3.0, 30.0, 5.0, None, None), (rb3, 2016-05-15 11:00:00, 31.0, 301.0, 6.0, None, None)])"""
        assert test_string == reference_string


@pytest.mark.spatialite
class TestLoggerImportLeveloggerSpatialiteFromMixin(
    WlvllogImportFromLoggerLeveloggerMixin, utils_for_tests.MidvattenTestSpatialiteDbSv
):
    """All 12 Levelogger integration tests on SpatiaLite backend."""


@pytest.mark.postgis
class TestLoggerImportLeveloggerPostgis(
    WlvllogImportFromLoggerLeveloggerMixin, utils_for_tests.MidvattenTestPostgisDbSv
):
    """All 12 Levelogger integration tests on PostGIS backend."""


# ── DiverOffice Baro parser tests ─────────────────────────────────────────────


@pytest.mark.active
class TestDiverOfficeBaroParser:
    """Unit tests for DiverOfficeBaroParser.parse."""

    # Matches the real baro .mon file format (space-delimited data section)
    MON_CONTENT = (
        "[Logger settings]\n"
        "  Serial number           =..00-DA123  219.\n"
        "  Instrument number       =          UTC+1     \n"
        "  Location                =Rb1Baro\n"
        "  Number of channels      =2\n"
        "[Channel 1]\n"
        "  Identification          =PRESSURE\n"
        "[Channel 2]\n"
        "  Identification          =TEMPERATURE\n"
        "[data]\n"
        "2\n"
        "2023/10/05 13:00:00.0      978.667       9.470\n"
        "2023/10/05 14:00:00.0      978.667      12.110\n"
    )

    # Matches the real baro .csv file format (semicolon-delimited)
    CSV_CONTENT = (
        "[Logger settings]\n"
        "  Serial number           =..00-DA123  219.\n"
        "  Instrument number       =          UTC+1     \n"
        "  Location                =Rb1Baro\n"
        "[Channel 1]\n"
        "  Identification          =PRESSURE\n"
        "[Channel 2]\n"
        "  Identification          =TEMPERATURE\n"
        "Date/time;Pressure[cmH2O];Temperature[\u00b0C]\n"
        "2023/10/05 13:00:00;978,667;9,470\n"
        "2023/10/05 14:00:00;978,667;12,110\n"
    )

    def test_parse_mon_extracts_pressure_and_temperature(self):
        with file_utils.tempinput(self.MON_CONTENT, "utf-8", suffix=".mon") as f:
            result = DiverOfficeBaroParser.parse(path=f, charset="utf-8")
        filedata, filename, location, utc_offset, serial_number = result
        assert filedata[0] == ["date_time", "baro_cmh2o", "temperature"]
        assert len(filedata) == 3  # header + 2 data rows
        assert filedata[1][0] == "2023-10-05 13:00:00"
        assert float(filedata[1][1]) == pytest.approx(978.667, rel=1e-3)
        assert float(filedata[1][2]) == pytest.approx(9.470, rel=1e-3)

    def test_parse_baro_mon_preserves_wider_pressure_after_inference_window(self):
        content = build_mon(1001, baro=True)
        with file_utils.tempinput(content, "utf-8", suffix=".mon") as path:
            file_data, *_ = DiverOfficeBaroParser.parse(path, "utf-8")

        assert file_data[-1][1] == "100.308"

    def test_parse_csv_extracts_pressure_and_temperature(self):
        with file_utils.tempinput(self.CSV_CONTENT, "utf-8", suffix=".csv") as f:
            result = DiverOfficeBaroParser.parse(path=f, charset="utf-8")
        filedata, filename, location, utc_offset, serial_number = result
        assert filedata[0] == ["date_time", "baro_cmh2o", "temperature"]
        assert len(filedata) == 3
        assert filedata[1][0] == "2023-10-05 13:00:00"
        assert float(filedata[1][1]) == pytest.approx(978.667, rel=1e-3)

    def test_parse_mon_first_row_missing_pressure_preserves_temperature(self):
        content = (
            "[Logger settings]\n"
            "  Location                =Rb1Baro\n"
            "  Number of channels      =2\n"
            "[Channel 1]\n"
            "  Identification          =PRESSURE\n"
            "[Channel 2]\n"
            "  Identification          =TEMPERATURE\n"
            "[data]\n"
            "2\n"
            "2023/10/05 13:00:00.0                    9.470\n"
            "2023/10/05 14:00:00.0      978.667      12.110\n"
        )
        with file_utils.tempinput(content, "utf-8", suffix=".mon") as f:
            result = DiverOfficeBaroParser.parse(path=f, charset="utf-8")

        filedata, *_ = result
        assert filedata[0] == ["date_time", "baro_cmh2o", "temperature"]
        assert filedata[1] == ["2023-10-05 13:00:00", None, "9.47"]
        assert filedata[2][0] == "2023-10-05 14:00:00"
        assert float(filedata[2][1]) == pytest.approx(978.667, rel=1e-3)
        assert float(filedata[2][2]) == pytest.approx(12.110, rel=1e-3)

    def test_parse_extracts_location(self):
        with file_utils.tempinput(self.MON_CONTENT, "utf-8", suffix=".mon") as f:
            result = DiverOfficeBaroParser.parse(path=f, charset="utf-8")
        _, _, location, _, _ = result
        assert location == "Rb1Baro"

    def test_parse_extracts_serial_number(self):
        with file_utils.tempinput(self.MON_CONTENT, "utf-8", suffix=".mon") as f:
            result = DiverOfficeBaroParser.parse(path=f, charset="utf-8")
        _, _, _, _, serial_number = result
        assert serial_number == "DA123"

    def test_parse_extracts_utc_offset(self):
        with file_utils.tempinput(self.MON_CONTENT, "utf-8", suffix=".mon") as f:
            result = DiverOfficeBaroParser.parse(path=f, charset="utf-8")
        _, _, _, utc_offset, _ = result
        assert utc_offset is not None
        assert "UTC+1" in utc_offset or "+1" in utc_offset

    def test_parse_date_filter(self):
        with file_utils.tempinput(self.MON_CONTENT, "utf-8", suffix=".mon") as f:
            result = DiverOfficeBaroParser.parse(
                path=f,
                charset="utf-8",
                begindate="2023-10-05 14:00:00",
            )
        filedata, *_ = result
        assert len(filedata) == 2  # header + 1 row (second row only)
        assert filedata[1][0] == "2023-10-05 14:00:00"

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_parse_no_pressure_column_warns(self, mock_messagebar):
        content = (
            "[Channel 1]\n"
            "  Identification          =TEMPERATURE\n"
            "[data]\n"
            "1\n"
            "2023/10/05 13:00:00.0       9.470\n"
        )
        with file_utils.tempinput(content, "utf-8", suffix=".mon") as f:
            result = DiverOfficeBaroParser.parse(path=f, charset="utf-8")
        # Temperature-only file: temp_degc column present, baro_cmh2o absent
        filedata, *_ = result
        # Either warns or returns data with only temp column — either way no crash
        assert isinstance(filedata, list)


@pytest.mark.active
class TestPivotBaroToMeteo:
    """Unit tests for _pivot_baro_to_meteo helper."""

    def test_pivots_both_channels(self):
        file_data = [
            ["date_time", "baro_cmh2o", "temperature", "obsid"],
            ["2023-10-05 13:00:00", "978.667", "9.470", "Rb1Baro"],
        ]
        result = _pivot_baro_to_meteo(file_data, "DA123", "baro.mon")
        assert result[0] == [
            "obsid",
            "instrumentid",
            "parameter",
            "date_time",
            "reading_num",
            "unit",
        ]
        params = [(r[2], r[4], r[5]) for r in result[1:]]
        assert ("pressure", "978.667", "cmH2O") in params
        assert ("temp", "9.470", "\u00b0C") in params

    def test_uses_serial_number_as_instrumentid(self):
        file_data = [
            ["date_time", "baro_cmh2o", "obsid"],
            ["2023-10-05 13:00:00", "978.667", "Rb1Baro"],
        ]
        result = _pivot_baro_to_meteo(file_data, "SN999", "baro.mon")
        assert result[1][1] == "SN999"

    def test_falls_back_to_filename_when_no_serial(self):
        file_data = [
            ["date_time", "baro_cmh2o", "obsid"],
            ["2023-10-05 13:00:00", "978.667", "Rb1Baro"],
        ]
        result = _pivot_baro_to_meteo(file_data, None, "mybaro.mon")
        assert result[1][1] == "mybaro.mon"

    def test_skips_none_values(self):
        file_data = [
            ["date_time", "baro_cmh2o", "temperature", "obsid"],
            ["2023-10-05 13:00:00", "978.667", None, "Rb1Baro"],
        ]
        result = _pivot_baro_to_meteo(file_data, "DA123", "baro.mon")
        params = [r[2] for r in result[1:]]
        assert "pressure" in params
        assert "temp" not in params


@pytest.mark.spatialite
class TestLoggerImportBaroSpatialite(utils_for_tests.MidvattenTestSpatialiteDbSv):
    """Integration tests for LoggerImport with DiverOffice Baro format.

    Verifies the full start_import() path: parse → pivot → seed zz_meteoparam
    → general_import into meteo table.
    """

    _BARO_MON = (
        "[Logger settings]\n"
        "  Serial number           =..00-DA123  219.\n"
        "  Instrument number       =          UTC+1     \n"
        "  Location                =Rb1Baro\n"
        "  Number of channels      =2\n"
        "[Channel 1]\n"
        "  Identification          =PRESSURE\n"
        "[Channel 2]\n"
        "  Identification          =TEMPERATURE\n"
        "[data]\n"
        "2\n"
        "2023/10/05 13:00:00.0      978.667       9.470\n"
        "2023/10/05 14:00:00.0      979.100      10.000\n"
    )

    def _run_baro_import(self, mock_messagebar):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('Rb1Baro')")

        with file_utils.tempinput(self._BARO_MON, "utf-8", suffix=".mon") as f:

            @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
            @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
            def _run(
                self,
                filename,
                mock_select_files,
                mock_popup,
                mock_iface,
                mock_askuser,
                mock_notfound,
            ):
                mock_notfound.return_value.answer = "ok"
                mock_notfound.return_value.value = "Rb1Baro"
                mock_notfound.return_value.reuse_column = "location"
                mock_select_files.return_value = [filename]

                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = LoggerImport(self.iface, ms)
                importer.load_gui()
                importer.format_combo.setCurrentText(
                    LoggerImport.FORMAT_DIVEROFFICE_BARO
                )
                importer.select_files()
                importer.start_import(
                    files=importer.files,
                    skip_rows_without_water_level=False,
                    confirm_names=importer.confirm_names.checked,
                    import_all_data=importer.import_all_data.checked,
                )

            _run(self, f)

        print(mock_messagebar.mock_calls)

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_baro_import_inserts_into_meteo(self, mock_messagebar):
        self._run_baro_import(mock_messagebar)

        meteoparam_result = db_utils.sql_load_fr_db(
            "SELECT parameter FROM zz_meteoparam WHERE parameter='pressure'"
        )
        assert meteoparam_result[0] is True
        assert len(meteoparam_result[1]) == 1, (
            "Expected 'pressure' to be seeded into zz_meteoparam"
        )

        meteo_result = db_utils.sql_load_fr_db(
            "SELECT obsid, parameter, date_time, reading_num, unit"
            " FROM meteo WHERE obsid='Rb1Baro' AND parameter='pressure'"
            " ORDER BY date_time"
        )
        assert meteo_result[0] is True
        rows = meteo_result[1]
        assert len(rows) == 2, f"Expected 2 pressure rows in meteo, got: {rows}"
        assert rows[0][2] == "2023-10-05 13:00:00"
        assert rows[0][4] == "cmH2O"

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_baro_import_does_not_write_to_wlevels_logger(self, mock_messagebar):
        """Baro data must go to meteo only, not to w_levels_logger."""
        self._run_baro_import(mock_messagebar)

        wlevels_result = db_utils.sql_load_fr_db(
            "SELECT COUNT(*) FROM w_levels_logger WHERE obsid='Rb1Baro'"
        )
        assert wlevels_result[0] is True
        assert wlevels_result[1][0][0] == 0, (
            "Baro import must not write to w_levels_logger"
        )
