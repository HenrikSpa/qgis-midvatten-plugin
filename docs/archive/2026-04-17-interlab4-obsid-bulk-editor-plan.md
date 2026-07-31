> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-04-17 · modified: 2026-04-17 · archived: 2026-07-31

# Interlab4 Obsid Bulk Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the per-row `NotFoundQuestion` loop in the Interlab4 importer with a batch-editable `ObsidAssignmentDialog` (spreadsheet-style grid + bulk actions), while keeping `NotFoundQuestion` as a safety-net fallback for rows the user leaves unfilled.

**Architecture:** A new reusable `ObsidAssignmentDialog` (`QTableWidget` + global search + bulk toolbar) is inserted into `Interlab4Import.start_import()` *after* the existing `zz_interlab4_obsid_assignment` cache lookup and *before* the existing `filter_nonexisting_values_and_ask()` call. Rows are grouped by a pure-Python `group_editor_rows()` helper (dedupe when `provtagningsorsak` is empty; explode to per-lablittera otherwise). On Apply, the dialog writes non-override filled rows back to the cache (INSERT OR REPLACE), then the remaining unfilled rows fall through to the existing loop unchanged. `NotFoundQuestion` is **not** touched — other importers still use it.

**Tech Stack:** Python 3, PyQt5 (QGIS), SQLite/PostGIS via existing `db_utils`, `pytest` (+ `pytest-qt` for GUI smoke tests).

**Build in a dedicated git worktree off `ai_test`. Dispatch subagents (model `sonnet`) one per task.**

**Spec:** `/home/hsai1/.claude/plans/curious-seeking-chipmunk.md`

**Code style rules (enforced by ruff):**
- All imports at module level — never inside functions (PEP 8; memory feedback)
- User-facing strings use `QCoreApplication.translate("Interlab4ObsidDialog", "...")`
- Run `ruff check --fix . && ruff format .` after every task

**Test conventions:**
- Mark with `@pytest.mark.spatialite`
- Mock `MessagebarAndLog` as `@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")` with param name `mock_messagebar`
- Print `mock_messagebar.mock_calls` before assert groups to surface hidden errors
- Use `utils_for_tests.MidvattenTestSpatialiteNotCreated` as base for DB-less tests
- Tests that construct Qt widgets must `gc.collect()` in teardown to avoid SQLite lock-ups

---

## File Structure

**New files:**
- `tools/obsid_assignment_dialog.py` — the `ObsidAssignmentDialog` class, its item delegate, and the `EditorRow` dataclass + `group_editor_rows()` helper. Self-contained; no Interlab4 imports.
- `test/test_obsid_assignment_dialog.py` — unit tests for grouping logic + Qt smoke tests.
- `test/test_interlab4_bulk_editor_integration.py` — integration test covering the full `start_import` flow with the new dialog.

**Modified files:**
- `tools/import_interlab4.py` — modify `Interlab4Import.start_import()` (lines ~230–323) to call the new dialog between the cache lookup and the existing `filter_nonexisting_values_and_ask()` fallback.

---

## Phase 1 — Pure-Python data model and grouping

No Qt dependencies. Fully unit-testable.

### Task 1: `EditorRow` dataclass and `group_editor_rows()` helper

**Files:**
- Create: `tools/obsid_assignment_dialog.py`
- Create: `test/test_obsid_assignment_dialog.py`

- [ ] **Step 1: Write the failing grouping test**

Create `test/test_obsid_assignment_dialog.py`:

```python
"""Tests for ObsidAssignmentDialog support code."""
from midvatten.tools.obsid_assignment_dialog import (
    EditorRow,
    group_editor_rows,
)


def _row(lablittera, spec, namn, orsak=""):
    return {
        "lablittera": lablittera,
        "specifik provplats": spec,
        "provplatsnamn": namn,
        "provtagningsorsak": orsak,
    }


class TestGroupEditorRows:
    def test_clean_rows_dedupe_by_pair(self):
        rows = [
            _row("L1", "Br1", "Brunn 1"),
            _row("L2", "Br1", "Brunn 1"),
            _row("L3", "Br2", "Brunn 2"),
        ]
        editor_rows = group_editor_rows(rows)
        assert len(editor_rows) == 2
        br1 = next(r for r in editor_rows if r.specifik_provplats == "Br1")
        assert br1.lablitteras == ["L1", "L2"]
        assert br1.is_override is False

    def test_override_rows_are_not_deduped(self):
        rows = [
            _row("L1", "Br2", "Brunn 2", orsak="annan"),
            _row("L2", "Br2", "Brunn 2", orsak="annan"),
        ]
        editor_rows = group_editor_rows(rows)
        assert len(editor_rows) == 2
        assert all(r.is_override for r in editor_rows)
        assert [r.lablitteras for r in editor_rows] == [["L1"], ["L2"]]

    def test_provtagningsorsak_also_triggers_override(self):
        rows = [
            _row("L1", "Br1", "Brunn 1", orsak="annan"),
        ]
        editor_rows = group_editor_rows(rows)
        assert editor_rows[0].is_override is True

    def test_mixed_clean_and_override(self):
        rows = [
            _row("L1", "Br1", "Brunn 1"),
            _row("L2", "Br1", "Brunn 1"),
            _row("L3", "Br2", "Brunn 2", orsak="annan"),
        ]
        editor_rows = group_editor_rows(rows)
        clean = [r for r in editor_rows if not r.is_override]
        override = [r for r in editor_rows if r.is_override]
        assert len(clean) == 1 and clean[0].lablitteras == ["L1", "L2"]
        assert len(override) == 1 and override[0].lablitteras == ["L3"]

    def test_prefill_from_cache(self):
        rows = [_row("L1", "Br1", "Brunn 1")]
        cache = {("Br1", "Brunn 1"): "Br1"}
        editor_rows = group_editor_rows(rows, cache_matches=cache)
        assert editor_rows[0].obsid == "Br1"
        assert editor_rows[0].cached is True
```

