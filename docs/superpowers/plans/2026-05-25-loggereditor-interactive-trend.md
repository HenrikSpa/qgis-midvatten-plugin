# LoggerEditor Interactive Trend Adjustment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the broken 4-button trend tab with a direct-manipulation drag-to-adjust-trend interaction on the matplotlib plot.

**Architecture:** New `AdjustTrendButton` (NavigationButton subclass) toggles trend mode. In trend mode, a trend line + two draggable circle markers appear between the first and last selected data points. Dragging an endpoint vertically and releasing applies a linearly interpolated correction to `level_masl` in the selected range. Same mutual-exclusion pattern as move-nodes: select range first, then enter trend mode.

**Tech Stack:** Python 3, matplotlib (Line2D, PickEvent, mpl_connect), pandas DataFrame, PyQt5/6 (QAction), QGIS plugin infrastructure.

**Spec:** `docs/superpowers/specs/2026-05-25-loggereditor-interactive-trend-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `tools/loggereditor.py` | Add trend methods, AdjustTrendButton class, wire mutual exclusion, remove old trend code |
| Modify | `ui/calibr_logger_dialog_integrated.ui` | Remove the `adjust_drift` tab (old trend UI) |
| Modify | `test/test_wlevels_calc_calibr.py` | Replace old `test_calibrlogger_adjust_trend` with new interactive trend tests |
| Create | `icons/adjust_trend.png` | Toolbar icon for the trend button |

---

### Task 1: Unit-test the trend correction math

The core correction formula is pure math with no UI dependency. Test it first as a standalone function.

**Files:**
- Create: `test/test_trend_correction.py`
- Create (stub): `tools/trend_math.py`

- [ ] **Step 1: Write failing tests for the correction math**

Create `test/test_trend_correction.py`:

```python
import datetime

import numpy as np
import pandas as pd
import pytest


def test_drag_end_up():
    """Drag end endpoint up by 10; start stays fixed (pivot).
    
    Correction should be 0 at start, +10 at end, linear in between.
    """
    from midvatten.tools.trend_math import apply_trend_correction

    index = pd.to_datetime(["2017-02-01", "2017-02-05", "2017-02-10"]).to_pydatetime()
    buf = pd.DataFrame({"level_masl": [100.0, 150.0, 200.0]}, index=index)

    original_start_y = 100.0
    original_end_y = 200.0
    new_start_y = 100.0  # pivot — unchanged
    new_end_y = 210.0  # dragged up by 10

    apply_trend_correction(buf, original_start_y, original_end_y, new_start_y, new_end_y)

    expected = [100.0, 155.0, 210.0]  # +0, +5, +10
    np.testing.assert_allclose(buf["level_masl"].values, expected, atol=1e-10)


def test_drag_start_down():
    """Drag start endpoint down by 6; end stays fixed (pivot).
    
    Correction should be -6 at start, 0 at end, linear in between.
    """
    from midvatten.tools.trend_math import apply_trend_correction

    index = pd.to_datetime(["2017-02-01", "2017-02-05", "2017-02-10"]).to_pydatetime()
    buf = pd.DataFrame({"level_masl": [100.0, 150.0, 200.0]}, index=index)

    apply_trend_correction(buf, 100.0, 200.0, 94.0, 200.0)

    # f values: 0/9=0.0, 4/9≈0.4444, 9/9=1.0
    # corrections: -6*(1-0)+0*0=-6, -6*(1-4/9)+0=-10/3, -6*0+0*1=0
    expected = [94.0, 150.0 - 6.0 * 5 / 9, 200.0]
    np.testing.assert_allclose(buf["level_masl"].values, expected, atol=1e-10)


def test_drag_both_endpoints():
    """Both endpoints moved — start up by 2, end down by 3."""
    from midvatten.tools.trend_math import apply_trend_correction

    index = pd.to_datetime(["2017-02-01", "2017-02-10"]).to_pydatetime()
    buf = pd.DataFrame({"level_masl": [100.0, 200.0]}, index=index)

    apply_trend_correction(buf, 100.0, 200.0, 102.0, 197.0)

    expected = [102.0, 197.0]  # +2 at start, -3 at end
    np.testing.assert_allclose(buf["level_masl"].values, expected, atol=1e-10)


