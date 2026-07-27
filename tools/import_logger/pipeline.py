"""Pure DataFrame transformations shared by every logger file format."""

from __future__ import annotations

import datetime
import re
from dataclasses import replace
from collections.abc import Mapping

import pandas as pd
from pandas.api.types import is_datetime64_ns_dtype, is_numeric_dtype
from pytz.exceptions import AmbiguousTimeError

from midvatten.tools.utils import date_utils

from .models import (
    CANONICAL_COLUMNS,
    MEASUREMENT_COLUMNS,
    METEO_COLUMNS,
    WATER_LEVEL_COLUMNS,
    LoggerDataKind,
    LoggerImportOptions,
    LoggerPipelineNotice,
    ParsedLoggerFile,
    PreparedLoggerFile,
)

_FIXED_TIMEZONE = re.compile(r"(?:gmt|utc)", re.IGNORECASE)
_BARO_DESTINATION = {
    "baro_cmh2o": ("pressure", "cmH2O"),
    "temp_degc": ("temp", "°C"),
}


class LoggerPipelineError(ValueError):
    """A shared logger transformation could not be completed safely."""


class TimezoneConversionError(LoggerPipelineError):
    """A requested source-to-target timezone conversion was invalid."""


class InvalidLatestDateError(LoggerPipelineError):
    """A non-null database latest-date value was structurally invalid."""


def validate_logger_frame(
    data: pd.DataFrame, *, allow_extra_columns: bool = False
) -> None:
    """Raise when *data* does not satisfy the canonical parser-frame contract.

    With ``allow_extra_columns`` the frame may carry additional trailing
    columns (e.g. ``obsid``) as long as it *starts* with the canonical ones.
    This lets post-resolution callers validate in place instead of slicing a
    full copy of the frame just to check it.
    """
    if not isinstance(data, pd.DataFrame):
        raise LoggerPipelineError("logger data must be a pandas DataFrame")
    columns = tuple(data.columns)
    if allow_extra_columns:
        if columns[: len(CANONICAL_COLUMNS)] != CANONICAL_COLUMNS:
            raise LoggerPipelineError(
                f"logger columns must start with {CANONICAL_COLUMNS!r}, got {columns!r}"
            )
    elif columns != CANONICAL_COLUMNS:
        raise LoggerPipelineError(
            f"logger columns must be exactly {CANONICAL_COLUMNS!r}, got {columns!r}"
        )
    if not data.columns.is_unique:
        raise LoggerPipelineError("logger columns must be unique")
    if not isinstance(data.index, pd.RangeIndex) or not data.index.equals(
        pd.RangeIndex(len(data))
    ):
        raise LoggerPipelineError("logger data must use a zero-based RangeIndex")
    if not is_datetime64_ns_dtype(data["date_time"].dtype):
        raise LoggerPipelineError("date_time must have naive datetime64[ns] dtype")
    if data["date_time"].dt.tz is not None:
        raise LoggerPipelineError("date_time must be timezone-naive internally")
    if data["date_time"].isna().any():
        raise LoggerPipelineError("date_time must not contain NaT")
    invalid_numeric = [
        column for column in MEASUREMENT_COLUMNS if not is_numeric_dtype(data[column])
    ]
    if invalid_numeric:
        raise LoggerPipelineError(
            f"measurement columns must be numeric: {invalid_numeric!r}"
        )


def _copy_with_data(parsed: ParsedLoggerFile, data: pd.DataFrame) -> ParsedLoggerFile:
    """Attach a defensive copy of a frame the caller may still hold.

    No reset_index: every caller validates first, and validate_logger_frame
    already requires a zero-based RangeIndex, so reindexing is a no-op that
    costs a second full copy of the frame (~35 ms and 20 MB per call on a
    500k-row file).
    """
    return replace(parsed, data=data.copy())


def _with_data(parsed: ParsedLoggerFile, data: pd.DataFrame) -> ParsedLoggerFile:
    """Attach a frame the callee just built. No defensive copy is needed."""
    return replace(parsed, data=data)


