> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-06-04 · modified: 2026-06-04 · archived: 2026-07-31

# Logger Editor — duplicate-resolution UI (Plan 2c of Plan 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface duplicate timestamps to the user (non-blocking banner) and give them a dialog to clean them — wiring the Plan 2b resolution operations, with visual comparison on the existing plot and row/series metadata for context.

**Architecture:** A `_refresh_dupe_banner()` method shows/hides an in-window warning label + "Resolve duplicates…" button based on `_duplicate_instants()`. The button opens `ResolveDuplicatesDialog` (new module `tools/loggereditor_resolve_dupes.py`, mirroring `tools/loggereditor_refseries.py`). The dialog reads `editor._classify_duplicates()` and calls the 2b ops (`_remove_redundant_duplicates`, `_remove_cross_source_overlaps`, `_resolve_conflict_keep`); a `_focus_plot_on_instants()` helper drives the existing plot for visual comparison. Row-level `comment` is loaded into the buffer for display.

**Tech Stack:** Python 3, pandas, PyQt/QGIS; pytest (show()-based integration where UI state is asserted).

This is Plan 2c of Plan 2. Plan 2a (foundation) and 2b (classification + resolution ops) are merged. Spec: `docs/superpowers/specs/2026-06-03-loggereditor-duplicate-datetime-resolution-design.md`.

---

## Background the implementer must know

- Detection/classification/resolution already exist on `LoggerEditor` (Plan 2a/2b): `_duplicate_instants()`, `_classify_duplicates()` → list of `{"instant": Timestamp, "kind": "redundant"|"cross_source"|"conflict", "rows": [ {date_time_raw, head_cm_m, level_masl, source, series_id, dt_length, [created_at]} ]}`, and `_remove_redundant_duplicates() -> int`, `_remove_cross_source_overlaps(keep_source) -> int`, `_resolve_conflict_keep(instant, keep_raw) -> int`. All mutate `self._buf`, push undo history, and are persisted on Save.
- Editor UI built in `show()`. Key widgets: `self.horizontal_layout` (obsid row, has the Save button), `self.vertical_layout_6` (holds `self.tab_widget`; undo/redo strip is inserted before the tab via `insertWidget`), checkboxes `self.separate_source_cb` / `self.separate_created_at_cb` / `self.separate_dt_precision_cb`, date widgets `self.from_date_time` / `self.to_date_time` (`setDateTime(...)`), `self._selected_line_keys` (set), `self._recompute_line_keys()`, `self.update_plot()`, `self._iface` (QGIS iface).
- Qt imports already present: `QCheckBox, QComboBox, QDockWidget, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QShortcut, QTextEdit, QVBoxLayout, QWidget`. NOT yet imported: `QDialog, QDialogButtonBox, QTableWidget, QTableWidgetItem, QScrollArea`.
- Sibling dialog template: `tools/loggereditor_refseries.py` `class RefSeriesDialog(QDialog)` (QVBoxLayout + QDialogButtonBox). Read it before Task 4.
- Tests build the editor two ways: `_make_editor_with_buf` (no `show()`, for buffer logic) and full `show()` (the `test_wlevels_calc_calibr.py` calibr tests). The dialog and `_focus_plot_on_instants` need `show()`; the banner-state check needs `show()`.

---

## File Structure

- Modify: `tools/loggereditor.py` — `comment` loading (Task 1), `_focus_plot_on_instants` (Task 2), banner widget + `_refresh_dupe_banner` + open-dialog wiring (Task 3 & 4 hook).
- Create: `tools/loggereditor_resolve_dupes.py` — `ResolveDuplicatesDialog` (Task 4).
- Test: `test/test_loggereditor_dupes.py` (Tasks 1, 2, 4 logic) and `test/test_loggereditor_resolve_ui.py` (new; Task 3 banner + Task 4 dialog via show()).

---

## Task 1: Load row-level `comment` into the buffer

**Files:**
- Modify: `tools/loggereditor.py` (`load_obsid_and_init` — `has_comment` + SQL `extra_cols` + buffer build, all three schema variants; `_make_editor_with_buf` in `test/test_loggereditor_series.py`)
- Test: `test/test_loggereditor_dupes.py`

- [ ] **Step 1: Write the failing test**

