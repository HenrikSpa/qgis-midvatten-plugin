"""Tests for the unified typed-DataFrame LoggerImport tool."""

from __future__ import annotations

import locale
import os
from collections import OrderedDict
from datetime import datetime, timedelta
from unittest import mock
from unittest.mock import MagicMock

import pandas as pd
import pytest
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import Qt

from midvatten.test import utils_for_tests
from midvatten.test.mocks_for_tests import MockReturnUsingDictIn
from midvatten.tools import import_data_to_db
from midvatten.tools.import_logger import (
    CANONICAL_COLUMNS,
    DiverOfficeBaroParser,
    DiverOfficeParseError,
    DiverOfficeParser,
    HoboParser,
    LeveloggerParser,
    LoggerDataKind,
    LoggerImport,
    LoggerImportOptions,
    TzConverter,
)
from midvatten.tools.import_logger.parsers import (
    FileError,
    fix_date,
    _coerce_numeric_column,
    _first_metadata_value,
    _IncompleteMonLayoutError,
    _SourceLine,
)
from midvatten.tools.import_logger.importer import (
    LoggerImportSummary,
    logger_schema_capabilities,
)
from midvatten.tools.import_logger.models import (
    BARO_METEO_PARAMS,
    METEO_TABLE,
    WATER_LEVEL_TABLE,
    LoggerParseBatchResult,
    ParsedLoggerFile,
)
from midvatten.tools.import_logger.pipeline import run_pre_resolution_pipeline
from midvatten.tools.utils import db_utils, file_utils
from midvatten.tools.utils.date_utils import to_date
from midvatten.tools.utils.gui_utils import set_combobox
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


def make_diveroffice_csv(
    channels: list[str],
    header_columns: list[str],
    declared_count: str | None = None,
) -> str:
    """Build a minimal DiverOffice .csv with a metadata block and one data row.

    The header row is always line ``3 + 2 * len(channels) + 1``.
    """
    lines = [
        "[Logger settings]",
        "  Location=rb1",
        f"  Number of channels={declared_count or len(channels)}",
    ]
    for channel, name in enumerate(channels, 1):
        lines.extend([f"[Channel {channel}]", f"  Identification={name}"])
    lines.append(";".join(header_columns))
    lines.append(
        ";".join(["2025/01/01 00:00:00"] + ["1.0"] * (len(header_columns) - 1))
    )
    return "\n".join(lines) + "\n"


def assert_canonical(parsed) -> None:
    assert tuple(parsed.data.columns) == CANONICAL_COLUMNS
    assert str(parsed.data["date_time"].dtype) == "datetime64[ns]"
    assert all(
        pd.api.types.is_numeric_dtype(parsed.data[column])
        for column in CANONICAL_COLUMNS[1:]
    )
    assert parsed.data.index.equals(pd.RangeIndex(len(parsed.data)))


def replace_with_legacy_logger_schema(*, source_column: bool) -> None:
    """Replace current logger tables with an isolated legacy table shape."""
    db_utils.sql_alter_db("DROP TABLE w_levels_logger")
    db_utils.sql_alter_db("DROP TABLE w_logger_series")
    source_definition = ", source text" if source_column else ""
    db_utils.sql_alter_db(
        "CREATE TABLE w_levels_logger ("
        "obsid text NOT NULL, date_time text NOT NULL, head_cm double, "
        "temp_degc double, cond_mscm double, level_masl double, comment text"
        f"{source_definition}, PRIMARY KEY (obsid, date_time), "
        "FOREIGN KEY(obsid) REFERENCES obs_points(obsid) "
        "ON UPDATE CASCADE ON DELETE CASCADE)"
    )


def test_logger_schema_capabilities_cover_all_supported_shapes() -> None:
    oldest = logger_schema_capabilities(["obsid", "date_time"])
    assert not oldest.has_series_id
    assert not oldest.has_created_at
    assert not oldest.has_source_column

    source_column = logger_schema_capabilities(["obsid", "date_time", "source"])
    assert source_column.has_source_column
    assert not source_column.has_series_id

    current = logger_schema_capabilities(
        ["obsid", "date_time", "series_id", "created_at"]
    )
    assert current.has_series_id
    assert current.has_created_at
    assert not current.has_source_column


