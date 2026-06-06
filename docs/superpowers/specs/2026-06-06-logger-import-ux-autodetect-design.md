# Logger Import UX: Layout + Format Auto-Detection

## Problem

The Logger Import dialog has two UX issues:

1. **Workflow order**: The format combo is buried in the right-side settings panel,
   but the action buttons (Select files, Start import) are in the left panel.
   Users naturally select files first, then discover they need to change the
   format — which clears their file selection.

2. **No format auto-detection**: Users must know which format their files are in
   and manually select it. For DiverOffice vs DiverOffice Baro in particular,
   the distinction is non-obvious and the wrong choice produces confusing
   failures.

## Design

### Part 1: Move format combo to left panel

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

### Part 2: Format auto-detection

#### detect_format() function

A new module-level function in `parsers.py`:

```python
def detect_format(path: str, charset: str = "utf-8") -> str | None:
```

Reads the first 50 lines of the file. Returns one of the `LoggerImport.FORMAT_*`
string constants, or `None` if the format cannot be determined.

The format constants are currently class attributes on `LoggerImport`. To avoid
a circular import (`parsers.py` importing from `importer.py`), the detection
function returns plain string literals that match the constant values
(`"DiverOffice"`, `"DiverOffice Baro"`, `"Levelogger"`, `"Hobo"`).

#### Detection signatures

Each signature check is strictly a subset of what the corresponding parser
accepts — detection is never stricter than parsing.

| Signal | Detected format |
|--------|-----------------|
| `[Logger settings]`, `[Channel N]`, or `[Channel identification]` section present; channel identification contains "pressure" or "baro" (case-insensitive) | `"DiverOffice Baro"` |
| Same section markers present; channel identification contains "level" or "waterhead", or no channel detail available | `"DiverOffice"` |
| `[Data]` section present without other distinguishing metadata | `"DiverOffice"` (default for the DiverOffice family) |
| Row starts with `Date` and file contains `LEVEL` or `TEMPERATURE` column headers | `"Levelogger"` |
| Row contains `Date Time` (Hobo-style header) | `"Hobo"` |
| None of the above | `None` |

The function catches `UnicodeDecodeError` and `OSError` and returns `None`
rather than crashing.

#### Integration in select_files()

After `midvatten_utils.select_files()` returns and before enabling buttons,
`select_files()` runs detection:

1. Call `detect_format(path)` on each selected file.
2. Collect detected formats into a set (ignoring `None` results).
3. Three outcomes:

   - **All files agree on one format**: programmatically set
     `self.format_combo` to that format. This triggers `_on_format_changed`,
     which preserves compatible files (per the earlier bugfix) and updates
     format-specific widget visibility.

   - **Files disagree (multiple formats detected)**: show
     `MessagebarAndLog.warning("Selected files appear to be different formats
     — please verify the format setting")`. Do not change the combo.

   - **All files unknown (empty set)**: show `MessagebarAndLog.info("Could not
     auto-detect format — please verify the format setting")`. Do not change
     the combo.

4. Enable buttons regardless — detection never blocks import.

#### Ordering: detection vs format change

When auto-detection sets the combo, `_on_format_changed` fires before the
buttons are enabled. The file-compatibility check in `_on_format_changed`
(from the earlier bugfix) ensures files are preserved when switching between
compatible formats. The sequence is:

1. `select_files()` stores `self.files`
2. `detect_format()` returns a format
3. Combo is set → `_on_format_changed` fires → files are preserved if compatible
4. Buttons are enabled

Since detection reads the selected files themselves, the detected format will
always accept those files' extensions — so `_on_format_changed` will never
clear the selection due to auto-detection. As a defensive measure, `select_files()`
saves the file list before setting the combo and re-assigns `self.files` after
`_on_format_changed` returns, ensuring the selection is never dropped.

#### Warning presentation

- Warnings use `MessagebarAndLog` (QGIS message bar + log panel), consistent
  with the rest of the plugin.
- No modal dialogs for detection results.
- The format combo remains editable at all times — the user can override
  auto-detection before or after it runs.

## Testing

### detect_format() unit tests

Test with inline string snippets (via `common_utils.tempinput`) for each format
variant:

- DiverOffice `.mon` file (water level channels) → `"DiverOffice"`
- DiverOffice `.csv` file (flat key=value header) → `"DiverOffice"`
- DiverOffice Baro `.mon` file (pressure channel) → `"DiverOffice Baro"`
- DiverOffice Baro `.csv` file → `"DiverOffice Baro"`
- Levelogger CSV → `"Levelogger"`
- Hobo CSV → `"Hobo"`
- Empty file → `None`
- Binary/garbage file → `None`
- File with only metadata, no data section → still detected by section markers

### Integration tests

- Mock `midvatten_utils.select_files` to return a baro `.mon` path; call
  `select_files()` on `LoggerImport`; assert `format_combo.currentText()` is
  `"DiverOffice Baro"` and `start_import_button.isEnabled()` is `True`.
- Mock with mixed-format files; assert combo unchanged and warning logged.

## Scope exclusions

- No drag-and-drop file support (separate feature).
- No numbered step labels in the left panel (utilitarian QGIS aesthetic).
- Detection does not attempt charset sniffing — it uses utf-8 with silent
  fallback to returning `None`. Charset handling remains in `start_import()`.
