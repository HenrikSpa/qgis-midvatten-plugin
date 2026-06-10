# Logger Editor Layout Overhaul & Bug Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix a NumPy broadcasting bug, remove the "Update plot" button (auto-update on obsid change), add "From selection" period buttons, move all 6 plot-option checkboxes to the reference series dock, and replace the blurry adjust-trend PNG with an SVG icon.

**Architecture:** All changes are in `tools/loggereditor.py` (Python logic), `ui/calibr_logger_dialog_integrated.ui` (Qt Designer XML), and `icons/svg/` (new icon). The UI file loses widgets (`push_buttonupdateplot`, `grid_layout_7`, `horizontal_layout_2`, `logger_line_nodes`, `plot_logger_head`, `normalize_head`, `line99`). All six checkboxes are recreated dynamically in `_setup_ref_dock()`. Two "From selection" buttons are added to the period grid in the UI file. Tests referencing the removed widget names are updated.

**Tech Stack:** Python 3, PyQt5/6, NumPy, Matplotlib, QGIS API

---

### Task 1: Fix NumPy Broadcasting Bug

**Files:**
- Modify: `tools/loggereditor.py:510`

This is a one-line fix. The bug is that `np.array(line_keys, dtype=object)` on a list of uniform-length tuples creates a 2D array `(N, K)` which can't be assigned to a 1D recarray field of shape `(N,)`.

- [ ] **Step 1: Run existing tests to confirm the bug context**

```bash
python3 -m pytest test/test_wlevels_calc_calibr.py -x -v 2>&1 | tail -20
```

Expected: Tests pass (the bug only manifests with large datasets where all tuples have the same length).

- [ ] **Step 2: Fix the assignment**

In `tools/loggereditor.py` line 510, change:

```python
# Before:
arr["line_key"] = np.array(line_keys, dtype=object)

# After:
arr["line_key"] = line_keys
```

Direct list assignment to an object-dtype recarray field avoids NumPy's shape inference.

- [ ] **Step 3: Run tests**

```bash
python3 -m pytest test/test_wlevels_calc_calibr.py -x -v 2>&1 | tail -20
```

Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add tools/loggereditor.py
git commit -m "fix: assign line_keys list directly to recarray to avoid broadcasting error"
```

---

### Task 2: Remove "Update plot" Button and Auto-Update on Obsid Change

**Files:**
- Modify: `ui/calibr_logger_dialog_integrated.ui` — remove `push_buttonupdateplot` widget and its containing `horizontal_layout_2` and `grid_layout_7` (the checkboxes inside grid_layout_7 will be recreated dynamically in Task 4)
- Modify: `tools/loggereditor.py:157` — remove `push_buttonupdateplot.clicked.connect`
- Modify: `tools/loggereditor.py:1153-1172` — add `self.update_plot()` calls in `_on_obsid_changed()`

- [ ] **Step 1: Remove the UI file widgets**

In `ui/calibr_logger_dialog_integrated.ui`, delete the entire `<item>` block from line 1343 through line 1472 (the `horizontal_layout_2` containing `grid_layout_7` with checkboxes/separator and `push_buttonupdateplot`).

That block is:
```xml
        <item>
         <layout class="QHBoxLayout" name="horizontal_layout_2">
          ...everything through...
         </layout>
        </item>
```

- [ ] **Step 2: Remove the clicked.connect for update plot**

In `tools/loggereditor.py`, delete line 157:

```python
# Delete this line:
self.push_buttonupdateplot.clicked.connect(lambda x: self.update_plot())
```

- [ ] **Step 3: Add auto-update on obsid change**

In `tools/loggereditor.py`, modify `_on_obsid_changed()`. The current code is:

```python
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
```

Replace with:

```python
def _on_obsid_changed(self, new_index: int) -> None:
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
```

Two `self.update_plot()` calls added: one on the not-dirty early-return path, one at the end (covers save-succeeded and discard paths). The cancel and save-failed paths do NOT call it.

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest test/test_wlevels_calc_calibr.py -x -v 2>&1 | tail -20
```