- [ ] **Step 2: Run test — expect ImportError**

Run: `python3 -m pytest test/test_obsid_assignment_dialog.py -x`
Expected: FAIL with `ModuleNotFoundError: No module named 'midvatten.tools.obsid_assignment_dialog'`.

- [ ] **Step 3: Implement the dataclass + grouping**

Create `tools/obsid_assignment_dialog.py`:

```python
"""Bulk obsid assignment editor for Interlab4 (and reusable elsewhere).

Pure-Python support code for the dialog lives at the top of this module so it
can be imported and unit-tested without requiring a Qt event loop. The
QWidget / QDialog classes live below, after the imports guard.
"""
from __future__ import annotations

from dataclasses import dataclass, field


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
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `python3 -m pytest test/test_obsid_assignment_dialog.py -x`
Expected: PASS (5 tests).

- [ ] **Step 5: Lint + commit**

```bash
ruff check --fix . && ruff format .
git add tools/obsid_assignment_dialog.py test/test_obsid_assignment_dialog.py
git commit -m "feat(interlab4): add EditorRow dataclass and grouping helper"
```

---

## Phase 2 — Dialog skeleton

Build the dialog shell bottom-up: table rendering → obsid delegate → global search → show-matched toggle. Each step keeps the dialog runnable and adds one feature at a time.

### Task 2: `ObsidAssignmentDialog` shell with `QTableWidget` rendering

**Files:**
- Modify: `tools/obsid_assignment_dialog.py` (append dialog class)
- Modify: `test/test_obsid_assignment_dialog.py` (append Qt smoke test)

- [ ] **Step 1: Write the failing smoke test**

Append to `test/test_obsid_assignment_dialog.py`:

```python
import gc
import pytest

qtbot_available = True
try:
    import pytestqt  # noqa: F401
except ImportError:
    qtbot_available = False

pytestmark_qt = pytest.mark.skipif(not qtbot_available, reason="pytest-qt not installed")


@pytestmark_qt
class TestObsidAssignmentDialogShell:
    def teardown_method(self):
        gc.collect()

    def test_dialog_shows_one_row_per_editor_row(self, qtbot):
        from midvatten.tools.obsid_assignment_dialog import (
            EditorRow,
            ObsidAssignmentDialog,
        )
        rows = [
            EditorRow("Br1", "Brunn 1", "", ["L1", "L2"]),
            EditorRow("Br2", "Brunn 2", "", ["L3"]),
        ]
        dialog = ObsidAssignmentDialog(rows, existing_obsids=["Br1", "Br2"])
        qtbot.addWidget(dialog)
        assert dialog.table.rowCount() == 2
        assert dialog.table.item(0, 0).text() == "Br1"
        assert dialog.table.item(0, 1).text() == "Brunn 1"
        assert dialog.table.item(0, 3).text() == "2"  # #lablitteras
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `python3 -m pytest test/test_obsid_assignment_dialog.py::TestObsidAssignmentDialogShell -x`
Expected: FAIL with `ImportError: cannot import name 'ObsidAssignmentDialog'`.

- [ ] **Step 3: Implement the dialog shell**

Append to `tools/obsid_assignment_dialog.py`:

```python
from qgis.PyQt.QtCore import Qt, QCoreApplication
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


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

    def __init__(self, editor_rows: list[EditorRow], existing_obsids: list[str], parent=None):
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
            self.table.setItem(row_idx, _COL_SPEC, QTableWidgetItem(row.specifik_provplats))
            self.table.setItem(row_idx, _COL_NAMN, QTableWidgetItem(row.provplatsnamn))
            self.table.setItem(row_idx, _COL_ORSAK, QTableWidgetItem(row.provtagningsorsak))
            self.table.setItem(row_idx, _COL_NLAB, QTableWidgetItem(str(len(row.lablitteras))))
            self.table.setItem(row_idx, _COL_OBSID, QTableWidgetItem(row.obsid))
        self.table.setSortingEnabled(True)
```

- [ ] **Step 4: Run test — expect PASS**

Run: `python3 -m pytest test/test_obsid_assignment_dialog.py -x`
Expected: PASS (all tests, including skip-if-no-pytest-qt).

- [ ] **Step 5: Commit**

```bash
ruff check --fix . && ruff format .
git add tools/obsid_assignment_dialog.py test/test_obsid_assignment_dialog.py
git commit -m "feat(interlab4): ObsidAssignmentDialog shell with QTableWidget"
```

---

### Task 3: Obsid cell delegate with `QCompleter` and validation colouring

**Files:**
- Modify: `tools/obsid_assignment_dialog.py`
- Modify: `test/test_obsid_assignment_dialog.py`

- [ ] **Step 1: Write the failing delegate test**

Append to `TestObsidAssignmentDialogShell` in `test/test_obsid_assignment_dialog.py`:

```python
    def test_invalid_obsid_paints_cell_red(self, qtbot):
        from midvatten.tools.obsid_assignment_dialog import (
            EditorRow,
            ObsidAssignmentDialog,
        )
        rows = [EditorRow("Br1", "Brunn 1", "", "", ["L1"])]
        dialog = ObsidAssignmentDialog(rows, existing_obsids=["Br1", "Br2"])
        qtbot.addWidget(dialog)
        # Directly set an invalid obsid via the model to bypass the delegate
        dialog.set_obsid_value(0, "not_in_obs_points")
        assert dialog.row_has_invalid_obsid(0)
```

- [ ] **Step 2: Run — expect FAIL**

Run: `python3 -m pytest test/test_obsid_assignment_dialog.py::TestObsidAssignmentDialogShell::test_invalid_obsid_paints_cell_red -x`
Expected: FAIL with `AttributeError: 'ObsidAssignmentDialog' has no attribute 'set_obsid_value'`.

- [ ] **Step 3: Add the delegate + validation helpers**

In `tools/obsid_assignment_dialog.py`, add imports and a delegate class:

```python
from qgis.PyQt.QtCore import Qt, QCoreApplication
from qgis.PyQt.QtGui import QBrush, QColor
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLineEdit,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


_INVALID_BRUSH = QBrush(QColor(255, 200, 200))
_DEFAULT_BRUSH = QBrush(Qt.white)


class _ObsidDelegate(QStyledItemDelegate):
    def __init__(self, existing_obsids: list[str], parent=None):
        super().__init__(parent)
        self._existing_obsids = list(existing_obsids)

    def set_existing_obsids(self, obsids: list[str]):
        self._existing_obsids = list(obsids)

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        completer = QCompleter(self._existing_obsids, editor)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        editor.setCompleter(completer)
        return editor
```

Extend `ObsidAssignmentDialog._build_ui` to install the delegate on the obsid column:

```python
        self.obsid_delegate = _ObsidDelegate(self.existing_obsids, self)
        self.table.setItemDelegateForColumn(_COL_OBSID, self.obsid_delegate)
        self.table.itemChanged.connect(self._on_item_changed)
```

Add methods to the dialog:

```python
    def set_obsid_value(self, row_idx: int, obsid: str):
        item = self.table.item(row_idx, _COL_OBSID)
        if item is None:
            item = QTableWidgetItem()
            self.table.setItem(row_idx, _COL_OBSID, item)
        item.setText(obsid)
        self.editor_rows[row_idx].obsid = obsid
        self._paint_obsid_cell(row_idx)

    def row_has_invalid_obsid(self, row_idx: int) -> bool:
        obsid = self.editor_rows[row_idx].obsid
        return bool(obsid) and obsid not in self.existing_obsids

    def _paint_obsid_cell(self, row_idx: int):
        item = self.table.item(row_idx, _COL_OBSID)
        if item is None:
            return
        item.setBackground(_INVALID_BRUSH if self.row_has_invalid_obsid(row_idx) else _DEFAULT_BRUSH)

    def _on_item_changed(self, item):
        if item.column() != _COL_OBSID:
            return
        row_idx = item.row()
        self.editor_rows[row_idx].obsid = item.text()
        self._paint_obsid_cell(row_idx)
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `python3 -m pytest test/test_obsid_assignment_dialog.py -x`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
ruff check --fix . && ruff format .
git add tools/obsid_assignment_dialog.py test/test_obsid_assignment_dialog.py
git commit -m "feat(interlab4): obsid cell delegate with completer + validation colouring"
```

---

### Task 4: Global search bar + live row count

**Files:** same as Task 3.

- [ ] **Step 1: Write the failing test**

Append to `test/test_obsid_assignment_dialog.py`:

```python
    def test_search_filters_rows_by_any_column(self, qtbot):
        from midvatten.tools.obsid_assignment_dialog import (
            EditorRow,
            ObsidAssignmentDialog,
        )
        rows = [
            EditorRow("Br1", "Brunn 1", "", "", ["L1"]),
            EditorRow("Br2", "Brunn 2", "", "", ["L2"]),
            EditorRow("Br10", "Brunn 10", "", "", ["L3"]),
        ]
        dialog = ObsidAssignmentDialog(rows, existing_obsids=["Br1", "Br2", "Br10"])
        qtbot.addWidget(dialog)
        dialog.search_input.setText("Br1")
        # Both Br1 and Br10 contain "Br1"
        visible = [r for r in range(dialog.table.rowCount()) if not dialog.table.isRowHidden(r)]
        assert len(visible) == 2
        assert dialog.row_count_label.text() == "2 / 3"
```

- [ ] **Step 2: Run — expect FAIL**

Run: `python3 -m pytest test/test_obsid_assignment_dialog.py::TestObsidAssignmentDialogShell::test_search_filters_rows_by_any_column -x`
Expected: FAIL (no `search_input`).

- [ ] **Step 3: Add the search bar**

In `_build_ui`, above the table:

```python
        from qgis.PyQt.QtWidgets import QHBoxLayout, QLabel, QLineEdit as _QLineEdit

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel(_tr("Search:")))
        self.search_input = _QLineEdit(self)
        self.search_input.setPlaceholderText(_tr("filter any column..."))
        self.search_input.textChanged.connect(self._apply_filters)
        toolbar.addWidget(self.search_input)
        self.row_count_label = QLabel("0 / 0", self)
        toolbar.addWidget(self.row_count_label)
        layout.addLayout(toolbar)
```

