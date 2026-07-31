> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-07-29 · modified: 2026-07-29 · archived: 2026-07-31

### Task 1: Fix cursor leaks in `calc_best_fit`, `delete_selected_range`, and `_trend_release`

Three methods in `tools/loggereditor.py` use manual `start_waiting_cursor()` / `stop_waiting_cursor()` without try/finally. If the body raises, the wait cursor leaks permanently. The fix for each is the same: wrap the cursor-protected block in try/finally.

**Files:**
- Modify: `tools/loggereditor.py:3141-3177` (`calc_best_fit`)
- Modify: `tools/loggereditor.py:3361-3371` (`delete_selected_range`)
- Modify: `tools/loggereditor.py:3673-3700` (`_trend_release`)
- Test: `test/test_wlevels_calc_calibr.py`

**Interfaces:**
- Consumes: `common_utils.start_waiting_cursor`, `common_utils.stop_waiting_cursor` (existing)
- Produces: No new interfaces — only wraps existing calls in try/finally

- [ ] **Step 1: Write the failing test for `calc_best_fit` cursor leak**

Add to the test file after the existing `TestCalibrloggerSpatialite` class:

```python
def test_calc_best_fit_restores_cursor_on_exception():
    """calc_best_fit must pop the cursor even when the body raises."""
    editor = LoggerEditor.__new__(LoggerEditor)
    editor.load_obsid_and_init = mock.MagicMock(return_value="rb1")
    editor.reset_plot_selects_and_calib_help = mock.MagicMock()
    editor.get_search_radius = mock.MagicMock(side_effect=RuntimeError("boom"))

    with (
        mock.patch(
            "midvatten.tools.loggereditor.common_utils.start_waiting_cursor"
        ) as start_cursor,
        mock.patch(
            "midvatten.tools.loggereditor.common_utils.stop_waiting_cursor"
        ) as stop_cursor,
        pytest.raises(RuntimeError, match="boom"),
    ):
        editor.calc_best_fit()

    start_cursor.assert_called_once()
    stop_cursor.assert_called_once()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest test/test_wlevels_calc_calibr.py::test_calc_best_fit_restores_cursor_on_exception -xvs`
Expected: FAIL — `stop_cursor` was not called because the exception bypasses it.

- [ ] **Step 3: Fix `calc_best_fit` — wrap in try/finally**

In `tools/loggereditor.py`, replace lines 3144–3177:

```python
    @fn_timer
    def calc_best_fit(self):
        """Fit selected logger level_masl values to manual measurements."""
        obsid = self.load_obsid_and_init()
        common_utils.start_waiting_cursor()
        try:
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
                calculated_diff = common_utils.calc_mean_diff(coupled_vals)
                if math.isnan(calculated_diff):
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
                    self.offset.setText(str(calculated_diff))
                    self.add_to_level_masl(obsid)
        finally:
            common_utils.stop_waiting_cursor()
```

- [ ] **Step 4: Fix `delete_selected_range` — wrap in try/finally**

In `tools/loggereditor.py`, replace lines 3361–3371:

```python
        really_delete = dialog_utils.Askuser("YesNo", msg).result
        if really_delete:
            common_utils.start_waiting_cursor()
            try:
                mask = self._build_edit_mask(fr_d_t, to_d_t)
                if set_to_null_instead:
                    self._buf.loc[mask, "level_masl"] = np.nan
                    self._history_push("Set to null")
                else:
                    self._buf = self._buf.drop(index=self._buf.index[mask])
                    self._history_push("Delete data")
            finally:
                common_utils.stop_waiting_cursor()
            self.update_plot()
```

- [ ] **Step 5: Fix `_trend_release` — wrap in try/finally**

In `tools/loggereditor.py`, replace lines 3673–3700:

```python
        common_utils.start_waiting_cursor()
        try:
            sub = self._buf.loc[mask].copy()
            applied = apply_trend_correction(
                sub, original_start_y, original_end_y, new_start_y, new_end_y
            )
            if applied:
                self._buf.loc[mask, "level_masl"] = sub["level_masl"]

                obsid = self._buf_obsid or ""
                delta_start = new_start_y - original_start_y
                delta_end = new_end_y - original_end_y
                message_utils.MessagebarAndLog.info(
                    log_msg=QCoreApplication.translate(
                        "Calibrlogger",
                        "Trend adjusted for %s (%s to %s): Δ_start=%.4f, Δ_end=%.4f",
                    )
                    % (
                        obsid,
                        fr_d_t.strftime(_DT_FMT),
                        to_d_t.strftime(_DT_FMT),
                        delta_start,
                        delta_end,
                    )
                )
                self._history_push("Adjust trend")
        finally:
            common_utils.stop_waiting_cursor()
        self.update_plot()
```

- [ ] **Step 6: Run the test and full loggereditor suite**

Run: `python3 -m pytest test/test_wlevels_calc_calibr.py -x`
Expected: All tests pass including the new cursor-leak test.

- [ ] **Step 7: Lint and commit**

```bash
ruff check --fix tools/loggereditor.py test/test_wlevels_calc_calibr.py
ruff format tools/loggereditor.py test/test_wlevels_calc_calibr.py
git add tools/loggereditor.py test/test_wlevels_calc_calibr.py
git commit -m "fix(loggereditor): wrap cursor-protected blocks in try/finally

Three methods used manual start/stop_waiting_cursor without try/finally:
calc_best_fit, delete_selected_range, and _trend_release. An exception
between the two calls leaked the wait cursor permanently.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

