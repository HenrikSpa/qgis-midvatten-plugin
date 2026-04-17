"""
Unified logger data importer for DiverOffice, Levelogger, and HOBO formats.

Replaces import_diveroffice.py, import_levelogger.py, import_hobologger.py.
"""

from __future__ import annotations

import csv
import datetime
import os
import re
import traceback
from datetime import datetime as _datetime

import qgis.PyQt
import qgis.PyQt.QtWidgets as QtWidgets
from qgis.PyQt.QtCore import QCoreApplication

from midvatten.tools import import_data_to_db
from midvatten.tools.base_importer import BaseImporter
from midvatten.tools.utils import common_utils, date_utils, db_utils, midvatten_utils
from midvatten.tools.utils.string_utils import returnunicode as ru
from midvatten.tools.utils.common_utils import format_timezone_string
from midvatten.tools.utils.date_utils import (
    find_date_format,
    datestring_to_date,
    parse_timezone_to_timedelta,
)
from midvatten.tools.utils.gui_utils import (
    VRowEntry,
    get_line,
    DateTimeFilter,
    RowEntry,
    set_combobox,
)

import pandas as pd  # pandas is a mandatory dependency of this plugin

import_ui_dialog = qgis.PyQt.uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "..", "ui", "import_fieldlogger.ui")
)[0]


# ── Helpers ───────────────────────────────────────────────────────────────────


class FileError(Exception):
    pass


def fix_date(
    date_time: str, filename: str, tz_converter: TzConverter | None = None
) -> datetime.datetime:
    """Convert a HOBO date string to a datetime, optionally converting timezone.

    Copied verbatim from import_hobologger.fix_date().
    """
    try:
        dt = datetime.datetime.strptime(date_time[:-2].rstrip(), "%m/%d/%y %I:%M:%S")
    except ValueError:
        dt = date_utils.datestring_to_date(date_time)
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

    Copied verbatim from import_hobologger.get_tz_string().

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

    # Pre-parse the last-date for each obsid once (not once per row).
    last_dates_parsed: dict[str, object] = {}
    for obsid, val in obsid_last_imported_dates.items():
        last_date_str = _get_last_date_str(val)
        last_dates_parsed[obsid] = (
            datestring_to_date(last_date_str) if last_date_str is not None else None
        )

    def _is_newer(row: list[str]) -> bool:
        obsid = row[obsid_idx]
        if obsid not in obsid_last_imported_dates:
            return True
        last_date = last_dates_parsed.get(obsid)
        if last_date is None:
            return True
        return datestring_to_date(row[date_time_idx]) > last_date

    filtered_file_data = [row for row in file_data[1:] if _is_newer(row)]

    filtered_file_data.insert(0, file_data[0])
    return filtered_file_data


# ── GUI components ─────────────────────────────────────────────────────────────


class TzConverter(RowEntry):
    """Timezone selector widget for HOBO logger imports.

    Copied verbatim from import_hobologger.TzConverter (inherits RowEntry).
    """

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
            self.layout.addWidget(widget)

        self.target_tz = "GMT+1"

        self.layout.addStretch()

    def convert_datetime(self, date_time: datetime.datetime) -> datetime.datetime:
        if self.source_tz is None:
            return date_time

        source_td = date_utils.parse_timezone_to_timedelta(self.source_tz)
        target_td = date_utils.parse_timezone_to_timedelta(self.target_tz)

        diff = target_td - source_td

        if diff == 0:
            return date_time
        else:
            new_date = date_utils.datestring_to_date(date_time) + diff
            return new_date

    @property
    def target_tz(self):
        return self._tz_list.currentText()

    @target_tz.setter
    def target_tz(self, value):
        set_combobox(self._tz_list, value)


class CheckboxAndExplanation(VRowEntry):
    """A checkbox widget with an optional explanatory label below it.

    Copied verbatim from import_diveroffice.CheckboxAndExplanation
    (inherits VRowEntry).
    """

    def __init__(self, checkbox_label, explanation=None):
        super().__init__()
        self.checkbox = qgis.PyQt.QtWidgets.QCheckBox(checkbox_label)
        self.layout.addWidget(self.checkbox)
        self.label = qgis.PyQt.QtWidgets.QLabel()

        if explanation:
            self.label.setText(explanation)
            self.layout.addWidget(self.label)

    @property
    def checked(self):
        return self.checkbox.isChecked()

    @checked.setter
    def checked(self, check=True):
        self.checkbox.setChecked(check)


# ── Parser classes ─────────────────────────────────────────────────────────────


