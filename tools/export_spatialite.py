"""ExportSpatialite — exports the current Midvatten database to a new SpatiaLite file."""

import logging

import qgis.core
from qgis.PyQt.QtCore import QCoreApplication, QEventLoop, Qt, QThread
from qgis.PyQt.QtWidgets import QApplication, QDialog, QMessageBox, QProgressDialog

from midvatten.tools.create_db import NewDb
from midvatten.tools.create_db_dialogs import NewSpatialiteDbDialog
from midvatten.tools.export_worker import ExportWorker
from midvatten.tools.utils import common_utils, db_utils, layer_utils, message_utils

log = logging.getLogger(__name__)

# (table, GROUP BY expression) pairs for semantic datetime duplicate detection.
# Expressions mirror the unique index definitions in create_db.sql.
_DT_DUPLICATE_CHECKS: list[tuple[str, str]] = [
    ("w_levels", "obsid, datetime(date_time)"),
    ("w_levels_logger", "obsid, datetime(date_time)"),
    ("comments", "obsid, datetime(date_time)"),
    ("w_flow", "obsid, flowtype, instrumentid, datetime(date_time)"),
    ("meteo", "obsid, parameter, instrumentid, datetime(date_time)"),
    ("w_qual_field", "obsid, parameter, datetime(date_time), COALESCE(unit, '<NULL>')"),
    (
        "w_qual_logger",
        "obsid, parameter, instrument, datetime(date_time), COALESCE(unit, '<NULL>')",
    ),
]


def _find_datetime_duplicates(source_db_settings: str) -> dict[str, int]:
    """Return {table: dup_count} for SQLite source tables with semantic datetime duplicates."""
    try:
        conn = db_utils.DbConnectionManager(source_db_settings)
        conn.connect2db()
    except Exception:
        log.debug("Could not connect to source DB for duplicate check", exc_info=True)
        return {}
    if not conn.is_sqlite():
        conn.closedb()
        return {}
    duplicates: dict[str, int] = {}
    try:
        for table, group_by in _DT_DUPLICATE_CHECKS:
            tq = db_utils.ident(table)
            sql = f"SELECT COUNT(*) FROM (SELECT 1 FROM {tq} GROUP BY {group_by} HAVING COUNT(*) > 1)"
            try:
                count = conn.execute_and_fetchall(sql)[0][0]
                if count:
                    duplicates[table] = count
            except Exception:
                log.debug(
                    "Duplicate check query failed for table %s", table, exc_info=True
                )
    finally:
        conn.closedb()
    return duplicates


