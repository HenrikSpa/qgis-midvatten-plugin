# Quick Wins Slice 1 (Maintainability Plan Items 1–4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the `calc_mean_diff()` NaN-filter bug and land the three zero-risk cleanups (decorator metadata, Piper combobox dedup, dead commented-out code) from the 2026-06-10 maintainability review.

**Architecture:** Five independent, behavior-preserving changes (one is a deliberate bug fix) to existing modules — no new files except tests added to `test/test_midvatten_utils.py` and a new `test/test_midvsettingsdialog.py`. Each task is TDD where a test is meaningful, straight deletion where code is dead.

**Tech Stack:** Python 3, pytest, numpy, PyQt/QGIS (tests run inside the QGIS-enabled venv). Use `python3`, never `python`.

**Before starting:** Create an isolated worktree via the `superpowers:using-git-worktrees` skill (CLAUDE.md requirement). If reusing an older worktree, `git merge ai_test` first so `_pkgroot/` + root `conftest.py` exist. NEVER repoint `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/midvatten`.

**After all tasks:** Invoke the `simplify` skill on the changed code (CLAUDE.md requirement).

**Parent plan:** `docs/superpowers/plans/2026-06-10-maintainability-refactor-review.md` (items 1–4). Constraints that apply here: none of these files are on the midv_addons contract surface *except* `common_utils` — Task 1 and Task 2 only change function internals/metadata, never names or signatures, so the contract holds.

---

### Task 1: Fix `calc_mean_diff()` NaN filter

The condition `if not math.isnan(m) or math.isnan(val)` is wrong: a NaN `val` passes
the filter, poisons the list with NaN, and `np.mean` returns NaN — so one bad
measurement makes the whole logger calibration fail with "no matched measurements".
The docstring states the intent: "Nan-values are excluded from the mean."

Sole caller is `Calibrlogger` in `tools/loggereditor.py:2987`, which already handles a
NaN return (pops "no matched measurements" info). After the fix, mixed lists (some NaN
pairs, some valid) produce a usable mean from the valid pairs instead of failing;
all-NaN lists still return NaN, so the caller's fallback path is preserved.

**Files:**
- Modify: `tools/utils/common_utils.py:155-169` (function `calc_mean_diff`)
- Test: `test/test_midvatten_utils.py` (append at end of file)

- [ ] **Step 1: Write the failing tests**

Append to `test/test_midvatten_utils.py`:

```python
@pytest.mark.active
class TestCalcMeanDiff:
    def test_basic_mean(self):
        assert common_utils.calc_mean_diff([(5, 2), (8, 1)]) == 5.0

    def test_nan_val_pairs_are_excluded(self):
        # A NaN in either position must not poison the mean.
        result = common_utils.calc_mean_diff(
            [(5, 2), (8, 1), (float("nan"), 3), (4, float("nan"))]
        )
        assert result == 5.0

    def test_all_nan_returns_nan(self):
        result = common_utils.calc_mean_diff([(float("nan"), float("nan"))])
        assert math.isnan(result)
```

Check the imports at the top of `test/test_midvatten_utils.py`; ensure these exist
(add any that are missing):

```python
import math
import pytest
from midvatten.tools.utils import common_utils
```

- [ ] **Step 2: Run tests to verify the new one fails**

Run: `python3 -m pytest test/test_midvatten_utils.py::TestCalcMeanDiff -v`
Expected: `test_nan_val_pairs_are_excluded` FAILS (result is nan, not 5.0);
`test_basic_mean` and `test_all_nan_returns_nan` PASS.

- [ ] **Step 3: Fix the condition**

In `tools/utils/common_utils.py`, replace:

```python
    return np.mean(
        [
            float(m) - float(val)
            for m, val in coupled_vals
            if not math.isnan(m) or math.isnan(val)
        ]
    )
```

with:

```python
    return np.mean(
        [
            float(m) - float(val)
            for m, val in coupled_vals
            if not (math.isnan(m) or math.isnan(val))
        ]
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest test/test_midvatten_utils.py::TestCalcMeanDiff -v`
Expected: all 3 PASS. (`test_all_nan_returns_nan` may print a numpy
"Mean of empty slice" RuntimeWarning — that is pre-existing behavior, fine.)

