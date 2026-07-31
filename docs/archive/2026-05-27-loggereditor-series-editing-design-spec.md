> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-06-10 · modified: 2026-06-10 · archived: 2026-07-31

# Logger Editor: Series Editing via "Series" Tab

**Date:** 2026-05-27
**Status:** Draft

## Context

The `w_logger_series` table was recently added to group logger data by import batch, enabling batch-level metadata (source, instrument, description, comment) and batch revert. Currently the logger editor reads series info only for visualization (coloring lines by source) but provides no way to create, edit, or reassign series.

Users need to annotate logger data provenance — for example, when a segment of data clearly came from a different physical logger or was imported from a different file. They should be able to select a period in the plot and assign it to a new or existing series directly from the logger editor.

## Design

### New "Series" Tab

Add a fourth tab to the logger editor's tab widget (alongside "Adjust level", "Delete data", "History"). The tab contains:

1. **Selection summary label** — always shows what's currently selected:
   - Time range and point count
   - Breakdown by series: "800 from 'source1' (id=3), 400 from 'Diver file B' (id=7), 300 unassigned"

2. **Series metadata form** — four fields:
   - **Source** (QLineEdit, required) — free-text provenance. `strip()` applied before accepting. Validation error if blank.
   - **Instrument** (QLineEdit, optional) — device description or serial number
   - **Description** (QLineEdit, optional) — short metadata (filename, logger position)
   - **Comment** (QTextEdit or QLineEdit, optional) — longer free-form notes

3. **Action area** — three actions, availability depends on selection context:

| Action | Availability | Behavior |
|--------|-------------|----------|
| **Create new series** | Always (when points are selected) | Creates a new `w_logger_series` row with form values. Reassigns all selected points' `series_id` to the new row. |
| **Assign to existing series** | Always (when points are selected) | Dropdown of existing `w_logger_series` rows for this obsid (showing source + id). Reassigns all selected points' `series_id`. The metadata form fields are disabled in this mode — the existing series' metadata is not changed. |
| **Edit series metadata** | Only when all selected points share one non-NULL `series_id` | Pre-fills the form with the series' current metadata. User edits and applies. If only a sub-range of the series is selected, shows message: "Changes apply to all N points in series 'X', not just the M selected." |

### Auto-Detect Behavior

When the user switches to the Series tab (or the selection changes while on it), the tab auto-detects the appropriate mode:

- **Full-series selection** (all points of one non-NULL series are selected): Edit mode. Form pre-fills with series metadata. "Create" and "Assign" buttons remain available for splitting/reassigning.
- **Sub-range of one series** (some but not all points of one non-NULL series are selected): Create/Assign mode. Form is blank. The user likely wants to split these points into a new series or reassign them. "Edit entire series" is available as a secondary option with a clear warning: "Changes apply to all N points in series 'X', not just the M selected."
- **All selected points have NULL series_id:** Create mode. Form is blank. "Create" and "Assign" buttons available.
- **Mixed series_ids (any combination of named series and/or NULL):** Create/Assign mode. Form is blank. "Edit" button is disabled. Summary shows the breakdown. User can create a new series or assign all points to an existing one.

### Selection Rules

- **Any selection is valid** — no blocking on mixed series. The selection summary message always makes clear what's included.
- **NULL series_id points are not treated as one homogeneous group.** Each NULL-series point is independently selectable. The user can select any subset of unassigned points.
- **Line-click selection:** Clicking an unassigned line (NULL series) selects all its points. Clicking a named series line selects all points in that series. Both can then be narrowed via time range.

### Undo/Redo Integration

Series edits participate in the existing undo/redo system:

- **History snapshot expansion:** `_history_push()` now also captures the `series_id` column alongside `level_masl`. On undo/redo, both are restored.
- **Series metadata buffer:** A separate in-memory dict tracks `w_logger_series` row states (new rows, modified rows). This is also part of the undo snapshot.
- **History labels:**
  - "Set series: 'Diver replacement' (new, 500 points)"
  - "Assign to series: 'source1' (300 points)"
  - "Edit series 'source1': source → 'Diver original'"

### Save to DB

When the user clicks Save, all series changes are written in a single atomic transaction alongside the existing `level_masl` diff logic:

1. **INSERT** new `w_logger_series` rows created during editing
2. **UPDATE** modified `w_logger_series` rows (metadata changes)
3. **UPDATE** `w_levels_logger.series_id` for rows where it changed
4. **DELETE** orphaned `w_logger_series` rows — if a series row has no remaining `w_levels_logger` rows referencing it (because the user reassigned all its points away), it is deleted. This is consistent with the project preference to avoid soft-delete flags.

Order matters: INSERT new series first (to get IDs), then UPDATE level_logger rows, then DELETE orphans. All steps run within the same transaction.

### Plot Visual Feedback

- After any series edit action, the plot redraws with updated series coloring
- Points reassigned to a different series appear on their new series' line
- Legend updates to reflect new or renamed series
- Selected-line overlay (black circles) remains to show what was just changed

### Validation

- **Source field is required.** `source.strip()` must be non-empty. If blank, show inline validation: "Source is required."
- **Instrument, Description, Comment** are optional (can be blank → stored as NULL).

### Schema Compatibility

The feature is only available when the editor detects `series_join` mode (modern schema with `w_logger_series` table and `series_id` column). On legacy schemas (`source_col` or `no_source`), the Series tab is either hidden or shows a message explaining the schema needs upgrading.

## Critical Files

- `tools/loggereditor.py` — main editor; add Series tab, expand undo system, extend save logic
- `definitions/create_db.sql` — schema reference (no changes needed)
- `tools/utils/db_utils/helpers.py` — may need new helper functions for series CRUD
- `ui/calibr_logger_dialog_integrated.ui` — may need changes if tabs are defined here (verify during planning)

## Verification

1. **Integration tests** (lead with user-facing flow per project conventions):
   - Open logger editor with real QGIS layer → select period → switch to Series tab → create new series → verify plot recolors → undo → verify revert → redo → save → verify DB state
   - Full-series selection → edit metadata → save → verify only metadata changed, series_id unchanged
   - Sub-range of existing series → create new series → verify only selected points moved, rest unchanged
   - Mixed series selection → verify edit-metadata is disabled, create/assign work
   - NULL-series points → create series → verify assignment
   - Orphaned series after reassignment → verify cleanup on save
   - Legacy schema → verify Series tab is hidden/disabled
2. **Unit tests** (buffer/snapshot logic):
   - Series buffer CRUD operations
   - Undo/redo snapshots with series_id column
   - Save diff computation for series changes