def _warn_duplicates(parent, duplicates: dict[str, int]) -> bool:
    lines = "\n".join(f"  {table}: {count}" for table, count in duplicates.items())
    msg = QCoreApplication.translate(
        "ExportSpatialite",
        "The source database contains duplicate timestamps in the following tables:\n\n"
        "{}\n\n"
        "Duplicate timestamps are likely data errors. The exported database will keep only "
        "the earliest duplicate row per timestamp.\n\n"
        "It is recommended to review and correct these in the source database before exporting.\n\n"
        "Continue with export?",
    ).format(lines)
    result = QMessageBox.question(
        parent,
        QCoreApplication.translate("ExportSpatialite", "Duplicate timestamps detected"),
        msg,
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    return result == QMessageBox.Yes


class ExportSpatialite:
    def __init__(self, iface, ms):
        self._iface = iface
        self._ms = ms

    def show(self) -> None:
        common_utils.start_waiting_cursor()

        obsid_p = layer_utils.get_selected_features_as_tuple("obs_points")
        obsid_l = layer_utils.get_selected_features_as_tuple("obs_lines")
        log.debug("Selected obs_points to export: %s", obsid_p)
        log.debug("Selected obs_lines to export: %s", obsid_l)

        source_srid = db_utils.sql_load_fr_db(
            """SELECT srid FROM geometry_columns WHERE f_table_name = 'obs_points';"""
        )[1][0][0]
        w_levels_logger_timezone = db_utils.get_timezone_from_db("w_levels_logger")
        w_levels_timezone = db_utils.get_timezone_from_db("w_levels")

        common_utils.stop_waiting_cursor()

        selected_all = (
            QCoreApplication.translate("Midvatten", "selected")
            if obsid_p or obsid_l
            else QCoreApplication.translate("Midvatten", "all")
        )

        dialog = NewSpatialiteDbDialog(parent=self._iface.mainWindow())
        dialog.setWindowTitle(
            QCoreApplication.translate(
                "ExportSpatialite", "Export to SpatiaLite database ({})"
            ).format(selected_all)
        )
        dialog._path_edit.clear()
        if source_srid:
            dialog._epsg_spin.setValue(source_srid)
        if w_levels_logger_timezone is not None:
            idx = dialog._logger_tz_combo.findText(w_levels_logger_timezone)
            dialog._logger_tz_combo.setCurrentIndex(max(0, idx))
        if w_levels_timezone is not None:
            idx = dialog._levels_tz_combo.findText(w_levels_timezone)
            dialog._levels_tz_combo.setCurrentIndex(max(0, idx))

        if dialog.exec() != QDialog.Accepted:
            return

        if not dialog.dbpath:
            message_utils.MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "export_spatialite", "No destination path specified."
                )
            )
            return

        source_db_settings = qgis.core.QgsProject.instance().readEntry(
            "Midvatten", "database"
        )[0]
        duplicates = _find_datetime_duplicates(source_db_settings)
        if duplicates and not _warn_duplicates(self._iface.mainWindow(), duplicates):
            return

        newdbinstance = NewDb()
        progress = QProgressDialog(
            QCoreApplication.translate(
                "ExportSpatialite", "Creating new database, please wait..."
            ),
            None,
            0,
            0,
            self._iface.mainWindow(),
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setCancelButton(None)
        progress.show()
        QApplication.processEvents()
        try:
            newdbinstance.create_new_spatialite_db(
                newdbinstance._read_version(),
                user_select_crs="n",
                epsg_code=str(dialog.epsg_code),
                delete_srids=False,
                w_levels_logger_timezone=dialog.w_levels_logger_timezone,
                w_levels_timezone=dialog.w_levels_timezone,
                locale=dialog.locale,
                dbpath=dialog.dbpath,
            )
        finally:
            progress.close()

        if not newdbinstance.db_settings:
            message_utils.MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "export_spatialite",
                    "Export to spatialite failed, see log message panel",
                ),
                button=True,
            )
            return

        new_dbpath = db_utils.get_spatialite_db_path_from_dbsettings_string(
            newdbinstance.db_settings
        )
        if not new_dbpath:
            message_utils.MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "export_spatialite",
                    "Export to spatialite failed, see log message panel",
                ),
                button=True,
            )
            return

        self._run_export_worker(
            new_dbpath, dialog, obsid_p, obsid_l, source_db_settings
        )

    def _run_export_worker(
        self,
        new_dbpath: str,
        dialog,
        obsid_p: tuple[str, ...],
        obsid_l: tuple[str, ...],
        source_db_settings: str,
    ) -> None:
        worker = ExportWorker(
            source_db_settings=source_db_settings,
            dest_path=new_dbpath,
            obsid_points=obsid_p,
            obsid_lines=obsid_l,
            dest_srid=str(dialog.epsg_code),
        )
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)

        progress = QProgressDialog(
            QCoreApplication.translate(
                "ExportSpatialite", "Exporting data, please wait..."
            ),
            QCoreApplication.translate("ExportSpatialite", "Cancel"),
            0,
            0,
            self._iface.mainWindow(),
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.processEvents()

        loop = QEventLoop()
        _stats: str | None = None
        _signal_received = False

        def on_finished(stats: str) -> None:
            nonlocal _stats, _signal_received
            _stats = stats
            _signal_received = True
            loop.quit()

        def on_error(msg: str) -> None:
            nonlocal _signal_received
            log.error("Export error:\n%s", msg)
            _signal_received = True
            loop.quit()

        def on_table_started(name: str, total: int) -> None:
            progress.setLabelText(
                QCoreApplication.translate("ExportSpatialite", "Exporting: {}").format(
                    name
                )
            )
            progress.setMaximum(total)

        worker.finished.connect(on_finished)
        worker.error.connect(on_error)
        worker.table_started.connect(on_table_started)
        worker.rows_written.connect(progress.setValue)
        progress.canceled.connect(worker.cancel)

        thread.start()
        loop.exec_()
        thread.wait()
        progress.close()

        if not _signal_received:
            message_utils.MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "ExportSpatialite", "Export failed unexpectedly."
                ),
                button=True,
            )
            return
        if _stats is None:
            message_utils.MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "ExportSpatialite", "Export failed, see log message panel"
                ),
                button=True,
            )
        elif _stats == "":
            message_utils.MessagebarAndLog.info(
                bar_msg=QCoreApplication.translate(
                    "ExportSpatialite", "Export cancelled."
                )
            )
        else:
            message_utils.MessagebarAndLog.info(
                bar_msg=QCoreApplication.translate(
                    "ExportSpatialite",
                    "Export done, see differences in log message panel",
                ),
                log_msg=QCoreApplication.translate(
                    "ExportData", "Tables with different number of rows:\n%s"
                )
                % _stats,
            )