```python
    def test_buffer_carries_comment_when_present(self):
        _insert_obs_point("rb1")
        editor = _make_editor_with_buf(
            self.iface, self.midvatten.ms, obsid="rb1",
            dates=["2024-01-01 00:00:00", "2024-01-02 00:00:00"],
            head_values=[1.0, 2.0], level_values=[10.0, 20.0],
            series_ids=[None, None], sources=["", ""], series_buf={},
            comments=["hello", ""],
        )
        assert editor._buf["comment"].tolist() == ["hello", ""]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest test/test_loggereditor_dupes.py -k carries_comment -x`
Expected: FAIL — `_make_editor_with_buf` has no `comments` parameter.

- [ ] **Step 3: Add `comments` to the test helper**

In `test/test_loggereditor_series.py` `_make_editor_with_buf`, add a keyword param `comments: list | None = None` and include the column when provided:

```python
def _make_editor_with_buf(
    iface, ms, obsid, dates, head_values, level_values,
    series_ids, sources, series_buf, comments=None,
):
    ...
    data = {
        "head_cm_m": head_values,
        "level_masl": level_values,
        "source": sources,
        "series_id": pd.array(series_ids, dtype="Int64"),
        "dt_length": [len(d) for d in dates],
        "date_time_raw": list(dates),
    }
    if comments is not None:
        data["comment"] = list(comments)
    buf_df = pd.DataFrame(data, index=pd.to_datetime(dates, format="ISO8601"))
```

- [ ] **Step 4: Run to verify the test passes**

Run: `python3 -m pytest test/test_loggereditor_dupes.py -k carries_comment -x`
Expected: PASS.

- [ ] **Step 5: Load `comment` in the real load path**

In `tools/loggereditor.py` `load_obsid_and_init`, next to `has_created_at = "created_at" in existing_columns`, add:

```python
            has_comment = "comment" in existing_columns
```

In EACH of the three schema-variant SQL builders, append a conditional comment column to `extra_cols` AFTER the `created_at` append and BEFORE the `dt_length` append. For the `series_join` variant use `l.comment`; for `source_col` and `no_source` use `comment`:

```python
                if has_comment:
                    extra_cols += ", COALESCE(l.comment, '') AS comment"   # series_join
                # ... (use COALESCE(comment, '') for the other two variants)
```

In the buffer-construction block, after the `created_at` block and its `col_idx += 1`, and BEFORE the `dt_length` read, add:

```python
                if has_comment:
                    cols_data["comment"] = [
                        str(r[col_idx]) if r[col_idx] else ""
                        for r in head_level_masl_list
                    ]
                    col_idx += 1
```

In the empty-buffer branch, append `"comment"` to `buf_cols` when `has_comment` (place it before `dt_length`/`date_time_raw` consistently with the read order).

IMPORTANT: the column order in `extra_cols` must match the `col_idx` read order exactly: `created_at` (if present), `comment` (if present), `dt_length`. Keep `date_time_raw` sourced from `r[0]`.

- [ ] **Step 6: No-regression + lint + commit**

```bash
python3 -m pytest test/test_loggereditor_dupes.py test/test_loggereditor_series.py test/test_loggereditor_separation.py test/test_loggereditor_refseries.py test/test_wlevels_calc_calibr.py -m spatialite -x
ruff check --fix tools/loggereditor.py test/test_loggereditor_dupes.py test/test_loggereditor_series.py
ruff format tools/loggereditor.py test/test_loggereditor_dupes.py test/test_loggereditor_series.py
git add tools/loggereditor.py test/test_loggereditor_dupes.py test/test_loggereditor_series.py
git commit -m "feat: load row-level comment into loggereditor buffer"
```

---

## Task 2: `_focus_plot_on_instants` helper

Drives the existing plot to show the competing rows at given instants: turns on datetime-precision separation (so twins draw as distinct lines), selects the affected line keys, and sets the date range to span the instants.

**Files:**
- Modify: `tools/loggereditor.py` (add `_focus_plot_on_instants`)
- Test: `test/test_loggereditor_resolve_ui.py` (new; needs `show()`)

- [ ] **Step 1: Write the failing test**

Create `test/test_loggereditor_resolve_ui.py`:

```python
"""show()-based UI tests for duplicate-resolution (banner, plot-focus, dialog)."""

import gc
from unittest import mock

import pytest

pytest.importorskip("qgis.PyQt")

import pandas as pd

from midvatten.test import utils_for_tests
from midvatten.tools.loggereditor import LoggerEditor
from midvatten.tools.utils import db_utils, gui_utils
from midvatten.test.test_loggereditor_dupes import _drop_dt_index


def _setup_twin_obsid():
    db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
    _drop_dt_index()
    db_utils.sql_alter_db(
        "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl)"
        " VALUES ('rb1','2024-01-01 00:00',100,10.0),"
        " ('rb1','2024-01-01 00:00:00',100,10.0),"
        " ('rb1','2024-01-02 00:00:00',200,20.0)"
    )


@pytest.mark.spatialite
class TestResolveUiSpatialite(utils_for_tests.MidvattenTestSpatialiteDbSv):
    def teardown_method(self):
        super().teardown_method()
        gc.collect()

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_focus_plot_on_instants_sets_range_and_separation(self, mock_messagebar):
        _setup_twin_obsid()
        editor = LoggerEditor(self.iface, self.midvatten.ms)
        editor.show()
        gui_utils.set_combobox(editor.combobox_obsid, "rb1")
        editor.update_plot()

        editor._focus_plot_on_instants([pd.Timestamp("2024-01-01 00:00:00")])

        print(f"{mock_messagebar.mock_calls=}")
        # datetime-precision separation enabled so twins are distinct lines
        assert editor.separate_dt_precision_cb.isChecked() is True
        # the date range brackets the focused instant
        assert editor.from_date_time.dateTime().toPyDateTime() <= pd.Timestamp(
            "2024-01-01 00:00:00"
        )
        assert editor.to_date_time.dateTime().toPyDateTime() >= pd.Timestamp(
            "2024-01-01 00:00:00"
        )
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest test/test_loggereditor_resolve_ui.py -k focus_plot -x`
Expected: FAIL — `_focus_plot_on_instants` missing.

- [ ] **Step 3: Implement `_focus_plot_on_instants`**

Add to `LoggerEditor` (near `update_plot`):

```python
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
            keys = set(self._buf.loc[mask, "_line_key"].tolist())
            self._selected_line_keys = keys
        lo = min(instants)
        hi = max(instants)
        # pad by a day so the points are not on the axis edge
        self.from_date_time.setDateTime(lo - pd.Timedelta(days=1))
        self.to_date_time.setDateTime(hi + pd.Timedelta(days=1))
        self.update_plot()
```

Note: `separate_dt_precision_cb.stateChanged` may be wired to recompute/replot; calling `setChecked(True)` then `update_plot()` is safe (idempotent). If toggling the checkbox triggers its own replot, that's fine — `update_plot` at the end ensures the final state.

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest test/test_loggereditor_resolve_ui.py -k focus_plot -x`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
ruff check --fix tools/loggereditor.py test/test_loggereditor_resolve_ui.py
ruff format tools/loggereditor.py test/test_loggereditor_resolve_ui.py
git add tools/loggereditor.py test/test_loggereditor_resolve_ui.py
git commit -m "feat: _focus_plot_on_instants drives plot to show competing twins"
```

---

## Task 3: Duplicate banner (warning + Resolve button)

**Files:**
- Modify: `tools/loggereditor.py` (`show()` builds the banner widget; `_refresh_dupe_banner()`; call it at the end of `update_plot`)
- Test: `test/test_loggereditor_resolve_ui.py`

- [ ] **Step 1: Write the failing test**

```python
    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_dupe_banner_visible_only_when_duplicates(self, mock_messagebar):
        _setup_twin_obsid()
        # a second clean obsid
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('clean1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl)"
            " VALUES ('clean1','2024-03-01 00:00:00',1,1.0)"
        )
        editor = LoggerEditor(self.iface, self.midvatten.ms)
        editor.show()

        gui_utils.set_combobox(editor.combobox_obsid, "rb1")
        editor.update_plot()
        print(f"{mock_messagebar.mock_calls=}")
        assert editor._resolve_dupes_btn.isVisible() is True
        assert "2" in editor._dupe_warning_label.text()  # 2 duplicate timestamps? -> count is 1 instant / 2 rows

        gui_utils.set_combobox(editor.combobox_obsid, "clean1")
        editor.update_plot()
        assert editor._resolve_dupes_btn.isVisible() is False
```

