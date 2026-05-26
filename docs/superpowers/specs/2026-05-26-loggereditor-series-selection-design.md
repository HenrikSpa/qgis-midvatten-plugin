# Logger Editor: Series Selection & Separation Controls

## Problem

The logger editor separates data into lines by `source`, but edit operations (set position, add offset, delete, set null, trend adjust) apply to **all** data in the selected period regardless of which series the points belong to. Users cannot target a specific series for editing. Additionally, there is no way to separate lines by import session (`created_at`) or datetime precision, which would help identify and remove bad imports.

## Design

### Stackable Separation Toggles

Three checkboxes in the left control panel:

| Checkbox | Default | Composite key contribution |
|----------|---------|---------------------------|
| Separate by source | ON | `source` (from `w_logger_series.source` or `w_levels_logger.source`) |
| Separate by created_at | OFF | `created_at` timestamp (possibly grouped) |
| Separate by datetime precision | OFF | `LENGTH(date_time)` — distinguishes resolution (10=date-only, 16=minute `YYYY-MM-DD HH:MM`, 19=second `YYYY-MM-DD HH:MM:SS`). Timezone suffixes or microseconds produce additional groups. |

When multiple are checked, each line represents a unique combination of the active dimensions. Legend labels adapt to show the active dimensions, e.g. `"source=Diver, imported=2024-03-15 14:22:00"`.

**Data loading:** The SQL query adds `created_at` and `LENGTH(date_time)` to the SELECT when those separations are enabled. The in-memory buffer (`_buf`) gains a `_line_key` column — a tuple built from whichever dimensions are active.

### created_at Warning & Auto-Grouping

When enabling "Separate by created_at", count distinct values for the current obsid first.

**<= 10 distinct values:** Proceed normally.

**> 10 distinct values:** Show a dialog:

> "Found N distinct import timestamps. This may clutter the plot."

Options:
- **Group by hour** — truncate `created_at` to `YYYY-MM-DD HH:00:00`
- **Group by day** — truncate to `YYYY-MM-DD`
- **Continue without grouping** — use all N as-is
- **Cancel** — uncheck the toggle

Grouping is in-memory only (no DB changes).

**Batched plot creation:** When the total number of lines across all active separation dimensions exceeds 15, draw lines incrementally with a progress indicator and abort button. Abort reverts the most recently changed toggle and restores the previous plot.

### Line Selection via LegendPicker

Port dynplot's `LegendPicker` class (`dynplot/utils/matplotlib_utils.py`) to the logger editor.

**Click behavior:**
- **Click** legend entry or plot line: select only that line (others dim to 0.2 alpha)
- **Click** the sole selected line: deselect (all return to full opacity)
- **Ctrl+Click**: toggle add/remove from multi-selection

**Visual feedback:**
- Selected lines: alpha 1.0
- Unselected lines: alpha 0.2
- Both legend entries and plot lines dim together

**Integration with editing:**
- **No lines selected:** edits apply to all data in the period (current behavior, unchanged)
- **Lines selected:** edits apply only to selected lines within the period
- The `plot_or_update_selected_line()` overlay respects line selection — only highlights selected lines' points in the period

### "Fit Period to Selection" Button

A new button near the from/to date controls.

- Enabled only when one or more lines are selected via LegendPicker
- Sets `from_date_time` and `to_date_time` to the min/max `date_time` of selected lines' data
- Triggers normal plot update

Greyed out when no lines are selected.

### Edit Operation Filtering

All five edit operations gain a series filter when lines are selected.

**In-memory filtering:** Edit masks add `& self._buf["_line_key"].isin(selected_keys)` when lines are selected. No additional filter when nothing is selected. `_line_key` is recomputed whenever a separation toggle changes and on data reload (`load_obsid_and_init`).

**SQL generation in `_compute_update_statements()`:**
- Range-based UPDATE paths (set position, add offset, set null) extend the WHERE clause:
  - Source: `AND series_id IN (?, ...)` (series_join schema) or `AND source IN (?, ...)` (source_col schema) — uses IN for multi-line selection via Ctrl+Click
  - created_at: `AND created_at IN (?, ...)` (exact values) or `AND created_at BETWEEN ? AND ?` (grouped by hour/day bounds). Grouped-line edits affect all underlying timestamps inside the group.
  - Datetime precision: no SQL filter needed (derived, not stored); per-row fallback handles it
- Per-row paths (delete, trend adjust) inherently filter correctly since only modified rows are saved. Source/created_at filters added as defense-in-depth.

**Schema compatibility:**
- `no_source` schema: source separation checkbox is disabled with tooltip "Source column not available in this database". Same as today — all data as one line.
- `source_col` schema: source filter uses `AND source = ?` directly. May lack `created_at` column.
- `series_join` schema: source filter uses `AND series_id = ?` via the join.
- **created_at may be absent** on older databases that haven't run the upgrade migration. Before enabling "Separate by created_at", check whether the column exists (same pattern as the importer: `"created_at" in column_list`). If missing, disable the checkbox and show a tooltip explaining the column is not available in this database.
- Datetime precision (`LENGTH(date_time)`) works on all schemas since `date_time` is always present.

## Out of Scope

- Persisting separation toggle state across sessions
- Separation by any other dimension (e.g., instrument, head_cm range)
- Changes to the database schema