class TestTimezoneErrorPromptImportsAnyway:
    """The timezone-conversion prompt offers 'import anyway', not 'skip'.

    Users routinely want the data even when the UTC offset can't be read, so
    the default action must keep the file (Yes = import anyway; No = skip;
    Cancel = abort the whole import, handled inside Askuser).
    ``_accept_parsed_files`` touches no ``self`` state, so it is exercised
    directly on a bare object.
    """

    @staticmethod
    def _parsed_with_tz_error() -> ParsedLoggerFile:
        return ParsedLoggerFile(
            data=pd.DataFrame(
                {"date_time": ["2020-01-01 00:00:00"], "head_cm": [1.0]}
            ),
            filename="logger.csv",
            source_path="/tmp/logger.csv",
            kind=LoggerDataKind.WATER_LEVEL,
            location="rb1",
            serial_number=None,
            timezone_error="could not read UTC offset",
        )

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    @mock.patch("midvatten.tools.import_logger.importer.dialog_utils.Askuser")
    def test_yes_imports_file_anyway(self, mock_askuser, mock_messagebar):
        mock_askuser.return_value.result = 1  # Yes = import anyway
        parsed = self._parsed_with_tz_error()
        summary = LoggerImportSummary()

        kept = LoggerImport._accept_parsed_files(
            object(), LoggerParseBatchResult([parsed], []), summary
        )

        print(mock_messagebar.mock_calls)
        assert kept == [parsed]
        assert summary.skipped == []
        msg = mock_askuser.call_args.kwargs["msg"]
        assert "anyway" in msg.lower()
        assert "skip file?" not in msg.lower()

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    @mock.patch("midvatten.tools.import_logger.importer.dialog_utils.Askuser")
    def test_no_skips_file(self, mock_askuser, mock_messagebar):
        mock_askuser.return_value.result = 0  # No = skip
        parsed = self._parsed_with_tz_error()
        summary = LoggerImportSummary()

        kept = LoggerImport._accept_parsed_files(
            object(), LoggerParseBatchResult([parsed], []), summary
        )

        print(mock_messagebar.mock_calls)
        assert kept == []
        assert summary.skipped == ["/tmp/logger.csv"]