(Adjust the count assertion in Step 3 to whatever the banner text states; assert the banner reports the right number of duplicated *instants* — here 1. Use `assert "1" in editor._dupe_warning_label.text()`.)

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest test/test_loggereditor_resolve_ui.py -k dupe_banner -x`
Expected: FAIL — no `_resolve_dupes_btn` / `_dupe_warning_label`.

- [ ] **Step 3: Build the banner in `show()` and add `_refresh_dupe_banner`**

In `show()`, after the undo/redo strip insertion (around the `parent_layout.insertWidget(tab_index, undo_redo_widget)` block), build a banner widget and insert it likewise:

```python
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
            parent_layout.insertWidget(
                max(tab_index, 0), self._dupe_banner
            )
            self._dupe_banner.setVisible(False)
```

Add the refresh method and a placeholder dialog opener (the real dialog comes in Task 4):

```python
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

    def _open_resolve_dupes_dialog(self) -> None:
        # Real implementation added in Task 4.
        pass
```

Call `self._refresh_dupe_banner()` at the very end of `update_plot` (after the move/select-nodes block).

Note on `isVisible()` in tests: a child widget's `isVisible()` reflects the parent window being shown; the calibr tests call `.show()` so this holds. If `isVisible()` proves flaky in the headless test env, assert `editor._dupe_banner.isVisibleTo(editor)` instead (does not require the window to be mapped). Use `isVisibleTo` in the test if `isVisible` is unreliable.

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest test/test_loggereditor_resolve_ui.py -k dupe_banner -x`
Expected: PASS. (If `isVisible()` is flaky, switch the asserts to `isVisibleTo(editor)`.)

- [ ] **Step 5: Lint + commit**

```bash
ruff check --fix tools/loggereditor.py test/test_loggereditor_resolve_ui.py
ruff format tools/loggereditor.py test/test_loggereditor_resolve_ui.py
git add tools/loggereditor.py test/test_loggereditor_resolve_ui.py
git commit -m "feat: duplicate-timestamps banner in logger editor"
```

---

## Task 4: ResolveDuplicatesDialog

**Files:**
- Create: `tools/loggereditor_resolve_dupes.py`
- Modify: `tools/loggereditor.py` (`_open_resolve_dupes_dialog` opens the dialog; add the import)
- Test: `test/test_loggereditor_dupes.py` (dialog logic via direct handler calls — no `exec_`)

- [ ] **Step 1: Read the sibling dialog template**

Read `tools/loggereditor_refseries.py` (`RefSeriesDialog`) to match the QDialog construction style, imports, and translate usage.

- [ ] **Step 2: Write the failing tests**

Add to `test/test_loggereditor_dupes.py` (uses the `_twin_editor` helper from Plan 2b):

```python
    def test_resolve_dialog_remove_redundant(self):
        from midvatten.tools.loggereditor_resolve_dupes import ResolveDuplicatesDialog
        editor = self._twin_editor()
        before = len(editor._buf)
        dlg = ResolveDuplicatesDialog(editor)
        dlg._on_remove_redundant()
        # the redundant coarse twin is gone
        assert len(editor._buf) == before - 1
        assert editor._dirty is True

    def test_resolve_dialog_cross_source_keep(self):
        from midvatten.tools.loggereditor_resolve_dupes import ResolveDuplicatesDialog
        editor = self._twin_editor()
        dlg = ResolveDuplicatesDialog(editor)
        dlg._on_keep_source("a")
        sub = editor._buf[editor._buf.index == pd.Timestamp("2024-01-02 00:00:00")]
        assert sub["source"].tolist() == ["a"]

    def test_resolve_dialog_summary_counts(self):
        from midvatten.tools.loggereditor_resolve_dupes import ResolveDuplicatesDialog
        editor = self._twin_editor()
        dlg = ResolveDuplicatesDialog(editor)
        counts = dlg._bucket_counts()
        assert counts == {"redundant": 1, "cross_source": 1, "conflict": 1}
```

- [ ] **Step 3: Run to verify they fail**

Run: `python3 -m pytest test/test_loggereditor_dupes.py -k resolve_dialog -x`
Expected: FAIL — module/class does not exist.

- [ ] **Step 4: Implement `ResolveDuplicatesDialog`**

Create `tools/loggereditor_resolve_dupes.py`:

