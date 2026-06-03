# Logger Editor — duplicate-safe save (Plan 1 of 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the Logger Editor save from crashing (and from silently overwriting data) when an obsid contains two rows sharing the same normalized instant, while warning the user instead of blocking the save.

**Architecture:** Add a duplicate-instant detector on the in-memory buffer. In `save_to_db`, diff and write only the rows whose normalized instant is unique; leave duplicated instants untouched in both the buffer and the DB, and emit one warning. Also guard an unrelated empty-list crash in `getlastcalibration`.

**Tech Stack:** Python 3, pandas, PyQt/QGIS, SpatiaLite/PostgreSQL via the project DB abstraction; pytest.

This is Plan 1 of 2. Plan 2 (resolve-duplicates dialog, plot comparison, metadata) builds on the detector added here. Spec: `docs/superpowers/specs/2026-06-03-loggereditor-duplicate-datetime-resolution-design.md`.

---

## File Structure

- Modify: `tools/loggereditor.py`
  - `getlastcalibration` — guard empty list (Task 1).
  - New method `_duplicate_instants` — detection helper (Task 2).
  - `save_to_db` — diff/write on de-duplicated views, warn on skipped instants (Task 3).
  - `_compute_update_statements` — take the buffer to use as a parameter instead of reading `self._buf` (Task 3).
- Test: `test/test_loggereditor_dupes.py` (new) — all tests for this plan.

Reuse the existing test helpers by importing them from `test/test_loggereditor_series.py`:
`_insert_obs_point`, `_insert_logger_row`, `_make_editor_with_buf`.

---

## Task 1: Guard empty-list crash in `getlastcalibration`

Fixes the log line `Getting last calibration failed for obsid Rb0403_L, msg: list index out of range`. The buffered branch already returns `[]` safely; the DB branch returns `lastcalibr` which can be an empty list, and the caller does `self.lastcalibr[0]`. Guard the caller.

**Files:**
- Modify: `tools/loggereditor.py` (the `getlastcalibration` caller around line 996-1002, where `self.lastcalibr[0]` is indexed)
- Test: `test/test_loggereditor_dupes.py`

- [ ] **Step 1: Read the caller**

Run: `grep -n "lastcalibr" tools/loggereditor.py`
Find the block that does `self.lastcalibr = self.getlastcalibration(...)` followed by `self.lastcalibr[0]` indexing, and the `except ... "Getting last calibration failed"` handler. Note the exact surrounding lines.

- [ ] **Step 2: Write the failing test**

```python
def test_getlastcalibration_empty_returns_empty_list(self):
    """DB branch with no calibrated rows must return [] (no IndexError)."""
    _insert_obs_point("rb_empty")
    # row with NULL level_masl -> no calibration available
    db_utils.sql_alter_db(
        "INSERT INTO w_levels_logger (obsid, date_time, head_cm) VALUES (?, ?, ?)",
        all_args=[("rb_empty", "2024-01-01 00:00:00", 100.0)],
    )
    editor = LoggerEditor(self.iface, self.midvatten.ms)
    editor._buf = None  # force the DB branch
    result = editor.getlastcalibration("rb_empty")
    assert result == []
```

- [ ] **Step 3: Run test to verify it passes or fails**

Run: `python3 -m pytest test/test_loggereditor_dupes.py::TestLoggerEditorDupes::test_getlastcalibration_empty_returns_empty_list -x`
Expected: PASS if `getlastcalibration` already returns `[]`; the real bug is at the caller. If it passes, keep it as a regression guard and continue to Step 4 to fix the caller.

- [ ] **Step 4: Guard the caller**

In the caller block, wrap the `self.lastcalibr[0]` access so an empty list is handled. Replace the indexing block (the one inside `try:` that builds `text` from `self.lastcalibr[0][1]` / `self.lastcalibr[0][0]`) so it only runs `if self.lastcalibr:`. Concretely, change:

```python
if self.lastcalibr:
    text = ... f"{self.lastcalibr[0][1]:.3f}", str(self.lastcalibr[0][0]) ...
```

so the formatting only dereferences `self.lastcalibr[0]` when `self.lastcalibr` is truthy. Leave the existing `except` in place as a backstop.

- [ ] **Step 5: Commit**

```bash
git add tools/loggereditor.py test/test_loggereditor_dupes.py
git commit -m "fix: guard empty last-calibration list in loggereditor"
```

---

## Task 2: Duplicate-instant detection helper

**Files:**
- Modify: `tools/loggereditor.py` (add method on `LoggerEditor`)
- Test: `test/test_loggereditor_dupes.py`

- [ ] **Step 1: Write the failing test**

