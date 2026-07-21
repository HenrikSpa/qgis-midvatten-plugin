"""Background workers used by the logger import dialog."""

from __future__ import annotations

import csv
import os
import threading
import traceback
from dataclasses import dataclass
from datetime import timedelta

import pandas as pd
from qgis.PyQt.QtCore import QCoreApplication, QObject, pyqtSignal, pyqtSlot

from midvatten.tools import import_data_to_db
from midvatten.tools.import_logger.parsers import (
    DiverOfficeBaroParser,
    DiverOfficeParseError,
    DiverOfficeParser,
    HoboParser,
    LeveloggerParser,
)
from midvatten.tools.utils import date_utils, db_utils, message_utils


class LoggerImportCancelledError(Exception):
    pass


class LoggerWorker(QObject):
    """Common signals and cooperative cancellation for logger workers."""

    progress = pyqtSignal(str)
    finished = pyqtSignal(object)
    cancelled = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def _check_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise LoggerImportCancelledError()


@dataclass
class ParsedLoggerFile:
    file_data: list
    filename: str
    location: str | None
    serial_number: str | None
    timezone_error: str | None = None
    source_path: str | None = None


@dataclass(frozen=True)
class LoggerFileFailure:
    filename: str
    stage: str
    reason: str


@dataclass
class LoggerParseBatchResult:
    parsed_files: list[ParsedLoggerFile]
    failures: list[LoggerFileFailure]


@dataclass(frozen=True)
class LoggerParseRequest:
    files: tuple[str, ...]
    format_name: str
    skip_rows_without_water_level: bool
    from_date: str | None
    to_date: str | None
    requested_utc_offset: str
    hobo_target_timezone: str


class _WorkerTzConverter:
    """Widget-free timezone converter for HOBO parsing."""

    def __init__(self, target_tz: str):
        self.source_tz: str | None = None
        self.target_tz = target_tz

    def convert_datetime(self, value):
        if self.source_tz is None:
            return value
        source = date_utils.parse_timezone_to_timedelta(self.source_tz)
        target = date_utils.parse_timezone_to_timedelta(self.target_tz)
        return value + (target - source)


class LoggerParseWorker(LoggerWorker):
    def __init__(self, request: LoggerParseRequest):
        super().__init__()
        self.request = request

    @pyqtSlot()
    def run(self) -> None:
        parsed_files: list[ParsedLoggerFile] = []
        failures: list[LoggerFileFailure] = []
        try:
            for file_idx, selected_file in enumerate(self.request.files):
                self._check_cancelled()
                self.progress.emit(
                    QCoreApplication.translate(
                        "LoggerImport", "Parsing file %s of %s..."
                    )
                    % (file_idx + 1, len(self.request.files))
                )
                try:
                    result = self._parse_file(selected_file)
                except LoggerImportCancelledError:
                    raise
                except (
                    DiverOfficeParseError,
                    UnicodeDecodeError,
                    OSError,
                    csv.Error,
                    pd.errors.ParserError,
                ) as error:
                    failures.append(
                        LoggerFileFailure(
                            filename=selected_file,
                            stage="parse",
                            reason=str(error),
                        )
                    )
                    continue
                self._check_cancelled()
                if result is None:
                    continue
                parsed_files.append(result)
            self.finished.emit(LoggerParseBatchResult(parsed_files, failures))
        except LoggerImportCancelledError:
            self.cancelled.emit()
        except Exception:
            self.error.emit(traceback.format_exc())

    def _parse_file(self, selected_file: str) -> ParsedLoggerFile | None:
        parse_kwargs = {
            "path": selected_file,
            "begindate": self.request.from_date,
            "enddate": self.request.to_date,
        }
        if self.request.format_name == "DiverOffice":
            parse_func = DiverOfficeParser.parse
            parse_kwargs["skip_rows_without_water_level"] = (
                self.request.skip_rows_without_water_level
            )
            parse_kwargs["interactive"] = False
        elif self.request.format_name == "DiverOffice Baro":
            parse_func = DiverOfficeBaroParser.parse
            parse_kwargs["interactive"] = False
        elif self.request.format_name == "Levelogger":
            parse_func = LeveloggerParser.parse
            parse_kwargs["skip_rows_without_water_level"] = (
                self.request.skip_rows_without_water_level
            )
        else:
            parse_func = HoboParser.parse
            parse_kwargs["tz_converter"] = _WorkerTzConverter(
                self.request.hobo_target_timezone
            )

        try:
            result = parse_func(charset="utf-8", **parse_kwargs)
        except UnicodeDecodeError:
            try:
                result = parse_func(charset="cp1252", **parse_kwargs)
            except UnicodeDecodeError:
                message_utils.MessagebarAndLog.warning(
                    bar_msg=QCoreApplication.translate(
                        "LoggerImport",
                        "Could not read %s — is this a %s file?",
                    )
                    % (os.path.basename(selected_file), self.request.format_name)
                )
                raise

        if result in ("cancel", "skip", "ignore"):
            if result == "cancel":
                raise LoggerImportCancelledError()
            return None

        file_data, filename, location, file_utc_offset, serial_number = result
        timezone_error = None
        if (
            self.request.format_name in ("DiverOffice", "DiverOffice Baro")
            and self.request.requested_utc_offset
        ):
            if not file_utc_offset:
                message_utils.MessagebarAndLog.warning(
                    log_msg=QCoreApplication.translate(
                        "LoggerImport", "UTC-offset not found in file %s"
                    )
                    % filename
                )
            else:
                requested = date_utils.parse_timezone_to_timedelta(
                    self.request.requested_utc_offset
                )
                try:
                    source = date_utils.parse_timezone_to_timedelta(file_utc_offset)
                except ValueError as exc:
                    timezone_error = str(exc)
                else:
                    if requested != source and len(file_data) > 1:
                        file_data = self._shift_file_data(file_data, source - requested)

        return ParsedLoggerFile(
            file_data=file_data,
            filename=filename,
            location=location,
            serial_number=serial_number,
            timezone_error=timezone_error,
            source_path=selected_file,
        )

    @staticmethod
    def _shift_file_data(file_data: list, offset: timedelta) -> list:
        frame = pd.DataFrame.from_records(
            file_data[1:],
            index="date_time",
            columns=file_data[0],
        )
        frame.index = pd.to_datetime(frame.index) - offset
        frame.index = frame.index.strftime("%Y-%m-%d %H:%M:%S")
        shifted = [["date_time", *frame.columns.tolist()]]
        shifted.extend([list(row) for row in frame.itertuples()])
        return shifted