```python
"""Dialog to resolve duplicate timestamps in the logger editor.

Reads the editor's classification and calls its buffer resolution operations
(all undoable and persisted on Save). Visual comparison is delegated to the
editor's plot via _focus_plot_on_instants.
"""

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


def _tr(text: str) -> str:
    return QCoreApplication.translate("ResolveDuplicatesDialog", text)


class ResolveDuplicatesDialog(QDialog):
    def __init__(self, editor, parent=None):
        super().__init__(parent or editor)
        self._editor = editor
        self.setWindowTitle(_tr("Resolve duplicate timestamps"))
        self.resize(640, 480)
        self._outer = QVBoxLayout(self)
        self._body_holder = QVBoxLayout()
        self._outer.addLayout(self._body_holder)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        self._outer.addWidget(buttons)
        self._rebuild()

    # --- data helpers -------------------------------------------------
    def _groups(self) -> list:
        return self._editor._classify_duplicates()

    def _bucket_counts(self) -> dict:
        counts = {"redundant": 0, "cross_source": 0, "conflict": 0}
        for g in self._groups():
            counts[g["kind"]] += 1
        return counts

    def _cross_source_values(self) -> list:
        """Distinct sources appearing in cross-source groups (for keep choices)."""
        sources = []
        for g in self._groups():
            if g["kind"] != "cross_source":
                continue
            for r in g["rows"]:
                if r["source"] not in sources:
                    sources.append(r["source"])
        return sources

    # --- actions ------------------------------------------------------
    def _on_remove_redundant(self) -> None:
        self._editor._remove_redundant_duplicates()
        self._after_change()

    def _on_keep_source(self, keep_source: str) -> None:
        self._editor._remove_cross_source_overlaps(keep_source)
        self._after_change()

    def _on_keep_conflict(self, instant, keep_raw: str) -> None:
        self._editor._resolve_conflict_keep(instant, keep_raw)
        self._after_change()

    def _on_show_instants(self, instants: list) -> None:
        self._editor._focus_plot_on_instants(instants)

    def _after_change(self) -> None:
        self._editor.update_plot()
        self._rebuild()

    # --- view ---------------------------------------------------------
    def _clear_body(self) -> None:
        while self._body_holder.count():
            item = self._body_holder.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

    def _rebuild(self) -> None:
        self._clear_body()
        groups = self._groups()
        counts = self._bucket_counts()

        if not groups:
            self._body_holder.addWidget(
                QLabel(_tr("No duplicate timestamps remain."), self)
            )
            return

        # Bucket 1 — redundant
        if counts["redundant"]:
            box = QGroupBox(
                _tr("Redundant (identical values) — %s") % counts["redundant"], self
            )
            lay = QVBoxLayout(box)
            lay.addWidget(
                QLabel(
                    _tr("Keeps the higher datetime-precision row, drops the rest."),
                    self,
                )
            )
            row = QHBoxLayout()
            btn = QPushButton(
                _tr("Remove %s redundant row(s)")
                % sum(len(g["rows"]) - 1 for g in groups if g["kind"] == "redundant"),
                self,
            )
            btn.clicked.connect(self._on_remove_redundant)
            show = QPushButton(_tr("Show on plot"), self)
            show.clicked.connect(
                lambda: self._on_show_instants(
                    [g["instant"] for g in self._groups() if g["kind"] == "redundant"]
                )
            )
            row.addWidget(btn)
            row.addWidget(show)
            row.addStretch()
            lay.addLayout(row)
            self._body_holder.addWidget(box)

        # Bucket 2 — cross-source
        if counts["cross_source"]:
            box = QGroupBox(
                _tr("Different sources — %s") % counts["cross_source"], self
            )
            lay = QVBoxLayout(box)
            lay.addWidget(
                QLabel(_tr("Keep one source at the overlapping instants:"), self)
            )
            for src in self._cross_source_values():
                row = QHBoxLayout()
                label = src if (src and str(src).strip()) else _tr("(no source)")
                keep_btn = QPushButton(_tr("Keep '%s'") % label, self)
                keep_btn.clicked.connect(
                    lambda _checked=False, s=src: self._on_keep_source(s)
                )
                row.addWidget(keep_btn)
                row.addStretch()
                lay.addLayout(row)
            show = QPushButton(_tr("Show on plot"), self)
            show.clicked.connect(
                lambda: self._on_show_instants(
                    [g["instant"] for g in self._groups() if g["kind"] == "cross_source"]
                )
            )
            lay.addWidget(show)
            self._body_holder.addWidget(box)

        # Bucket 3 — conflicts (per instant)
        if counts["conflict"]:
            box = QGroupBox(_tr("Conflicts (values differ) — %s") % counts["conflict"], self)
            lay = QVBoxLayout(box)
            scroll = QScrollArea(self)
            scroll.setWidgetResizable(True)
            inner = QWidget(scroll)
            inner_lay = QVBoxLayout(inner)
            for g in groups:
                if g["kind"] != "conflict":
                    continue
                instant = g["instant"]
                inner_lay.addWidget(
                    QLabel(_tr("At %s:") % instant.strftime("%Y-%m-%d %H:%M:%S"), inner)
                )
                for r in g["rows"]:
                    row = QHBoxLayout()
                    desc = _tr("head=%s level=%s src=%s") % (
                        r["head_cm_m"], r["level_masl"], r["source"],
                    )
                    keep_btn = QPushButton(_tr("Keep: %s") % desc, inner)
                    keep_btn.clicked.connect(
                        lambda _checked=False, i=instant, raw=r["date_time_raw"]: (
                            self._on_keep_conflict(i, raw)
                        )
                    )
                    row.addWidget(keep_btn)
                    row.addStretch()
                    inner_lay.addLayout(row)
            inner_lay.addStretch()
            scroll.setWidget(inner)
            lay.addWidget(scroll)
            self._body_holder.addWidget(box)
```

