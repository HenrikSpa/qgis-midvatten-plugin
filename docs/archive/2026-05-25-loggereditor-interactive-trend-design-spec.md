> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-06-10 · modified: 2026-06-10 · archived: 2026-07-31

# LoggerEditor Interactive Trend Adjustment

**Date:** 2026-05-25
**Status:** Draft

## Problem

The current trend adjustment in LoggerEditor requires the user to:
1. Click four separate buttons (l1, l2, m1, m2) and click on the plot for each to define old-trend and new-trend endpoints
2. Click "Adjust trend" to apply

This is 9+ clicks for a single drift correction. The m1/m2 button signals are broken, and even when working, the interaction model is unintuitive — users must understand the concept of "old trend vs new trend" as separate line pairs.

## Solution

Replace the 4-button trend tab with a direct-manipulation interaction:

1. **Select range** using the existing RectangleSelector
2. **Enter trend mode** via a new toolbar button — a trend line appears between the first and last selected data point with large draggable circle markers at both ends
3. **Drag an endpoint** vertically — the line pivots around the other endpoint
4. **Release** — the slope correction is applied to `level_masl` within the range, the trend line redraws at the corrected positions, and the user can drag again

## Workflow

### Step 1: Select Range

The user draws a rectangle on the plot using the existing `RectangleSelector` (the "Select nodes" toolbar button). This sets `from_date_time` / `to_date_time` and highlights selected nodes as it does today.

### Step 2: Enter Trend Mode

The user clicks a new **"Adjust Trend"** toolbar button (`AdjustTrendButton`, a `NavigationButton` subclass like the existing Select/Move/Cursor buttons).

This:
- Deactivates pan/zoom, select-nodes, move-nodes, and multi-cursor modes
- Draws a straight trend line from the first to the last selected data point
- Draws two large filled circle markers at both endpoints
- Connects pick/motion/release events for drag interaction

### Step 3: Drag Endpoint

The user grabs one circle marker and drags it vertically.

While dragging:
- Only the trend line and circles move — data points stay in place
- The non-dragged endpoint stays fixed (acts as pivot)
- The trend line rotates around the pivot

### Step 4: Release and Apply

On `button_release_event`:
1. Compute endpoint deltas: `Δ_start = new_start_y - original_start_y`, `Δ_end = new_end_y - original_end_y`
2. For each row in the selected range, interpolate the correction:
   `f = (row_epoch - start_epoch) / (end_epoch - start_epoch)`
   `level_masl += Δ_start * (1 - f) + Δ_end * f`
3. Push to history ("Adjust trend")
4. Redraw the plot with corrected data
5. Redraw the trend line + circles at the new corrected data positions

The trend line stays visible after applying, allowing the user to drag again for further adjustment.

### Step 5: Exit Trend Mode

Same mutual-exclusion pattern as move-nodes: trend mode and select-nodes mode are never active at the same time. To adjust a different range, exit trend mode first, select a new range, then re-enter trend mode.

The trend line and circles are removed when the user:
- Clicks the toolbar button again (toggles off)
- Switches to another mode (select-nodes, move-nodes, pan/zoom)

### Undo

The existing Ctrl+Z / undo button reverts the last correction via the history system.

## Visual Elements

### Trend Line
- Straight line from first to last selected data point on `self.axes`
- Style: dashed, red/orange color, zorder above data lines
- Artist type: `Line2D`

### Circle Markers (Endpoints)
- Two filled circles at the trend line endpoints
- Size: ~12pt marker, visible pick radius (~10px)
- Color: same as trend line
- `picker=True` for matplotlib pick events
- Artist type: `Line2D` with marker style (one per endpoint)

## Event Handling

### New Toolbar Button: `AdjustTrendButton`

Subclass of `NavigationButton` (like `SelectNodesButton`, `MoveNodesButton`, `MultiCursorButton`).

Toggle ON:
- Call `LoggerEditor.toggle_adjust_trend(on=True)`
- `self.reset_cid()` to disconnect any existing event handlers
- `self.deactivate_pan_zoom()`
- Uncheck select-nodes, move-nodes, and multi-cursor buttons
- `self.period_selector.set_active(False)`
- Draw trend line + circles
- Connect pick/motion/release events via `self.cid.append(self.canvas.mpl_connect(...))`

