import datetime
import itertools
import json
import logging
import math
import os

import numpy as np
import pandas as pd
import qgis.PyQt
from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtGui import QCloseEvent, QIcon, QKeySequence
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QShortcut,
    QVBoxLayout,
    QWidget,
)
from matplotlib import pyplot as plt, ticker as tick
from matplotlib.backend_bases import PickEvent, MouseButton
from matplotlib.gridspec import GridSpec

from midvatten.tools.utils.mpl_compat import FigureCanvas, NavigationToolbar
from matplotlib.dates import num2date, datestr2num
from matplotlib.widgets import MultiCursor, RectangleSelector

from qgis.PyQt import uic
from midvatten.tools.utils import common_utils, db_utils
from midvatten.tools.utils.common_utils import fn_timer
from midvatten.tools.utils.db_utils.dialect import ident
from midvatten.tools.utils.db_utils.execution import use_or_create_connection
from midvatten.tools.utils.file_utils import ui_path
from midvatten.tools.utils.string_utils import returnunicode as ru
from midvatten.tools.utils.date_utils import (
    change_timezone,
    datestring_to_date,
    dateshift,
)
from midvatten.tools.utils.gui_utils import NavigationButton, WA_DeleteOnClose
from midvatten.tools.loggereditor_refseries import RefSeriesDialog
from midvatten.tools.trend_math import apply_trend_correction

log = logging.getLogger(__name__)

_DT_FMT = "%Y-%m-%d %H:%M:%S"

Calibr_Ui_Dialog = uic.loadUiType(ui_path("calibr_logger_dialog_integrated.ui"))[0]