- [ ] **Step 5: Run the calibration test file (covers the only caller)**

Run: `python3 -m pytest test/test_wlevels_calc_calibr.py -x -q`
Expected: PASS (no reference data involves NaN measurement pairs; if anything fails
here, stop and investigate — do NOT change test reference data).

- [ ] **Step 6: Commit**

```bash
git add tools/utils/common_utils.py test/test_midvatten_utils.py
git commit -m "fix: calc_mean_diff no longer lets NaN pairs poison the mean"
```

---

### Task 2: `@wraps` on `general_exception_handler`

The decorator (`tools/utils/common_utils.py:481-515`) loses `__name__`/`__doc__` of
wrapped functions, which garbles tracebacks, logs, and mock patching. `wraps` is
already imported at `common_utils.py:30` (`from functools import wraps`).

**Files:**
- Modify: `tools/utils/common_utils.py:492` (inner `new_func` of `general_exception_handler`)
- Test: `test/test_midvatten_utils.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `test/test_midvatten_utils.py`:

```python
@pytest.mark.active
class TestDecoratorMetadata:
    def test_general_exception_handler_preserves_metadata(self):
        @common_utils.general_exception_handler
        def my_decorated_func():
            """My docstring."""

        assert my_decorated_func.__name__ == "my_decorated_func"
        assert my_decorated_func.__doc__ == "My docstring."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest "test/test_midvatten_utils.py::TestDecoratorMetadata::test_general_exception_handler_preserves_metadata" -v`
Expected: FAIL with `assert 'new_func' == 'my_decorated_func'`

- [ ] **Step 3: Apply `@wraps`**

In `tools/utils/common_utils.py`, inside `general_exception_handler`, replace:

```python
    def new_func(*args, **kwargs):
```

with:

```python
    @wraps(func)
    def new_func(*args, **kwargs):
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest "test/test_midvatten_utils.py::TestDecoratorMetadata::test_general_exception_handler_preserves_metadata" -v`
Expected: PASS

- [ ] **Step 5: Run the module's test file (the decorator is used throughout)**

Run: `python3 -m pytest test/test_midvatten_utils.py -x -q`
Expected: PASS. If a test fails on a mock target name, that test was depending on
the broken metadata — fix the test's patch target, not the decorator.

- [ ] **Step 6: Commit**

```bash
git add tools/utils/common_utils.py test/test_midvatten_utils.py
git commit -m "fix: preserve wrapped-function metadata in general_exception_handler"
```

---

### Task 3: `@wraps` on `if_connection_ok`

Same fix for `tools/utils/db_utils/execution.py:134-142`. This module does NOT yet
import `wraps`.

**Files:**
- Modify: `tools/utils/db_utils/execution.py` (imports + `func_wrapper` at line 137)
- Test: `test/test_midvatten_utils.py` (append to `TestDecoratorMetadata`)

- [ ] **Step 1: Write the failing test**

Add to the top of `test/test_midvatten_utils.py` (module-level — project rule: no
imports inside functions):

```python
from midvatten.tools.utils.db_utils import execution
```

Then append inside the `TestDecoratorMetadata` class (create the class as shown in
Task 2 Step 1 if Task 2 has not run yet):

```python
    def test_if_connection_ok_preserves_metadata(self):
        @execution.if_connection_ok
        def my_db_func():
            """Db docstring."""

        assert my_db_func.__name__ == "my_db_func"
        assert my_db_func.__doc__ == "Db docstring."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest "test/test_midvatten_utils.py::TestDecoratorMetadata::test_if_connection_ok_preserves_metadata" -v`
Expected: FAIL with `assert 'func_wrapper' == 'my_db_func'`

- [ ] **Step 3: Apply `@wraps`**

In `tools/utils/db_utils/execution.py`, add to the import block at the top of the
file (module-level, alphabetical position among stdlib imports):

```python
from functools import wraps
```

Then inside `if_connection_ok`, replace:

```python
    def func_wrapper(*args, **kwargs):
