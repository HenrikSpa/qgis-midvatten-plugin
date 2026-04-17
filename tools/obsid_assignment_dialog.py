"""Bulk obsid assignment editor for Interlab4 (and reusable elsewhere).

Pure-Python support code (EditorRow, group_editor_rows) lives near the top;
the QDialog subclass follows below.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from qgis.PyQt.QtCore import Qt, QCoreApplication
from qgis.PyQt.QtGui import QBrush, QColor
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


@dataclass
class EditorRow:
    """One row in the ObsidAssignmentDialog table.

    Clean rows (no override text) represent a set of lablitteras sharing the
    same (spec_provplats, provplatsnamn). Override rows represent a single
    lablittera with hand-written override text that must be judged per sample.
    """

    specifik_provplats: str
    provplatsnamn: str
    provtagningsorsak: str
    lablitteras: list[str] = field(default_factory=list)
    obsid: str = ""
    cached: bool = False
    is_override: bool = False
    skipped: bool = False


def _has_override(row: dict) -> bool:
    """True when provtagningsorsak contains a hand-written override note.

    Uses the same sanitisation as the existing import_interlab4.py:
    "-" or "0" placeholders mean "no reason" and strip to empty.
    """
    value = (row.get("provtagningsorsak", "") or "").strip()
    value = value.replace("-", "").replace("0", "").strip()
    return bool(value)


def group_editor_rows(
    rows: list[dict],
    cache_matches: dict[tuple[str, str], str] | None = None,
) -> list[EditorRow]:
    """Group raw per-lablittera metadata into EditorRow instances.

    `rows` is a list of dicts with lowercase header keys (lablittera,
    specifik provplats, provplatsnamn, provtagningsorsak?).
    `cache_matches` maps (spec_provplats, provplatsnamn) -> obsid from
    zz_interlab4_obsid_assignment.

    Rows with a non-empty provtagningsorsak (after sanitising "-"/"0"
    placeholders) are treated as override rows and are not deduped.
    """
    cache_matches = cache_matches or {}
    clean_groups: dict[tuple[str, str], EditorRow] = {}
    override_rows: list[EditorRow] = []

    for row in rows:
        spec = row.get("specifik provplats", "") or ""
        namn = row.get("provplatsnamn", "") or ""
        orsak = row.get("provtagningsorsak", "") or ""
        lablittera = row.get("lablittera", "") or ""
        is_override = _has_override(row)

        if is_override:
            override_rows.append(
                EditorRow(
                    specifik_provplats=spec,
                    provplatsnamn=namn,
                    provtagningsorsak=orsak,
                    lablitteras=[lablittera],
                    is_override=True,
                )
            )
        else:
            key = (spec, namn)
            existing = clean_groups.get(key)
            if existing is None:
                cached_obsid = cache_matches.get(key, "")
                clean_groups[key] = EditorRow(
                    specifik_provplats=spec,
                    provplatsnamn=namn,
                    provtagningsorsak=orsak,
                    lablitteras=[lablittera],
                    obsid=cached_obsid,
                    cached=bool(cached_obsid),
                    is_override=False,
                )
            else:
                existing.lablitteras.append(lablittera)

    return list(clean_groups.values()) + override_rows


def _tr(text: str) -> str:
    return QCoreApplication.translate("Interlab4ObsidDialog", text)


_COL_SPEC = 0
_COL_NAMN = 1
_COL_ORSAK = 2
_COL_NLAB = 3
_COL_OBSID = 4
_COLUMN_HEADERS = (
    "specifik provplats",
    "provplatsnamn",
    "provtagningsorsak",
    "#lablitteras",
    "obsid",
)

_INVALID_BRUSH = QBrush(QColor(255, 200, 200))
_DEFAULT_BRUSH = QBrush(Qt.white)


class _ObsidDelegate(QStyledItemDelegate):
    def __init__(self, existing_obsids: list[str], parent=None):
        super().__init__(parent)
        self._existing_obsids = list(existing_obsids)

    def set_existing_obsids(self, obsids: list[str]):
        self._existing_obsids = list(obsids)

    def createEditor(self, parent, option, index):  # noqa: N802
        editor = QLineEdit(parent)
        completer = QCompleter(self._existing_obsids, editor)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        editor.setCompleter(completer)
        return editor


class ObsidAssignmentDialog(QDialog):
    """Bulk obsid-assignment editor. Reusable; no Interlab4-specific imports."""

    def __init__(
        self,
        editor_rows: list[EditorRow],
        existing_obsids: list[str],
        reload_callback=None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(_tr("Assign obsids"))
        self.editor_rows = list(editor_rows)
        self.existing_obsids = list(existing_obsids)
        self._reload_callback = reload_callback
        self._build_ui()
        self._populate_table()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, len(_COLUMN_HEADERS), self)
        self.table.setHorizontalHeaderLabels([_tr(h) for h in _COLUMN_HEADERS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel(_tr("Search:")))
        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText(_tr("filter any column..."))
        self.search_input.textChanged.connect(self._apply_filters)
        search_row.addWidget(self.search_input)
        self.row_count_label = QLabel("0 / 0", self)
        search_row.addWidget(self.row_count_label)
        self.show_matched_checkbox = QCheckBox(_tr("Show matched rows"), self)
        self.show_matched_checkbox.setChecked(False)
        self.show_matched_checkbox.toggled.connect(self._apply_filters)
        search_row.addWidget(self.show_matched_checkbox)
        layout.addLayout(search_row)
        bulk_row = QHBoxLayout()
        bulk_row.addWidget(QLabel(_tr("Fill with:")))
        self.fill_combo = QComboBox(self)
        self.fill_combo.setEditable(True)
        self.fill_combo.addItems(self.existing_obsids)
        fill_completer = QCompleter(self.existing_obsids, self.fill_combo)
        fill_completer.setCaseSensitivity(Qt.CaseInsensitive)
        fill_completer.setFilterMode(Qt.MatchContains)
        self.fill_combo.setCompleter(fill_completer)
        bulk_row.addWidget(self.fill_combo)
        self.fill_selection_button = QPushButton(_tr("Fill selection"), self)
        self.fill_selection_button.clicked.connect(self._fill_selection)
        bulk_row.addWidget(self.fill_selection_button)
        self.skip_selection_button = QPushButton(_tr("Skip selection"), self)
        self.skip_selection_button.clicked.connect(
            lambda: self._set_skipped_for_selection(True)
        )
        bulk_row.addWidget(self.skip_selection_button)
        self.unskip_selection_button = QPushButton(_tr("Unskip selection"), self)
        self.unskip_selection_button.clicked.connect(
            lambda: self._set_skipped_for_selection(False)
        )
        bulk_row.addWidget(self.unskip_selection_button)
        self.reload_obsids_button = QPushButton(_tr("Reload obsids"), self)
        self.reload_obsids_button.setEnabled(self._reload_callback is not None)
        self.reload_obsids_button.clicked.connect(self._reload_obsids)
        bulk_row.addWidget(self.reload_obsids_button)
        bulk_row.addStretch(1)
        layout.addLayout(bulk_row)
        layout.addWidget(self.table)

        self.buttons = QDialogButtonBox()
        layout.addWidget(self.buttons)

        self.obsid_delegate = _ObsidDelegate(self.existing_obsids, self)
        self.table.setItemDelegateForColumn(_COL_OBSID, self.obsid_delegate)
        self.table.itemChanged.connect(self._on_item_changed)

    def _populate_table(self):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.editor_rows))
        for row_idx, row in enumerate(self.editor_rows):
            self.table.setItem(
                row_idx, _COL_SPEC, QTableWidgetItem(row.specifik_provplats)
            )
            self.table.setItem(row_idx, _COL_NAMN, QTableWidgetItem(row.provplatsnamn))
            self.table.setItem(
                row_idx, _COL_ORSAK, QTableWidgetItem(row.provtagningsorsak)
            )
            self.table.setItem(
                row_idx, _COL_NLAB, QTableWidgetItem(str(len(row.lablitteras)))
            )
            self.table.setItem(row_idx, _COL_OBSID, QTableWidgetItem(row.obsid))
            if row.cached:
                for col in range(self.table.columnCount()):
                    item = self.table.item(row_idx, col)
                    if item is not None:
                        item.setForeground(QBrush(QColor(120, 120, 120)))
        self._apply_filters()

    def set_obsid_value(self, row_idx: int, obsid: str):
        item = self.table.item(row_idx, _COL_OBSID)
        if item is None:
            item = QTableWidgetItem()
            self.table.setItem(row_idx, _COL_OBSID, item)
        item.setText(obsid)
        self.editor_rows[row_idx].obsid = obsid
        self._paint_obsid_cell(row_idx)

    def row_has_invalid_obsid(self, row_idx: int) -> bool:
        row = self.editor_rows[row_idx]
        if row.skipped:
            return False
        return bool(row.obsid) and row.obsid not in self.existing_obsids

    def _paint_obsid_cell(self, row_idx: int):
        item = self.table.item(row_idx, _COL_OBSID)
        if item is None:
            return
        item.setBackground(
            _INVALID_BRUSH if self.row_has_invalid_obsid(row_idx) else _DEFAULT_BRUSH
        )

    def _apply_filters(self):
        needle = self.search_input.text().strip().lower()
        show_matched = self.show_matched_checkbox.isChecked()
        visible = 0
        for row_idx in range(self.table.rowCount()):
            row = self.editor_rows[row_idx]
            if not show_matched and row.cached:
                self.table.setRowHidden(row_idx, True)
                continue
            if needle:
                match = False
                for col in (_COL_SPEC, _COL_NAMN, _COL_ORSAK, _COL_OBSID):
                    item = self.table.item(row_idx, col)
                    if item and needle in item.text().lower():
                        match = True
                        break
            else:
                match = True
            self.table.setRowHidden(row_idx, not match)
            if match:
                visible += 1
        self.row_count_label.setText(f"{visible} / {self.table.rowCount()}")

    def _selected_row_indices(self) -> list[int]:
        return sorted({idx.row() for idx in self.table.selectionModel().selectedRows()})

    def _fill_selection(self):
        obsid = self.fill_combo.currentText().strip()
        for row_idx in self._selected_row_indices():
            self.set_obsid_value(row_idx, obsid)

    def _set_skipped_for_selection(self, skipped: bool):
        for row_idx in self._selected_row_indices():
            self.editor_rows[row_idx].skipped = skipped
            item = self.table.item(row_idx, _COL_OBSID)
            if item is None:
                item = QTableWidgetItem()
                self.table.setItem(row_idx, _COL_OBSID, item)
            if skipped:
                item.setText("[skipped]")
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                for col in range(self.table.columnCount()):
                    cell = self.table.item(row_idx, col)
                    if cell is not None:
                        font = cell.font()
                        font.setStrikeOut(True)
                        cell.setFont(font)
            else:
                item.setText(self.editor_rows[row_idx].obsid)
                item.setFlags(item.flags() | Qt.ItemIsEditable)
                for col in range(self.table.columnCount()):
                    cell = self.table.item(row_idx, col)
                    if cell is not None:
                        font = cell.font()
                        font.setStrikeOut(False)
                        cell.setFont(font)
            self._paint_obsid_cell(row_idx)

    def _on_item_changed(self, item):
        if item.column() != _COL_OBSID:
            return
        row_idx = item.row()
        self.editor_rows[row_idx].obsid = item.text()
        self._paint_obsid_cell(row_idx)

    def _reload_obsids(self):
        if self._reload_callback is None:
            return
        self.existing_obsids = list(self._reload_callback())
        self.obsid_delegate.set_existing_obsids(self.existing_obsids)
        current_text = self.fill_combo.currentText()
        self.fill_combo.clear()
        self.fill_combo.addItems(self.existing_obsids)
        self.fill_combo.setEditText(current_text)
        for row_idx in range(self.table.rowCount()):
            self._paint_obsid_cell(row_idx)
