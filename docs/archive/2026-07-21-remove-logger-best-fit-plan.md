> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-07-21 · modified: 2026-07-21 · archived: 2026-07-31

# Remove Logger-Elevation Best Fit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove automatic logger-elevation inference while retaining manual `head_cm` calculation, automatic adjustment of existing `level_masl`, and manual offset adjustment.

**Architecture:** The Qt Designer file remains the source of the calibration layout, while `LoggerEditor` keeps responsibility for connecting controls and applying buffered edits. Remove the obsolete UI entry point first, then narrow the existing best-fit helper to the one remaining operation: matching manual measurements against `level_masl` and applying the mean difference as an offset.

**Tech Stack:** Python 3.9+, PyQt/QGIS UI XML, pandas/NumPy time-series buffers, pytest

## Global Constraints

- Keep exactly three calibration actions: manual calculation from `head_cm`, automatic fitting of existing `level_masl`, and manual offset addition.
- Remove the **Calculate best fit (auto)** control and its automatic logger-elevation code path.
- Remove only `line_3`, the separator between **Fit to measurements (auto)** and its search-radius input; retain `line_2` between the calculation and offset sections.
- Label the remaining setting exactly **Auto-fit search radius**.
- Preserve matching, period selection, undo/redo, dirty-state tracking, saving behavior, and database schemas.
- Do not change the best-fit matching algorithm or unrelated historical terminology.

## File Map

- `ui/calibr_logger_dialog_integrated.ui`: declares the three remaining calibration actions, their layout, and the search-radius label.
- `tools/loggereditor.py`: connects the remaining controls and implements automatic fitting of `level_masl`.
- `test/test_wlevels_calc_calibr.py`: verifies the UI contract and the remaining automatic-fit behavior.

---

### Task 1: Reduce the calibration UI to three actions

**Files:**
- Modify: `test/test_wlevels_calc_calibr.py:1114`
- Modify: `ui/calibr_logger_dialog_integrated.ui:922-958,1096-1160`
- Modify: `tools/loggereditor.py:193`

**Interfaces:**
- Consumes: `LoggerEditor.__init__(iface, ms)`, which loads `calibr_logger_dialog_integrated.ui` through `setupUi()`.
- Produces: `button_calculate`, `button_auto_fit`, `button_add_offset`, `best_fit_search_radius`, and `label_15`; no `button_auto_calculate` or `line_3` attributes.

- [ ] **Step 1: Add a failing UI contract test**

Add this test at the start of `CalibrloggerSpatialiteMixin`:

```python
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_calibration_ui_has_only_three_level_actions(self, mock_messagebar):
        editor = LoggerEditor(self.iface, self.midvatten.ms)

        assert hasattr(editor, "button_calculate")
        assert hasattr(editor, "button_auto_fit")
        assert hasattr(editor, "button_add_offset")
        assert hasattr(editor, "best_fit_search_radius")
        assert not hasattr(editor, "button_auto_calculate")
        assert not hasattr(editor, "line_3")
        assert editor.label_15.text() == "Auto-fit search radius"
```

- [ ] **Step 2: Run the UI test and verify that it fails**

Run:

```bash
python3 -m pytest test/test_wlevels_calc_calibr.py::TestCalibrloggerSpatialite::test_calibration_ui_has_only_three_level_actions -q
```

Expected: FAIL because `button_auto_calculate` and `line_3` still exist and `label_15` still reads `Auto methods search radius`.

- [ ] **Step 3: Remove the obsolete widgets and signal connection**

In `ui/calibr_logger_dialog_integrated.ui`:

1. Delete the complete `<item>` containing `<widget class="QPushButton" name="button_auto_calculate">`.
2. Keep the complete `<item>` containing `<widget class="Line" name="line_2">`.
3. Delete the complete `<item>` containing `<widget class="Line" name="line_3">`.
4. Change only the text property of `label_15` to:

```xml
                <property name="text">
                 <string>Auto-fit search radius</string>
                </property>
```

In `LoggerEditor.__init__`, delete the connection to the removed widget:

```python
        self.button_auto_calculate.clicked.connect(lambda x: self.logger_pos_best_fit())
```

Keep the remaining automatic-fit connection unchanged:

```python
        self.button_auto_fit.clicked.connect(lambda x: self.level_masl_best_fit())
```

- [ ] **Step 4: Run the UI contract test and verify that it passes**

Run:

```bash
python3 -m pytest test/test_wlevels_calc_calibr.py::TestCalibrloggerSpatialite::test_calibration_ui_has_only_three_level_actions -q
```

Expected: PASS.

- [ ] **Step 5: Verify the removed UI text and object names are absent from production sources**

Run:

```bash
rg -n 'button_auto_calculate|Calculate best fit \(auto\)|Auto methods search radius|name="line_3"' tools/loggereditor.py ui/calibr_logger_dialog_integrated.ui
```

Expected: no output and exit status 1.

- [ ] **Step 6: Commit the UI reduction**

```bash
git add test/test_wlevels_calc_calibr.py ui/calibr_logger_dialog_integrated.ui tools/loggereditor.py
git commit -m "refactor: simplify logger calibration controls"
```

---

### Task 2: Remove automatic logger-elevation fitting logic

**Files:**
- Modify: `test/test_wlevels_calc_calibr.py:184-323,1114`
- Modify: `tools/loggereditor.py:3124-3187`

**Interfaces:**
- Consumes: `match_ts_values(meas_ts, logger_ts, search_radius_tuple)` and `add_to_level_masl(obsid=None)`.
- Produces: `level_masl_best_fit() -> None` as the sole automatic-fit entry point; `calc_best_fit() -> None` always fits `self.level_masl_ts` and writes the calculated difference to `self.offset`.