class LoggerEditor(qgis.PyQt.QtWidgets.QMainWindow, Calibr_Ui_Dialog):
    _MAX_HISTORY = 200

    @staticmethod
    def _compute_line_keys(
        buf: pd.DataFrame,
        separate_source: bool,
        separate_created_at: bool,
        separate_dt_precision: bool,
        created_at_grouping: str | None,
    ) -> list[tuple]:
        n = len(buf)
        if n == 0:
            return []
        parts: list[list] = []
        if separate_source and "source" in buf.columns:
            parts.append(buf["source"].fillna("").tolist())
        if separate_created_at and "created_at" in buf.columns:
            ca = buf["created_at"].fillna("")
            if created_at_grouping == "hour":
                ca = ca.str[:13]
            elif created_at_grouping == "day":
                ca = ca.str[:10]
            parts.append(ca.tolist())
        if separate_dt_precision and "dt_length" in buf.columns:
            parts.append(buf["dt_length"].tolist())
        if not parts:
            return [("_all",)] * n
        return list(zip(*parts))

    @fn_timer
    def __init__(self, iface, ms):
        qgis.PyQt.QtWidgets.QMainWindow.__init__(self, iface.mainWindow())
        self._iface = iface
        self._ms = ms
        self.settingsdict = ms.settingsdict
        self.setAttribute(WA_DeleteOnClose)
        self.setupUi(self)  # Required by Qt4 to initialize the UI
        self.setWindowTitle(
            QCoreApplication.translate(
                "Calibrlogger", "Edit water level logger (w_levels_logger) data"
            )
        )  # Set the title for the dialog
        self.obsid = ""
        self.meas_ts = None
        self.head_ts = None
        self.head_ts_for_plot = None
        self.level_masl_ts = None
        self.logger_artist = None
        self.loggerpos_masl_or_offset_state = 1
        self.selected_line = None
        self.moving_idx = None

        self._buf: pd.DataFrame | None = None
        self._original_buf: pd.DataFrame | None = None
        self._buf_obsid: str | None = None
        self._dirty: bool = False
        self._schema_variant: str | None = None
        self._meas_ts = None
        self._meas_obsid: str | None = None
        self._history: list[dict] = []
        self._history_pos: int = -1
        self._prev_combobox_index: int = -1
        self._ref_subplot_dirty: bool = True
        self._buf_version: int = 0
        self._ts_version: int = -1
        self._last_saved_history_pos: int | None = None

        text = QCoreApplication.translate(
            "Calibrlogger",
            "Select the observation point with logger data to be adjusted.",
        )

        self.statusbar.showMessage(text, 0)
        self.log_calc_manual.setText(
            '<a href="https://github.com/jkall/qgis-midvatten-plugin/wiki/4.-Edit-data">Midvatten manual</a>'
        )

        self.cid = []
        self._trend_line = None
        self._trend_start_marker = None
        self._trend_end_marker = None
        self._trend_dragging = None
        self._trend_original_start_y = None
        self._trend_original_end_y = None

        self.button_calculate.clicked.connect(lambda x: self.set_logger_pos())
        self.button_add_offset.clicked.connect(lambda x: self.add_to_level_masl())
        self.push_button_from.clicked.connect(lambda x: self.set_from_date_from_x())
        self.push_button_to.clicked.connect(lambda x: self.set_to_date_from_x())
        self.push_button_from_extent.clicked.connect(
            lambda: self.update_date_from_extent(
                self.from_date_time, self.axes.get_xbound()[0]
            )
        )
        self.push_button_to_extent.clicked.connect(
            lambda: self.update_date_from_extent(
                self.to_date_time, self.axes.get_xbound()[1]
            )
        )
        self.push_buttonupdateplot.clicked.connect(lambda x: self.update_plot())
        self.button_auto_calculate.clicked.connect(lambda x: self.logger_pos_best_fit())
        self.button_auto_fit.clicked.connect(lambda x: self.level_masl_best_fit())
        self.push_button_delete_logger.clicked.connect(
            lambda: self.delete_selected_range("w_levels_logger")
        )
        self.push_button_set_null.clicked.connect(
            lambda: self.delete_selected_range(
                "w_levels_logger", set_to_null_instead=True
            )
        )
        self.from_date_time.dateTimeChanged.connect(
            lambda: self.plot_or_update_selected_line()
        )
        self.to_date_time.dateTimeChanged.connect(
            lambda: self.plot_or_update_selected_line()
        )

    def show(self) -> None:
        if not hasattr(self, "calibrplotfigure"):
            self.calibrplotfigure = plt.figure(layout="constrained")
            self._ref_gs = GridSpec(
                2, 1, figure=self.calibrplotfigure, height_ratios=[3, 1]
            )
            self.axes = self.calibrplotfigure.add_subplot(self._ref_gs[0])
            self.ref_axes = self.calibrplotfigure.add_subplot(
                self._ref_gs[1], sharex=self.axes
            )
            self.ref_axes.set_visible(False)
            self.canvas = FigureCanvas(self.calibrplotfigure)
            self.mpltoolbar = NavigationToolbar(self.canvas, self.widget_plot)
            self.layoutplot.addWidget(self.canvas)
            self.layoutplot.addWidget(self.mpltoolbar)

            try:
                # Support for older version of Matplotlib
                self.period_selector = RectangleSelector(
                    self.axes,
                    self.line_select_callback,
                    useblit=True,
                    button=[1],
                    minspanx=0,
                    minspany=0,
                    spancoords="data",
                    interactive=False,
                    # lineprops=dict(color="black", linestyle="-", linewidth=2, alpha=0.5),
                    rectprops=dict(
                        facecolor=None, edgecolor="black", alpha=0.5, fill=False
                    ),
                )
            except Exception:
                self.period_selector = RectangleSelector(
                    self.axes,
                    self.line_select_callback,
                    useblit=True,
                    button=[1],
                    minspanx=0,
                    minspany=0,
                    spancoords="data",
                    interactive=False,
                    # lineprops=dict(color="black", linestyle="-", linewidth=2, alpha=0.5),
                    props=dict(
                        facecolor=None, edgecolor="black", alpha=0.5, fill=False
                    ),
                )
            self.period_selector.set_active(False)

            self.select_nodes_button = SelectNodesButton(self, self.calibrplotfigure)
            self.move_nodes_button = MoveNodesButton(self, self.calibrplotfigure)
            self.multi_cursor_button = MultiCursorButton(self, self.calibrplotfigure)
            self.adjust_trend_button = AdjustTrendButton(self, self.calibrplotfigure)

            self.get_search_radius()

            common_utils.start_waiting_cursor()
            # Populate combobox with obsid from table w_levels_logger
            self.load_obsid_from_db()
            common_utils.stop_waiting_cursor()
            self._prev_combobox_index = self.combobox_obsid.currentIndex()
            self.combobox_obsid.currentIndexChanged.connect(self._on_obsid_changed)

            self.w_levels_logger_tz = db_utils.get_timezone_from_db("w_levels_logger")
            self.w_levels_tz = db_utils.get_timezone_from_db("w_levels")

            existing_columns = db_utils.tables_columns(table="w_levels_logger").get(
                "w_levels_logger", []
            )
            has_series_id = "series_id" in existing_columns
            has_series_table = bool(db_utils.tables_columns(table="w_logger_series"))
            if has_series_id and has_series_table:
                self._schema_variant = "series_join"
            elif "source" in existing_columns:
                self._schema_variant = "source_col"
            else:
                self._schema_variant = "no_source"

            # --- Save button in obsid row ---
            self._save_btn = QPushButton(
                QCoreApplication.translate("LoggerEditor", "Save"),
                self,
            )
            self._save_btn.setEnabled(False)
            self._save_btn.clicked.connect(self._on_save_clicked)
            self.horizontal_layout.addWidget(self._save_btn)

            # --- Undo / Redo strip ---
            undo_redo_widget = QWidget(self)
            undo_redo_layout = QHBoxLayout(undo_redo_widget)
            undo_redo_layout.setContentsMargins(0, 0, 0, 0)
            self._undo_btn = QPushButton(
                QCoreApplication.translate("LoggerEditor", "← Undo"), self
            )
            self._redo_btn = QPushButton(
                QCoreApplication.translate("LoggerEditor", "Redo →"), self
            )
            undo_redo_layout.addWidget(self._undo_btn)
            undo_redo_layout.addWidget(self._redo_btn)
            undo_redo_layout.addStretch()
            self._undo_btn.clicked.connect(self.undo)
            self._redo_btn.clicked.connect(self.redo)
            parent_layout = self.vertical_layout_6
            tab_index = -1
            for i in range(parent_layout.count()):
                item = parent_layout.itemAt(i)
                if item.widget() is self.tab_widget:
                    tab_index = i
                    break
            if tab_index >= 0:
                parent_layout.insertWidget(tab_index, undo_redo_widget)
            undo_shortcut = QShortcut(QKeySequence("Ctrl+Z"), self)
            undo_shortcut.activated.connect(self.undo)
            redo_shortcut = QShortcut(QKeySequence("Ctrl+Shift+Z"), self)
            redo_shortcut.activated.connect(self.redo)

            # --- History tab ---
            self._history_list = QListWidget(self)
            self._history_list.itemClicked.connect(
                lambda item: self.jump_to_history(self._history_list.row(item))
            )
            self.tab_widget.addTab(
                self._history_list,
                QCoreApplication.translate("LoggerEditor", "History"),
            )

            self._setup_ref_dock()

        super().show()
        self.activateWindow()

    def update_date_from_extent(self, date_time_edit, xbound_min_or_max):
        date_time_edit.setDateTime(num2date(xbound_min_or_max))

    @property
    def selected_obsid(self):
        uncalibrated_str = " (uncalibrated)"
        return str(self.combobox_obsid.currentText().replace(uncalibrated_str, ""))

    @fn_timer
    def get_all_obsids_in_w_levels_logger(self):
        return [
            row[0]
            for row in db_utils.sql_load_fr_db(
                """SELECT DISTINCT obsid FROM w_levels_logger ORDER BY obsid"""
            )[1]
        ]

    @fn_timer
    def get_uncalibrated_obsids(self, obsid=None):
        dbconnection = db_utils.DbConnectionManager()
        try:
            ph = dbconnection.placeholder()
            if dbconnection.is_sqlite():
                sql = """SELECT obsid FROM (SELECT obsid, MAX(date_time), level_masl, head_cm FROM w_levels_logger {} GROUP BY obsid)
                         WHERE level_masl IS NULL AND head_cm IS NOT NULL ORDER BY obsid""".format(
                    "" if obsid is None else f" WHERE obsid = {ph}"
                )
            else:
                sql = """SELECT obsid FROM
                        (SELECT DISTINCT ON (obsid) obsid, level_masl, head_cm
                        FROM w_levels_logger
                        {}
                        ORDER BY obsid, date_time desc) foo
                        WHERE level_masl IS NULL AND head_cm IS NOT NULL ORDER BY obsid""".format(
                    "" if obsid is None else f" WHERE obsid = {ph}"
                )

            execute_args = (obsid,) if obsid is not None else None
            res = [
                row[0]
                for row in db_utils.sql_load_fr_db(
                    sql, dbconnection=dbconnection, execute_args=execute_args
                )[1]
            ]
        except Exception:
            dbconnection.closedb()
            raise
        else:
            dbconnection.closedb()
        return res

    @fn_timer
    def load_obsid_from_db(self):
        self.combobox_obsid.clear()
        self.combobox_obsid.addItems(self.get_all_obsids_in_w_levels_logger())
        self.update_combobox_with_calibration_info(
            _obsids_with_uncalibrated_data=self.get_uncalibrated_obsids()
        )

    @fn_timer
    def update_combobox_with_calibration_info(
        self, obsid=None, _obsids_with_uncalibrated_data=None
    ):
        """
        Adds an " (uncalibrated)" suffix after each obsid containing NULL-values in the column level_masl or removes it
        if there is no NULL-values.

        :param obsid: If obsid is given, only that obsid is checked. If not given then all obsids are checked.
        :param _obsids_with_uncalibrated_data: A list of obsids which are uncalibrated.

        If only obsid is given, calibration status will be read from database for that obsid.
        If only _obsids_with_uncalibrated_data is given, all obsids will update status based on that list.
        If both obsid and _obsids_with_uncalibrated_data are given, only status for that obsid will be updated based _obsids_with_uncalibrated_data.
        If none is given, all obsids will update status based on result from database.
        :return:
        """
        uncalibrated_str = " (uncalibrated)"

        num_entries = self.combobox_obsid.count()

        if obsid is None and _obsids_with_uncalibrated_data is None:
            obsids_with_uncalibrated_data = self.get_uncalibrated_obsids()
        elif _obsids_with_uncalibrated_data is not None:
            obsids_with_uncalibrated_data = _obsids_with_uncalibrated_data

        for idx in range(num_entries):
            current_obsid = self.combobox_obsid.itemText(idx).replace(
                uncalibrated_str, ""
            )

            if obsid is not None:
                # If obsid was given, only continue loop for that one:
                if current_obsid != obsid:
                    continue
                if obsids_with_uncalibrated_data is None:
                    obsids_with_uncalibrated_data = self.get_uncalibrated_obsids(
                        current_obsid
                    )

            if current_obsid in obsids_with_uncalibrated_data:
                new_text = current_obsid + uncalibrated_str
            else:
                new_text = current_obsid

            self.combobox_obsid.setItemText(idx, new_text)

    def _build_ts_recarray(
        self,
        buf: pd.DataFrame,
        col: str,
        values_override: np.ndarray | None = None,
    ) -> np.recarray:
        """Build a (date_time, values, source) recarray directly from a DataFrame column."""
        sources = buf["source"].to_numpy()
        max_src_len = int(buf["source"].str.len().max() or 0)
        arr = np.empty(
            len(buf),
            dtype=[
                ("date_time", object),
                ("values", float),
                ("source", f"U{max(max_src_len, 1)}"),
            ],
        )
        arr["date_time"] = buf.index.strftime(_DT_FMT).to_numpy()
        arr["values"] = (
            values_override
            if values_override is not None
            else buf[col].to_numpy(dtype=float, na_value=np.nan)
        )
        arr["source"] = sources
        return arr.view(np.recarray)

    def _build_head_ts_for_plot(self, buf: pd.DataFrame) -> None:
        """Set self.head_ts_for_plot; handles normalize_head using DataFrame ops."""
        if not self.plot_logger_head.isChecked():
            self.head_ts_for_plot = None
            return
        if not self.normalize_head.isChecked():
            self.head_ts_for_plot = self.head_ts
            return
        head_valid = buf["head_cm_m"].dropna()
        if head_valid.empty:
            common_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "Calibrlogger", "No head values to normalize against."
                )
            )
            self.head_ts_for_plot = self.head_ts
            return
        head_mean = float(head_valid.mean())
        level_valid = buf["level_masl"].dropna()
        meas_vals = self.meas_ts.values.astype(float, copy=False)
        meas_valid = meas_vals[~np.isnan(meas_vals)]
        if level_valid.empty and meas_valid.size == 0:
            common_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "Calibrlogger",
                    "No calibrated level_masl values to normalize against.",
                )
            )
            self.head_ts_for_plot = self.head_ts
            return
        level_masl_mean = (
            float(level_valid.mean())
            if not level_valid.empty
            else float(meas_valid.mean())
        )
        normalized_vals = (
            buf["head_cm_m"]
            .add(level_masl_mean - head_mean)
            .to_numpy(dtype=float, na_value=np.nan)
        )
        self.head_ts_for_plot = self._build_ts_recarray(
            buf, "head_cm_m", values_override=normalized_vals
        )

    def _ensure_meas_ts(self, obsid: str, dbconnection=None) -> None:
        """Load and cache w_levels for obsid; reuse cache when obsid hasn't changed."""
        if self._meas_obsid == obsid and self._meas_ts is not None:
            self.meas_ts = self._meas_ts
            return
        own_conn = dbconnection is None
        if own_conn:
            dbconnection = db_utils.DbConnectionManager()
        ph = dbconnection.placeholder()
        meas_sql = f"SELECT date_time, level_masl FROM w_levels WHERE obsid = {ph} ORDER BY date_time"
        _ok, meas_list = db_utils.sql_load_fr_db(
            meas_sql, dbconnection=dbconnection, execute_args=(obsid,)
        )
        if own_conn:
            dbconnection.closedb()
        self.meas_ts = self.list_of_list_to_recarray(meas_list)
        if self.w_levels_logger_tz and self.w_levels_tz:
            self.meas_ts.date_time = [
                change_timezone(x, self.w_levels_tz, self.w_levels_logger_tz)
                for x in self.meas_ts.date_time
            ]
        self._meas_ts = self.meas_ts
        self._meas_obsid = obsid

    @fn_timer
    def load_obsid_and_init(self):
        """Checks the current obsid and reloads all ts.
        :return: obsid

        Info: Before, some time series was only reloaded when the obsid was changed, but this caused a problem if the
        data was changed in the background in for example spatialite gui. Now all time series are reloaded always.
        It's rather fast anyway.
        """
        common_utils.start_waiting_cursor()
        obsid = self.selected_obsid
        if not obsid:
            log.debug("error obsid " + str(obsid))
            common_utils.stop_waiting_cursor()
            return None

        if obsid == self._buf_obsid and self._buf is not None:
            self._ensure_meas_ts(obsid)
            if self._ts_version == self._buf_version:
                # Buffer unchanged since last plot — reuse cached recarrays.
                self.obsid = obsid
                self.setlastcalibration(obsid)
                common_utils.stop_waiting_cursor()
                return obsid
            buf = self._buf
        else:
            if self._schema_variant is None:
                raise RuntimeError(
                    "load_obsid_and_init called before show() — schema variant not yet detected"
                )

            dbconnection = db_utils.DbConnectionManager()
            ph = dbconnection.placeholder()

            self._ensure_meas_ts(obsid, dbconnection)

            schema_variant = self._schema_variant
            if schema_variant == "series_join":
                head_level_masl_sql = (
                    f"SELECT l.date_time, l.head_cm / 100, l.level_masl,"
                    f" TRIM(COALESCE(s.source, ''))"
                    f" FROM w_levels_logger l"
                    f" LEFT JOIN w_logger_series s ON s.id = l.series_id"
                    f" WHERE l.obsid = {ph} ORDER BY l.date_time"
                )
            elif schema_variant == "source_col":
                head_level_masl_sql = f"SELECT date_time, head_cm / 100, level_masl, TRIM(COALESCE(source, '')) FROM w_levels_logger WHERE obsid = {ph} ORDER BY date_time"
            else:
                head_level_masl_sql = f"SELECT date_time, head_cm / 100, level_masl, '' as source FROM w_levels_logger WHERE obsid = {ph} ORDER BY date_time"

            _ok, head_level_masl_list = db_utils.sql_load_fr_db(
                head_level_masl_sql, dbconnection=dbconnection, execute_args=(obsid,)
            )
            dbconnection.closedb()

            if head_level_masl_list:
                buf_df = pd.DataFrame(
                    {
                        "head_cm_m": [r[1] for r in head_level_masl_list],
                        "level_masl": [r[2] for r in head_level_masl_list],
                        "source": [r[3] for r in head_level_masl_list],
                    },
                    index=pd.to_datetime(
                        [r[0] for r in head_level_masl_list]
                    ).to_pydatetime(),
                )
            else:
                buf_df = pd.DataFrame(columns=["head_cm_m", "level_masl", "source"])
            self._buf = buf_df
            self._original_buf = buf_df.copy()
            self._history.clear()
            self._history_pos = -1
            self._history_push("Loaded")
            self._dirty = False
            self._last_saved_history_pos = self._history_pos
            self._buf_obsid = obsid
            self._ref_subplot_dirty = True
            buf = self._buf

        self.head_ts = self._build_ts_recarray(buf, "head_cm_m")
        self.level_masl_ts = self._build_ts_recarray(buf, "level_masl")
        self._build_head_ts_for_plot(buf)

        self.obsid = obsid

        calibration_status = (
            [obsid] if not buf.empty and pd.isna(buf["level_masl"].iloc[-1]) else []
        )
        self.update_combobox_with_calibration_info(
            obsid=obsid, _obsids_with_uncalibrated_data=calibration_status
        )

        self.setlastcalibration(obsid)
        self._ts_version = self._buf_version
        common_utils.stop_waiting_cursor()
        return obsid

    @fn_timer
    def setlastcalibration(self, obsid):
        if not obsid == "":
            self.lastcalibr = self.getlastcalibration(obsid)
            text = (
                QCoreApplication.translate(
                    "Calibrlogger",
                    """There is no earlier known position for the logger in %s""",
                )
                % self.selected_obsid
            )
            if self.lastcalibr:
                if all(
                    [
                        self.lastcalibr[0][0],
                        self.lastcalibr[0][1] is not None,
                        self.lastcalibr[0][1] != "",
                    ]
                ):
                    text = QCoreApplication.translate(
                        "Calibrlogger",
                        "Last pos. for logger in %s was %s masl at %s",
                    ) % (
                        obsid,
                        f"{self.lastcalibr[0][1]:.3f}",
                        str(self.lastcalibr[0][0]),
                    )

            self.info.setText(text)

    @fn_timer
    def getlastcalibration(self, obsid):
        if self._buf is not None:
            calibrated = self._buf[self._buf["level_masl"].notna()]
            if not calibrated.empty:
                last = calibrated.tail(1)
                dt = last.index[0]
                dt_str = dt.strftime("%Y-%m-%d %H:%M")
                level_masl = last["level_masl"].iloc[0]
                head_cm_m = last["head_cm_m"].iloc[0]
                loggerpos = level_masl - head_cm_m if pd.notna(head_cm_m) else None
                return [(dt_str, loggerpos)]
            return []

        dbconnection = db_utils.DbConnectionManager()
        ph = dbconnection.placeholder()
        sql = f"SELECT date_time, (level_masl - (head_cm/100)) AS loggerpos FROM w_levels_logger WHERE date_time = (SELECT max(date_time) AS date_time FROM w_levels_logger WHERE obsid = {ph} AND (CASE WHEN level_masl IS NULL THEN -1000 ELSE level_masl END) > -990 AND level_masl IS NOT NULL AND head_cm IS NOT NULL) AND obsid = {ph}"
        _ok, lastcalibr = db_utils.sql_load_fr_db(
            sql, dbconnection=dbconnection, execute_args=(obsid, obsid)
        )
        dbconnection.closedb()
        return lastcalibr

    def _on_save_clicked(self) -> None:
        if self.save_to_db():
            self.update_plot()

    def save_to_db(self) -> bool:
        """Compute diff between _buf and _original_buf and write minimal DB changes."""
        if self._buf is None or self._original_buf is None or self._buf_obsid is None:
            return False
        obsid = self._buf_obsid
        common_utils.start_waiting_cursor()
        try:
            deleted_indices = self._original_buf.index.difference(self._buf.index)
            delete_params = list(
                zip(
                    [obsid] * len(deleted_indices),
                    deleted_indices.strftime(_DT_FMT),
                )
            )

            common_index = self._original_buf.index.intersection(self._buf.index)
            orig_vals = self._original_buf.loc[common_index, "level_masl"]
            new_vals = self._buf.loc[common_index, "level_masl"]
            changed_mask = ~(
                (orig_vals == new_vals) | (orig_vals.isna() & new_vals.isna())
            )
            changed_index = common_index[changed_mask]
            orig_changed = orig_vals.loc[changed_index]
            new_changed = new_vals.loc[changed_index]
            head_changed = self._buf.loc[changed_index, "head_cm_m"]

            dbconnection = db_utils.DbConnectionManager()
            ph = dbconnection.placeholder()
            tbl = ident("w_levels_logger")
            # SQLite stores date_time as text; normalize both sides so that
            # '2017-02-01 00:00' and '2017-02-01 00:00:00' compare equal.
            is_sqlite = dbconnection.is_sqlite()
            if is_sqlite:
                dt_eq = f"datetime({ident('date_time')}) = datetime({ph})"
            else:
                dt_eq = f"{ident('date_time')} = {ph}"
            range_stmts, per_row_params = self._compute_update_statements(
                changed_index,
                orig_changed,
                new_changed,
                head_changed,
                obsid,
                tbl,
                ph,
                is_sqlite,
            )
            try:
                with dbconnection.transaction():
                    if delete_params:
                        delete_sql = (
                            f"DELETE FROM {tbl} WHERE {ident('obsid')} = {ph}"
                            f" AND {dt_eq}"
                        )
                        dbconnection.executemany(delete_sql, delete_params)
                    for sql, params in range_stmts:
                        dbconnection.execute(sql, params)
                    if per_row_params:
                        update_sql = (
                            f"UPDATE {tbl} SET {ident('level_masl')} = {ph}"
                            f" WHERE {ident('obsid')} = {ph}"
                            f" AND {dt_eq}"
                        )
                        dbconnection.executemany(update_sql, per_row_params)
            finally:
                dbconnection.closedb()
        except Exception as e:
            common_utils.MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate("LoggerEditor", "Save failed."),
                log_msg=str(e),
            )
            return False
        finally:
            common_utils.stop_waiting_cursor()

        self._original_buf = self._buf.copy()
        self._last_saved_history_pos = self._history_pos
        self._dirty = False
        self._ref_subplot_dirty = True
        self._refresh_window_title()
        self._refresh_history_widget()
        return True

    def _compute_update_statements(
        self,
        changed_index: pd.DatetimeIndex,
        orig_changed: pd.Series,
        new_changed: pd.Series,
        head_changed: pd.Series,
        obsid: str,
        tbl: str,
        ph: str,
        is_sqlite: bool,
    ) -> tuple[list[tuple], list[tuple]]:
        """Group changed rows by contiguous buf-position; emit range or per-row SQL.

        Returns (range_stmts, per_row_params):
          range_stmts  — list of (sql, params_tuple), executed with execute()
          per_row_params — list of (new_val, obsid, dt_str), executed with executemany()

        Contiguous groups of changed rows that match a known pattern (set logger
        position, add offset, set to NULL) are folded into a single range-based
        UPDATE statement.  Groups that don't match — e.g. trend adjustments — fall
        back to one row per statement via executemany.
        """
        if len(changed_index) == 0:
            return [], []

        dt_col = ident("date_time")
        obsid_col = ident("obsid")
        level_col = ident("level_masl")
        head_col = ident("head_cm")
        if is_sqlite:
            dt_between = f"datetime({dt_col}) BETWEEN datetime({ph}) AND datetime({ph})"
        else:
            dt_between = f"{dt_col} BETWEEN {ph} AND {ph}"
        # where_range embeds three placeholders in order: obsid, t1, t2
        where_range = f"{obsid_col} = {ph} AND {dt_between}"

        # A BETWEEN range-query only touches the intended rows when there are no
        # unchanged rows between t1 and t2 in the buffer — split on gaps to enforce this.
        buf_pos = self._buf.index.get_indexer(changed_index)
        splits = (np.where(np.diff(buf_pos) > 1)[0] + 1).tolist()
        group_slices = np.split(np.arange(len(changed_index)), splits)

        range_stmts: list[tuple] = []
        per_row_params: list[tuple] = []

        for grp_idx in group_slices:
            grp_changed = changed_index[grp_idx]
            grp_new = new_changed.iloc[grp_idx]
            grp_orig = orig_changed.iloc[grp_idx]
            dt_strs = grp_changed.strftime(_DT_FMT)
            t1, t2 = dt_strs[0], dt_strs[-1]

            # Pattern: set to NULL
            if grp_new.isna().all():
                sql = f"UPDATE {tbl} SET {level_col} = NULL WHERE {where_range}"
                range_stmts.append((sql, (obsid, t1, t2)))
                continue

            # Pattern: set logger position — new = C + head_cm/100 (constant C)
            grp_head = head_changed.iloc[grp_idx]
            if grp_head.notna().all():
                c_arr = (grp_new - grp_head).to_numpy(dtype=float)
                if np.all(np.abs(c_arr - c_arr[0]) < 1e-9):
                    sql = (
                        f"UPDATE {tbl}"
                        f" SET {level_col} = {ph} + {head_col} / 100.0"
                        f" WHERE {head_col} IS NOT NULL AND {where_range}"
                    )
                    range_stmts.append((sql, (float(c_arr[0]), obsid, t1, t2)))
                    continue

            # Pattern: add constant offset — new = orig + D (constant D, both non-null)
            if grp_new.notna().all() and grp_orig.notna().all():
                d_arr = (grp_new - grp_orig).to_numpy(dtype=float)
                if np.all(np.abs(d_arr - d_arr[0]) < 1e-9):
                    sql = (
                        f"UPDATE {tbl}"
                        f" SET {level_col} = {level_col} + {ph}"
                        f" WHERE {level_col} IS NOT NULL AND {where_range}"
                    )
                    range_stmts.append((sql, (float(d_arr[0]), obsid, t1, t2)))
                    continue

            # Fallback: per-row executemany (trend adjustments, mixed patterns)
            per_row_params.extend(
                zip(
                    grp_new.to_numpy(dtype=object, na_value=None),
                    itertools.repeat(obsid, len(grp_idx)),
                    dt_strs,
                )
            )

        return range_stmts, per_row_params

    def _ask_save_discard_cancel(self, msg: str) -> str:
        """Show Save / Discard / Cancel dialog; return 'save', 'discard', or 'cancel'."""
        box = qgis.PyQt.QtWidgets.QMessageBox(self)
        box.setWindowTitle(
            QCoreApplication.translate("LoggerEditor", "Unsaved changes")
        )
        box.setText(msg)
        save_btn = box.addButton(
            QCoreApplication.translate("LoggerEditor", "Save"),
            qgis.PyQt.QtWidgets.QMessageBox.AcceptRole,
        )
        discard_btn = box.addButton(
            QCoreApplication.translate("LoggerEditor", "Discard"),
            qgis.PyQt.QtWidgets.QMessageBox.DestructiveRole,
        )
        box.addButton(
            QCoreApplication.translate("LoggerEditor", "Cancel"),
            qgis.PyQt.QtWidgets.QMessageBox.RejectRole,
        )
        box.exec_()
        clicked = box.clickedButton()
        if clicked is save_btn:
            return "save"
        if clicked is discard_btn:
            return "discard"
        return "cancel"

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._dirty:
            result = self._ask_save_discard_cancel(
                QCoreApplication.translate(
                    "LoggerEditor",
                    "You have unsaved changes. Save before closing?",
                )
            )
            if result == "cancel":
                event.ignore()
                return
            if result == "save" and not self.save_to_db():
                event.ignore()
                return
        event.accept()

    def _revert_combobox_to_prev(self) -> None:
        self.combobox_obsid.blockSignals(True)
        self.combobox_obsid.setCurrentIndex(self._prev_combobox_index)
        self.combobox_obsid.blockSignals(False)

    def _on_obsid_changed(self, new_index: int) -> None:
        if not self._dirty:
            self._prev_combobox_index = new_index
            return
        result = self._ask_save_discard_cancel(
            QCoreApplication.translate(
                "LoggerEditor",
                "You have unsaved changes for this logger. Save before switching?",
            )
        )
        if result == "cancel":
            self._revert_combobox_to_prev()
            return
        if result == "save":
            if not self.save_to_db():
                self._revert_combobox_to_prev()
                return
        else:
            self._discard_buf()
        self._prev_combobox_index = new_index

    def _discard_buf(self) -> None:
        self._buf = None
        self._original_buf = None
        self._dirty = False
        self._buf_obsid = None
        self._history = []
        self._history_pos = -1
        self._last_saved_history_pos = None

    def _history_push(self, label: str) -> None:
        del self._history[self._history_pos + 1 :]
        entry = {
            "label": label,
            "timestamp": datetime.datetime.now(),
            "level_masl": self._buf["level_masl"].copy(),
            "present_index": self._buf.index.copy(),
        }
        self._history.append(entry)
        self._history_pos = len(self._history) - 1
        self._buf_version += 1
        if len(self._history) > self._MAX_HISTORY:
            trim = len(self._history) - self._MAX_HISTORY
            self._history = self._history[trim:]
            self._history_pos -= trim
            if self._last_saved_history_pos is not None:
                self._last_saved_history_pos -= trim
                if self._last_saved_history_pos < 0:
                    self._last_saved_history_pos = None
        self._dirty = True
        self._refresh_window_title()
        self._refresh_history_widget()

    def undo(self) -> None:
        if self._history_pos > 0:
            self._history_pos -= 1
            self._restore_from_history(self._history_pos)

    def redo(self) -> None:
        if self._history_pos < len(self._history) - 1:
            self._history_pos += 1
            self._restore_from_history(self._history_pos)

    def jump_to_history(self, n: int) -> None:
        if 0 <= n < len(self._history):
            self._history_pos = n
            self._restore_from_history(n)

    def _restore_from_history(self, pos: int) -> None:
        entry = self._history[pos]
        self._buf = self._original_buf.loc[entry["present_index"]].copy()
        self._buf["level_masl"] = entry["level_masl"]
        self._buf_version += 1
        self._dirty = pos != 0
        self._refresh_window_title()
        self._refresh_history_widget()
        self.update_plot()

    def _refresh_history_widget(self) -> None:
        if not hasattr(self, "_history_list") or not hasattr(self, "_undo_btn"):
            return
        self._history_list.clear()
        for i, entry in enumerate(self._history):
            ts = entry["timestamp"].strftime("%H:%M:%S")
            saved_marker = " [saved]" if i == self._last_saved_history_pos else ""
            item = QListWidgetItem(f"{ts}  {entry['label']}{saved_marker}")
            if i == self._history_pos:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            self._history_list.addItem(item)
        if self._history:
            self._history_list.scrollToItem(self._history_list.item(self._history_pos))
        self._undo_btn.setEnabled(self._history_pos > 0)
        self._redo_btn.setEnabled(self._history_pos < len(self._history) - 1)

    def _refresh_window_title(self) -> None:
        base = self.windowTitle()
        if base.endswith(" *"):
            base = base[:-2]
        new_title = base + " *" if self._dirty else base
        if new_title != self.windowTitle():
            self.setWindowTitle(new_title)
        if hasattr(self, "_save_btn"):
            self._save_btn.setEnabled(self._dirty)

    def _obsid_ensure_buf_current(self) -> str | None:
        """Return buffered obsid if it matches the current combobox selection.
        If the user switched obsid without clicking Update Plot, the buffer is
        stale — fall back to load_obsid_and_init() to reload the correct one."""
        if self._buf_obsid == self.selected_obsid:
            return self._buf_obsid
        return self.load_obsid_and_init()

    @fn_timer
    def set_logger_pos(self, obsid=None):
        self.loggerpos_masl_or_offset_state = 1
        if obsid is None:
            obsid = self._obsid_ensure_buf_current()
        if not self.logger_elevation.text() == "":
            self.calibrate(obsid)
            self.update_plot()

    @fn_timer
    def add_to_level_masl(self, obsid=None):
        self.loggerpos_masl_or_offset_state = 0
        if obsid is None:
            obsid = self._obsid_ensure_buf_current()
        if not self.offset.text() == "":
            self.calibrate(obsid)
        self.update_plot()

    @fn_timer
    def calibrate(self, obsid=None):

        if obsid is None:
            obsid = self.load_obsid_and_init()

        if not obsid == "":
            fr_d_t = self.from_date_time.dateTime().toPyDateTime()
            to_d_t = self.to_date_time.dateTime().toPyDateTime()

            if self.loggerpos_masl_or_offset_state == 1:
                self.update_level_masl_from_head(
                    obsid, fr_d_t, to_d_t, self.logger_elevation.text()
                )
            else:
                self.update_level_masl_from_level_masl(
                    obsid, fr_d_t, to_d_t, self.offset.text()
                )

        else:
            text = QCoreApplication.translate(
                "Calibrlogger",
                "Select the observation point with logger data to be adjusted.",
            )

            self.statusbar.showMessage(text, 0)

    @fn_timer
    def update_level_masl_from_level_masl(self, obsid, fr_d_t, to_d_t, newzref):
        """Updates the level masl using newzref.
        :param obsid: (str) The obsid
        :param fr_d_t: (datetime) start of calibration
        :param to_d_t: (datetime) end of calibration
        :param newzref: (int/float/str [m]) The correction that should be made against the head [m]
        :return: None
        """
        if self._buf is None:
            common_utils.MessagebarAndLog.warning(bar_msg="No data loaded")
            return
        fr = fr_d_t.replace(tzinfo=None)
        to = to_d_t.replace(tzinfo=None)
        mask = (
            (fr <= self._buf.index)
            & (self._buf.index <= to)
            & self._buf["level_masl"].notna()
        )
        self._buf.loc[mask, "level_masl"] += float(newzref)
        self._history_push("Adjust level")

    @fn_timer
    def update_level_masl_from_head(self, obsid, fr_d_t, to_d_t, newzref):
        """Updates the level masl using newzref.
        :param obsid: (str) The obsid
        :param fr_d_t: (datetime) start of calibration
        :param to_d_t: (datetime) end of calibration
        :param newzref: (int/float/str [m]) The correction that should be made against the head [m]
        :return: None
        """
        if self._buf is None:
            common_utils.MessagebarAndLog.warning(bar_msg="No data loaded")
            return
        fr = fr_d_t.replace(tzinfo=None)
        to = to_d_t.replace(tzinfo=None)
        mask = (
            (fr <= self._buf.index)
            & (self._buf.index <= to)
            & self._buf["head_cm_m"].notna()
        )
        self._buf.loc[mask, "level_masl"] = (
            float(newzref) + self._buf.loc[mask, "head_cm_m"]
        )
        self._history_push("Set logger position")

    @fn_timer
    def list_of_list_to_recarray(self, list_of_lists):
        my_format = [
            ("date_time", datetime.datetime),
            ("values", float),
        ]  # Define (with help from function datetime) a good format for numpy array

        if len(list_of_lists):
            if len(list_of_lists[0]) == 3:
                max_len = max([len(x[2]) for x in list_of_lists])
                my_format = [
                    ("date_time", datetime.datetime),
                    ("values", float),
                    ("source", np.dtype("U" + str(max_len))),
                ]

        table = np.array(list_of_lists, dtype=my_format)  # NDARRAY
        table2 = table.view(
            np.recarray
        )  # RECARRAY   Makes the two columns inte callable objects, i.e. write table2.values
        return table2

    @fn_timer
    def update_plot(self):
        """Plots self.level_masl_ts, self.meas_ts and maybe self.head_ts"""
        self.reset_plot_selects_and_calib_help()
        self.statusbar.showMessage(
            QCoreApplication.translate("Calibrlogger", "Updating plot..."), 0
        )
        last_used_obsid = self.obsid
        obsid = self.load_obsid_and_init()
        common_utils.start_waiting_cursor()
        if obsid is None:
            self.statusbar.clearMessage()
            return
        self.selected_line = None
        self.axes.clear()

        handles, labels = self._draw_series()

        self.plot_or_update_selected_line()

        self._finish_plot(handles, labels)
        self._draw_reference_subplot()

        if last_used_obsid == self.obsid:
            self.mpltoolbar.forward()
        else:
            # Clear choices
            self.reset_settings()
            self.mpltoolbar.update()

        common_utils.stop_waiting_cursor()

        self.toggle_move_nodes(self.move_nodes_button.button().isChecked())
        self.toggle_select_nodes(self.select_nodes_button.button().isChecked())
        if hasattr(self, "adjust_trend_button"):
            self.toggle_adjust_trend(self.adjust_trend_button.button().isChecked())

    def _draw_series(self):
        """Draw measurement and logger time series onto self.axes. Return (handles, labels)."""
        obsid = self.obsid
        handles = []
        labels = []

        # Load manual reading (full time series) for the obsid
        if self.meas_ts.size and self.contains_more_than_nan(self.meas_ts):
            a = self.plot_recarray(
                self.axes,
                self.meas_ts,
                obsid + QCoreApplication.translate("Calibrlogger", " measurements"),
                style=dict(
                    linestyle="-",
                    marker="o",
                    zorder=50,
                    color="#1f77b4ff",
                    markersize=10,
                    markerfacecolor="None",
                    markeredgecolor="#1f77b4ff",
                    markeredgewidth=3,
                ),
            )[0]
            handles.append(a)
            labels.append(a.get_label())

        if self.logger_line_nodes.isChecked():
            marker = "o"
        else:
            marker = ""

        logger_level_masl_colors = [
            "#ff7f0e",
            "#2ca02c",
            "#d62728",
            "#9467bd",
            "#8c564b",
            "#e377c2",
            "#7f7f7f",
            "#bcbd22",
            "#17becf",
        ]
        logger_head_colors = [str(x / 10) for x in reversed(list(range(1, 10)))]

        self.logger_plot_artists = []
        logger_time_list = self.timestring_list_to_time_list(
            self.a_recarray_to_timestring_list(self.level_masl_ts)
        )
        if self.level_masl_ts.size and self.contains_more_than_nan(self.level_masl_ts):
            self.logger_artist = self.plot_recarray(
                self.axes,
                self.level_masl_ts,
                obsid
                + QCoreApplication.translate(
                    "Calibrlogger", " logger water level for editing"
                ),
                time_list=logger_time_list,
                style=dict(
                    linestyle="none", picker=5, marker=None, zorder=10, color="white"
                ),
            )[0]

            for idx, source in enumerate(
                np.unique(self.level_masl_ts.source, equal_nan=True)
            ):
                label = obsid + QCoreApplication.translate(
                    "Calibrlogger", " logger water level"
                )

                if source is None or not str(source).strip():
                    pass
                else:
                    label = label + f", {source}"

                ts = self.level_masl_ts.copy()
                ts.values[ts.source != source] = np.nan
                try:
                    color = logger_level_masl_colors[idx]
                except IndexError:
                    color = np.random.rand(3, 1).ravel()
                a = self.plot_recarray(
                    self.axes,
                    ts,
                    label,
                    time_list=logger_time_list,
                    style=dict(
                        linestyle="-",
                        picker=0,
                        markersize=3,
                        marker=marker,
                        zorder=10,
                        color=color,
                    ),
                )[0]
                self.logger_plot_artists.append(a)
                handles.append(a)
                labels.append(label)

        else:
            self.logger_artist = None

        if (
            self.plot_logger_head.isChecked()
            and self.head_ts_for_plot.size
            and self.contains_more_than_nan(self.head_ts_for_plot)
        ):
            for idx, source in enumerate(
                np.unique(self.head_ts_for_plot.source, equal_nan=True)
            ):
                try:
                    color = logger_head_colors[idx]
                except IndexError:
                    color = np.random.rand(3, 1).ravel()

                label = obsid + QCoreApplication.translate(
                    "Calibrlogger", " logger head"
                )

                if source is None or not str(source).strip():
                    pass
                else:
                    label = label + f", {source}"
                ts = self.head_ts_for_plot.copy()
                ts.values[ts.source != source] = np.nan

                a = self.plot_recarray(
                    self.axes,
                    ts,
                    label,
                    style=dict(linestyle="--", zorder=5, color=color, marker=""),
                    time_list=logger_time_list,
                )[0]
                handles.append(a)
                labels.append(label)

        return handles, labels

    def _finish_plot(self, handles, labels):
        """Configure axes, draw legend and refresh canvas."""
        self.axes.grid(True)
        self.axes.yaxis.set_major_formatter(
            tick.ScalarFormatter(useOffset=False, useMathText=False)
        )
        self.calibrplotfigure.autofmt_xdate()
        if not self.ref_axes.get_visible():
            self._restore_main_xticklabels()
        self.axes.set_ylabel(
            QCoreApplication.translate("Calibrlogger", "Level (masl)")
        )  # accepts national characters ('åäö') in matplotlib axes labels
        self.axes.set_title(
            QCoreApplication.translate("Calibrlogger", "Plot for ") + str(self.obsid)
        )
        for label in self.axes.xaxis.get_ticklabels():
            label.set_fontsize(8)
        for label in self.axes.yaxis.get_ticklabels():
            label.set_fontsize(8)

        if self.axes.legend_ is None:
            leg = self.axes.legend(handles, labels)

        self.canvas.draw()
        self.statusbar.clearMessage()

    def _setup_ref_dock(self) -> None:
        self._ref_series: list[dict] = []
        self._ref_dock = QDockWidget(
            QCoreApplication.translate("Calibrlogger", "Reference series"), self
        )
        self._ref_dock.setObjectName("ref_series_dock")
        container = QWidget()
        vbox = QVBoxLayout(container)
        btn_row = QHBoxLayout()
        self._ref_list = QListWidget()
        self._ref_add_btn = QPushButton(
            QCoreApplication.translate("Calibrlogger", "+ Add")
        )
        self._ref_edit_btn = QPushButton(
            QCoreApplication.translate("Calibrlogger", "Edit")
        )
        self._ref_remove_btn = QPushButton(
            QCoreApplication.translate("Calibrlogger", "Remove")
        )
        btn_row.addWidget(self._ref_add_btn)
        btn_row.addWidget(self._ref_edit_btn)
        btn_row.addWidget(self._ref_remove_btn)
        vbox.addLayout(btn_row)
        vbox.addWidget(self._ref_list)
        self._ref_dock.setWidget(container)
        self.addDockWidget(Qt.RightDockWidgetArea, self._ref_dock)
        toggle = self._ref_dock.toggleViewAction()
        icon_path = os.path.join(
            os.path.dirname(__file__), "..", "icons", "svg", "ref_panel.svg"
        )
        toggle.setIcon(QIcon(icon_path))
        self.mpltoolbar.addAction(toggle)
        self._ref_add_btn.clicked.connect(self._on_add_ref_series)
        self._ref_edit_btn.clicked.connect(self._on_edit_ref_series)
        self._ref_remove_btn.clicked.connect(self._on_remove_ref_series)
        self._ref_list.itemDoubleClicked.connect(lambda _: self._on_edit_ref_series())
        self._load_ref_series()
        self._draw_reference_subplot()

    def _load_ref_series(self) -> None:
        raw = self._ms.settingsdict.get("loggered_ref_series", "[]")
        try:
            self._ref_series = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            self._ref_series = []
        self._refresh_ref_list_widget()

    def _save_ref_series(self) -> None:
        self._ms.settingsdict["loggered_ref_series"] = json.dumps(self._ref_series)
        self._ms.save_settings("loggered_ref_series")

    def _refresh_ref_list_widget(self) -> None:
        self._ref_list.clear()
        for s in self._ref_series:
            filter_str = _ref_series_filter_str(s)
            summary = f"{s.get('table', '?')} · {s.get('y_col', '?')}"
            if filter_str:
                summary += f" · {filter_str}"
            summary += f" · {s.get('style', 'line')}"
            if s.get("resample"):
                summary += f" · {s['resample']} {s.get('resample_agg', '')}"
            self._ref_list.addItem(summary)

    def _on_add_ref_series(self) -> None:
        dlg = RefSeriesDialog(parent=self)
        if dlg.exec() == dlg.Accepted:
            self._ref_series.append(dlg.to_dict())
            self._save_ref_series()
            self._refresh_ref_list_widget()
            self._ref_subplot_dirty = True
            self._draw_reference_subplot()

    def _on_edit_ref_series(self) -> None:
        idx = self._ref_list.currentRow()
        if idx < 0:
            return
        dlg = RefSeriesDialog.from_dict(self._ref_series[idx], parent=self)
        if dlg.exec() == dlg.Accepted:
            self._ref_series[idx] = dlg.to_dict()
            self._save_ref_series()
            self._refresh_ref_list_widget()
            self._ref_subplot_dirty = True
            self._draw_reference_subplot()

    def _on_remove_ref_series(self) -> None:
        idx = self._ref_list.currentRow()
        if idx < 0:
            return
        del self._ref_series[idx]
        self._save_ref_series()
        self._refresh_ref_list_widget()
        self._ref_subplot_dirty = True
        self._draw_reference_subplot()

    def _restore_main_xticklabels(self) -> None:
        # get_ticklabels() filters out invisible labels, so use get_major_ticks()
        # to reach labels hidden by autofmt_xdate().
        for tick in self.axes.xaxis.get_major_ticks():
            tick.label1.set_visible(True)
            tick.label1.set_rotation(30)
            tick.label1.set_ha("right")

    def _hide_main_xticklabels(self) -> None:
        for tick in self.axes.xaxis.get_major_ticks():
            tick.label1.set_visible(False)

    def _draw_reference_subplot(self) -> None:
        if not self._ref_subplot_dirty:
            return
        self._ref_subplot_dirty = False
        # sharex makes both axes share the same xaxis.major ticker object, so
        # ref_axes.cla() resets the shared formatter/locator to scalar defaults.
        # Restore only when a date formatter is already active; restoring a plain
        # ScalarFormatter would block matplotlib's date-unit auto-detection when
        # the ref series data is subsequently plotted.
        formatter = self.axes.xaxis.get_major_formatter()
        locator = self.axes.xaxis.get_major_locator()
        self.ref_axes.cla()
        if not isinstance(formatter, tick.ScalarFormatter):
            self.axes.xaxis.set_major_formatter(formatter)
            self.axes.xaxis.set_major_locator(locator)
        if not self._ref_series:
            self._ref_gs.set_height_ratios([1, 0.001])
            self.ref_axes.set_visible(False)
            self._restore_main_xticklabels()
            self.canvas.draw()
            return
        self._ref_gs.set_height_ratios([3, 1])
        self.ref_axes.set_visible(True)
        self._hide_main_xticklabels()
        with use_or_create_connection(None) as conn:
            for s in self._ref_series:
                self._plot_ref_series(conn, s)
        self.ref_axes.legend(fontsize="small", loc="best")
        self.ref_axes.grid(True)
        self.ref_axes.yaxis.set_major_formatter(
            tick.ScalarFormatter(useOffset=False, useMathText=False)
        )
        for label in self.ref_axes.xaxis.get_ticklabels():
            label.set_fontsize(8)
            label.set_rotation(30)
            label.set_ha("right")
        for label in self.ref_axes.yaxis.get_ticklabels():
            label.set_fontsize(8)
        self.canvas.draw()

    def _plot_ref_series(self, conn, s: dict) -> None:
        combos = list(_iter_filter_combos(s.get("filters", [])))
        is_multi = len(combos) > 1
        for combo in combos:
            self._plot_one_combo(conn, s, combo, is_multi)

    def _plot_one_combo(self, conn, s: dict, combo: dict, is_multi: bool) -> None:
        sql, params = self._build_ref_query(conn, s, combo)
        rows = conn.execute_and_fetchall(sql, params)
        if not rows:
            return
        df = pd.DataFrame(rows, columns=["x", "y"])
        df["x"] = pd.to_datetime(df["x"], errors="coerce")
        df = df.dropna(subset=["x", "y"]).set_index("x").sort_index()["y"]
        if df.empty:
            return
        if s.get("resample"):
            df = getattr(df.resample(s["resample"]), s.get("resample_agg", "mean"))()
        if s.get("interpolate"):
            df = df.interpolate(method="time")
        norm = s.get("normalize", "")
        if norm == "date" and s.get("normalize_date"):
            ref_val = df.asof(pd.Timestamp(s["normalize_date"]))
            if pd.notna(ref_val):
                df = df - ref_val
        elif norm == "mean":
            df = df - df.mean()
        elif norm == "zscore":
            std = df.std()
            if std > 0:
                df = (df - df.mean()) / std
        df = df * s.get("scale", 1.0)
        if df.empty:
            return
        _ref_series_plot_style(
            self.ref_axes,
            df.index.to_pydatetime(),
            df.values,
            s.get("style", "line"),
            _ref_series_combo_label(s, combo, is_multi),
        )

    def _build_ref_query(self, conn, s: dict, combo: dict) -> tuple:
        ph = conn.placeholder()
        sql = (
            f"SELECT {ident(s['x_col'])}, {ident(s['y_col'])} FROM {ident(s['table'])}"
        )
        where_parts: list[str] = []
        params: list = []
        for col, val in combo.items():
            where_parts.append(f"{ident(col)} = {ph}")
            params.append(val)
        if where_parts:
            sql += " WHERE " + " AND ".join(where_parts)
        sql += f" ORDER BY {ident(s['x_col'])}"
        return sql, params

    @fn_timer
    def plot_recarray(self, axes, a_recarray, label, time_list=None, style=None):
        """Plots a recarray to the supplied axes object"""
        if time_list is None:
            time_list = self.timestring_list_to_time_list(
                self.a_recarray_to_timestring_list(a_recarray)
            )
        return self.plot_the_recarray(axes, time_list, a_recarray, label, style=style)

    @fn_timer
    def a_recarray_to_timestring_list(self, a_recarray):
        return a_recarray.date_time.tolist()

    @fn_timer
    def timestring_list_to_time_list(self, timestring_list):
        """Convert date strings to date"""
        return num2date(datestr2num(timestring_list))

    @fn_timer
    def contains_more_than_nan(self, a_recarray: np.recarray) -> bool:
        return bool(
            a_recarray.size
            and not np.all(np.isnan(a_recarray.values.astype(float, copy=False)))
        )

    @fn_timer
    def plot_the_recarray(self, axes, time_list, a_recarray, label, style=None):
        if style is None:
            style = {}
        return axes.plot(time_list, a_recarray.values, label=label, **style)

    @fn_timer
    def set_from_date_from_x(self):
        """Used to set the self.from_date_time by clicking on a line node in the plot self.canvas"""
        self.set_date_from_x(
            self.from_date_time,
            QCoreApplication.translate(
                "Calibrlogger", 'Select a date to use as "from"'
            ),
            from_node=False,
        )

    @fn_timer
    def set_to_date_from_x(self):
        """Used to set the self.to_date_time by clicking on a line node in the plot self.canvas"""
        self.set_date_from_x(
            self.to_date_time,
            QCoreApplication.translate("Calibrlogger", 'Select a date to use as "to"'),
            from_node=False,
        )

    @fn_timer
    def set_date_from_x_onclick(self, event, date_holder, from_node=False):
        """Sets the date_holder to a date from a line node closest to the pick event

        date_holder: a QDateTimeEdit object.
        """
        if from_node:
            found_date = num2date(event.artist.get_xdata()[event.ind[0]])
        else:
            found_date = num2date(event.xdata)

        self.reset_plot_selects_and_calib_help()
        date_holder.setDateTime(found_date)

    @fn_timer
    def reset_plot_selects_and_calib_help(self):
        """Reset self.cid and self.calib_help"""
        self.reset_cid()
        self.statusbar.clearMessage()

    @fn_timer
    def reset_settings(self):

        self.to_date_time.setDateTime(datestring_to_date("2099-12-31 23:59:59"))
        self.offset.setText("")
        self.best_fit_search_radius.setText("60 minutes")

        last_calibration = self.getlastcalibration(self.obsid)
        try:
            if last_calibration[0][1] and last_calibration[0][0]:
                self.logger_elevation.setText(f"{last_calibration[0][1]:.5f}")
                self.from_date_time.setDateTime(
                    datestring_to_date(last_calibration[0][0])
                    + datetime.timedelta(milliseconds=1)
                )
            else:
                self.logger_elevation.setText("")
                self.from_date_time.setDateTime(
                    datestring_to_date("2099-12-31 23:59:59")
                )
        except Exception as e:
            common_utils.MessagebarAndLog.info(
                log_msg=QCoreApplication.translate(
                    "Calibrlogger",
                    "Getting last calibration failed for obsid %s, msg: %s",
                )
                % (self.obsid, str(e))
            )
            self.logger_elevation.setText("")
            self.from_date_time.setDateTime(datestring_to_date("2099-12-31 23:59:59"))

    @fn_timer
    def reset_cid(self):
        """Resets self.cid to an empty list and disconnects unused events"""
        for x in self.cid:
            self.canvas.mpl_disconnect(x)
        self.cid = []

    @fn_timer
    def logger_pos_best_fit(self):
        self.loggerpos_masl_or_offset_state = 1
        self.calc_best_fit()

    @fn_timer
    def level_masl_best_fit(self):
        self.loggerpos_masl_or_offset_state = 0
        self.calc_best_fit()

    @fn_timer
    def calc_best_fit(self):
        """Calculates the self.logger_elevation from self.meas_ts and self.head_ts

        First matches measurements from self.meas_ts to logger values from
        self.head_ts. This is done by making a mean of all logger values inside
        self.meas_ts date - search_radius and self.meas_ts date + search_radius.
        (this could probably be change to get only the closest logger value
        inside the search_radius instead)
        (search_radius is gotten from self.get_search_radius())

        Then calculates the mean of all matches and set to self.logger_elevation.
        """
        obsid = self.load_obsid_and_init()
        common_utils.start_waiting_cursor()
        self.reset_plot_selects_and_calib_help()
        search_radius = self.get_search_radius()
        if self.loggerpos_masl_or_offset_state == 1:
            logger_ts = self.head_ts
            text_field = self.logger_elevation
            calib_func = self.set_logger_pos
        else:
            logger_ts = self.level_masl_ts
            text_field = self.offset
            calib_func = self.add_to_level_masl

        coupled_vals = self.match_ts_values(self.meas_ts, logger_ts, search_radius)
        if not coupled_vals:
            common_utils.pop_up_info(
                QCoreApplication.translate(
                    "Calibrlogger",
                    "There was no match found between measurements and logger values inside the chosen period.\n Try to increase the search radius or adjust the period!",
                )
            )
        else:
            calculated_diff = str(common_utils.calc_mean_diff(coupled_vals))
            if not calculated_diff or calculated_diff.lower() == "nan":
                common_utils.pop_up_info(
                    QCoreApplication.translate(
                        "Calibrlogger",
                        "There was no matched measurements or logger values inside the chosen period.\n Try to increase the search radius!",
                    )
                )
                common_utils.MessagebarAndLog.info(
                    log_msg=QCoreApplication.translate(
                        "Calibrlogger",
                        "Calculated water level from logger: midvatten_utils.calc_mean_diff(coupled_vals) didn't return a useable value.",
                    )
                )
            else:
                text_field.setText(calculated_diff)
                calib_func(obsid)

        common_utils.stop_waiting_cursor()

    @fn_timer
    def match_ts_values(self, meas_ts, logger_ts, search_radius_tuple):
        """Matches two timeseries values for shared timesteps

        For every measurement point, a mean of logger values inside
        measurementpoint + x minutes to measurementpoint - x minutes
        is coupled together.

        At the first used measurement, only logger values greater than
        the set start date is used.
        At the last measurement, only logger values lesser than the set end
        date is used.
        This is done so that values from another logger reposition is not
        mixed with the chosen logger positioning. (Hard to explain).
        """
        coupled_vals = []

        # Get the search radius, default to 60 minutes
        search_radius = int(search_radius_tuple[0])
        search_radius_period = search_radius_tuple[1]

        logger_gen = iter(logger_ts)
        try:
            log_row = next(logger_gen)
        except StopIteration:
            return None
        log_vals = []

        all_done = False
        # The .replace(tzinfo=None) is used to remove info about timezone. Needed for the comparisons. This should not be a problem though as the date scale in the plot is based on the dates from the database.
        outer_begin = self.from_date_time.dateTime().toPyDateTime().replace(tzinfo=None)
        outer_end = self.to_date_time.dateTime().toPyDateTime().replace(tzinfo=None)
        logger_step = datestring_to_date(log_row[0]).replace(tzinfo=None)
        for m in meas_ts:
            if logger_step is None:
                break
            meas_step = datestring_to_date(m[0]).replace(tzinfo=None)

            step_begin = dateshift(meas_step, -search_radius, search_radius_period)
            step_end = dateshift(meas_step, search_radius, search_radius_period)

            if step_end < outer_begin:
                continue
            if step_begin > outer_end:
                break

            # Skip logger steps that are earlier than the chosen begin date or are not inside the measurement period.
            while logger_step <= step_begin or logger_step <= outer_begin:
                try:
                    log_row = next(logger_gen)
                except StopIteration:
                    all_done = True
                    break
                logger_step = datestring_to_date(log_row[0]).replace(tzinfo=None)

            log_vals = []

            while (
                logger_step is not None
                and step_begin <= logger_step <= step_end
                and outer_begin <= logger_step <= outer_end
            ):
                if not math.isnan(float(log_row[1])) or log_row[1] in ("nan", "NULL"):
                    log_vals.append(float(log_row[1]))
                try:
                    log_row = next(logger_gen)
                except StopIteration:
                    all_done = True
                    break
                logger_step = datestring_to_date(log_row[0]).replace(tzinfo=None)

            if log_vals:
                mean = np.mean(log_vals)
                if not math.isnan(mean):
                    coupled_vals.append((m[1], mean))
            if all_done:
                break
        return coupled_vals

    @fn_timer
    def get_search_radius(self):
        """Get the period search radius, default to 60 minutes"""
        if not self.best_fit_search_radius.text():
            search_radius = "60 minutes"
            self.best_fit_search_radius.setText(search_radius)
        else:
            search_radius = self.best_fit_search_radius.text()

        search_radius_splitted = ru(search_radius).split()
        if len(search_radius_splitted) != 2:
            common_utils.pop_up_info(
                QCoreApplication.translate(
                    "Calibrlogger", "Must write time resolution also, ex. %s"
                )
                % "60 minutes"
            )
        return tuple(search_radius_splitted)

    @fn_timer
    def deactivate_pan_zoom(self):
        """Deactivates the NavigationToolbar pan or zoom feature if they are currently active"""
        try:
            a = self.mpltoolbar._active
        except AttributeError:
            # Adjustment for matplotlib ~3.5
            a = self.mpltoolbar.mode.name
        if a.upper() == "PAN":
            self.mpltoolbar.pan()
        elif a.upper() == "ZOOM":
            self.mpltoolbar.zoom()

    @fn_timer
    def delete_selected_range(self, table_name, set_to_null_instead=False):
        """Deletes or nulls the current selected range in the in-memory buffer.
        :return: None
        """
        if self._buf is None:
            common_utils.MessagebarAndLog.warning(bar_msg="No data loaded")
            return

        current_loaded_obsid = self.obsid
        selected_obsid = self.selected_obsid
        if current_loaded_obsid != selected_obsid:
            common_utils.pop_up_info(
                QCoreApplication.translate(
                    "Calibrlogger",
                    "Error!\n The obsid selection has been changed but the plot has not been updated. No deletion done.\nUpdating plot.",
                )
            )
            self.update_plot()
            return
        elif selected_obsid is None:
            common_utils.pop_up_info(
                QCoreApplication.translate(
                    "Calibrlogger",
                    "Error!\n No obsid was selected. No deletion done.\nUpdating plot.",
                )
            )
            self.update_plot()
            return

        fr_d_t = self.from_date_time.dateTime().toPyDateTime().replace(tzinfo=None)
        to_d_t = self.to_date_time.dateTime().toPyDateTime().replace(tzinfo=None)

        if set_to_null_instead:
            msg = QCoreApplication.translate(
                "Calibrlogger",
                "Do you want to set level_masl to NULL for the period %s to %s for obsid %s in table %s?",
            ) % (
                str(self.from_date_time.dateTime().toPyDateTime()),
                str(self.to_date_time.dateTime().toPyDateTime()),
                selected_obsid,
                table_name,
            )
        else:
            msg = QCoreApplication.translate(
                "Calibrlogger",
                "Do you want to delete the period %s to %s for obsid %s from table %s?",
            ) % (
                str(self.from_date_time.dateTime().toPyDateTime()),
                str(self.to_date_time.dateTime().toPyDateTime()),
                selected_obsid,
                table_name,
            )

        really_delete = common_utils.Askuser("YesNo", msg).result
        if really_delete:
            common_utils.start_waiting_cursor()
            mask = (fr_d_t <= self._buf.index) & (self._buf.index <= to_d_t)
            if set_to_null_instead:
                self._buf.loc[mask, "level_masl"] = np.nan
                self._history_push("Set to null")
            else:
                self._buf = self._buf.drop(index=self._buf.index[mask])
                self._history_push("Delete data")
            common_utils.stop_waiting_cursor()
            self.update_plot()

    @fn_timer
    def set_date_from_x(self, datetimeedit, help_msg=None, from_node=False):
        """Used to set the self.to_date_time by clicking on a line node in the plot self.canvas"""
        self.reset_plot_selects_and_calib_help()
        self.deactivate_pan_zoom()
        if help_msg:
            self.statusbar.showMessage(help_msg, 0)
        self.canvas.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.canvas.setFocus()
        if from_node:
            event = "pick_event"
        else:
            event = "button_press_event"
        self.cid.append(
            self.canvas.mpl_connect(
                event,
                lambda event: self.set_date_from_x_onclick(
                    event, datetimeedit, from_node
                ),
            )
        )

    def plot_or_update_selected_line(self):
        if self.logger_artist is None:
            return
        fr_d_t = self.from_date_time.dateTime().toPyDateTime().replace(tzinfo=None)
        to_d_t = self.to_date_time.dateTime().toPyDateTime().replace(tzinfo=None)
        xdata = self.logger_artist.get_xdata()
        ydata = [
            y if fr_d_t <= xdata[idx].replace(tzinfo=None) <= to_d_t else None
            for idx, y in enumerate(self.logger_artist.get_ydata())
        ]

        if self.selected_line is None:
            self.selected_line = self.axes.plot(
                xdata,
                ydata,
                linestyle="none",
                marker="o",
                markerfacecolor="None",
                markeredgecolor="black",
                markeredgewidth=1,
                markersize=4,
                zorder=30,
                label=QCoreApplication.translate("Calibrlogger", "Selected nodes"),
            )[0]
        else:
            self.selected_line.set_ydata(ydata)
        self.canvas.draw_idle()

    def connect_selected_line_move(self):
        self.cid.append(self.canvas.mpl_connect("pick_event", self.node_pressed))
        self.cid.append(
            self.canvas.mpl_connect("motion_notify_event", self.node_moving)
        )
        self.cid.append(
            self.canvas.mpl_connect("button_release_event", self.node_released)
        )

    def node_pressed(self, event):
        if isinstance(event, PickEvent) and event.mouseevent.button is MouseButton.LEFT:
            if self.logger_artist is not None and event.artist is self.logger_artist:
                self.moving_idx = event.ind[0]

    def node_moving(self, event):
        if self.moving_idx is not None and self.selected_line is not None:
            ydata = self.selected_line.get_ydata()
            _y = ydata[self.moving_idx]
            if _y is None:
                return
            diff = event.ydata - _y
            new_ydata = [y + diff if y is not None else None for y in ydata]
            self.selected_line.set_ydata(new_ydata)
            self.canvas.draw_idle()

    def node_released(self, event=None):
        if self.moving_idx is not None:
            logger_y = self.logger_artist.get_ydata()[self.moving_idx]
            selected_y = self.selected_line.get_ydata()[self.moving_idx]
            if logger_y is not None and selected_y is not None:
                offset = (
                    self.selected_line.get_ydata()[self.moving_idx]
                    - self.logger_artist.get_ydata()[self.moving_idx]
                )
                self.moving_idx = None
                if offset:
                    self.loggerpos_masl_or_offset_state = 1
                    self.offset.setText(f"{offset:.5f}")
                    self.add_to_level_masl()
            self.moving_idx = None

    def line_select_callback(self, eclick, erelease):
        """
        https://matplotlib.org/stable/gallery/widgets/rectangle_selector.html
        https://matplotlib.org/stable/gallery/widgets/rectangle_selector.html?highlight=rectangle%20selector

        :param eclick:
        :param erelease:
        :return:
        """
        x1, y1 = num2date(eclick.xdata), eclick.ydata
        x2, y2 = num2date(erelease.xdata), erelease.ydata
        y_idx = [
            idx
            for idx, y in enumerate(self.logger_artist.get_ydata())
            if min(y1, y2) <= y <= max(y1, y2)
        ]
        x_idx = [
            idx
            for idx, x in enumerate(self.logger_artist.get_xdata())
            if min(x1, x2) <= x <= max(x1, x2)
        ]
        found_idx = [idx for idx in x_idx if idx in y_idx]
        if found_idx:
            self.from_date_time.setDateTime(
                self.logger_artist.get_xdata()[min(found_idx)]
            )
            self.to_date_time.setDateTime(
                self.logger_artist.get_xdata()[max(found_idx)]
            )

    def toggle_move_nodes(self, on):
        if on:
            self.reset_cid()
            self.deactivate_pan_zoom()
            self.period_selector.set_active(False)
            self.select_nodes_button.uncheck()
            self.adjust_trend_button.uncheck()
            self._remove_trend_overlay()
            self.connect_selected_line_move()

    def toggle_select_nodes(self, on):
        if on:
            self.reset_cid()
            self.deactivate_pan_zoom()
            self.move_nodes_button.uncheck()
            self.adjust_trend_button.uncheck()
            self._remove_trend_overlay()
        self.period_selector.set_active(on)

    def toggle_adjust_trend(self, on: bool):
        if on:
            self.reset_cid()
            self.deactivate_pan_zoom()
            self.period_selector.set_active(False)
            self.select_nodes_button.uncheck()
            self.move_nodes_button.uncheck()
            self._draw_trend_overlay()
        else:
            self.reset_cid()
            self._remove_trend_overlay()

    def _draw_trend_overlay(self):
        self._remove_trend_overlay()
        self.reset_cid()

        if self._buf is None or self.logger_artist is None:
            self.statusbar.showMessage(
                QCoreApplication.translate("Calibrlogger", "No data loaded."),
                5000,
            )
            return

        fr_d_t = self.from_date_time.dateTime().toPyDateTime().replace(tzinfo=None)
        to_d_t = self.to_date_time.dateTime().toPyDateTime().replace(tzinfo=None)

        mask = (
            (fr_d_t <= self._buf.index)
            & (self._buf.index <= to_d_t)
            & self._buf["level_masl"].notna()
        )
        selected = self._buf.loc[mask]

        if len(selected) < 2:
            self.statusbar.showMessage(
                QCoreApplication.translate(
                    "Calibrlogger",
                    "Need at least 2 points with level_masl in the selected range.",
                ),
                5000,
            )
            return

        start_dt = selected.index[0]
        end_dt = selected.index[-1]
        start_y = selected["level_masl"].iloc[0]
        end_y = selected["level_masl"].iloc[-1]

        if start_dt == end_dt:
            self.statusbar.showMessage(
                QCoreApplication.translate(
                    "Calibrlogger",
                    "Selected points have the same timestamp — cannot define a trend.",
                ),
                5000,
            )
            return

        self._trend_line = self.axes.plot(
            [start_dt, end_dt],
            [start_y, end_y],
            linestyle="--",
            color="#dc5028",
            linewidth=2,
            zorder=40,
        )[0]

        self._trend_start_marker = self.axes.plot(
            [start_dt],
            [start_y],
            marker="o",
            markersize=12,
            color="#dc5028",
            zorder=41,
            picker=10,
        )[0]

        self._trend_end_marker = self.axes.plot(
            [end_dt],
            [end_y],
            marker="o",
            markersize=12,
            color="#dc5028",
            zorder=41,
            picker=10,
        )[0]

        self.cid.append(self.canvas.mpl_connect("pick_event", self._trend_pick))
        self.cid.append(
            self.canvas.mpl_connect("motion_notify_event", self._trend_move)
        )
        self.cid.append(
            self.canvas.mpl_connect("button_release_event", self._trend_release)
        )
        self.canvas.draw_idle()

    def _trend_pick(self, event):
        if not isinstance(event, PickEvent):
            return
        if event.artist is self._trend_start_marker:
            self._trend_dragging = "start"
        elif event.artist is self._trend_end_marker:
            self._trend_dragging = "end"
        else:
            return
        self._trend_original_start_y = self._trend_start_marker.get_ydata()[0]
        self._trend_original_end_y = self._trend_end_marker.get_ydata()[0]

    def _trend_move(self, event):
        if self._trend_dragging is None:
            return
        if event.ydata is None:
            return

        start_y = self._trend_start_marker.get_ydata()[0]
        end_y = self._trend_end_marker.get_ydata()[0]

        if self._trend_dragging == "start":
            start_y = event.ydata
        else:
            end_y = event.ydata

        self._trend_line.set_ydata([start_y, end_y])
        self._trend_start_marker.set_ydata([start_y])
        self._trend_end_marker.set_ydata([end_y])
        self.canvas.draw_idle()

    def _trend_release(self, event):
        if self._trend_dragging is None:
            return
        if self._buf is None:
            self._trend_dragging = None
            return

        new_start_y = self._trend_start_marker.get_ydata()[0]
        new_end_y = self._trend_end_marker.get_ydata()[0]
        original_start_y = self._trend_original_start_y
        original_end_y = self._trend_original_end_y
        self._trend_dragging = None

        if (
            abs(new_start_y - original_start_y) < 1e-10
            and abs(new_end_y - original_end_y) < 1e-10
        ):
            return

        fr_d_t = self.from_date_time.dateTime().toPyDateTime().replace(tzinfo=None)
        to_d_t = self.to_date_time.dateTime().toPyDateTime().replace(tzinfo=None)

        mask = (
            (fr_d_t <= self._buf.index)
            & (self._buf.index <= to_d_t)
            & self._buf["level_masl"].notna()
        )
        selected = self._buf.loc[mask]
        if len(selected) < 2:
            return

        common_utils.start_waiting_cursor()
        sub = self._buf.loc[mask].copy()
        applied = apply_trend_correction(
            sub, original_start_y, original_end_y, new_start_y, new_end_y
        )
        if applied:
            self._buf.loc[mask, "level_masl"] = sub["level_masl"]

            obsid = self._buf_obsid or ""
            delta_start = new_start_y - original_start_y
            delta_end = new_end_y - original_end_y
            common_utils.MessagebarAndLog.info(
                log_msg=QCoreApplication.translate(
                    "Calibrlogger",
                    "Trend adjusted for %s (%s to %s): Δ_start=%.4f, Δ_end=%.4f",
                )
                % (
                    obsid,
                    fr_d_t.strftime(_DT_FMT),
                    to_d_t.strftime(_DT_FMT),
                    delta_start,
                    delta_end,
                )
            )
            self._history_push("Adjust trend")

        common_utils.stop_waiting_cursor()
        self.update_plot()

    def _remove_trend_overlay(self):
        for attr in ("_trend_line", "_trend_start_marker", "_trend_end_marker"):
            artist = getattr(self, attr, None)
            if artist is not None:
                try:
                    artist.remove()
                except (ValueError, NotImplementedError):
                    pass
                setattr(self, attr, None)
        self._trend_dragging = None