@pytest.mark.active
class TestDiverOfficeParser:
    def test_parse_mon_first_rows_missing_water_head(self):
        content = (
            "[Logger settings]\n  Location                =rb1\n"
            "  Number of channels      =2\n[Channel 1]\n"
            "  Identification          =WATER HEAD (WC)\n[Channel 2]\n"
            "  Identification          =TEMPERATURE\n[Data]\n4\n"
            "2025/05/05 13:00:00.0                    5.250\n"
            "2025/05/05 14:00:00.0                    4.827\n"
            "2025/05/05 15:00:00.0      409.667       4.820\n"
            "2025/05/05 16:00:00.0      409.433       4.837\n"
            "END OF DATA FILE OF DATALOGGER FOR WINDOWS\n"
        )
        with file_utils.tempinput(content, "utf-8", suffix=".MON") as path:
            parsed = DiverOfficeParser.parse(path, "utf-8")
        filtered = run_pre_resolution_pipeline(
            parsed,
            LoggerImportOptions(skip_missing_water_head=True),
        )

        assert_canonical(parsed)
        assert parsed.data["head_cm"].isna().tolist() == [True, True, False, False]
        assert parsed.data["temp_degc"].tolist() == [5.25, 4.827, 4.82, 4.837]
        assert filtered.data["head_cm"].tolist() == [409.667, 409.433]

    def test_parse_mon_preserves_wider_head_after_inference_window(self):
        with file_utils.tempinput(build_mon(1001), "utf-8", suffix=".mon") as path:
            parsed = DiverOfficeParser.parse(path, "utf-8")
        assert parsed.data.iloc[-1]["head_cm"] == pytest.approx(100.308)

    @pytest.mark.parametrize(
        ("before", "after"),
        [("9.999", "10.001"), ("99.999", "100.001"), ("999.999", "1000.001")],
    )
    def test_parse_mon_preserves_digit_width_crossings(self, before, after):
        with file_utils.tempinput(
            make_fixed_mon([(before,)] * 1000 + [(after,)]),
            "utf-8",
            suffix=".mon",
        ) as path:
            parsed = DiverOfficeParser.parse(path, "utf-8")
        assert parsed.data.iloc[-1]["head_cm"] == pytest.approx(float(after))

    def test_parse_mon_preserves_missing_channel_positions(self):
        content = make_fixed_mon(
            [("1.0", None, "3.0"), (None, "2.0", "3.0"), ("1.0", "2.0", None)]
        )
        with file_utils.tempinput(content, "utf-8", suffix=".mon") as path:
            parsed = DiverOfficeParser.parse(path, "utf-8")
        measurements = parsed.data.loc[:, ["head_cm", "temp_degc", "cond_mscm"]]
        assert measurements.notna().values.tolist() == [
            [True, False, True],
            [False, True, True],
            [True, True, False],
        ]
        assert measurements.sum(skipna=True).tolist() == [2.0, 4.0, 6.0]

    @pytest.mark.parametrize("value", ["-100.308", "+1,25", "1.25e3"])
    def test_parse_mon_accepts_supported_numeric_tokens(self, value):
        with file_utils.tempinput(
            make_fixed_mon([(value,)]), "utf-8", suffix=".mon"
        ) as path:
            parsed = DiverOfficeParser.parse(path, "utf-8")
        assert parsed.data.loc[0, "head_cm"] == pytest.approx(
            float(value.replace(",", "."))
        )

    @pytest.mark.parametrize(
        ("content", "message"),
        [
            (
                make_fixed_mon([("1.0",)]).replace(
                    "2025/01/01 00:00:00.0", "not-a-date 00:00:00.0"
                ),
                "date/time",
            ),
            (make_fixed_mon([("invalid",)]), "numeric"),
            (make_fixed_mon([("1.0",)], declared_count=2), "declared 2 data rows"),
            (
                make_fixed_mon([("1.0", "2.0")]).replace(
                    "Number of channels      =2", "Number of channels      =3"
                ),
                "declares 3 channels",
            ),
        ],
    )
    def test_parse_mon_rejects_structurally_invalid_input(self, content, message):
        with file_utils.tempinput(content, "utf-8", suffix=".mon") as path:
            with pytest.raises(DiverOfficeParseError, match=message):
                DiverOfficeParser.parse(path, "utf-8")

    def test_parse_mon_fallback_accepts_lossless_left_aligned_field(self):
        content = make_fixed_mon([("9.9",), ("100.308",)])
        content = content.replace(f"{'9.9':>12}", "    9.9     ").replace(
            f"{'100.308':>12}", "    100.308 "
        )
        with file_utils.tempinput(content, "utf-8", suffix=".mon") as path:
            parsed = DiverOfficeParser.parse(path, "utf-8")
        assert parsed.data["head_cm"].tolist() == [9.9, 100.308]

    def test_parse_mon_fallback_rejects_ambiguous_layout(self):
        content = make_fixed_mon([("1.0", "2.0"), ("10.0", "20.0")])
        content = content.replace("         1.0         2.0", "  1.0 2.0              ")
        with file_utils.tempinput(content, "utf-8", suffix=".mon") as path:
            with pytest.raises(DiverOfficeParseError, match="fallback"):
                DiverOfficeParser.parse(path, "utf-8")

    def test_mon_primary_requires_all_channel_endpoints_in_one_row(self):
        prefix = "2025/01/01 00:00:00.0"
        lines = [
            _SourceLine(1, prefix + "    1    2"),
            _SourceLine(2, prefix + "    1         3"),
            _SourceLine(3, prefix + "         2    3"),
        ]
        scanned = DiverOfficeParser._scan_mon_rows(lines, "ambiguous.mon")
        with pytest.raises(_IncompleteMonLayoutError, match="same row"):
            DiverOfficeParser._read_mon_by_right_edge(scanned, 4)

    def test_parse_csv_metadata_and_header_order(self):
        content = (
            "[Logger settings]\n  Serial number=..00-R2717  214.\n"
            "  Location=rb1\n  Number of channels=2\n[Channel 1]\n"
            "  Identification=WATER HEAD (WC)\n[Channel 2]\n"
            "  Identification=TEMPERATURE\n"
            "Date/time;Temperature[°C];Water head[cm]\n"
            "2025/01/01 00:00:00;10.0;123.4\n"
        )
        with file_utils.tempinput(content, "utf-8", suffix=".csv") as path:
            parsed = DiverOfficeParser.parse(path, "utf-8")
        assert_canonical(parsed)
        assert parsed.location == "rb1"
        assert parsed.serial_number == "R2717"
        assert parsed.data.loc[0, ["head_cm", "temp_degc"]].tolist() == [123.4, 10.0]

    @pytest.mark.parametrize(
        ("content", "message", "expected_line"),
        [
            pytest.param(
                make_diveroffice_csv(
                    ["WATER HEAD (WC)", "TEMPERATURE"],
                    ["Date/time", "Date/time", "Water head[cm]"],
                ),
                "CSV header must contain exactly one Date/time column",
                8,
                id="two_date_time_columns",
            ),
            pytest.param(
                make_diveroffice_csv(
                    ["WATER HEAD (WC)", "TEMPERATURE"],
                    ["Date/time", "Water head[cm]"],
                ),
                "CSV header has 1 channels but file declares 2",
                8,
                id="header_channel_count_mismatch",
            ),
            pytest.param(
                make_diveroffice_csv(
                    ["WATER HEAD (WC)", "TEMPERATURE", "LEVEL"],
                    ["Date/time", "Water head[cm]", "Temperature[C]", "Level[cm]"],
                ),
                "CSV header maps more than one column to head_cm",
                10,
                id="two_columns_map_to_head_cm",
            ),
            pytest.param(
                make_diveroffice_csv(
                    ["WATER HEAD (WC)", "TEMPERATURE"],
                    ["Date/time", "Temperature[C]", "Conductivity[mS/cm]"],
                ),
                "CSV header channels disagree with channel metadata",
                8,
                id="header_disagrees_with_channel_metadata",
            ),
        ],
    )
    def test_parse_csv_rejects_inconsistent_header(
        self, content, message, expected_line
    ):
        with file_utils.tempinput(content, "utf-8", suffix=".csv") as path:
            with pytest.raises(DiverOfficeParseError, match=message) as excinfo:
                DiverOfficeParser.parse(path, "utf-8")
        assert excinfo.value.line_number == expected_line
        assert excinfo.value.raw_text == content.splitlines()[expected_line - 1]

    def test_parse_csv_rejects_non_numeric_declared_channel_count(self):
        content = make_diveroffice_csv(
            ["WATER HEAD (WC)", "TEMPERATURE"],
            ["Date/time", "Water head[cm]", "Temperature[C]"],
            declared_count="two",
        )
        with file_utils.tempinput(content, "utf-8", suffix=".csv") as path:
            with pytest.raises(
                DiverOfficeParseError, match="invalid declared channel count"
            ) as excinfo:
                DiverOfficeParser.parse(path, "utf-8")
        assert excinfo.value.line_number is None


