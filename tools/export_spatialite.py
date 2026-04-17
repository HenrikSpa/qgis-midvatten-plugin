"""ExportSpatialite — exports the current Midvatten database to a new SpatiaLite file."""

import logging

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import QDialog, QFileDialog, QWidget

from midvatten.tools.create_db import NewDb
from midvatten.tools.create_db_dialogs import NewSpatialiteDbDialog
from midvatten.tools.export_data import ExportData
from midvatten.tools.utils import common_utils, db_utils

log = logging.getLogger(__name__)


class ExportSpatialiteDialog(NewSpatialiteDbDialog):
    """Variant of NewSpatialiteDbDialog for export: pre-fills values from source DB."""

    _DEFAULT_PATH = "midv_export.sqlite"

    def __init__(
        self,
        source_srid: int,
        selected_all_text: str,
        w_levels_logger_timezone: str = None,
        w_levels_timezone: str = None,
        parent: QWidget = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(
            QCoreApplication.translate(
                "ExportSpatialite",
                "Export to SpatiaLite database ({})",
            ).format(selected_all_text)
        )
        if source_srid:
            self._epsg_spin.setValue(source_srid)
        if w_levels_logger_timezone is not None:
            idx = self._logger_tz_combo.findText(w_levels_logger_timezone)
            self._logger_tz_combo.setCurrentIndex(max(0, idx))
        if w_levels_timezone is not None:
            idx = self._levels_tz_combo.findText(w_levels_timezone)
            self._levels_tz_combo.setCurrentIndex(max(0, idx))

    def _browse_path(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            QCoreApplication.translate("ExportSpatialite", "Export database"),
            self._path_edit.text() or self._DEFAULT_PATH,
            "Spatialite (*.sqlite)",
        )
        if path:
            self._path_edit.setText(path)


class ExportSpatialite:
    def __init__(self, iface, ms):
        self._iface = iface
        self._ms = ms

    def show(self) -> None:
        common_utils.start_waiting_cursor()

        obsid_p = common_utils.get_selected_features_as_tuple("obs_points")
        obsid_l = common_utils.get_selected_features_as_tuple("obs_lines")
        log.debug("Selected obs_points to export:%s", obsid_p)
        log.debug("Selected obs_lines to export:%s", obsid_l)

        source_srid = db_utils.sql_load_fr_db(
            """SELECT srid FROM geometry_columns WHERE f_table_name = 'obs_points';"""
        )[1][0][0]
        w_levels_logger_timezone = db_utils.get_timezone_from_db("w_levels_logger")
        w_levels_timezone = db_utils.get_timezone_from_db("w_levels")

        common_utils.stop_waiting_cursor()

        selected_all = (
            QCoreApplication.translate("Midvatten", "selected")
            if any([obsid_p, obsid_l])
            else QCoreApplication.translate("Midvatten", "all")
        )

        dialog = ExportSpatialiteDialog(
            source_srid=source_srid,
            selected_all_text=selected_all,
            w_levels_logger_timezone=w_levels_logger_timezone,
            w_levels_timezone=w_levels_timezone,
            parent=self._iface.mainWindow(),
        )
        if dialog.exec() != QDialog.Accepted:
            return

        if not dialog.dbpath:
            common_utils.MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "export_spatialite", "No destination path specified."
                )
            )
            return

        newdbinstance = NewDb()
        common_utils.start_waiting_cursor()
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
        common_utils.start_waiting_cursor()

        if newdbinstance.db_settings:
            new_dbpath = db_utils.get_spatialite_db_path_from_dbsettings_string(
                newdbinstance.db_settings
            )
            if not new_dbpath:
                common_utils.MessagebarAndLog.critical(
                    bar_msg=QCoreApplication.translate(
                        "export_spatialite",
                        "Export to spatialite failed, see log message panel",
                    ),
                    button=True,
                )
                common_utils.stop_waiting_cursor()
                return
            exportinstance = ExportData(self._iface, self._ms)
            exportinstance.ID_obs_points = obsid_p
            exportinstance.ID_obs_lines = obsid_l
            exportinstance.export_2_splite(new_dbpath, str(dialog.epsg_code))

        common_utils.stop_waiting_cursor()