def _fixed_offset(value: str) -> datetime.timedelta | None:
    if "/" in value or not _FIXED_TIMEZONE.search(value):
        return None
    return date_utils.parse_timezone_to_timedelta(value)


def _timezone_spec(value: str) -> str | datetime.tzinfo:
    offset = _fixed_offset(value)
    if offset is None:
        return value
    return datetime.timezone(offset, name=value)


def _timezones_equivalent(source: str, target: str) -> bool:
    if source.strip().casefold() == target.strip().casefold():
        return True
    source_offset = _fixed_offset(source)
    target_offset = _fixed_offset(target)
    return (
        source_offset is not None
        and target_offset is not None
        and source_offset == target_offset
    )


def reconcile_transformed_timestamp_collisions(
    before: ParsedLoggerFile,
    after: ParsedLoggerFile,
) -> ParsedLoggerFile:
    """Coalesce only timestamp collisions newly created by a timezone transform."""
    validate_logger_frame(before.data)
    validate_logger_frame(after.data)
    if len(before.data) != len(after.data):
        raise LoggerPipelineError("timezone reconciliation requires aligned frames")

    duplicate_mask = after.data["date_time"].duplicated(keep=False)
    if not duplicate_mask.any():
        return _copy_with_data(after, after.data)

    before_dates = before.data["date_time"]
    data = after.data.copy()
    collision_indices: list[list[int]] = []
    duplicated = data.loc[duplicate_mask]
    for _, indices in duplicated.groupby("date_time", sort=False).groups.items():
        positions = list(indices)
        if before_dates.iloc[positions].nunique(dropna=False) > 1:
            collision_indices.append(positions)

    if not collision_indices:
        return replace(after, data=data)

    discard_indices: list[int] = []
    conflict_count = 0
    collision_count = 0
    for positions in collision_indices:
        collision_count += 1
        keep_index = positions[0]
        discard_indices.extend(positions[1:])
        for column in MEASUREMENT_COLUMNS:
            values = data.loc[positions, column].dropna().tolist()
            if not values:
                data.at[keep_index, column] = float("nan")
                continue
            chosen = values[0]
            data.at[keep_index, column] = chosen
            conflict_count += sum(value != chosen for value in values[1:])

    data = data.drop(index=discard_indices).reset_index(drop=True)
    notices = after.notices
    if conflict_count:
        notices += (
            LoggerPipelineNotice(
                stage="timezone",
                message=(
                    f"Kept the first value for {conflict_count} conflicting "
                    f"measurement(s) across {collision_count} transformed "
                    "timestamp collision(s)."
                ),
            ),
        )
    return replace(after, data=data, notices=notices)


def normalize_timezone(
    parsed: ParsedLoggerFile,
    target: str | None,
) -> ParsedLoggerFile:
    """Convert naive source timestamps to naive target-timezone timestamps."""
    validate_logger_frame(parsed.data)
    result = _copy_with_data(parsed, parsed.data)
    source = parsed.source_timezone
    if not source or not target:
        return result

    try:
        if _timezones_equivalent(source, target):
            return result
        source_spec = _timezone_spec(source)
        target_spec = _timezone_spec(target)
        try:
            localized = result.data["date_time"].dt.tz_localize(
                source_spec,
                ambiguous="infer",
                nonexistent="shift_forward",
            )
        except AmbiguousTimeError:
            localized = result.data["date_time"].dt.tz_localize(
                source_spec,
                ambiguous=False,
                nonexistent="shift_forward",
            )
        converted = localized.dt.tz_convert(target_spec).dt.tz_localize(None)
    except Exception as error:
        raise TimezoneConversionError(
            f"timezone conversion from {source!r} to {target!r} failed: {error}"
        ) from error

    if converted.equals(result.data["date_time"]):
        return result
    converted_file = _copy_with_data(
        result,
        result.data.assign(date_time=converted),
    )
    return reconcile_transformed_timestamp_collisions(result, converted_file)