```

with:

```python
    @wraps(func)
    def func_wrapper(*args, **kwargs):
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest "test/test_midvatten_utils.py::TestDecoratorMetadata::test_if_connection_ok_preserves_metadata" -v`
Expected: PASS

- [ ] **Step 5: Run the db_utils test files**

Run: `python3 -m pytest test/test_db_utils.py -x -q` (if that file doesn't exist,
run `python3 -m pytest test/ -k db_utils -x -q`)
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tools/utils/db_utils/execution.py test/test_midvatten_utils.py
git commit -m "fix: preserve wrapped-function metadata in if_connection_ok"
```

---

### Task 4: Deduplicate Piper combobox loading

`midvsettingsdialog.py:312-338` (`MidvattenSettingsDock.load_and_select_last_piper_settings`)
repeats the same findText/setCurrentIndex block 8 times (param_cl, param_hco3,
param_so4, param_na, param_k, param_ca, param_mg, marker_combo_box). Replace with a
data-driven loop. Behavior contract: for each pair, look up the saved setting text in
the combobox; if found (index >= 0), select it; if not found, leave the combobox
untouched.

No existing test imports `midvsettingsdialog`, so add a focused unit test that calls
the unbound method on a stub — this tests the exact contract without needing a full
QGIS dock widget.

**Files:**
- Modify: `midvsettingsdialog.py:312-338`
- Test: Create `test/test_midvsettingsdialog.py`

- [ ] **Step 1: Write the test (passes against OLD code too — this is a refactor lock)**

Create `test/test_midvsettingsdialog.py`:

```python
"""Tests for midvsettingsdialog.MidvattenSettingsDock helpers."""

from unittest import mock

import pytest

from midvatten.midvsettingsdialog import MidvattenSettingsDock


class ComboStub:
    """Mimics the QComboBox subset used by load_and_select_last_piper_settings."""

    def __init__(self, items):
        self.items = items
        self.current_index = -99  # sentinel: untouched

    def findText(self, text):
        try:
            return self.items.index(text)
        except ValueError:
            return -1

    def setCurrentIndex(self, index):
        self.current_index = index


@pytest.mark.active
class TestLoadAndSelectLastPiperSettings:
    def _make_stub_dock(self, settingsdict):
        dock = mock.Mock(spec=[])
        dock.ms = mock.Mock(spec=["settingsdict"])
        dock.ms.settingsdict = settingsdict
        dock.param_cl = ComboStub(["", "cl_col"])
        dock.param_hco3 = ComboStub(["", "hco3_col"])
        dock.param_so4 = ComboStub(["", "so4_col"])
        dock.param_na = ComboStub(["", "na_col"])
        dock.param_k = ComboStub(["", "k_col"])
        dock.param_ca = ComboStub(["", "ca_col"])
        dock.param_mg = ComboStub(["", "mg_col"])
        dock.marker_combo_box = ComboStub(["", "obsid"])
        return dock

    def test_found_settings_are_selected(self):
        dock = self._make_stub_dock(
            {
                "piper_cl": "cl_col",
                "piper_hco3": "hco3_col",
                "piper_so4": "so4_col",
                "piper_na": "na_col",
                "piper_k": "k_col",
                "piper_ca": "ca_col",
                "piper_mg": "mg_col",
                "piper_markers": "obsid",
            }
        )
        MidvattenSettingsDock.load_and_select_last_piper_settings(dock)
        assert dock.param_cl.current_index == 1
        assert dock.param_hco3.current_index == 1
        assert dock.param_so4.current_index == 1
        assert dock.param_na.current_index == 1
        assert dock.param_k.current_index == 1
        assert dock.param_ca.current_index == 1
        assert dock.param_mg.current_index == 1
        assert dock.marker_combo_box.current_index == 1

    def test_missing_settings_leave_comboboxes_untouched(self):
        dock = self._make_stub_dock(
            {
                "piper_cl": "not_in_combobox",
                "piper_hco3": "hco3_col",
                "piper_so4": "nope",
                "piper_na": "nope",
                "piper_k": "nope",
                "piper_ca": "nope",
                "piper_mg": "nope",
                "piper_markers": "nope",
            }
        )
        MidvattenSettingsDock.load_and_select_last_piper_settings(dock)
        assert dock.param_cl.current_index == -99  # untouched
        assert dock.param_hco3.current_index == 1  # found and set
        assert dock.marker_combo_box.current_index == -99
```

