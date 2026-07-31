> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-06-06 · modified: 2026-06-06 · archived: 2026-07-31

# Logger Import UX: Move Format Combo to Left Panel

## Problem

The format combo is buried in the right-side settings panel, but the action
buttons (Select files, Start import) are in the left panel. Users naturally
select files first, then discover they need to change the format — which
clears their file selection (now fixed, but the workflow is still backwards).

Moving the format combo to the left panel creates a natural top-to-bottom
workflow: pick format, select files, import.

## Design

Move `self.format_combo` from `main_vertical_layout` (right-side scrollable
panel) to `grid_layout_buttons` (left panel) at row 0, pushing existing
buttons down by one row each.

**Layout changes:**

- `import_fieldlogger.ui`: increase left panel minimum width from 120px to
  160px to fit combo text.
- `importer.py` `load_gui()`: add the format combo and a label to
  `grid_layout_buttons` instead of `main_vertical_layout`. Remove the
  `RowEntry` wrapper (not needed in a grid layout). Add a horizontal separator
  line below the combo.
- The format description label stays in the right panel — it is reference text,
  not an action step.

**Resulting left-panel order (top to bottom):**

1. "Logger format:" label + combo box
2. Separator line
3. "Select files" button
4. File count label ("No files selected" / "3 file(s) selected")
5. "Close after import" checkbox
6. "Start import" button
7. "Export csv" button

## Testing

- Existing tests continue to pass (they call `load_gui()` directly and
  interact with the widgets regardless of which layout they are in).
- Manual verification: open the dialog in QGIS, confirm the format combo
  appears in the left panel and switching formats still shows/hides the
  correct format-specific settings in the right panel.

## Scope exclusions

- No format auto-detection (users know their file format; the format combo
  is now prominent and easy to set before selecting files).
- No drag-and-drop file support.
- No numbered step labels in the left panel (utilitarian QGIS aesthetic).