(Place these lines *before* the `layout.addWidget(self.table)` call. Move the `QLineEdit` import to the module-level import block.)

Implement the filter:

```python
    def _apply_filters(self):
        needle = self.search_input.text().strip().lower()
        visible = 0
        for row_idx in range(self.table.rowCount()):
            if not needle:
                match = True
            else:
                match = False
                for col in (_COL_SPEC, _COL_NAMN, _COL_ORSAK, _COL_OBSID):
                    item = self.table.item(row_idx, col)
                    if item and needle in item.text().lower():
                        match = True
                        break
            self.table.setRowHidden(row_idx, not match)
            if match:
                visible += 1
        self.row_count_label.setText(f"{visible} / {self.table.rowCount()}")
```

Call `self._apply_filters()` at the end of `_populate_table`.

- [ ] **Step 4: Run — expect PASS**

Run: `python3 -m pytest test/test_obsid_assignment_dialog.py -x`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
ruff check --fix . && ruff format .
git add -u
git commit -m "feat(interlab4): global search bar with live row count"
```

---

### Task 5: Show / hide matched rows toggle

**Files:** same.

- [ ] **Step 1: Write the failing test**

Append:

```python
    def test_matched_rows_hidden_by_default_and_toggleable(self, qtbot):
        from midvatten.tools.obsid_assignment_dialog import (
            EditorRow,
            ObsidAssignmentDialog,
        )
        rows = [
            EditorRow("Br1", "Brunn 1", "", "", ["L1"], obsid="Br1", cached=True),
            EditorRow("Br2", "Brunn 2", "", "", ["L2"]),
        ]
        dialog = ObsidAssignmentDialog(rows, existing_obsids=["Br1", "Br2"])
        qtbot.addWidget(dialog)
        # Default: matched row hidden
        assert dialog.table.isRowHidden(0) is True
        assert dialog.table.isRowHidden(1) is False
        # Toggle on -> both visible
        dialog.show_matched_checkbox.setChecked(True)
        assert dialog.table.isRowHidden(0) is False
        assert dialog.table.isRowHidden(1) is False
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Add the toggle**

In `_build_ui` (same toolbar row as search):

```python
        from qgis.PyQt.QtWidgets import QCheckBox

        self.show_matched_checkbox = QCheckBox(_tr("Show matched rows"), self)
        self.show_matched_checkbox.setChecked(False)
        self.show_matched_checkbox.toggled.connect(self._apply_filters)
        toolbar.addWidget(self.show_matched_checkbox)
```

Update `_apply_filters` so matched rows are hidden unless the checkbox is on:

```python
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
```

Also grey out cached rows in `_populate_table`:

```python
            if row.cached:
                for col in range(self.table.columnCount()):
                    item = self.table.item(row_idx, col)
                    if item is not None:
                        item.setForeground(QBrush(QColor(120, 120, 120)))
```

(Import `QColor` at module level.)

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
ruff check --fix . && ruff format .
git add -u
git commit -m "feat(interlab4): hide cached rows by default with toggle"
```

---

## Phase 3 — Bulk actions

### Task 6: Fill selection (obsid combobox + button)

**Files:** same.

- [ ] **Step 1: Failing test**

```python
    def test_fill_selection_writes_obsid_to_selected_rows(self, qtbot):
        from midvatten.tools.obsid_assignment_dialog import (
            EditorRow,
            ObsidAssignmentDialog,
        )
        rows = [
            EditorRow("Br1", "Brunn 1", "", "", ["L1"]),
            EditorRow("Br1", "Brunn 1", "", "", ["L2"]),
            EditorRow("Br2", "Brunn 2", "", "", ["L3"]),
        ]
        dialog = ObsidAssignmentDialog(rows, existing_obsids=["Br1", "Br2"])
        qtbot.addWidget(dialog)
        dialog.table.selectRow(0)
        dialog.table.selectionModel().select(
            dialog.table.model().index(1, 0),
            dialog.table.selectionModel().Select | dialog.table.selectionModel().Rows,
        )
        dialog.fill_combo.setEditText("Br1")
        dialog.fill_selection_button.click()
        assert dialog.editor_rows[0].obsid == "Br1"
        assert dialog.editor_rows[1].obsid == "Br1"
        assert dialog.editor_rows[2].obsid == ""
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Add toolbar row**

After the search toolbar, add a second `QHBoxLayout` bulk-action toolbar:

```python
        from qgis.PyQt.QtWidgets import QComboBox, QPushButton

        bulk = QHBoxLayout()
        bulk.addWidget(QLabel(_tr("Fill with:")))
        self.fill_combo = QComboBox(self)
        self.fill_combo.setEditable(True)
        self.fill_combo.addItems(self.existing_obsids)
        fill_completer = QCompleter(self.existing_obsids, self.fill_combo)
        fill_completer.setCaseSensitivity(Qt.CaseInsensitive)
        fill_completer.setFilterMode(Qt.MatchContains)
        self.fill_combo.setCompleter(fill_completer)
        bulk.addWidget(self.fill_combo)
        self.fill_selection_button = QPushButton(_tr("Fill selection"), self)
        self.fill_selection_button.clicked.connect(self._fill_selection)
        bulk.addWidget(self.fill_selection_button)
        layout.addLayout(bulk)
```

Implement the action:

