import csv
import threading
from contextlib import contextmanager
from unittest import mock

import pytest
from qgis.PyQt.QtCore import QEventLoop, QThread, QTimer

from midvatten.tools.import_logger.workers import (
    LoggerDbImportRequest,
    LoggerDbImportResult,
    LoggerDbImportWorker,
    ParsedLoggerFile,
    LoggerParseRequest,
    LoggerParseWorker,
    LoggerSeriesSpec,
)
from midvatten.tools.import_logger.parsers import DiverOfficeParseError


@pytest.mark.parametrize(
    "parse_error",
    [
        DiverOfficeParseError("bad.mon", "ambiguous endpoints", 12),
        csv.Error("malformed quoted field"),
    ],
)
def test_parse_worker_collects_bad_file_and_continues(parse_error):
    request = LoggerParseRequest(
        files=("bad.mon", "good.mon"),
        format_name="DiverOffice",
        skip_rows_without_water_level=False,
        from_date=None,
        to_date=None,
        requested_utc_offset="",
        hobo_target_timezone="GMT+1",
    )
    worker = LoggerParseWorker(request)
    finished = []
    errors = []
    worker.finished.connect(finished.append)
    worker.error.connect(errors.append)
    good_file = ParsedLoggerFile(
        [["date_time", "head_cm"], ["2025-01-01 00:00:00", "1.0"]],
        "good.mon",
        "obs1",
        None,
    )

    with mock.patch.object(
        worker,
        "_parse_file",
        side_effect=[
            parse_error,
            good_file,
        ],
    ):
        worker.run()

    assert errors == []
    assert [item.filename for item in finished[0].parsed_files] == ["good.mon"]
    assert [item.filename for item in finished[0].failures] == ["bad.mon"]


def test_parse_worker_reports_unexpected_programming_error_as_terminal():
    request = LoggerParseRequest(
        files=("bad.mon", "never-reached.mon"),
        format_name="DiverOffice",
        skip_rows_without_water_level=False,
        from_date=None,
        to_date=None,
        requested_utc_offset="",
        hobo_target_timezone="GMT+1",
    )
    worker = LoggerParseWorker(request)
    finished = []
    errors = []
    worker.finished.connect(finished.append)
    worker.error.connect(errors.append)

    with mock.patch.object(worker, "_parse_file", side_effect=KeyError("bug")):
        worker.run()

    assert finished == []
    assert len(errors) == 1
    assert "KeyError" in errors[0]


class FakeConnection:
    def __init__(self, imported_row_count=1):
        self.cancelled = threading.Event()
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.executed = []
        self.imported_row_count = imported_row_count

    @contextmanager
    def transaction(self):
        try:
            yield self
        except Exception:
            self.rollbacks += 1
            raise
        else:
            self.commits += 1

    def placeholder(self):
        return "?"

    def execute(self, sql, parameters=()):
        self.executed.append((sql, parameters))

    def execute_and_fetchall(self, sql, parameters=()):
        self.executed.append((sql, parameters))
        return [(self.imported_row_count,)]

    def cancel(self):
        self.cancelled.set()

    def closedb(self):
        self.closed = True


def make_db_request(filename="logger.mon"):
    return LoggerDbImportRequest(
        filename=filename,
        dest_table="w_levels_logger",
        file_data=[
            ["date_time", "head_cm", "obsid"],
            ["2025-01-01 00:00:00", "100.308", "rb1"],
        ],
        series=LoggerSeriesSpec(
            obsid="rb1",
            source="test",
            description=filename,
            instrument="SN1",
            created_at="2026-07-21 12:00:00",
        ),
    )


def test_database_worker_commits_series_and_rows_together():
    connection = FakeConnection()
    imported_data = []
    worker = LoggerDbImportWorker({}, make_db_request())
    results = []
    worker.finished.connect(results.append)

    with (
        mock.patch(
            "midvatten.tools.import_logger.workers.db_utils.DbConnectionManager",
            return_value=connection,
        ),
        mock.patch(
            "midvatten.tools.import_logger.workers.db_utils.get_last_insert_id",
            return_value=7,
        ),
        mock.patch(
            "midvatten.tools.import_logger.workers.import_data_to_db.MidvDataImporter.general_import",
            side_effect=lambda _, data, **__: imported_data.append(data),
        ),
    ):
        worker.run()

    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert results == [LoggerDbImportResult("logger.mon", imported=True)]
    assert imported_data[0][0][-2:] == ["series_id", "created_at"]
    assert imported_data[0][1][-2:] == [7, "2026-07-21 12:00:00"]


def test_database_worker_rolls_back_series_and_rows_together():
    connection = FakeConnection()
    worker = LoggerDbImportWorker({}, make_db_request("bad.mon"))
    results = []
    errors = []
    worker.finished.connect(results.append)
    worker.error.connect(errors.append)

    with (
        mock.patch(
            "midvatten.tools.import_logger.workers.db_utils.DbConnectionManager",
            return_value=connection,
        ),
        mock.patch(
            "midvatten.tools.import_logger.workers.db_utils.get_last_insert_id",
            return_value=7,
        ),
        mock.patch(
            "midvatten.tools.import_logger.workers.import_data_to_db.MidvDataImporter.general_import",
            side_effect=RuntimeError("insert failed"),
        ),
    ):
        worker.run()

    assert connection.rollbacks == 1
    assert connection.commits == 0
    assert errors == []
    assert len(results) == 1
    assert results[0].filename == "bad.mon"
    assert not results[0].imported
    assert "insert failed" in results[0].reason