def _typed_bound(value: object, name: str) -> pd.Timestamp | None:
    if value is None:
        return None
    if isinstance(value, str):
        raise LoggerPipelineError(f"{name} must already be parsed, not text")
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as error:
        raise LoggerPipelineError(f"invalid {name}: {value!r}") from error
    if pd.isna(timestamp):
        raise LoggerPipelineError(f"invalid {name}: {value!r}")
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_localize(None)
    return timestamp


def filter_date_window(
    data: pd.DataFrame,
    start: object = None,
    end: object = None,
) -> pd.DataFrame:
    """Apply an inclusive typed date window without mutating *data*."""
    validate_logger_frame(data)
    start_timestamp = _typed_bound(start, "from_date")
    end_timestamp = _typed_bound(end, "to_date")
    if (
        start_timestamp is not None
        and end_timestamp is not None
        and start_timestamp > end_timestamp
    ):
        raise LoggerPipelineError("from_date must not be later than to_date")
    mask = pd.Series(True, index=data.index)
    if start_timestamp is not None:
        mask &= data["date_time"] >= start_timestamp
    if end_timestamp is not None:
        mask &= data["date_time"] <= end_timestamp
    return data.loc[mask].reset_index(drop=True).copy()


def drop_missing_water_head(data: pd.DataFrame) -> pd.DataFrame:
    """Drop water-level rows whose head measurement is null."""
    validate_logger_frame(data)
    return data.dropna(subset=["head_cm"]).reset_index(drop=True).copy()


def assign_obsid(data: pd.DataFrame, obsid: str) -> pd.DataFrame:
    """Return a frame with one scalar observation identifier column."""
    validate_logger_frame(data)
    return data.assign(obsid=obsid).copy()


def _unwrap_latest_date(value: object) -> object:
    current = value
    while isinstance(current, (list, tuple)):
        if not current:
            return None
        current = current[0]
    return current


def parse_latest_dates(
    snapshot: Mapping[str, object],
) -> dict[str, pd.Timestamp | None]:
    """Parse a legacy database latest-date snapshot once, deterministically."""
    parsed: dict[str, pd.Timestamp | None] = {}
    for obsid, wrapped_value in snapshot.items():
        value = _unwrap_latest_date(wrapped_value)
        if value is None or (isinstance(value, str) and not value.strip()):
            parsed[obsid] = None
            continue
        if isinstance(value, str):
            timestamp = pd.to_datetime(
                value,
                format="mixed",
                yearfirst=True,
                errors="coerce",
            )
        else:
            try:
                timestamp = pd.Timestamp(value)
            except (TypeError, ValueError):
                timestamp = pd.NaT
        if pd.isna(timestamp):
            raise InvalidLatestDateError(
                f"Invalid latest logger date for {obsid!r}: {value!r}"
            )
        timestamp = pd.Timestamp(timestamp)
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_localize(None)
        parsed[obsid] = timestamp
    return parsed


def filter_after_latest_date(
    data: pd.DataFrame,
    obsid: str,
    latest_dates: Mapping[str, pd.Timestamp | None],
) -> pd.DataFrame:
    """Keep typed file rows strictly newer than the observation cutoff."""
    validate_logger_frame(data, allow_extra_columns=True)
    cutoff = latest_dates.get(obsid)
    if cutoff is None:
        return data.reset_index(drop=True).copy()
    if not isinstance(cutoff, pd.Timestamp):
        raise LoggerPipelineError("latest_dates must be parsed before filtering")
    return data.loc[data["date_time"] > cutoff].reset_index(drop=True).copy()


