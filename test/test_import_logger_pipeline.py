"""Accepted behavior for the logger import DataFrame pipeline.

The matrix deliberately separates product intent from representation artifacts.
Rows classified as ``shared intent`` describe places where the legacy formats
implemented the same user option inconsistently; the accepted rule is the one
that every parser result must follow after the refactor.
"""

from __future__ import annotations

import pandas as pd
import pytest

from pandas.testing import assert_frame_equal

from midvatten.tools.import_logger.models import (
    CANONICAL_COLUMNS,
    METEO_COLUMNS,
    LoggerDataKind,
    LoggerImportOptions,
    ParsedLoggerFile,
    empty_logger_frame,
)
from midvatten.tools.import_logger.pipeline import (
    InvalidLatestDateError,
    LoggerPipelineError,
    assign_obsid,
    baro_to_meteo,
    drop_missing_water_head,
    filter_after_latest_date,
    filter_date_window,
    normalize_timezone,
    parse_latest_dates,
    run_post_resolution_pipeline,
    run_pre_resolution_pipeline,
    validate_logger_frame,
)


INTENT_MATRIX = (
    (
        "DiverOffice fixed-width and delimited parsing",
        "required intent",
        "Preserve complete-file validation, units, metadata, and channel slots",
    ),
    (
        "DiverOffice Baro parsing",
        "required intent",
        "Preserve pressure/temperature meaning and meteo destination",
    ),
    (
        "Levelogger parsing",
        "required intent",
        "Preserve variants, metadata, and level/conductivity unit conversion",
    ),
    (
        "HOBO parsing",
        "required intent",
        "Preserve quoted input, AM/PM/EM, metadata, and source timezone",
    ),
    (
        "from/to date window",
        "shared intent",
        "Inclusive endpoints in the normalized target/database timezone",
    ),
    (
        "skip missing water head",
        "shared intent",
        "Drop null head only for water-level data; no-op for Baro",
    ),
    (
        "import all data",
        "required intent",
        "Bypass latest-date cutoff but retain exact database deduplication",
    ),
    (
        "latest-date snapshot",
        "required intent",
        "Use one immutable pre-import snapshot for every file in the batch",
    ),
    (
        "schema variants",
        "required intent",
        "Support oldest, source-column, and logger-series schemas unchanged",
    ),
    (
        "CSV export",
        "required intent",
        "Preserve destination columns, semicolon delimiter, UTF-8, and blank nulls",
    ),
    (
        "failure isolation and cancellation",
        "required intent",
        "Isolate parse/database failures and make cancellation terminal",
    ),
    (
        "parser five-tuples and header-bearing row lists",
        "legacy artifact",
        "Replace with named metadata and one canonical typed DataFrame",
    ),
    (
        "parser-specific postprocessing order",
        "legacy artifact",
        "Run every parsed frame through the same ordered pipeline",
    ),
    (
        "stringify and heuristically reparse timestamps",
        "legacy artifact",
        "Parse source timestamps once and keep datetime dtype",
    ),
)


def failure2_shaped_timestamps() -> pd.DatetimeIndex:
    """Return the deterministic hourly timestamps represented by failure2.MON."""
    return pd.date_range("2025-05-05 15:00:00", periods=9_915, freq="h")


def test_intent_matrix_covers_every_format_and_acceptance_class() -> None:
    areas = {area for area, _, _ in INTENT_MATRIX}
    classifications = {classification for _, classification, _ in INTENT_MATRIX}

    assert {
        "DiverOffice fixed-width and delimited parsing",
        "DiverOffice Baro parsing",
        "Levelogger parsing",
        "HOBO parsing",
    } <= areas
    assert classifications == {"required intent", "shared intent", "legacy artifact"}


def logger_frame(
    dates: list[str],
    *,
    head: list[float | None] | None = None,
    temp: list[float | None] | None = None,
    cond: list[float | None] | None = None,
    baro: list[float | None] | None = None,
) -> pd.DataFrame:
    size = len(dates)
    data = pd.DataFrame(
        {
            "date_time": pd.to_datetime(dates, format="%Y-%m-%d %H:%M:%S"),
            "head_cm": head if head is not None else [float("nan")] * size,
            "temp_degc": temp if temp is not None else [float("nan")] * size,
            "cond_mscm": cond if cond is not None else [float("nan")] * size,
            "baro_cmh2o": baro if baro is not None else [float("nan")] * size,
        },
        columns=CANONICAL_COLUMNS,
    )
    for column in CANONICAL_COLUMNS[1:]:
        data[column] = pd.to_numeric(data[column]).astype("float64")
    return data


def parsed_file(
    data: pd.DataFrame,
    *,
    kind: LoggerDataKind = LoggerDataKind.WATER_LEVEL,
    source_timezone: str | None = None,
) -> ParsedLoggerFile:
    return ParsedLoggerFile(
        data=data,
        filename="logger.mon",
        source_path="/tmp/logger.mon",
        kind=kind,
        location="rb1",
        serial_number="SN1",
        source_timezone=source_timezone,
    )