- [ ] **Step 5: Wire the opener in the editor**

In `tools/loggereditor.py`, add at module top (with the other tool imports):

```python
from midvatten.tools.loggereditor_resolve_dupes import ResolveDuplicatesDialog
```

Replace the placeholder `_open_resolve_dupes_dialog` body:

```python
    def _open_resolve_dupes_dialog(self) -> None:
        if not self._duplicate_instants().size:
            return
        dlg = ResolveDuplicatesDialog(self, parent=self)
        dlg.exec_()
        self._refresh_dupe_banner()
```

(If a circular-import arises because `loggereditor_resolve_dupes` imports nothing from `loggereditor`, there is none — the dialog only takes an `editor` instance at runtime. Keep the import at module top.)

- [ ] **Step 6: Run the dialog tests**

Run: `python3 -m pytest test/test_loggereditor_dupes.py -k resolve_dialog -x`
Expected: PASS.

- [ ] **Step 7: Full no-regression + lint + commit**

```bash
python3 -m pytest test/test_loggereditor_dupes.py test/test_loggereditor_resolve_ui.py test/test_loggereditor_series.py test/test_loggereditor_separation.py test/test_loggereditor_refseries.py test/test_wlevels_calc_calibr.py -m spatialite -x
ruff check --fix tools/loggereditor.py tools/loggereditor_resolve_dupes.py test/test_loggereditor_dupes.py
ruff format tools/loggereditor.py tools/loggereditor_resolve_dupes.py test/test_loggereditor_dupes.py
git add tools/loggereditor.py tools/loggereditor_resolve_dupes.py test/test_loggereditor_dupes.py
git commit -m "feat: ResolveDuplicatesDialog wiring 2b resolution ops"
```

---

## Self-Review

**Spec coverage:** load banner (Task 3), resolve dialog with the three buckets — redundant bulk-remove, cross-source keep-one, per-instant conflict keep (Task 4), visual comparison via the existing plot (Task 2 `_focus_plot_on_instants`, "Show on plot" buttons), and `comment`/series metadata display (Task 1 loads `comment`; `_series_buf` already holds series metadata; conflict rows show head/level/source). All actions go through the 2b ops → undoable + persisted (Plan 2a). The dialog refreshes after each action and shows "No duplicate timestamps remain." when done.

**Placeholder scan:** none — every step has concrete code/commands. Task 3's placeholder `_open_resolve_dupes_dialog` is explicitly replaced in Task 4.

**Type consistency:** `_classify_duplicates()` group dicts (`instant`/`kind`/`rows`) are consumed consistently; `_focus_plot_on_instants(list)`; dialog handlers `_on_remove_redundant()`, `_on_keep_source(str)`, `_on_keep_conflict(instant, raw)`, `_bucket_counts() -> dict`. `_resolve_dupes_btn`/`_dupe_warning_label`/`_dupe_banner` names consistent between Task 3 and tests. The import in Task 4 Step 5 matches the module/class created in Step 4.

**Risk notes:**
- `isVisible()` vs `isVisibleTo()` in the headless test env — the plan tells the implementer to fall back to `isVisibleTo(editor)` if needed.
- The `comment` `col_idx` ordering (Task 1) must match between SQL build and buffer read — called out explicitly.
- The dialog uses lambdas with default-arg capture (`s=src`, `raw=r[...]`) to avoid late-binding closure bugs — already encoded.
