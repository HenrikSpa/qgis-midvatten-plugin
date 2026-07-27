"""Background workers used by the logger import dialog."""

from __future__ import annotations

import csv
import os
import threading
import traceback
from dataclasses import replace

import pandas as pd
from qgis.PyQt.QtCore import QCoreApplication, QObject, pyqtSignal, pyqtSlot

from midvatten.tools import import_data_to_db
from midvatten.tools.import_logger.models import (
    NO_NEW_ROWS_REASON,
    LoggerDbImportRequest,
    LoggerDbImportResult,
    LoggerFileFailure,
    LoggerImportOptions,
    LoggerParseBatchResult,
    LoggerParseRequest,
    ParsedLoggerFile,
)
from midvatten.tools.import_logger.parsers import (
    DiverOfficeBaroParser,
    DiverOfficeParseError,
    DiverOfficeParser,
    FileError,
    HoboParser,
    LeveloggerParser,
)
from midvatten.tools.import_logger.pipeline import (
    TimezoneConversionError,
    run_pre_resolution_pipeline,
)
from midvatten.tools.utils import db_utils, message_utils


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


_PARSERS = {
    "DiverOffice": DiverOfficeParser,
    "DiverOffice Baro": DiverOfficeBaroParser,
    "Levelogger": LeveloggerParser,
    "Hobo": HoboParser,
}


class LoggerParseWorker(LoggerWorker):
    def __init__(self, request: LoggerParseRequest):
        super().__init__()
        self.request = request

    @pyqtSlot()
    def run(self) -> None:
        parsed_files: list[ParsedLoggerFile] = []
        failures: list[LoggerFileFailure] = []
        try:
            for file_index, selected_file in enumerate(self.request.files):
                self._check_cancelled()
                self.progress.emit(
                    QCoreApplication.translate(
                        "LoggerImport", "Parsing file %s of %s..."
                    )
                    % (file_index + 1, len(self.request.files))
                )
                try:
                    result = self._parse_file(selected_file)
                except LoggerImportCancelledError:
                    raise
                except (
                    DiverOfficeParseError,
                    FileError,
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
                parsed_files.append(result)
            self.finished.emit(LoggerParseBatchResult(parsed_files, failures))
        except LoggerImportCancelledError:
            self.cancelled.emit()
        except Exception:
            self.error.emit(traceback.format_exc())

    def _parse_file(self, selected_file: str) -> ParsedLoggerFile:
        parser = _PARSERS[self.request.format_name]
        try:
            parsed = parser.parse(selected_file, "utf-8")
        except UnicodeDecodeError:
            try:
                parsed = parser.parse(selected_file, "cp1252")
            except UnicodeDecodeError:
                message_utils.MessagebarAndLog.warning(
                    bar_msg=QCoreApplication.translate(
                        "LoggerImport",
                        "Could not read %s — is this a %s file?",
                    )
                    % (os.path.basename(selected_file), self.request.format_name)
                )
                raise

        options = LoggerImportOptions(
            target_timezone=self.request.target_timezone,
            from_date=self.request.from_date,
            to_date=self.request.to_date,
            skip_missing_water_head=self.request.skip_missing_water_head,
        )
        try:
            return run_pre_resolution_pipeline(parsed, options)
        except TimezoneConversionError as error:
            unshifted = run_pre_resolution_pipeline(
                parsed,
                replace(options, target_timezone=None),
            )
            return replace(unshifted, timezone_error=str(error))


class LoggerDbImportWorker(LoggerWorker):
    """Import one prepared file atomically on a worker-owned connection."""

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

    def _prepare_frame(self, connection) -> tuple[pd.DataFrame, int | None]:
        # general_import owns the defensive copy at the database boundary.
        frame = self.request.frame
        series = self.request.series
        if series is None:
            return frame, None

        placeholder = connection.placeholder()
        connection.execute(
            "INSERT INTO w_logger_series "
            f"(obsid, source, description, instrument) VALUES ({placeholder}, "
            f"{placeholder}, {placeholder}, {placeholder})",
            (series.obsid, series.source, series.description, series.instrument),
        )
        series_id = db_utils.get_last_insert_id(connection)
        assignments = {"series_id": series_id}
        if series.created_at is not None:
            assignments["created_at"] = series.created_at
        return frame.assign(**assignments), series_id

    @pyqtSlot()
    def run(self) -> None:
        connection = None
        try:
            connection = db_utils.DbConnectionManager(self._db_settings)
            with self._connection_lock:
                self._connection = connection

            self._check_cancelled()
            with connection.transaction():
                frame, series_id = self._prepare_frame(connection)
                importer = import_data_to_db.MidvDataImporter()
                inserted_count = importer.general_import(
                    self.request.dest_table,
                    frame,
                    _dbconnection=connection,
                    skip_confirmation=True,
                    defer_commit=True,
                    progress_callback=self._on_progress,
                    manage_wait_cursor=False,
                    raise_insert_errors=True,
                )
                self._check_cancelled()
                has_new_rows = inserted_count != 0
                if series_id is not None:
                    placeholder = connection.placeholder()
                    # Only worth asking when rows were actually inserted: with
                    # inserted_count == 0 the series is dropped either way, so
                    # the COUNT is a round trip that cannot change the outcome.
                    if has_new_rows:
                        has_new_rows = (
                            connection.execute_and_fetchall(
                                "SELECT COUNT(*) FROM w_levels_logger "
                                f"WHERE series_id = {placeholder}",
                                (series_id,),
                            )[0][0]
                            != 0
                        )
                    if not has_new_rows:
                        connection.execute(
                            f"DELETE FROM w_logger_series WHERE id = {placeholder}",
                            (series_id,),
                        )
                if has_new_rows:
                    result = LoggerDbImportResult(self.request.filename, True)
                else:
                    result = LoggerDbImportResult(
                        self.request.filename, False, NO_NEW_ROWS_REASON
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
