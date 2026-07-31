> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-04-17 · modified: 2026-04-17 · archived: 2026-07-31

# Interlab4 Import: s_qual_lab Destination Table Support

**Date:** 2026-04-17  
**Branch:** ai_test  

## Problem

The interlab4 import dialog hardcodes `w_qual_lab` as its destination table. The database also has `s_qual_lab` for soil sample analyses, which shares an identical schema but has no import path.

## Goal

Add a radio-button toggle to the import dialog so the user can choose between `w_qual_lab` (default) and `s_qual_lab`. If `s_qual_lab` does not yet exist, offer to create it on demand. As part of this work, promote `s_qual_lab` from an optional extra table to a standard part of the schema.

---

## Design

### 1. UI — Destination Table GroupBox

A `QGroupBox` labelled **"Destination table"** is inserted at row 0 of `grid_layout_buttons` (all existing rows shift down by 1). It contains two `QRadioButton`s:

| Widget | Label | Default | Tooltip |
|---|---|---|---|
| `radio_w_qual_lab` | `w_qual_lab` | checked | "Water sample analyses" |
| `radio_s_qual_lab` | `s_qual_lab` | unchecked | "Soil sample analyses" |

The window title is simplified to **"Import interlab4 data"** (table selection is visible in the GroupBox).

Both radio buttons are connected to `_on_dest_table_changed()`.

### 2. `dest_table` Property

```python
@property
def dest_table(self) -> str:
    return "s_qual_lab" if self.radio_s_qual_lab.isChecked() else "w_qual_lab"
```

### 3. On-Demand Table Creation

`_on_dest_table_changed()` runs when either radio button is clicked:

1. If `radio_w_qual_lab` is selected: no action needed.
2. If `radio_s_qual_lab` is selected and `"s_qual_lab" in tables_columns()`: no action needed.
3. If `radio_s_qual_lab` is selected and `s_qual_lab` does **not** exist:
   - Show `QMessageBox.question`: *"Table s_qual_lab does not exist. Create it now?"*
   - **Yes** → call `_create_s_qual_lab()`, keep radio selection.
   - **No** → revert to `radio_w_qual_lab.setChecked(True)`.

`_create_s_qual_lab()`:
- Reads `create_db.sql` via `db_defs.get_full_filename("create_db.sql")`.
- Calls `_extract_create_table(sql_text, "s_qual_lab")` to parse out the `CREATE TABLE s_qual_lab ...` block (lines from `CREATE TABLE s_qual_lab` up to and including the first `);`).
- Executes the DDL via `DbConnectionManager` + `commit`.

`_extract_create_table(sql_text: str, table_name: str) -> str` is a small static helper that can be unit-tested independently.

### 4. Data Flow Changes

Three places in `Interlab4Import` that hardcode `w_qual_lab` are updated to use `self.dest_table`:

| Location | Before | After |
|---|---|---|
| `load_files()` skip query | `FROM w_qual_lab` | `FROM {ident("s_qual_lab" or "w_qual_lab")}` via `self.dest_table` |
| `start_import()` | `dest_table="w_qual_lab"` | `dest_table=self.dest_table` |
| `__init__` window title | `"Import interlab4 data to w_qual_lab table"` | `"Import interlab4 data"` |

The `skip_imported_reports` check queries only the selected destination table. Switching tables gives the user a clean slate for that table's existing reports.

### 5. Schema Clean-up

`s_qual_lab` is promoted from optional to standard:

| File | Change |
|---|---|
| `definitions/create_db_extra_data_tables.sql` | Remove the `CREATE TABLE s_qual_lab` block |
| `definitions/midvatten_defs.py` | Remove `"s_qual_lab"` from the `extra_data_tables` list |
| `definitions/create_db.sql` | Update comment from `/*Soil quality data*/` to `/*Soil sample analyses*/` |

`s_qual_lab` is already present in `create_db.sql` so it will be created for all new databases going forward. Existing databases without the table get it created on first use via the creation dialog.

---

## Testing

New test methods (existing interlab4 tests are unchanged):

- **`test_dest_table_defaults_to_w_qual_lab`** — assert `dest_table == "w_qual_lab"` on fresh dialog init.
- **`test_s_qual_lab_creation_on_selection`** — mock `QMessageBox.question` to return Yes; assert `s_qual_lab` is created in the DB when radio is clicked.
- **`test_skip_reports_queries_dest_table`** — select `s_qual_lab`, load files, assert the skip query uses `s_qual_lab` not `w_qual_lab`.
- **`test_extract_create_table`** — unit test for `_extract_create_table()` parsing helper.

---

## Files Touched

- `tools/import_interlab4.py` — UI, property, creation flow, data flow changes
- `definitions/create_db.sql` — comment update on `s_qual_lab`
- `definitions/create_db_extra_data_tables.sql` — remove `s_qual_lab` block
- `definitions/midvatten_defs.py` — remove `s_qual_lab` from extra_data_tables
- `test/test_import_interlab4.py` — new test methods