def test_failure2_shape_survives_latest_date_filter() -> None:
    timestamps = failure2_shaped_timestamps()
    data = logger_frame(
        timestamps.strftime("%Y-%m-%d %H:%M:%S").tolist(),
        head=[1.0] * len(timestamps),
    )
    latest_dates = parse_latest_dates({"rb1": "2025-05-05 14:00:00"})

    result = filter_after_latest_date(data, "rb1", latest_dates)
    retained = set(result["date_time"])

    assert len(result) == 9_915
    assert {
        pd.Timestamp("2025-06-01 00:00:00"),
        pd.Timestamp("2025-06-04 23:00:00"),
        pd.Timestamp("2025-06-05 00:00:00"),
        pd.Timestamp("2025-12-04 23:00:00"),
        pd.Timestamp("2026-01-01 00:00:00"),
    } <= retained


def test_empty_logger_frame_has_exact_schema_and_dtypes() -> None:
    data = empty_logger_frame()

    validate_logger_frame(data)
    assert tuple(data.columns) == CANONICAL_COLUMNS
    assert str(data["date_time"].dtype) == "datetime64[ns]"
    assert all(str(data[column].dtype) == "float64" for column in CANONICAL_COLUMNS[1:])


@pytest.mark.parametrize(
    "mutate, match",
    [
        (lambda data: data.rename(columns={"head_cm": "head"}), "columns"),
        (lambda data: data.assign(date_time=pd.NaT), "must not contain NaT"),
        (lambda data: data.assign(head_cm="bad"), "must be numeric"),
        (lambda data: data.set_axis(pd.Index([2])), "RangeIndex"),
    ],
)
def test_validate_logger_frame_rejects_invalid_contract(mutate, match) -> None:
    data = logger_frame(["2025-01-01 00:00:00"], head=[1.0])

    with pytest.raises(LoggerPipelineError, match=match):
        validate_logger_frame(mutate(data))


def test_date_window_is_inclusive_typed_and_non_mutating() -> None:
    data = logger_frame(
        [
            "2025-01-01 00:00:00",
            "2025-01-01 01:00:00",
            "2025-01-01 02:00:00",
        ],
        head=[1.0, 2.0, 3.0],
    )
    original = data.copy(deep=True)

    result = filter_date_window(
        data,
        pd.Timestamp("2025-01-01 01:00:00"),
        pd.Timestamp("2025-01-01 02:00:00"),
    )

    assert result["head_cm"].tolist() == [2.0, 3.0]
    assert_frame_equal(data, original)
    assert result.index.equals(pd.RangeIndex(2))


def test_date_window_rejects_unparsed_text_bounds() -> None:
    with pytest.raises(LoggerPipelineError, match="already be parsed"):
        filter_date_window(empty_logger_frame(), "2025-01-01", None)


def test_drop_missing_head_and_assign_obsid_are_vectorized_copies() -> None:
    data = logger_frame(
        ["2025-01-01 00:00:00", "2025-01-01 01:00:00"],
        head=[None, 2.0],
    )

    filtered = drop_missing_water_head(data)
    assigned = assign_obsid(filtered, "rb1")

    assert filtered["head_cm"].tolist() == [2.0]
    assert assigned["obsid"].tolist() == ["rb1"]
    assert "obsid" not in data.columns


def test_parse_latest_dates_handles_legacy_shapes_and_rejects_invalid() -> None:
    parsed = parse_latest_dates(
        {
            "rb1": [("2025-06-01 00:00:00",)],
            "rb2": None,
            "rb3": pd.Timestamp("2025-12-04 23:00:00"),
        }
    )

    assert parsed == {
        "rb1": pd.Timestamp("2025-06-01 00:00:00"),
        "rb2": None,
        "rb3": pd.Timestamp("2025-12-04 23:00:00"),
    }
    with pytest.raises(InvalidLatestDateError, match="rb1"):
        parse_latest_dates({"rb1": "not-a-date"})


def test_latest_date_unknown_obsid_and_import_all_leave_rows_unchanged() -> None:
    data = logger_frame(["2025-01-01 00:00:00"], head=[1.0])
    parsed = parsed_file(data)

    unknown = filter_after_latest_date(data, "unknown", {})
    prepared = run_post_resolution_pipeline(
        parsed,
        "rb1",
        {"rb1": pd.Timestamp("2030-01-01")},
        LoggerImportOptions(import_all_data=True),
    )

    assert_frame_equal(unknown, data)
    assert len(prepared.data) == 1


def test_baro_reshape_preserves_source_then_pressure_temperature_order() -> None:
    data = logger_frame(
        ["2025-01-01 00:00:00", "2025-01-01 01:00:00"],
        temp=[5.0, None],
        baro=[100.0, 101.0],
    )

    result = baro_to_meteo(data, "baro1", "SN1")

    assert tuple(result.columns) == METEO_COLUMNS
    assert result[["parameter", "reading_num"]].values.tolist() == [
        ["pressure", 100.0],
        ["temp", 5.0],
        ["pressure", 101.0],
    ]
    assert result["instrumentid"].unique().tolist() == ["SN1"]


