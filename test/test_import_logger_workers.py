import threading
from unittest import mock

from qgis.PyQt.QtCore import QEventLoop, QThread, QTimer

from midvatten.tools.import_logger.workers import (
    LoggerParseRequest,
    LoggerParseWorker,
)


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
    from contextlib import contextmanager

    from midvatten.tools.import_logger.workers import LoggerDbImportWorker

    importer_started = threading.Event()

    class FakeConnection:
        def __init__(self):
            self.cancelled = threading.Event()
            self.commits = 0
            self.rollbacks = 0
            self.closed = False

        @contextmanager
        def transaction(self):
            try:
                yield self
            except Exception:
                self.rollbacks += 1
                raise
            else:
                self.commits += 1

        def cancel(self):
            self.cancelled.set()

        def closedb(self):
            self.closed = True

    class FakeImporter:
        def general_import(self, *args, progress_callback=None, **kwargs):
            importer_started.set()
            progress_callback("Checking for duplicate timestamps...")
            assert connection.cancelled.wait(timeout=2)

    connection = FakeConnection()
    worker = LoggerDbImportWorker({}, "w_levels_logger", [["obsid", "date_time"]])
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
