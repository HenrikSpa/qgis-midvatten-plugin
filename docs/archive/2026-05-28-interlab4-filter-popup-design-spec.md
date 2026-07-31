> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-06-10 · modified: 2026-06-10 · archived: 2026-07-31

# Interlab4 Import Dialog: Filter Popup

**Date:** 2026-05-28
**Status:** Draft

## Problem

The interlab4 import dialog has a vertical splitter with two panels:
- **Top panel (`MetaFilterSelection`):** A combobox (column selector) and multi-line text editor for bulk-filtering reports by pasting a list of values. Used <1% of the time.
- **Bottom panel (`MetadataFilter`):** A sortable QTableWidget showing all loaded reports with dynamic metadata columns. This is where the user spends all their time.

The top panel wastes vertical space in the common workflow (load files, sort table, select rows, import). The filter feature is rarely needed but has a valid use case: bulk-matching reports by a list of lablittera values (or occasionally other metadata columns) when manual selection isn't practical.

## Solution

Move the filter UI out of the main layout into a non-modal popup dialog. Remove the vertical splitter. The table fills the full content area.

## Layout: Before and After

**Before:**
```
┌──────────────────────────────────────────┬──────────────┐
│ MetaFilterSelection (splitter top)       │  Right       │
│  [Column header ▼]                       │  sidebar     │
│  ┌──────────────────────────────┐        │  buttons     │
│  │ (text editor for filter)     │        │              │
│  └──────────────────────────────┘        │              │
│──────────── splitter handle ─────────────│              │
│ MetadataFilter (splitter bottom)         │              │
│ [Update selection] [Show only selected☐] │              │
│ "3 of 47 selected"   [Save to file]     │              │
│┌────────────────────────────────────────┐│              │
││ lablittera │ datum │ projekt │ provtyp  ││              │
│├────────────┼───────┼─────────┼─────────┤│              │
││ ...        │       │         │          ││              │
│└────────────────────────────────────────┘│              │
└──────────────────────────────────────────┴──────────────┘
```

**After:**
```
┌──────────────────────────────────────────┬──────────────┐
│ [Filter by list...] [Show only selected☐]│  Right       │
│ "3 of 47 selected"   [Save to file]     │  sidebar     │
│┌────────────────────────────────────────┐│  buttons     │
││ lablittera │ datum │ projekt │ provtyp  ││              │
│├────────────┼───────┼─────────┼─────────┤│              │
││ ...        │       │         │          ││              │
││            │       │         │          ││              │
││            │       │         │          ││              │
││            │       │         │          ││              │
│└────────────────────────────────────────┘│              │
└──────────────────────────────────────────┴──────────────┘
```

**Popup (when "Filter by list..." is clicked):**
```
┌─── Filter by list ─────────────────────┐
│ Column: [lablittera              ▼]    │
│ ┌────────────────────────────────┐     │
│ │ R-2024-001                     │     │
│ │ R-2024-015                     │     │
│ │ R-2024-033                     │     │
│ │                                │     │
│ └────────────────────────────────┘     │
│              [Apply]  [Close]          │
└────────────────────────────────────────┘
```

## Changes

### 1. `MetaFilterSelection`: VRowEntry → QDialog

Change the base class from `VRowEntry` to `QDialog`. Constructor signature: `__init__(self, parent=None)`. The `all_lab_results` parameter is dropped — `update_combobox()` is already called separately from `load_files()` when files are loaded.

The dialog:
- Is parented to the main `Interlab4Import` window (stays on top, non-modal — `QDialog` defaults to `Qt.NonModal`, no explicit modality flags needed)
- Window title: "Filter by list"
- Contains: QLabel("Column header") + QComboBox + ExtendedQPlainTextEdit + Apply/Close buttons in a QVBoxLayout
- `update_combobox()` and `get_items_dict()` are unchanged
- Apply button triggers the existing `set_selection()` on `MetadataFilter`. Apply does **not** close the dialog — the user can iterate.
- Close button hides the dialog (not destroyed). Content persists across open/close cycles.

### 2. `Interlab4Import.init_gui()`: remove splitter, add filter button

- Remove `SplitterWithHandel` creation
- Add `MetadataFilter` directly to `main_vertical_layout`
- Create `MetaFilterSelection(parent=self)` as a dialog (not added to any layout)
- Add a "Filter by list..." button to `MetadataFilter.button_layout`
- Connect the button to show the popup: `self.specific_meta_filter.show()` + `raise_()` + `activateWindow()` (ensures the popup comes to front even if already visible)
- Connect the popup's Apply button to `self.metadata_filter.set_selection(self.specific_meta_filter.get_items_dict())`
- Remove the old `update_selection_button.clicked.connect(...)` wiring (lines 87–91) — this signal is replaced by the popup's Apply button connection

### 3. `MetadataFilter`: remove "Update selection" button

- Remove `self.update_selection_button` — its role is replaced by the popup's Apply button
- "Show only selected rows" checkbox stays (useful independently of the filter)
- Everything else in `MetadataFilter` is unchanged

### 4. Help tooltip update

Update the `help_label` tooltip text to describe the popup workflow instead of referring to the "top list":

New text:
```
Selected rows (lablitteras) in the table will be imported when pushing "Start import" button.
The table can be sorted by clicking the column headers.

Rows can also be selected using the "Filter by list..." button.
Howto:
1. Click "Filter by list..." to open the filter dialog.
2. Choose a column header in the drop down list.
3. Paste a list of entries (one row per entry).
4. Click "Apply".
All rows where values in the chosen column match entries in the pasted list will be selected.

Hover over a column header to see which database column it will go to.

("Save data table to csv" saves the data table into a csv file for examination in another application.)
("Save metadata table to file" saves the metadata table into a csv file for examination in another application.)
```

## What stays the same

- `MetadataFilter.set_selection()` logic (regex matching, row selection, hide/show) — unchanged
- `MetadataFilter.update_table()` — unchanged
- `MetadataFilter.get_selected_lablitteras()` — unchanged
- Table columns, tooltips, sorting, selection behavior — unchanged
- All right sidebar buttons and import logic — unchanged
- `get_metadata_headers()` — unchanged

## Scope

This is a layout-only change. No changes to:
- Import logic or data processing
- Database operations
- File parsing
- Table data population
- Selection semantics
