> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-06-10 · modified: 2026-06-10 · archived: 2026-07-31

# Logger Editor Layout Overhaul & Bug Fix

**Date:** 2026-05-26
**Scope:** `tools/loggereditor.py`, `ui/calibr_logger_dialog_integrated.ui`, `icons/`

## 1. Bug Fix: NumPy Broadcasting Error

**Problem:** `_build_ts_recarray()` at line 510 wraps `line_keys` (a list of tuples) in `np.array(line_keys, dtype=object)`. NumPy interprets the uniform-length tuples as a 2D array with shape `(N, K)`, which cannot broadcast into the 1D recarray field of shape `(N,)`.

**Fix:** Assign the list directly without wrapping in `np.array()`:
```python
arr["line_key"] = line_keys
```
NumPy handles direct list assignment to an object-dtype recarray field without shape inference. Verified that both direct list assignment and element-wise approaches work; direct assignment is simplest.

## 2. Auto-Update on Obsid Change

**Problem:** The user must manually click "Update plot" after changing the obsid combobox. Forgetting causes stale-buffer errors (line 2120) and confusion.

**Change:**
- Add `self.update_plot()` at the end of `_on_obsid_changed()`. The method has four exit paths:
  1. **Not dirty** (line 1156 early return) — add `self.update_plot()` before the return.
  2. **Cancel** (line 1164 revert + return) — do NOT call `update_plot()` (user wants to stay on the current obsid).
  3. **Save succeeded** (line 1167) — falls through to the end, where `update_plot()` is added.
  4. **Discard** (line 1171) — falls through to the end, where `update_plot()` is added.
  5. **Save failed** (line 1168 revert + return) — do NOT call `update_plot()`.
- Remove `push_buttonupdateplot` from `calibr_logger_dialog_integrated.ui`.
- Remove the `clicked.connect` at line 157 and any remaining references.
- All other programmatic `update_plot()` calls remain unchanged.

## 3. "From Selection" Buttons in Period Section

**Problem:** The single "Fit period to selection" button below the plot sets both From and To simultaneously, but the period section convention is independent From/To control.

**Change:**
- Add a "From selection" button on the From row (third button, after "Select in plot" and "From current extent").
- Add a "From selection" button on the To row (same position).
- From-selection sets `from_date_time` to `min(selected_data.index)`.
- To-selection sets `to_date_time` to `max(selected_data.index)`.
- Both buttons are disabled when no lines are selected (same guard as the old single button).
- Remove the old `fit_period_btn` and its grid row.

**Placement in UI:** The existing period section in the `.ui` file has button rows using `QGridLayout` with "Select in plot" (col 0) and "From current extent" (col 1). Add the "From selection" buttons as col 2 in each button row. This is done in the `.ui` file XML directly (not dynamically).

**Implementation:** Split `_fit_period_to_selection()` into two methods: `_from_date_from_selection()` (sets `from_date_time` to `min(selected_data.index)`) and `_to_date_from_selection()` (sets `to_date_time` to `max(selected_data.index)`). Both use the same guard as the old `_fit_period_to_selection()`.

## 4. Checkboxes Moved to Reference Series Panel

**Problem:** Six checkboxes below the plot consume vertical space and feel cramped. The reference series panel has unused space.

**Change:**
- Remove from below-plot area (`grid_layout_7` in `.ui` file):
  - `logger_line_nodes` (Circle nodes for logger line)
  - `plot_logger_head` (Plot logger water head)
  - `normalize_head` (Normalize head to logger line)
  - Horizontal separator `line99`
- Remove dynamically-added checkboxes from `grid_layout_7`:
  - `separate_source_cb`
  - `separate_created_at_cb`
  - `separate_dt_precision_cb`
- Add all six checkboxes to the reference series dock widget (`_setup_ref_dock()`), in a single-column layout below the series list, under a "Plot options" QLabel header.
- The three `.ui`-defined checkboxes (`logger_line_nodes`, `plot_logger_head`, `normalize_head`) and the separator `line99` are removed from the `.ui` file. They are recreated dynamically in `_setup_ref_dock()` alongside the three separation checkboxes.
- Remove `horizontal_layout_2` and `grid_layout_7` from the `.ui` file (they will be empty after the checkboxes and Update plot button are removed).

**Tooltips** (added to each checkbox):
| Checkbox | Tooltip |
|---|---|
| Circle nodes for logger line | Show circle markers at each data point on the logger line |
| Plot logger water head | Plot the raw head_cm column as a separate line |
| Normalize head to logger line | Shift head_cm line so its mean matches level_masl mean (visual only, no DB change) |
| Separate by source | Draw separate lines per data source |
| Separate by import time | Draw separate lines per import timestamp |
| Separate by datetime precision | Draw separate lines per datetime string precision |

## 5. Adjust Trend Icon Replacement

**Problem:** `icons/adjust_trend.png` is a 24×24, 198-byte PNG that looks blurry and inconsistent with the other toolbar icons (which are SVGs like `move_nodes.svg`, `select_nodes.svg`).

**Change:**
- Create `icons/svg/adjust_trend.svg` — a clean vector icon depicting a trend line with an adjustment arrow, matching the visual style of the existing SVG icons (monochrome `#555` strokes, 16×16 viewBox).
- Update `AdjustTrendButton._button_setup` to reference the new SVG path.
- Delete `icons/adjust_trend.png`.

## Testing

- Existing tests that reference `push_buttonupdateplot` or `grid_layout_7` will need updating.
- The NumPy fix should be covered by existing `_build_ts_recarray` / `_compute_line_keys` tests — verify they pass with the change.
- No new database schema changes.