```python
    def _selected_row_indices(self) -> list[int]:
        return sorted({idx.row() for idx in self.table.selectionModel().selectedRows()})

    def _fill_selection(self):
        obsid = self.fill_combo.currentText().strip()
        for row_idx in self._selected_row_indices():
            self.set_obsid_value(row_idx, obsid)
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
ruff check --fix . && ruff format .
git add -u
git commit -m "feat(interlab4): bulk Fill selection action"
```

---

### Task 7: Skip / Unskip selection

**Files:** same.

- [ ] **Step 1: Failing test**

```python
    def test_skip_and_unskip_selected_rows(self, qtbot):
        from midvatten.tools.obsid_assignment_dialog import (
            EditorRow,
            ObsidAssignmentDialog,
        )
        rows = [EditorRow("Br1", "Brunn 1", "", "", ["L1"])]
        dialog = ObsidAssignmentDialog(rows, existing_obsids=["Br1"])
        qtbot.addWidget(dialog)
        dialog.table.selectRow(0)
        dialog.skip_selection_button.click()
        assert dialog.editor_rows[0].skipped is True
        assert dialog.table.item(0, 4).text() == "[skipped]"
        dialog.unskip_selection_button.click()
        assert dialog.editor_rows[0].skipped is False
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Add buttons**

In the bulk toolbar:

```python
        self.skip_selection_button = QPushButton(_tr("Skip selection"), self)
        self.skip_selection_button.clicked.connect(lambda: self._set_skipped_for_selection(True))
        bulk.addWidget(self.skip_selection_button)
        self.unskip_selection_button = QPushButton(_tr("Unskip selection"), self)
        self.unskip_selection_button.clicked.connect(lambda: self._set_skipped_for_selection(False))
        bulk.addWidget(self.unskip_selection_button)
```

Implementation:

```python
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
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
ruff check --fix . && ruff format .
git add -u
git commit -m "feat(interlab4): Skip / Unskip selection actions"
```

---

### Task 8: Reload obsids button

**Files:** same.

- [ ] **Step 1: Failing test**

```python
    def test_reload_obsids_refreshes_completer(self, qtbot):
        from midvatten.tools.obsid_assignment_dialog import (
            EditorRow,
            ObsidAssignmentDialog,
        )
        rows = [EditorRow("Br1", "Brunn 1", "", "", ["L1"])]
        dialog = ObsidAssignmentDialog(
            rows,
            existing_obsids=["Br1"],
            reload_callback=lambda: ["Br1", "Br2", "BrNEW"],
        )
        qtbot.addWidget(dialog)
        dialog.reload_obsids_button.click()
        assert "BrNEW" in dialog.existing_obsids
        assert dialog.fill_combo.findText("BrNEW") >= 0
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Accept `reload_callback` and wire the button**

Update the constructor:

```python
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
```

In the bulk toolbar:

```python
        self.reload_obsids_button = QPushButton(_tr("Reload obsids"), self)
        self.reload_obsids_button.setEnabled(self._reload_callback is not None)
        self.reload_obsids_button.clicked.connect(self._reload_obsids)
        bulk.addWidget(self.reload_obsids_button)
```

Implementation:

```python
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
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
ruff check --fix . && ruff format .
git add -u
git commit -m "feat(interlab4): Reload obsids button"
```

---

## Phase 4 — Apply / Save draft / Cancel

### Task 9: Dialog result enum + button wiring

**Files:** same.

- [ ] **Step 1: Failing test**

```python
    def test_save_draft_produces_expected_result(self, qtbot):
        from midvatten.tools.obsid_assignment_dialog import (
            EditorRow,
            ObsidAssignmentDialog,
            DialogOutcome,
        )
        rows = [EditorRow("Br1", "Brunn 1", "", "", ["L1"], obsid="Br1")]
        dialog = ObsidAssignmentDialog(rows, existing_obsids=["Br1"])
        qtbot.addWidget(dialog)
        dialog.save_draft_button.click()
        assert dialog.outcome == DialogOutcome.SAVE_DRAFT

    def test_apply_produces_expected_result(self, qtbot):
        from midvatten.tools.obsid_assignment_dialog import (
            EditorRow,
            ObsidAssignmentDialog,
            DialogOutcome,
        )
        rows = [EditorRow("Br1", "Brunn 1", "", "", ["L1"], obsid="Br1")]
        dialog = ObsidAssignmentDialog(rows, existing_obsids=["Br1"])
        qtbot.addWidget(dialog)
        dialog.apply_button.click()
        assert dialog.outcome == DialogOutcome.APPLY

    def test_apply_blocked_on_invalid_obsid(self, qtbot, monkeypatch):
        from midvatten.tools.obsid_assignment_dialog import (
            EditorRow,
            ObsidAssignmentDialog,
        )
        rows = [EditorRow("Br1", "Brunn 1", "", "", ["L1"])]
        dialog = ObsidAssignmentDialog(rows, existing_obsids=["Br1"])
        qtbot.addWidget(dialog)
        dialog.set_obsid_value(0, "not_a_real_obsid")
        warnings = []
        monkeypatch.setattr(dialog, "_warn_invalid_obsid", lambda: warnings.append(1))
        dialog.apply_button.click()
        assert dialog.outcome is None
        assert warnings == [1]
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Add the outcome enum + buttons**

At the top of `tools/obsid_assignment_dialog.py`:

```python
from enum import Enum


class DialogOutcome(Enum):
    APPLY = "apply"
    SAVE_DRAFT = "save_draft"
    CANCEL = "cancel"