@pytest.mark.active
class TestLeveloggerParser:
    def test_parse_basic_units_and_metadata(self):
        content = (
            "Serial_number: 123\nLocation: rb1\nLEVEL\nUNIT: m\nTEMPERATURE\n"
            "Date;Time;ms;LEVEL;TEMPERATURE;spec. conductivity (uS/cm)\n"
            "2016-03-15;10:30:00;0;0.01;10;1000\n"
        )
        with file_utils.tempinput(content, "utf-8") as path:
            parsed = LeveloggerParser.parse(path, "utf-8")
        assert_canonical(parsed)
        assert parsed.location == "rb1"
        assert parsed.serial_number == "123"
        assert parsed.data.loc[0, ["head_cm", "temp_degc", "cond_mscm"]].tolist() == [
            1.0,
            10.0,
            1.0,
        ]

    @pytest.mark.parametrize(
        "layout", ["Serial_number: 12345", "Serial_number:\n12345"]
    )
    def test_parse_serial_number_variants(self, layout):
        content = (
            f"{layout}\nLocation: rb1\nLEVEL\nUNIT: cm\n"
            "Date;Time;ms;LEVEL\n2016-03-15;10:30:00;0;1\n"
        )
        with file_utils.tempinput(content, "utf-8") as path:
            parsed = LeveloggerParser.parse(path, "utf-8")
        assert parsed.serial_number == "12345"

    def test_invalid_nonempty_measurement_fails_file(self):
        content = "Date;Time;LEVEL\n2016-03-15;10:30:00;bad\n"
        with file_utils.tempinput(content, "utf-8") as path:
            with pytest.raises(FileError, match="Invalid numeric"):
                LeveloggerParser.parse(path, "utf-8")