- [ ] **Step 2: Run the test against the OLD implementation**

Run: `python3 -m pytest test/test_midvsettingsdialog.py -v`
Expected: PASS (both tests). This locks the contract before the refactor. If it
fails, the stub doesn't match the real contract — fix the test, not the code.

- [ ] **Step 3: Replace the method body with the loop**

In `midvsettingsdialog.py`, replace the entire method:

```python
    def load_and_select_last_piper_settings(self):
        searchindex = self.param_cl.findText(self.ms.settingsdict["piper_cl"])
        if searchindex >= 0:
            self.param_cl.setCurrentIndex(searchindex)
        searchindex = self.param_hco3.findText(self.ms.settingsdict["piper_hco3"])
        if searchindex >= 0:
            self.param_hco3.setCurrentIndex(searchindex)
        searchindex = self.param_so4.findText(self.ms.settingsdict["piper_so4"])
        if searchindex >= 0:
            self.param_so4.setCurrentIndex(searchindex)
        searchindex = self.param_na.findText(self.ms.settingsdict["piper_na"])
        if searchindex >= 0:
            self.param_na.setCurrentIndex(searchindex)
        searchindex = self.param_k.findText(self.ms.settingsdict["piper_k"])
        if searchindex >= 0:
            self.param_k.setCurrentIndex(searchindex)
        searchindex = self.param_ca.findText(self.ms.settingsdict["piper_ca"])
        if searchindex >= 0:
            self.param_ca.setCurrentIndex(searchindex)
        searchindex = self.param_mg.findText(self.ms.settingsdict["piper_mg"])
        if searchindex >= 0:
            self.param_mg.setCurrentIndex(searchindex)
        searchindex = self.marker_combo_box.findText(
            self.ms.settingsdict["piper_markers"]
        )
        if searchindex >= 0:
            self.marker_combo_box.setCurrentIndex(searchindex)
```

with:

```python
    def load_and_select_last_piper_settings(self):
        setting_comboboxes = (
            ("piper_cl", self.param_cl),
            ("piper_hco3", self.param_hco3),
            ("piper_so4", self.param_so4),
            ("piper_na", self.param_na),
            ("piper_k", self.param_k),
            ("piper_ca", self.param_ca),
            ("piper_mg", self.param_mg),
            ("piper_markers", self.marker_combo_box),
        )
        for setting_key, combobox in setting_comboboxes:
            searchindex = combobox.findText(self.ms.settingsdict[setting_key])
            if searchindex >= 0:
                combobox.setCurrentIndex(searchindex)
```

- [ ] **Step 4: Run the test against the NEW implementation**

Run: `python3 -m pytest test/test_midvsettingsdialog.py -v`
Expected: PASS (same contract, new code).

- [ ] **Step 5: Commit**

```bash
git add midvsettingsdialog.py test/test_midvsettingsdialog.py
git commit -m "refactor: data-driven Piper combobox loading in settings dock"
```

---

### Task 5: Remove dead "Only for dev" block in import_fieldlogger

`tools/import_fieldlogger.py:1675-1685`: a triple-quoted expression statement inside
`WQualFieldImportFields.alter_data()` containing dev-only debug code (with Python 2
`except TypeError, e:` syntax). It never executes. Pure deletion, no test needed
beyond the existing import test file.

**Files:**
- Modify: `tools/import_fieldlogger.py:1675-1685`

- [ ] **Step 1: Delete the block**

In `tools/import_fieldlogger.py`, inside `alter_data`, delete exactly these lines
(the triple-quoted block between `observations = copy.deepcopy(observations)` and
`for observation in observations:`):

```python
        """
        #Only for dev
        adepth_dict = {}
        try:
            for obs in observations:
                midvatten_utils.MessagebarAndLog.info(log_msg="Obs: " + str(obs))
                if obs['parametername'] == self.depth:
                    adepth_dict[obs['date_time']] = obs['value']
        except TypeError, e:
            raise Exception("Obs: " + str(obs) + " e " + str(e))
        """
```

