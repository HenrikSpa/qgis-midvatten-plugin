> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-07-29 · modified: 2026-07-29 · archived: 2026-07-31

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

