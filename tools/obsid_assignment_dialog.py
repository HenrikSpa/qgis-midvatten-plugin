"""Bulk obsid assignment editor for Interlab4 (and reusable elsewhere).

Pure-Python support code (EditorRow, group_editor_rows) lives near the top;
the QDialog subclass follows below.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from qgis.PyQt.QtCore import Qt, QCoreApplication
from qgis.PyQt.QtGui import QBrush, QColor
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class DialogOutcome(Enum):
    APPLY = "apply"
    SAVE_DRAFT = "save_draft"
    CANCEL = "cancel"


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
    drafted: bool = False


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


def ask_obsid_rows_as_dicts(ask_obsid_table: list[list]) -> list[dict]:
    """Turn the Interlab4 ask_obsid_table (list-of-lists with a header row)
    into a list of dicts with lowercase keys, which is what group_editor_rows
    expects.
    """
    header = [str(h).strip().lower() for h in ask_obsid_table[0]]
    return [dict(zip(header, row)) for row in ask_obsid_table[1:]]


def fan_out_filled_rows(editor_rows: list[EditorRow]):
    """Convert dialog state into (filled_map, skipped_set, cache_rows).

    filled_map: {lablittera: obsid}
    skipped_set: {lablittera}
    cache_rows: list of (spec_provplats, provplatsnamn, obsid) for
                 non-override, non-cached, filled rows only.
    """
    filled: dict[str, str] = {}
    skipped: set[str] = set()
    cache_rows: list[tuple[str, str, str]] = []
    for row in editor_rows:
        if row.skipped:
            skipped.update(row.lablitteras)
            continue
        if not row.obsid:
            continue
        for lab in row.lablitteras:
            filled[lab] = row.obsid
        if not row.is_override and not row.cached:
            cache_rows.append((row.specifik_provplats, row.provplatsnamn, row.obsid))
    return filled, skipped, cache_rows


def apply_session_draft(
    editor_rows: list[EditorRow],
    draft: dict[str, str],
    skipped: set[str],
) -> None:
    """Overlay a per-lablittera session draft onto freshly grouped rows.

    Restores exactly what the user typed this session. For each row: if any of
    its lablitteras was skipped, mark it skipped; else if any was filled, set the
    obsid to the first matching draft value and flag it `drafted` (so it renders
    as a normal visible row even when it is also in the durable cache).
    """
    for row in editor_rows:
        if any(lab in skipped for lab in row.lablitteras):
            row.skipped = True
            continue
        for lab in row.lablitteras:
            if lab in draft:
                row.obsid = draft[lab]
                row.drafted = True
                break


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
        self.outcome = None
        self._build_ui()
        self._populate_table()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, len(_COLUMN_HEADERS), self)
        self.table.setHorizontalHeaderLabels([_tr(h) for h in _COLUMN_HEADERS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        # Click-to-sort is enabled; _editor_index_at() translates the
        # sort-affected visual row back to the stable editor_rows index via
        # Qt.UserRole set on column 0. We pin the indicator to column 0 ASC
        # so the initial display matches insertion order.
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSortIndicator(0, Qt.AscendingOrder)
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

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.save_draft_button = QPushButton(_tr("Save draft && close"), self)
        self.apply_button = QPushButton(_tr("Apply && import"), self)
        self.cancel_button = QPushButton(_tr("Cancel"), self)
        self.save_draft_button.clicked.connect(self._on_save_draft)
        self.apply_button.clicked.connect(self._on_apply)
        self.cancel_button.clicked.connect(self._on_cancel)
        footer.addWidget(self.save_draft_button)
        footer.addWidget(self.apply_button)
        footer.addWidget(self.cancel_button)
        layout.addLayout(footer)

        self.obsid_delegate = _ObsidDelegate(self.existing_obsids, self)
        self.table.setItemDelegateForColumn(_COL_OBSID, self.obsid_delegate)
        self.table.itemChanged.connect(self._on_item_changed)

    def _populate_table(self):
        # Disable sorting during bulk insertion; re-enable at the end so
        # the initial row order matches editor_rows.
        self.table.setSortingEnabled(False)
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(self.editor_rows))
            for row_idx, row in enumerate(self.editor_rows):
                spec_item = QTableWidgetItem(row.specifik_provplats)
                spec_item.setData(Qt.UserRole, row_idx)
                self.table.setItem(row_idx, _COL_SPEC, spec_item)
                self.table.setItem(
                    row_idx, _COL_NAMN, QTableWidgetItem(row.provplatsnamn)
                )
                self.table.setItem(
                    row_idx, _COL_ORSAK, QTableWidgetItem(row.provtagningsorsak)
                )
                self.table.setItem(
                    row_idx, _COL_NLAB, QTableWidgetItem(str(len(row.lablitteras)))
                )
                self.table.setItem(row_idx, _COL_OBSID, QTableWidgetItem(row.obsid))
                if row.cached and not row.drafted:
                    for col in range(self.table.columnCount()):
                        item = self.table.item(row_idx, col)
                        if item is not None:
                            item.setForeground(QBrush(QColor(120, 120, 120)))
        finally:
            self.table.blockSignals(False)
        self.table.setSortingEnabled(True)
        self._apply_filters()

    def _editor_index_at(self, visual_row: int) -> int:
        """Map a table visual row back to its stable editor_rows index."""
        spec_item = self.table.item(visual_row, _COL_SPEC)
        if spec_item is None:
            return visual_row
        stored = spec_item.data(Qt.UserRole)
        return int(stored) if stored is not None else visual_row

    def set_obsid_value(self, visual_row: int, obsid: str):
        item = self.table.item(visual_row, _COL_OBSID)
        if item is None:
            item = QTableWidgetItem()
            self.table.setItem(visual_row, _COL_OBSID, item)
        item.setText(obsid)
        self.editor_rows[self._editor_index_at(visual_row)].obsid = obsid
        self._paint_obsid_cell(visual_row)

    def row_has_invalid_obsid(self, visual_row: int) -> bool:
        row = self.editor_rows[self._editor_index_at(visual_row)]
        if row.skipped:
            return False
        return bool(row.obsid) and row.obsid not in self.existing_obsids

    def _paint_obsid_cell(self, visual_row: int):
        item = self.table.item(visual_row, _COL_OBSID)
        if item is None:
            return
        item.setBackground(
            _INVALID_BRUSH if self.row_has_invalid_obsid(visual_row) else _DEFAULT_BRUSH
        )

    def _apply_filters(self):
        needle = self.search_input.text().strip().lower()
        show_matched = self.show_matched_checkbox.isChecked()
        visible = 0
        for visual_row in range(self.table.rowCount()):
            row = self.editor_rows[self._editor_index_at(visual_row)]
            if not show_matched and row.cached and not row.drafted:
                self.table.setRowHidden(visual_row, True)
                continue
            if needle:
                match = False
                for col in (_COL_SPEC, _COL_NAMN, _COL_ORSAK, _COL_OBSID):
                    item = self.table.item(visual_row, col)
                    if item and needle in item.text().lower():
                        match = True
                        break
            else:
                match = True
            self.table.setRowHidden(visual_row, not match)
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
        for visual_row in self._selected_row_indices():
            editor_row = self.editor_rows[self._editor_index_at(visual_row)]
            editor_row.skipped = skipped
            item = self.table.item(visual_row, _COL_OBSID)
            if item is None:
                item = QTableWidgetItem()
                self.table.setItem(visual_row, _COL_OBSID, item)
            if skipped:
                item.setText("[skipped]")
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            else:
                item.setText(editor_row.obsid)
                item.setFlags(item.flags() | Qt.ItemIsEditable)
            for col in range(self.table.columnCount()):
                cell = self.table.item(visual_row, col)
                if cell is not None:
                    font = cell.font()
                    font.setStrikeOut(skipped)
                    cell.setFont(font)
            self._paint_obsid_cell(visual_row)

    def _on_item_changed(self, item):
        if item.column() != _COL_OBSID:
            return
        visual_row = item.row()
        self.editor_rows[self._editor_index_at(visual_row)].obsid = item.text()
        self._paint_obsid_cell(visual_row)

    def _reload_obsids(self):
        if self._reload_callback is None:
            return
        self.existing_obsids = list(self._reload_callback())
        self.obsid_delegate.set_existing_obsids(self.existing_obsids)
        current_text = self.fill_combo.currentText()
        self.fill_combo.clear()
        self.fill_combo.addItems(self.existing_obsids)
        new_completer = QCompleter(self.existing_obsids, self.fill_combo)
        new_completer.setCaseSensitivity(Qt.CaseInsensitive)
        new_completer.setFilterMode(Qt.MatchContains)
        self.fill_combo.setCompleter(new_completer)
        self.fill_combo.setEditText(current_text)
        for row_idx in range(self.table.rowCount()):
            self._paint_obsid_cell(row_idx)

    def _any_invalid_obsid(self) -> bool:
        for row_idx, row in enumerate(self.editor_rows):
            if row.skipped:
                continue
            if row.obsid and row.obsid not in self.existing_obsids:
                return True
        return False

    def _warn_invalid_obsid(self):
        QMessageBox.warning(
            self,
            _tr("Invalid obsid"),
            _tr(
                "Some rows contain obsids that are not in obs_points. "
                "Fix, clear, or skip those rows before applying."
            ),
        )

    def _on_save_draft(self):
        if self._any_invalid_obsid():
            self._warn_invalid_obsid()
            return
        self.outcome = DialogOutcome.SAVE_DRAFT
        self.accept()

    def _on_apply(self):
        if self._any_invalid_obsid():
            self._warn_invalid_obsid()
            return
        self.outcome = DialogOutcome.APPLY
        self.accept()

    def _on_cancel(self):
        if self._has_unsaved_work():
            box = QMessageBox(self)
            box.setWindowTitle(_tr("Discard changes?"))
            box.setText(
                _tr(
                    "You have filled %d rows that are not yet saved. Discard or save as draft?"
                )
                % self._unsaved_count()
            )
            discard_btn = box.addButton(_tr("Discard"), QMessageBox.DestructiveRole)
            save_btn = box.addButton(_tr("Save draft"), QMessageBox.AcceptRole)
            keep_btn = box.addButton(_tr("Keep editing"), QMessageBox.RejectRole)
            box.exec_()
            clicked = box.clickedButton()
            if clicked is keep_btn:
                return
            if clicked is save_btn:
                self._on_save_draft()
                return
        self.outcome = DialogOutcome.CANCEL
        self.reject()

    def _has_unsaved_work(self) -> bool:
        return self._unsaved_count() > 0

    def _unsaved_count(self) -> int:
        count = 0
        for row in self.editor_rows:
            if row.skipped:
                continue
            if row.obsid and not row.cached:
                count += 1
        return count