class DiverOfficeParser:
    """Parser for Diver-Office .mon and .csv logger files.

    Handles two metadata formats:
    - ``[Logger settings]`` / ``[Channel N]`` sections with ``key=value`` pairs
    - ``[Channel identification]`` sections with ``key;value`` pairs
    """

    @staticmethod
    def parse(
        path: str,
        charset: str,
        skip_rows_without_water_level: bool = False,
        begindate: str | None = None,
        enddate: str | None = None,
    ) -> tuple[list, str, str, str | None]:
        """Parse a Diver-Office .mon or .csv file.

        Returns ``(filedata, filename, location, utc_offset)``.

        Based on DiverofficeImport.parse_diveroffice_file() with the following
        changes:
        - ``pandas_on`` guard removed (pandas is mandatory).
        - Metadata key-value separator extended to handle both ``=`` and ``;``.
        - Additional metadata keys looked up: ``utc offset (hh:mm)`` and
          ``location`` in the ``channel identification`` section.
        """
        filedata = []
        filename = os.path.basename(path)
        section = None
        data_start_row = None
        metadata = {}
        # Parse metadata
        with open(path, encoding=str(charset)) as f:
            rows = [ru(rawrow).rstrip("\n").rstrip("\r").strip() for rawrow in f]

        for rownr, row in enumerate(rows):
            if path.lower().endswith(".csv") and row.startswith("Date/time"):
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

        # Resolve location
        location = metadata.get("logger settings", {}).get("location", "")
        if not location:
            location = metadata.get("series settings", {}).get("location", "")
        if not location:
            location = metadata.get("channel identification", {}).get("location", "")

        data_headers = {0: "date_time"}
        for section, data in metadata.items():
            m = re.search("channel ([0-9]+)", section)
            if m is not None:
                secno = m.groups()[0]
                colname = data.get("identification", "")
                if colname:
                    data_headers[int(secno)] = colname

        stop_row = None
        for inv_rownr, row in enumerate(rows[::-1]):
            true_rownr = len(rows) - inv_rownr - 1
            if true_rownr == data_start_row:
                break
            if row.lower().strip().startswith("end of data"):
                stop_row = true_rownr
                break
        if stop_row is not None:
            skipfooter = len(rows) - stop_row
        else:
            skipfooter = 0

        # When no [Channel N] sections found, derive column names from the header row
        if len(data_headers) == 1 and data_start_row is not None:
            # data_start_row points to the first data row; header is one row before
            header_row_idx = data_start_row - 1
            if header_row_idx >= 0:
                header_row = rows[header_row_idx]
                # Determine the delimiter for this header row
                if "\t" in header_row:
                    hdr_delim = "\t"
                elif ";" in header_row:
                    hdr_delim = ";"
                else:
                    hdr_delim = ","
                header_cols = [c.strip() for c in header_row.split(hdr_delim)]
                for colidx, colname in enumerate(header_cols):
                    if colidx == 0:
                        continue  # Already mapped to date_time
                    col_lower = colname.lower()
                    if (
                        "level" in col_lower
                        or "waterhead" in col_lower.replace(" ", "")
                        or "water head" in col_lower
                    ):
                        data_headers[colidx] = "LEVEL"
                    elif "temp" in col_lower:
                        data_headers[colidx] = "TEMPERATURE"
                    elif "cond" in col_lower:
                        data_headers[colidx] = "CONDUCTIVITY"

        delimiter = common_utils.get_delimiter_from_file_rows(
            rows[data_start_row:stop_row] if stop_row else rows[data_start_row:],
            delimiters=[
                "\t",
                ";",
                ",",
                "        ",
                "       ",
                "      ",
                "     ",
                "    ",
                "   ",
                "  ",
            ],
            num_fields=len(data_headers),
            filename=filename,
        )

        usecols = []
        colnames = []
        for k, v in sorted(data_headers.items()):
            if "level" in v.lower() or "waterhead" in v.lower().replace(" ", ""):
                usecols.append(k)
                colnames.append("head_cm")
            elif "temp" in v.lower():
                usecols.append(k)
                colnames.append("temp_degc")
            elif "cond" in v.lower():
                usecols.append(k)
                colnames.append("cond_mscm")

        if colnames:
            colnames.insert(0, "date_time")
            usecols.insert(0, 0)

        if "head_cm" not in colnames:
            common_utils.MessagebarAndLog.warning(
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
            # Nothing to read — return empty result
            return filedata, filename, location, utc_offset or None

        df = pd.read_csv(
            path,
            sep=delimiter,
            encoding=charset,
            usecols=usecols,
            names=colnames,
            skipfooter=skipfooter,
            skiprows=data_start_row,
            parse_dates=["date_time"],
            engine="python",
        )
        for col in df.columns[1:]:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(",", ".").str.strip(), errors="coerce"
            )

        if not df.empty:
            if begindate is not None:
                df = df.loc[(df["date_time"] >= begindate), :]
            if enddate is not None:
                df = df.loc[df["date_time"] <= enddate, :]

            if df.empty:
                return filedata, filename, location, utc_offset or None

        if skip_rows_without_water_level:
            df = df.dropna(subset=["head_cm"])
            if df.empty:
                return filedata, filename, location, utc_offset or None

        df["date_time"] = df["date_time"].dt.strftime("%Y-%m-%d %H:%M:%S")
        # Replaces NaN with None
        df = df.astype(object).where(pd.notnull(df), None)

        filedata = [["date_time", "head_cm", "temp_degc", "cond_mscm"]]
        for c in filedata[0]:
            if c not in df.columns:
                df[c] = None
        # Convert numeric values to strings (None stays None) for consistent
        # downstream handling; the date_time column is already a string.
        for col in filedata[0][1:]:
            if col in df.columns:
                df[col] = df[col].apply(lambda v: str(v) if v is not None else None)
        filedata.extend(df.loc[:, filedata[0]].values.tolist())
        if len(filedata) < 2:
            return common_utils.ask_user_about_stopping(
                QCoreApplication.translate(
                    "LoggerImport",
                    "Failure, parsing failed for file %s\nNo valid data "
                    "found!\nDo you want to stop the import? "
                    "(else it will continue with the next file)",
                )
                % path
            )

        return filedata, filename, location, utc_offset or None

    @staticmethod
    def parse_old(
        path: str,
        charset: str,
        skip_rows_without_water_level: bool = False,
        begindate: str | None = None,
        enddate: str | None = None,
    ) -> (
        tuple[list[list[str]], str, str, str]
        | str
        | tuple[list[list[str]], str, str, None]
    ):
        """Parse a legacy Diver-Office CSV file.

        Returns ``(filedata, filename, location, utc_offset)``.

        Copied verbatim from DiverofficeImport.parse_diveroffice_file_old().
        """
        translation_dict_in_order = {
            "Date/time": "date_time",
            "Water head[cm]": "head_cm",
            "Level[cm]": "head_cm",
            "Temperature[°C]": "temp_degc",
            "Conductivity[mS/cm]": "cond_mscm",
            "1:Conductivity[mS/cm]": "cond_mscm",
            "2:Spec.cond.[mS/cm]": "cond_mscm",
            "Conductivity[ms/cm]": "cond_mscm",
            "1:Conductivity[ms/cm]": "cond_mscm",
            "2:Spec.cond.[ms/cm]": "cond_mscm",
        }

        filedata = []
        begin_extraction = False
        utc_offset = None

        data_rows = []
        with open(path, encoding=str(charset)) as f:
            location = None
            for rawrow in f:
                rawrow = ru(rawrow)
                row = rawrow.rstrip("\n").rstrip("\r").lstrip()

                # Try to get location
                if row.startswith("Location"):
                    location = row.split("=")[1].strip()
                    continue

                if row.lower().startswith("Instrument number".lower()):
                    try:
                        utc_offset = row.split("=")[1].strip()
                    except IndexError:
                        pass
                    continue

                # Parse header
                if "Date/time" in row:
                    begin_extraction = True

                if begin_extraction:
                    if row and "end of data" not in row.lower():
                        data_rows.append(row)

        if not begin_extraction:
            common_utils.MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "LoggerImport",
                    "Diveroffice import warning. See log message panel",
                ),
                log_msg=QCoreApplication.translate(
                    "LoggerImport",
                    "Warning, the file %s \ndid not have Date/time as a "
                    "header and will be skipped.\nSupported headers are %s",
                )
                % (ru(path), ", ".join(list(translation_dict_in_order.keys()))),
            )
            return "skip"

        if len(data_rows[0].split(",")) > len(data_rows[0].split(";")):
            delimiter = ","
        else:
            delimiter = ";"

        file_header = data_rows[0].split(delimiter)
        nr_of_cols = len(file_header)

        if nr_of_cols < 2:
            common_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "LoggerImport",
                    "Diveroffice import warning. See log message panel",
                ),
                log_msg=QCoreApplication.translate(
                    "LoggerImport",
                    "Delimiter could not be found for file %s or it "
                    "contained only one column, skipping it.",
                )
                % path,
            )
            return "skip"

        translated_header = [
            translation_dict_in_order.get(col, None) for col in file_header
        ]
        if "head_cm" not in translated_header:
            common_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "LoggerImport",
                    "Diveroffice import warning. See log message panel",
                ),
                log_msg=QCoreApplication.translate(
                    "LoggerImport",
                    "Warning, the file %s \ndid not have Water head[cm] "
                    "as a header.\nMake sure its barocompensated!\n"
                    "Supported headers are %s",
                )
                % (ru(path), ", ".join(list(translation_dict_in_order.keys()))),
            )
            if skip_rows_without_water_level:
                return "skip"

        new_header = ["date_time", "head_cm", "temp_degc", "cond_mscm"]
        colnrs_to_import = [
            translated_header.index(x) if x in translated_header else None
            for x in new_header
        ]
        date_col = colnrs_to_import[0]
        filedata.append(new_header)

        errors = set()
        skipped_rows = 0
        for row in data_rows[1:]:
            cols = row.split(delimiter)
            if len(cols) != nr_of_cols:
                return common_utils.ask_user_about_stopping(
                    QCoreApplication.translate(
                        "LoggerImport",
                        "Failure: The number of data columns in file %s "
                        "was not equal to the header.\nIs the decimal separator "
                        "the same as the delimiter?\nDo you want to stop the "
                        "import? (else it will continue with the next file)",
                    )
                    % path
                )

            dateformat = find_date_format(cols[date_col])

            if dateformat is not None:
                date = _datetime.strptime(cols[date_col], dateformat)

                if begindate is not None:
                    if date < begindate:
                        continue
                if enddate is not None:
                    if date > enddate:
                        continue

                if skip_rows_without_water_level:
                    try:
                        float(
                            cols[translated_header.index("head_cm")].replace(",", ".")
                        )
                    except Exception:
                        skipped_rows += 1
                        continue

                printrow = [_datetime.strftime(date, "%Y-%m-%d %H:%M:%S")]

                try:
                    printrow.extend(
                        [
                            (
                                (
                                    str(float(cols[colnr].replace(",", ".")))
                                    if cols[colnr]
                                    else ""
                                )
                                if colnr is not None
                                else ""
                            )
                            for colnr in colnrs_to_import
                            if colnr != date_col
                        ]
                    )
                except ValueError as e:
                    errors.add(
                        QCoreApplication.translate(
                            "LoggerImport", "parse_diveroffice_file error: %s"
                        )
                        % str(e)
                    )
                    continue

                if any(printrow[1:]):
                    filedata.append(printrow)
        if errors:
            common_utils.MessagebarAndLog.warning(
                log_msg=QCoreApplication.translate(
                    "LoggerImport",
                    'Error messages while parsing file "%s":\n%s',
                )
                % (path, "\n".join(errors))
            )

        if len(filedata) < 2:
            return common_utils.ask_user_about_stopping(
                QCoreApplication.translate(
                    "LoggerImport",
                    "Failure, parsing failed for file %s\n"
                    "No valid data found!\nDo you want to stop the import?"
                    " (else it will continue with the next file)",
                )
                % path
            )

        filename = os.path.basename(path)

        return filedata, filename, location, utc_offset