def test_null_level_masl_skipped():
    """Rows with NaN level_masl should not be modified."""
    from midvatten.tools.trend_math import apply_trend_correction

    index = pd.to_datetime(["2017-02-01", "2017-02-05", "2017-02-10"]).to_pydatetime()
    buf = pd.DataFrame({"level_masl": [100.0, np.nan, 200.0]}, index=index)

    apply_trend_correction(buf, 100.0, 200.0, 100.0, 210.0)

    assert buf["level_masl"].values[0] == pytest.approx(100.0)
    assert pd.isna(buf["level_masl"].values[1])
    assert buf["level_masl"].values[2] == pytest.approx(210.0)


def test_zero_time_span_no_change():
    """If start and end have the same timestamp, correction is skipped (no division by zero)."""
    from midvatten.tools.trend_math import apply_trend_correction

    index = pd.to_datetime(["2017-02-01", "2017-02-01"]).to_pydatetime()
    buf = pd.DataFrame({"level_masl": [100.0, 200.0]}, index=index)

    apply_trend_correction(buf, 100.0, 200.0, 110.0, 210.0)

    np.testing.assert_allclose(buf["level_masl"].values, [100.0, 200.0], atol=1e-10)


def test_single_point_no_crash():
    """Single-point selection: no crash, no change (start==end timestamp)."""
    from midvatten.tools.trend_math import apply_trend_correction

    index = pd.to_datetime(["2017-02-01"]).to_pydatetime()
    buf = pd.DataFrame({"level_masl": [100.0]}, index=index)

    apply_trend_correction(buf, 100.0, 100.0, 110.0, 110.0)

    np.testing.assert_allclose(buf["level_masl"].values, [100.0], atol=1e-10)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest test/test_trend_correction.py -v`
Expected: All 6 tests FAIL with `ModuleNotFoundError: No module named 'midvatten.tools.trend_math'`

- [ ] **Step 3: Implement the correction function**

Create `tools/trend_math.py`:

```python
import datetime

import pandas as pd


_UTC_EPOCH = datetime.datetime(1970, 1, 1)


def apply_trend_correction(
    buf: pd.DataFrame,
    original_start_y: float,
    original_end_y: float,
    new_start_y: float,
    new_end_y: float,
) -> bool:
    """Apply a linearly interpolated trend correction to buf["level_masl"] in-place.

    Returns True if a correction was applied, False if skipped (zero time span).
    """
    mask = buf["level_masl"].notna()
    if mask.sum() < 2:
        return False

    start_dt = buf.index[0]
    end_dt = buf.index[-1]
    start_epoch = (start_dt - _UTC_EPOCH).total_seconds()
    end_epoch = (end_dt - _UTC_EPOCH).total_seconds()
    span = end_epoch - start_epoch

    if span == 0:
        return False

    delta_start = new_start_y - original_start_y
    delta_end = new_end_y - original_end_y

    row_epochs = buf.index.map(lambda dt: (dt - _UTC_EPOCH).total_seconds())
    f = (row_epochs - start_epoch) / span
    correction = delta_start * (1 - f) + delta_end * f
    buf.loc[mask, "level_masl"] += correction[mask]
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest test/test_trend_correction.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add test/test_trend_correction.py tools/trend_math.py
git commit -m "feat(loggereditor): add trend correction math with tests

TDD: direction-agnostic linear interpolation of endpoint deltas."
```

---

### Task 2: Remove old trend tab from UI file

**Files:**
- Modify: `ui/calibr_logger_dialog_integrated.ui`

- [ ] **Step 1: Identify the `adjust_drift` widget boundaries**

The `adjust_drift` widget starts at line 1161. It is a tab inside the `QTabWidget` named `tab_widget`. The entire `<widget class="QWidget" name="adjust_drift">...</widget>` block must be removed, including its `<attribute name="title">` and all 26 nested widgets (l1_button, l2_button, m1_button, m2_button, l1_date, l2_date, m1_date, m2_date, l1_level, l2_level, m1_level, m2_level, adjust_trend_button, etc.).

- [ ] **Step 2: Remove the `adjust_drift` widget block from the UI file**

Use an XML-aware approach. Find the line `<widget class="QWidget" name="adjust_drift">` and remove everything through its matching `</widget>` closing tag. The block is roughly lines 1161–1811 (the `adjust_trend_button` widget's closing tag is the last nested element, and the outer `</widget>` follows).

To do this precisely, use Python:

```python
import xml.etree.ElementTree as ET

