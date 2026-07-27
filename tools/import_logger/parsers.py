"""
Parser classes and helpers for DiverOffice, Levelogger, and HOBO logger formats.
"""

from __future__ import annotations

import csv
import datetime
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from io import StringIO

import qgis.PyQt.QtWidgets as QtWidgets
from qgis.PyQt.QtCore import QCoreApplication

import pandas as pd  # pandas is a mandatory dependency of this plugin

from midvatten.tools.utils import (
    file_utils,
    message_utils,
)
from midvatten.tools.utils.string_utils import returnunicode as ru
from midvatten.tools.utils.common_utils import format_timezone_string
from midvatten.tools.import_logger.models import (
    CANONICAL_COLUMNS,
    MEASUREMENT_COLUMNS,
    LoggerDataKind,
    ParsedLoggerFile,
    empty_logger_frame,
)
from midvatten.tools.utils.gui_utils import (
    RowEntry,
    set_combobox,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


class FileError(Exception):
    pass


def fix_date(date_time: str, filename: str) -> datetime.datetime:
    """Parse one HOBO timestamp using only documented source formats."""
    value = str(date_time).strip()
    suffix_match = re.fullmatch(r"(.+?)\s+([A-Za-z]{2})", value)
    suffix = suffix_match.group(2).casefold() if suffix_match else None
    if suffix in {
        "am",
        "pm",
        "fm",
        "em",
    }:
        try:
            # strptime's %p is locale-dependent, and several locales (sv_SE
            # among them) define no AM/PM strings at all — there %p matches
            # only the empty string and rejects every meridiem token. QGIS
            # sets LC_TIME from the user's locale, so parse the 12-hour time
            # with the locale-independent %I and apply the shift ourselves.
            base = datetime.datetime.strptime(
                suffix_match.group(1),
                "%m/%d/%y %I:%M:%S",
            )
            is_pm = suffix in {"pm", "em"}
            return base.replace(hour=base.hour % 12 + (12 if is_pm else 0))
        except ValueError as error:
            raise FileError(
                QCoreApplication.translate(
                    "LoggerImport", "Dateformat in file %s could not be parsed."
                )
                % filename
            ) from error

    for date_format in (
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%m/%d/%y %H:%M:%S",
    ):
        try:
            return datetime.datetime.strptime(value, date_format)
        except ValueError:
            continue
    raise FileError(
        QCoreApplication.translate(
            "LoggerImport", "Dateformat in file %s could not be parsed."
        )
        % filename
    )


def get_tz_string(date_time_tz: str) -> str | None:
    """Extract a timezone string from a HOBO date-time column header.

    >>> get_tz_string('Date Time, GMT+02:00')
    'GMT+02:00'
    >>> get_tz_string('Date Time, GMT+2')
    'GMT+2'
    >>> get_tz_string('Date Time, GMT')
    'GMT'
    >>> get_tz_string('Date Time, GMT-2:00')
    'GMT-2:00'
    """
    match = re.match(r"Date Time, ([A-Za-z0-9\+\-\:]+)", date_time_tz, re.IGNORECASE)
    return match.group(1) if match else None


def _parse_explicit_datetimes(
    values: pd.Series,
    formats: tuple[str, ...],
) -> pd.Series:
    """Parse known source formats and expose every structurally invalid value."""
    parsed = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    remaining = parsed.isna()
    for date_format in formats:
        candidates = pd.to_datetime(
            values.loc[remaining], format=date_format, errors="coerce"
        )
        parsed.loc[remaining] = candidates
        remaining = parsed.isna()
        if not remaining.any():
            break
    return parsed


def _canonical_frame(data: pd.DataFrame) -> pd.DataFrame:
    """Add absent numeric channels once and return the exact parser schema."""
    result = data.copy()
    for column in MEASUREMENT_COLUMNS:
        if column not in result.columns:
            result[column] = float("nan")
        result[column] = pd.to_numeric(result[column]).astype("float64")
    if "date_time" not in result.columns:
        return empty_logger_frame()
    result["date_time"] = result["date_time"].astype("datetime64[ns]")
    return result.loc[:, CANONICAL_COLUMNS].reset_index(drop=True)


def _first_metadata_value(
    metadata: dict[str, dict[str, str]],
    lookups: tuple[tuple[str, str], ...],
) -> str:
    """Return the first non-empty value for the ordered (section, key) pairs.

    DiverOffice moved the same field between sections across file-format
    generations, so every metadata field is resolved by trying each known
    location in priority order.
    """
    for section_name, key in lookups:
        value = metadata.get(section_name, {}).get(key, "")
        if value:
            return value
    return ""


def _coerce_numeric_column(values: pd.Series) -> tuple[pd.Series, int | None]:
    """Coerce measurement text to numbers, reporting the first bad value.

    Blank and whitespace-only values become NA — a logger row may legitimately
    omit a channel. Decimal commas are accepted. The second element is the
    positional index of the first non-blank value that is not a number, or
    ``None`` when every value converted.
    """
    normalized = values.astype("string").str.strip()
    normalized = normalized.mask(normalized == "")
    normalized = normalized.str.replace(",", ".", regex=False)
    converted = pd.to_numeric(normalized, errors="coerce")
    invalid = normalized.notna() & converted.isna()
    if invalid.any():
        return converted, int(invalid.to_numpy().nonzero()[0][0])
    return converted, None


# ── GUI components ─────────────────────────────────────────────────────────────


class TzConverter(RowEntry):
    """Timezone selector widget for HOBO logger imports."""

    def __init__(self):
        super().__init__()
        self.label = QtWidgets.QLabel(
            QCoreApplication.translate("TzSelector", "Select target timezone: ")
        )
        timezones = [format_timezone_string(hour) for hour in range(-11, 15)]

        self._tz_list = QtWidgets.QComboBox()
        self._tz_list.addItems(timezones)

        for widget in [self.label, self._tz_list]:
            self.layout().addWidget(widget)

        self.target_tz = "GMT+1"

        self.layout().addStretch()

    @property
    def target_tz(self):
        return self._tz_list.currentText()

    @target_tz.setter
    def target_tz(self, value):
        set_combobox(self._tz_list, value)


# ── Parser classes ─────────────────────────────────────────────────────────────

# keyword (space-stripped, lowercase) → output column name
_DIVEROFFICE_DEFAULT_COL_MAP: dict[str, str] = {
    "level": "head_cm",
    "waterhead": "head_cm",
    "temp": "temp_degc",
    "cond": "cond_mscm",
}
_DIVEROFFICE_BARO_COL_MAP: dict[str, str] = {
    "pressure": "baro_cmh2o",
    "baro": "baro_cmh2o",
    "temp": "temp_degc",
}


@dataclass(frozen=True)
class _SourceLine:
    number: int
    text: str


@dataclass(frozen=True)
class _MonToken:
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class _ScannedMonRow:
    source: _SourceLine
    date_time: str
    tokens: tuple[_MonToken, ...]


@dataclass(frozen=True)
class _ParsedMonMetadata:
    """Everything the DiverOffice header pass produces, before column mapping."""

    sections: dict[str, dict[str, str]]
    raw_rows: list[str]
    rows: list[str]
    data_start_row: int | None


class _IncompleteMonLayoutError(Exception):
    """The right edges do not uniquely describe every declared channel."""


class DiverOfficeParseError(ValueError):
    """A DiverOffice file could not be parsed without risking data loss."""

    def __init__(
        self,
        filename: str,
        reason: str,
        line_number: int | None = None,
        raw_text: str | None = None,
        fallback_reason: str | None = None,
    ):
        self.filename = filename
        self.reason = reason
        self.line_number = line_number
        self.raw_text = raw_text
        self.fallback_reason = fallback_reason
        location = f" line {line_number}" if line_number is not None else ""
        details = f"{filename}{location}: {reason}"
        if raw_text is not None:
            details += f" [raw={raw_text!r}]"
        if fallback_reason is not None:
            details += f" [fallback={fallback_reason}]"
        super().__init__(details)


class DiverOfficeParser:
    """Parser for Diver-Office .mon and .csv logger files.

    Handles two metadata formats:
    - ``[Logger settings]`` / ``[Channel N]`` sections with ``key=value`` pairs
    - ``[Channel identification]`` sections with ``key;value`` pairs
    """

    @staticmethod
    def _extract_diver_serial(serial_raw: str) -> str | None:
        _tail = serial_raw.split("-")[-1].split()
        return _tail[0] if _tail else None

    @staticmethod
    def _scan_mon_rows(
        data_rows: list[_SourceLine], filename: str
    ) -> list[_ScannedMonRow]:
        scanned_rows = []
        for source in data_rows:
            match = re.match(r"^\s*(?P<date>\S+)\s+(?P<time>\S+)", source.text)
            if match is None:
                raise DiverOfficeParseError(
                    filename,
                    "data row does not start with a date and time",
                    source.number,
                    source.text,
                )
            tokens = tuple(
                _MonToken(
                    text=token.group(),
                    start=match.end() + token.start(),
                    end=match.end() + token.end(),
                )
                for token in re.finditer(r"\S+", source.text[match.end() :])
            )
            scanned_rows.append(
                _ScannedMonRow(
                    source=source,
                    date_time=f"{match.group('date')} {match.group('time')}",
                    tokens=tokens,
                )
            )
        return scanned_rows

    @staticmethod
    def _read_mon_by_right_edge(
        scanned_rows: list[_ScannedMonRow], expected_num_fields: int
    ) -> pd.DataFrame:
        channel_count = expected_num_fields - 1
        right_edges = sorted(
            {token.end for row in scanned_rows for token in row.tokens}
        )
        if len(right_edges) != channel_count:
            raise _IncompleteMonLayoutError(
                f"expected {channel_count} channel end positions but found "
                f"{len(right_edges)} ({right_edges})"
            )

        required_edges = set(right_edges)
        if not any(
            {token.end for token in row.tokens} == required_edges
            for row in scanned_rows
        ):
            raise _IncompleteMonLayoutError(
                "channel end positions never occur together in the same row"
            )

        channel_by_edge = {edge: index for index, edge in enumerate(right_edges, 1)}
        records: list[list[str | None]] = []
        for row in scanned_rows:
            record: list[str | None] = [row.date_time] + [None] * channel_count
            for token in row.tokens:
                channel = channel_by_edge[token.end]
                if channel > 1 and token.start < right_edges[channel - 2]:
                    raise _IncompleteMonLayoutError(
                        "measurement token crosses a proven channel boundary"
                    )
                record[channel] = token.text
            records.append(record)
        return pd.DataFrame(records, columns=range(expected_num_fields))

    @staticmethod
    def _read_mon_fallback(
        scanned_rows: list[_ScannedMonRow],
        expected_num_fields: int,
        filename: str,
        primary_reason: str,
    ) -> pd.DataFrame:
        raw_df = pd.read_fwf(
            StringIO("\n".join(row.source.text for row in scanned_rows)),
            header=None,
            dtype=str,
            infer_nrows=len(scanned_rows),
        )
        expected_raw_fields = expected_num_fields + 1
        if raw_df.shape != (len(scanned_rows), expected_raw_fields):
            raise DiverOfficeParseError(
                filename,
                "fixed-width fallback produced an unexpected number of fields",
                fallback_reason=(
                    f"{primary_reason}; expected {expected_raw_fields} raw fields, "
                    f"found {raw_df.shape[1]}"
                ),
            )

        channel_count = expected_num_fields - 1
        left_edges = sorted(
            {token.start for row in scanned_rows for token in row.tokens}
        )
        if len(left_edges) != channel_count:
            raise DiverOfficeParseError(
                filename,
                "fallback could not establish one stable start position per channel",
                fallback_reason=primary_reason,
            )
        channel_by_start = {start: channel for channel, start in enumerate(left_edges)}

        for row_index, scanned in enumerate(scanned_rows):
            source_slots: list[str | None] = [None] * channel_count
            for token in scanned.tokens:
                source_slots[channel_by_start[token.start]] = token.text
            parsed_slots = tuple(
                None if pd.isna(value) or not str(value).strip() else str(value).strip()
                for value in raw_df.iloc[row_index, 2:]
            )
            if parsed_slots != tuple(source_slots):
                raise DiverOfficeParseError(
                    filename,
                    "fixed-width fallback did not preserve measurement channel slots",
                    scanned.source.number,
                    scanned.source.text,
                    fallback_reason=primary_reason,
                )

        date_time = (
            raw_df.iloc[:, 0].fillna("").str.strip()
            + " "
            + raw_df.iloc[:, 1].fillna("").str.strip()
        ).str.strip()
        for row_index, scanned in enumerate(scanned_rows):
            if date_time.iloc[row_index] != scanned.date_time:
                raise DiverOfficeParseError(
                    filename,
                    "fixed-width fallback did not preserve date/time",
                    scanned.source.number,
                    scanned.source.text,
                    fallback_reason=primary_reason,
                )
        physical_df = pd.concat(
            [date_time, raw_df.iloc[:, 2:].reset_index(drop=True)], axis=1
        )
        physical_df.columns = range(expected_num_fields)
        return physical_df

    @staticmethod
    def _strict_frame_conversion(
        frame: pd.DataFrame,
        source_lines: list[_SourceLine],
        filename: str,
        date_col_idx: int = 0,
    ) -> pd.DataFrame:
        """Convert dates and numbers while rejecting every non-empty bad value."""
        converted_frame = frame.copy()
        parsed_dates = _parse_explicit_datetimes(
            converted_frame.iloc[:, date_col_idx].astype("string").str.strip(),
            (
                "%Y/%m/%d %H:%M:%S.%f",
                "%Y/%m/%d %H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S",
            ),
        )
        invalid_dates = parsed_dates.isna()
        if invalid_dates.any():
            row_index = int(invalid_dates.to_numpy().nonzero()[0][0])
            source = source_lines[row_index]
            raise DiverOfficeParseError(
                filename,
                "invalid date/time value",
                source.number,
                source.text,
            )
        date_column = converted_frame.columns[date_col_idx]
        converted_frame[date_column] = parsed_dates

        for col_idx in range(converted_frame.shape[1]):
            if col_idx == date_col_idx:
                continue
            raw = converted_frame.iloc[:, col_idx]
            converted, invalid_position = _coerce_numeric_column(raw)
            if invalid_position is not None:
                source = source_lines[invalid_position]
                raise DiverOfficeParseError(
                    filename,
                    f"invalid numeric value {raw.iloc[invalid_position]!r}",
                    source.number,
                    source.text,
                )
            converted_frame[converted_frame.columns[col_idx]] = converted
        return converted_frame

    @staticmethod
    def _read_delimited_data(
        source_lines: list[_SourceLine],
        delimiter: str,
        expected_num_fields: int,
        usecols: list[int],
        colnames: list[str],
        date_col_idx: int,
        filename: str,
    ) -> pd.DataFrame:
        records: list[list[str | None]] = []
        for source in source_lines:
            values = next(csv.reader([source.text], delimiter=delimiter))
            if len(values) != expected_num_fields:
                raise DiverOfficeParseError(
                    filename,
                    f"expected {expected_num_fields} delimited fields but found "
                    f"{len(values)}",
                    source.number,
                    source.text,
                )
            records.append([value.strip() or None for value in values])

        physical_df = pd.DataFrame(records, columns=range(expected_num_fields))
        physical_df = DiverOfficeParser._strict_frame_conversion(
            physical_df, source_lines, filename, date_col_idx
        )
        df = physical_df.loc[:, usecols].copy()
        df.columns = colnames
        return df

    @staticmethod
    def _read_mon_data(
        data_rows: list[_SourceLine],
        expected_num_fields: int,
        usecols: list[int],
        colnames: list[str],
        filename: str,
    ) -> pd.DataFrame:
        """Read fixed-width MON rows without altering any source token."""
        if not data_rows:
            return pd.DataFrame(columns=colnames)

        scanned_rows = DiverOfficeParser._scan_mon_rows(data_rows, filename)
        try:
            physical_df = DiverOfficeParser._read_mon_by_right_edge(
                scanned_rows, expected_num_fields
            )
        except _IncompleteMonLayoutError as error:
            physical_df = DiverOfficeParser._read_mon_fallback(
                scanned_rows,
                expected_num_fields,
                filename,
                str(error),
            )
            message_utils.MessagebarAndLog.info(
                log_msg=QCoreApplication.translate(
                    "LoggerImport",
                    "Accepted %s using the validated full-file fixed-width fallback: %s",
                )
                % (filename, error)
            )

        physical_df = DiverOfficeParser._strict_frame_conversion(
            physical_df, data_rows, filename
        )
        df = physical_df.loc[:, usecols].copy()
        df.columns = colnames
        return df

    @staticmethod
    def _read_metadata(path: str, charset: str) -> _ParsedMonMetadata:
        """Read the file and parse its header sections into key/value maps."""
        section = None
        data_start_row = None
        metadata: dict[str, dict[str, str]] = {}
        with open(path, encoding=str(charset)) as f:
            raw_rows = [ru(rawrow).rstrip("\n").rstrip("\r") for rawrow in f]
        rows = [rawrow.strip() for rawrow in raw_rows]

        for rownr, row in enumerate(rows):
            if (
                path.lower().endswith(".csv")
                and "Date/time" in row
                and not row.startswith("[")
            ):
                data_start_row = rownr + 1
                break

            if row.startswith("["):
                section = row.strip().lstrip("[").rstrip("]").lower()

                if section == "data":
                    data_start_row = rownr + 2
                    break
                else:
                    continue

            if section:
                # Support both '=' (classic .mon) and ';' (channel identification) separators
                if "=" in row:
                    kv = [x.strip() for x in row.split("=")]
                    metadata.setdefault(section, {})[kv[0].lower()] = "=".join(kv[1:])
                elif ";" in row:
                    kv = [x.strip() for x in row.split(";", 1)]
                    metadata.setdefault(section, {})[kv[0].lower()] = (
                        kv[1] if len(kv) > 1 else ""
                    )
            elif "=" in row and not row.startswith("["):
                # Legacy flat CSV: bare key=value lines before Date/time header
                kv = [x.strip() for x in row.split("=", 1)]
                key = kv[0].lower()
                if key in ("location", "instrument number", "serial number"):
                    metadata.setdefault("flat", {})[key] = kv[1] if len(kv) > 1 else ""

        return _ParsedMonMetadata(
            sections=metadata,
            raw_rows=raw_rows,
            rows=rows,
            data_start_row=data_start_row,
        )

    @staticmethod
    def _resolve_declared_channels(
        metadata: dict[str, dict[str, str]],
        data_headers: dict[int, str],
        filename: str,
    ) -> int | None:
        """Return the declared channel count, proving it matches the headers."""
        declared_channels_raw = _first_metadata_value(
            metadata,
            (
                ("logger settings", "number of channels"),
                ("series settings", "number of channels"),
            ),
        )
        if not declared_channels_raw:
            return None

        try:
            declared_channels = int(declared_channels_raw.strip())
        except ValueError as error:
            raise DiverOfficeParseError(
                filename,
                f"invalid declared channel count {declared_channels_raw!r}",
            ) from error

        identified_channels = set(data_headers) - {0}
        expected_channels = set(range(1, declared_channels + 1))
        if identified_channels != expected_channels:
            raise DiverOfficeParseError(
                filename,
                f"file declares {declared_channels} channels but identifies "
                f"channels {sorted(identified_channels)}",
            )
        return declared_channels

    @staticmethod
    def _resolve_csv_header(
        rows: list[str],
        raw_rows: list[str],
        header_row_idx: int,
        data_headers: dict[int, str],
        declared_channels: int | None,
        mapped_output_name: Callable[[str], str | None],
        filename: str,
    ) -> tuple[dict[int, str], int, int, str]:
        """Reconcile the authoritative CSV header against channel metadata.

        A data row may legitimately omit a measurement, so the header — not the
        widest data row — decides the field count and column identities.
        """
        header_row = rows[header_row_idx]
        hdr_delim = file_utils.get_delimiter_from_file_rows(
            [header_row],
            delimiters=["\t", ";", ","],
            filename=filename,
        )
        if hdr_delim is None:
            hdr_delim = ","
        header_cols = [
            c.strip() for c in next(csv.reader([header_row], delimiter=hdr_delim))
        ]
        expected_num_fields = len(header_cols)

        date_columns = [
            index
            for index, column in enumerate(header_cols)
            if column.lower() == "date/time"
        ]
        if len(date_columns) != 1:
            raise DiverOfficeParseError(
                filename,
                "CSV header must contain exactly one Date/time column",
                header_row_idx + 1,
                raw_rows[header_row_idx],
            )
        if (
            declared_channels is not None
            and expected_num_fields != declared_channels + 1
        ):
            raise DiverOfficeParseError(
                filename,
                f"CSV header has {expected_num_fields - 1} channels but file "
                f"declares {declared_channels}",
                header_row_idx + 1,
                raw_rows[header_row_idx],
            )

        metadata_outputs = {
            mapped
            for index, header in data_headers.items()
            if index != 0 and (mapped := mapped_output_name(header)) is not None
        }
        date_col_idx = date_columns[0]
        header_data_headers = {date_col_idx: "date_time"}
        header_outputs: set[str] = set()
        for colidx, colname in enumerate(header_cols):
            if colidx == date_col_idx:
                continue
            mapped = mapped_output_name(colname)
            if mapped is None:
                continue
            if mapped in header_outputs:
                raise DiverOfficeParseError(
                    filename,
                    f"CSV header maps more than one column to {mapped}",
                    header_row_idx + 1,
                    raw_rows[header_row_idx],
                )
            header_outputs.add(mapped)
            header_data_headers[colidx] = colname
        if metadata_outputs and metadata_outputs != header_outputs:
            raise DiverOfficeParseError(
                filename,
                "CSV header channels disagree with channel metadata",
                header_row_idx + 1,
                raw_rows[header_row_idx],
            )

        return header_data_headers, expected_num_fields, date_col_idx, hdr_delim

    @staticmethod
    def _read_identity(
        metadata: dict[str, dict[str, str]],
    ) -> tuple[str, str | None, str]:
        """Return the (utc_offset, serial_number, location) identity fields."""
        # Each field moved between sections across DiverOffice generations, so
        # every known location is tried in priority order. For the UTC offset the
        # classic format stores it as 'instrument number', while the newer format
        # uses 'utc offset (hh:mm)' in 'channel identification'.
        utc_offset = _first_metadata_value(
            metadata,
            (
                ("logger settings", "instrument number"),
                ("series settings", "instrument number"),
                ("channel identification", "utc offset (hh:mm)"),
                ("flat", "instrument number"),
            ),
        )
        serial_raw = _first_metadata_value(
            metadata,
            (
                ("logger settings", "serial number"),
                ("series settings", "serial number"),
                ("flat", "serial number"),
            ),
        )
        serial_number = DiverOfficeParser._extract_diver_serial(serial_raw)
        location = _first_metadata_value(
            metadata,
            (
                ("logger settings", "location"),
                ("series settings", "location"),
                ("channel identification", "location"),
                ("flat", "location"),
            ),
        )
        return utc_offset, serial_number, location

    @staticmethod
    def _slice_data_rows(
        rows: list[str],
        raw_rows: list[str],
        data_start_row: int,
        filename: str,
    ) -> tuple[list[_SourceLine], list[str], str]:
        """Return the data block as (source_lines, data_rows, count_row)."""
        # Walk backwards by index rather than over rows[::-1]: the marker is on
        # the last line or not at all, so the loop breaks almost immediately,
        # while the reversed slice copies the whole file's line list first.
        stop_row = None
        for true_rownr in range(len(rows) - 1, data_start_row, -1):
            if rows[true_rownr].lower().strip().startswith("end of data"):
                stop_row = true_rownr
                break
        data_stop = stop_row if stop_row is not None else len(raw_rows)
        source_lines = [
            _SourceLine(number=index + 1, text=raw_rows[index])
            for index in range(data_start_row, data_stop)
        ]
        data_rows = [source.text.strip() for source in source_lines]

        count_row = rows[data_start_row - 1] if data_start_row > 0 else ""
        if count_row.isdigit() and int(count_row) != len(source_lines):
            raise DiverOfficeParseError(
                filename,
                f"declared {int(count_row)} data rows but found {len(source_lines)}",
                data_start_row,
                raw_rows[data_start_row - 1],
            )
        return source_lines, data_rows, count_row

    @staticmethod
    def _build_column_selection(
        data_headers: dict[int, str],
        date_col_idx: int,
        mapped_output_name: Callable[[str], str | None],
    ) -> tuple[list[int], list[str]]:
        """Return the (usecols, colnames) pair pandas reads the data with."""
        usecols = []
        colnames = []
        seen_outcols: set[str] = set()
        for k, v in sorted(data_headers.items()):
            if v == "date_time":
                continue
            outcol = mapped_output_name(v)
            if outcol is not None and outcol not in seen_outcols:
                usecols.append(k)
                colnames.append(outcol)
                seen_outcols.add(outcol)

        colnames.insert(0, "date_time")
        usecols.insert(0, date_col_idx)
        # pandas requires usecols sorted ascending
        sorted_pairs = sorted(zip(usecols, colnames))
        usecols = [pair[0] for pair in sorted_pairs]
        colnames = [pair[1] for pair in sorted_pairs]
        return usecols, colnames

    @staticmethod
    def _delimiter_is_at_timestamp_boundary(
        source_lines: list[_SourceLine],
        delimiter: str,
    ) -> bool:
        """Return whether every data row places the delimiter after the date/time."""
        # Compiled once: the pattern is loop-invariant, and rebuilding it per row
        # costs an re.escape, an f-string and a regex-cache lookup per data row.
        pattern = re.compile(rf"^\s*\S+\s+[^\s{re.escape(delimiter)}]+")
        for source in source_lines:
            timestamp = pattern.match(source.text)
            if timestamp is None or not source.text[timestamp.end() :].startswith(
                delimiter
            ):
                return False
        return True

    @staticmethod
    def parse(path: str, charset: str) -> ParsedLoggerFile:
        return DiverOfficeParser._parse(
            path,
            charset,
            col_map=_DIVEROFFICE_DEFAULT_COL_MAP,
            kind=LoggerDataKind.WATER_LEVEL,
        )

    @staticmethod
    def _parse(
        path: str,
        charset: str,
        *,
        col_map: dict[str, str],
        kind: LoggerDataKind,
    ) -> ParsedLoggerFile:
        def mapped_output_name(header: str) -> str | None:
            normalized = header.lower().replace(" ", "")
            for keyword, outcol in col_map.items():
                if keyword in normalized:
                    return outcol
            return None

        filename = os.path.basename(path)
        parsed_metadata = DiverOfficeParser._read_metadata(path, charset)
        metadata = parsed_metadata.sections
        raw_rows = parsed_metadata.raw_rows
        rows = parsed_metadata.rows
        data_start_row = parsed_metadata.data_start_row

        utc_offset, serial_number, location = DiverOfficeParser._read_identity(metadata)

        def make_result(data: pd.DataFrame) -> ParsedLoggerFile:
            return ParsedLoggerFile(
                data=_canonical_frame(data),
                filename=filename,
                source_path=path,
                kind=kind,
                location=location or None,
                serial_number=serial_number,
                source_timezone=utc_offset or None,
            )

        data_headers = {0: "date_time"}
        for section_name, section_values in metadata.items():
            m = re.search("channel ([0-9]+)", section_name)
            if m is not None:
                secno = m.groups()[0]
                colname = section_values.get("identification", "")
                if colname:
                    data_headers[int(secno)] = colname

        declared_channels = DiverOfficeParser._resolve_declared_channels(
            metadata, data_headers, filename
        )

        if data_start_row is None:
            message_utils.MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "LoggerImport",
                    "Diveroffice import warning. See log message panel",
                ),
                log_msg=QCoreApplication.translate(
                    "LoggerImport",
                    "Warning, the file %s \ndid not have Date/time as a "
                    "header and will be skipped.",
                )
                % ru(path),
            )
            raise DiverOfficeParseError(filename, "Date/time header not found")

        is_csv = path.lower().endswith(".csv")
        source_lines, data_rows, count_row = DiverOfficeParser._slice_data_rows(
            rows, raw_rows, data_start_row, filename
        )
        date_col_idx = 0  # .mon files: date/time is always at column index 0
        delimiter = None
        header_delimiter = None
        expected_num_fields = max(data_headers) + 1

        if is_csv:
            header_row_idx = data_start_row - 1
            if header_row_idx >= 0:
                (
                    data_headers,
                    expected_num_fields,
                    date_col_idx,
                    header_delimiter,
                ) = DiverOfficeParser._resolve_csv_header(
                    rows,
                    raw_rows,
                    header_row_idx,
                    data_headers,
                    declared_channels,
                    mapped_output_name,
                    filename,
                )

        delimiter = file_utils.get_delimiter_from_file_rows(
            data_rows,
            delimiters=["\t", ";", ","],
            num_fields=expected_num_fields,
            filename=filename,
            allow_ragged_rows=True,
        )
        if count_row.isdigit() and delimiter is not None:
            # Counted MON data can itself be delimited. Distinguish that from
            # fixed-width values containing decimal commas at the unambiguous
            # timestamp boundary.
            delimiter_at_boundary = (
                DiverOfficeParser._delimiter_is_at_timestamp_boundary(
                    source_lines, delimiter
                )
            )
            if not delimiter_at_boundary:
                delimiter = None
        if delimiter is None and is_csv:
            delimiter = header_delimiter

        usecols, colnames = DiverOfficeParser._build_column_selection(
            data_headers, date_col_idx, mapped_output_name
        )

        if "head_cm" in col_map.values() and "head_cm" not in colnames:
            message_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "LoggerImport",
                    "Diveroffice import warning. See log message panel",
                ),
                log_msg=QCoreApplication.translate(
                    "LoggerImport",
                    "Warning, the file %s \ndid not have Water head as a "
                    "channel.\nMake sure its barocompensated!",
                )
                % path,
            )
        if delimiter is not None:
            df = DiverOfficeParser._read_delimited_data(
                source_lines,
                delimiter,
                expected_num_fields,
                usecols,
                colnames,
                date_col_idx,
                filename,
            )
        else:
            df = DiverOfficeParser._read_mon_data(
                source_lines,
                expected_num_fields,
                usecols,
                colnames,
                filename,
            )
        if len(colnames) == 1:
            return make_result(empty_logger_frame())
        return make_result(df)


