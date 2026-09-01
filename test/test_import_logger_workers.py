import csv
import threading
from contextlib import contextmanager
from unittest import mock

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from qgis.PyQt.QtCore import QEventLoop, QThread, QTimer

from midvatten.tools.import_logger import models, workers
from midvatten.tools.import_logger.models import (
    LoggerDataKind,
    LoggerDbImportRequest,
    LoggerDbImportResult,
    LoggerParseRequest,
    LoggerSeriesSpec,
    ParsedLoggerFile,
)
from midvatten.tools.import_logger.parsers import DiverOfficeParseError
from midvatten.tools.import_logger.workers import (
    LoggerDbImportWorker,
    LoggerParseWorker,
)


def canonical_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date_time": pd.to_datetime(["2025-01-01 00:00:00"]),
            "head_cm": [1.0],
            "temp_degc": [float("nan")],
            "cond_mscm": [float("nan")],
            "baro_cmh2o": [float("nan")],
        }
    )


def parsed_file(filename: str = "good.mon") -> ParsedLoggerFile:
    return ParsedLoggerFile(
        data=canonical_frame(),
        filename=filename,
        source_path=filename,
        kind=LoggerDataKind.WATER_LEVEL,
        location="obs1",
        serial_number=None,
    )


def parse_request(*files: str) -> LoggerParseRequest:
    return LoggerParseRequest(
        files=files,
        format_name="DiverOffice",
        skip_missing_water_head=False,
        from_date=None,
        to_date=None,
        target_timezone=None,
    )


@pytest.mark.parametrize(
    "parse_error",
    [
        DiverOfficeParseError("bad.mon", "ambiguous endpoints", 12),
        csv.Error("malformed quoted field"),
    ],
)
def test_parse_worker_collects_bad_file_and_continues(parse_error):
    worker = LoggerParseWorker(parse_request("bad.mon", "good.mon"))
    finished = []
    errors = []
    worker.finished.connect(finished.append)
    worker.error.connect(errors.append)

    with mock.patch.object(
        worker,
        "_parse_file",
        side_effect=[parse_error, parsed_file()],
    ):
        worker.run()

    assert errors == []
    assert [item.filename for item in finished[0].parsed_files] == ["good.mon"]
    assert [item.filename for item in finished[0].failures] == ["bad.mon"]


def test_parse_worker_reports_unexpected_programming_error_as_terminal():
    worker = LoggerParseWorker(parse_request("bad.mon", "never-reached.mon"))
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
        frame=pd.DataFrame(
            {
                "date_time": pd.to_datetime(["2025-01-01 00:00:00"]),
                "head_cm": [100.308],
                "obsid": ["rb1"],
            }
        ),
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
    request = make_db_request()
    original = request.frame.copy(deep=True)
    worker = LoggerDbImportWorker({}, request)
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
    assert imported_data[0][["series_id", "created_at"]].iloc[0].tolist() == [
        7,
        "2026-07-21 12:00:00",
    ]
    assert_frame_equal(request.frame, original)


def test_database_worker_rolls_back_series_and_rows_together():
    connection = FakeConnection()
    worker = LoggerDbImportWorker({}, make_db_request("bad.mon"))
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
            side_effect=RuntimeError("insert failed"),
        ),
    ):
        worker.run()

    assert connection.rollbacks == 1
    assert connection.commits == 0
    assert len(results) == 1
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

    def slow_parse(*_args):
        parser_started.set()
        assert release_parser.wait(timeout=2)
        return parsed_file("logger.csv")

    worker = LoggerParseWorker(parse_request("first.csv", "second.csv"))
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
        loop.exec()
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
            frame=pd.DataFrame(columns=["obsid", "date_time"]),
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

    worker.cancelled.connect(
        lambda: (states.__setitem__("cancelled", True), loop.quit())
    )
    worker.finished.connect(
        lambda *_: (states.__setitem__("finished", True), loop.quit())
    )
    worker.error.connect(
        lambda error: (states.__setitem__("error", error), loop.quit())
    )

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
        QTimer.singleShot(10, lambda: worker.cancel())
        loop.exec()
        thread.wait()

    assert states == {"cancelled": True, "finished": False, "error": None}
    assert connection.cancelled.is_set()
    assert connection.rollbacks == 1
    assert connection.commits == 0
    assert connection.closed


def test_no_new_rows_reason_is_shared_between_worker_and_dialog():
    # Pinning the text is the part that matters: the dialog classifies a
    # skipped file by comparing against it. Asserting `workers.X is models.X`
    # would only restate Python's import aliasing, and importing the dialog
    # here to do so drags loadUiType() into this pure worker/threading module.
    assert models.NO_NEW_ROWS_REASON == "no non-duplicate rows"
    assert workers.NO_NEW_ROWS_REASON == models.NO_NEW_ROWS_REASON