tree = ET.parse("ui/calibr_logger_dialog_integrated.ui")
root = tree.getroot()

# Find the tab_widget, then remove adjust_drift from it
for tab_widget in root.iter("widget"):
    if tab_widget.get("name") == "tab_widget":
        for child in list(tab_widget):
            if child.tag == "widget" and child.get("name") == "adjust_drift":
                tab_widget.remove(child)
                break
        break

tree.write("ui/calibr_logger_dialog_integrated.ui", xml_declaration=True, encoding="UTF-8")
```

Then verify the file still loads by checking it is valid XML.

- [ ] **Step 3: Verify the UI file is valid**

Run: `python3 -c "import xml.etree.ElementTree as ET; ET.parse('ui/calibr_logger_dialog_integrated.ui'); print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add ui/calibr_logger_dialog_integrated.ui
git commit -m "refactor(ui): remove old adjust_drift tab from logger dialog

The 4-button trend UI (l1/l2/m1/m2) is replaced by interactive toolbar trend."
```

---

### Task 3: Remove old trend code from loggereditor.py

**Files:**
- Modify: `tools/loggereditor.py`

- [ ] **Step 1: Remove old signal connections**

In `__init__` (around lines 111–122 and 144), remove these signal connections:

```python
# REMOVE these lines:
self.l1_button.clicked.connect(
    lambda x: self.set_adjust_data("l1_date", "l1_level")
)
self.l2_button.clicked.connect(
    lambda x: self.set_adjust_data("L2_date", "l2_level")
)
self.m1_button.clicked.connect(
    lambda x: self.set_adjust_data("M1_date", "M1_level")
)
self.m2_button.clicked.connect(
    lambda x: self.set_adjust_data("M2_date", "M2_level")
)
# ...
self.adjust_trend_button.clicked.connect(lambda x: self.adjust_trend_func())
```

- [ ] **Step 2: Remove old trend methods**

Remove these three methods entirely:

1. `set_adjust_data(self, date_holder, level_holder)` — around lines 1864–1876
2. `set_adjust_data_on_click(self, event, date_var, level_var)` — around lines 1878–1882
3. `adjust_trend_func(self)` — around lines 1884–1960

- [ ] **Step 3: Run existing tests to verify nothing breaks**

Run: `python3 -m pytest test/test_wlevels_calc_calibr.py -v -x`
Expected: The two `test_calibrlogger_adjust_trend` tests will FAIL because `adjust_trend_func` no longer exists. All other tests should PASS. This is expected — we will replace these tests in Task 6.

- [ ] **Step 4: Commit**

```bash
git add tools/loggereditor.py
git commit -m "refactor(loggereditor): remove old 4-button trend code

Removes set_adjust_data, set_adjust_data_on_click, adjust_trend_func,
and their signal connections. The old UI tab was removed in the prior commit."
```

---

### Task 4: Create toolbar icon and AdjustTrendButton class

**Files:**
- Create: `icons/adjust_trend.png`
- Modify: `tools/loggereditor.py`

- [ ] **Step 1: Create a simple trend-line icon**

Create a 24×24 PNG icon showing a diagonal trend line. Use Python + PIL or matplotlib to generate it:

```python
from PIL import Image, ImageDraw

img = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)
# Diagonal line from bottom-left to top-right
draw.line([(3, 20), (21, 4)], fill=(220, 80, 40, 255), width=3)
# Circles at endpoints
draw.ellipse([(0, 17), (6, 23)], fill=(220, 80, 40, 255))
draw.ellipse([(18, 1), (24, 7)], fill=(220, 80, 40, 255))
img.save("icons/adjust_trend.png")
```

- [ ] **Step 2: Add the `AdjustTrendButton` class**

Add after the `MultiCursorButton` class (around line 2145 in the current file, but line numbers will have shifted after Task 3 removals). Place it just before the `_iter_filter_combos` function:

```python
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
```

- [ ] **Step 3: Instantiate `AdjustTrendButton` in `LoggerEditor.show()`**

In `show()`, after `self.multi_cursor_button = MultiCursorButton(...)` (currently line 204), add:

```python
self.adjust_trend_button = AdjustTrendButton(self, self.calibrplotfigure)
```

- [ ] **Step 4: Add `toggle_adjust_trend` stub and trend state attributes**

In `__init__`, after `self.cid = []` (line 105), add initial state:

```python
self._trend_line = None
self._trend_start_marker = None
self._trend_end_marker = None
self._trend_dragging = None
self._trend_original_start_y = None
self._trend_original_end_y = None
```

Add the `toggle_adjust_trend` method on `LoggerEditor`, near the existing `toggle_move_nodes` / `toggle_select_nodes` methods:

```python
def toggle_adjust_trend(self, on: bool):
    if on:
        self.reset_cid()
        self.deactivate_pan_zoom()
        self.period_selector.set_active(False)
        self.select_nodes_button.uncheck()
        self.move_nodes_button.uncheck()
        self._draw_trend_overlay()
    else:
        self._remove_trend_overlay()