def test_timezone_conversion_without_collision_preserves_every_row() -> None:
    data = logger_frame(
        ["2025-01-01 00:00:00", "2025-01-01 01:00:00"],
        head=[1.0, 2.0],
    )

    result = normalize_timezone(parsed_file(data, source_timezone="UTC"), "UTC+1")

    assert result.data["date_time"].tolist() == [
        pd.Timestamp("2025-01-01 01:00:00"),
        pd.Timestamp("2025-01-01 02:00:00"),
    ]
    assert result.data["head_cm"].tolist() == [1.0, 2.0]
    assert result.notices == ()


def test_no_timezone_transformation_does_not_reconcile_existing_duplicates() -> None:
    data = logger_frame(
        ["2025-01-01 00:00:00", "2025-01-01 00:00:00"],
        head=[1.0, 2.0],
    )

    result = normalize_timezone(parsed_file(data, source_timezone="UTC"), "GMT")

    assert_frame_equal(result.data, data)
    assert result.notices == ()


def test_autumn_collision_coalesces_complementary_and_equal_values() -> None:
    data = logger_frame(
        ["2025-10-26 00:30:00", "2025-10-26 01:30:00"],
        head=[1.0, None],
        temp=[5.0, 5.0],
        cond=[None, 2.0],
    )

    result = normalize_timezone(
        parsed_file(data, source_timezone="UTC"),
        "Europe/Stockholm",
    )

    assert len(result.data) == 1
    assert result.data.loc[0, "date_time"] == pd.Timestamp("2025-10-26 02:30:00")
    assert result.data.loc[0, ["head_cm", "temp_degc", "cond_mscm"]].tolist() == [
        1.0,
        5.0,
        2.0,
    ]
    assert result.notices == ()


def test_autumn_collision_keeps_first_conflict_and_reports_only_data_loss() -> None:
    data = logger_frame(
        [
            "2025-10-26 00:15:00",
            "2025-10-26 01:15:00",
            "2025-10-26 00:30:00",
            "2025-10-26 01:30:00",
        ],
        head=[1.0, 2.0, 3.0, 3.0],
    )

    result = normalize_timezone(
        parsed_file(data, source_timezone="UTC"),
        "Europe/Stockholm",
    )

    assert result.data["head_cm"].tolist() == [1.0, 3.0]
    assert len(result.notices) == 1
    assert "1 conflicting measurement" in result.notices[0].message


def test_ambiguous_source_hour_falls_back_to_standard_time() -> None:
    data = logger_frame(["2025-10-26 02:30:00"], head=[1.0])

    result = normalize_timezone(
        parsed_file(data, source_timezone="Europe/Stockholm"),
        "UTC",
    )

    assert result.data["date_time"].tolist() == [pd.Timestamp("2025-10-26 01:30:00")]


def test_spring_nonexistent_time_shifts_and_coalesces_without_failure() -> None:
    data = logger_frame(
        ["2025-03-30 02:30:00", "2025-03-30 03:00:00"],
        head=[1.0, None],
        temp=[None, 5.0],
    )

    result = normalize_timezone(
        parsed_file(data, source_timezone="Europe/Stockholm"),
        "UTC",
    )

    assert len(result.data) == 1
    assert result.data["date_time"].tolist() == [pd.Timestamp("2025-03-30 01:00:00")]
    assert result.data.loc[0, ["head_cm", "temp_degc"]].tolist() == [1.0, 5.0]
    assert result.notices == ()


@pytest.mark.parametrize(
    ("kind", "expected_rows"),
    [(LoggerDataKind.WATER_LEVEL, 1), (LoggerDataKind.BAROMETRIC, 2)],
)
def test_pre_pipeline_applies_target_window_then_kind_missing_policy(
    kind: LoggerDataKind,
    expected_rows: int,
) -> None:
    data = logger_frame(
        ["2025-01-01 00:00:00", "2025-01-01 01:00:00"],
        head=[None, 2.0],
        temp=[4.0, 5.0],
        baro=[100.0, 101.0],
    )
    original = data.copy(deep=True)

    result = run_pre_resolution_pipeline(
        parsed_file(data, kind=kind, source_timezone="UTC"),
        LoggerImportOptions(
            target_timezone="Europe/Stockholm",
            from_date=pd.Timestamp("2025-01-01 01:00:00"),
            to_date=pd.Timestamp("2025-01-01 02:00:00"),
            skip_missing_water_head=True,
        ),
    )

    assert len(result.data) == expected_rows
    assert_frame_equal(data, original)


def test_post_pipeline_uses_kind_policy_without_mutating_parser_frame() -> None:
    data = logger_frame(["2025-01-01 00:00:00"], temp=[5.0], baro=[100.0])
    original = data.copy(deep=True)

    result = run_post_resolution_pipeline(
        parsed_file(data, kind=LoggerDataKind.BAROMETRIC),
        "baro1",
        {},
        LoggerImportOptions(),
    )

    assert tuple(result.data.columns) == METEO_COLUMNS
    assert result.data["parameter"].tolist() == ["pressure", "temp"]
    assert_frame_equal(data, original)