Toggle OFF:
- Call `LoggerEditor.toggle_adjust_trend(on=False)`
- Remove trend line + circles from axes
- `self.reset_cid()` disconnects events automatically (they're in `self.cid`)

**Mutual exclusion**: `toggle_select_nodes` and `toggle_move_nodes` must also call `self.adjust_trend_button.uncheck()` and `self._remove_trend_overlay()` to clear trend state when switching modes.

### Drag State

New attributes on `LoggerEditor`:
- `_trend_line`: the `Line2D` artist for the trend line (or `None`)
- `_trend_start_marker`: circle marker artist at start endpoint
- `_trend_end_marker`: circle marker artist at end endpoint
- `_trend_dragging`: `"start"` | `"end"` | `None`
- `_trend_original_start_y`: y-value of start before drag began
- `_trend_original_end_y`: y-value of end before drag began

### Event Handlers

**`_trend_pick(event)`**
- Check `event.artist is self._trend_start_marker` or `event.artist is self._trend_end_marker` (identity check, same pattern as `node_pressed` checks `event.artist is self.logger_artist`)
- Set `_trend_dragging` to `"start"` or `"end"` accordingly
- Store both current y-values as `_trend_original_start_y` / `_trend_original_end_y`

**`_trend_move(event)`**
- If `_trend_dragging` is `None`, return
- If `event.ydata` is `None` (mouse left axes), return — ignore off-canvas motion
- Compute new y for the dragged endpoint from `event.ydata`
- Update trend line ydata: pivot endpoint stays, dragged endpoint moves
- Update circle marker positions
- `canvas.draw_idle()`

**`_trend_release(event)`**
- If `_trend_dragging` is `None`, return
- Read current positions from the trend line/markers
- Compute endpoint deltas vs. stored originals
- `common_utils.start_waiting_cursor()`
- Apply correction to `self._buf.loc[mask, "level_masl"]` using the interpolation formula
- Log the adjustment via `MessagebarAndLog.info` (obsid, date range, Δ_start, Δ_end)
- `self._history_push("Adjust trend")`
- `common_utils.stop_waiting_cursor()`
- `self.update_plot()`
- Redraw trend line + circles at corrected positions (re-read the first and last selected points' `level_masl` from `_buf` to get the new endpoint y-values — these become the new "original" positions for subsequent drags)
- Clear `_trend_dragging`

## Math

```
start_epoch = (first_selected_datetime - utc_epoch).total_seconds()
end_epoch   = (last_selected_datetime  - utc_epoch).total_seconds()
span        = end_epoch - start_epoch

Δ_start = new_start_y - original_start_y
Δ_end   = new_end_y   - original_end_y

For each row in the selected range where level_masl is not null:
    row_epoch = (row_datetime - utc_epoch).total_seconds()
    f = (row_epoch - start_epoch) / span
    level_masl += Δ_start * (1 - f) + Δ_end * f
```

This linear interpolation of endpoint deltas is direction-agnostic — it gives the correct result regardless of which endpoint was dragged. When the start endpoint is the pivot (Δ_start=0), correction grows linearly from 0 to Δ_end. When the end endpoint is the pivot (Δ_end=0), correction is Δ_start at the start and tapers to 0. After release, the "original" positions reset to the corrected positions for the next drag.

## UI Changes

### Remove Old Trend Tab

Remove the "Adjust drift/trend" tab (`adjust_drift`) from the UI file (`calibr_logger_dialog_integrated.ui`). This removes:
- The `l1_button`, `l2_button`, `m1_button`, `m2_button` QPushButtons
- The `l1_date`, `l2_date`, `m1_date`, `m2_date` QDateTimeEdit fields
- The `l1_level`, `l2_level`, `m1_level`, `m2_level` QLineEdit fields
- The `adjust_trend_button` QPushButton
- The info label explaining the old formula

### Remove Old Trend Code

Remove from `loggereditor.py`:
- `set_adjust_data()` method
- `set_adjust_data_on_click()` method
- `adjust_trend_func()` method
- Signal connections for the four trend buttons in `__init__`
- Signal connection for `adjust_trend_button`

### Add Toolbar Button

Add `AdjustTrendButton` to the matplotlib toolbar, alongside the existing Select/Move/Cursor buttons. It should have a distinct icon or label (e.g., a small trend-line icon or the text "Trend").

### Add Trend Methods

New methods on `LoggerEditor`:
- `toggle_adjust_trend(on: bool)` — enter/exit trend mode
- `_draw_trend_overlay()` — create/update the trend line + circle artists
- `_remove_trend_overlay()` — remove trend artists from axes
- `_trend_pick(event: PickEvent)` — handle pick on circle marker
- `_trend_move(event)` — handle motion during drag
- `_trend_release(event)` — compute and apply correction on release

## Edge Cases

- **No selection**: if no range is selected when entering trend mode, show a status message and don't draw anything
- **Single point selected**: need at least 2 points with non-null level_masl for a trend line; show a message if not enough
- **Zero time span**: if first and last selected points have the same timestamp, slope is undefined; skip the correction
- **Null level_masl at endpoints**: use the first and last non-null level_masl points within the selection for the trend line endpoints

## Testing

- Unit test: slope correction math with known input/output values
- Unit test: edge cases (single point, zero span, null endpoints)
- Integration test: select range + drag + release flow using mock matplotlib events, verify `_buf["level_masl"]` is correctly adjusted
- Integration test: undo after trend adjustment restores original values