```

Add stubs for `_draw_trend_overlay` and `_remove_trend_overlay` so nothing crashes:

```python
def _draw_trend_overlay(self):
    pass

def _remove_trend_overlay(self):
    for attr in ("_trend_line", "_trend_start_marker", "_trend_end_marker"):
        artist = getattr(self, attr, None)
        if artist is not None:
            try:
                artist.remove()
            except ValueError:
                pass  # already detached by axes.clear()
            setattr(self, attr, None)
    self._trend_dragging = None
```

- [ ] **Step 5: Wire mutual exclusion into existing toggle methods**

Update `toggle_select_nodes` — add `self.adjust_trend_button.uncheck()` and `self._remove_trend_overlay()`:

```python
def toggle_select_nodes(self, on):
    if on:
        self.reset_cid()
        self.deactivate_pan_zoom()
        self.move_nodes_button.uncheck()
        self.adjust_trend_button.uncheck()
        self._remove_trend_overlay()
    self.period_selector.set_active(on)
```

Update `toggle_move_nodes` — add `self.adjust_trend_button.uncheck()` and `self._remove_trend_overlay()`:

```python
def toggle_move_nodes(self, on):
    if on:
        self.reset_cid()
        self.deactivate_pan_zoom()
        self.period_selector.set_active(False)
        self.select_nodes_button.uncheck()
        self.adjust_trend_button.uncheck()
        self._remove_trend_overlay()
        self.connect_selected_line_move()
```

- [ ] **Step 6: Run tests to verify nothing breaks**

Run: `python3 -m pytest test/test_wlevels_calc_calibr.py -v -x -k "not adjust_trend"`
Expected: All non-trend tests PASS

- [ ] **Step 7: Commit**

```bash
git add icons/adjust_trend.png tools/loggereditor.py
git commit -m "feat(loggereditor): add AdjustTrendButton with toggle and mutual exclusion

