"""ExportSpatialite — exports the current Midvatten database to a new SpatiaLite file."""

import logging

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from midvatten.tools.create_db import NewDb
from midvatten.tools.create_db_dialogs import _locale_options
from midvatten.tools.export_data import ExportData
from midvatten.tools.utils import common_utils, db_utils

log = logging.getLogger(__name__)


class ExportSpatialiteDialog(QDialog):
    """Single dialog collecting destination locale, CRS, and file path for export."""

    def __init__(
        self,
        source_srid: int,
        selected_all_text: str,
        parent: QWidget = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(
            QCoreApplication.translate(
                "ExportSpatialite", "Export to SpatiaLite database"
            )
        )
        self._source_srid = source_srid
        self._build_ui(selected_all_text)
        self._connect_signals()

    def _build_ui(self, selected_all_text: str) -> None:
        layout = QVBoxLayout(self)

        info_label = QLabel(
            QCoreApplication.translate(
                "ExportSpatialite",
                "Exporting {} obs_points and obs_lines.",
            ).format(selected_all_text)
        )
        layout.addWidget(info_label)

        form = QFormLayout()

        self._locale_combo = QComboBox()
        self._locale_combo.addItems(_locale_options())
        form.addRow(
            QCoreApplication.translate("ExportSpatialite", "Locale:"),
            self._locale_combo,
        )

        self._epsg_spin = QSpinBox()
        self._epsg_spin.setRange(1, 999999)
        self._epsg_spin.setValue(self._source_srid if self._source_srid else 4326)
        form.addRow(
            QCoreApplication.translate("ExportSpatialite", "Destination CRS (EPSG):"),
            self._epsg_spin,
        )

        path_row = QHBoxLayout()
        self._path_edit = QLineEdit()
        self._browse_btn = QPushButton(
            QCoreApplication.translate("ExportSpatialite", "Browse\u2026")
        )
        path_row.addWidget(self._path_edit)
        path_row.addWidget(self._browse_btn)
        path_widget = QWidget()
        path_widget.setLayout(path_row)
        form.addRow(
            QCoreApplication.translate("ExportSpatialite", "Destination file:"),
            path_widget,
        )

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _connect_signals(self) -> None:
        self._browse_btn.clicked.connect(self._browse_path)

    def _browse_path(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            QCoreApplication.translate("ExportSpatialite", "Export database"),
            self._path_edit.text() or "midv_export.sqlite",
            "Spatialite (*.sqlite)",
        )
        if path:
            self._path_edit.setText(path)

    @property
    def locale(self) -> str:
        return self._locale_combo.currentText()

    @property
    def epsg_code(self) -> int:
        return self._epsg_spin.value()

    @property
    def dbpath(self) -> str:
        return self._path_edit.text()


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
            w_levels_logger_timezone=w_levels_logger_timezone,
            w_levels_timezone=w_levels_timezone,
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
