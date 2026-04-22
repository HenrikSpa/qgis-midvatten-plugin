"""Reference series configuration dialog for the logger editor."""

import logging

from qgis.PyQt.QtCore import QCoreApplication, QDate
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from midvatten.tools.utils.db_utils.dialect import ident
from midvatten.tools.utils.db_utils.execution import use_or_create_connection
from midvatten.tools.utils.db_utils.helpers import nonplot_tables
from midvatten.tools.utils.db_utils.schema import get_table_info, get_tables

log = logging.getLogger(__name__)

_STYLES = ["line", "marker", "line+marker", "step-pre", "step-post"]
_AGG_FUNCS = ["sum", "mean", "max", "min"]
_NORM_MODES = ["", "date", "mean", "zscore"]


def _tr(text: str) -> str:
    return QCoreApplication.translate("RefSeries", text)


class _FilterRow(QWidget):
    def __init__(self, table: str, parent_dialog: "RefSeriesDialog"):
        super().__init__()
        self._parent = parent_dialog

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.col_combo = QComboBox()
        self.col_combo.setMinimumWidth(110)
        layout.addWidget(self.col_combo)

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(2)

        self.values_list = QListWidget()
        self.values_list.setSelectionMode(QAbstractItemView.MultiSelection)
        right_layout.addWidget(self.values_list)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(_tr("Filter..."))
        self.search_edit.textChanged.connect(self._filter_list)
        right_layout.addWidget(self.search_edit)
        layout.addWidget(right_widget)

        remove_btn = QPushButton("✕")
        remove_btn.setMaximumWidth(28)
        remove_btn.setToolTip(_tr("Remove filter"))
        remove_btn.clicked.connect(lambda: parent_dialog._remove_filter_row(self))
        layout.addWidget(remove_btn)

        self._populate_columns(table)
        self.col_combo.currentTextChanged.connect(self._on_col_changed)

    def _populate_columns(self, table: str, col_info=None) -> None:
        prev = self.col_combo.currentText()
        self.col_combo.blockSignals(True)
        self.col_combo.clear()
        if table:
            if col_info is None:
                with use_or_create_connection(None) as conn:
                    col_info = get_table_info(table, dbconnection=conn)
            if col_info:
                for row in col_info:
                    self.col_combo.addItem(row[1])
        self.col_combo.blockSignals(False)
        idx = self.col_combo.findText(prev)
        self.col_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._on_col_changed(self.col_combo.currentText())

    def _on_col_changed(self, col: str) -> None:
        self.values_list.clear()
        self.search_edit.clear()
        table = self._parent.current_table()
        if not col or not table:
            return
        with use_or_create_connection(None) as conn:
            try:
                rows = conn.execute_and_fetchall(
                    f"SELECT DISTINCT {ident(col)} FROM {ident(table)} ORDER BY 1"
                )
                for (val,) in rows:
                    if val is not None:
                        self.values_list.addItem(str(val))
            except Exception:
                log.debug("Failed to load distinct values for %s.%s", table, col)

    def _filter_list(self, text: str) -> None:
        lo = text.lower()
        for i in range(self.values_list.count()):
            item = self.values_list.item(i)
            item.setHidden(lo not in item.text().lower())

    def set_col(self, col: str) -> None:
        idx = self.col_combo.findText(col)
        if idx >= 0:
            self.col_combo.setCurrentIndex(idx)

    def set_selected_values(self, values: list) -> None:
        value_set = set(values)
        for i in range(self.values_list.count()):
            item = self.values_list.item(i)
            item.setSelected(item.text() in value_set)

    def to_filter_dict(self) -> dict:
        selected = []
        for i in range(self.values_list.count()):
            item = self.values_list.item(i)
            if item.isSelected():
                selected.append(item.text())
        return {"col": self.col_combo.currentText(), "values": selected}


class RefSeriesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_tr("Reference series configuration"))
        self.setMinimumWidth(500)
        self._filter_rows: list[_FilterRow] = []

        main_layout = QVBoxLayout(self)

        top_form = QFormLayout()
        top_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.table_combo = QComboBox()
        self._populate_tables()
        self.table_combo.currentTextChanged.connect(self._on_table_changed)
        top_form.addRow(_tr("Table:"), self.table_combo)

        self.ycol_combo = QComboBox()
        top_form.addRow(_tr("Y-column:"), self.ycol_combo)
        main_layout.addLayout(top_form)

        main_layout.addWidget(QLabel(_tr("Filters:")))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(60)
        scroll.setMaximumHeight(320)
        scroll.setSizeAdjustPolicy(QScrollArea.AdjustToContents)
        self._filters_widget = QWidget()
        self._filters_layout = QVBoxLayout(self._filters_widget)
        self._filters_layout.setSpacing(4)
        self._filters_layout.setContentsMargins(2, 2, 2, 2)
        self._filters_layout.addStretch()
        scroll.setWidget(self._filters_widget)
        main_layout.addWidget(scroll)

        add_filter_btn = QPushButton(_tr("+ Add filter"))
        add_filter_btn.clicked.connect(self._add_filter_row)
        main_layout.addWidget(add_filter_btn)

        resample_form = QFormLayout()
        resample_hl = QHBoxLayout()
        resample_hl.setContentsMargins(0, 0, 0, 0)
        self.resample_edit = QLineEdit()
        self.resample_edit.setPlaceholderText("e.g. 1D, 1h")
        self.resample_edit.setMaximumWidth(80)
        self.agg_combo = QComboBox()
        for a in _AGG_FUNCS:
            self.agg_combo.addItem(a)
        resample_hl.addWidget(self.resample_edit)
        resample_hl.addWidget(self.agg_combo)
        resample_hl.addStretch()
        resample_form.addRow(_tr("Resample:"), resample_hl)
        main_layout.addLayout(resample_form)

        self.interpolate_cb = QCheckBox(_tr("Interpolate after resample"))
        main_layout.addWidget(self.interpolate_cb)

        norm_form = QFormLayout()
        norm_hl = QHBoxLayout()
        norm_hl.setContentsMargins(0, 0, 0, 0)
        self.norm_combo = QComboBox()
        for label in [_tr("None"), _tr("To date"), _tr("Zero mean"), _tr("Z-score")]:
            self.norm_combo.addItem(label)
        self.norm_date_edit = QDateEdit()
        self.norm_date_edit.setCalendarPopup(True)
        self.norm_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.norm_date_edit.setDate(QDate.currentDate())
        self.norm_date_edit.setVisible(False)
        self.norm_combo.currentIndexChanged.connect(self._on_norm_changed)
        norm_hl.addWidget(self.norm_combo)
        norm_hl.addWidget(self.norm_date_edit)
        norm_hl.addStretch()
        norm_form.addRow(_tr("Normalize:"), norm_hl)
        main_layout.addLayout(norm_form)

        bottom_form = QFormLayout()

        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.001, 100000)
        self.scale_spin.setValue(1.0)
        self.scale_spin.setSingleStep(0.1)
        self.scale_spin.setDecimals(4)
        bottom_form.addRow(_tr("Scale:"), self.scale_spin)

        self.style_combo = QComboBox()
        for s in _STYLES:
            self.style_combo.addItem(s)
        bottom_form.addRow(_tr("Style:"), self.style_combo)

        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText(_tr("auto"))
        bottom_form.addRow(_tr("Label:"), self.label_edit)
        main_layout.addLayout(bottom_form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

        if self.table_combo.count() > 0:
            self._on_table_changed(self.table_combo.currentText())

    def _populate_tables(self) -> None:
        self.table_combo.blockSignals(True)
        self.table_combo.clear()
        try:
            excluded = set(nonplot_tables(as_tuple=True))
            for t in get_tables():
                if t not in excluded and not t.startswith("zz_"):
                    self.table_combo.addItem(t)
        except Exception:
            log.debug("Failed to load table list")
        self.table_combo.blockSignals(False)

    def _on_table_changed(self, table: str) -> None:
        self.ycol_combo.clear()
        if not table:
            return
        with use_or_create_connection(None) as conn:
            info = get_table_info(table, dbconnection=conn)
        if info:
            first_numeric = None
            for i, row in enumerate(info):
                self.ycol_combo.addItem(row[1])
                if first_numeric is None:
                    col_type = (row[2] or "").lower()
                    if any(t in col_type for t in ("real", "double", "float", "int")):
                        first_numeric = i
            if first_numeric is not None:
                self.ycol_combo.setCurrentIndex(first_numeric)
        for frow in self._filter_rows:
            frow._populate_columns(table, col_info=info)

    def _on_norm_changed(self, idx: int) -> None:
        self.norm_date_edit.setVisible(_NORM_MODES[idx] == "date")

    def current_table(self) -> str:
        return self.table_combo.currentText()

    def _add_filter_row(self) -> None:
        row = _FilterRow(self.current_table(), self)
        self._filter_rows.append(row)
        self._filters_layout.insertWidget(self._filters_layout.count() - 1, row)
        if self.isVisible():
            self.adjustSize()

    def _remove_filter_row(self, row: "_FilterRow") -> None:
        self._filters_layout.removeWidget(row)
        self._filter_rows.remove(row)
        row.deleteLater()
        if self.isVisible():
            self.adjustSize()

    def to_dict(self) -> dict:
        norm_idx = self.norm_combo.currentIndex()
        return {
            "table": self.table_combo.currentText(),
            "x_col": "date_time",
            "y_col": self.ycol_combo.currentText(),
            "filters": [r.to_filter_dict() for r in self._filter_rows],
            "resample": self.resample_edit.text().strip(),
            "resample_agg": self.agg_combo.currentText(),
            "interpolate": self.interpolate_cb.isChecked(),
            "normalize": _NORM_MODES[norm_idx],
            "normalize_date": self.norm_date_edit.date().toString("yyyy-MM-dd"),
            "scale": self.scale_spin.value(),
            "style": self.style_combo.currentText(),
            "label": self.label_edit.text().strip(),
        }

    @classmethod
    def from_dict(cls, d: dict, parent=None) -> "RefSeriesDialog":
        dlg = cls(parent=parent)
        idx = dlg.table_combo.findText(d.get("table", ""))
        if idx >= 0:
            dlg.table_combo.setCurrentIndex(idx)
        idx = dlg.ycol_combo.findText(d.get("y_col", ""))
        if idx >= 0:
            dlg.ycol_combo.setCurrentIndex(idx)
        for f in d.get("filters", []):
            dlg._add_filter_row()
            frow = dlg._filter_rows[-1]
            frow.set_col(f["col"])
            frow.set_selected_values(f.get("values", []))
        dlg.resample_edit.setText(d.get("resample", ""))
        agg_idx = dlg.agg_combo.findText(d.get("resample_agg", "sum"))
        if agg_idx >= 0:
            dlg.agg_combo.setCurrentIndex(agg_idx)
        dlg.interpolate_cb.setChecked(d.get("interpolate", False))
        norm = d.get("normalize", "")
        if norm in _NORM_MODES:
            dlg.norm_combo.setCurrentIndex(_NORM_MODES.index(norm))
        norm_date = d.get("normalize_date", "")
        if norm_date:
            dlg.norm_date_edit.setDate(QDate.fromString(norm_date, "yyyy-MM-dd"))
        dlg.scale_spin.setValue(d.get("scale", 1.0))
        style_idx = dlg.style_combo.findText(d.get("style", "line"))
        if style_idx >= 0:
            dlg.style_combo.setCurrentIndex(style_idx)
        dlg.label_edit.setText(d.get("label", ""))
        return dlg
