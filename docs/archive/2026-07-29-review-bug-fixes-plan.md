> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-07-29 · modified: 2026-07-29 · archived: 2026-07-31

# Post-Review Bug Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three bugs found during the Opus 5 commit review: cursor leaks in three loggereditor methods, a wrong dirty-flag comparison in undo/redo, and spurious empty log entries in the message bar utility.

**Architecture:** All three bugs are independent single-file fixes. Each adds a targeted regression test first, then applies the minimal code change to make it pass. The cursor leaks are all the same pattern (manual start/stop without try/finally), so they share one task.

**Tech Stack:** Python, PyQt5, pytest, QGIS API (mocked in tests)

**Note:** Commit `0af86bd` added `common_utils.suspended_waiting_cursor()` — a context manager that unwinds *all* cursor levels for a modal prompt and restores them in `finally`. That pattern is better than bare `stop/start` pairs around modals, and was already applied to `importer.py`, `create_db.py`, `export_data.py`, and `export_fieldlogger.py`. `calc_best_fit` shows modal dialogs (`pop_up_info`) inside its cursor scope — wrapping those in `suspended_waiting_cursor` is a separate UX improvement, not part of this leak fix.

## Global Constraints

- Run `ruff check --fix .` and `ruff format .` after each task
- Run `python3 -m pytest test/test_wlevels_calc_calibr.py test/test_midvatten_utils.py -x` between tasks
- Never change test reference data — fix impl, not expectations

---

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

### Task 2: Fix `_restore_from_history` dirty flag comparison

`_restore_from_history` (line 1927) sets `self._dirty = pos != 0`, but
position 0 is only the saved state immediately after loading. After a save
at position N, undoing back to N should clear dirty, but `N != 0` evaluates
to True — a false positive that causes "unsaved changes" warnings.

**Files:**
- Modify: `tools/loggereditor.py:1927`
- Test: `test/test_wlevels_calc_calibr.py`

**Interfaces:**
- Consumes: `self._last_saved_history_pos` (existing, set by `save_to_db` and `load_obsid_and_init`)
- Produces: No new interfaces — one-line fix to dirty-flag logic

- [ ] **Step 1: Write the failing test**

Add to `test/test_wlevels_calc_calibr.py` in the appropriate location
(after the existing undo/redo tests, inside one of the
`CalibrloggerSpatialiteMixin` test classes that has DB fixtures):

```python
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_undo_to_saved_position_clears_dirty(self, mock_messagebar):
        """After save, undoing back to the saved position must clear _dirty."""
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl) "
            "VALUES ('rb1', '2017-02-01 00:00', 100, NULL)"
        )
        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")
        calibrlogger.update_plot()

        # Make an edit and save — saved position is now 1
        calibrlogger.from_date_time.setDateTime(
            date_utils.to_date("2000-01-01 00:00:00")
        )
        calibrlogger.logger_elevation.setText("5")
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")
        calibrlogger.set_logger_pos()
        assert calibrlogger._dirty
        saved_pos = calibrlogger._history_pos

        calibrlogger.save_to_db()
        assert not calibrlogger._dirty
        assert calibrlogger._last_saved_history_pos == saved_pos

        # Make another edit — dirty again
        calibrlogger.set_logger_pos()
        assert calibrlogger._dirty

        # Undo back to the saved position — should clear dirty
        calibrlogger.undo()
        assert calibrlogger._history_pos == saved_pos
        assert not calibrlogger._dirty
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest test/test_wlevels_calc_calibr.py::TestCalibrloggerSpatialite::test_undo_to_saved_position_clears_dirty -xvs`
Expected: FAIL — `assert not calibrlogger._dirty` fails because `pos != 0` is True when saved_pos > 0.

- [ ] **Step 3: Fix `_restore_from_history`**

In `tools/loggereditor.py` line 1927, replace:

```python
        self._dirty = pos != 0
```

with:

```python
        self._dirty = pos != self._last_saved_history_pos
```

This compares against the actual saved position, not a hardcoded 0.
When `_last_saved_history_pos` is `None` (never saved in this session),
every position is dirty — which matches the current `pos != 0` behavior
for position 0 (loaded = saved) and is even more correct for later
positions (previously `pos == 0` after a load would incorrectly show
as clean even if the user had never saved this session, but that couldn't
happen because load sets `_last_saved_history_pos = _history_pos`).