```

In `__init__` initialize `self.outcome = None`. In `_build_ui`, replace the bare `QDialogButtonBox` with three explicit buttons:

```python
        from qgis.PyQt.QtWidgets import QHBoxLayout as _Row
        footer = _Row()
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
```

Implement:

```python
    def _any_invalid_obsid(self) -> bool:
        for row_idx, row in enumerate(self.editor_rows):
            if row.skipped:
                continue
            if row.obsid and row.obsid not in self.existing_obsids:
                return True
        return False

    def _warn_invalid_obsid(self):
        from qgis.PyQt.QtWidgets import QMessageBox
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
            from qgis.PyQt.QtWidgets import QMessageBox
            box = QMessageBox(self)
            box.setWindowTitle(_tr("Discard changes?"))
            box.setText(
                _tr("You have filled %d rows that are not yet saved. Discard or save as draft?")
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
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
ruff check --fix . && ruff format .
git add -u
git commit -m "feat(interlab4): Save draft / Apply / Cancel buttons with guards"
```

---

## Phase 5 — Integration into Interlab4Import

### Task 10: Extract an `ask_obsid_rows_as_dicts()` helper for dialog input

This keeps the integration loop readable. Pure-Python, unit-testable.

**Files:**
- Modify: `tools/obsid_assignment_dialog.py` (add helper)
- Modify: `test/test_obsid_assignment_dialog.py`

- [ ] **Step 1: Failing test**

```python
def test_ask_obsid_rows_as_dicts_handles_lowercase_headers():
    from midvatten.tools.obsid_assignment_dialog import ask_obsid_rows_as_dicts
    ask_obsid_table = [
        ["Lablittera", "Specifik Provplats", "Provplatsnamn", "Provtagningsorsak"],
        ["L1", "Br1", "Brunn 1", ""],
        ["L2", "Br1", "Brunn 1", "annan"],
    ]
    rows = ask_obsid_rows_as_dicts(ask_obsid_table)
    assert rows[0]["lablittera"] == "L1"
    assert rows[0]["specifik provplats"] == "Br1"
    assert rows[1]["provtagningsorsak"] == "annan"
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

```python
def ask_obsid_rows_as_dicts(ask_obsid_table: list[list]) -> list[dict]:
    """Turn the Interlab4 ask_obsid_table (list-of-lists with a header row)
    into a list of dicts with lowercase keys, which is what group_editor_rows
    expects.
    """
    header = [str(h).strip().lower() for h in ask_obsid_table[0]]
    return [dict(zip(header, row)) for row in ask_obsid_table[1:]]
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
ruff check --fix . && ruff format .
git add -u
git commit -m "feat(interlab4): ask_obsid_rows_as_dicts input helper"
```

---

### Task 11: Write the cache upsert + fan-out helpers

**Files:**
- Modify: `tools/obsid_assignment_dialog.py`
- Modify: `test/test_obsid_assignment_dialog.py`

- [ ] **Step 1: Failing test**

```python
def test_fan_out_filled_rows_into_lablittera_map():
    from midvatten.tools.obsid_assignment_dialog import (
        EditorRow,
        fan_out_filled_rows,
    )
    rows = [
        EditorRow("Br1", "Brunn 1", "", "", ["L1", "L2"], obsid="Br1"),
        EditorRow("Br2", "Brunn 2", "", "", ["L3"], skipped=True),
        EditorRow("Br3", "Brunn 3", "egentl. Br3", "", ["L4"], obsid="Br3", is_override=True),
        EditorRow("Br4", "Brunn 4", "", "", ["L5"]),  # unfilled
    ]
    filled, skipped, cache_rows = fan_out_filled_rows(rows)
    assert filled == {"L1": "Br1", "L2": "Br1", "L4": "Br3"}
    assert skipped == {"L3"}
    # Override row is not added to cache_rows
    assert cache_rows == [("Br1", "Brunn 1", "Br1")]
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

```python
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
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
ruff check --fix . && ruff format .
git add -u
git commit -m "feat(interlab4): fan_out_filled_rows helper"
```

---

### Task 12: Integrate the dialog into `Interlab4Import.start_import()`

**Files:**
- Modify: `tools/import_interlab4.py` lines 229–323
- Create: `test/test_interlab4_bulk_editor_integration.py`

- [ ] **Step 1: Write the integration test first**

Create `test/test_interlab4_bulk_editor_integration.py`:

```python
"""End-to-end test for the bulk obsid editor inside Interlab4Import."""
import gc
from unittest import mock
import pytest

from midvatten.test import utils_for_tests
from midvatten.tools.obsid_assignment_dialog import DialogOutcome


@pytest.mark.spatialite
class TestInterlab4BulkEditorIntegration(
    utils_for_tests.MidvattenTestSpatialiteNotCreated
):
    def teardown_method(self):
        gc.collect()

    def test_apply_fills_obsids_and_writes_cache(self, monkeypatch):
        """Simulate a user filling obsids in the dialog, clicking Apply, and
        verify (a) w_qual_lab inserts use the chosen obsids and
        (b) zz_interlab4_obsid_assignment gained the non-override rows."""
        from midvatten.tools.import_interlab4 import Interlab4Import

        importer = Interlab4Import(self.iface, self.midvatten.ms)
        # TODO(executor): construct a minimal all_lab_results fixture with
        # 3 lablitteras across 2 locations, 1 override row. Use existing
        # test fixtures from test_import_interlab4_backends.py as reference.

        def fake_dialog_ctor(editor_rows, existing_obsids, reload_callback=None, parent=None):
            # Fill every clean row with the first obsid; skip override rows.
            dialog = mock.MagicMock()
            for row in editor_rows:
                if row.is_override:
                    row.skipped = True
                else:
                    row.obsid = existing_obsids[0]
            dialog.outcome = DialogOutcome.APPLY
            dialog.editor_rows = editor_rows
            return dialog

        with mock.patch(
            "midvatten.tools.obsid_assignment_dialog.ObsidAssignmentDialog",
            side_effect=fake_dialog_ctor,
        ), mock.patch(
            "midvatten.tools.utils.common_utils.MessagebarAndLog"
        ) as mock_messagebar:
            # TODO(executor): call importer.start_import(...) with fixture data.
            print(mock_messagebar.mock_calls)
            # Assert cache row count increased and that the w_qual_lab insert
            # used the expected obsid.
```

- [ ] **Step 2: Modify `start_import()`**

Key integration decision: **the new bulk editor replaces `obsid_assignment_using_table()` entirely** — we query the cache directly and pass ALL rows (matched + unmatched) to the dialog with the cache hits noted on each row. The existing `filter_nonexisting_values_and_ask()` then runs as a fallback for any leftover unfilled rows. This keeps the cache visible to the user inside the dialog (needed for the "Show matched rows" toggle).

Replace the block from current line ~239 (`connection_columns = ...`) through line ~323 (end of the cache-write block) with:

```python
        # --- NEW: query cache directly so all rows go to the bulk editor ---
        from midvatten.tools.obsid_assignment_dialog import (
            DialogOutcome,
            ObsidAssignmentDialog,
            ask_obsid_rows_as_dicts,
            fan_out_filled_rows,
            group_editor_rows,
        )

        connection_columns = ("specifik provplats", "provplatsnamn")
        remaining_lablitteras_obsids: dict[str, str] = {}

        cache_pair_map: dict[tuple[str, str], str] = {}
        if self.use_obsid_assignment_table.isChecked():
            dbconnection = db_utils.DbConnectionManager()
            try:
                sql = dbconnection.sql_ident(
                    'SELECT {c1}, {c2}, "obsid" FROM {t}',
                    t=self.obsid_assignment_table,
                    c1=connection_columns[0].replace(" ", "_"),
                    c2=connection_columns[1],
                )
                for spec, namn, obsid in dbconnection.execute_and_fetchall(sql):
                    cache_pair_map[(spec, namn)] = obsid
            finally:
                dbconnection.closedb()

        if ask_obsid_table and len(ask_obsid_table) > 1:
            row_dicts = ask_obsid_rows_as_dicts(ask_obsid_table)
            editor_rows = group_editor_rows(row_dicts, cache_matches=cache_pair_map)
            dialog = ObsidAssignmentDialog(
                editor_rows,
                existing_obsids=existing_obsids,
                reload_callback=db_utils.get_all_obsids,
                parent=self,
            )
            dialog.exec_()
            if dialog.outcome in (None, DialogOutcome.CANCEL):
                self.status = True
                return Cancel()

            filled, skipped, cache_rows = fan_out_filled_rows(dialog.editor_rows)

            # INSERT OR REPLACE because the user may have edited a cached row
            # via the "Show matched rows" toggle. Override rows are excluded
            # by fan_out_filled_rows itself.
            if cache_rows and self.use_obsid_assignment_table.isChecked():
                dbconnection = db_utils.DbConnectionManager()
                try:
                    ph = dbconnection.placeholder()
                    sql = dbconnection.sql_ident(
                        f"INSERT OR REPLACE INTO {{t}} ({{c1}}, {{c2}}, obsid) VALUES ({ph}, {ph}, {ph})",
                        t=self.obsid_assignment_table,
                        c1=connection_columns[0].replace(" ", "_"),
                        c2=connection_columns[1],
                    )
                    dbconnection.execute_and_commit(sql, all_args=cache_rows)
                finally:
                    dbconnection.closedb()
                common_utils.MessagebarAndLog.info(
                    bar_msg=QCoreApplication.translate(
                        "Interlab4Import",
                        "Obsid assignments added to table %s.",
                    )
                    % self.obsid_assignment_table
                )

            if dialog.outcome == DialogOutcome.SAVE_DRAFT:
                # Cache written; do not run the import.
                self.status = True
                return Cancel()

            # Apply path: merge filled lablitteras and drop skipped ones.
            remaining_lablitteras_obsids.update(filled)
            header = ask_obsid_table[0]
            lab_idx = [str(h).strip().lower() for h in header].index("lablittera")
            ask_obsid_table = [header] + [
                row for row in ask_obsid_table[1:]
                if row[lab_idx] not in filled and row[lab_idx] not in skipped
            ]

        # --- Existing NotFoundQuestion fallback for stragglers ---
        if ask_obsid_table and len(ask_obsid_table) > 1:
            answer = common_utils.filter_nonexisting_values_and_ask(
                ask_obsid_table,
                "obsid",
                existing_values=existing_obsids,
                try_capitalize=False,
                always_ask_user=True,
            )
            if answer == "cancel":
                self.status = True
                return Cancel()
            elif not answer:
                self.status = False
                common_utils.MessagebarAndLog.critical(
                    bar_msg=QCoreApplication.translate(
                        "Interlab4Import",
                        "Error, no observations remain. No import done.",
                    )
                )
                return Cancel()
            else:
                remaining_lablitteras_obsids.update(
                    dict([(x[0], x[-1]) for x in answer[1:]])
                )

                # Also cache NotFoundQuestion answers so future imports benefit.
                # Skip rows with non-empty provtagningsorsak (override semantics).
                if self.use_obsid_assignment_table.isChecked():
                    header = answer[0]
                    try:
                        spec_i = header.index(connection_columns[0])
                        namn_i = header.index(connection_columns[1])
                    except ValueError:
                        spec_i = namn_i = None
                    try:
                        orsak_i = header.index("provtagningsorsak")
                    except ValueError:
                        orsak_i = None
                    if spec_i is not None and namn_i is not None:
                        new_cache_rows: list[tuple[str, str, str]] = []
                        handled = set()
                        for row in answer[1:]:
                            if orsak_i is not None:
                                orsak = (row[orsak_i] or "").replace("-", "").replace("0", "").strip()
                                if orsak and not ignore_provtagningsorsak:
                                    continue
                            pair = (row[spec_i], row[namn_i])
                            if pair in handled:
                                continue
                            handled.add(pair)
                            new_cache_rows.append((pair[0], pair[1], row[-1]))
                        if new_cache_rows:
                            dbconnection = db_utils.DbConnectionManager()
                            try:
                                ph = dbconnection.placeholder()
                                sql = dbconnection.sql_ident(
                                    f"INSERT OR REPLACE INTO {{t}} ({{c1}}, {{c2}}, obsid) VALUES ({ph}, {ph}, {ph})",
                                    t=self.obsid_assignment_table,
                                    c1=connection_columns[0].replace(" ", "_"),
                                    c2=connection_columns[1],
                                )
                                dbconnection.execute_and_commit(sql, all_args=new_cache_rows)
                            finally:
                                dbconnection.closedb()
```

> **Executor note:** `obsid_assignment_using_table()` is no longer called in `start_import()`. Delete the method if no other callers remain after grep. The `handled = set()` loop in the original lines 277–323 is preserved here for the NotFoundQuestion fallback path so stragglers still seed the cache for future imports.

- [ ] **Step 3: Run tests**

Run: `python3 -m pytest test/test_import_interlab4.py -x`
Expected: PASS (existing tests unaffected because our new branch only runs when `ask_obsid_table` is non-empty and the dialog is reachable; existing tests skip the dialog via monkeypatch or don't exercise this path).

Then run: `python3 -m pytest test/test_interlab4_bulk_editor_integration.py -x` after completing the TODO fixtures.

- [ ] **Step 4: Commit**

```bash
ruff check --fix . && ruff format .
git add tools/import_interlab4.py test/test_interlab4_bulk_editor_integration.py
git commit -m "feat(interlab4): integrate ObsidAssignmentDialog into start_import"
```

---

## Phase 6 — Verification

### Task 13: Run the full test suite

- [ ] **Step 1: Run full suite**

Run: `python3 -m pytest test/ -x`
Expected: All existing tests pass, plus the new ones added in Tasks 1-12.

- [ ] **Step 2: If any failure, fix root cause (never change reference data)**

Follow the project rule from `CLAUDE.md`: never change test reference data; find the real bug.

- [ ] **Step 3: Commit any fixes as their own commit**

---

### Task 14: Manual verification in QGIS

No code changes. Check off each item after verifying in a running QGIS session.

- [ ] Import a known-good `.lab` bundle with 5 lablitteras across 2 locations and one provtagningsorsak override. Dialog shows 3 rows (2 clean + 1 override). Fill them, click Apply. Verify:
  - `w_qual_lab` rows exist with the chosen obsids.
  - `zz_interlab4_obsid_assignment` gained 2 new rows (not 3 — override not cached).
- [ ] Re-run the same import. Dialog shows 1 row (the override only). Toggle "Show matched rows" — the 2 pre-filled rows appear greyed.
- [ ] Start a new import with 40+ distinct new locations. Fill ~half via `[Fill selection]`. Click `[Save draft & close]`. Re-run the import; only the remaining ~20 rows appear.
- [ ] Accidentally click `[Cancel]` with filled cells. Confirm the guard dialog offers `[Discard] [Save draft] [Keep editing]`.
- [ ] Click `[Skip selection]` on 2 rows, then Apply. Verify the skipped lablitteras are **not** in `w_qual_lab` and **not** in `zz_interlab4_obsid_assignment`.
- [ ] Enter an obsid that is not in obs_points. Cell paints red. Click `[Apply]` — dialog blocks with a warning message box.
- [ ] Click `[Reload obsids]` after adding a new obs_point in QGIS (separate attribute-table edit). Verify the new obsid appears in the `[Fill with:]` combobox and the per-cell completer.
- [ ] Type `Br1` in the search bar. Verify only rows containing `Br1` in any column remain visible; row count label updates.

If any item fails, write up the regression as a separate bug ticket before continuing.

---

## Open tasks deferred for later

These were discussed during brainstorming and are explicitly out of scope for this plan:

- Standalone "Manage Interlab4 obsid mapping" menu entry. The widget is reusable and can be wired to a menu action in a follow-up.
- Pattern-fill helper (regex / LIKE fill across a column). The "Fill selection" action + sort + search covers the common case; add only if users ask.
- Schema extension to cache `provtagningsorsak` overrides. User accepted re-asking per import.
