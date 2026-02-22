# Plan: Tests for DrillreportUi (tools/custom_drillreport.py)

## Objective

Add tests for the **DrillreportUi** class that:
- Use **sqlite only** (test class inherits from `utils_for_tests.MidvattenTestSpatialiteDbSv`).
- Cover **user‑interactable widgets**: buttons, text inputs (QPlainTextEdit / QLineEdit), checkboxes.
- Rely on **test data in `obs_points` and `stratigraphy`** that is exported as HTML via DrillreportUi.

No list or combobox widgets exist in the Custom general report UI; interaction is via **buttons**, **plain text / line edits**, and **checkboxes**.

---

## 1. Widget inventory (from custom_drillreport.ui and DrillreportUi)

| Widget type        | Name(s) | User action to test |
|--------------------|--------|----------------------|
| **Buttons**        | `push_button_ok`, `push_button_cancel`, `push_button_update_from_string` | Click → trigger `drillreport()`, `close()`, `ask_and_update_stored_settings()` |
| **QPlainTextEdit** | `general_metadata`, `geo_metadata`, `strat_columns` | Set text (column lists, one per line) |
| **QLineEdit**      | `general_metadata_header`, `geo_metadata_header`, `strat_columns_header`, `comment_header`, `topleft_topright_colwidths`, `general_colwidth`, `geo_colwidth`, `decimal_separator` | Set text |
| **QCheckBox**      | `header_in_table`, `skip_empty`, `include_comments`, `empty_row_between_obsids` | Set checked / unchecked |

There are **no** QListWidget or QComboBox in this UI.

### Widget verification

This inventory was verified against `ui/custom_drillreport.ui` on 2025-02-22. No user-interactable widgets were missed.

---

## 2. Test file and base setup

- **File**: `test/test_custom_drillreport_ui_spatialite.py` (new file).
- **Base class**: `utils_for_tests.MidvattenTestSpatialiteDbSv`.
- **Imports**: `unittest.mock`, `midvatten.test.utils_for_tests`, `midvatten.tools.custom_drillreport.DrillreportUi`, `midvatten.tools.utils.db_utils`, and (if needed) `qgis.PyQt.QtCore` for `QDir.tempPath()`.
- **Decorator**: `@attr(status="on")` on the test class (same as `test_drillreport_spatialite.py` and `test_customplot_spatialite.py`).
- **Mocks** (per project rules):
  - `@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")` with argument name `mock_messagebar`; print `mock_messagebar.mock_calls` before groups of asserts.
  - Do **not** print asserted values to stdout (rely on `--failure-detail` for assert output).

---

## 3. Required mocks for DrillreportUi tests

- **`common_utils.getselectedobjectnames`**  
  Patch where it is used: `midvatten.tools.custom_drillreport.common_utils.getselectedobjectnames`.  
  Return a list of obsids that exist in the test DB (e.g. `["OP1", "OP2"]`) so that `drillreport()` does not hit “Must select at least 1 obsid” and so the report is generated.

- **`QDesktopServices.openUrl`**  
  Patch `midvatten.tools.custom_drillreport.QDesktopServices.openUrl` so the report is not opened in a browser. Optionally assert that it was called with the expected report path (e.g. `file:///tmp/midvatten_reports/drill_report.html` or equivalent from `QDir.tempPath()`).

- **`common_utils.save_stored_settings`**  
  Can be mocked to avoid touching real stored settings if desired (optional).

- **For “Update settings from string”**  
  Patch `qgis.PyQt.QtWidgets.QInputDialog.getText` to return a valid settings string (e.g. a dict representation) or to simulate cancel (second element `False`). If the test triggers `UserInterruptError`, mock accordingly.

---

## 4. Test data: obs_points and stratigraphy

- Use **minimal, stable inserts** compatible with the existing schema (see `definitions/create_db.sql`).
- **obs_points**: at least `obsid` and geometry; add columns that appear in default general_metadata / geo_metadata (e.g. `type`, `h_tocags`, `material`, `diam`, `drillstop`, `screen`, `drilldate`, `east`, `north`, `ne_accur`, `ne_source`, `h_toc`, `h_accur`, `h_source`) so the exported HTML can be asserted.
- **stratigraphy**: `obsid`, `stratid`, `depthtop`, `depthbot`, `geology`, `geoshort`, `capacity`, `development`, `comment` so that stratigraphy table output in the report is predictable.

Example pattern (align with existing test_drillreport_spatialite.py style):

```python
db_utils.sql_alter_db(
    """INSERT INTO obs_points (obsid, east, north, h_gs, geometry)
       VALUES ('OP1', 633466, 711659, 5, ST_GeomFromText('POINT(633466 711659)', 3006))"""
)
db_utils.sql_alter_db(
    """INSERT INTO stratigraphy (obsid, stratid, depthtop, depthbot, geology, geoshort, capacity, development)
       VALUES ('OP1', 1, 0, 1, 'sand', 'sand', '3', 'j')"""
)
# Add more rows as needed for multi-obsid tests.
```

- Report output path: `os.path.join(QDir.tempPath(), "midvatten_reports", "drill_report.html")` (same as in `Drillreport.__init__`).

---

## 5. Instantiating DrillreportUi in tests

- **Parent**: use `self.iface.mainWindow()` from the test base (same as in `midvatten_plugin.custom_drillreport()`), or a mock that provides a QWidget parent.
- **Settings**: use `self.midvatten.ms` (or equivalent from `MidvattenTestSpatialiteDbSv`) so that DB connection and locale come from the test DB.

Example:

```python
ui = DrillreportUi(self.iface.mainWindow(), self.midvatten.ms)
```

- Because `QWidget.show` is overridden in the test base (`stop_show`), the dialog will not actually be shown.