Expected: All PASS (tests use `load_obsid_and_init()` directly, not the button).

- [ ] **Step 5: Commit**

```bash
git add tools/loggereditor.py ui/calibr_logger_dialog_integrated.ui
git commit -m "feat: auto-update plot on obsid change, remove Update plot button"
```

---

### Task 3: Add "From Selection" Buttons to Period Section

**Files:**
- Modify: `ui/calibr_logger_dialog_integrated.ui` — add two buttons in the period grid
- Modify: `tools/loggereditor.py` — split `_fit_period_to_selection` into two methods, connect new buttons, update enable-state tracking, remove old `fit_period_btn`

- [ ] **Step 1: Add buttons to the UI file**

In `ui/calibr_logger_dialog_integrated.ui`, add a "From selection" button at row 1 column 2 (after `push_button_from_extent`) and at row 4 column 2 (after `push_button_to_extent`). Also update the separator at row 2 to span 3 columns.

After the `push_button_from_extent` closing `</item>` tag (line 465), add:

```xml
          <item row="1" column="2">
           <widget class="QPushButton" name="push_button_from_selection">
            <property name="sizePolicy">
             <sizepolicy hsizetype="Minimum" vsizetype="Minimum">
              <horstretch>0</horstretch>
              <verstretch>0</verstretch>
             </sizepolicy>
            </property>
            <property name="minimumSize">
             <size>
              <width>30</width>
              <height>30</height>
             </size>
            </property>
            <property name="font">
             <font>
              <family>Noto Sans</family>
              <pointsize>8</pointsize>
              <weight>50</weight>
              <bold>false</bold>
             </font>
            </property>
            <property name="toolTip">
             <string>Set From to the earliest date of the selected lines</string>
            </property>
            <property name="text">
             <string>From selection</string>
            </property>
            <property name="enabled">
             <bool>false</bool>
            </property>
           </widget>
          </item>
```

After the `push_button_to_extent` closing `</item>` tag (around line 611), add:

```xml
          <item row="4" column="2">
           <widget class="QPushButton" name="push_button_to_selection">
            <property name="sizePolicy">
             <sizepolicy hsizetype="Minimum" vsizetype="Minimum">
              <horstretch>0</horstretch>
              <verstretch>0</verstretch>
             </sizepolicy>
            </property>
            <property name="minimumSize">
             <size>
              <width>30</width>
              <height>30</height>
             </size>
            </property>
            <property name="font">
             <font>
              <family>Noto Sans</family>
              <pointsize>8</pointsize>
              <weight>50</weight>
              <bold>false</bold>
             </font>
            </property>
            <property name="toolTip">
             <string>Set To to the latest date of the selected lines</string>
            </property>
            <property name="text">
             <string>From selection</string>
            </property>
            <property name="enabled">
             <bool>false</bool>
            </property>
           </widget>
          </item>
```

Also change the separator `<item row="2" column="0" colspan="2">` to `colspan="3"`.

- [ ] **Step 2: Replace _fit_period_to_selection with two methods**

In `tools/loggereditor.py`, replace the `_fit_period_to_selection` method (lines 699-707) and `_update_fit_period_button_state` (lines 709-711) with:

```python
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
```

- [ ] **Step 3: Remove old fit_period_btn creation and connect new buttons**

In `tools/loggereditor.py` `show()`, remove the block that creates `fit_period_btn` (lines 299-311):

```python
# Delete these lines:
self.fit_period_btn = QPushButton(...)
self.fit_period_btn.setFont(...)
self.fit_period_btn.setEnabled(False)
self.fit_period_btn.setToolTip(...)
self.fit_period_btn.clicked.connect(self._fit_period_to_selection)
self.grid_layout_7.addWidget(self.fit_period_btn, 6, 0, 1, 2)
```

Add connections after the existing `push_button_to_extent.clicked.connect` (after line 155):

