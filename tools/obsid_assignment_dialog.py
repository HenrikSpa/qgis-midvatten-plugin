"""Bulk obsid assignment editor for Interlab4 (and reusable elsewhere).

Pure-Python support code (EditorRow, group_editor_rows) lives near the top;
the QDialog subclass follows below.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
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


class ObsidAssignmentDialog(QDialog):
    """Bulk obsid-assignment editor. Reusable; no Interlab4-specific imports."""

    def __init__(
        self, editor_rows: list[EditorRow], existing_obsids: list[str], parent=None
    ):
        super().__init__(parent)
        self.setWindowTitle(_tr("Assign obsids"))
        self.editor_rows = list(editor_rows)
        self.existing_obsids = list(existing_obsids)
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
        layout.addWidget(self.table)

        self.buttons = QDialogButtonBox()
        layout.addWidget(self.buttons)

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