class DiverOfficeBaroParser:
    """Parser for DiverOffice barometric logger files."""

    @staticmethod
    def parse(path: str, charset: str) -> ParsedLoggerFile:
        return DiverOfficeParser._parse(
            path,
            charset,
            col_map=_DIVEROFFICE_BARO_COL_MAP,
            kind=LoggerDataKind.BAROMETRIC,
        )


def _strict_numeric_series(
    values: pd.Series,
    *,
    filename: str,
    column: str,
) -> pd.Series:
    converted, invalid_position = _coerce_numeric_column(values)
    if invalid_position is not None:
        raise FileError(
            QCoreApplication.translate(
                "LoggerImport",
                "Invalid numeric value %s in column %s of file %s (data row %s).",
            )
            % (values.iloc[invalid_position], column, filename, invalid_position + 1)
        )
    return converted.astype("float64")


class LeveloggerParser:
    """Parser for Levelogger data wizard CSV files."""

    @staticmethod
    def _col1_value(col1: list[str], key: str) -> str | None:
        try:
            index = col1.index(key)
        except ValueError:
            pass
        else:
            if index + 1 < len(col1):
                return col1[index + 1].strip() or None
        for cell in col1:
            if cell.startswith(key):
                return cell[len(key) :].strip() or None
        return None

    @staticmethod
    def parse(path: str, charset: str) -> ParsedLoggerFile:
        filename = os.path.basename(path)
        with open(path, encoding=str(charset)) as handle:
            rows_unsplit = [row.strip("\r\n").lstrip() for row in handle]

        try:
            header_index = next(
                index
                for index, row in enumerate(rows_unsplit)
                if row.startswith("Date")
            )
        except StopIteration as error:
            raise FileError(
                QCoreApplication.translate(
                    "LoggerImport", "File %s could not be parsed."
                )
                % filename
            ) from error

        delimiter = file_utils.get_delimiter_from_file_rows(
            rows_unsplit[header_index:],
            filename=filename,
            delimiters=[";", ","],
            num_fields=None,
        )
        if delimiter is None:
            raise FileError(f"Could not determine delimiter in {filename}")
        rows = [next(csv.reader([row], delimiter=delimiter)) for row in rows_unsplit]
        col1 = [row[0] if row else "" for row in rows]
        location = LeveloggerParser._col1_value(col1, "Location:")
        serial_number = LeveloggerParser._col1_value(col1, "Serial_number:")

        level_factor = 100.0
        try:
            level_unit_index = col1.index("LEVEL")
            level_unit = col1[level_unit_index + 1].split(":", 1)[1].strip()
        except (ValueError, IndexError):
            level_unit = None
        if level_unit == "cm":
            level_factor = 1.0
        elif level_unit not in (None, "m"):
            message_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "LoggerImport",
                    "The unit for level wasn't m or cm, a factor of %s was used. "
                    "Check the imported data.",
                )
                % str(level_factor)
            )

        header = rows[header_index]
        if "Date" not in header or "Time" not in header:
            raise FileError(f"Date and Time columns not found in {filename}")
        source_rows = rows[header_index + 1 :]
        if not source_rows:
            data = empty_logger_frame()
        else:
            if any(len(row) != len(header) for row in source_rows):
                raise FileError(f"Ragged data row in {filename}")
            source = pd.DataFrame(source_rows, columns=header)
            combined_dates = (
                source["Date"].astype("string").str.strip()
                + " "
                + source["Time"].astype("string").str.strip()
            )
            parsed_dates = _parse_explicit_datetimes(
                combined_dates,
                (
                    "%Y-%m-%d %H:%M:%S",
                    "%Y/%m/%d %H:%M:%S",
                    "%d/%m/%Y %H:%M:%S",
                ),
            )
            if parsed_dates.isna().any():
                row_index = int(parsed_dates.isna().to_numpy().nonzero()[0][0])
                raise FileError(
                    f"Invalid date/time in {filename} data row {row_index + 1}"
                )

            data = pd.DataFrame({"date_time": parsed_dates})
            column_specs = {
                "head_cm": ("LEVEL", level_factor),
                "temp_degc": ("TEMPERATURE", 1.0),
            }
            conductivity_column = next(
                (
                    column
                    for column in (
                        "spec. conductivity (uS/cm)",
                        "spec. conductivity (mS/cm)",
                    )
                    if column in source.columns
                ),
                None,
            )
            if conductivity_column is not None:
                factor = 0.001 if "uS/cm" in conductivity_column else 1.0
                column_specs["cond_mscm"] = (conductivity_column, factor)
            for target, (source_column, factor) in column_specs.items():
                if source_column in source.columns:
                    data[target] = _strict_numeric_series(
                        source[source_column],
                        filename=filename,
                        column=source_column,
                    ) * float(factor)
            data = _canonical_frame(data)

        return ParsedLoggerFile(
            data=data,
            filename=filename,
            source_path=path,
            kind=LoggerDataKind.WATER_LEVEL,
            location=location,
            serial_number=serial_number,
        )


