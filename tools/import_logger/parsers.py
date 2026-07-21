"""
Parser classes and helpers for DiverOffice, Levelogger, and HOBO logger formats.
"""

from __future__ import annotations

import csv
import datetime
import os
import re
from dataclasses import dataclass
from io import StringIO

import qgis.PyQt.QtWidgets as QtWidgets
from qgis.PyQt.QtCore import QCoreApplication

import pandas as pd  # pandas is a mandatory dependency of this plugin

from midvatten.tools.utils import (
    common_utils,
    date_utils,
    dialog_utils,
    file_utils,
    message_utils,
)
from midvatten.tools.utils.string_utils import returnunicode as ru
from midvatten.tools.utils.common_utils import format_timezone_string
from midvatten.tools.utils.date_utils import to_date
from midvatten.tools.utils.gui_utils import (
    RowEntry,
    set_combobox,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


class FileError(Exception):
    pass


def fix_date(
    date_time: str, filename: str, tz_converter: TzConverter | None = None
) -> datetime.datetime:
    """Convert a HOBO date string to a datetime, optionally converting timezone."""
    try:
        dt = datetime.datetime.strptime(date_time[:-2].rstrip(), "%m/%d/%y %I:%M:%S")
    except ValueError:
        dt = date_utils.to_date(date_time)
        if dt is None:
            raise FileError(
                QCoreApplication.translate(
                    "LoggerImport",
                    """Dateformat in file %s could not be parsed.""",
                )
                % filename
            )
    else:
        dt_end = date_time[-2:]
        if dt_end.lower() in ("em", "pm"):
            dt = date_utils.dateshift(dt, 12, "hours")

    if tz_converter is not None:
        dt = tz_converter.convert_datetime(dt)

    return dt


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
    if not match:
        return None
    else:
        return match.group(1)


def _get_last_date_str(last_dates_value: object) -> str | None:
    """Normalise the different shapes that ``obsid_last_imported_dates`` values
    can take:
    - ``[('2016-09-28',)]``  — from ``db_utils.get_last_logger_dates()``
    - ``'2016-09-28'``       — plain string (used in tests)
    """
    if last_dates_value is None:
        return None
    if isinstance(last_dates_value, str):
        return last_dates_value
    # Assume list-of-tuple: [(date_str,), ...]
    try:
        return last_dates_value[0][0]
    except (IndexError, TypeError):
        return str(last_dates_value)


def filter_dates_from_filedata(
    file_data: list[list[str]],
    obsid_last_imported_dates: dict[str, object],
    obsid_header_name: str = "obsid",
    date_time_header_name: str = "date_time",
) -> list[list[str]]:
    """Return only rows with dates strictly after the last imported date for
    each obsid.

    Accepts two value formats for *obsid_last_imported_dates*:

    * ``{'obs1': [('2016-09-28',)]}`` — produced by
      ``db_utils.get_last_logger_dates()``
    * ``{'obs1': '2016-09-28'}`` — plain string (used in tests)

    >>> filter_dates_from_filedata([['obsid', 'date_time'], ['obs1', '2016-09-28'], ['obs1', '2016-09-29']], {'obs1': [('2016-09-28', )]})
    [['obsid', 'date_time'], ['obs1', '2016-09-29']]
    """
    if len(file_data) == 1:
        return file_data

    obsid_idx = file_data[0].index(obsid_header_name)
    date_time_idx = file_data[0].index(date_time_header_name)

    last_dates_parsed: dict[str, object] = {}
    for obsid, val in obsid_last_imported_dates.items():
        last_date_str = _get_last_date_str(val)
        last_dates_parsed[obsid] = (
            to_date(last_date_str) if last_date_str is not None else None
        )

    data_rows = file_data[1:]
    row_dates = date_utils.to_dates([row[date_time_idx] for row in data_rows])

    filtered_file_data = []
    for row, row_date in zip(data_rows, row_dates):
        obsid = row[obsid_idx]
        if obsid not in obsid_last_imported_dates:
            filtered_file_data.append(row)
            continue
        last_date = last_dates_parsed.get(obsid)
        if last_date is None:
            filtered_file_data.append(row)
            continue
        if row_date is not None and row_date > last_date:
            filtered_file_data.append(row)

    filtered_file_data.insert(0, file_data[0])
    return filtered_file_data


# ── GUI components ─────────────────────────────────────────────────────────────


class TzConverter(RowEntry):
    """Timezone selector widget for HOBO logger imports."""

    def __init__(self):
        super().__init__()
        self.source_tz = None
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

    def convert_datetime(self, date_time: datetime.datetime) -> datetime.datetime:
        if self.source_tz is None:
            return date_time

        source_td = date_utils.parse_timezone_to_timedelta(self.source_tz)
        target_td = date_utils.parse_timezone_to_timedelta(self.target_tz)

        diff = target_td - source_td

        if diff == 0:
            return date_time
        else:
            new_date = date_utils.to_date(date_time) + diff
            return new_date

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
    "temp": "temperature",
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
        parsed_dates = pd.to_datetime(
            converted_frame.iloc[:, date_col_idx], errors="coerce"
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
            normalized = raw.astype("string").str.strip()
            normalized = normalized.mask(normalized == "")
            normalized = normalized.str.replace(",", ".", regex=False)
            converted = pd.to_numeric(normalized, errors="coerce")
            invalid = normalized.notna() & converted.isna()
            if invalid.any():
                row_index = int(invalid.to_numpy().nonzero()[0][0])
                source = source_lines[row_index]
                raise DiverOfficeParseError(
                    filename,
                    f"invalid numeric value {raw.iloc[row_index]!r}",
                    source.number,
                    source.text,
                )
            column = converted_frame.columns[col_idx]
            converted_frame[column] = converted
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
    def parse(
        path: str,
        charset: str,
        col_map: dict[str, str] | None = None,
        output_cols: list[str] | None = None,
        skip_rows_without_water_level: bool = False,
        begindate: str | None = None,
        enddate: str | None = None,
        interactive: bool = True,
    ) -> tuple[list, str, str, str | None, str | None]:
        """Parse a Diver-Office .mon or .csv file.

        Returns ``(filedata, filename, location, utc_offset, serial_number)``.

        ``col_map`` maps space-stripped lowercase keywords to output column names.
        ``output_cols`` fixes the column order in the returned filedata (None-filled
        when absent); defaults to water-level columns when not supplied.
        """
        _col_map = col_map if col_map is not None else _DIVEROFFICE_DEFAULT_COL_MAP
        _output_cols = (
            output_cols
            if output_cols is not None
            else ["date_time", "head_cm", "temp_degc", "cond_mscm"]
        )

        def mapped_output_name(header: str) -> str | None:
            normalized = header.lower().replace(" ", "")
            for keyword, outcol in _col_map.items():
                if keyword in normalized:
                    return outcol
            return None

        filedata = []
        filename = os.path.basename(path)
        section = None
        data_start_row = None
        metadata = {}
        # Parse metadata
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

        # Resolve UTC offset: classic format stores it as 'instrument number',
        # newer format uses 'utc offset (hh:mm)' in 'channel identification'.
        utc_offset = metadata.get("logger settings", {}).get("instrument number", "")
        if not utc_offset:
            utc_offset = metadata.get("series settings", {}).get(
                "instrument number", ""
            )
        if not utc_offset:
            utc_offset = metadata.get("channel identification", {}).get(
                "utc offset (hh:mm)", ""
            )
        if not utc_offset:
            utc_offset = metadata.get("flat", {}).get("instrument number", "")

        serial_raw = metadata.get("logger settings", {}).get("serial number", "")
        if not serial_raw:
            serial_raw = metadata.get("series settings", {}).get("serial number", "")
        if not serial_raw:
            serial_raw = metadata.get("flat", {}).get("serial number", "")
        serial_number = DiverOfficeParser._extract_diver_serial(serial_raw)

        # Resolve location
        location = metadata.get("logger settings", {}).get("location", "")
        if not location:
            location = metadata.get("series settings", {}).get("location", "")
        if not location:
            location = metadata.get("channel identification", {}).get("location", "")
        if not location:
            location = metadata.get("flat", {}).get("location", "")

        data_headers = {0: "date_time"}
        for section, data in metadata.items():
            m = re.search("channel ([0-9]+)", section)
            if m is not None:
                secno = m.groups()[0]
                colname = data.get("identification", "")
                if colname:
                    data_headers[int(secno)] = colname

        declared_channels: int | None = None
        declared_channels_raw = metadata.get("logger settings", {}).get(
            "number of channels", ""
        ) or metadata.get("series settings", {}).get("number of channels", "")
        if declared_channels_raw:
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
            return filedata, filename, location, utc_offset or None, serial_number

        stop_row = None
        for inv_rownr, row in enumerate(rows[::-1]):
            true_rownr = len(rows) - inv_rownr - 1
            if true_rownr == data_start_row:
                break
            if row.lower().strip().startswith("end of data"):
                stop_row = true_rownr
                break
        is_csv = path.lower().endswith(".csv")
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
        date_col_idx = 0  # .mon files: date/time is always at column index 0
        delimiter = None
        header_delimiter = None
        expected_num_fields = max(data_headers) + 1

        if is_csv:
            # The CSV header is authoritative. A data row may legitimately have
            # a missing measurement and must not influence header detection.
            header_row_idx = data_start_row - 1
            if header_row_idx >= 0:
                header_row = rows[header_row_idx]
                hdr_delim = file_utils.get_delimiter_from_file_rows(
                    [header_row],
                    delimiters=["\t", ";", ","],
                    filename=filename,
                )
                if hdr_delim is None:
                    hdr_delim = ","
                header_delimiter = hdr_delim
                header_cols = [
                    c.strip()
                    for c in next(csv.reader([header_row], delimiter=hdr_delim))
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
                data_headers = header_data_headers

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
            delimiter_at_boundary = True
            for source in source_lines:
                timestamp = re.match(
                    rf"^\s*\S+\s+[^\s{re.escape(delimiter)}]+", source.text
                )
                if timestamp is None or not source.text[timestamp.end() :].startswith(
                    delimiter
                ):
                    delimiter_at_boundary = False
                    break
            if not delimiter_at_boundary:
                delimiter = None
        if delimiter is None and is_csv:
            delimiter = header_delimiter

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

        if colnames:
            colnames.insert(0, "date_time")
            usecols.insert(0, date_col_idx)
            # pandas requires usecols sorted ascending
            sorted_pairs = sorted(zip(usecols, colnames))
            usecols = [p[0] for p in sorted_pairs]
            colnames = [p[1] for p in sorted_pairs]

        if "head_cm" in _col_map.values() and "head_cm" not in colnames:
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
            if skip_rows_without_water_level:
                return "skip"

        if not colnames:
            return filedata, filename, location, utc_offset or None, serial_number

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
        if not df.empty:
            if begindate is not None:
                df = df.loc[(df["date_time"] >= begindate), :]
            if enddate is not None:
                df = df.loc[df["date_time"] <= enddate, :]

            if df.empty:
                return filedata, filename, location, utc_offset or None, serial_number

        if skip_rows_without_water_level and "head_cm" in df.columns:
            df = df.dropna(subset=["head_cm"])
            if df.empty:
                return filedata, filename, location, utc_offset or None, serial_number

        df["date_time"] = df["date_time"].dt.strftime("%Y-%m-%d %H:%M:%S")
        df = df.astype(object).where(pd.notnull(df), None)

        filedata = [_output_cols]
        for c in _output_cols:
            if c not in df.columns:
                df[c] = None
        for col in _output_cols[1:]:
            if col in df.columns:
                df[col] = df[col].apply(lambda v: str(v) if v is not None else None)
        filedata.extend(df.loc[:, _output_cols].values.tolist())
        if len(filedata) < 2:
            if not interactive:
                return filedata, filename, location, utc_offset or None, serial_number
            return dialog_utils.ask_user_about_stopping(
                QCoreApplication.translate(
                    "LoggerImport",
                    "Failure, parsing failed for file %s\nNo valid data "
                    "found!\nDo you want to stop the import? "
                    "(else it will continue with the next file)",
                )
                % path
            )

        return filedata, filename, location, utc_offset or None, serial_number


class DiverOfficeBaroParser:
    """Parser for Diver-Office barometric logger files (TD-Diver baro).

    Same file format as DiverOfficeParser; maps Pressure[cmH2O] →
    ``baro_cmh2o`` and Temperature → ``temperature`` for import into ``meteo``.
    """

    @staticmethod
    def parse(
        path: str,
        charset: str,
        begindate: str | None = None,
        enddate: str | None = None,
        interactive: bool = True,
    ) -> tuple[list, str, str, str | None, str | None]:
        """Parse a DiverOffice baro file (.mon or .csv).

        Returns ``(filedata, filename, location, utc_offset, serial_number)``
        where filedata has header ``['date_time', 'baro_cmh2o', 'temperature']``.
        """
        return DiverOfficeParser.parse(
            path,
            charset,
            col_map=_DIVEROFFICE_BARO_COL_MAP,
            output_cols=["date_time", "baro_cmh2o", "temperature"],
            begindate=begindate,
            enddate=enddate,
            interactive=interactive,
        )


# Column → (meteo parameter, unit) mapping for baro imports
_BARO_COL_TO_METEO: dict[str, tuple[str, str]] = {
    "baro_cmh2o": ("pressure", "cmH2O"),
    "temperature": ("temp", "\u00b0C"),
}

# Parameters that must exist in zz_meteoparam for baro imports
# ("temp" is always seeded by insert_datadomain.sql — only "pressure" needs checking)
_BARO_METEO_PARAMS: list[tuple[str, str]] = [
    ("pressure", "Barometric pressure"),
]


def _pivot_baro_to_meteo(
    file_data: list[list],
    serial_number: str | None,
    filename: str,
) -> list[list]:
    """Convert wide baro filedata (date_time, baro_cmh2o, temperature, obsid)
    to meteo long format (obsid, instrumentid, parameter, date_time,
    reading_num, unit).
    """
    instrumentid = serial_number or filename
    header = file_data[0]
    meteo_rows: list[list] = [
        ["obsid", "instrumentid", "parameter", "date_time", "reading_num", "unit"]
    ]
    for row in file_data[1:]:
        row_dict = dict(zip(header, row))
        obsid = row_dict.get("obsid", "")
        date_time = row_dict.get("date_time", "")
        for col, (param, unit) in _BARO_COL_TO_METEO.items():
            val = row_dict.get(col)
            if val is not None:
                meteo_rows.append([obsid, instrumentid, param, date_time, val, unit])
    return meteo_rows


class LeveloggerParser:
    """Parser for Levelogger data wizard CSV files."""

    @staticmethod
    def _col1_value(col1: list[str], key: str) -> str | None:
        try:
            idx = col1.index(key)
            return col1[idx + 1].strip() or None
        except ValueError:
            pass
        for cell in col1:
            if cell.startswith(key):
                return cell[len(key) :].strip() or None
        return None

    @staticmethod
    def parse(
        path: str,
        charset: str,
        skip_rows_without_water_level: bool = False,
        begindate: str | None = None,
        enddate: str | None = None,
    ) -> tuple[list, str, str | None, None, str | None]:
        """Parse a Levelogger CSV file.

        Returns ``(filedata, filename, location, timezone, serial_number)`` where
        timezone is always ``None``.

        Also handles ``Location: value`` on a single line (the legacy format used
        only the two-line ``Location:\\nvalue`` layout).
        """
        filedata = []
        location = None
        timezone = None
        serial_number = None
        level_unit_factor_to_cm = 100
        spec_cond_factor_to_mscm = 0.001
        filename = os.path.basename(path)
        if begindate is not None:
            begindate = date_utils.to_date(begindate)
        if enddate is not None:
            enddate = date_utils.to_date(enddate)

        with open(path, encoding=str(charset)) as f:
            rows_unsplit = [row.lstrip().rstrip("\n").rstrip("\r") for row in f]

        try:
            data_header_idx = [
                rownr
                for rownr, row in enumerate(rows_unsplit)
                if row.startswith("Date")
            ][0]
        except IndexError:
            message_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "LoggerImport", """File %s could not be parsed."""
                )
                % filename
            )
            return [], filename, location, timezone, serial_number

        delimiter = file_utils.get_delimiter_from_file_rows(
            rows_unsplit[data_header_idx:],
            filename=filename,
            delimiters=[";", ","],
            num_fields=None,
        )

        if delimiter is None:
            return [], filename, location, timezone, serial_number

        rows = [next(csv.reader([row], delimiter=delimiter)) for row in rows_unsplit]

        col1 = [row[0] for row in rows]

        location = LeveloggerParser._col1_value(col1, "Location:")
        serial_number = LeveloggerParser._col1_value(col1, "Serial_number:")

        try:
            level_unit_idx = col1.index("LEVEL")
        except ValueError:
            pass
        else:
            try:
                level_unit = col1[level_unit_idx + 1].split(":")[1].lstrip()
            except IndexError:
                pass
            else:
                if level_unit == "cm":
                    level_unit_factor_to_cm = 1
                elif level_unit == "m":
                    level_unit_factor_to_cm = 100
                else:
                    level_unit_factor_to_cm = 100
                    message_utils.MessagebarAndLog.warning(
                        bar_msg=QCoreApplication.translate(
                            "LoggerImport",
                            """The unit for level wasn't m or cm, a factor of %s was used. Check the imported data.""",
                        )
                        % str(level_unit_factor_to_cm)
                    )

        file_header = rows[data_header_idx]

        new_header = ["date_time", "head_cm", "temp_degc", "cond_mscm"]
        filedata.append(new_header)

        date_colnr = file_header.index("Date")
        time_colnr = file_header.index("Time")
        try:
            level_colnr = file_header.index("LEVEL")
        except ValueError:
            level_colnr = None
        try:
            temp_colnr = file_header.index("TEMPERATURE")
        except ValueError:
            temp_colnr = None
        try:
            spec_cond_colnr = file_header.index("spec. conductivity (uS/cm)")
        except ValueError:
            try:
                spec_cond_colnr = file_header.index("spec. conductivity (mS/cm)")
            except ValueError:
                spec_cond_colnr = None
            else:
                spec_cond_factor_to_mscm = 1
        else:
            spec_cond_factor_to_mscm = 0.001

        try:
            first_data_row = rows[data_header_idx + 1]
        except IndexError:
            message_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "LoggerImport", """No data in file %s."""
                )
                % filename
            )
            return [], filename, location, timezone, serial_number
        else:
            date_str = " ".join(
                [first_data_row[date_colnr], first_data_row[time_colnr]]
            )
            if date_utils.to_date(date_str) is None:
                message_utils.MessagebarAndLog.warning(
                    bar_msg=QCoreApplication.translate(
                        "LoggerImport",
                        """Dateformat in file %s could not be parsed.""",
                    )
                    % filename
                )
                return [], filename, location, timezone, serial_number

        candidate_rows = []
        date_strings = []
        for row in rows[data_header_idx + 1 :]:
            if (
                skip_rows_without_water_level
                and level_colnr is not None
                and not isinstance(
                    common_utils.to_float_or_none(row[level_colnr]), float
                )
            ):
                continue
            date_strings.append(" ".join([row[date_colnr], row[time_colnr]]))
            candidate_rows.append(row)

        parsed_dates = date_utils.to_dates(date_strings)

        for row, row_date in zip(candidate_rows, parsed_dates):
            if row_date is None:
                continue
            if begindate is not None and row_date < begindate:
                continue
            if enddate is not None and row_date > enddate:
                continue
            filedata.append(
                [
                    row_date.strftime("%Y-%m-%d %H:%M:%S"),
                    (
                        str(
                            float(row[level_colnr].replace(",", "."))
                            * level_unit_factor_to_cm
                        )
                        if (
                            common_utils.to_float_or_none(row[level_colnr]) is not None
                            if level_colnr is not None
                            else None
                        )
                        else None
                    ),
                    (
                        str(float(row[temp_colnr].replace(",", ".")))
                        if (
                            common_utils.to_float_or_none(row[temp_colnr])
                            if temp_colnr is not None
                            else None
                        )
                        else None
                    ),
                    (
                        str(
                            float(row[spec_cond_colnr].replace(",", "."))
                            * spec_cond_factor_to_mscm
                        )
                        if (
                            common_utils.to_float_or_none(row[spec_cond_colnr])
                            if spec_cond_colnr is not None
                            else None
                        )
                        else None
                    ),
                ]
            )

        filedata = [row for row in filedata if any(row[1:])]

        return filedata, filename, location, timezone, serial_number