def test_database_worker_requests_insert_error_propagation():
    connection = FakeConnection()
    worker = LoggerDbImportWorker({}, make_db_request("propagate.mon"))
    results = []
    worker.finished.connect(results.append)
    fake_importer = mock.Mock()
    fake_importer.general_import.return_value = 1

    with (
        mock.patch(
            "midvatten.tools.import_logger.workers.db_utils.DbConnectionManager",
            return_value=connection,
        ),
        mock.patch(
            "midvatten.tools.import_logger.workers.db_utils.get_last_insert_id",
            return_value=7,
        ),
        mock.patch(
            "midvatten.tools.import_logger.workers.import_data_to_db.MidvDataImporter",
            return_value=fake_importer,
        ),
    ):
        worker.run()

    assert connection.commits == 1
    assert len(results) == 1
    assert results[0].imported
    assert fake_importer.general_import.call_args.kwargs["raise_insert_errors"] is True


def test_database_worker_removes_series_when_all_rows_are_duplicates():
    connection = FakeConnection(imported_row_count=0)
    worker = LoggerDbImportWorker({}, make_db_request("duplicates.mon"))
    results = []
    worker.finished.connect(results.append)

    with (
        mock.patch(
            "midvatten.tools.import_logger.workers.db_utils.DbConnectionManager",
            return_value=connection,
        ),
        mock.patch(
            "midvatten.tools.import_logger.workers.db_utils.get_last_insert_id",
            return_value=7,
        ),
        mock.patch(
            "midvatten.tools.import_logger.workers.import_data_to_db.MidvDataImporter.general_import"
        ),
    ):
        worker.run()

    assert connection.commits == 1
    assert results == [
        LoggerDbImportResult(
            "duplicates.mon", imported=False, reason="no non-duplicate rows"
        )
    ]
    assert any("DELETE FROM w_logger_series" in sql for sql, _ in connection.executed)


def test_parse_worker_keeps_gui_event_loop_responsive_and_cancels():
    parser_started = threading.Event()
    release_parser = threading.Event()

    def slow_parse(**kwargs):
        assert kwargs["interactive"] is False
        parser_started.set()
        assert release_parser.wait(timeout=2)
        return (
            [["date_time", "head_cm"], ["2020-01-01 00:00:00", "1"]],
            "logger.csv",
            "obs1",
            None,
            None,
        )

    request = LoggerParseRequest(
        files=("first.csv", "second.csv"),
        format_name="DiverOffice",
        skip_rows_without_water_level=False,
        from_date=None,
        to_date=None,
        requested_utc_offset="",
        hobo_target_timezone="GMT+1",
    )
    worker = LoggerParseWorker(request)
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.cancelled.connect(thread.quit)
    worker.error.connect(thread.quit)

    loop = QEventLoop()
    states = {"timer_fired": False, "cancelled": False, "error": None}

    def request_cancel():
        states["timer_fired"] = True
        worker.cancel()
        release_parser.set()

    def on_cancelled():
        states["cancelled"] = True
        loop.quit()

    def on_error(error):
        states["error"] = error
        loop.quit()

    worker.cancelled.connect(on_cancelled)
    worker.error.connect(on_error)
    worker.finished.connect(loop.quit)

    with mock.patch(
        "midvatten.tools.import_logger.workers.DiverOfficeParser.parse",
        side_effect=slow_parse,
    ) as parse:
        thread.start()
        assert parser_started.wait(timeout=1)
        QTimer.singleShot(10, request_cancel)
        loop.exec_()
        thread.wait()

    assert states == {"timer_fired": True, "cancelled": True, "error": None}
    assert parse.call_count == 1


def test_database_worker_interrupts_active_query_and_rolls_back():
    importer_started = threading.Event()

    class FakeImporter:
        def general_import(self, *args, progress_callback=None, **kwargs):
            importer_started.set()
            progress_callback("Checking for duplicate timestamps...")
            assert connection.cancelled.wait(timeout=2)

    connection = FakeConnection()
    worker = LoggerDbImportWorker(
        {},
        LoggerDbImportRequest(
            filename="logger.mon",
            dest_table="w_levels_logger",
            file_data=[["obsid", "date_time"]],
        ),
    )
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.cancelled.connect(thread.quit)
    worker.error.connect(thread.quit)

    loop = QEventLoop()
    states = {"cancelled": False, "finished": False, "error": None}

    def request_cancel():
        worker.cancel()

    def on_cancelled():
        states["cancelled"] = True
        loop.quit()

    def on_finished():
        states["finished"] = True
        loop.quit()

    def on_error(error):
        states["error"] = error
        loop.quit()

    worker.cancelled.connect(on_cancelled)
    worker.finished.connect(on_finished)
    worker.error.connect(on_error)

    with (
        mock.patch(
            "midvatten.tools.import_logger.workers.db_utils.DbConnectionManager",
            return_value=connection,
        ),
        mock.patch(
            "midvatten.tools.import_logger.workers.import_data_to_db.MidvDataImporter",
            return_value=FakeImporter(),
        ),
    ):
        thread.start()
        assert importer_started.wait(timeout=1)
        QTimer.singleShot(10, request_cancel)
        loop.exec_()
        thread.wait()

    assert states == {"cancelled": True, "finished": False, "error": None}
    assert connection.cancelled.is_set()
    assert connection.rollbacks == 1
    assert connection.commits == 0
    assert connection.closed