```python
def test_duplicate_instants_detects_repeated_label(self):
    editor = _make_editor_with_buf(
        self.iface, self.midvatten.ms, obsid="rb1",
        dates=["2024-01-01 00:00", "2024-01-01 00:00:00", "2024-01-02 00:00:00"],
        head_values=[1.0, 1.0, 2.0],
        level_values=[10.0, 10.0, 20.0],
        series_ids=[None, None, None],
        sources=["", "", ""], series_buf={},
    )
    dups = editor._duplicate_instants()
    assert len(dups) == 1
    assert dups[0] == pd.Timestamp("2024-01-01 00:00:00")

def test_duplicate_instants_empty_when_clean(self):
    editor = _make_editor_with_buf(
        self.iface, self.midvatten.ms, obsid="rb1",
        dates=["2024-01-01 00:00:00", "2024-01-02 00:00:00"],
        head_values=[1.0, 2.0], level_values=[10.0, 20.0],
        series_ids=[None, None], sources=["", ""], series_buf={},
    )
    assert len(editor._duplicate_instants()) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest test/test_loggereditor_dupes.py -k duplicate_instants -x`
Expected: FAIL with `AttributeError: 'LoggerEditor' object has no attribute '_duplicate_instants'`

- [ ] **Step 3: Implement the helper**

Add to `LoggerEditor` (near the other buffer helpers):

```python
def _duplicate_instants(self) -> pd.DatetimeIndex:
    """Parsed-datetime labels occurring more than once in _buf.

    A repeated label means two rows share the same normalized instant
    (same (obsid, datetime(date_time))) but differ in raw date_time text.
    """
    if self._buf is None or self._buf.empty:
        return pd.DatetimeIndex([])
    dup_mask = self._buf.index.duplicated(keep=False)
    return self._buf.index[dup_mask].unique()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest test/test_loggereditor_dupes.py -k duplicate_instants -x`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/loggereditor.py test/test_loggereditor_dupes.py
git commit -m "feat: add _duplicate_instants detector to loggereditor"
```

---

## Task 3: Duplicate-safe save guard

`save_to_db` must not crash on duplicated instants and must not write them (no twin overwrite). Diff and write on de-duplicated views of the buffers; keep the real `self._buf`/`self._original_buf` intact (duplicates remain for later resolution); warn once.

**Files:**
- Modify: `tools/loggereditor.py` — `save_to_db` and `_compute_update_statements`
- Test: `test/test_loggereditor_dupes.py`

- [ ] **Step 1: Write the failing test (crash + corruption guard)**

```python
@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_save_with_duplicate_instant_does_not_crash_or_corrupt(self, mock_messagebar):
    _insert_obs_point("rb1")
    # Two rows, same normalized instant, different raw text (the twin pair)
    _insert_logger_row("rb1", "2024-01-01 00:00", 100.0, 10.0)
    _insert_logger_row("rb1", "2024-01-01 00:00:00", 100.0, 11.0)
    # One clean row the user will actually edit
    _insert_logger_row("rb1", "2024-01-02 00:00:00", 200.0, 20.0)

    editor = _make_editor_with_buf(
        self.iface, self.midvatten.ms, obsid="rb1",
        dates=["2024-01-01 00:00", "2024-01-01 00:00:00", "2024-01-02 00:00:00"],
        head_values=[1.0, 1.0, 2.0],
        level_values=[10.0, 11.0, 20.0],
        series_ids=[None, None, None],
        sources=["", "", ""], series_buf={},
    )
    # Edit only the clean row
    editor._buf.loc[pd.Timestamp("2024-01-02 00:00:00"), "level_masl"] = 99.0

    result = editor.save_to_db()
    print(f"{mock_messagebar.mock_calls=}")
    assert result is True  # save succeeded, did not crash

    dbconn = db_utils.DbConnectionManager()
    rows = dbconn.execute_and_fetchall(
        "SELECT date_time, level_masl FROM w_levels_logger"
        " WHERE obsid='rb1' ORDER BY date_time"
    )
    dbconn.closedb()
    by_dt = {r[0]: r[1] for r in rows}
    # The clean edit persisted
    assert by_dt["2024-01-02 00:00:00"] == 99.0
    # BOTH twins are untouched (no silent overwrite of either)
    assert by_dt["2024-01-01 00:00"] == 10.0
    assert by_dt["2024-01-01 00:00:00"] == 11.0
    # A warning was emitted about the skipped duplicate
    assert mock_messagebar.warning.called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest test/test_loggereditor_dupes.py -k duplicate_instant_does_not_crash -x`
Expected: FAIL — `save_to_db` returns False (logged `Boolean index has wrong length`) so `result is True` fails, or the warning assert fails.

- [ ] **Step 3: Thread an explicit buffer into `_compute_update_statements`**

Change the signature to take the buffer it should index, instead of reading `self._buf`:

```python
def _compute_update_statements(
    self,
    buf: pd.DataFrame,
    changed_index: pd.DatetimeIndex,
    orig_changed: pd.Series,
    new_changed: pd.Series,
    head_changed: pd.Series,
    obsid: str,
    tbl: str,
    ph: str,
    is_sqlite: bool,
) -> tuple[list[tuple], list[tuple]]:
```

Inside the method, change the single `self._buf` use to the parameter:

```python
        buf_pos = buf.index.get_indexer(changed_index)