class HoboParser:
    """Parser for HOBO temperature logger CSV files."""

    @staticmethod
    def parse(
        path: str,
        charset: str,
        tz_converter: TzConverter | None = None,
        begindate: str | None = None,
        enddate: str | None = None,
    ) -> tuple[list, str, str | None, None, str | None]:
        """Parse a HOBO temperature logger CSV file.

        Returns ``(filedata, filename, location, None, serial_number)`` — always a 5-tuple.
        ``tz_converter``, if provided, is used to adjust timestamps to the target timezone.
        """
        filedata = []
        location = None
        serial_number = None
        filename = os.path.basename(path)
        if begindate is not None:
            begindate = date_utils.to_date(begindate)
        if enddate is not None:
            enddate = date_utils.to_date(enddate)

        with open(path, encoding=str(charset)) as f:
            rows_unsplit = [row.lstrip().rstrip("\n").rstrip("\r") for row in f]
            csvreader = csv.reader(rows_unsplit, delimiter=",", quotechar='"')

        rows = [ru(row, keep_containers=True) for row in csvreader]

        try:
            data_header_idx = [
                rownr for rownr, row in enumerate(rows) if "Date Time" in "_".join(row)
            ][0]
        except IndexError:
            message_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "LoggerImport", """File %s could not be parsed."""
                )
                % filename
            )
            return [], filename, location, None, serial_number
        date_colnr = [idx for idx, col in enumerate(rows[1]) if "Date Time" in col]
        if not date_colnr:
            raise Exception(
                QCoreApplication.translate(
                    "LoggerImport", "Date Time column not found!"
                )
            )
        else:
            date_colnr = date_colnr[0]

        if tz_converter:
            tz_string = get_tz_string(rows[1][date_colnr])
            if tz_string is None:
                message_utils.MessagebarAndLog.warning(
                    bar_msg=QCoreApplication.translate(
                        "LoggerImport", "Timezone not found in %s"
                    )
                    % filename
                )
            tz_converter.source_tz = tz_string

        temp_colnr = [idx for idx, col in enumerate(rows[1]) if "Temp, °C" in col]
        if not temp_colnr:
            raise Exception(
                QCoreApplication.translate(
                    "LoggerImport", "Temperature column not found!"
                )
            )
        else:
            temp_colnr = temp_colnr[0]

        match = re.search(r"LBL: ([A-Za-z0-9_\-]+)", rows[1][temp_colnr])
        if not match:
            location = filename
        else:
            location = match.group(1)

        sn_match = re.search(r"LGR S/N:\s*(\w+)", rows[data_header_idx][temp_colnr])
        serial_number = sn_match.group(1) if sn_match else None

        new_header = ["date_time", "head_cm", "temp_degc", "cond_mscm"]
        filedata.append(new_header)

        try:
            first_data_row = rows[data_header_idx + 1]
        except IndexError:
            message_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "LoggerImport", """No data in file %s."""
                )
                % filename
            )
            return [], filename, location, None, serial_number
        else:
            dt = first_data_row[date_colnr]
            if date_utils.to_date(dt) is None:
                dt = first_data_row[date_colnr][:-2].rstrip()
                if date_utils.to_date(dt) is None:
                    message_utils.MessagebarAndLog.warning(
                        bar_msg=QCoreApplication.translate(
                            "LoggerImport",
                            """Dateformat in file %s could not be parsed.""",
                        )
                        % filename
                    )
                    return [], filename, location, None, serial_number
        for row in rows[data_header_idx + 1 :]:
            dt = fix_date(row[date_colnr], filename, tz_converter)
            if begindate is not None and dt < begindate:
                continue
            if enddate is not None and dt > enddate:
                continue
            filedata.append(
                [
                    date_utils.to_YmdHMS(dt),
                    "",
                    (
                        str(float(row[temp_colnr].replace(",", ".")))
                        if (
                            common_utils.to_float_or_none(row[temp_colnr])
                            if temp_colnr is not None
                            else None
                        )
                        else ""
                    ),
                    "",
                ]
            )

        filedata = [row for row in filedata if any(row[1:])]

        return filedata, filename, location, None, serial_number