@pytest.mark.active
class TestHoboParser:
    def test_parse_metadata_timezone_em_and_changed_order(self):
        content = (
            '﻿"Plot Title: temp"\n'
            '"#","Temp, °C (LGR S/N: 1234, SEN S/N: 1234, LBL: Rb1)",'
            '"Date Time, GMT+01:00"\n'
            "1,4.558,07/19/18 10:00:00 fm\n"
            "2,4.402,07/19/18 01:00:00 em\n"
        )
        with file_utils.tempinput(content, "utf-8") as path:
            parsed = HoboParser.parse(path, "utf-8")
        assert_canonical(parsed)
        assert parsed.location == "Rb1"
        assert parsed.serial_number == "1234"
        assert parsed.source_timezone == "GMT+01:00"
        assert parsed.data["date_time"].tolist() == [
            pd.Timestamp("2018-07-19 10:00:00"),
            pd.Timestamp("2018-07-19 13:00:00"),
        ]
        assert parsed.data["temp_degc"].tolist() == [4.558, 4.402]

    @pytest.mark.parametrize(
        ("suffix", "expected"),
        [
            ("12:00:00 am", pd.Timestamp("2018-07-19 00:00:00")),
            ("12:00:00 pm", pd.Timestamp("2018-07-19 12:00:00")),
            ("12:00:00 fm", pd.Timestamp("2018-07-19 00:00:00")),
            ("12:00:00 em", pd.Timestamp("2018-07-19 12:00:00")),
        ],
    )
    def test_parse_meridiem_noon_and_midnight(self, suffix, expected):
        content = (
            chr(34)
            + "#"
            + chr(34)
            + ","
            + chr(34)
            + "Date Time, GMT+01:00"
            + chr(34)
            + ","
            + chr(34)
            + "Temp, °C (LGR S/N: 1234, LBL: Rb1)"
            + chr(34)
            + "\n1,07/19/18 "
            + suffix
            + ",4.558\n"
        )
        with file_utils.tempinput(content, "utf-8") as path:
            parsed = HoboParser.parse(path, "utf-8")
        assert parsed.data.loc[0, "date_time"] == expected

    @pytest.mark.parametrize(
        ("lc_time", "meridiem", "expected_hour"),
        [
            ("C", "am", 0),
            ("C", "pm", 12),
            ("sv_SE.UTF-8", "am", 0),
            ("sv_SE.UTF-8", "pm", 12),
            ("sv_SE.UTF-8", "fm", 0),
            ("sv_SE.UTF-8", "em", 12),
        ],
    )
    def test_fix_date_meridiem_is_locale_independent(
        self, lc_time, meridiem, expected_hour
    ):
        """HOBO meridiems must parse under any LC_TIME.

        strptime's %p is locale-dependent and sv_SE defines no AM/PM strings,
        so a %p-based implementation rejects every meridiem token there.
        QgsApplication.initQgis() sets LC_TIME from the user's locale, so this
        reaches real imports — not just tests.
        """
        previous = locale.setlocale(locale.LC_TIME)
        try:
            try:
                locale.setlocale(locale.LC_TIME, lc_time)
            except locale.Error:
                pytest.skip(f"locale {lc_time} not available on this system")
            parsed = fix_date(f"07/19/18 12:00:00 {meridiem}", "hobo.csv")
        finally:
            locale.setlocale(locale.LC_TIME, previous)

        assert parsed == datetime(2018, 7, 19, expected_hour, 0, 0)

    def test_parse_year_first_variant(self):
        content = (
            '"#","Date Time, GMT+01:00",'
            '"Temp, °C (LGR S/N: 1234, LBL: Rb1)"\n'
            "1,2018-07-19 10:00:00,4.558\n"
        )
        with file_utils.tempinput(content, "utf-8") as path:
            parsed = HoboParser.parse(path, "utf-8")
        assert parsed.data.loc[0, "date_time"] == pd.Timestamp("2018-07-19 10:00:00")


