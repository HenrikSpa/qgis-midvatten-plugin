"""Accepted behavior for the logger import DataFrame pipeline.

The matrix deliberately separates product intent from representation artifacts.
Rows classified as ``shared intent`` describe places where the legacy formats
implemented the same user option inconsistently; the accepted rule is the one
that every parser result must follow after the refactor.
"""

from __future__ import annotations

import pandas as pd
import pytest

from midvatten.tools.import_logger.parsers import filter_dates_from_filedata


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


def test_failure2_shape_survives_latest_date_filter() -> None:
    timestamps = failure2_shaped_timestamps()
    file_data = [["date_time", "head_cm", "obsid"]]
    file_data.extend(
        [timestamp.strftime("%Y-%m-%d %H:%M:%S"), "1.0", "rb1"]
        for timestamp in timestamps
    )

    result = filter_dates_from_filedata(
        file_data,
        {"rb1": "2025-05-05 14:00:00"},
    )
    retained = {row[0] for row in result[1:]}

    assert len(result) - 1 == 9_915
    assert {
        "2025-06-01 00:00:00",
        "2025-06-04 23:00:00",
        "2025-06-05 00:00:00",
        "2025-12-04 23:00:00",
        "2026-01-01 00:00:00",
    } <= retained