def baro_to_meteo(
    data: pd.DataFrame,
    obsid: str,
    instrumentid: str,
) -> pd.DataFrame:
    """Reshape canonical Baro measurements into deterministic meteo rows."""
    validate_logger_frame(data, allow_extra_columns=True)
    wide = data.assign(_source_ordinal=range(len(data)), obsid=obsid)
    long = wide.melt(
        id_vars=["_source_ordinal", "obsid", "date_time"],
        value_vars=list(_BARO_DESTINATION),
        var_name="_measurement",
        value_name="reading_num",
    ).dropna(subset=["reading_num"])
    long["_measurement_ordinal"] = long["_measurement"].map(
        {column: index for index, column in enumerate(_BARO_DESTINATION)}
    )
    long = long.sort_values(["_source_ordinal", "_measurement_ordinal"], kind="stable")
    long["instrumentid"] = instrumentid
    long["parameter"] = long["_measurement"].map(
        {column: metadata[0] for column, metadata in _BARO_DESTINATION.items()}
    )
    long["unit"] = long["_measurement"].map(
        {column: metadata[1] for column, metadata in _BARO_DESTINATION.items()}
    )
    return long.loc[:, METEO_COLUMNS].reset_index(drop=True).copy()


def run_pre_resolution_pipeline(
    parsed: ParsedLoggerFile,
    options: LoggerImportOptions,
) -> ParsedLoggerFile:
    """Run every shared transform that precedes interactive obsid resolution."""
    validate_logger_frame(parsed.data)
    result = normalize_timezone(parsed, options.target_timezone)
    # filter_date_window and drop_missing_water_head each return a fresh,
    # range-indexed copy, so _with_data must not copy a second time.
    result = _with_data(
        result,
        filter_date_window(result.data, options.from_date, options.to_date),
    )
    if options.skip_missing_water_head and result.kind is LoggerDataKind.WATER_LEVEL:
        result = _with_data(result, drop_missing_water_head(result.data))
    validate_logger_frame(result.data)
    return result


def run_post_resolution_pipeline(
    parsed: ParsedLoggerFile,
    obsid: str,
    latest_dates: Mapping[str, pd.Timestamp | None],
    options: LoggerImportOptions,
) -> PreparedLoggerFile:
    """Run the common post-obsid pipeline and prepare destination-shaped data."""
    validate_logger_frame(parsed.data)
    data = assign_obsid(parsed.data, obsid)
    if not options.import_all_data and parsed.kind is LoggerDataKind.WATER_LEVEL:
        data = filter_after_latest_date(data, obsid, latest_dates)
    instrumentid = parsed.serial_number or parsed.filename
    if parsed.kind is LoggerDataKind.BAROMETRIC:
        destination = baro_to_meteo(data, obsid, instrumentid)
    elif parsed.kind is LoggerDataKind.WATER_LEVEL:
        destination = data.loc[:, WATER_LEVEL_COLUMNS].copy()
    else:
        # The registry this replaced raised KeyError on an unknown kind. Keep
        # failing loudly: silently shaping a new kind as water level would
        # write it to the wrong destination table.
        raise LoggerPipelineError(f"unsupported logger kind {parsed.kind!r}")
    return PreparedLoggerFile(
        data=destination,
        filename=parsed.filename,
        source_path=parsed.source_path,
        kind=parsed.kind,
        location=parsed.location,
        serial_number=parsed.serial_number,
        obsid=obsid,
        notices=parsed.notices,
    )


def concatenate_prepared_frames(
    prepared_files: list[PreparedLoggerFile],
) -> pd.DataFrame:
    """Combine destination-shaped files once for CSV export."""
    if not prepared_files:
        return pd.DataFrame()
    columns = tuple(prepared_files[0].data.columns)
    if any(tuple(item.data.columns) != columns for item in prepared_files[1:]):
        raise LoggerPipelineError("export frames must share one destination schema")
    return pd.concat(
        [item.data for item in prepared_files],
        ignore_index=True,
        copy=False,
    )


def write_logger_csv(path: str, prepared_files: list[PreparedLoggerFile]) -> None:
    """Write logger destination data at the sole CSV text boundary."""
    data = concatenate_prepared_frames(prepared_files)
    data.to_csv(
        path,
        sep=";",
        encoding="utf-8",
        index=False,
        date_format="%Y-%m-%d %H:%M:%S",
        na_rep="",
    )
