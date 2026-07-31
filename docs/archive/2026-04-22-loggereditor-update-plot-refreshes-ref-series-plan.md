> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-06-10 · modified: 2026-06-10 · archived: 2026-07-31

# Logger Editor: Update Plot Refreshes Reference Series Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the user clicks "Update plot" in the Logger editor, the reference series subplot is also re-read from the database and redrawn.

**Architecture:** A single call to `_draw_reference_subplot()` is added at the end of `update_plot()`, after `_finish_plot()`. `_draw_reference_subplot()` already handles the empty-list case (hides the subplot), so the call is unconditional. The change sits after the `obsid is None` early-return guard, so the reference subplot is only refreshed when the main plot loads successfully.

**Tech Stack:** Python 3, PyQt5, matplotlib, pytest

---

### Task 1: Add failing test

**Files:**
- Modify: `test/test_wlevels_calc_calibr.py`

The existing test class `CalibrloggerMixin` (used in both SpatiaLite and PostGIS subclasses) is the right place for this test. We mock `_draw_reference_subplot` on the instance after construction and assert it is called exactly once by `update_plot()`.

- [ ] **Step 1: Write the failing test**

Open `test/test_wlevels_calc_calibr.py`. Inside `CalibrloggerMixin`, add this method after the last existing test:

```python
@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_update_plot_calls_draw_reference_subplot(self, mock_messagebar):
    db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
    db_utils.sql_alter_db(
        "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl) "
        "VALUES ('rb1', '2017-02-01 00:00', 50, 100)"
    )
    calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
    calibrlogger.show()
    with mock.patch.object(calibrlogger, "_draw_reference_subplot") as mock_draw_ref:
        calibrlogger.update_plot()
    print(f"{mock_messagebar.mock_calls=}")
    mock_draw_ref.assert_called_once_with()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python3 -m pytest test/test_wlevels_calc_calibr.py -k "test_update_plot_calls_draw_reference_subplot" -x -v
```

Expected: **FAIL** — `assert mock_draw_ref.called` fails because `_draw_reference_subplot` is not yet called from `update_plot`.

---

### Task 2: Implement the fix

**Files:**
- Modify: `tools/loggereditor.py:616`

- [ ] **Step 3: Add the call in `update_plot()`**

In `tools/loggereditor.py`, find `update_plot()`. The relevant section currently reads:

```python
        handles, labels = self._draw_series()

        self.plot_or_update_selected_line()

        self._finish_plot(handles, labels)

        if last_used_obsid == self.obsid:
```

Change it to:

```python
        handles, labels = self._draw_series()

        self.plot_or_update_selected_line()

        self._finish_plot(handles, labels)
        self._draw_reference_subplot()

        if last_used_obsid == self.obsid:
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
python3 -m pytest test/test_wlevels_calc_calibr.py -k "test_update_plot_calls_draw_reference_subplot" -x -v
```

Expected: **PASS**

- [ ] **Step 5: Run the full loggereditor test file to check for regressions**

```bash
python3 -m pytest test/test_wlevels_calc_calibr.py test/test_loggereditor_refseries.py -x -v
```

Expected: all tests **PASS**

- [ ] **Step 6: Run ruff and commit**

```bash
ruff check --fix tools/loggereditor.py test/test_wlevels_calc_calibr.py
ruff format tools/loggereditor.py test/test_wlevels_calc_calibr.py
git add tools/loggereditor.py test/test_wlevels_calc_calibr.py
git commit -m "feat(loggereditor): refresh reference series subplot on Update plot"
```
