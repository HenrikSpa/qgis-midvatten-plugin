"""ExportWorker — QObject wrapper that runs ExportEngine in a QThread."""

import logging
import os
import threading
import traceback

from qgis.PyQt.QtCore import QObject, pyqtSignal, pyqtSlot

from midvatten.tools.export_engine import ExportCancelledError, ExportEngine
from midvatten.tools.utils import db_utils
from midvatten.tools.utils.db_utils import DbConnectionManager

log = logging.getLogger(__name__)


class ExportWorker(QObject):
    table_started = pyqtSignal(str, int)  # table name, total rows
    rows_written = pyqtSignal(int)  # cumulative rows for this table
    finished = pyqtSignal(str)  # stats string (empty = cancelled)
    error = pyqtSignal(str)  # traceback string

    def __init__(
        self,
        source_db_settings: str,
        dest_path: str,
        obsid_points: tuple[str, ...],
        obsid_lines: tuple[str, ...],
        dest_srid: str,
    ):
        super().__init__()
        self._source_db_settings = source_db_settings
        self._dest_path = dest_path
        self._obsid_points = obsid_points
        self._obsid_lines = obsid_lines
        self._dest_srid = dest_srid
        self._cancel_flag = threading.Event()

    def cancel(self) -> None:
        self._cancel_flag.set()

    @pyqtSlot()
    def run(self) -> None:
        source_conn: DbConnectionManager | None = None
        dest_conn: DbConnectionManager | None = None
        try:
            source_conn = DbConnectionManager(self._source_db_settings)
            source_conn.connect2db()
            db_utils.export_bytea_as_bytes(source_conn)
            dest_conn = DbConnectionManager(self._dest_path)
            dest_conn.connect2db()

            stats = ExportEngine().export(
                source_conn=source_conn,
                dest_conn=dest_conn,
                obsid_points=self._obsid_points,
                obsid_lines=self._obsid_lines,
                dest_srid=self._dest_srid,
                progress_cb=self._on_progress,
                cancel_flag=self._cancel_flag,
            )
            dest_conn.commit_and_closedb()
            dest_conn = None
            source_conn.closedb()
            source_conn = None
            self.finished.emit(stats)

        except ExportCancelledError:
            self._close_connections(source_conn, dest_conn)
            try:
                os.remove(self._dest_path)
            except OSError:
                pass
            self.finished.emit("")

        except Exception:
            self._close_connections(source_conn, dest_conn)
            self.error.emit(traceback.format_exc())

    def _on_progress(self, tname: str, rows_written: int, total: int) -> None:
        if rows_written == 0:
            self.table_started.emit(tname, total)
        else:
            self.rows_written.emit(rows_written)

    @staticmethod
    def _close_connections(
        source_conn: DbConnectionManager | None,
        dest_conn: DbConnectionManager | None,
    ) -> None:
        for conn in (source_conn, dest_conn):
            if conn is not None:
                try:
                    conn.closedb()
                except Exception:
                    pass