- [ ] **Step 2: Verify the module still compiles and its tests pass**

Run: `python3 -m pytest test/test_import_fieldlogger.py -x -q`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tools/import_fieldlogger.py
git commit -m "chore: drop dead dev-only block from WQualFieldImportFields.alter_data"
```

---

### Task 6: Remove commented-out remnants in drillreport

`tools/drillreport.py` ~lines 75-96: commented-out `Askuser` call and old sleep/timing
code. The *explanatory* comment line ("Due to problems regarding speed…") STAYS — it
documents why `merged_question = True` is hardcoded. Only the dead code lines go.

**Files:**
- Modify: `tools/drillreport.py`

- [ ] **Step 1: Delete the commented-out Askuser code**

In `tools/drillreport.py`, find:

```python
        else:
            # Due to problems regarding speed when opening many tabs, only the merge mode is used.
            # merged_question = midvatten_utils.Askuser(question='YesNo', msg="Do you want to open all drill reports merged on the same tab?\n"
            #                                    "Else they will be opened separately.\n\n(If answering no, creating drill reports for many obsids take 0.2 seconds per obsid.\nIt might fail if the computer is to slow.\nIf it fails, try to select only one obsid at the time)").result
            merged_question = True
```

replace with (keeping the why-comment, dropping the dead call):

```python
        else:
            # Due to problems regarding speed when opening many tabs, only the merge mode is used.
            merged_question = True
```

- [ ] **Step 2: Delete the commented-out sleep block**

In the same file, find:

```python
        else:
            # opened = False
            for obsid in obsids:
                f, rpt = self.open_file(obsid, reportpath)
                self.write_obsid(obsid, rpt, imgpath, logopath, f)
                url_status = self.close_file(f, reportpath)
                # This must be used if many obsids are allowed to used this method.
                # if not opened:
                #    sleep(2)
                #    opened = True
                # else:
                #    sleep(0.2)
```

replace with:

```python
        else:
            for obsid in obsids:
                f, rpt = self.open_file(obsid, reportpath)
                self.write_obsid(obsid, rpt, imgpath, logopath, f)
                url_status = self.close_file(f, reportpath)
```

(Note: if `url_status` is unused after this edit, leave it as-is in this task — ruff
will flag it in Task 7 if it's a new violation; do not widen scope here.)

- [ ] **Step 3: Verify compile + any drillreport tests**

Run: `python3 -c "import ast; ast.parse(open('tools/drillreport.py').read())" && python3 -m pytest test/ -k drillreport -q`
Expected: parse OK; tests PASS (or "no tests ran" if none match — that's fine).

- [ ] **Step 4: Commit**

```bash
git add tools/drillreport.py
git commit -m "chore: remove commented-out Askuser and sleep remnants from drillreport"
```

---

### Task 7: Lint, format, simplify, and full verification

**Files:** all files touched above.

- [ ] **Step 1: Ruff**

Run: `ruff check --fix . && ruff format .`
Expected: no errors (warnings on pre-existing untouched code are out of scope —
only fix issues in files this plan modified). If ruff reformatted anything, re-run
the tests of the affected task.

- [ ] **Step 2: Invoke the `simplify` skill** on the changed files (CLAUDE.md
requirement). Apply only fixes within this slice's files.

- [ ] **Step 3: Run the targeted test set**

Run: `python3 -m pytest test/test_midvatten_utils.py test/test_midvsettingsdialog.py test/test_wlevels_calc_calibr.py test/test_import_fieldlogger.py -q`
Expected: all PASS.

- [ ] **Step 4: Commit any ruff/simplify deltas**

```bash
git add -A
git commit -m "style: ruff + simplify pass over slice 1 changes"
```

(Skip if the working tree is clean.)

- [ ] **Step 5: Hand off** — follow the `superpowers:finishing-a-development-branch`
skill: merge target is `ai_test` (never propose master). Full suite (~33-43 min) runs
at the sprint boundary per project convention, not per-task.