@pytest.mark.active
def test_diveroffice_and_hobo_share_target_timezone_window() -> None:
    diver_content = (
        "Location=rb1\nInstrument number=UTC\n"
        "Date/time,Water head[cm],Temperature[°C]\n"
        "2025/01/01 00:00:00,1.0,10.0\n"
        "2025/01/01 01:00:00,2.0,20.0\n"
    )
    quote = chr(34)
    hobo_content = (
        quote
        + "#"
        + quote
        + ","
        + quote
        + "Date Time, GMT+00:00"
        + quote
        + ","
        + quote
        + "Temp, °C (LGR S/N: 1, LBL: rb1)"
        + quote
        + "\n"
        + "1,2025-01-01 00:00:00,10.0\n"
        + "2,2025-01-01 01:00:00,20.0\n"
    )
    options = LoggerImportOptions(
        target_timezone="UTC+1",
        from_date=pd.Timestamp("2025-01-01 02:00:00"),
        to_date=pd.Timestamp("2025-01-01 02:00:00"),
    )

    with (
        file_utils.tempinput(diver_content, "utf-8") as diver_path,
        file_utils.tempinput(hobo_content, "utf-8") as hobo_path,
    ):
        diver = run_pre_resolution_pipeline(
            DiverOfficeParser.parse(diver_path, "utf-8"), options
        )
        hobo = run_pre_resolution_pipeline(
            HoboParser.parse(hobo_path, "utf-8"), options
        )

    expected_date = [pd.Timestamp("2025-01-01 02:00:00")]
    assert diver.data["date_time"].tolist() == expected_date
    assert hobo.data["date_time"].tolist() == expected_date
    assert diver.data["temp_degc"].tolist() == [20.0]
    assert hobo.data["temp_degc"].tolist() == [20.0]


@pytest.mark.active
class TestDiverOfficeBaroParser:
    def test_parse_returns_canonical_semantic_frame(self):
        with file_utils.tempinput(
            build_mon(2, baro=True), "utf-8", suffix=".mon"
        ) as path:
            parsed = DiverOfficeBaroParser.parse(path, "utf-8")
        assert_canonical(parsed)
        assert parsed.kind is LoggerDataKind.BAROMETRIC
        assert parsed.data["baro_cmh2o"].tolist() == [99.9, 100.308]
        assert parsed.data["temp_degc"].tolist() == [5.0, 5.0]
        assert parsed.data["head_cm"].isna().all()