- [ ] **Step 4: Run the test and full loggereditor suite**

Run: `python3 -m pytest test/test_wlevels_calc_calibr.py -x`
Expected: All tests pass.

- [ ] **Step 5: Lint and commit**

```bash
ruff check --fix tools/loggereditor.py test/test_wlevels_calc_calibr.py
ruff format tools/loggereditor.py test/test_wlevels_calc_calibr.py
git add tools/loggereditor.py test/test_wlevels_calc_calibr.py
git commit -m "fix(loggereditor): compare dirty flag against saved position, not zero

_restore_from_history used pos != 0 to decide dirtiness, but position 0
is only the saved state right after loading. After a save at position N,
undoing back to N still showed as dirty because N != 0. Compare against
_last_saved_history_pos instead.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Guard `_log_on_main_thread` against None `bar_msg`

`_log_on_main_thread` unconditionally calls `QgsApplication.messageLog().logMessage(returnunicode(bar_msg), ...)` at line 133 even when `bar_msg is None`. Since `returnunicode(None)` returns `""`, every `log_msg`-only call (40 call sites) produces a spurious empty entry in the QGIS message log panel.

**Files:**
- Modify: `tools/utils/message_utils.py:133-135`
- Test: `test/test_midvatten_utils.py`

**Interfaces:**
- Consumes: `QgsApplication.messageLog().logMessage` (QGIS API)
- Produces: No new interfaces — conditional guard on existing call

- [ ] **Step 1: Write the failing test**

Add to the `TestMessageDispatcher` class in `test/test_midvatten_utils.py`:

```python
    def test_log_msg_only_does_not_produce_empty_bar_entry(self):
        """When only log_msg is supplied, the bar_msg log entry must be skipped."""
        with mock.patch("qgis.utils.iface") as mock_iface:
            mock_log = mock.MagicMock()
            with mock.patch(
                "midvatten.tools.utils.message_utils.QgsApplication"
            ) as mock_app:
                mock_app.messageLog.return_value = mock_log
                message_utils.MessagebarAndLog._log_on_main_thread(
                    log_msg="detail only"
                )

        logged_messages = [
            call.args[0] for call in mock_log.logMessage.call_args_list
        ]
        assert "" not in logged_messages
        assert "detail only" in logged_messages
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest test/test_midvatten_utils.py::TestMessageDispatcher::test_log_msg_only_does_not_produce_empty_bar_entry -xvs`
Expected: FAIL — `""` appears in `logged_messages` because line 133 logs `returnunicode(None)`.

- [ ] **Step 3: Fix the guard in `_log_on_main_thread`**

In `tools/utils/message_utils.py`, replace lines 133–135:

```python
        QgsApplication.messageLog().logMessage(
            returnunicode(bar_msg), "Midvatten", level=log_level
        )
```

with:

```python
        if bar_msg is not None:
            QgsApplication.messageLog().logMessage(
                returnunicode(bar_msg), "Midvatten", level=log_level
            )
```

This moves the `bar_msg` log entry inside a guard, matching the bar_msg
widget guard already present at line 112. When only `log_msg` is supplied,
only the `log_msg` entry (lines 136–139) is written.

- [ ] **Step 4: Run the test and full utils suite**

Run: `python3 -m pytest test/test_midvatten_utils.py -x`
Expected: All tests pass.

- [ ] **Step 5: Lint and commit**

```bash
ruff check --fix tools/utils/message_utils.py test/test_midvatten_utils.py
ruff format tools/utils/message_utils.py test/test_midvatten_utils.py
git add tools/utils/message_utils.py test/test_midvatten_utils.py
git commit -m "fix(message_utils): skip empty bar_msg log entry when only log_msg is set

_log_on_main_thread unconditionally logged returnunicode(bar_msg) even
when bar_msg was None, producing a spurious empty string in the QGIS
message log panel for every log_msg-only call (40 call sites). Guard it
the same way the messagebar widget creation is already guarded.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Final verification

After all three tasks:

```bash
python3 -m pytest test/test_wlevels_calc_calibr.py test/test_midvatten_utils.py -x
```

Expected: All tests pass. No regressions.