```python
self.push_button_from_selection.clicked.connect(
    self._from_date_from_selection
)
self.push_button_to_selection.clicked.connect(
    self._to_date_from_selection
)
```

- [ ] **Step 4: Update all references to old method name**

In `tools/loggereditor.py`, find all calls to `_update_fit_period_button_state()` (lines 624 and 1391) and rename them to `_update_selection_button_state()`.

- [ ] **Step 5: Run tests**

```bash
python3 -m pytest test/test_wlevels_calc_calibr.py -x -v 2>&1 | tail -20
```

Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/loggereditor.py ui/calibr_logger_dialog_integrated.ui
git commit -m "feat: add independent From/To selection buttons, remove Fit period to selection"
```

---

### Task 4: Move All 6 Checkboxes to Reference Series Dock

**Files:**
- Modify: `tools/loggereditor.py:255-275` — remove checkbox additions to `grid_layout_7`, create all 6 dynamically in `_setup_ref_dock()`
- Modify: `tools/loggereditor.py:1623-1660` — add checkboxes to `_setup_ref_dock()`
- Modify: `test/test_wlevels_calc_calibr.py:481-482,513-514` — update test references

The UI file changes for removing `grid_layout_7` were already done in Task 2. Now the three UI-defined checkboxes (`logger_line_nodes`, `plot_logger_head`, `normalize_head`) no longer exist from the `.ui` file — they must be created dynamically.

- [ ] **Step 1: Create all 6 checkboxes dynamically in show()**

In `tools/loggereditor.py` `show()`, the current code at lines 255-275 creates 3 separation checkboxes and adds all 3 to `grid_layout_7`. The 3 UI-defined checkboxes (`logger_line_nodes`, `plot_logger_head`, `normalize_head`) were in the `.ui` file but are now removed.

Replace lines 255-275 (the separation checkbox creation block) with code that creates all 6 checkboxes. Place this BEFORE the `_setup_ref_dock()` call. The font reference `self.logger_line_nodes.font()` must be replaced with an explicit font since that widget no longer comes from the .ui file:

```python
from qgis.PyQt.QtGui import QFont
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
    QCoreApplication.translate(
        "Calibrlogger", "Plot logger water head"
    )
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
        "Shift head_cm line so its mean matches level_masl mean (visual only, no DB change)",
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
```

Also remove the 3 lines that added checkboxes to `grid_layout_7` (lines 273-275):
```python
# Delete:
self.grid_layout_7.addWidget(self.separate_source_cb, 3, 0, 1, 2)
self.grid_layout_7.addWidget(self.separate_created_at_cb, 4, 0, 1, 2)
self.grid_layout_7.addWidget(self.separate_dt_precision_cb, 5, 0, 1, 2)
```

And update the font reference on line 302 (`self.fit_period_btn.setFont(self.logger_line_nodes.font())`) — this line was already removed in Task 3.

- [ ] **Step 2: Add checkboxes to _setup_ref_dock()**

In `tools/loggereditor.py`, modify `_setup_ref_dock()` to add the "Plot options" section with all 6 checkboxes after the series list. Change the method from:

```python
def _setup_ref_dock(self) -> None:
    self._ref_series: list[dict] = []
    self._ref_dock = QDockWidget(...)
    self._ref_dock.setObjectName("ref_series_dock")
    container = QWidget()
    vbox = QVBoxLayout(container)
    btn_row = QHBoxLayout()
    ...
    vbox.addLayout(btn_row)
    vbox.addWidget(self._ref_list)
    self._ref_dock.setWidget(container)
    ...
```

To:

```python
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

    # Plot options section
    from qgis.PyQt.QtWidgets import QLabel, QFrame
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
```

Note: `QFont` import should be added at the top of the file (it's already imported: `from qgis.PyQt.QtGui import QCloseEvent, QFont, QIcon, QKeySequence`). `QLabel` and `QFrame` need to be added to the existing `QWidgets` import block.

- [ ] **Step 3: Update imports**

In `tools/loggereditor.py`, add `QFont` to the QtGui import (line 12) and `QLabel`, `QFrame` to the QtWidgets import (lines 13-22):

```python
from qgis.PyQt.QtGui import QCloseEvent, QFont, QIcon, QKeySequence