class LeveloggerParser:
    """Parser for Levelogger data wizard CSV files."""

    @staticmethod
    def parse(
        path: str,
        charset: str,
        skip_rows_without_water_level: bool = False,
        begindate: str | None = None,
        enddate: str | None = None,
    ) -> tuple[list, str, str | None, None]:
        """Parse a Levelogger CSV file.

        Returns ``(filedata, filename, location, timezone)`` where timezone is
        always ``None``.

        Copied verbatim from LeveloggerImport.parse_levelogger_file() with the
        addition of a fallback for ``Location: value`` on the same line (the
        original parser only handles the two-line ``Location:\\nvalue`` format).
        """
        filedata = []
        location = None
        timezone = None
        level_unit_factor_to_cm = 100
        spec_cond_factor_to_mscm = 0.001
        filename = os.path.basename(path)
        if begindate is not None:
            begindate = date_utils.datestring_to_date(begindate)
        if enddate is not None:
            enddate = date_utils.datestring_to_date(enddate)

        with open(path, encoding=str(charset)) as f:
            rows_unsplit = [row.lstrip().rstrip("\n").rstrip("\r") for row in f]

        try:
            data_header_idx = [
                rownr
                for rownr, row in enumerate(rows_unsplit)
                if row.startswith("Date")
            ][0]
        except IndexError:
            common_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "LoggerImport", """File %s could not be parsed."""
                )
                % filename
            )
            return [], filename, location, timezone

        delimiter = common_utils.get_delimiter_from_file_rows(
            rows_unsplit[data_header_idx:],
            filename=filename,
            delimiters=[";", ","],
            num_fields=None,
        )

        if delimiter is None:
            return [], filename, location, timezone

        rows = [row.split(";") for row in rows_unsplit]
        lens = set([len(row) for row in rows[data_header_idx:]])
        if len(lens) != 1 or list(lens)[0] == 1:
            # Assume that the delimiter was not ';'
            rows = [row.split(",") for row in rows_unsplit]

        col1 = [row[0] for row in rows]

        # Original parser: location is on the line AFTER "Location:"
        try:
            location_idx = col1.index("Location:")
        except ValueError:
            location_idx = None

        if location_idx is not None:
            location = col1[location_idx + 1]
        else:
            # Fallback: handle "Location: value" on the same line
            for cell in col1:
                if cell.startswith("Location:"):
                    location = cell[len("Location:") :].strip()
                    break

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
                    common_utils.MessagebarAndLog.warning(
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
            common_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "LoggerImport", """No data in file %s."""
                )
                % filename
            )
            return [], filename, location, timezone
        else:
            date_str = " ".join(
                [first_data_row[date_colnr], first_data_row[time_colnr]]
            )
            date_format = date_utils.datestring_to_date(date_str)
            if date_format is None:
                common_utils.MessagebarAndLog.warning(
                    bar_msg=QCoreApplication.translate(
                        "LoggerImport",
                        """Dateformat in file %s could not be parsed.""",
                    )
                    % filename
                )
                return [], filename, location, timezone

        for row in rows[data_header_idx + 1 :]:
            date_str = " ".join([row[date_colnr], row[time_colnr]])
            if skip_rows_without_water_level and not isinstance(
                common_utils.to_float_or_none(row[level_colnr]), float
            ):
                continue
            if begindate is not None or enddate is not None:
                row_date = date_utils.datestring_to_date(date_str, df=date_format)
                if begindate is not None and row_date < begindate:
                    continue
                if enddate is not None and row_date > enddate:
                    continue
            filedata.append(
                [
                    date_utils.long_dateformat(date_str, date_format),
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

        return filedata, filename, location, timezone


class HoboParser:
    """Parser for HOBO temperature logger CSV files."""

    @staticmethod
    def parse(
        path: str,
        charset: str,
        tz_converter: TzConverter | None = None,
        begindate: str | None = None,
        enddate: str | None = None,
    ) -> tuple[list, str, str | None, None]:
        """Parse a HOBO temperature logger CSV file.

        Returns ``(filedata, filename, location, None)`` — always a 4-tuple.

        BUG FIX: The original HobologgerImport.parse_hobologger_file() returned
        a 3-tuple which silently broke all Hobo imports when the caller unpacked
        4 values. All four return sites now add ``None`` as the fourth element.

        Copied verbatim from HobologgerImport.parse_hobologger_file() with:
        - ``self.tz_converter`` replaced by the ``tz_converter`` parameter.
        - All return statements changed to 4-tuple (add ``None``).
        """
        filedata = []
        location = None
        filename = os.path.basename(path)
        if begindate is not None:
            begindate = date_utils.datestring_to_date(begindate)
        if enddate is not None:
            enddate = date_utils.datestring_to_date(enddate)

        with open(path, encoding=str(charset)) as f:
            rows_unsplit = [row.lstrip().rstrip("\n").rstrip("\r") for row in f]
            csvreader = csv.reader(rows_unsplit, delimiter=",", quotechar='"')

        rows = [ru(row, keep_containers=True) for row in csvreader]

        try:
            data_header_idx = [
                rownr for rownr, row in enumerate(rows) if "Date Time" in "_".join(row)
            ][0]
        except IndexError:
            common_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "LoggerImport", """File %s could not be parsed."""
                )
                % filename
            )
            return [], filename, location, None  # 4-tuple fix

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
                common_utils.MessagebarAndLog.warning(
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

        new_header = ["date_time", "head_cm", "temp_degc", "cond_mscm"]
        filedata.append(new_header)

        try:
            first_data_row = rows[data_header_idx + 1]
        except IndexError:
            common_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "LoggerImport", """No data in file %s."""
                )
                % filename
            )
            return [], filename, location, None  # 4-tuple fix
        else:
            dt = first_data_row[date_colnr]
            date_format = date_utils.find_date_format(dt, suppress_error_msg=True)
            if date_format is None:
                dt = first_data_row[date_colnr][:-2].rstrip()
                date_format = date_utils.find_date_format(dt)
                if date_format is None:
                    common_utils.MessagebarAndLog.warning(
                        bar_msg=QCoreApplication.translate(
                            "LoggerImport",
                            """Dateformat in file %s could not be parsed.""",
                        )
                        % filename
                    )
                    return [], filename, location, None  # 4-tuple fix

        for row in rows[data_header_idx + 1 :]:
            dt = fix_date(row[date_colnr], filename, tz_converter)
            if begindate is not None and dt < begindate:
                continue
            if enddate is not None and dt > enddate:
                continue
            filedata.append(
                [
                    date_utils.long_dateformat(dt),
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

        return filedata, filename, location, None  # 4-tuple fix


# ── Dialog class ──────────────────────────────────────────────────────────────


class LoggerImport(BaseImporter, import_ui_dialog):
    """Unified logger data importer for DiverOffice, Levelogger, and HOBO formats.

    Replaces DiverofficeImport, LeveloggerImport, and HobologgerImport with a
    single dialog that includes a format selector and shows format-specific help
    text inline (instead of the pre-import wall-of-text Askuser dialogs).
    """

    FORMAT_DIVEROFFICE = "DiverOffice"
    FORMAT_LEVELOGGER = "Levelogger"
    FORMAT_HOBO = "Hobo"

    def __init__(self, iface, ms):
        self.files = []
        # BaseImporter.__init__(iface, ms) calls QMainWindow.__init__(self, iface.mainWindow())
        # internally and sets self.iface = iface, self.ms = ms, self.status = True.
        super().__init__(iface, ms)
        self.setWindowTitle(QCoreApplication.translate("LoggerImport", "Logger import"))
        # Do NOT call load_gui() here — widgets are built lazily in show().
        # Tests call load_gui() directly to avoid opening a real window.

    def show(self) -> None:
        """Entry point called by the plugin dispatcher — builds widgets then shows."""
        self.load_gui()
        super().show()
        self.activateWindow()

    # ── GUI construction ─────────────────────────────────────────────────────

    def load_gui(self) -> None:
        # Format selector
        format_row = RowEntry()
        format_label = QtWidgets.QLabel(
            QCoreApplication.translate("LoggerImport", "Logger format:")
        )
        self.format_combo = QtWidgets.QComboBox()
        self.format_combo.addItems(
            [
                self.FORMAT_DIVEROFFICE,
                self.FORMAT_LEVELOGGER,
                self.FORMAT_HOBO,
            ]
        )
        format_row.layout.addWidget(format_label)
        format_row.layout.addWidget(self.format_combo)
        self.add_row(format_row.widget)
        self.add_row(get_line())

        # Date/time filter (all formats)
        self.date_time_filter = DateTimeFilter(calendar=True)
        self.add_row(self.date_time_filter)

        # Format-specific sections (each builds a container widget shown/hidden by _on_format_changed)
        self._build_diveroffice_section()
        self._build_levelogger_section()
        self._build_hobo_section()

        self.add_row(get_line())

        # skip_rows + its separator line, grouped so both can be shown/hidden together
        self._skip_rows_container = QtWidgets.QWidget()
        _vl = QtWidgets.QVBoxLayout(self._skip_rows_container)
        _vl.setContentsMargins(0, 0, 0, 0)
        self.skip_rows = CheckboxAndExplanation(
            QCoreApplication.translate("LoggerImport", "Skip rows without water level"),
            QCoreApplication.translate(
                "LoggerImport",
                "Checked = Rows without a value for columns Water head[cm] or Level[cm] will be skipped.",
            ),
        )
        self.skip_rows.checked = True
        _vl.addWidget(self.skip_rows.widget)
        _vl.addWidget(get_line())
        self.add_row(self._skip_rows_container)

        # confirm_names
        self.confirm_names = CheckboxAndExplanation(
            QCoreApplication.translate(
                "LoggerImport", "Confirm each logger obsid before import"
            ),
            QCoreApplication.translate(
                "LoggerImport",
                "Checked = The obsid will be requested of the user for every file.\n\n"
                "Unchecked = the location attribute, both as is and capitalized, in the\n"
                "file will be matched against obsids in the database.\n\n"
                "In both cases, obsid will be requested of the user if no match in the "
                "database is found.",
            ),
        )
        self.confirm_names.checked = True
        self.add_row(self.confirm_names.widget)
        self.add_row(get_line())

        # import_all_data
        self.import_all_data = CheckboxAndExplanation(
            QCoreApplication.translate("LoggerImport", "Import all data"),
            QCoreApplication.translate(
                "LoggerImport",
                "Checked = any data not matching an exact datetime in the database\n"
                "for the corresponding obsid will be imported.\n\n"
                "Unchecked = only new data after the latest date in the database,\n"
                "for each observation point, will be imported.",
            ),
        )
        self.import_all_data.checked = False
        self.add_row(self.import_all_data.widget)

        # Optional source comment
        existing_columns = db_utils.tables_columns(table="w_levels_logger")[
            "w_levels_logger"
        ]
        series_table = db_utils.tables_columns(table="w_logger_series").get(
            "w_logger_series"
        )
        # Show source edit for:
        #   - Old/current schema: column w_levels_logger.source
        #   - New schema: w_logger_series table exists; source lives on the series row
        if "source" in existing_columns or series_table:
            self.add_row(get_line())
            self.source_row = RowEntry()
            self.source_label = QtWidgets.QLabel(
                QCoreApplication.translate(
                    "LoggerImport", "Add source comment (optional)"
                )
            )
            self.source_edit = QtWidgets.QLineEdit()
            self.source_row.layout.addWidget(self.source_label)
            self.source_row.layout.addWidget(self.source_edit)
            self.add_row(self.source_row.widget)
        else:
            self.source_edit = None

        # Buttons
        self.select_files_button = QtWidgets.QPushButton(
            QCoreApplication.translate("LoggerImport", "Select files")
        )
        self.grid_layout_buttons.addWidget(self.select_files_button, 0, 0)
        self.select_files_button.clicked.connect(self.select_files)

        self.close_after_import = QtWidgets.QCheckBox(
            QCoreApplication.translate("LoggerImport", "Close dialog after import")
        )
        self.close_after_import.setChecked(True)
        self.grid_layout_buttons.addWidget(self.close_after_import, 1, 0)

        self.start_import_button = QtWidgets.QPushButton(
            QCoreApplication.translate("LoggerImport", "Start import")
        )
        self.grid_layout_buttons.addWidget(self.start_import_button, 2, 0)
        self.start_import_button.clicked.connect(
            lambda: self.start_import(
                files=self.files,
                skip_rows_without_water_level=self.skip_rows.checked,
                confirm_names=self.confirm_names.checked,
                import_all_data=self.import_all_data.checked,
                from_date=self.date_time_filter.from_date,
                to_date=self.date_time_filter.to_date,
                export_csv=False,
                import_to_db=True,
            )
        )
        self.start_import_button.setEnabled(False)

        self.export_csv_button = QtWidgets.QPushButton(
            QCoreApplication.translate("LoggerImport", "Export csv")
        )
        self.grid_layout_buttons.addWidget(self.export_csv_button, 3, 0)
        self.export_csv_button.clicked.connect(
            lambda: self.start_import(
                files=self.files,
                skip_rows_without_water_level=self.skip_rows.checked,
                confirm_names=self.confirm_names.checked,
                import_all_data=self.import_all_data.checked,
                from_date=self.date_time_filter.from_date,
                to_date=self.date_time_filter.to_date,
                export_csv=True,
                import_to_db=False,
            )
        )
        self.export_csv_button.setEnabled(False)

        self.grid_layout_buttons.setRowStretch(4, 1)
        self.main_vertical_layout.addStretch()
        self.setGeometry(500, 150, 1200, 700)

        # Wire format change AFTER all widgets are built
        self.format_combo.currentTextChanged.connect(self._on_format_changed)
        self._on_format_changed(self.format_combo.currentText())

    def _build_diveroffice_section(self) -> None:
        """Build DiverOffice-specific section (help text + UTC offset). Hidden for other formats."""
        self._diveroffice_section = QtWidgets.QWidget()
        _vl = QtWidgets.QVBoxLayout(self._diveroffice_section)
        _vl.setContentsMargins(0, 0, 0, 0)

        _help = QtWidgets.QLabel(
            QCoreApplication.translate(
                "LoggerImport",
                "DiverOffice format: semicolon or comma separated.\n"
                "Data header must contain 'Date/time' and at least one of:\n"
                "Water head[cm], Temperature[\u00b0C], Level[cm], Conductivity[mS/cm].\n"
                "Column names matter; column order does not.",
            )
        )
        _help.setWordWrap(True)
        _vl.addWidget(_help)

        self.utcoffset_label = QtWidgets.QLabel(
            QCoreApplication.translate(
                "LoggerImport", "Identify and change UTC offset:"
            )
        )
        self.utc_offset = QtWidgets.QComboBox()
        self.utc_offset.setToolTip(
            QCoreApplication.translate(
                "LoggerImport",
                "Identifies UTC-offset in file and changes to the selected one.",
            )
        )
        self.utc_offset.addItem("")
        self.utc_offset.addItems(
            [format_timezone_string(hour) for hour in range(-12, 15)]
        )
        database_timezone = db_utils.get_timezone_from_db("w_levels_logger")
        if database_timezone is not None:
            set_combobox(self.utc_offset, database_timezone, add_if_not_exists=False)
        self.utcoffset_row = RowEntry()
        self.utcoffset_row.layout.addWidget(self.utcoffset_label)
        self.utcoffset_row.layout.addWidget(self.utc_offset)
        _vl.addWidget(self.utcoffset_row.widget)

        self.add_row(self._diveroffice_section)

    def _build_levelogger_section(self) -> None:
        """Build Levelogger-specific section (help text only). Hidden for other formats."""
        self._levelogger_section = QtWidgets.QWidget()
        _vl = QtWidgets.QVBoxLayout(self._levelogger_section)
        _vl.setContentsMargins(0, 0, 0, 0)

        _help = QtWidgets.QLabel(
            QCoreApplication.translate(
                "LoggerImport",
                "Levelogger format: CSV exported from the Levelogger data wizard.\n"
                "Header must contain 'Date', 'Time', and at least one of:\n"
                "LEVEL, TEMPERATURE, spec. conductivity.\n"
                "LEVEL unit (cm or m) is read from the row after 'LEVEL'.",
            )
        )
        _help.setWordWrap(True)
        _vl.addWidget(_help)
        self.add_row(self._levelogger_section)

    def _build_hobo_section(self) -> None:
        """Build Hobo-specific section (help text + TzConverter). Hidden for other formats."""
        self._hobo_section = QtWidgets.QWidget()
        _vl = QtWidgets.QVBoxLayout(self._hobo_section)
        _vl.setContentsMargins(0, 0, 0, 0)

        _help = QtWidgets.QLabel(
            QCoreApplication.translate(
                "LoggerImport",
                "Hobo format: UTF-8 CSV from HOBO logger.\n"
                'First row: "Plot Title: <name>"\n'
                'Second row: "#","Date Time, GMT+HH:MM","Temp, \u00b0C (...LBL: obsid)"\n'
                "obsid is read from the LBL tag in the temperature column header.",
            )
        )
        _help.setWordWrap(True)
        _vl.addWidget(_help)

        self.tz_converter = TzConverter()
        _vl.addWidget(self.tz_converter.widget)
        self.add_row(self._hobo_section)

    def _on_format_changed(self, format_name: str) -> None:
        """Show/hide format-specific widgets and update window title."""
        is_diveroffice = format_name == self.FORMAT_DIVEROFFICE
        is_hobo = format_name == self.FORMAT_HOBO

        self._diveroffice_section.setVisible(is_diveroffice)
        self._levelogger_section.setVisible(format_name == self.FORMAT_LEVELOGGER)
        self._hobo_section.setVisible(is_hobo)

        self._skip_rows_container.setVisible(not is_hobo)
        self.skip_rows.checked = not is_hobo

        titles = {
            self.FORMAT_DIVEROFFICE: QCoreApplication.translate(
                "LoggerImport", "Logger import \u2014 DiverOffice"
            ),
            self.FORMAT_LEVELOGGER: QCoreApplication.translate(
                "LoggerImport", "Logger import \u2014 Levelogger"
            ),
            self.FORMAT_HOBO: QCoreApplication.translate(
                "LoggerImport", "Logger import \u2014 Hobo"
            ),
        }
        self.setWindowTitle(titles.get(format_name, "Logger import"))

        self.files = []
        self.start_import_button.setEnabled(False)
        self.export_csv_button.setEnabled(False)

    # ── File selection ───────────────────────────────────────────────────────

    @common_utils.general_exception_handler
    def select_files(self) -> None:
        """Open file picker. Encoding is handled automatically in start_import()."""
        format_name = self.format_combo.currentText()
        extension = (
            "csv (*.csv);;mon (*.mon)"
            if format_name == self.FORMAT_DIVEROFFICE
            else "csv (*.csv)"
        )
        files = midvatten_utils.select_files(only_one_file=False, extension=extension)
        if not files:
            raise common_utils.UserInterruptError()

        self.files = files
        self.start_import_button.setEnabled(True)
        self.export_csv_button.setEnabled(True)

    # ── Import logic ─────────────────────────────────────────────────────────

    @common_utils.general_exception_handler
    @import_data_to_db.import_exception_handler
    def start_import(
        self,
        files,
        skip_rows_without_water_level,
        confirm_names,
        import_all_data,
        from_date=None,
        to_date=None,
        export_csv=False,
        import_to_db=True,
    ):
        common_utils.start_waiting_cursor()
        parsed_files = []
        format_name = self.format_combo.currentText()

        default_charset = "utf-8"
        fallback_charset = "cp1252"

        for selected_file in files:
            filename = os.path.basename(selected_file)

            parse_kwargs = dict(
                path=selected_file,
                begindate=from_date,
                enddate=to_date,
            )
            if format_name == self.FORMAT_DIVEROFFICE:
                parse_func = (
                    DiverOfficeParser.parse_old
                    if selected_file.endswith(".csv")
                    else DiverOfficeParser.parse
                )
                parse_kwargs["skip_rows_without_water_level"] = (
                    skip_rows_without_water_level
                )
            elif format_name == self.FORMAT_LEVELOGGER:
                parse_func = LeveloggerParser.parse
                parse_kwargs["skip_rows_without_water_level"] = (
                    skip_rows_without_water_level
                )
            else:  # FORMAT_HOBO
                parse_func = HoboParser.parse
                parse_kwargs["tz_converter"] = self.tz_converter

            try:
                res = parse_func(charset=default_charset, **parse_kwargs)
            except UnicodeDecodeError:
                try:
                    res = parse_func(charset=fallback_charset, **parse_kwargs)
                except UnicodeDecodeError:
                    common_utils.MessagebarAndLog.warning(
                        bar_msg=QCoreApplication.translate(
                            "LoggerImport",
                            "Could not read %s \u2014 is this a %s file?",
                        )
                        % (filename, format_name)
                    )
                    continue
            except Exception:
                common_utils.MessagebarAndLog.critical(
                    bar_msg=QCoreApplication.translate(
                        "LoggerImport", "Error on file %s."
                    )
                    % selected_file,
                    log_msg=traceback.format_exc(),
                )
                raise

            if res == "cancel":
                self.status = True
                common_utils.stop_waiting_cursor()
                return res
            elif res in ("skip", "ignore"):
                continue

            try:
                file_data, filename, location, file_utc_offset = res
            except Exception as e:
                common_utils.MessagebarAndLog.warning(
                    bar_msg=QCoreApplication.translate(
                        "LoggerImport", "Import error, see log message panel"
                    ),
                    log_msg=QCoreApplication.translate(
                        "LoggerImport", "File %s could not be parsed. Msg:\n%s"
                    )
                    % (selected_file, str(e)),
                )
                continue

            # UTC offset adjustment (DiverOffice only)
            if format_name == self.FORMAT_DIVEROFFICE and self.utc_offset.currentText():
                if not file_utc_offset:
                    common_utils.MessagebarAndLog.warning(
                        log_msg=QCoreApplication.translate(
                            "LoggerImport", "UTC-offset not found in file %s"
                        )
                        % filename
                    )
                else:
                    requested_timedelta = parse_timezone_to_timedelta(
                        self.utc_offset.currentText()
                    )
                    try:
                        file_timedelta = parse_timezone_to_timedelta(file_utc_offset)
                    except ValueError as e:
                        msg = QCoreApplication.translate(
                            "LoggerImport",
                            "Reading timezone in file %s failed,\n"
                            " no conversion done:\n%s\n\nSkip file?",
                        ) % (ru(selected_file), str(e))
                        common_utils.stop_waiting_cursor()
                        question = common_utils.Askuser(
                            question="YesNo",
                            msg=msg,
                            dialogtitle=QCoreApplication.translate(
                                "askuser", "File timezone error!"
                            ),
                            include_cancel_button=True,
                        )
                        common_utils.start_waiting_cursor()
                        if question.result:
                            continue
                    else:
                        if requested_timedelta != file_timedelta:
                            td = file_timedelta - requested_timedelta
                            df = pd.DataFrame.from_records(
                                file_data[1:],
                                index="date_time",
                                columns=file_data[0],
                            )
                            df.index = pd.to_datetime(df.index) - td
                            df.index = df.index.strftime("%Y-%m-%d %H:%M:%S")
                            file_data = [["date_time"]]
                            file_data[0].extend(df.columns.tolist())
                            file_data.extend([list(row) for row in df.itertuples()])

            parsed_files.append((file_data, filename, location))

        if len(parsed_files) == 0:
            common_utils.MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "LoggerImport", "Import Failure: No files imported"
                )
            )
            common_utils.stop_waiting_cursor()
            return

        # Add obsid to all parsed filedatas by asking the user for it.
        filename_location_obsid = [["filename", "location", "obsid"]]
        filename_location_obsid.extend(
            [
                [parsed_file[1], parsed_file[2], parsed_file[2]]
                for parsed_file in parsed_files
            ]
        )

        try_capitalize = not confirm_names

        existing_obsids = db_utils.get_all_obsids()
        common_utils.stop_waiting_cursor()
        filename_location_obsid = common_utils.filter_nonexisting_values_and_ask(
            file_data=filename_location_obsid,
            header_value="obsid",
            existing_values=existing_obsids,
            try_capitalize=try_capitalize,
            always_ask_user=confirm_names,
        )
        common_utils.start_waiting_cursor()

        if len(filename_location_obsid) < 2:
            common_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "LoggerImport",
                    "Warning. All files were skipped, nothing imported!",
                )
            )
            common_utils.stop_waiting_cursor()
            return False

        filenames_obsid = {x[0]: x[2] for x in filename_location_obsid[1:]}

        parsed_files_with_obsid = []
        for file_data, filename, location in parsed_files:
            if not file_data:
                common_utils.MessagebarAndLog.warning(
                    bar_msg=QCoreApplication.translate(
                        "LoggerImport",
                        "Diveroffice import warning. See log message panel",
                    ),
                    log_msg=QCoreApplication.translate(
                        "LoggerImport",
                        "No data parsed from file %s. Remove rows without the correct number of columns.",
                    )
                    % filename,
                )
                continue

            if filename in filenames_obsid:
                file_data = list(file_data)
                obsid = filenames_obsid[filename]
                file_data[0].append("obsid")
                for row in file_data[1:]:
                    row.append(obsid)
                parsed_files_with_obsid.append([file_data, filename, location])

        if not parsed_files_with_obsid:
            common_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "LoggerImport", "Warning. All files were skipped, nothing imported!"
                )
            )
            common_utils.stop_waiting_cursor()
            return False

        # Schema variant detection. In the new schema, source has moved to a
        # w_logger_series row that groups all rows from one imported file.
        # In older schemas, source is still a column on w_levels_logger. We
        # keep supporting both so users don't have to migrate to keep using
        # this importer.
        wlogger_cols = db_utils.tables_columns(table="w_levels_logger").get(
            "w_levels_logger", []
        )
        has_series_id = "series_id" in wlogger_cols
        has_created_at = "created_at" in wlogger_cols
        has_source_column = "source" in wlogger_cols

        source_text = (
            self.source_edit.text().strip() if self.source_edit is not None else ""
        )

        # New-schema import path: create one w_logger_series row per imported
        # file and tag every row from that file with its new series_id and a
        # single batch-level created_at.
        if import_to_db and has_series_id:
            source_for_series = source_text or None
            batch_created_at = _datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            dbconn = db_utils.DbConnectionManager()
            try:
                ph = dbconn.placeholder()
                for parsed_file in parsed_files_with_obsid:
                    file_data = parsed_file[0]
                    filename = parsed_file[1]
                    obsid = filenames_obsid[filename]
                    description = (
                        os.path.basename(filename) if filename else None
                    )
                    dbconn.execute(
                        f"INSERT INTO w_logger_series "
                        f"(obsid, source, description) VALUES ({ph}, {ph}, {ph})",
                        (obsid, source_for_series, description),
                    )
                    series_id = db_utils.get_last_insert_id(dbconn)
                    file_data[0].append("series_id")
                    if has_created_at:
                        file_data[0].append("created_at")
                    for row in file_data[1:]:
                        row.append(series_id)
                        if has_created_at:
                            row.append(batch_created_at)
                dbconn.commit()
            finally:
                dbconn.closedb()

        file_to_import_to_db = [parsed_files_with_obsid[0][0][0]]
        file_to_import_to_db.extend(
            [
                row
                for parsed_file in parsed_files_with_obsid
                for row in parsed_file[0][1:]
            ]
        )

        if not import_all_data:
            file_to_import_to_db = filter_dates_from_filedata(
                file_to_import_to_db, db_utils.get_last_logger_dates()
            )
        if len(file_to_import_to_db) < 2:
            common_utils.MessagebarAndLog.info(
                bar_msg=QCoreApplication.translate(
                    "LoggerImport",
                    "No new data existed in the files. Nothing imported.",
                )
            )
            self.status = True
            common_utils.stop_waiting_cursor()
            return True

        # Old-schema path: source is a column on w_levels_logger itself.
        # Only append it if we are NOT on the new schema (the new path
        # already put source on the w_logger_series row).
        if (
            source_text
            and has_source_column
            and not has_series_id
            and self.source_edit is not None
        ):
            file_to_import_to_db[0].append("source")
            for row in file_to_import_to_db[1:]:
                row.append(source_text)

        if import_to_db:
            importer = import_data_to_db.MidvDataImporter()
            try:
                importer.general_import("w_levels_logger", file_to_import_to_db)
            except Exception:
                common_utils.MessagebarAndLog.warning(
                    log_msg=f"Got error {traceback.format_exc()}"
                )
                raise
        if export_csv:
            path = QtWidgets.QFileDialog.getSaveFileName(
                self, "Save File", "", "CSV(*.csv)"
            )
            if path:
                path = ru(path[0])
                common_utils.write_printlist_to_file(path, file_to_import_to_db)

        common_utils.stop_waiting_cursor()

        if self.close_after_import.isChecked():
            self.close()