---

## 6. Suggested test cases

1. **test_ok_button_generates_html**  
   - Insert obs_points + stratigraphy for one or two obsids.  
   - Mock `getselectedobjectnames` to return those obsids; mock `MessagebarAndLog` and `QDesktopServices.openUrl`.  
   - Create DrillreportUi, set default or minimal widget state (or leave defaults), call `push_button_ok.clicked.emit()` or invoke `drillreport()` directly.  
   - Assert the report file exists and that its HTML contains expected content (e.g. obsid, stratigraphy rows, or key headers).  
   - Normalize paths in HTML (e.g. `src="..."`) if needed (cf. test_drillreport_spatialite.py) and print `mock_messagebar.mock_calls` before asserts.

2. **test_cancel_button_closes**  
   - Create DrillreportUi, then trigger `push_button_cancel.clicked.emit()`.  
   - Assert the window is closed (e.g. `isVisible()` or closed flag), and that no report file was created if no OK was clicked.

3. **test_checkboxes_affect_export**  
   - With same DB and mocks as in (1), set `header_in_table`, `skip_empty`, `include_comments`, or `empty_row_between_obsids` to different states.  
   - Run `drillreport()` and assert the generated HTML reflects the option (e.g. “empty_row_between_obsids” text when `empty_row_between_obsids` is checked, or header placement when `header_in_table` is toggled).

4. **test_plain_text_metadata_columns_affect_export**  
   - Set `general_metadata.setPlainText("obsid\ntype\nh_gs")` and `geo_metadata.setPlainText("east\nnorth")`, `strat_columns.setPlainText("depth\ngeology\ngeoshort")` (or subset).  
   - Generate report and assert the HTML contains the corresponding headers/values from the test data.

5. **test_line_edit_headers_affect_export**  
   - Set `general_metadata_header.setText("Custom general")`, etc.  
   - Generate report and assert the HTML contains these header strings.

6. **test_decimal_separator_affect_export**  
   - Set `decimal_separator` to `","` and ensure numeric values in the report use that separator (if the code uses it in the HTML).

7. **test_update_settings_from_string**  
   - Mock `QInputDialog.getText` to return a valid dict string (e.g. `{"header_in_table": True, "skip_empty": False, ...}`).  
   - Trigger `push_button_update_from_string.clicked.emit()` (or call `ask_and_update_stored_settings()`).  
   - Assert widget state is updated (e.g. checkboxes) from the string, and optionally that `save_stored_settings` was called.  
   - If testing cancel: mock `getText` to return `(..., False)` and assert no change or `UserInterruptError` handling.

8. **test_no_selection_shows_message**  
   - Mock `getselectedobjectnames` to return `[]`.  
   - Trigger OK / `drillreport()`.  
   - Assert `MessagebarAndLog.critical` (or equivalent) was called with a message like “Must select at least 1 obsid”, and no report file is created (or openUrl not called).

9. **test_save_and_restore_stored_settings**  
   - Set widgets to a known state, call `save_stored_settings()`, then create a new DrillreportUi (or call `update_from_stored_settings` with the stored dict).  
   - Assert widgets match the saved state (e.g. checkbox states, line edit text).

---

## 7. Reference tests and helpers

- **test_drillreport_spatialite.py**: DB inserts, Drillreport (non‑UI) usage, HTML path normalization, `openUrl` mock, reference HTML (for the non‑custom report). Reuse similar insert and assert style; custom_drillreport produces different HTML structure.
- **test_customplot_spatialite.py**: `MidvattenTestSpatialiteDbSv`, mocking `MessagebarAndLog`, setting combobox/list and checkboxes (`gui_utils.set_combobox`, `.setChecked`), printing `mock_messagebar.mock_calls`, and using `create_test_string` for comparisons.
- **test/test_drillreport_spatialite.py** and **test_calclvl_spatialite.py**: patching `getselectedobjectnames` to return a list of obsids.

---

## 8. Implementation order

1. Add test file and shared helpers: DB insert helpers for obs_points + stratigraphy, report path helper.
2. Implement test_ok_button_generates_html (and test_no_selection_shows_message) to lock in mocks and DB setup.
3. Add test_cancel_button_closes and test_no_selection_shows_message.
4. Add tests for checkboxes, plain text, and line edits affecting export (3–6).
5. Add test_update_settings_from_string and test_save_and_restore_stored_settings (7, 9).

---

## 9. Linting and running

- After writing code: run `ruff check --fix .` and `ruff format .` (per project rules).
- Run tests with:  
  `nosetests3 test/test_custom_drillreport_ui_spatialite.py --failure-detail --with-doctest --nologcapture --stop`  
  from the repo root or from `test/`.
- Follow the rule for test execution order: ensure DB-creation tests and central utils/defs tests pass before running this new file.

---

## 10. Summary

| Item | Choice |
|------|--------|
| Test file | `test/test_custom_drillreport_ui_spatialite.py` |
| Base class | `utils_for_tests.MidvattenTestSpatialiteDbSv` |
| DB | SQLite only; data in `obs_points`, `stratigraphy` |
| Widgets covered | Buttons (OK, Cancel, Update settings), QPlainTextEdit (metadata/strat columns), QLineEdit (headers, widths, decimal separator), QCheckBox (header_in_table, skip_empty, include_comments, empty_row_between_obsids) |
| Mocks | MessagebarAndLog, getselectedobjectnames, QDesktopServices.openUrl; optionally save_stored_settings and QInputDialog.getText |
| Output | HTML file under `QDir.tempPath()/midvatten_reports/drill_report.html`; assert content and MessagebarAndLog calls as needed |

This plan is ready to be implemented step by step in the new test file.