Toolbar button toggles trend mode. Stubs for overlay draw/remove.
Mutual exclusion wired between select-nodes, move-nodes, and adjust-trend."
```

---

### Task 5: Implement trend overlay drawing and drag interaction

**Files:**
- Modify: `tools/loggereditor.py`

- [ ] **Step 1: Implement `_draw_trend_overlay`**

Replace the stub with the real implementation. This method reads the first and last selected data points from `_buf` and draws the trend line + circle markers:

```python
def _draw_trend_overlay(self):
    self._remove_trend_overlay()
    self.reset_cid()

    if self._buf is None or self.logger_artist is None:
        self.statusbar.showMessage(
            QCoreApplication.translate("Calibrlogger", "No data loaded."), 5000,
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
    self.cid.append(self.canvas.mpl_connect("motion_notify_event", self._trend_move))
    self.cid.append(
        self.canvas.mpl_connect("button_release_event", self._trend_release)
    )
    self.canvas.draw_idle()
```

- [ ] **Step 2: Implement `_trend_pick`**

```python
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
```

- [ ] **Step 3: Implement `_trend_move`**

```python
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
```

- [ ] **Step 4: Implement `_trend_release`**

```python
def _trend_release(self, event):
    if self._trend_dragging is None:
        return

    new_start_y = self._trend_start_marker.get_ydata()[0]
    new_end_y = self._trend_end_marker.get_ydata()[0]
    original_start_y = self._trend_original_start_y
    original_end_y = self._trend_original_end_y
    self._trend_dragging = None

    if new_start_y == original_start_y and new_end_y == original_end_y:
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

    from midvatten.tools.trend_math import apply_trend_correction

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
```

`update_plot()` re-toggles trend mode via the re-toggle line added in Step 5, which calls `_draw_trend_overlay()` with the corrected `_buf` values.

Note: `_draw_trend_overlay` includes `self.reset_cid()` so old event connections are cleaned up before reconnecting. Since `update_plot()` calls `axes.clear()` (which detaches all artists) and `reset_plot_selects_and_calib_help()` (which calls `reset_cid()`), by the time we enter `_draw_trend_overlay` the old artists are already detached — `_remove_trend_overlay`'s try/except handles that gracefully.

- [ ] **Step 5: Add trend mode re-toggle to `update_plot`**

`update_plot()` already re-toggles move-nodes and select-nodes after redrawing (lines 1120-1121). Add the same for adjust-trend. After the existing lines:

```python
self.toggle_move_nodes(self.move_nodes_button.button().isChecked())
self.toggle_select_nodes(self.select_nodes_button.button().isChecked())
```

Add:

```python
if hasattr(self, "adjust_trend_button"):
    self.toggle_adjust_trend(self.adjust_trend_button.button().isChecked())
```

The `hasattr` guard is needed because `update_plot` can be called from `show()` before the toolbar buttons are created.

With this change, `_trend_release` no longer needs to call `_draw_trend_overlay()` at the end — `update_plot()` will re-toggle trend mode which calls `toggle_adjust_trend(True)` → `_draw_trend_overlay()`. Remove the final `self._draw_trend_overlay()` call from `_trend_release`.

- [ ] **Step 6: Run the math tests to verify they still pass**

Run: `python3 -m pytest test/test_trend_correction.py -v`
Expected: All 6 tests PASS

- [ ] **Step 7: Commit**

```bash
git add tools/loggereditor.py
git commit -m "feat(loggereditor): implement trend overlay draw and drag interaction

Trend line + circle markers appear on selected range. Drag endpoint
vertically, release to apply linearly interpolated correction.
update_plot re-toggles trend mode like move/select nodes."
```

---

### Task 6: Replace old integration tests with new trend tests

**Files:**
- Modify: `test/test_wlevels_calc_calibr.py`

The old `test_calibrlogger_adjust_trend` tests in both `CalibrloggerSpatialiteMixin` and `CalibrloggerPostgisMixin` (they share the same structure) set up l1/l2/m1/m2 dates and levels and call `adjust_trend_func()`. We need to replace them with tests that exercise the new interactive trend flow.

The old test scenario:
- Two points: `rb1` at 2017-02-01 level=100, 2017-02-10 level=200
- Old trend: l1=(2017-02-01, 100), l2=(2017-02-10, 200) → slope 100/9days
- New trend: m1=(2017-02-01, 200), m2=(2017-02-10, 100) → slope -100/9days
- Result: level_masl at 2017-02-10 goes from 200 to ~0 (the old slope minus new slope correction)

The **equivalent new-style interaction** would be: the user sees the trend line from (2017-02-01, 100) to (2017-02-10, 200), then drags the start endpoint to 200 and the end endpoint to 100 — inverting the trend. Let's verify the math:
- `Δ_start = 200 - 100 = +100`, `Δ_end = 100 - 200 = -100`
- At start (f=0): `+100*(1-0) + (-100)*0 = +100` → 100+100 = 200
- At end (f=1): `+100*0 + (-100)*1 = -100` → 200-100 = 100
- So final: [200, 100] — a perfect inversion

But the old test expected [100, ~0]. That's because the old formula was different (it computed slope difference using two separate line pairs and subtracted). The new formula gives a different but correct result — the user's intent is different (they're directly placing endpoints where they want them).

We need a **new reference** that matches the new formula's behavior.

- [ ] **Step 1: Replace the old SpatiaLite trend test**

In `CalibrloggerSpatialiteMixin`, replace `test_calibrlogger_adjust_trend` with:

```python
@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_calibrlogger_adjust_trend(self, mock_messagebar):
    """Interactive trend: drag start up by 5, end stays (pivot)."""
    db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
    db_utils.sql_alter_db(
        "INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('rb1', '2017-02-01 00:00', 100)"
    )
    db_utils.sql_alter_db(
        "INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('rb1', '2017-02-10 00:00', 200)"
    )

    calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
    calibrlogger.show()
    gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")
    calibrlogger.update_plot()
    calibrlogger.from_date_time.setDateTime(
        date_utils.datestring_to_date("2000-01-01 00:00:00")
    )
    calibrlogger.to_date_time.setDateTime(
        date_utils.datestring_to_date("2099-12-31 23:59:59")
    )

    from midvatten.tools.trend_math import apply_trend_correction

    # Simulate: user sees trend from 100 to 200, drags start up to 105
    apply_trend_correction(calibrlogger._buf, 100.0, 200.0, 105.0, 200.0)
    calibrlogger._history_push("Adjust trend")
    calibrlogger.save_to_db()

    res = db_utils.sql_load_fr_db(
        "SELECT obsid, date_time, level_masl FROM w_levels_logger ORDER BY date_time"
    )
    print(f"{mock_messagebar.mock_calls=}")
    # Δ_start=+5, Δ_end=0. At start (f=0): +5. At end (f=1): 0.
    test = utils_for_tests.create_test_string(res)
    ref = "(True, [(rb1, 2017-02-01 00:00, 105.0), (rb1, 2017-02-10 00:00, 200.0)])"
    assert test == ref
```

- [ ] **Step 2: Replace the old PostGIS trend test**

In the PostGIS mixin class (around line 803), replace `test_calibrlogger_adjust_trend` with the same test body as Step 1 (they share the same logic — the only difference is the database backend, which is handled by the test class hierarchy).

```python
@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_calibrlogger_adjust_trend(self, mock_messagebar):
    """Interactive trend: drag start up by 5, end stays (pivot)."""
    db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
    db_utils.sql_alter_db(
        "INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('rb1', '2017-02-01 00:00', 100)"
    )
    db_utils.sql_alter_db(
        "INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('rb1', '2017-02-10 00:00', 200)"
    )

    calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
    calibrlogger.show()
    gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")
    calibrlogger.update_plot()
    calibrlogger.from_date_time.setDateTime(
        date_utils.datestring_to_date("2000-01-01 00:00:00")
    )
    calibrlogger.to_date_time.setDateTime(
        date_utils.datestring_to_date("2099-12-31 23:59:59")
    )

    from midvatten.tools.trend_math import apply_trend_correction

    apply_trend_correction(calibrlogger._buf, 100.0, 200.0, 105.0, 200.0)
    calibrlogger._history_push("Adjust trend")
    calibrlogger.save_to_db()

    res = db_utils.sql_load_fr_db(
        "SELECT obsid, date_time, level_masl FROM w_levels_logger ORDER BY date_time"
    )
    print(f"{mock_messagebar.mock_calls=}")
    test = utils_for_tests.create_test_string(res)
    ref = "(True, [(rb1, 2017-02-01 00:00, 105.0), (rb1, 2017-02-10 00:00, 200.0)])"
    assert test == ref
```

- [ ] **Step 3: Add an undo integration test to the SpatiaLite mixin**

Add a new test method:

```python
@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_calibrlogger_adjust_trend_undo(self, mock_messagebar):
    """Undo should restore level_masl to pre-trend values."""
    db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
    db_utils.sql_alter_db(
        "INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('rb1', '2017-02-01 00:00', 100)"
    )
    db_utils.sql_alter_db(
        "INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('rb1', '2017-02-10 00:00', 200)"
    )

    calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
    calibrlogger.show()
    gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")
    calibrlogger.update_plot()
    calibrlogger.from_date_time.setDateTime(
        date_utils.datestring_to_date("2000-01-01 00:00:00")
    )
    calibrlogger.to_date_time.setDateTime(
        date_utils.datestring_to_date("2099-12-31 23:59:59")
    )

    from midvatten.tools.trend_math import apply_trend_correction

    original_values = calibrlogger._buf["level_masl"].copy()
    apply_trend_correction(calibrlogger._buf, 100.0, 200.0, 120.0, 180.0)
    calibrlogger._history_push("Adjust trend")

    # Undo
    calibrlogger.undo()

    print(f"{mock_messagebar.mock_calls=}")
    assert (calibrlogger._buf["level_masl"] == original_values).all()
```

- [ ] **Step 4: Add an event-handler integration test to the SpatiaLite mixin**

This test exercises the full user-facing flow: toggle trend mode → pick marker → drag → release → verify `_buf` is corrected and trend overlay is redrawn.

```python
@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_calibrlogger_adjust_trend_drag_flow(self, mock_messagebar):
    """Full event-handler flow: enter trend mode, pick, drag, release."""
    from unittest.mock import MagicMock
    from matplotlib.backend_bases import PickEvent

    db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
    db_utils.sql_alter_db(
        "INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('rb1', '2017-02-01 00:00', 100)"
    )
    db_utils.sql_alter_db(
        "INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('rb1', '2017-02-10 00:00', 200)"
    )

    calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
    calibrlogger.show()
    gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")
    calibrlogger.update_plot()
    calibrlogger.from_date_time.setDateTime(
        date_utils.datestring_to_date("2000-01-01 00:00:00")
    )
    calibrlogger.to_date_time.setDateTime(
        date_utils.datestring_to_date("2099-12-31 23:59:59")
    )

    # Enter trend mode
    calibrlogger.adjust_trend_button.button().setChecked(True)
    calibrlogger.toggle_adjust_trend(True)
    assert calibrlogger._trend_start_marker is not None
    assert calibrlogger._trend_end_marker is not None

    # Simulate pick on start marker
    mouse_event = MagicMock()
    mouse_event.button = 1
    pick_event = MagicMock(spec=PickEvent)
    pick_event.artist = calibrlogger._trend_start_marker
    calibrlogger._trend_pick(pick_event)
    assert calibrlogger._trend_dragging == "start"

    # Simulate drag: move start endpoint up by 5
    motion_event = MagicMock()
    motion_event.ydata = 105.0
    calibrlogger._trend_move(motion_event)

    # Simulate release
    release_event = MagicMock()
    calibrlogger._trend_release(release_event)

    # Verify correction applied
    print(f"{mock_messagebar.mock_calls=}")
    assert calibrlogger._buf["level_masl"].iloc[0] == pytest.approx(105.0)
    assert calibrlogger._buf["level_masl"].iloc[1] == pytest.approx(200.0)

    # Verify trend overlay was redrawn (not stale/crashed)
    assert calibrlogger._trend_line is not None
    assert calibrlogger._trend_start_marker is not None
```

- [ ] **Step 5: Run the trend-related tests**

Run: `python3 -m pytest test/test_wlevels_calc_calibr.py -v -x -k "adjust_trend"`
Expected: All trend tests PASS (SpatiaLite and PostGIS)

Run: `python3 -m pytest test/test_trend_correction.py -v`
Expected: All 6 unit tests PASS

- [ ] **Step 6: Commit**

```bash
git add test/test_wlevels_calc_calibr.py
git commit -m "test(loggereditor): replace old trend tests with interactive trend tests

Tests exercise apply_trend_correction on _buf, event handler flow, and undo."
```

---

### Task 7: Run full test suite and fix any regressions

**Files:**
- Possibly modify: `tools/loggereditor.py`, `test/test_wlevels_calc_calibr.py`

- [ ] **Step 1: Run full test suite**

Run: `python3 -m pytest test/ -x -v`
Expected: All tests PASS. If any fail, investigate and fix.

Common failure modes to watch for:
- Tests that reference `self.l1_button`, `self.l2_button`, etc. (removed UI widgets) — these would fail at `LoggerEditor.__init__` because `uic.loadUi` no longer creates those attributes. The signal connections were removed in Task 3, but if any other code references these widgets, it will need cleanup.
- Tests that call `adjust_trend_func()` — should have been replaced in Task 6.

- [ ] **Step 2: Run ruff**

Run: `ruff check --fix tools/loggereditor.py tools/trend_math.py test/test_trend_correction.py test/test_wlevels_calc_calibr.py && ruff format tools/loggereditor.py tools/trend_math.py test/test_trend_correction.py test/test_wlevels_calc_calibr.py`
Expected: No errors

- [ ] **Step 3: Fix any issues found, re-run tests**

If ruff or tests flagged anything, fix it and re-run: `python3 -m pytest test/ -x -v`

- [ ] **Step 4: Commit any fixes**

```bash
git add -u
git commit -m "fix: address regressions and lint from trend refactor"
```

---

## Summary of Changes

| Task | What | Risk |
|------|------|------|
| 1 | Pure math function + tests (no UI) | None — isolated |
| 2 | Remove UI tab from .ui file | Low — just XML removal |
| 3 | Remove old Python trend code | Medium — must catch all references |
| 4 | Add toolbar button + toggle + mutual exclusion | Medium — wiring between modes |
| 5 | Implement drag interaction | Medium — matplotlib event handling |
| 6 | Replace integration tests | Low — new tests for new behavior |
| 7 | Full suite regression check | Catch-all |
