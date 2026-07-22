"""Shared typed models for logger parsing and post-processing."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

import pandas as pd

CANONICAL_COLUMNS = (
    "date_time",
    "head_cm",
    "temp_degc",
    "cond_mscm",
    "baro_cmh2o",
)
MEASUREMENT_COLUMNS = CANONICAL_COLUMNS[1:]
WATER_LEVEL_COLUMNS = (
    "date_time",
    "head_cm",
    "temp_degc",
    "cond_mscm",
    "obsid",
)
METEO_COLUMNS = (
    "obsid",
    "instrumentid",
    "parameter",
    "date_time",
    "reading_num",
    "unit",
)


class LoggerDataKind(Enum):
    WATER_LEVEL = "water_level"
    BAROMETRIC = "barometric"


@dataclass(frozen=True)
class LoggerPipelineNotice:
    stage: str
    message: str


@dataclass
class ParsedLoggerFile:
    data: pd.DataFrame
    filename: str
    source_path: str
    kind: LoggerDataKind
    location: str | None
    serial_number: str | None
    source_timezone: str | None = None
    timezone_error: str | None = None
    notices: tuple[LoggerPipelineNotice, ...] = field(default_factory=tuple)


@dataclass
class PreparedLoggerFile:
    data: pd.DataFrame
    filename: str
    source_path: str
    kind: LoggerDataKind
    location: str | None
    serial_number: str | None
    obsid: str
    notices: tuple[LoggerPipelineNotice, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class LoggerImportOptions:
    target_timezone: str | None = None
    from_date: datetime | pd.Timestamp | None = None
    to_date: datetime | pd.Timestamp | None = None
    skip_missing_water_head: bool = False
    import_all_data: bool = False


@dataclass(frozen=True)
class LoggerSchemaCapabilities:
    has_series_id: bool
    has_created_at: bool
    has_source_column: bool


def empty_logger_frame() -> pd.DataFrame:
    """Return an empty frame with the canonical logger schema and dtypes."""
    return pd.DataFrame(
        {
            "date_time": pd.Series(dtype="datetime64[ns]"),
            "head_cm": pd.Series(dtype="float64"),
            "temp_degc": pd.Series(dtype="float64"),
            "cond_mscm": pd.Series(dtype="float64"),
            "baro_cmh2o": pd.Series(dtype="float64"),
        }
    )