class HoboParser:
    """Parser for quoted HOBO temperature logger CSV files."""

    @staticmethod
    def parse(path: str, charset: str) -> ParsedLoggerFile:
        filename = os.path.basename(path)
        with open(path, encoding=str(charset)) as handle:
            rows = [
                ru(row, keep_containers=True)
                for row in csv.reader(handle, delimiter=",", quotechar='"')
            ]

        try:
            header_index = next(
                index for index, row in enumerate(rows) if "Date Time" in "_".join(row)
            )
        except StopIteration as error:
            raise FileError(
                QCoreApplication.translate(
                    "LoggerImport", "File %s could not be parsed."
                )
                % filename
            ) from error
        header = rows[header_index]
        date_columns = [
            index for index, column in enumerate(header) if "Date Time" in column
        ]
        temperature_columns = [
            index for index, column in enumerate(header) if "Temp, °C" in column
        ]
        if len(date_columns) != 1 or len(temperature_columns) != 1:
            raise FileError(f"Required HOBO columns not found uniquely in {filename}")
        date_index = date_columns[0]
        temperature_index = temperature_columns[0]
        source_timezone = get_tz_string(header[date_index])
        if source_timezone is None:
            message_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "LoggerImport", "Timezone not found in %s"
                )
                % filename
            )

        location_match = re.search(r"LBL: ([A-Za-z0-9_\-]+)", header[temperature_index])
        location = location_match.group(1) if location_match else filename
        serial_match = re.search(r"LGR S/N:\s*(\w+)", header[temperature_index])
        serial_number = serial_match.group(1) if serial_match else None

        source_rows = rows[header_index + 1 :]
        if not source_rows:
            data = empty_logger_frame()
        else:
            if any(len(row) != len(header) for row in source_rows):
                raise FileError(f"Ragged data row in {filename}")
            source = pd.DataFrame(source_rows, columns=header)
            parsed_dates = source.iloc[:, date_index].map(
                lambda value: fix_date(value, filename)
            )
            data = pd.DataFrame(
                {
                    "date_time": pd.to_datetime(parsed_dates),
                    "temp_degc": _strict_numeric_series(
                        source.iloc[:, temperature_index],
                        filename=filename,
                        column=header[temperature_index],
                    ),
                }
            )
            data = _canonical_frame(data)

        return ParsedLoggerFile(
            data=data,
            filename=filename,
            source_path=path,
            kind=LoggerDataKind.WATER_LEVEL,
            location=location,
            serial_number=serial_number,
            source_timezone=source_timezone,
        )