```

- [ ] **Step 4: Add the de-duplication guard at the top of `save_to_db` and use local buffers**

Immediately after the early-return guard (`if self._buf is None or self._original_buf is None or self._buf_obsid is None: return False`) and `obsid = self._buf_obsid`, add:

```python
        dup_instants = self._duplicate_instants()
        if len(dup_instants) > 0:
            buf = self._buf[~self._buf.index.duplicated(keep=False)]
            original_buf = self._original_buf[
                ~self._original_buf.index.duplicated(keep=False)
            ]
            sample = ", ".join(d.strftime(_DT_FMT) for d in dup_instants[:5])
            more = "" if len(dup_instants) <= 5 else f" (+{len(dup_instants) - 5} more)"
            common_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "LoggerEditor",
                    "%s duplicate timestamp(s) were skipped while saving."
                    " Resolve duplicates to save edits at those times.",
                )
                % len(dup_instants),
                log_msg="Skipped duplicate instants for obsid %s: %s%s"
                % (obsid, sample, more),
            )
        else:
            buf = self._buf
            original_buf = self._original_buf
```

Then, within `save_to_db`, in the diff-and-write region only (NOT the post-save remap region that starts at `if id_mapping:`), replace reads of `self._buf` with `buf` and `self._original_buf` with `original_buf`. Specifically:

- `deleted_indices = original_buf.index.difference(buf.index)`
- `common_index = original_buf.index.intersection(buf.index)`
- `orig_vals = original_buf.loc[common_index, "level_masl"]`
- `new_vals = buf.loc[common_index, "level_masl"]`
- `head_changed = buf.loc[changed_index, "head_cm_m"]`
- pass `buf` as the new first argument to `_compute_update_statements(buf, changed_index, ...)`
- series CRUD: `new_series = {k: v for k, v in self._series_buf.items() if k < 0 and (buf["series_id"] == k).any()}`
- series_id update section: `common = original_buf.index.intersection(buf.index)`, `orig_sid = original_buf.loc[common, "series_id"]`, `new_sid = buf.loc[common, "series_id"]`, and `raw_sid = buf.loc[dt_idx, "series_id"]`

Leave the post-save block unchanged: `self._buf.loc[...]`, `self._original_buf = self._buf.copy()`, etc. The real buffer keeps its duplicates so Plan 2 can resolve them.

- [ ] **Step 5: Run the new test to verify it passes**

Run: `python3 -m pytest test/test_loggereditor_dupes.py -k duplicate_instant_does_not_crash -x`
Expected: PASS

- [ ] **Step 6: Run the full new test file and the existing logger-editor tests (no regressions)**

Run: `python3 -m pytest test/test_loggereditor_dupes.py test/test_loggereditor_series.py test/test_loggereditor_separation.py -x`
Expected: PASS (the de-dup path is a no-op when there are no duplicates, so existing behavior is unchanged).

- [ ] **Step 7: Lint/format**

Run: `ruff check --fix tools/loggereditor.py test/test_loggereditor_dupes.py && ruff format tools/loggereditor.py test/test_loggereditor_dupes.py`

- [ ] **Step 8: Commit**

```bash
git add tools/loggereditor.py test/test_loggereditor_dupes.py
git commit -m "fix: make loggereditor save duplicate-instant safe (warn, skip, no crash)"
```

---

## Test file scaffold

Create `test/test_loggereditor_dupes.py` with this header (Task 1 adds the first test method into the class body):

```python
"""Tests for LoggerEditor duplicate-instant handling (Plan 1: safe save)."""

import gc
from unittest import mock

import pandas as pd
import pytest

pytest.importorskip("qgis.PyQt")

from midvatten.test import utils_for_tests
from midvatten.tools.loggereditor import LoggerEditor
from midvatten.tools.utils import db_utils
from midvatten.test.test_loggereditor_series import (
    _insert_obs_point,
    _insert_logger_row,
    _make_editor_with_buf,
)


@pytest.mark.spatialite
class TestLoggerEditorDupes(utils_for_tests.MidvattenTestSpatialiteDbSv):
    def teardown_method(self):
        super().teardown_method()
        gc.collect()

    # test methods added per task below
```

---

## Self-Review

**Spec coverage (Plan 1 slice):**
- Crash fix → Task 3. ✓
- No silent twin overwrite → Task 3 test asserts both twins untouched. ✓
- Warn-not-block → Task 3 warning + save still returns True. ✓
- Detection helper (foundation for Plan 2) → Task 2. ✓
- `getlastcalibration` guard → Task 1. ✓
- Resolve dialog / banner / plot comparison / metadata → deferred to Plan 2 (out of scope here). ✓

**Placeholder scan:** none — all steps contain concrete code and commands.

**Type consistency:** `_duplicate_instants` returns `pd.DatetimeIndex` and is consumed via `len(...)` and `.strftime` in Task 3. `_compute_update_statements` gains a leading `buf` parameter; the only call site (in `save_to_db`) is updated to pass `buf` first. Local names `buf`/`original_buf` are defined before first use in both branches of the guard.