- [ ] **Step 1: Add the failing API regression test and route behavior tests through the surviving entry point**

Add this test after the UI contract test in `CalibrloggerSpatialiteMixin`:

```python
    def test_automatic_fit_has_no_logger_elevation_entry_point(self):
        assert not hasattr(LoggerEditor, "logger_pos_best_fit")
        assert hasattr(LoggerEditor, "level_masl_best_fit")
```

Rename the four existing automatic-offset tests as follows:

```python
test_calibrlogger_level_masl_best_fit_out_of_radius
test_calibrlogger_level_masl_best_fit
test_calibrlogger_level_masl_best_fit_matches_same_from_date
test_calibrlogger_level_masl_best_fit_matches_same_to_date
```

In each of those tests, delete:

```python
        calibrlogger.loggerpos_masl_or_offset_state = 2
```

Replace each direct helper call:

```python
        calibrlogger.calc_best_fit()
```

with the public remaining action:

```python
        calibrlogger.level_masl_best_fit()
```

- [ ] **Step 2: Run the API regression test and verify that it fails**

Run:

```bash
python3 -m pytest test/test_wlevels_calc_calibr.py::TestCalibrloggerSpatialite::test_automatic_fit_has_no_logger_elevation_entry_point -q
```

Expected: FAIL because `LoggerEditor.logger_pos_best_fit` still exists.

- [ ] **Step 3: Narrow the best-fit implementation to `level_masl` adjustment**

Delete `logger_pos_best_fit()` and replace `level_masl_best_fit()` plus `calc_best_fit()` with:

```python
    @fn_timer
    def level_masl_best_fit(self):
        self.calc_best_fit()

    @fn_timer
    def calc_best_fit(self):
        """Fit selected logger level_masl values to manual measurements."""
        obsid = self.load_obsid_and_init()
        common_utils.start_waiting_cursor()
        self.reset_plot_selects_and_calib_help()
        search_radius = self.get_search_radius()

        coupled_vals = self.match_ts_values(
            self.meas_ts, self.level_masl_ts, search_radius
        )
        if not coupled_vals:
            message_utils.pop_up_info(
                QCoreApplication.translate(
                    "Calibrlogger",
                    "There was no match found between measurements and logger values inside the chosen period.\n Try to increase the search radius or adjust the period!",
                )
            )
        else:
            calculated_diff = str(common_utils.calc_mean_diff(coupled_vals))
            if not calculated_diff or calculated_diff.lower() == "nan":
                message_utils.pop_up_info(
                    QCoreApplication.translate(
                        "Calibrlogger",
                        "There was no matched measurements or logger values inside the chosen period.\n Try to increase the search radius!",
                    )
                )
                message_utils.MessagebarAndLog.info(
                    log_msg=QCoreApplication.translate(
                        "Calibrlogger",
                        "Calculated water level from logger: midvatten_utils.calc_mean_diff(coupled_vals) didn't return a useable value.",
                    )
                )
            else:
                self.offset.setText(calculated_diff)
                self.add_to_level_masl(obsid)

        common_utils.stop_waiting_cursor()
```

Do not remove `loggerpos_masl_or_offset_state`; `set_logger_pos()`, `add_to_level_masl()`, and `calibrate()` still use it to distinguish the two manual edit paths.

- [ ] **Step 4: Run the focused automatic-fit tests**

Run:

```bash
python3 -m pytest \
  test/test_wlevels_calc_calibr.py::TestCalibrloggerSpatialite::test_automatic_fit_has_no_logger_elevation_entry_point \
  test/test_wlevels_calc_calibr.py::TestCalibrloggerSpatialite::test_calibrlogger_level_masl_best_fit_out_of_radius \
  test/test_wlevels_calc_calibr.py::TestCalibrloggerSpatialite::test_calibrlogger_level_masl_best_fit \
  test/test_wlevels_calc_calibr.py::TestCalibrloggerSpatialite::test_calibrlogger_level_masl_best_fit_matches_same_from_date \
  test/test_wlevels_calc_calibr.py::TestCalibrloggerSpatialite::test_calibrlogger_level_masl_best_fit_matches_same_to_date \
  -q
```

Expected: 5 passed.

- [ ] **Step 5: Verify production references to the removed path are gone**

Run:

```bash
rg -n 'button_auto_calculate|logger_pos_best_fit|Calculate best fit \(auto\)|Auto methods search radius|name="line_3"' tools/loggereditor.py ui/calibr_logger_dialog_integrated.ui
```

Expected: no output and exit status 1.

Run:

```bash
rg -n 'button_calculate|button_auto_fit|button_add_offset|Auto-fit search radius' tools/loggereditor.py ui/calibr_logger_dialog_integrated.ui
```

Expected: matches for all three remaining buttons and the new search-radius label.

- [ ] **Step 6: Run focused regression, lint, and whitespace verification**

Run:

```bash
python3 -m pytest test/test_wlevels_calc_calibr.py -q
```

Expected: 66 passed with the existing unrelated Matplotlib `Axes3D` warning.

Run:

```bash
ruff check tools/loggereditor.py test/test_wlevels_calc_calibr.py
git diff --check
```

Expected: both commands exit successfully with no errors.

- [ ] **Step 7: Commit the automatic-fit cleanup**

```bash
git add test/test_wlevels_calc_calibr.py tools/loggereditor.py
git commit -m "refactor: remove logger elevation best fit"
```