@pytest.mark.spatialite
class TestLoggerImportDiverOfficeSpatialite(
    utils_for_tests.MidvattenTestSpatialiteDbSv
):
    """Integration tests for LoggerImport with DiverOffice format."""

    def test_format_combo_items_have_destination_tooltips(self):
        """The format dropdown explains where each format's data ends up."""
        ms = MagicMock()
        ms.settingsdict = OrderedDict()
        importer = LoggerImport(self.iface, ms)
        importer.load_gui()

        expected_destinations = {
            LoggerImport.FORMAT_DIVEROFFICE: WATER_LEVEL_TABLE,
            LoggerImport.FORMAT_DIVEROFFICE_BARO: METEO_TABLE,
            LoggerImport.FORMAT_LEVELOGGER: WATER_LEVEL_TABLE,
            LoggerImport.FORMAT_HOBO: WATER_LEVEL_TABLE,
        }
        combo = importer.format_combo
        assert combo.count() == len(expected_destinations)
        for index in range(combo.count()):
            format_name = combo.itemText(index)
            tooltip = combo.itemData(index, Qt.ToolTipRole)
            assert tooltip, f"missing tooltip for {format_name}"
            assert expected_destinations[format_name] in tooltip

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

    @pytest.mark.parametrize(
        ("source_column", "expected_source"),
        [(False, None), (True, "field campaign")],
        ids=["oldest", "source-column"],
    )
    def test_import_supports_legacy_schema_metadata(
        self, source_column, expected_source
    ):
        replace_with_legacy_logger_schema(source_column=source_column)
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        content = (
            "Location=rb1\nDate/time,Water head[cm],Temperature[°C]\n"
            "2025/01/01 00:00:00,1.5,5.0\n"
        )
        with (
            file_utils.tempinput(content, "utf-8") as filename,
            mock.patch(
                "midvatten.tools.import_logger.midvatten_utils.select_files",
                return_value=[filename],
            ),
            mock.patch("midvatten.tools.utils.dialog_utils.Askuser"),
            mock.patch(
                "midvatten.tools.utils.common_utils.filter_nonexisting_values_and_ask",
                side_effect=lambda file_data, **_kwargs: file_data,
            ),
            mock.patch("qgis.utils.iface", autospec=True),
        ):
            ms = MagicMock()
            ms.settingsdict = OrderedDict()
            importer = LoggerImport(self.iface, ms)
            importer.load_gui()
            importer.confirm_names.checked = False
            importer.import_all_data.checked = True
            if importer.source_edit is not None:
                importer.source_edit.setText("field campaign")
            assert importer.start_import(
                importer.files or [filename],
                importer.skip_rows.checked,
                importer.confirm_names.checked,
                importer.import_all_data.checked,
            )

        selected = "obsid, date_time, head_cm"
        if source_column:
            selected += ", source"
        rows = db_utils.sql_load_fr_db(f"SELECT {selected} FROM w_levels_logger")
        expected = ["rb1", "2025-01-01 00:00:00", 1.5]
        if expected_source is not None:
            expected.append(expected_source)
        assert rows == (True, [tuple(expected)])

    def test_export_only_resolves_obsid_aggregates_and_never_writes_db(self, tmp_path):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        first = (
            "Location=rb1\nDate/time,Water head[cm],Temperature[°C]\n"
            "2025/01/01 00:00:00,1.0,\n"
        )
        second = (
            "Location=rb1\nDate/time,Water head[cm],Temperature[°C]\n"
            "2025/01/01 01:00:00,2.0,5.0\n"
        )
        exported = tmp_path / "logger.csv"
        with (
            file_utils.tempinput(first, "utf-8") as first_path,
            file_utils.tempinput(second, "utf-8") as second_path,
            mock.patch(
                "midvatten.tools.import_logger.midvatten_utils.select_files",
                return_value=[first_path, second_path],
            ),
            mock.patch(
                "qgis.PyQt.QtWidgets.QFileDialog.getSaveFileName",
                return_value=(str(exported), "CSV(*.csv)"),
            ),
            mock.patch("midvatten.tools.utils.dialog_utils.Askuser"),
            mock.patch(
                "midvatten.tools.utils.common_utils.filter_nonexisting_values_and_ask",
                side_effect=lambda file_data, **_kwargs: file_data,
            ),
            mock.patch("qgis.utils.iface", autospec=True),
            mock.patch.object(
                LoggerImport,
                "_run_db_worker",
                side_effect=AssertionError("export-only mode attempted a DB job"),
            ),
        ):
            ms = MagicMock()
            ms.settingsdict = OrderedDict()
            importer = LoggerImport(self.iface, ms)
            importer.load_gui()
            importer.confirm_names.checked = False
            importer.import_all_data.checked = True
            importer.select_files()
            assert importer.start_import(
                importer.files,
                importer.skip_rows.checked,
                importer.confirm_names.checked,
                importer.import_all_data.checked,
                export_csv=True,
                import_to_db=False,
            )

        assert db_utils.sql_load_fr_db("SELECT COUNT(*) FROM w_levels_logger") == (
            True,
            [(0,)],
        )
        assert exported.read_text(encoding="utf-8") == (
            "date_time;head_cm;temp_degc;cond_mscm;obsid\n"
            "2025-01-01 00:00:00;1.0;;;rb1\n"
            "2025-01-01 01:00:00;2.0;5.0;;rb1\n"
        )

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

    @pytest.mark.parametrize("oldest_schema", [False, True], ids=["current", "oldest"])
    def test_failure2_shaped_mon_matches_import_all_result(self, oldest_schema):
        """Generated hourly MON data must not lose the seven 96-hour blocks."""
        if oldest_schema:
            replace_with_legacy_logger_schema(source_column=False)
        cutoff = "2025-05-05 14:00:00"
        expected = (
            pd.date_range("2025-05-05 15:00:00", periods=9_915, freq="h")
            .strftime("%Y-%m-%d %H:%M:%S")
            .tolist()
        )
        content = build_mon(
            len(expected),
            start=datetime(2025, 5, 5, 15),
            step=timedelta(hours=1),
            location="rb1",
        )
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")

        def run_import(filename: str, import_all_data: bool) -> list[str]:
            db_utils.sql_alter_db("DELETE FROM w_levels_logger")
            if not oldest_schema:
                db_utils.sql_alter_db("DELETE FROM w_logger_series")
            db_utils.sql_alter_db(
                "INSERT INTO w_levels_logger (obsid, date_time, head_cm) "
                f"VALUES ('rb1', '{cutoff}', 1)"
            )
            with (
                mock.patch(
                    "midvatten.tools.import_logger.midvatten_utils.select_files",
                    return_value=[filename],
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
                f"WHERE obsid = 'rb1' AND date_time > '{cutoff}' ORDER BY date_time"
            )
            assert result[0]
            return [row[0] for row in result[1]]

        with file_utils.tempinput(content, "utf-8", suffix=".MON") as filename:
            cutoff_result = run_import(filename, import_all_data=False)
            import_all_result = run_import(filename, import_all_data=True)

        assert len(cutoff_result) == 9_915
        assert cutoff_result == import_all_result == expected

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

                # Yes = import the file anyway (keep its timestamps as-is).
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
        reference_string = r"""(True, [(rb1, 2016-03-15 10:30:00, 1.0, 10.0, None, None, None), (rb1, 2016-03-15 11:00:00, 11.0, 101.0, None, None, None), (rb2, 2016-04-15 10:30:00, 2.0, 20.0, None, None, None), (rb2, 2016-04-15 11:00:00, 21.0, 201.0, None, None, None), (rb3, 2016-05-15 10:30:00, 3.0, 30.0, 5.0, None, None), (rb3, 2016-05-15 11:00:00, 31.0, 301.0, 6.0, None, None), (rb4, 2016-05-15 10:30:00, 3.0, 30.0, 5.0, None, None), (rb4, 2016-05-15 11:00:00, 31.0, 301.0, 6.0, None, None), (rb5, 2016-05-15 13:30:00, 3.0, 30.0, 5.0, None, None), (rb5, 2016-05-15 14:00:00, 31.0, 301.0, 6.0, None, None)])"""
        assert test_string == reference_string
        assert (
            mock_askuser.mock_calls[0].kwargs.get("dialogtitle", "")
            == "Time zone conversion failed"
        )
        tz_msg = mock_askuser.mock_calls[0].kwargs.get("msg", "")
        assert "UTC+ABC2 could not be parsed!" in tz_msg
        assert "Import file anyway?" in tz_msg

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
                # No = skip this file (rb2 is left out of the import).
                mock_askuser.return_value.result = 0
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
        assert "Time zone conversion failed" in ", ".join(
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

            @mock.patch("midvatten.tools.import_logger.QtWidgets.QMessageBox.question")
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
        assert mock_askuser.call_args.args[1] == "Time zone conversion failed"

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
    def test_ensure_baro_meteo_parameters_seeds_missing_rows(self, mock_messagebar):
        """The extracted seeding inserts missing rows and is idempotent."""
        db_utils.sql_alter_db("DELETE FROM zz_meteoparam WHERE parameter='pressure'")

        ms = MagicMock()
        ms.settingsdict = OrderedDict()
        importer = LoggerImport(self.iface, ms)
        with db_utils.use_or_create_connection(None) as dbconnection:
            importer._ensure_baro_meteo_parameters(dbconnection)
            importer._ensure_baro_meteo_parameters(dbconnection)

        print(mock_messagebar.mock_calls)

        result = db_utils.sql_load_fr_db(
            "SELECT parameter, explanation FROM zz_meteoparam"
            " WHERE parameter='pressure'"
        )
        assert result[0] is True
        assert result[1] == [BARO_METEO_PARAMS[0]]

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


def test_first_metadata_value_returns_the_first_non_empty_match():
    metadata = {
        "logger settings": {"location": ""},
        "series settings": {"location": "Second"},
        "flat": {"location": "Fourth"},
    }
    lookups = (
        ("logger settings", "location"),
        ("series settings", "location"),
        ("channel identification", "location"),
        ("flat", "location"),
    )
    assert _first_metadata_value(metadata, lookups) == "Second"
    assert _first_metadata_value({}, lookups) == ""


def test_coerce_numeric_column_reports_the_first_invalid_position():
    converted, invalid_position = _coerce_numeric_column(
        pd.Series(["1,5", " 2.5 ", "", "  ", "3"])
    )
    assert invalid_position is None
    assert converted.tolist()[:2] == [1.5, 2.5]
    assert pd.isna(converted.iloc[2]) and pd.isna(converted.iloc[3])

    _converted, invalid_position = _coerce_numeric_column(
        pd.Series(["1.0", "", "oops", "2.0"])
    )
    assert invalid_position == 2

    # Non-default index: the contract is the *positional* offset, because both
    # call sites use it positionally (source_lines[...] and values.iloc[...]).
    # With a default RangeIndex a label-based lookup would pass by coincidence.
    _converted, invalid_position = _coerce_numeric_column(
        pd.Series(["1.0", "", "oops", "2.0"], index=[10, 11, 12, 13])
    )
    assert invalid_position == 2