class SelectNodesButton(NavigationButton):
    def __init__(self, parent, fig):
        super().__init__(parent, fig)
        self._button_setup = [
            (
                "select nodes",
                self.clicked,
                "Select nodes",
                os.path.join(
                    os.path.dirname(__file__), "..", "icons", "select_nodes.png"
                ),
            )
        ]
        self.connect_toolbar()

    def button(self):
        return list(self.actions.values())[0]

    def clicked(self):
        if not self.button().isChecked():
            self.parent.reset_cid()
        self.parent.toggle_select_nodes(self.button().isChecked())


class MoveNodesButton(NavigationButton):
    def __init__(self, parent, fig):
        super().__init__(parent, fig)
        self._button_setup = [
            (
                "move nodes",
                self.clicked,
                "Move nodes",
                os.path.join(
                    os.path.dirname(__file__), "..", "icons", "move_nodes.png"
                ),
            )
        ]
        self.connect_toolbar()

    def button(self):
        return list(self.actions.values())[0]

    def clicked(self):
        if not self.button().isChecked():
            self.parent.reset_cid()
        self.parent.toggle_move_nodes(self.button().isChecked())


class MultiCursorButton(NavigationButton):
    def __init__(self, parent, fig):
        super().__init__(parent, fig)
        self._button_setup = [
            (
                "show crosshair",
                self.clicked,
                "Show crosshair",
                os.path.join(os.path.dirname(__file__), "..", "icons", "crosshair.png"),
            )
        ]
        self.connect_toolbar()
        self.mc = MultiCursor(
            fig.canvas, fig.axes, horizOn=True, vertOn=True, color="k", lw=0.8, ls="--"
        )
        self.mc.visible = False

    def clicked(self):
        self.mc.visible = self.button().isChecked()
        if not self.mc.visible:
            self.fig.canvas.draw_idle()