from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QShortcut,
    QVBoxLayout,
    QWidget,
)
```

Remove the inline `from qgis.PyQt.QtWidgets import QLabel, QFrame` from the `_setup_ref_dock` body.

- [ ] **Step 4: Update tests**

In `test/test_wlevels_calc_calibr.py`, lines 481-482 and 513-514 reference `calibrlogger.plot_logger_head` and `calibrlogger.normalize_head`. These attributes still exist (just created dynamically now instead of from the .ui file), so the tests should work without changes. Verify:

```bash
python3 -m pytest test/test_wlevels_calc_calibr.py -x -v 2>&1 | tail -30
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/loggereditor.py
git commit -m "feat: move all 6 plot-option checkboxes to reference series dock"
```

---

### Task 5: Replace adjust_trend.png with SVG

**Files:**
- Create: `icons/svg/adjust_trend.svg`
- Modify: `tools/loggereditor.py:2616-2618` — update icon path
- Delete: `icons/adjust_trend.png`

- [ ] **Step 1: Create the SVG icon**

Create `icons/svg/adjust_trend.svg`. The existing SVG icons use a 48×48mm viewBox (`viewBox="0 0 48 48"`), black strokes with `stroke-width:1.5`. The adjust trend icon should depict a trend line with an adjustment arrow:

```xml
<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<svg
   xmlns="http://www.w3.org/2000/svg"
   width="48mm"
   height="48mm"
   viewBox="0 0 48 48"
   version="1.1">
  <g transform="translate(0,-249)">
    <!-- Upward trend line -->
    <path
       style="fill:none;stroke:#000000;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round"
       d="M 5,290 L 20,275 L 30,280 L 43,265" />
    <!-- Adjustment arrow (vertical double-headed) -->
    <path
       style="fill:none;stroke:#000000;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round"
       d="M 36,270 L 36,286" />
    <!-- Arrow head top -->
    <path
       style="fill:#000000;stroke:#000000;stroke-width:0.8;stroke-linecap:round;stroke-linejoin:round"
       d="M 36,270 L 34,273 L 38,273 Z" />
    <!-- Arrow head bottom -->
    <path
       style="fill:#000000;stroke:#000000;stroke-width:0.8;stroke-linecap:round;stroke-linejoin:round"
       d="M 36,286 L 34,283 L 38,283 Z" />
  </g>
</svg>
```

- [ ] **Step 2: Update the icon path in AdjustTrendButton**

In `tools/loggereditor.py`, change line 2617 from:

```python
os.path.join(
    os.path.dirname(__file__), "..", "icons", "adjust_trend.png"
),
```

To:

```python
os.path.join(
    os.path.dirname(__file__), "..", "icons", "svg", "adjust_trend.svg"
),
```

- [ ] **Step 3: Delete the old PNG**

```bash
git rm icons/adjust_trend.png
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest test/test_wlevels_calc_calibr.py -x -v 2>&1 | tail -20
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add icons/svg/adjust_trend.svg tools/loggereditor.py
git commit -m "feat: replace adjust_trend.png with clean SVG icon"
```

---

### Task 6: Final Integration Test

**Files:**
- No new files

- [ ] **Step 1: Run the full test suite**

```bash
python3 -m pytest test/ -x -v 2>&1 | tail -40
```

Expected: All PASS with no regressions.

- [ ] **Step 2: Run ruff**

```bash
ruff check --fix tools/loggereditor.py && ruff format tools/loggereditor.py
```

- [ ] **Step 3: Commit any linting fixes**

```bash
git add tools/loggereditor.py
git diff --cached --stat
# Only commit if there are changes:
git commit -m "style: apply ruff formatting to loggereditor.py"
```
