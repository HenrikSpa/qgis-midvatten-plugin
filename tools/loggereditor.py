import datetime
import itertools
import json
import logging
import math
import os
import traceback

import numpy as np
import pandas as pd
import qgis.PyQt
from qgis.PyQt.QtCore import QCoreApplication, Qt, QTimer
from qgis.PyQt.QtGui import QCloseEvent, QFont, QIcon, QKeySequence
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QShortcut,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from midvatten.tools.utils.legend_picker import LegendPicker
import matplotlib.lines
from matplotlib import pyplot as plt, ticker as tick
from matplotlib.backend_bases import PickEvent, MouseButton
from matplotlib.gridspec import GridSpec

from midvatten.tools.utils.mpl_compat import FigureCanvas, NavigationToolbar
from matplotlib.dates import num2date, datestr2num, date2num
from matplotlib.transforms import blended_transform_factory
from matplotlib.widgets import MultiCursor, RectangleSelector

from qgis.PyQt import uic
from midvatten.definitions import midvatten_defs as defs
from midvatten.tools.utils import (
    common_utils,
    db_utils,
    dialog_utils,
    exceptions,
    message_utils,
)
from midvatten.tools.utils.common_utils import fn_timer
from midvatten.tools.utils.db_utils.dialect import ident
from midvatten.tools.utils.db_utils.execution import use_or_create_connection
from midvatten.tools.utils.file_utils import ui_path
from midvatten.tools.utils.string_utils import returnunicode as ru
from midvatten.tools.utils.date_utils import (
    change_timezone,
    to_date,
    dateshift,
)
from midvatten.tools.utils.gui_utils import NavigationButton, WA_DeleteOnClose
from midvatten.tools.loggereditor_refseries import RefSeriesDialog
from midvatten.tools.loggereditor_resolve_dupes import ResolveDuplicatesDialog
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
        self._series_buf: dict[int, dict] = {}
        self._original_series_buf: dict[int, dict] = {}
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
        self._dupe_marker_artists: list = []
        self._resolve_dialog = None

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
        self.push_button_from_selection.clicked.connect(self._from_date_from_selection)
        self.push_button_to_selection.clicked.connect(self._to_date_from_selection)
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

            self._existing_columns = existing_columns

            _cb_font = QFont("Noto Sans", 8)

            self.logger_line_nodes = QCheckBox(
                QCoreApplication.translate(
                    "Calibrlogger", "Circle nodes for logger line"
                )
            )
            self.logger_line_nodes.setChecked(True)
            self.logger_line_nodes.setFont(_cb_font)
            self.logger_line_nodes.setToolTip(
                QCoreApplication.translate(
                    "Calibrlogger",
                    "Show circle markers at each data point on the logger line",
                )
            )

            self.plot_logger_head = QCheckBox(
                QCoreApplication.translate("Calibrlogger", "Plot logger water head")
            )
            self.plot_logger_head.setChecked(True)
            self.plot_logger_head.setFont(_cb_font)
            self.plot_logger_head.setToolTip(
                QCoreApplication.translate(
                    "Calibrlogger",
                    "Plot the raw head_cm column as a separate line",
                )
            )

            self.normalize_head = QCheckBox(
                QCoreApplication.translate(
                    "Calibrlogger", "Normalize head to logger line"
                )
            )
            self.normalize_head.setChecked(True)
            self.normalize_head.setFont(_cb_font)
            self.normalize_head.setToolTip(
                QCoreApplication.translate(
                    "Calibrlogger",
                    "Shift head_cm line so its mean matches level_masl mean"
                    " (visual only, no DB change)",
                )
            )

            self.separate_source_cb = QCheckBox(
                QCoreApplication.translate("Calibrlogger", "Separate by source")
            )
            self.separate_source_cb.setChecked(True)
            self.separate_source_cb.setFont(_cb_font)
            self.separate_source_cb.setToolTip(
                QCoreApplication.translate(
                    "Calibrlogger",
                    "Draw separate lines per data source",
                )
            )

            self.separate_created_at_cb = QCheckBox(
                QCoreApplication.translate("Calibrlogger", "Separate by import time")
            )
            self.separate_created_at_cb.setFont(_cb_font)
            self.separate_created_at_cb.setToolTip(
                QCoreApplication.translate(
                    "Calibrlogger",
                    "Draw separate lines per import timestamp",
                )
            )

            self.separate_dt_precision_cb = QCheckBox(
                QCoreApplication.translate(
                    "Calibrlogger", "Separate by datetime precision"
                )
            )
            self.separate_dt_precision_cb.setFont(_cb_font)
            self.separate_dt_precision_cb.setToolTip(
                QCoreApplication.translate(
                    "Calibrlogger",
                    "Draw separate lines per datetime string precision",
                )
            )

            if self._schema_variant == "no_source":
                self.separate_source_cb.setEnabled(False)
                self.separate_source_cb.setChecked(False)
                self.separate_source_cb.setToolTip(
                    QCoreApplication.translate(
                        "Calibrlogger",
                        "Source column not available in this database",
                    )
                )
            if "created_at" not in existing_columns:
                self.separate_created_at_cb.setEnabled(False)
                self.separate_created_at_cb.setToolTip(
                    QCoreApplication.translate(
                        "Calibrlogger",
                        "created_at column not available in this database",
                    )
                )

            self._created_at_grouping: str | None = None
            self._selected_line_keys: set = set()
            self._legend_picker = None

            self.separate_created_at_cb.stateChanged.connect(
                lambda _: self._on_created_at_toggled()
            )

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

            # --- Duplicate-timestamps banner (hidden unless duplicates exist) ---
            self._dupe_banner = QWidget(self)
            dupe_layout = QHBoxLayout(self._dupe_banner)
            dupe_layout.setContentsMargins(0, 0, 0, 0)
            self._dupe_warning_label = QLabel("", self)
            self._resolve_dupes_btn = QPushButton(
                QCoreApplication.translate("LoggerEditor", "Resolve duplicates…"),
                self,
            )
            self._resolve_dupes_btn.clicked.connect(self._open_resolve_dupes_dialog)
            dupe_layout.addWidget(self._dupe_warning_label)
            dupe_layout.addWidget(self._resolve_dupes_btn)
            dupe_layout.addStretch()
            parent_layout.insertWidget(max(tab_index, 0), self._dupe_banner)
            self._dupe_banner.setVisible(False)

            # --- Series tab (only for series_join schema) ---
            if self._schema_variant == "series_join":
                self._series_tab = self._build_series_tab()
                self.tab_widget.addTab(
                    self._series_tab,
                    QCoreApplication.translate("LoggerEditor", "Series"),
                )
                self.tab_widget.currentChanged.connect(self._on_tab_changed)

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

            self.update_plot()

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
        self.combobox_obsid.setPlaceholderText(
            QCoreApplication.translate("Calibrlogger", "Select an obsid...")
        )
        self.combobox_obsid.addItems(self.get_all_obsids_in_w_levels_logger())
        self.update_combobox_with_calibration_info(
            _obsids_with_uncalibrated_data=self.get_uncalibrated_obsids()
        )
        # Start clean: no obsid is loaded until the user picks one.
        self.combobox_obsid.setCurrentIndex(-1)

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
        """Build a (date_time, values, source, line_key) recarray from a DataFrame column."""
        n = len(buf)
        sources = buf["source"].to_numpy()
        max_src_len = int(buf["source"].str.len().max() or 0)
        if "_line_key" in buf.columns:
            line_keys = buf["_line_key"].tolist()
        else:
            line_keys = [("_all",)] * n
        arr = np.empty(
            n,
            dtype=[
                ("date_time", object),
                ("values", float),
                ("source", f"U{max(max_src_len, 1)}"),
                ("line_key", object),
            ],
        )
        arr["date_time"] = buf.index.strftime(_DT_FMT).to_numpy()
        arr["values"] = (
            values_override
            if values_override is not None
            else buf[col].to_numpy(dtype=float, na_value=np.nan)
        )
        arr["source"] = sources
        arr["line_key"] = line_keys
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
            message_utils.MessagebarAndLog.warning(
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
            message_utils.MessagebarAndLog.warning(
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

    def _build_optional_extra_cols(
        self, has_created_at: bool, has_comment: bool, prefix: str = ""
    ) -> str:
        """Return a SQL fragment of optional trailing SELECT columns.

        ``prefix`` is prepended to each column reference (e.g. ``"l."`` for
        aliased joins).  The fragment always ends with the dt_length column so
        callers can rely on a fixed trailing position."""
        extra = ""
        if has_created_at:
            extra += f", COALESCE({prefix}created_at, '') AS created_at"
        if has_comment:
            extra += f", COALESCE({prefix}comment, '') AS comment"
        extra += f", LENGTH({prefix}date_time) AS dt_length"
        return extra

    def _recompute_line_keys(self):
        if self._buf is not None and not self._buf.empty:
            new_keys = self._compute_line_keys(
                self._buf,
                separate_source=self.separate_source_cb.isChecked(),
                separate_created_at=self.separate_created_at_cb.isChecked(),
                separate_dt_precision=self.separate_dt_precision_cb.isChecked(),
                created_at_grouping=self._created_at_grouping,
            )
            old_keys = (
                self._buf["_line_key"].tolist()
                if "_line_key" in self._buf.columns
                else None
            )
            self._buf["_line_key"] = new_keys
            if old_keys != new_keys:
                self._buf_version += 1
        if self._legend_picker is not None:
            self._legend_picker.disconnect()
            self._legend_picker = None

    def _focus_plot_on_instants(self, instants: list) -> None:
        """Drive the main plot to show the competing rows at ``instants``:
        enable datetime-precision separation (so twins draw as distinct lines),
        select the affected line keys, and set the date range to span them."""
        if self._buf is None or not instants:
            return
        self.separate_dt_precision_cb.setChecked(True)
        self._recompute_line_keys()
        mask = self._buf.index.isin(instants)
        if "_line_key" in self._buf.columns:
            self._selected_line_keys = set(self._buf.loc[mask, "_line_key"].tolist())
        lo = min(instants)
        hi = max(instants)
        self.from_date_time.setDateTime(lo - pd.Timedelta(days=1))
        self.to_date_time.setDateTime(hi + pd.Timedelta(days=1))
        self.update_plot()

    def _duplicate_instants(self) -> pd.DatetimeIndex:
        """Parsed-datetime labels occurring more than once in _buf.

        A repeated label means two rows share the same normalized instant
        (same (obsid, datetime(date_time))) but differ in raw date_time text.
        """
        if self._buf is None or self._buf.empty:
            return pd.DatetimeIndex([])
        dup_mask = self._buf.index.duplicated(keep=False)
        return self._buf.index[dup_mask].unique()

    def _full_buffer_range(self) -> tuple:
        """(min, max) timestamp of the buffer index, or (None, None) if empty."""
        if self._buf is None or self._buf.empty:
            return (None, None)
        idx = self._buf.index
        return (idx.min(), idx.max())

    def _duplicate_runs(self) -> list:
        """Maximal runs of duplicated instants that are consecutive in the
        buffer's sorted distinct instants. Returns [(start_ts, end_ts), ...].
        A run breaks where a non-duplicated instant interrupts it. Scale-safe:
        an overlap of thousands of rows collapses to one run."""
        if self._buf is None or self._buf.empty:
            return []
        distinct = self._buf.index.unique().sort_values()
        dup_set = set(self._duplicate_instants())
        runs = []
        run_start = None
        prev = None
        for ts in distinct:
            if ts in dup_set:
                if run_start is None:
                    run_start = ts
                prev = ts
            else:
                if run_start is not None:
                    runs.append((run_start, prev))
                    run_start = None
        if run_start is not None:
            runs.append((run_start, prev))
        return runs

    def _classify_duplicates(self, fr=None, to=None) -> list[dict]:
        """Classify each duplicated instant in _buf.

        When *fr* and/or *to* are given, only instants within [fr, to] are
        returned; omit both (the default) to classify the full buffer.

        Returns a list of dicts: {"instant": Timestamp, "kind": str,
        "rows": [row-dict, ...]}, where kind is one of:
          - "cross_source": the competing rows come from >1 distinct source
          - "redundant":    same source and equal head_cm_m AND level_masl
          - "conflict":     same source but head_cm_m or level_masl differ
        """
        if self._buf is None:
            return []
        # Group the duplicated rows once (O(rows)) instead of scanning the whole
        # buffer per instant (O(instants x rows)) — matters for obsids with tens
        # of thousands of duplicates.
        dup = self._buf[self._buf.index.duplicated(keep=False)]
        if fr is not None:
            dup = dup[dup.index >= fr]
        if to is not None:
            dup = dup[dup.index <= to]
        if dup.empty:
            return []
        row_cols = ["date_time_raw", "head_cm_m", "level_masl", "source", "dt_length"]
        has_created_at = "created_at" in dup.columns
        groups = []
        for instant, sub in dup.groupby(level=0, sort=True):
            rows = []
            for _, r in sub.iterrows():
                row = {c: r[c] for c in row_cols}
                row["series_id"] = (
                    None if pd.isna(r["series_id"]) else int(r["series_id"])
                )
                if has_created_at:
                    row["created_at"] = r["created_at"]
                rows.append(row)
            sources = {r["source"] for r in rows}
            if len(sources) > 1:
                kind = "cross_source"
            elif (
                sub["head_cm_m"].nunique(dropna=False) <= 1
                and sub["level_masl"].nunique(dropna=False) <= 1
            ):
                # nunique(dropna=False) == 1 means all values equal (NaN==NaN).
                kind = "redundant"
            else:
                kind = "conflict"
            groups.append({"instant": instant, "kind": kind, "rows": rows})
        return groups

    def _drop_rows_by_raw(self, drop_raws: set, label: str) -> None:
        """Drop buffer rows whose date_time_raw is in drop_raws; snapshot for undo.

        date_time_raw is unique per row, so this removes exactly the chosen rows.
        Line keys are recomputed by the next plot refresh, not here (this method
        is callable without show())."""
        if not drop_raws:
            return
        self._buf = self._buf[~self._buf["date_time_raw"].isin(drop_raws)]
        self._history_push(label)

    def _remove_redundant_duplicates(self, fr=None, to=None) -> int:
        """Drop coarse twins at every 'redundant' instant, keeping the row with
        the highest datetime precision (longest dt_length; tie-break newest
        created_at when available). Returns the number of rows removed."""
        drop_raws = set()
        for grp in self._classify_duplicates(fr, to):
            if grp["kind"] != "redundant":
                continue
            keep = max(
                grp["rows"],
                key=lambda r: (r["dt_length"], r.get("created_at", "")),
            )
            for r in grp["rows"]:
                if r["date_time_raw"] != keep["date_time_raw"]:
                    drop_raws.add(r["date_time_raw"])
        self._drop_rows_by_raw(drop_raws, "Remove redundant duplicates")
        return len(drop_raws)

    def _remove_cross_source_overlaps(self, keep_source: str, fr=None, to=None) -> int:
        """At every 'cross_source' instant where keep_source is present, drop the
        rows from the other sources. Instants without keep_source are left
        untouched (never emptied). Returns the number of rows removed."""
        drop_raws = set()
        for grp in self._classify_duplicates(fr, to):
            if grp["kind"] != "cross_source":
                continue
            sources_here = {r["source"] for r in grp["rows"]}
            if keep_source not in sources_here:
                continue
            for r in grp["rows"]:
                if r["source"] != keep_source:
                    drop_raws.add(r["date_time_raw"])
        self._drop_rows_by_raw(drop_raws, "Remove cross-source overlaps")
        return len(drop_raws)

    def _resolve_conflict_keep(self, instant: pd.Timestamp, keep_raw: str) -> int:
        """At a single duplicated instant, keep the row whose date_time_raw is
        keep_raw and drop the others. Returns the number of rows removed."""
        sub = self._buf[self._buf.index == instant]
        drop_raws = {r for r in sub["date_time_raw"].tolist() if r != keep_raw}
        self._drop_rows_by_raw(drop_raws, "Resolve duplicate conflict")
        return len(drop_raws)

    def _label_for_key(self, obsid: str, key: tuple, translated_suffix: str) -> str:
        """Build a plot-line label from a line key. ``translated_suffix`` is the
        already-translated base (e.g. " logger water level"); the active
        "Separate by ..." dimensions are appended in key order."""
        label = obsid + translated_suffix
        parts = []
        dim_idx = 0
        if self.separate_source_cb.isChecked():
            src = key[dim_idx]
            dim_idx += 1
            if src and str(src).strip():
                parts.append(str(src))
        if self.separate_created_at_cb.isChecked():
            parts.append(f"imported={key[dim_idx]}")
            dim_idx += 1
        if self.separate_dt_precision_cb.isChecked():
            parts.append(f"dt_len={key[dim_idx]}")
            dim_idx += 1
        if parts:
            label += ", " + ", ".join(parts)
        return label

    def _label_for_line_key(self, obsid: str, key: tuple) -> str:
        return self._label_for_key(
            obsid,
            key,
            QCoreApplication.translate("Calibrlogger", " logger water level"),
        )

    def _label_for_head_key(self, obsid: str, key: tuple) -> str:
        return self._label_for_key(
            obsid,
            key,
            QCoreApplication.translate("Calibrlogger", " logger head"),
        )

    def _on_legend_pick(self, ax_lines: list):
        self._selected_line_keys = set()
        for line in ax_lines:
            if hasattr(line, "_line_key"):
                self._selected_line_keys.add(line._line_key)
        self.plot_or_update_selected_line()
        self._update_selection_button_state()

    @property
    def selected_line_keys(self) -> set:
        return getattr(self, "_selected_line_keys", set())

    def _build_edit_mask(
        self, fr_d_t, to_d_t, value_col: str | None = None
    ) -> pd.Series:
        fr = pd.Timestamp(fr_d_t)
        to = pd.Timestamp(to_d_t)
        mask = (fr <= self._buf.index) & (self._buf.index <= to)
        if value_col is not None:
            mask = mask & self._buf[value_col].notna()
        if self.selected_line_keys and "_line_key" in self._buf.columns:
            mask = mask & self._buf["_line_key"].isin(self.selected_line_keys)
        return mask

    def _on_created_at_toggled(self):
        if not self.separate_created_at_cb.isChecked():
            self._created_at_grouping = None
            return

        if self._buf is None or "created_at" not in self._buf.columns:
            return

        distinct_count = self._buf["created_at"].nunique()
        if distinct_count <= 10:
            self._created_at_grouping = None
            return

        box = qgis.PyQt.QtWidgets.QMessageBox(self)
        box.setWindowTitle(
            QCoreApplication.translate("Calibrlogger", "Many import timestamps")
        )
        box.setText(
            QCoreApplication.translate(
                "Calibrlogger",
                "Found {} distinct import timestamps. This may clutter the plot.",
            ).format(distinct_count)
        )
        btn_hour = box.addButton(
            QCoreApplication.translate("Calibrlogger", "Group by hour"),
            qgis.PyQt.QtWidgets.QMessageBox.ActionRole,
        )
        btn_day = box.addButton(
            QCoreApplication.translate("Calibrlogger", "Group by day"),
            qgis.PyQt.QtWidgets.QMessageBox.ActionRole,
        )
        btn_continue = box.addButton(
            QCoreApplication.translate("Calibrlogger", "Continue without grouping"),
            qgis.PyQt.QtWidgets.QMessageBox.ActionRole,
        )
        box.addButton(qgis.PyQt.QtWidgets.QMessageBox.Cancel)

        box.exec_()
        clicked = box.clickedButton()

        if clicked is btn_hour:
            self._created_at_grouping = "hour"
        elif clicked is btn_day:
            self._created_at_grouping = "day"
        elif clicked is btn_continue:
            self._created_at_grouping = None
        else:
            self.separate_created_at_cb.blockSignals(True)
            self.separate_created_at_cb.setChecked(False)
            self.separate_created_at_cb.blockSignals(False)

    def _from_date_from_selection(self) -> None:
        if not self.selected_line_keys or self._buf is None:
            return
        mask = self._buf["_line_key"].isin(self.selected_line_keys)
        selected_data = self._buf.loc[mask]
        if selected_data.empty:
            return
        self.from_date_time.setDateTime(selected_data.index.min())

    def _to_date_from_selection(self) -> None:
        if not self.selected_line_keys or self._buf is None:
            return
        mask = self._buf["_line_key"].isin(self.selected_line_keys)
        selected_data = self._buf.loc[mask]
        if selected_data.empty:
            return
        self.to_date_time.setDateTime(selected_data.index.max())

    def _update_selection_button_state(self) -> None:
        enabled = bool(self.selected_line_keys)
        self.push_button_from_selection.setEnabled(enabled)
        self.push_button_to_selection.setEnabled(enabled)

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
            self._recompute_line_keys()  # updates _line_key + bumps _buf_version
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
            existing_columns = getattr(self, "_existing_columns", [])
            has_created_at = "created_at" in existing_columns
            has_comment = "comment" in existing_columns
            if schema_variant == "series_join":
                extra_cols = self._build_optional_extra_cols(
                    has_created_at, has_comment, prefix="l."
                )
                head_level_masl_sql = (
                    f"SELECT l.date_time, l.head_cm / 100, l.level_masl,"
                    f" TRIM(COALESCE(s.source, '')), l.series_id{extra_cols}"
                    f" FROM w_levels_logger l"
                    f" LEFT JOIN w_logger_series s ON s.id = l.series_id"
                    f" WHERE l.obsid = {ph} ORDER BY l.date_time"
                )
            elif schema_variant == "source_col":
                extra_cols = self._build_optional_extra_cols(
                    has_created_at, has_comment
                )
                head_level_masl_sql = (
                    f"SELECT date_time, head_cm / 100, level_masl,"
                    f" TRIM(COALESCE(source, '')), NULL AS series_id{extra_cols}"
                    f" FROM w_levels_logger WHERE obsid = {ph}"
                    f" ORDER BY date_time"
                )
            else:
                extra_cols = self._build_optional_extra_cols(
                    has_created_at, has_comment
                )
                head_level_masl_sql = (
                    f"SELECT date_time, head_cm / 100, level_masl,"
                    f" '' as source, NULL AS series_id{extra_cols}"
                    f" FROM w_levels_logger WHERE obsid = {ph}"
                    f" ORDER BY date_time"
                )

            _ok, head_level_masl_list = db_utils.sql_load_fr_db(
                head_level_masl_sql, dbconnection=dbconnection, execute_args=(obsid,)
            )

            if schema_variant == "series_join":
                series_rows = dbconnection.execute_and_fetchall(
                    f"SELECT id, obsid, source, instrument, description, comment"
                    f" FROM w_logger_series WHERE obsid = {ph}",
                    (obsid,),
                )
                self._series_buf = {
                    row[0]: {
                        "obsid": row[1],
                        "source": row[2],
                        "instrument": row[3],
                        "description": row[4],
                        "comment": row[5],
                    }
                    for row in series_rows
                }
            else:
                self._series_buf = {}

            dbconnection.closedb()

            if head_level_masl_list:
                cols_data: dict = {
                    "head_cm_m": [r[1] for r in head_level_masl_list],
                    "level_masl": [r[2] for r in head_level_masl_list],
                    "source": [r[3] for r in head_level_masl_list],
                    "series_id": pd.array(
                        [r[4] for r in head_level_masl_list], dtype="Int64"
                    ),
                }
                col_idx = 5
                # Same order as _build_optional_extra_cols emits them.
                for colname, present in (
                    ("created_at", has_created_at),
                    ("comment", has_comment),
                ):
                    if present:
                        cols_data[colname] = [
                            str(r[col_idx]) if r[col_idx] else ""
                            for r in head_level_masl_list
                        ]
                        col_idx += 1
                cols_data["dt_length"] = [r[col_idx] for r in head_level_masl_list]
                cols_data["date_time_raw"] = [r[0] for r in head_level_masl_list]
                buf_df = pd.DataFrame(
                    cols_data,
                    index=pd.to_datetime(
                        [r[0] for r in head_level_masl_list],
                        format="mixed",
                    ).to_pydatetime(),
                )
            else:
                buf_cols = ["head_cm_m", "level_masl", "source", "series_id"]
                if has_created_at:
                    buf_cols.append("created_at")
                if has_comment:
                    buf_cols.append("comment")
                buf_cols.append("dt_length")
                buf_cols.append("date_time_raw")
                buf_df = pd.DataFrame(columns=buf_cols)
                buf_df["series_id"] = pd.array([], dtype="Int64")
            self._buf = buf_df
            self._recompute_line_keys()
            self._original_buf = buf_df.copy()
            self._original_series_buf = {
                k: dict(v) for k, v in self._series_buf.items()
            }
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
        id_mapping: dict[int, int] = {}

        common_utils.start_waiting_cursor()
        try:
            try:
                # Duplicate instants (two rows with the same normalized
                # datetime but different raw text) cannot be addressed
                # individually by the editor. Drop them from the local diff
                # buffers so the save targets only the unique rows, and warn
                # the user. The real buffers keep the twins — a later plan
                # adds a UI to resolve them.
                dup_mask = self._buf.index.duplicated(keep=False)
                has_dups = bool(dup_mask.any())
                buf_raw = set(self._buf["date_time_raw"])
                if has_dups:
                    dup_instants = self._buf.index[dup_mask].unique()
                    buf = self._buf[~dup_mask]
                    original_buf = self._original_buf[
                        ~self._original_buf.index.duplicated(keep=False)
                    ]
                    head = dup_instants[:5]
                    sample = ", ".join(head.strftime(_DT_FMT))
                    more = (
                        f" (+{len(dup_instants) - len(head)} more)"
                        if len(dup_instants) > len(head)
                        else ""
                    )
                    message_utils.MessagebarAndLog.warning(
                        bar_msg=QCoreApplication.translate(
                            "LoggerEditor",
                            "%s duplicate timestamp(s) were skipped while saving."
                            " Resolve duplicates to save edits at those times.",
                        )
                        % len(dup_instants),
                        log_msg=(
                            f"Skipped duplicate instants for obsid {obsid}:"
                            f" {sample}{more}"
                        ),
                    )
                else:
                    buf = self._buf
                    # A resolved twin (one of a duplicate pair dropped from
                    # the buffer) leaves self._buf clean, but
                    # self._original_buf still carries the duplicate index
                    # label. Align original_buf to the surviving rows by raw
                    # text so the UPDATE diff compares identically-labeled
                    # Series.
                    original_buf = self._original_buf[
                        self._original_buf["date_time_raw"].isin(buf_raw)
                    ]

                # Compute deletions over the FULL buffers by raw date_time text
                # so that dropping one twin (same normalized instant, different
                # raw text) is caught -- a label set-difference on the deduped
                # buffers would miss it because the surviving twin keeps the
                # label.
                orig_raw = self._original_buf["date_time_raw"]
                deleted_raw = orig_raw[~orig_raw.isin(buf_raw)].tolist()
                delete_params = [(obsid, raw) for raw in deleted_raw]

                common_index = original_buf.index.intersection(buf.index)
                orig_vals = original_buf.loc[common_index, "level_masl"]
                new_vals = buf.loc[common_index, "level_masl"]
                changed_mask = ~(
                    (orig_vals == new_vals) | (orig_vals.isna() & new_vals.isna())
                )
                changed_index = common_index[changed_mask]
                orig_changed = orig_vals.loc[changed_index]
                new_changed = new_vals.loc[changed_index]
                head_changed = buf.loc[changed_index, "head_cm_m"]
            except Exception as e:
                message_utils.MessagebarAndLog.critical(
                    bar_msg=QCoreApplication.translate(
                        "LoggerEditor",
                        "Save failed while computing changes;"
                        " nothing was written to the database.",
                    ),
                    log_msg=f"{e}\n{traceback.format_exc()}",
                )
                return False

            try:
                dbconnection = db_utils.DbConnectionManager()
            except Exception as e:
                message_utils.MessagebarAndLog.critical(
                    bar_msg=QCoreApplication.translate(
                        "LoggerEditor", "Save failed: could not connect to database."
                    ),
                    log_msg=f"{e}\n{traceback.format_exc()}",
                )
                return False

            try:
                ph = dbconnection.placeholder()
                tbl = ident("w_levels_logger")
                # SQLite stores date_time as text; normalize both sides so that
                # '2017-02-01 00:00' and '2017-02-01 00:00:00' compare equal.
                is_sqlite = dbconnection.is_sqlite()
                if is_sqlite:
                    dt_eq = f"datetime({ident('date_time')}) = datetime({ph})"
                else:
                    dt_eq = f"{ident('date_time')}::timestamp = {ph}::timestamp"
                range_stmts, per_row_params = self._compute_update_statements(
                    buf,
                    changed_index,
                    orig_changed,
                    new_changed,
                    head_changed,
                    obsid,
                    tbl,
                    ph,
                    is_sqlite,
                    force_per_row=has_dups,
                )
                with dbconnection.transaction():
                    if delete_params:
                        delete_sql = (
                            f"DELETE FROM {tbl} WHERE {ident('obsid')} = {ph}"
                            f" AND {ident('date_time')} = {ph}"
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

                    # --- Series CRUD (only for series_join schema) ---
                    if self._schema_variant == "series_join":
                        series_tbl = ident("w_logger_series")
                        logger_tbl = ident("w_levels_logger")

                        # 1. INSERT new series (negative temporary IDs)
                        new_series = {
                            k: v
                            for k, v in self._series_buf.items()
                            if k < 0 and (buf["series_id"] == k).any()
                        }
                        for temp_id, meta in new_series.items():
                            rows = dbconnection.execute_and_fetchall(
                                f"INSERT INTO {series_tbl}"
                                f" ({ident('obsid')}, {ident('source')},"
                                f" {ident('instrument')},"
                                f" {ident('description')},"
                                f" {ident('comment')})"
                                f" VALUES ({ph}, {ph}, {ph}, {ph}, {ph})"
                                f" RETURNING {ident('id')}",
                                (
                                    meta["obsid"],
                                    meta["source"],
                                    meta.get("instrument"),
                                    meta.get("description"),
                                    meta.get("comment"),
                                ),
                            )
                            id_mapping[temp_id] = rows[0][0]

                        # 2. UPDATE existing series with changed metadata
                        for sid, meta in self._series_buf.items():
                            if sid < 0:
                                continue
                            orig = self._original_series_buf.get(sid)
                            if orig is None or meta == orig:
                                continue
                            dbconnection.execute(
                                f"UPDATE {series_tbl}"
                                f" SET {ident('source')} = {ph},"
                                f" {ident('instrument')} = {ph},"
                                f" {ident('description')} = {ph},"
                                f" {ident('comment')} = {ph}"
                                f" WHERE {ident('id')} = {ph}",
                                (
                                    meta["source"],
                                    meta.get("instrument"),
                                    meta.get("description"),
                                    meta.get("comment"),
                                    sid,
                                ),
                            )

                        # 3. UPDATE series_id on rows where it changed
                        common = original_buf.index.intersection(buf.index)
                        if len(common) > 0:
                            orig_sid = original_buf.loc[common, "series_id"]
                            new_sid = buf.loc[common, "series_id"]
                            sid_changed = (
                                ~(
                                    (orig_sid == new_sid)
                                    | (orig_sid.isna() & new_sid.isna())
                                )
                            ).fillna(True)
                            changed_idx = common[sid_changed]
                            if len(changed_idx) > 0:
                                sid_update_params = []
                                for dt_idx in changed_idx:
                                    raw_sid = buf.loc[dt_idx, "series_id"]
                                    if pd.notna(raw_sid):
                                        int_sid = int(raw_sid)
                                        resolved = id_mapping.get(int_sid, int_sid)
                                    else:
                                        resolved = None
                                    dt_str = dt_idx.strftime(_DT_FMT)
                                    sid_update_params.append((resolved, obsid, dt_str))
                                sid_update_sql = (
                                    f"UPDATE {logger_tbl}"
                                    f" SET {ident('series_id')} = {ph}"
                                    f" WHERE {ident('obsid')} = {ph}"
                                    f" AND {dt_eq}"
                                )
                                dbconnection.executemany(
                                    sid_update_sql, sid_update_params
                                )

                        # 4. DELETE orphaned series
                        for sid in list(self._original_series_buf.keys()):
                            if sid not in self._series_buf:
                                dbconnection.execute(
                                    f"DELETE FROM {series_tbl}"
                                    f" WHERE {ident('id')} = {ph}",
                                    (sid,),
                                )
                            elif sid >= 0:
                                remaining = dbconnection.execute_and_fetchall(
                                    f"SELECT COUNT(*) FROM {logger_tbl}"
                                    f" WHERE {ident('series_id')} = {ph}",
                                    (sid,),
                                )
                                if remaining[0][0] == 0:
                                    dbconnection.execute(
                                        f"DELETE FROM {series_tbl}"
                                        f" WHERE {ident('id')} = {ph}",
                                        (sid,),
                                    )
            finally:
                dbconnection.closedb()
        except Exception as e:
            message_utils.MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "LoggerEditor",
                    "Save failed while writing; the transaction was rolled back.",
                ),
                log_msg=f"{e}\n{traceback.format_exc()}",
            )
            return False
        finally:
            common_utils.stop_waiting_cursor()

        # Remap temporary series IDs to real DB IDs after successful save
        if id_mapping:
            for temp_id, real_id in id_mapping.items():
                self._buf.loc[self._buf["series_id"] == temp_id, "series_id"] = real_id
                if temp_id in self._series_buf:
                    self._series_buf[real_id] = self._series_buf.pop(temp_id)
            # Back-patch all history snapshots so undo does not restore stale temp IDs
            for entry in self._history:
                sid_col = entry["series_id"]
                for temp_id, real_id in id_mapping.items():
                    sid_col[sid_col == temp_id] = real_id
                sb = entry["series_buf"]
                for temp_id, real_id in id_mapping.items():
                    if temp_id in sb:
                        sb[real_id] = sb.pop(temp_id)

        # Deliberately on self._buf, not the deduped local `buf`: the real
        # buffer keeps any twin rows (they were only excluded from the write).
        self._original_buf = self._buf.copy()
        self._original_series_buf = {k: dict(v) for k, v in self._series_buf.items()}
        self._last_saved_history_pos = self._history_pos
        self._dirty = False
        self._ref_subplot_dirty = True
        self._refresh_window_title()
        self._refresh_history_widget()
        return True

    def _compute_update_statements(
        self,
        buf: pd.DataFrame,
        changed_index: pd.DatetimeIndex,
        orig_changed: pd.Series,
        new_changed: pd.Series,
        head_changed: pd.Series,
        obsid: str,
        tbl: str,
        ph: str,
        is_sqlite: bool,
        force_per_row: bool = False,
    ) -> tuple[list[tuple], list[tuple]]:
        """Group changed rows by contiguous buf-position; emit range or per-row SQL.

        Returns (range_stmts, per_row_params):
          range_stmts  — list of (sql, params_tuple), executed with execute()
          per_row_params — list of (new_val, obsid, dt_str), executed with executemany()

        Contiguous groups of changed rows that match a known pattern (set logger
        position, add offset, set to NULL) are folded into a single range-based
        UPDATE statement.  Groups that don't match — e.g. trend adjustments — fall
        back to one row per statement via executemany.

        When ``force_per_row`` is True (duplicate instants present and dropped
        from ``buf``), range merging is disabled: a BETWEEN range derived from
        the deduped buffer could span a skipped twin's instant in the DB.
        Per-row statements target exact instants and never touch a twin.
        Note this disables range merging for ALL rows in the save, not just
        those adjacent to a twin; Plan 2 (duplicate-resolve UI) should remove
        the flag entirely once twins can no longer reach save.
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
            dt_between = (
                f"{dt_col}::timestamp BETWEEN {ph}::timestamp AND {ph}::timestamp"
            )
        where_range = f"{obsid_col} = {ph} AND {dt_between}"

        # A BETWEEN range-query only touches the intended rows when there are no
        # unchanged rows between t1 and t2 in the buffer — split on gaps to enforce this.
        buf_pos = buf.index.get_indexer(changed_index)
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

            if force_per_row:
                # Duplicate instants dropped from buf — a BETWEEN range could
                # span a skipped twin. Emit exact per-row updates only.
                per_row_params.extend(
                    zip(
                        grp_new.to_numpy(dtype=object, na_value=None),
                        itertools.repeat(obsid, len(grp_idx)),
                        dt_strs,
                    )
                )
                continue

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
        self._close_resolve_dialog()
        if not self._dirty:
            self._prev_combobox_index = new_index
            self.update_plot()
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
        self.update_plot()

    def _discard_buf(self) -> None:
        self._buf = None
        self._original_buf = None
        self._dirty = False
        self._buf_obsid = None
        self._series_buf = {}
        self._original_series_buf = {}
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
            "present_raw": self._buf["date_time_raw"].tolist(),
            "series_id": self._buf["series_id"].copy(),
            "series_buf": {k: dict(v) for k, v in self._series_buf.items()},
            "source": (
                self._buf["source"].copy() if "source" in self._buf.columns else None
            ),
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
        # Select snapshot rows from _original_buf by unique raw date_time text
        # (not the datetime index, which is non-unique when twins are present),
        # then restore the original datetime index.
        ob_by_raw = self._original_buf.set_index("date_time_raw", drop=False)
        self._buf = ob_by_raw.loc[entry["present_raw"]].copy()
        self._buf.index = entry["present_index"]
        self._buf["level_masl"] = entry["level_masl"].to_numpy()
        # Overlay positionally (numpy) to avoid index-alignment on duplicate
        # labels, but keep series_id's nullable-Int64 dtype.
        self._buf["series_id"] = pd.array(entry["series_id"].to_numpy(), dtype="Int64")
        if entry.get("source") is not None and "source" in self._buf.columns:
            self._buf["source"] = entry["source"].to_numpy()
        self._series_buf = {k: dict(v) for k, v in entry["series_buf"].items()}
        if hasattr(self, "_series_last_shown_id"):
            self._series_last_shown_id = None
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

    # ------------------------------------------------------------------
    # Series tab
    # ------------------------------------------------------------------

    def _build_series_tab(self) -> QWidget:
        """Create and return the Series tab widget for managing logger series."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # --- Selection summary ---
        self._series_summary_label = QLabel(
            QCoreApplication.translate("LoggerEditor", "No points selected")
        )
        self._series_summary_label.setWordWrap(True)
        layout.addWidget(self._series_summary_label)

        # --- Form fields ---
        form_group = QGroupBox(
            QCoreApplication.translate("LoggerEditor", "Series metadata")
        )
        form_layout = QFormLayout(form_group)

        self._series_source_edit = QLineEdit()
        form_layout.addRow(
            QCoreApplication.translate("LoggerEditor", "Source:"),
            self._series_source_edit,
        )

        self._series_instrument_edit = QLineEdit()
        form_layout.addRow(
            QCoreApplication.translate("LoggerEditor", "Instrument:"),
            self._series_instrument_edit,
        )

        self._series_description_edit = QLineEdit()
        form_layout.addRow(
            QCoreApplication.translate("LoggerEditor", "Description:"),
            self._series_description_edit,
        )

        self._series_comment_edit = QTextEdit()
        self._series_comment_edit.setMaximumHeight(80)
        form_layout.addRow(
            QCoreApplication.translate("LoggerEditor", "Comment:"),
            self._series_comment_edit,
        )

        layout.addWidget(form_group)

        # --- Action buttons ---
        action_group = QGroupBox(QCoreApplication.translate("LoggerEditor", "Actions"))
        action_layout = QVBoxLayout(action_group)

        self._series_create_btn = QPushButton(
            QCoreApplication.translate("LoggerEditor", "Create new series")
        )
        self._series_create_btn.clicked.connect(self._on_series_create)
        action_layout.addWidget(self._series_create_btn)

        assign_row = QHBoxLayout()
        self._series_assign_combo = QComboBox()
        self._series_assign_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        assign_row.addWidget(self._series_assign_combo, 1)
        self._series_assign_btn = QPushButton(
            QCoreApplication.translate("LoggerEditor", "Assign to existing")
        )
        self._series_assign_btn.clicked.connect(self._on_series_assign)
        assign_row.addWidget(self._series_assign_btn)
        action_layout.addLayout(assign_row)

        self._series_edit_btn = QPushButton(
            QCoreApplication.translate("LoggerEditor", "Apply changes")
        )
        self._series_edit_btn.clicked.connect(self._on_series_edit)
        action_layout.addWidget(self._series_edit_btn)

        layout.addWidget(action_group)

        # --- Info label ---
        self._series_info_label = QLabel()
        self._series_info_label.setWordWrap(True)
        self._series_info_label.setVisible(False)
        layout.addWidget(self._series_info_label)

        layout.addStretch()

        # Track the last-shown series id to avoid clobbering user edits
        self._series_last_shown_id: int | None = None

        # Debounce timer for series tab refresh during rapid date edits
        self._series_tab_timer = QTimer(self)
        self._series_tab_timer.setSingleShot(True)
        self._series_tab_timer.setInterval(500)
        self._series_tab_timer.timeout.connect(self._update_series_tab)

        # Initial disabled state
        self._series_create_btn.setEnabled(False)
        self._series_assign_btn.setEnabled(False)
        self._series_edit_btn.setEnabled(False)

        return tab

    def _on_tab_changed(self, index: int) -> None:
        if self.tab_widget.widget(index) is self._series_tab:
            self._update_series_tab()

    def _update_series_tab(self) -> None:
        """Update the series tab to reflect the current selection state."""
        if self._buf is None or not hasattr(self, "_series_summary_label"):
            return

        fr_d_t = self.from_date_time.dateTime().toPyDateTime().replace(tzinfo=None)
        to_d_t = self.to_date_time.dateTime().toPyDateTime().replace(tzinfo=None)
        mask = self._build_edit_mask(fr_d_t, to_d_t)
        n_selected = int(mask.sum())

        if n_selected == 0:
            self._series_summary_label.setText(
                QCoreApplication.translate("LoggerEditor", "No points selected")
            )
            self._series_create_btn.setEnabled(False)
            self._series_assign_btn.setEnabled(False)
            self._series_edit_btn.setEnabled(False)
            self._series_info_label.setVisible(False)
            return

        # Gather unique series_id values from selected rows
        selected_sids = self._buf.loc[mask, "series_id"]
        unique_sids = selected_sids.dropna().unique().tolist()
        n_unassigned = int(selected_sids.isna().sum())

        # Build summary text
        parts = []
        for sid in sorted(unique_sids):
            sid_int = int(sid)
            count = int((selected_sids == sid).sum())
            meta = self._series_buf.get(sid_int, {})
            src_label = meta.get("source") or QCoreApplication.translate(
                "LoggerEditor", "(unnamed)"
            )
            parts.append(f"{count} from '{src_label}' (id={sid_int})")
        if n_unassigned > 0:
            parts.append(
                f"{n_unassigned} "
                + QCoreApplication.translate("LoggerEditor", "unassigned")
            )
        summary = QCoreApplication.translate(
            "LoggerEditor", "Selected %d points: %s"
        ) % (n_selected, ", ".join(parts))
        self._series_summary_label.setText(summary)

        # Populate assign combo with existing series for this obsid
        self._series_assign_combo.clear()
        for sid, meta in sorted(self._series_buf.items()):
            label = (
                f"{meta.get('source') or QCoreApplication.translate('LoggerEditor', '(unnamed)')}"
                f" (id={sid})"
            )
            self._series_assign_combo.addItem(label, sid)

        # Determine mode
        has_single_sid = len(unique_sids) == 1 and n_unassigned == 0
        all_null = len(unique_sids) == 0 and n_unassigned > 0
        has_assignable = self._series_assign_combo.count() > 0

        if has_single_sid:
            sid_int = int(unique_sids[0])
            # Check if the selection covers ALL points with this series_id
            all_with_sid = self._buf["series_id"] == sid_int
            covers_all = all_with_sid.sum() == n_selected

            if covers_all:
                # EDIT mode — pre-fill form only if the series changed
                self._series_create_btn.setEnabled(True)
                self._series_assign_btn.setEnabled(has_assignable)
                self._series_edit_btn.setEnabled(True)
                self._series_info_label.setVisible(False)
                if self._series_last_shown_id != sid_int:
                    self._series_last_shown_id = sid_int
                    meta = self._series_buf.get(sid_int, {})
                    self._series_source_edit.setText(meta.get("source") or "")
                    self._series_instrument_edit.setText(meta.get("instrument") or "")
                    self._series_description_edit.setText(meta.get("description") or "")
                    self._series_comment_edit.setPlainText(meta.get("comment") or "")
            else:
                # Sub-range of one series — CREATE/ASSIGN only
                self._series_create_btn.setEnabled(True)
                self._series_assign_btn.setEnabled(has_assignable)
                self._series_edit_btn.setEnabled(False)
                self._series_info_label.setText(
                    QCoreApplication.translate(
                        "LoggerEditor",
                        "To edit series metadata, select the entire series.",
                    )
                )
                self._series_info_label.setVisible(True)
                self._series_last_shown_id = None
        elif all_null:
            # All unassigned — CREATE mode
            self._series_create_btn.setEnabled(True)
            self._series_assign_btn.setEnabled(has_assignable)
            self._series_edit_btn.setEnabled(False)
            self._series_info_label.setVisible(False)
            self._series_last_shown_id = None
        else:
            # Mixed series — CREATE/ASSIGN
            self._series_create_btn.setEnabled(True)
            self._series_assign_btn.setEnabled(has_assignable)
            self._series_edit_btn.setEnabled(False)
            self._series_info_label.setVisible(False)
            self._series_last_shown_id = None

    def _on_series_create(self) -> None:
        """Create a new series from the form fields and assign selected points."""
        source = self._series_source_edit.text().strip()
        if not source:
            message_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "LoggerEditor", "Source is required to create a series."
                )
            )
            return

        if self._buf is None:
            return

        fr_d_t = self.from_date_time.dateTime().toPyDateTime().replace(tzinfo=None)
        to_d_t = self.to_date_time.dateTime().toPyDateTime().replace(tzinfo=None)
        mask = self._build_edit_mask(fr_d_t, to_d_t)
        count = int(mask.sum())
        if count == 0:
            return

        # Generate negative temporary id to avoid collision with real DB ids
        new_id = min(min(self._series_buf.keys(), default=0), 0) - 1

        self._series_buf[new_id] = {
            "obsid": self._buf_obsid,
            "source": source,
            "instrument": self._series_instrument_edit.text().strip() or None,
            "description": self._series_description_edit.text().strip() or None,
            "comment": self._series_comment_edit.toPlainText().strip() or None,
        }

        self._buf.loc[mask, "series_id"] = new_id
        if "source" in self._buf.columns:
            self._buf.loc[mask, "source"] = source

        self._recompute_line_keys()
        self._history_push(
            QCoreApplication.translate(
                "LoggerEditor", "Set series: '%s' (new, %d points)"
            )
            % (source, count)
        )
        self.update_plot()

    def _on_series_assign(self) -> None:
        """Assign selected points to an existing series."""
        sid = self._series_assign_combo.currentData()
        if sid is None or self._buf is None:
            return

        fr_d_t = self.from_date_time.dateTime().toPyDateTime().replace(tzinfo=None)
        to_d_t = self.to_date_time.dateTime().toPyDateTime().replace(tzinfo=None)
        mask = self._build_edit_mask(fr_d_t, to_d_t)
        count = int(mask.sum())
        if count == 0:
            return

        # Guard: skip if all selected rows already have this series_id
        current_sids = self._buf.loc[mask, "series_id"]
        if current_sids.notna().all() and (current_sids == sid).all():
            return

        self._buf.loc[mask, "series_id"] = sid
        meta = self._series_buf.get(sid, {})
        new_source = meta.get("source") or ""
        if "source" in self._buf.columns:
            self._buf.loc[mask, "source"] = new_source

        self._recompute_line_keys()
        src_label = meta.get("source") or QCoreApplication.translate(
            "LoggerEditor", "(unnamed)"
        )
        self._history_push(
            QCoreApplication.translate(
                "LoggerEditor", "Assign to series '%s' (id=%d, %d points)"
            )
            % (src_label, sid, count)
        )
        self.update_plot()

    def _on_series_edit(self) -> None:
        """Edit metadata for the single fully-selected series."""
        source = self._series_source_edit.text().strip()
        if not source:
            message_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "LoggerEditor", "Source is required."
                )
            )
            return

        if self._buf is None:
            return

        fr_d_t = self.from_date_time.dateTime().toPyDateTime().replace(tzinfo=None)
        to_d_t = self.to_date_time.dateTime().toPyDateTime().replace(tzinfo=None)
        mask = self._build_edit_mask(fr_d_t, to_d_t)
        if mask.sum() == 0:
            return

        # Get the single series_id from selected points
        selected_sids = self._buf.loc[mask, "series_id"].dropna().unique()
        if len(selected_sids) != 1:
            return
        sid = int(selected_sids[0])

        # Update series metadata
        self._series_buf[sid] = {
            "obsid": self._series_buf.get(sid, {}).get("obsid", self._buf_obsid),
            "source": source,
            "instrument": self._series_instrument_edit.text().strip() or None,
            "description": self._series_description_edit.text().strip() or None,
            "comment": self._series_comment_edit.toPlainText().strip() or None,
        }

        # Update source in _buf for ALL rows with this series_id, not just selected
        if "source" in self._buf.columns:
            self._buf.loc[self._buf["series_id"] == sid, "source"] = source

        self._recompute_line_keys()
        self._history_push(
            QCoreApplication.translate("LoggerEditor", "Edit series '%s' (id=%d)")
            % (source, sid)
        )
        self.update_plot()

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
            message_utils.MessagebarAndLog.warning(bar_msg="No data loaded")
            return
        mask = self._build_edit_mask(
            fr_d_t.replace(tzinfo=None),
            to_d_t.replace(tzinfo=None),
            value_col="level_masl",
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
            message_utils.MessagebarAndLog.warning(bar_msg="No data loaded")
            return
        mask = self._build_edit_mask(
            fr_d_t.replace(tzinfo=None),
            to_d_t.replace(tzinfo=None),
            value_col="head_cm_m",
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
        self._selected_line_keys = set()
        self._update_selection_button_state()
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

        self.period_selector.set_active(False)
        if self.move_nodes_button.button().isChecked():
            self.toggle_move_nodes(True)
        elif self.select_nodes_button.button().isChecked():
            self.toggle_select_nodes(True)
        elif (
            hasattr(self, "adjust_trend_button")
            and self.adjust_trend_button.button().isChecked()
        ):
            self.toggle_adjust_trend(True)

        self._draw_duplicate_marker()
        self._refresh_dupe_banner()

    def _refresh_dupe_banner(self) -> None:
        if not hasattr(self, "_dupe_banner"):
            return
        n = len(self._duplicate_instants())
        if n > 0:
            self._dupe_warning_label.setText(
                QCoreApplication.translate(
                    "LoggerEditor", "⚠ %s duplicate timestamp(s) for this obsid."
                )
                % n
            )
            self._dupe_banner.setVisible(True)
        else:
            self._dupe_banner.setVisible(False)

    def _draw_duplicate_marker(self) -> None:
        """Draw red segments along the axes bottom, one per duplicate run, so the
        user sees where duplicates remain. Recomputed on every redraw, so it
        shrinks as periods are resolved."""
        self._dupe_marker_artists = []
        if self._buf is None:
            return
        runs = self._duplicate_runs()
        if not runs:
            return
        trans = blended_transform_factory(self.axes.transData, self.axes.transAxes)
        for start, end in runs:
            (line,) = self.axes.plot(
                [date2num(start), date2num(end)],
                [0.02, 0.02],
                transform=trans,
                color="red",
                linewidth=3,
                marker="|",
                markersize=8,
                solid_capstyle="butt",
                clip_on=False,
                zorder=5,
            )
            self._dupe_marker_artists.append(line)
        # The markers are added after _finish_plot's canvas.draw(); repaint so
        # they appear immediately rather than at the next incidental paint event.
        self.canvas.draw_idle()

    def _open_resolve_dupes_dialog(self) -> None:
        if not self._duplicate_instants().size:
            return
        if self._resolve_dialog is not None:
            self._resolve_dialog.raise_()
            self._resolve_dialog.activateWindow()
            self._resolve_dialog._rebuild()
            return
        dlg = ResolveDuplicatesDialog(self)
        self._resolve_dialog = dlg
        dlg.finished.connect(lambda _result: self._on_resolve_dialog_closed())
        dlg.show()

    def _on_resolve_dialog_closed(self) -> None:
        self._resolve_dialog = None

    def _close_resolve_dialog(self) -> None:
        if self._resolve_dialog is not None:
            self._resolve_dialog.close()
            self._resolve_dialog = None

    def _fast_update_after_move(self):
        """Update artist y-data in place after a move offset — avoids full redraw."""
        buf = self._buf
        if buf is None or self.logger_artist is None:
            self.update_plot()
            return

        new_values = buf["level_masl"].to_numpy(dtype=float, na_value=np.nan)
        self.level_masl_ts.values[:] = new_values
        self._ts_version = self._buf_version

        self.logger_artist.set_ydata(new_values)

        line_keys = self.level_masl_ts.line_key
        n = len(new_values)
        key_to_indices: dict = {}
        for i, k in enumerate(line_keys):
            key_to_indices.setdefault(k, []).append(i)
        for key, artist in self._line_key_to_artist.items():
            masked = np.full(n, np.nan)
            indices = key_to_indices.get(key)
            if indices is not None:
                idx = np.asarray(indices)
                masked[idx] = new_values[idx]
            artist.set_ydata(masked)

        self.plot_or_update_selected_line()
        self.setlastcalibration(self.obsid)
        self.canvas.draw()
        self.statusbar.clearMessage()

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
                    linestyle="none",
                    picker=5,
                    marker=".",
                    markersize=0.01,
                    alpha=0,
                    zorder=10,
                ),
            )[0]

            unique_keys = sorted(
                dict.fromkeys(self.level_masl_ts.line_key),
                key=lambda k: (bool(k[0] and str(k[0]).strip()), k),
            )
            self._line_key_to_artist = {}
            if len(unique_keys) > 15:
                progress = qgis.PyQt.QtWidgets.QProgressDialog(
                    QCoreApplication.translate(
                        "Calibrlogger",
                        f"Drawing {len(unique_keys)} lines...",
                    ),
                    QCoreApplication.translate("Calibrlogger", "Abort"),
                    0,
                    len(unique_keys),
                    self,
                )
                progress.setWindowModality(Qt.WindowModal)
            else:
                progress = None
            for idx, key in enumerate(unique_keys):
                label = self._label_for_line_key(obsid, key)
                ts = self.level_masl_ts.copy()
                mask = np.array([k != key for k in ts.line_key])
                ts.values[mask] = np.nan
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
                a._line_key = key
                self.logger_plot_artists.append(a)
                self._line_key_to_artist[key] = a
                handles.append(a)
                labels.append(label)
                if progress is not None:
                    progress.setValue(idx + 1)
                    qgis.PyQt.QtWidgets.QApplication.processEvents()
                    if progress.wasCanceled():
                        break
            if progress is not None and progress.wasCanceled():
                if self.separate_created_at_cb.isChecked():
                    self.separate_created_at_cb.blockSignals(True)
                    self.separate_created_at_cb.setChecked(False)
                    self.separate_created_at_cb.blockSignals(False)
                elif self.separate_dt_precision_cb.isChecked():
                    self.separate_dt_precision_cb.blockSignals(True)
                    self.separate_dt_precision_cb.setChecked(False)
                    self.separate_dt_precision_cb.blockSignals(False)
                self._recompute_line_keys()
                for a in list(self.logger_plot_artists):
                    try:
                        a.remove()
                    except (ValueError, NotImplementedError):
                        pass
                self.logger_plot_artists.clear()
                self._line_key_to_artist.clear()
                handles.clear()
                labels.clear()
                return self._draw_series()

        else:
            self.logger_artist = None

        if (
            self.plot_logger_head.isChecked()
            and self.head_ts_for_plot.size
            and self.contains_more_than_nan(self.head_ts_for_plot)
        ):
            head_unique_keys = sorted(
                dict.fromkeys(self.head_ts_for_plot.line_key),
                key=lambda k: (bool(k[0] and str(k[0]).strip()), k),
            )
            for idx, key in enumerate(head_unique_keys):
                try:
                    color = logger_head_colors[idx]
                except IndexError:
                    color = np.random.rand(3, 1).ravel()

                label = self._label_for_head_key(obsid, key)
                ts = self.head_ts_for_plot.copy()
                mask = np.array([k != key for k in ts.line_key])
                ts.values[mask] = np.nan

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

        leg = self.axes.legend(handles, labels)
        if self._legend_picker is not None:
            self._legend_picker.disconnect()
        legend_lines = leg.get_lines()
        paired = [
            (ll, h)
            for ll, h in zip(legend_lines, handles)
            if isinstance(h, matplotlib.lines.Line2D) and hasattr(h, "_line_key")
        ]
        if paired:
            pick_legend, pick_handles = zip(*paired)
            self._legend_picker = LegendPicker(
                legend=leg,
                fig=self.calibrplotfigure,
                handles=list(pick_handles),
                legend_lines=list(pick_legend),
            )
            self._legend_picker.register_pick_callback(self._on_legend_pick)
        else:
            self._legend_picker = None

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

        options_separator = QFrame()
        options_separator.setFrameShape(QFrame.HLine)
        options_separator.setFrameShadow(QFrame.Sunken)
        vbox.addWidget(options_separator)
        options_label = QLabel(
            QCoreApplication.translate("Calibrlogger", "Plot options")
        )
        options_label.setFont(QFont("Noto Sans", 8))
        options_label.setStyleSheet("font-weight: bold; color: #555;")
        vbox.addWidget(options_label)
        vbox.addWidget(self.logger_line_nodes)
        vbox.addWidget(self.plot_logger_head)
        vbox.addWidget(self.normalize_head)
        vbox.addWidget(self.separate_source_cb)
        vbox.addWidget(self.separate_created_at_cb)
        vbox.addWidget(self.separate_dt_precision_cb)
        self._update_plot_btn = QPushButton(
            QCoreApplication.translate("Calibrlogger", "Update plot")
        )
        self._update_plot_btn.setFont(QFont("Noto Sans", 8))
        self._update_plot_btn.clicked.connect(lambda _: self.update_plot())
        vbox.addWidget(self._update_plot_btn)
        vbox.addStretch()

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
            # resample_agg is loaded from persisted settings (project file),
            # so it must be validated like any other external input.
            try:
                agg = defs.validate_resample_how(s.get("resample_agg"))
            except exceptions.UsageError as e:
                message_utils.MessagebarAndLog.critical(bar_msg=str(e))
                return
            df = getattr(df.resample(s["resample"]), agg)()
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
        """Convert date strings or datetimes to matplotlib date objects"""
        if timestring_list and isinstance(timestring_list[0], datetime.datetime):
            return num2date(date2num(timestring_list))
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

        self.to_date_time.setDateTime(to_date("2099-12-31 23:59:59"))
        self.offset.setText("")
        self.best_fit_search_radius.setText("60 minutes")

        last_calibration = self.getlastcalibration(self.obsid)
        try:
            if last_calibration and last_calibration[0][1] and last_calibration[0][0]:
                self.logger_elevation.setText(f"{last_calibration[0][1]:.5f}")
                self.from_date_time.setDateTime(
                    to_date(last_calibration[0][0]) + datetime.timedelta(milliseconds=1)
                )
            else:
                self.logger_elevation.setText("")
                self.from_date_time.setDateTime(to_date("2099-12-31 23:59:59"))
        except Exception as e:
            message_utils.MessagebarAndLog.info(
                log_msg=QCoreApplication.translate(
                    "Calibrlogger",
                    "Getting last calibration failed for obsid %s, msg: %s",
                )
                % (self.obsid, str(e))
            )
            self.logger_elevation.setText("")
            self.from_date_time.setDateTime(to_date("2099-12-31 23:59:59"))

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
            message_utils.pop_up_info(
                QCoreApplication.translate(
                    "Calibrlogger",
                    "There was no match found between measurements and logger values inside the chosen period.\n Try to increase the search radius or adjust the period!",
                )
            )
        else:
            calculated_diff = str(common_utils.calc_mean_diff(coupled_vals))
            if not calculated_diff or calculated_diff.lower() == "nan":
                message_utils.pop_up_info(
                    QCoreApplication.translate(
                        "Calibrlogger",
                        "There was no matched measurements or logger values inside the chosen period.\n Try to increase the search radius!",
                    )
                )
                message_utils.MessagebarAndLog.info(
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
        outer_begin = self.from_date_time.dateTime().toPyDateTime().replace(tzinfo=None)
        outer_end = self.to_date_time.dateTime().toPyDateTime().replace(tzinfo=None)
        logger_step = to_date(log_row[0])
        if logger_step is None:
            return None
        for m in meas_ts:
            meas_step = to_date(m[0])
            if meas_step is None or logger_step is None:
                continue

            step_begin = dateshift(meas_step, -search_radius, search_radius_period)
            step_end = dateshift(meas_step, search_radius, search_radius_period)
            if step_end < outer_begin:
                continue
            if step_begin > outer_end:
                break

            while logger_step <= step_begin or logger_step <= outer_begin:
                try:
                    log_row = next(logger_gen)
                except StopIteration:
                    all_done = True
                    break
                logger_step = to_date(log_row[0])

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
                logger_step = to_date(log_row[0])

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
            message_utils.pop_up_info(
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
            message_utils.MessagebarAndLog.warning(bar_msg="No data loaded")
            return

        current_loaded_obsid = self.obsid
        selected_obsid = self.selected_obsid
        if current_loaded_obsid != selected_obsid:
            message_utils.pop_up_info(
                QCoreApplication.translate(
                    "Calibrlogger",
                    "Error!\n The obsid selection has been changed but the plot has not been updated. No deletion done.\nUpdating plot.",
                )
            )
            self.update_plot()
            return
        elif selected_obsid is None:
            message_utils.pop_up_info(
                QCoreApplication.translate(
                    "Calibrlogger",
                    "Error!\n No obsid was selected. No deletion done.\nUpdating plot.",
                )
            )
            self.update_plot()
            return

        fr_d_t = self.from_date_time.dateTime().toPyDateTime().replace(tzinfo=None)
        to_d_t = self.to_date_time.dateTime().toPyDateTime().replace(tzinfo=None)

        selection_note = ""
        if self.selected_line_keys:
            selection_note = "\n" + QCoreApplication.translate(
                "Calibrlogger",
                "(Only selected series will be affected.)",
            )
        if set_to_null_instead:
            msg = (
                QCoreApplication.translate(
                    "Calibrlogger",
                    "Do you want to set level_masl to NULL for the period %s to %s for obsid %s in table %s?",
                )
                % (
                    str(self.from_date_time.dateTime().toPyDateTime()),
                    str(self.to_date_time.dateTime().toPyDateTime()),
                    selected_obsid,
                    table_name,
                )
                + selection_note
            )
        else:
            msg = (
                QCoreApplication.translate(
                    "Calibrlogger",
                    "Do you want to delete the period %s to %s for obsid %s from table %s?",
                )
                % (
                    str(self.from_date_time.dateTime().toPyDateTime()),
                    str(self.to_date_time.dateTime().toPyDateTime()),
                    selected_obsid,
                    table_name,
                )
                + selection_note
            )

        really_delete = dialog_utils.Askuser("YesNo", msg).result
        if really_delete:
            common_utils.start_waiting_cursor()
            mask = self._build_edit_mask(fr_d_t, to_d_t)
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
        if self._buf is None or self._buf.empty:
            return
        fr_d_t = self.from_date_time.dateTime().toPyDateTime().replace(tzinfo=None)
        to_d_t = self.to_date_time.dateTime().toPyDateTime().replace(tzinfo=None)

        yf = np.asarray(self.logger_artist.get_ydata(), dtype=float)
        if len(self._buf) == len(yf):
            show = np.asarray(self._build_edit_mask(fr_d_t, to_d_t), dtype=bool)
        else:
            xf = date2num(self.logger_artist.get_xdata())
            fr_num = date2num(fr_d_t)
            to_num = date2num(to_d_t)
            show = (xf >= fr_num) & (xf <= to_num)
        ydata = np.where(show, yf, np.nan)

        if self.selected_line is None:
            xdata = self.logger_artist.get_xdata()
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
        if (
            hasattr(self, "_series_tab")
            and self.tab_widget.currentWidget() is self._series_tab
        ):
            self._series_tab_timer.start()

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
            if event.ydata is None:
                return
            ydata = self.selected_line.get_ydata()
            ref = float(ydata[self.moving_idx])
            if np.isnan(ref):
                return
            self.selected_line.set_ydata(ydata + (event.ydata - ref))
            self.canvas.draw_idle()

    def node_released(self, event=None):
        if self.moving_idx is not None:
            logger_y = self.logger_artist.get_ydata()[self.moving_idx]
            selected_y = self.selected_line.get_ydata()[self.moving_idx]
            if (
                logger_y is not None
                and selected_y is not None
                and not np.isnan(float(logger_y))
                and not np.isnan(float(selected_y))
            ):
                offset = (
                    self.selected_line.get_ydata()[self.moving_idx]
                    - self.logger_artist.get_ydata()[self.moving_idx]
                )
                self.moving_idx = None
                if offset:
                    self.offset.setText(f"{offset:.5f}")
                    self.loggerpos_masl_or_offset_state = 0
                    obsid = self._obsid_ensure_buf_current()
                    self.calibrate(obsid)
                    self._fast_update_after_move()
            self.moving_idx = None

    def line_select_callback(self, eclick, erelease):
        xdata = self.logger_artist.get_xdata()
        xf = date2num(xdata)
        yf = np.asarray(self.logger_artist.get_ydata(), dtype=float)
        x_lo, x_hi = sorted((eclick.xdata, erelease.xdata))
        y_lo, y_hi = sorted((eclick.ydata, erelease.ydata))
        mask = (xf >= x_lo) & (xf <= x_hi) & (yf >= y_lo) & (yf <= y_hi)
        if mask.any():
            sel_x = xf[mask]
            self.from_date_time.blockSignals(True)
            self.from_date_time.setDateTime(num2date(sel_x.min()))
            self.from_date_time.blockSignals(False)
            self.to_date_time.setDateTime(num2date(sel_x.max()))

    def toggle_move_nodes(self, on):
        if on:
            self.reset_cid()
            self.deactivate_pan_zoom()
            self.period_selector.set_active(False)
            self.select_nodes_button.uncheck()
            self.adjust_trend_button.uncheck()
            self._remove_trend_overlay()
            if self._legend_picker is not None:
                self._legend_picker.disconnect()
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

        mask = self._build_edit_mask(fr_d_t, to_d_t, value_col="level_masl")
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

        mask = self._build_edit_mask(fr_d_t, to_d_t, value_col="level_masl")
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
            message_utils.MessagebarAndLog.info(
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
                    os.path.dirname(__file__), "..", "icons", "svg", "adjust_trend.svg"
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