class AdjustTrendButton(NavigationButton):
    def __init__(self, parent, fig):
        super().__init__(parent, fig)
        self._button_setup = [
            (
                "adjust trend",
                self.clicked,
                "Adjust trend",
                os.path.join(
                    os.path.dirname(__file__), "..", "icons", "adjust_trend.png"
                ),
            )
        ]
        self.connect_toolbar()

    def button(self):
        return list(self.actions.values())[0]

    def clicked(self):
        if not self.button().isChecked():
            self.parent.reset_cid()
        self.parent.toggle_adjust_trend(self.button().isChecked())


def _iter_filter_combos(filters: list[dict]):
    """Yield one {col: value} mapping per cartesian-product combination of selected filter values."""
    active = [(f["col"], f["values"]) for f in filters if f.get("values")]
    if not active:
        yield {}
        return
    cols = [col for col, _ in active]
    value_lists = [vals for _, vals in active]
    for combo_vals in itertools.product(*value_lists):
        yield dict(zip(cols, combo_vals))


def _ref_series_filter_str(s: dict) -> str:
    return ", ".join(
        f"{f['col']}={'+'.join(str(v) for v in f['values'])}"
        for f in s.get("filters", [])
        if f.get("values")
    )


def _ref_series_auto_label(s: dict) -> str:
    base = f"{s.get('table', '?')}.{s.get('y_col', '?')}"
    filter_str = _ref_series_filter_str(s)
    return f"{base} [{filter_str}]" if filter_str else base


def _ref_series_combo_label(s: dict, combo: dict, is_multi: bool) -> str:
    combo_str = ", ".join(str(v) for v in combo.values())
    user_label = s.get("label", "")
    if is_multi:
        return f"{user_label} ({combo_str})" if user_label else combo_str
    return user_label or _ref_series_auto_label(s)


def _ref_series_plot_style(ax, x, y, style: str, label: str) -> None:
    kw: dict = {"label": label}
    if style == "line":
        ax.plot(x, y, **kw)
    elif style == "marker":
        ax.plot(x, y, linestyle="none", marker="o", markersize=3, **kw)
    elif style == "line+marker":
        ax.plot(x, y, marker="o", markersize=3, **kw)
    elif style == "step-pre":
        ax.step(x, y, where="pre", **kw)
    elif style == "step-post":
        ax.step(x, y, where="post", **kw)
    else:
        ax.plot(x, y, **kw)