@dataclass(frozen=True)
class LoggerSeriesSpec:
    obsid: str
    source: str | None
    description: str | None
    instrument: str | None
    created_at: str | None


@dataclass(frozen=True)
class LoggerDbImportRequest:
    filename: str
    dest_table: str
    file_data: list
    series: LoggerSeriesSpec | None = None


@dataclass(frozen=True)
class LoggerDbImportResult:
    filename: str
    imported: bool
    reason: str | None = None


class LoggerDbImportWorker(LoggerWorker):
    """Import one file atomically on a worker-owned connection."""

    def __init__(self, db_settings, request: LoggerDbImportRequest):
        super().__init__()
        self._db_settings = db_settings
        self.request = request
        self._connection_lock = threading.Lock()
        self._connection = None

    def cancel(self) -> None:
        super().cancel()
        with self._connection_lock:
            connection = self._connection
        if connection is not None:
            try:
                connection.cancel()
            except Exception:
                pass

    def _on_progress(self, message: str) -> None:
        self._check_cancelled()
        self.progress.emit(message)

    def _prepare_file_data(self, connection) -> tuple[list[list], int | None]:
        file_data = [list(row) for row in self.request.file_data]
        series = self.request.series
        if series is None:
            return file_data, None

        placeholder = connection.placeholder()
        connection.execute(
            "INSERT INTO w_logger_series "
            f"(obsid, source, description, instrument) VALUES ({placeholder}, "
            f"{placeholder}, {placeholder}, {placeholder})",
            (series.obsid, series.source, series.description, series.instrument),
        )
        series_id = db_utils.get_last_insert_id(connection)
        file_data[0].append("series_id")
        if series.created_at is not None:
            file_data[0].append("created_at")
        for row in file_data[1:]:
            row.append(series_id)
            if series.created_at is not None:
                row.append(series.created_at)
        return file_data, series_id

    @pyqtSlot()
    def run(self) -> None:
        connection = None
        try:
            connection = db_utils.DbConnectionManager(self._db_settings)
            with self._connection_lock:
                self._connection = connection

            self._check_cancelled()

            with connection.transaction():
                file_data, series_id = self._prepare_file_data(connection)
                importer = import_data_to_db.MidvDataImporter()
                inserted_count = importer.general_import(
                    self.request.dest_table,
                    file_data,
                    _dbconnection=connection,
                    skip_confirmation=True,
                    defer_commit=True,
                    progress_callback=self._on_progress,
                    manage_wait_cursor=False,
                    raise_insert_errors=True,
                )
                self._check_cancelled()
                result = LoggerDbImportResult(self.request.filename, True)
                if series_id is not None:
                    placeholder = connection.placeholder()
                    count = connection.execute_and_fetchall(
                        "SELECT COUNT(*) FROM w_levels_logger "
                        f"WHERE series_id = {placeholder}",
                        (series_id,),
                    )[0][0]
                    if inserted_count == 0 or count == 0:
                        connection.execute(
                            f"DELETE FROM w_logger_series WHERE id = {placeholder}",
                            (series_id,),
                        )
                        result = LoggerDbImportResult(
                            self.request.filename,
                            False,
                            "no non-duplicate rows",
                        )
                elif inserted_count == 0:
                    result = LoggerDbImportResult(
                        self.request.filename,
                        False,
                        "no non-duplicate rows",
                    )
            self.finished.emit(result)
        except Exception:
            if self._cancel_event.is_set():
                self.cancelled.emit()
            else:
                self.finished.emit(
                    LoggerDbImportResult(
                        self.request.filename,
                        False,
                        traceback.format_exc(),
                    )
                )
        finally:
            with self._connection_lock:
                self._connection = None
            if connection is not None:
                try:
                    connection.closedb()
                except Exception:
                    pass
