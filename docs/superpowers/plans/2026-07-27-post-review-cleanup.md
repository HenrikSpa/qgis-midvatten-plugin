# Post-Review Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply every maintainability fix identified in the review of commits `cd11468^..55b51e9` (2026-07-20 → 2026-07-23) without changing any user-visible behaviour.

**Architecture:** Three phases in dependency order. Phase 1 is mechanical, behaviour-preserving cleanup (deduplication, dead code, redundant copies) across `tools/import_logger/`, `tools/loggereditor.py`, `tools/import_data_to_db.py`, and `tools/utils/`. Phase 2 decomposes the two oversized methods that Phase 1 has already thinned. Phase 3 replaces the waiting-cursor marker-flag machinery with a reference-counted cursor stack — it has the widest blast radius and is deliberately last so it can be rejected without losing Phases 1–2.

**Tech Stack:** Python 3, pandas, PyQt5/QGIS, pytest, ruff.

## Global Constraints

- Use `python3`, never `python`.
- **This is a refactoring plan. No user-visible behaviour may change**, with exactly two deliberate exceptions, each argued in its own task text: Task 12 part B (the *first* matching `about_db` row wins per table, restoring the `LIMIT 1` semantics that the refactor dropped) and Task 17 (`stop_waiting_cursor()` becomes a no-op at depth 0). Outside those two, every task is green-to-green: the relevant test file passes before the edit and passes unchanged after it.
- **Never weaken or change an existing test's assertion values.** The point is that a refactor must not move its own goalposts. An edit to an existing test is allowed only when it is *value-identical* (e.g. swapping an expression for a provably equal one) or *purely additive* (adding an assertion). Narrowing coverage, relaxing an expectation, or changing an expected value is forbidden. Task 9 additionally swaps which API a test calls, keeping expected values byte-identical. Task 17 must leave the two cursor tests from commit 55b51e9 untouched.
- **Prefer extending existing test coverage over appending a near-duplicate test.** Where a task's brief specifies a new test and an equivalent one already exists, fold the brief's distinguishing assertions into the existing test instead — subject to the rule above. This plan exists to remove duplication; its own tests should not add any.
- **Some new tests are characterization tests and are expected to pass on first run** (Task 1 Step 2, Task 2 Step 2). That is correct for a refactor: they pin existing behaviour *before* it is restructured. Red-then-green applies only where a task adds genuinely new behaviour.
- Run `ruff check --fix` and `ruff format` **on the files the task touched**, before committing — not on `.`. A bare `ruff format .` reformats `tools/utils/matplotlib_replacements.py`, which has pre-existing drift, and sweeps an unrelated file into the task's commit.
- **`ruff check` will NOT find unused imports in this repo.** The config selects only `E,W,N,UP`, so `F401` is off. Any task that deletes code and may orphan an import must verify explicitly with `ruff check --select F401 <files>`. Do not reason about which imports went dead — measure it. (Repo-wide `ruff check` also reports ~297 pre-existing findings plus an `N999` caused by the worktree directory name; only files a task touches need to be clean.)
- Add type hints to all new function/method arguments.
- User-facing strings must use `QCoreApplication.translate("context", "text")`. Reuse the existing context string when moving a string.
- Never build SQL with string concatenation of untrusted values — use `ident()` and DB-API parameter binding.
- Never change database schemas.
- Do not repoint `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/midvatten`.
- **Never use bare `git stash` / `git stash pop`.** The stash stack is shared with the main checkout and every other worktree, and other sessions may push or pop concurrently — a bare `pop` can restore someone else's work into this tree. To check whether something is pre-existing, use `git show HEAD:<path>`, `git diff`, or a scratch copy instead. If a stash is genuinely unavoidable, use `git stash push -u -m "<unique-tag>"`, capture the SHA from `git stash list --format='%H %gs'`, restore with `git stash apply <sha>`, and drop that entry by re-finding it via its tag.
- Commit after every task. Conventional-commit prefixes: `refactor:`, `perf:`, `fix:`, `test:`.

## Prerequisites

- [ ] **Create an isolated worktree before writing any code.** Invoke the `superpowers:using-git-worktrees` skill. Branch from `ai_test`. Do not work directly in `/home/hsai1/dev/midv/midvatten`.
- [ ] **Record the baseline.** In the worktree run:

```bash
python3 -m pytest test/test_import_logger.py test/test_import_logger_pipeline.py \
  test/test_import_logger_workers.py test/test_import_data_to_db.py \
  test/test_file_utils.py test/test_db_utils.py test/test_midvatten_utils.py \
  test/test_wlevels_calc_calibr.py -q 2>&1 | tail -20
```

Expected: all pass. **If anything fails here, stop and report — do not start the plan on a red baseline.** Save the summary line; every task compares against it.

---

# Phase 0 — Unblock the baseline

---

### Task 0: Make HOBO meridiem parsing locale-independent

**Status: DONE** — completed before Phase 1, commit `bf3edf2`.

**Not part of the review cleanup.** This is a correctness fix that had to land first: the Prerequisites baseline came back `6 failed, 436 passed`, and all six failures shared one root cause that blocked the plan.

**The bug:** `fix_date` (`tools/import_logger/parsers.py:45`) normalised HOBO's meridiem suffix to English `"AM"`/`"PM"` and parsed it with `%p`. `%p` is locale-dependent, and Swedish glibc defines no AM/PM strings at all — under `sv_SE.UTF-8` it matches only the empty string and rejects `AM`, `PM`, `fm` and `em` alike. `QgsApplication.initQgis()` sets `LC_TIME` from the user's locale, so this reached real imports: on a Swedish QGIS, every HOBO file with AM/PM timestamps failed with "Dateformat in file %s could not be parsed."

Introduced by `13cdf5a` (2026-07-22), inside the reviewed week. The review that produced this plan was scoped to quality, not correctness, so it did not look for this class of defect.

**The fix:** parse the 12-hour time with the locale-independent `%I` and apply the AM/PM shift in Python, avoiding `%p` entirely.

**Regression cover:** `test_fix_date_meridiem_is_locale_independent` parametrises over `LC_TIME` in `{C, sv_SE.UTF-8}` × `{am, pm, fm, em}` and skips cleanly where the locale is unavailable. Without it, the six existing tests would pass in a C-locale CI whether or not the bug is present.

---

# Phase 1 — Mechanical cleanups

Behaviour-preserving. Each task is independently revertible.

---

### Task 1: Derive the empty logger frame from the column constants

**Problem:** `empty_logger_frame()` re-hardcodes the five column names that `CANONICAL_COLUMNS` / `MEASUREMENT_COLUMNS` define 120 lines above it. Adding a measurement channel means editing two places, and nothing catches the mismatch.

**Files:**
- Modify: `tools/import_logger/models.py:135-145`
- Test: `test/test_import_logger_pipeline.py`

**Interfaces:**
- Consumes: `CANONICAL_COLUMNS`, `MEASUREMENT_COLUMNS` from `models.py:11-18`.
- Produces: `empty_logger_frame() -> pd.DataFrame` — unchanged signature, unchanged output.

- [ ] **Step 1: Write the failing test**

Append to `test/test_import_logger_pipeline.py`:

```python
def test_empty_logger_frame_follows_the_column_constants():
    frame = empty_logger_frame()
    assert tuple(frame.columns) == CANONICAL_COLUMNS
    assert str(frame["date_time"].dtype) == "datetime64[ns]"
    assert all(
        str(frame[column].dtype) == "float64" for column in MEASUREMENT_COLUMNS
    )
    assert len(frame) == 0
```

`MEASUREMENT_COLUMNS` is not yet imported by that test file. Extend the existing import block at `test/test_import_logger_pipeline.py:16-23`:

```python
from midvatten.tools.import_logger.models import (
    CANONICAL_COLUMNS,
    MEASUREMENT_COLUMNS,
    METEO_COLUMNS,
    LoggerDataKind,
    LoggerImportOptions,
    ParsedLoggerFile,
    empty_logger_frame,
)
```

- [ ] **Step 2: Run the test — it should PASS against the current code**

Run: `python3 -m pytest test/test_import_logger_pipeline.py::test_empty_logger_frame_follows_the_column_constants -v`
Expected: PASS. This is a characterization test — it pins the contract *before* the refactor so the refactor cannot silently break it.

- [ ] **Step 3: Rewrite the function to derive its schema**

Replace `tools/import_logger/models.py:135-145` with:

```python
def empty_logger_frame() -> pd.DataFrame:
    """Return an empty frame with the canonical logger schema and dtypes."""
    return pd.DataFrame(
        {
            "date_time": pd.Series(dtype="datetime64[ns]"),
            **{
                column: pd.Series(dtype="float64")
                for column in MEASUREMENT_COLUMNS
            },
        }
    )
```

Dict literals preserve insertion order, and `MEASUREMENT_COLUMNS is CANONICAL_COLUMNS[1:]`, so the resulting column order is exactly `CANONICAL_COLUMNS`.

- [ ] **Step 4: Run the tests**

Run: `python3 -m pytest test/test_import_logger_pipeline.py test/test_import_logger.py -q`
Expected: all pass.

- [ ] **Step 5: Format and commit**

```bash
ruff check --fix . && ruff format .
git add tools/import_logger/models.py test/test_import_logger_pipeline.py
git commit -m "refactor: derive empty logger frame from column constants"
```

---

### Task 2: Stop copying logger frames that are already fresh copies

**Problem:** `_copy_with_data` does `data.reset_index(drop=True).copy()`, but it is applied to frames that `filter_date_window` and `drop_missing_water_head` already returned as `.reset_index(drop=True).copy()`. A water-level file makes 5 full-frame copies where 3 suffice. Separately, `filter_after_latest_date` and `baro_to_meteo` call `validate_logger_frame(data.loc[:, CANONICAL_COLUMNS])` — materialising a five-column copy of the whole frame purely to validate it.

**Files:**
- Modify: `tools/import_logger/pipeline.py:50-81` (validator + copy helpers), `:303-343` (the two `.loc` validations), `:378-395` (`run_pre_resolution_pipeline`)
- Test: `test/test_import_logger_pipeline.py`

**Interfaces:**
- Consumes: `ParsedLoggerFile` from `models.py:47`.
- Produces:
  - `validate_logger_frame(data: pd.DataFrame, *, allow_extra_columns: bool = False) -> None`
  - `_with_data(parsed: ParsedLoggerFile, data: pd.DataFrame) -> ParsedLoggerFile` — replaces the frame without copying it. For frames the callee just produced.
  - `_copy_with_data(parsed: ParsedLoggerFile, data: pd.DataFrame) -> ParsedLoggerFile` — unchanged; still used where the frame may be caller-owned.

- [ ] **Step 1: Write the characterization test**

Append to `test/test_import_logger_pipeline.py`:

```python
def _water_level_file(rows: int = 4) -> ParsedLoggerFile:
    return ParsedLoggerFile(
        data=pd.DataFrame(
            {
                "date_time": pd.to_datetime(
                    [f"2025-01-0{index + 1} 00:00:00" for index in range(rows)]
                ),
                "head_cm": [1.0, float("nan"), 3.0, 4.0],
                "temp_degc": [10.0, 11.0, 12.0, 13.0],
                "cond_mscm": [float("nan")] * rows,
                "baro_cmh2o": [float("nan")] * rows,
            }
        ),
        filename="a.mon",
        source_path="/tmp/a.mon",
        kind=LoggerDataKind.WATER_LEVEL,
        location="loc",
        serial_number="123",
    )


def test_pre_resolution_pipeline_does_not_alias_the_input_frame():
    parsed = _water_level_file()
    original = parsed.data.copy()

    result = run_pre_resolution_pipeline(
        parsed, LoggerImportOptions(skip_missing_water_head=True)
    )

    assert result.data is not parsed.data
    result.data.loc[0, "head_cm"] = 999.0
    assert_frame_equal(parsed.data, original)


def test_pre_resolution_pipeline_drops_missing_head_only_for_water_level():
    water = run_pre_resolution_pipeline(
        _water_level_file(), LoggerImportOptions(skip_missing_water_head=True)
    )
    assert water.data["head_cm"].tolist() == [1.0, 3.0, 4.0]

    baro = _water_level_file()
    baro = ParsedLoggerFile(
        data=baro.data,
        filename=baro.filename,
        source_path=baro.source_path,
        kind=LoggerDataKind.BAROMETRIC,
        location=baro.location,
        serial_number=baro.serial_number,
    )
    result = run_pre_resolution_pipeline(
        baro, LoggerImportOptions(skip_missing_water_head=True)
    )
    assert len(result.data) == 4
```

- [ ] **Step 2: Run it against current code**

Run: `python3 -m pytest test/test_import_logger_pipeline.py -k "does_not_alias or drops_missing_head_only" -v`
Expected: PASS. These pin the two properties the refactor must not break: no aliasing of the caller's frame, and baro files keep their null-head rows.

- [ ] **Step 3: Add `allow_extra_columns` to the validator**

Replace `tools/import_logger/pipeline.py:50-58` (the opening of `validate_logger_frame`) with:

```python
def validate_logger_frame(
    data: pd.DataFrame, *, allow_extra_columns: bool = False
) -> None:
    """Raise when *data* does not satisfy the canonical parser-frame contract.

    With ``allow_extra_columns`` the frame may carry additional trailing
    columns (e.g. ``obsid``) as long as it *starts* with the canonical ones.
    This lets post-resolution callers validate in place instead of slicing a
    full copy of the frame just to check it.
    """
    if not isinstance(data, pd.DataFrame):
        raise LoggerPipelineError("logger data must be a pandas DataFrame")
    columns = tuple(data.columns)
    if allow_extra_columns:
        if columns[: len(CANONICAL_COLUMNS)] != CANONICAL_COLUMNS:
            raise LoggerPipelineError(
                f"logger columns must start with {CANONICAL_COLUMNS!r}, got "
                f"{columns!r}"
            )
    elif columns != CANONICAL_COLUMNS:
        raise LoggerPipelineError(
            f"logger columns must be exactly {CANONICAL_COLUMNS!r}, got "
            f"{columns!r}"
        )
```

Leave the rest of the function (`:59-77`, the uniqueness / index / dtype / NaT checks) exactly as it is.

- [ ] **Step 4: Add the non-copying `_with_data` helper**

Insert immediately after `_copy_with_data` at `tools/import_logger/pipeline.py:81`:

```python
def _with_data(parsed: ParsedLoggerFile, data: pd.DataFrame) -> ParsedLoggerFile:
    """Attach a frame the callee just built. No defensive copy is needed."""
    return replace(parsed, data=data)
```

- [ ] **Step 5: Validate in place instead of slicing**

At `tools/import_logger/pipeline.py:309`, change:

```python
    validate_logger_frame(data.loc[:, CANONICAL_COLUMNS])
```

to:

```python
    validate_logger_frame(data, allow_extra_columns=True)
```

At `tools/import_logger/pipeline.py:324`, make the identical change inside `baro_to_meteo`.

- [ ] **Step 6: Remove the redundant copies from the pre-resolution pipeline**

Replace `tools/import_logger/pipeline.py:378-395` with:

```python
def run_pre_resolution_pipeline(
    parsed: ParsedLoggerFile,
    options: LoggerImportOptions,
) -> ParsedLoggerFile:
    """Run every shared transform that precedes interactive obsid resolution."""
    validate_logger_frame(parsed.data)
    result = normalize_timezone(parsed, options.target_timezone)
    # filter_date_window and drop_missing_water_head each return a fresh,
    # range-indexed copy, so _with_data must not copy a second time.
    result = _with_data(
        result,
        filter_date_window(result.data, options.from_date, options.to_date),
    )
    if options.skip_missing_water_head and result.kind is LoggerDataKind.WATER_LEVEL:
        result = _with_data(result, drop_missing_water_head(result.data))
    validate_logger_frame(result.data)
    return result
```

- [ ] **Step 7: Delete the now-unused missing-head registry**

Delete `tools/import_logger/pipeline.py:369-375` entirely:

```python
_MISSING_HEAD_POLICIES: Mapping[
    LoggerDataKind,
    Callable[[pd.DataFrame], pd.DataFrame],
] = {
    LoggerDataKind.WATER_LEVEL: drop_missing_water_head,
    LoggerDataKind.BAROMETRIC: lambda data: data.reset_index(drop=True).copy(),
}
```

The barometric entry was a no-op copy; the explicit `result.kind is LoggerDataKind.WATER_LEVEL` check in Step 6 replaces the whole table and saves two full-frame copies per barometric file.

- [ ] **Step 8: Run the tests**

Run: `python3 -m pytest test/test_import_logger_pipeline.py test/test_import_logger.py test/test_import_logger_workers.py -q`
Expected: all pass.

- [ ] **Step 9: Format and commit**

```bash
ruff check --fix . && ruff format .
git add tools/import_logger/pipeline.py test/test_import_logger_pipeline.py
git commit -m "perf: stop re-copying logger frames in the pre-resolution pipeline"
```

---

### Task 3: Collapse the destination-preparer registry

**Problem:** `_DESTINATION_PREPARERS` maps a two-member enum to two functions, one of which (`_water_destination`) exists solely to discard the two arguments it is handed. Three lookup tables keyed on `LoggerDataKind` is more indirection than a two-way branch earns.

**Files:**
- Modify: `tools/import_logger/pipeline.py:346-368` (delete), `:398-420` (`run_post_resolution_pipeline`)
- Test: `test/test_import_logger_pipeline.py` (existing coverage)

**Interfaces:**
- Consumes: `baro_to_meteo`, `WATER_LEVEL_COLUMNS`, `LoggerDataKind`.
- Produces: `run_post_resolution_pipeline(...)` — unchanged signature and output.

- [ ] **Step 1: Confirm existing coverage is green**

Run: `python3 -m pytest test/test_import_logger_pipeline.py -k "post_resolution" -v`
Expected: PASS. Note how many tests ran; the same set must pass at the end.

- [ ] **Step 2: Delete the wrappers and the registry**

Delete `tools/import_logger/pipeline.py:346-368` entirely — that is `_water_destination`, `_barometric_destination`, and `_DESTINATION_PREPARERS`.

- [ ] **Step 3: Branch inline in the post-resolution pipeline**

In `tools/import_logger/pipeline.py`, replace the line currently reading:

```python
    destination = _DESTINATION_PREPARERS[parsed.kind](data, obsid, instrumentid)
```

with:

```python
    if parsed.kind is LoggerDataKind.BAROMETRIC:
        destination = baro_to_meteo(data, obsid, instrumentid)
    else:
        destination = data.loc[:, WATER_LEVEL_COLUMNS].copy()
```

- [ ] **Step 4: Drop imports that are now unused**

`Callable` (from `typing`) is no longer referenced in `pipeline.py` once `_DESTINATION_PREPARERS` and `_MISSING_HEAD_POLICIES` are gone. Remove it from the import at `tools/import_logger/pipeline.py:8`. `Mapping` is still used by `parse_latest_dates` and `filter_after_latest_date` — keep it. Let `ruff check --fix .` confirm; do not guess.

- [ ] **Step 5: Run the tests**

Run: `python3 -m pytest test/test_import_logger_pipeline.py test/test_import_logger.py -q`
Expected: all pass, same count as Step 1 for the `post_resolution` subset.

- [ ] **Step 6: Format and commit**

```bash
ruff check --fix . && ruff format .
git add tools/import_logger/pipeline.py
git commit -m "refactor: branch on logger kind instead of a two-entry registry"
```

---

### Task 4: Replace the "no non-duplicate rows" magic string

**Problem:** `workers.py` builds the literal `"no non-duplicate rows"` in two places and `importer.py:869` matches it with `==`. A typo in either module silently reclassifies a successful skip as a database failure, and nothing fails.

**Files:**
- Modify: `tools/import_logger/models.py` (add constant), `tools/import_logger/workers.py:216-240`, `tools/import_logger/importer.py:869`
- Test: `test/test_import_logger_workers.py`

**Interfaces:**
- Produces: `models.NO_NEW_ROWS_REASON: str` — the single source of the reason text, imported by both `workers.py` and `importer.py`.

- [ ] **Step 1: Write the failing test**

Append to `test/test_import_logger_workers.py`:

```python
def test_no_new_rows_reason_is_shared_between_worker_and_dialog():
    from midvatten.tools.import_logger import importer, models, workers

    assert models.NO_NEW_ROWS_REASON == "no non-duplicate rows"
    assert workers.NO_NEW_ROWS_REASON is models.NO_NEW_ROWS_REASON
    assert importer.NO_NEW_ROWS_REASON is models.NO_NEW_ROWS_REASON
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest test/test_import_logger_workers.py::test_no_new_rows_reason_is_shared_between_worker_and_dialog -v`
Expected: FAIL with `AttributeError: module 'midvatten.tools.import_logger.models' has no attribute 'NO_NEW_ROWS_REASON'`.

- [ ] **Step 3: Add the constant**

Insert into `tools/import_logger/models.py` immediately after the `METEO_COLUMNS` tuple (after line 33):

```python
# Reason recorded when every row in a file was already present in the database.
# Shared so the dialog can classify the outcome without matching on prose.
NO_NEW_ROWS_REASON = "no non-duplicate rows"
```

- [ ] **Step 4: Use it in the worker and collapse the duplicated branches**

In `tools/import_logger/workers.py`, add `NO_NEW_ROWS_REASON` to the `models` import block at lines 15-23 (keep the list alphabetically ordered as it already is):

```python
from midvatten.tools.import_logger.models import (
    NO_NEW_ROWS_REASON,
    LoggerDbImportRequest,
    LoggerDbImportResult,
    LoggerFileFailure,
    LoggerImportOptions,
    LoggerParseBatchResult,
    LoggerParseRequest,
    ParsedLoggerFile,
)
```

Then replace `tools/import_logger/workers.py:216-240` (from `self._check_cancelled()` after `general_import` down to the end of the `elif inserted_count == 0:` block) with:

```python
                self._check_cancelled()
                has_new_rows = inserted_count > 0
                if series_id is not None:
                    placeholder = connection.placeholder()
                    count = connection.execute_and_fetchall(
                        "SELECT COUNT(*) FROM w_levels_logger "
                        f"WHERE series_id = {placeholder}",
                        (series_id,),
                    )[0][0]
                    has_new_rows = has_new_rows and count > 0
                    if not has_new_rows:
                        connection.execute(
                            f"DELETE FROM w_logger_series WHERE id = {placeholder}",
                            (series_id,),
                        )
                if has_new_rows:
                    result = LoggerDbImportResult(self.request.filename, True)
                else:
                    result = LoggerDbImportResult(
                        self.request.filename, False, NO_NEW_ROWS_REASON
                    )
```

This preserves the original logic exactly: the series row is deleted when either `inserted_count == 0` or the series has no rows, and the "no new rows" outcome is reported for both the series and non-series paths.

- [ ] **Step 5: Use it in the dialog**

In `tools/import_logger/importer.py`, add `NO_NEW_ROWS_REASON` to the `.models` import block at lines 40-51:

```python
from .models import (
    NO_NEW_ROWS_REASON,
    LoggerDataKind,
    LoggerDbImportRequest,
    LoggerDbImportResult,
    LoggerFileFailure,
    LoggerImportOptions,
    LoggerParseBatchResult,
    LoggerParseRequest,
    LoggerSchemaCapabilities,
    LoggerSeriesSpec,
    PreparedLoggerFile,
)
```

Then at `tools/import_logger/importer.py:869` change:

```python
                    elif result.reason == "no non-duplicate rows":
```

to:

```python
                    elif result.reason == NO_NEW_ROWS_REASON:
```

- [ ] **Step 6: Run the tests**

Run: `python3 -m pytest test/test_import_logger_workers.py test/test_import_logger.py -q`
Expected: all pass, including the new test.

- [ ] **Step 7: Format and commit**

```bash
ruff check --fix . && ruff format .
git add tools/import_logger/models.py tools/import_logger/workers.py \
  tools/import_logger/importer.py test/test_import_logger_workers.py
git commit -m "refactor: share the no-new-rows reason constant"
```

---

### Task 5: Publish the baro meteo parameters and move their seeding out of `start_import`

**Problem:** `importer.py:54` imports `_BARO_METEO_PARAMS` — a private name — across a module boundary, and the `zz_meteoparam` seeding loop sits inline inside the 275-line `start_import`. The constant is configuration data, not a pipeline transform, and the seeding is a database operation living in a GUI method.

**Files:**
- Modify: `tools/import_logger/models.py` (add constant), `tools/import_logger/pipeline.py:34-35` (remove), `tools/import_logger/importer.py:53-59` (imports), `:817-839` (extract)
- Test: `test/test_import_logger.py`

**Interfaces:**
- Consumes: `db_utils.DbConnectionManager`.
- Produces:
  - `models.BARO_METEO_PARAMS: tuple[tuple[str, str], ...]`
  - `LoggerImport._ensure_baro_meteo_parameters(self) -> None` — opens its own connection, inserts any missing `zz_meteoparam` rows, always closes.

- [ ] **Step 1: Move the constant to `models.py`**

Delete `tools/import_logger/pipeline.py:34-35`:

```python
# Parameters that must exist in zz_meteoparam for barometric imports.
_BARO_METEO_PARAMS: tuple[tuple[str, str], ...] = (("pressure", "Barometric pressure"),)
```

Add to `tools/import_logger/models.py`, immediately after `NO_NEW_ROWS_REASON` from Task 4:

```python
# Parameters that must exist in zz_meteoparam before a barometric import.
BARO_METEO_PARAMS: tuple[tuple[str, str], ...] = (("pressure", "Barometric pressure"),)
```

- [ ] **Step 2: Fix the importer's imports**

In `tools/import_logger/importer.py`, remove `_BARO_METEO_PARAMS` from the `.pipeline` import at lines 53-59, leaving:

```python
from .pipeline import (
    InvalidLatestDateError,
    parse_latest_dates,
    run_post_resolution_pipeline,
    write_logger_csv,
)
```

and add `BARO_METEO_PARAMS` to the `.models` import block edited in Task 4 (first entry, before `NO_NEW_ROWS_REASON`).

- [ ] **Step 3: Extract the seeding into a method**

Add this method to `LoggerImport`, immediately before `start_import` (i.e. before the `@common_utils.general_exception_handler` decorator at `tools/import_logger/importer.py:626`):

```python
    def _ensure_baro_meteo_parameters(self) -> None:
        """Insert any zz_meteoparam rows a barometric import depends on."""
        connection = db_utils.DbConnectionManager()
        try:
            placeholder = connection.placeholder()
            with connection.transaction():
                for parameter, explanation in BARO_METEO_PARAMS:
                    existing = connection.execute_and_fetchall(
                        "SELECT parameter FROM zz_meteoparam "
                        f"WHERE parameter = {placeholder}",
                        (parameter,),
                    )
                    if not existing:
                        connection.execute(
                            "INSERT INTO zz_meteoparam(parameter, explanation) "
                            f"VALUES ({placeholder}, {placeholder})",
                            (parameter, explanation),
                        )
        finally:
            connection.closedb()
```

- [ ] **Step 4: Call it from `start_import`**

Replace `tools/import_logger/importer.py:817-839` (the whole `if import_to_db and any(...)` block through its `finally: connection.closedb()`) with:

```python
            if import_to_db and any(
                prepared.kind is LoggerDataKind.BAROMETRIC
                for prepared in prepared_files
            ):
                self._ensure_baro_meteo_parameters()
```

- [ ] **Step 5: Run the tests**

Run: `python3 -m pytest test/test_import_logger.py test/test_import_logger_pipeline.py -q`
Expected: all pass.

- [ ] **Step 6: Format and commit**

```bash
ruff check --fix . && ruff format .
git add tools/import_logger/models.py tools/import_logger/pipeline.py \
  tools/import_logger/importer.py
git commit -m "refactor: move baro meteo parameter seeding out of start_import"
```

---

### Task 6: Unify the two UTC-offset section builders and the two button lambdas

**Problem:** `_build_diveroffice_section` and `_build_diveroffice_baro_section` are 65 lines that differ only in which attribute the combobox is stored on — same label text, same tooltip, same `range(-12, 15)`, same `set_combobox` call. Separately, the `start_import_button` and `export_csv_button` lambdas pass eight identical arguments and differ only in two booleans.

**Files:**
- Modify: `tools/import_logger/importer.py:185-189` (call sites), `:288-318` (button lambdas), `:375-439` (the two builders)
- Test: `test/test_import_logger.py`

**Interfaces:**
- Produces:
  - `LoggerImport._build_utc_offset_section(self, database_timezone: str | None) -> tuple[QtWidgets.QWidget, QtWidgets.QComboBox, QtWidgets.QLabel, RowEntry]` — builds the section, calls `self.add_row(section)`, returns `(section, combobox, label, row)`.
  - `LoggerImport._start_import_from_gui(self, *, export_csv: bool, import_to_db: bool)` — reads the current widget state and delegates to `start_import`.
- The public attributes `self._diveroffice_section`, `self._diveroffice_baro_section`, `self.utc_offset`, `self.baro_utc_offset`, `self.utcoffset_label`, `self.utcoffset_row` keep their existing names and meanings.

- [ ] **Step 1: Confirm existing dialog coverage is green**

Run: `python3 -m pytest test/test_import_logger.py -q`
Expected: PASS. Record the test count.

- [ ] **Step 2: Replace both builders with one**

Delete `tools/import_logger/importer.py:375-439` — the whole of `_build_diveroffice_section` and `_build_diveroffice_baro_section` — and put this in their place:

```python
    def _build_utc_offset_section(
        self, database_timezone: str | None = None
    ) -> tuple[QtWidgets.QWidget, QtWidgets.QComboBox, QtWidgets.QLabel, RowEntry]:
        """Build one format section holding a UTC-offset combobox.

        DiverOffice and DiverOffice Baro need the identical control; they only
        differ in which section is visible for the selected format.
        """
        section = QtWidgets.QWidget()
        section_layout = QtWidgets.QVBoxLayout(section)
        section_layout.setContentsMargins(0, 0, 0, 0)

        label = QtWidgets.QLabel(
            QCoreApplication.translate(
                "LoggerImport", "Identify and change UTC offset:"
            )
        )
        combobox = QtWidgets.QComboBox()
        combobox.setToolTip(
            QCoreApplication.translate(
                "LoggerImport",
                "Identifies UTC-offset in file and changes to the selected one.",
            )
        )
        combobox.addItem("")
        combobox.addItems([format_timezone_string(hour) for hour in range(-12, 15)])
        if database_timezone is not None:
            set_combobox(combobox, database_timezone, add_if_not_exists=False)

        row = RowEntry()
        row.layout().addWidget(label)
        row.layout().addWidget(combobox)
        section_layout.addWidget(row)

        self.add_row(section)
        return section, combobox, label, row
```

- [ ] **Step 3: Update the call sites**

Replace `tools/import_logger/importer.py:185-189`:

```python
        _db_tz = db_utils.get_timezone_from_db("w_levels_logger")
        self._build_diveroffice_section(_db_tz)
        self._build_diveroffice_baro_section(_db_tz)
        self._build_levelogger_section()
        self._build_hobo_section()
```

with:

```python
        _db_tz = db_utils.get_timezone_from_db("w_levels_logger")
        # Section build order determines layout order — DiverOffice first.
        (
            self._diveroffice_section,
            self.utc_offset,
            self.utcoffset_label,
            self.utcoffset_row,
        ) = self._build_utc_offset_section(_db_tz)
        (
            self._diveroffice_baro_section,
            self.baro_utc_offset,
            _baro_label,
            _baro_row,
        ) = self._build_utc_offset_section(_db_tz)
        self._build_levelogger_section()
        self._build_hobo_section()
```

`self.utcoffset_label` and `self.utcoffset_row` have no readers outside the old builder, but they are kept so nothing outside the repo that touches them breaks.

- [ ] **Step 4: Collapse the two button lambdas**

Replace `tools/import_logger/importer.py:288-299` (the `start_import_button.clicked.connect(...)` call) with:

```python
        self.start_import_button.clicked.connect(
            lambda: self._start_import_from_gui(export_csv=False, import_to_db=True)
        )
```

and `:306-317` (the `export_csv_button.clicked.connect(...)` call) with:

```python
        self.export_csv_button.clicked.connect(
            lambda: self._start_import_from_gui(export_csv=True, import_to_db=False)
        )
```

Then add this method immediately after `select_files` (after `tools/import_logger/importer.py:516`):

```python
    def _start_import_from_gui(self, *, export_csv: bool, import_to_db: bool):
        """Read the current widget state and run one import or CSV export."""
        return self.start_import(
            files=self.files,
            skip_rows_without_water_level=self.skip_rows.checked,
            confirm_names=self.confirm_names.checked,
            import_all_data=self.import_all_data.checked,
            from_date=self.date_time_filter.from_date,
            to_date=self.date_time_filter.to_date,
            export_csv=export_csv,
            import_to_db=import_to_db,
        )
```

- [ ] **Step 5: Run the tests**

Run: `python3 -m pytest test/test_import_logger.py -q`
Expected: all pass, same count as Step 1.

- [ ] **Step 6: Format and commit**

```bash
ruff check --fix . && ruff format .
git add tools/import_logger/importer.py
git commit -m "refactor: build one UTC-offset section and one import entry point"
```

---

### Task 7: Extract the DiverOffice metadata lookup chain and fix the shadowed loop variable

**Problem:** `DiverOfficeParser._parse` resolves three metadata fields with three hand-written `if not x:` fallback chains covering 27 lines. It also binds `section` as the metadata-parsing loop variable (`:533`, `:551`) and then rebinds the same name to a different meaning at `:618`, so the value read at `:551` is silently dead by the time the second loop runs.

**Files:**
- Modify: `tools/import_logger/parsers.py:103-132` (add helper), `:576-604` (the three chains), `:618-624` (shadowing)
- Test: `test/test_import_logger.py`

**Interfaces:**
- Produces: `_first_metadata_value(metadata: dict[str, dict[str, str]], lookups: tuple[tuple[str, str], ...]) -> str` — returns the first non-empty value for the ordered `(section, key)` pairs, or `""`.

- [ ] **Step 1: Write the failing test**

Append to `test/test_import_logger.py`:

```python
def test_first_metadata_value_returns_the_first_non_empty_match():
    from midvatten.tools.import_logger.parsers import _first_metadata_value

    metadata = {
        "logger settings": {"location": ""},
        "series settings": {"location": "Second"},
        "flat": {"location": "Fourth"},
    }
    lookups = (
        ("logger settings", "location"),
        ("series settings", "location"),
        ("channel identification", "location"),
        ("flat", "location"),
    )
    assert _first_metadata_value(metadata, lookups) == "Second"
    assert _first_metadata_value({}, lookups) == ""
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest test/test_import_logger.py::test_first_metadata_value_returns_the_first_non_empty_match -v`
Expected: FAIL with `ImportError: cannot import name '_first_metadata_value'`.

- [ ] **Step 3: Add the helper**

Insert into `tools/import_logger/parsers.py` immediately after `_canonical_frame` (after line 131):

```python
def _first_metadata_value(
    metadata: dict[str, dict[str, str]],
    lookups: tuple[tuple[str, str], ...],
) -> str:
    """Return the first non-empty value for the ordered (section, key) pairs.

    DiverOffice moved the same field between sections across file-format
    generations, so every metadata field is resolved by trying each known
    location in priority order.
    """
    for section_name, key in lookups:
        value = metadata.get(section_name, {}).get(key, "")
        if value:
            return value
    return ""
```

- [ ] **Step 4: Replace the three fallback chains**

Replace `tools/import_logger/parsers.py:576-604` (from the `# Resolve UTC offset:` comment through the last `location = metadata.get("flat", ...)` line) with:

```python
        # Each field moved between sections across DiverOffice generations, so
        # every known location is tried in priority order.
        utc_offset = _first_metadata_value(
            metadata,
            (
                ("logger settings", "instrument number"),
                ("series settings", "instrument number"),
                ("channel identification", "utc offset (hh:mm)"),
                ("flat", "instrument number"),
            ),
        )
        serial_raw = _first_metadata_value(
            metadata,
            (
                ("logger settings", "serial number"),
                ("series settings", "serial number"),
                ("flat", "serial number"),
            ),
        )
        serial_number = DiverOfficeParser._extract_diver_serial(serial_raw)
        location = _first_metadata_value(
            metadata,
            (
                ("logger settings", "location"),
                ("series settings", "location"),
                ("channel identification", "location"),
                ("flat", "location"),
            ),
        )
```

The lookup order is copied verbatim from the chains being deleted — do not reorder it.

- [ ] **Step 5: Fix the shadowed loop variable**

At `tools/import_logger/parsers.py:618-624`, rename the loop variables so the second loop no longer reuses `section` (and `data`, which shadows nothing but reads as a DataFrame name in a parser module):

```python
        data_headers = {0: "date_time"}
        for section_name, section_values in metadata.items():
            m = re.search("channel ([0-9]+)", section_name)
            if m is not None:
                secno = m.groups()[0]
                colname = section_values.get("identification", "")
                if colname:
                    data_headers[int(secno)] = colname
```

- [ ] **Step 6: Run the tests**

Run: `python3 -m pytest test/test_import_logger.py -q`
Expected: all pass, including the new test.

- [ ] **Step 7: Format and commit**

```bash
ruff check --fix . && ruff format .
git add tools/import_logger/parsers.py test/test_import_logger.py
git commit -m "refactor: extract the DiverOffice metadata lookup chain"
```

---

### Task 8: Unify the two strict numeric coercions

**Problem:** `_strict_frame_conversion` (`parsers.py:416-435`) and `_strict_numeric_series` (`:861-880`) implement the same algorithm — strip, blank-to-NA, comma-to-dot, `to_numeric`, locate the first non-blank failure — and differ only in which exception they raise. Fixing a coercion rule means finding both.

**Files:**
- Modify: `tools/import_logger/parsers.py:103-132` (add helper), `:416-435`, `:861-880`
- Test: `test/test_import_logger.py`

**Interfaces:**
- Produces: `_coerce_numeric_column(values: pd.Series) -> tuple[pd.Series, int | None]` — returns the coerced series and the *positional* index of the first non-blank value that failed to convert, or `None` when all converted.

- [ ] **Step 1: Write the failing test**

Append to `test/test_import_logger.py`:

```python
def test_coerce_numeric_column_reports_the_first_invalid_position():
    from midvatten.tools.import_logger.parsers import _coerce_numeric_column

    converted, invalid_position = _coerce_numeric_column(
        pd.Series(["1,5", " 2.5 ", "", "  ", "3"])
    )
    assert invalid_position is None
    assert converted.tolist()[:2] == [1.5, 2.5]
    assert pd.isna(converted.iloc[2]) and pd.isna(converted.iloc[3])

    _converted, invalid_position = _coerce_numeric_column(
        pd.Series(["1.0", "", "oops", "2.0"])
    )
    assert invalid_position == 2
```

`pd` is already imported in `test/test_import_logger.py`; confirm with `grep -n "^import pandas" test/test_import_logger.py` and add the import only if it is absent.

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest test/test_import_logger.py::test_coerce_numeric_column_reports_the_first_invalid_position -v`
Expected: FAIL with `ImportError: cannot import name '_coerce_numeric_column'`.

- [ ] **Step 3: Add the shared helper**

Insert into `tools/import_logger/parsers.py` immediately after `_first_metadata_value` (added in Task 7):

```python
def _coerce_numeric_column(values: pd.Series) -> tuple[pd.Series, int | None]:
    """Coerce measurement text to numbers, reporting the first bad value.

    Blank and whitespace-only values become NA — a logger row may legitimately
    omit a channel. Decimal commas are accepted. The second element is the
    positional index of the first non-blank value that is not a number, or
    ``None`` when every value converted.
    """
    normalized = values.astype("string").str.strip()
    normalized = normalized.mask(normalized == "")
    normalized = normalized.str.replace(",", ".", regex=False)
    converted = pd.to_numeric(normalized, errors="coerce")
    invalid = normalized.notna() & converted.isna()
    if invalid.any():
        return converted, int(invalid.to_numpy().nonzero()[0][0])
    return converted, None
```

- [ ] **Step 4: Use it in `_strict_frame_conversion`**

Replace `tools/import_logger/parsers.py:416-435` (the whole `for col_idx in range(converted_frame.shape[1]):` loop body) with:

```python
        for col_idx in range(converted_frame.shape[1]):
            if col_idx == date_col_idx:
                continue
            raw = converted_frame.iloc[:, col_idx]
            converted, invalid_position = _coerce_numeric_column(raw)
            if invalid_position is not None:
                source = source_lines[invalid_position]
                raise DiverOfficeParseError(
                    filename,
                    f"invalid numeric value {raw.iloc[invalid_position]!r}",
                    source.number,
                    source.text,
                )
            converted_frame[converted_frame.columns[col_idx]] = converted
```

Note: this path deliberately does **not** call `.astype("float64")` — that matches the current behaviour and must not change.

- [ ] **Step 5: Use it in `_strict_numeric_series`**

Replace `tools/import_logger/parsers.py:861-880` (the whole function body, keeping the signature) with:

```python
def _strict_numeric_series(
    values: pd.Series,
    *,
    filename: str,
    column: str,
) -> pd.Series:
    converted, invalid_position = _coerce_numeric_column(values)
    if invalid_position is not None:
        raise FileError(
            QCoreApplication.translate(
                "LoggerImport",
                "Invalid numeric value %s in column %s of file %s (data row %s).",
            )
            % (values.iloc[invalid_position], column, filename, invalid_position + 1)
        )
    return converted.astype("float64")
```

The `.astype("float64")` is kept here because the original had it — Levelogger and HOBO frames rely on the float dtype.

- [ ] **Step 6: Run the tests**

Run: `python3 -m pytest test/test_import_logger.py test/test_import_logger_workers.py -q`
Expected: all pass, including the new test.

- [ ] **Step 7: Format and commit**

```bash
ruff check --fix . && ruff format .
git add tools/import_logger/parsers.py test/test_import_logger.py
git commit -m "refactor: share one strict numeric coercion in the logger parsers"
```

---

### Task 9: Centralise the uncalibrated-obsid label and remove the dead accessor

**Problem:** Three sites build or strip the `" (uncalibrated)"` suffix by hand (`selected_obsid:500`, `load_obsid_from_db:597-602`, `update_combobox_with_calibration_info:631-643`). Separately, `get_all_obsids_in_w_levels_logger` has **no production callers** left — only two tests — yet it runs the full `CASE WHEN … is_uncalibrated` subquery and throws the flag away.

**Files:**
- Modify: `tools/loggereditor.py:69-71` (add helpers), `:498-500`, `:572-579` (delete), `:591-605`, `:630-645`
- Modify: `test/test_wlevels_calc_calibr.py:273-277`, `:1337-1339`
- Test: `test/test_wlevels_calc_calibr.py`

**Interfaces:**
- Produces (module-level in `tools/loggereditor.py`):
  - `_obsid_label(obsid: str, is_uncalibrated: bool) -> str`
  - `_obsid_from_label(label: str) -> str`
- Removes: `LoggerEditor.get_all_obsids_in_w_levels_logger`.
- `LoggerEditor.get_obsids_with_calibration_status(obsid=None, dbconnection=None) -> list[tuple[str, bool]]` and `get_uncalibrated_obsids(obsid=None, dbconnection=None) -> list[str]` are unchanged.

- [ ] **Step 1: Verify the method really is dead outside this repo**

```bash
grep -rn "get_all_obsids_in_w_levels_logger" --include=*.py . | grep -v "\.worktrees\|_pkgroot"
grep -rn "get_all_obsids_in_w_levels_logger" ~/dev/midv_addons 2>/dev/null
```

Expected: hits only in `tools/loggereditor.py` and `test/test_wlevels_calc_calibr.py`; **nothing** in `midv_addons`. If `midv_addons` uses it, stop and skip the deletion half of this task — the method is public API — and do only Steps 3-5.

- [ ] **Step 2: Write the failing test**

Append to `test/test_wlevels_calc_calibr.py`:

```python
def test_obsid_label_round_trips():
    from midvatten.tools.loggereditor import _obsid_from_label, _obsid_label

    assert _obsid_label("rb1", False) == "rb1"
    assert _obsid_label("rb1", True) == "rb1 (uncalibrated)"
    assert _obsid_from_label("rb1") == "rb1"
    assert _obsid_from_label("rb1 (uncalibrated)") == "rb1"
```

- [ ] **Step 3: Run it to verify it fails**

Run: `python3 -m pytest test/test_wlevels_calc_calibr.py::test_obsid_label_round_trips -v`
Expected: FAIL with `ImportError: cannot import name '_obsid_label'`.

- [ ] **Step 4: Add the helpers**

Insert into `tools/loggereditor.py` immediately after the `_UNCALIBRATED_SUFFIX` constant (after line 70, before `def _line_key_order`):

```python
def _obsid_label(obsid: str, is_uncalibrated: bool) -> str:
    """Return the obsid combobox label for one calibration state."""
    return obsid + _UNCALIBRATED_SUFFIX if is_uncalibrated else obsid


def _obsid_from_label(label: str) -> str:
    """Return the bare obsid behind a combobox label."""
    return str(label).replace(_UNCALIBRATED_SUFFIX, "")
```

- [ ] **Step 5: Route the three sites through the helpers**

At `tools/loggereditor.py:498-500`:

```python
    @property
    def selected_obsid(self):
        return _obsid_from_label(self.combobox_obsid.currentText())
```

At `tools/loggereditor.py:597-602`, replace the `labels = [...]` comprehension with:

```python
        labels = [
            _obsid_label(row_obsid, is_uncalibrated)
            for row_obsid, is_uncalibrated in self.get_obsids_with_calibration_status(
                dbconnection=dbconnection
            )
        ]
```

At `tools/loggereditor.py:630-645`, replace the loop body with:

```python
        for idx in range(num_entries):
            current_obsid = _obsid_from_label(self.combobox_obsid.itemText(idx))

            if obsid is not None and current_obsid != obsid:
                # If obsid was given, only continue loop for that one:
                continue

            self.combobox_obsid.setItemText(
                idx,
                _obsid_label(
                    current_obsid, current_obsid in obsids_with_uncalibrated_data
                ),
            )
```

- [ ] **Step 6: Delete the dead accessor**

Delete `tools/loggereditor.py:572-579` entirely:

```python
    @fn_timer
    def get_all_obsids_in_w_levels_logger(self, dbconnection=None):
        return [
            row[0]
            for row in self.get_obsids_with_calibration_status(
                dbconnection=dbconnection
            )
        ]
```

- [ ] **Step 7: Update the two tests that called it — keeping every asserted value identical**

At `test/test_wlevels_calc_calibr.py:273-277`, replace:

```python
        assert editor.get_all_obsids_in_w_levels_logger() == [
            "calibrated",
            "no_head",
            "uncalibrated",
        ]
```

with:

```python
        assert [row_obsid for row_obsid, _flag in summary] == [
            "calibrated",
            "no_head",
            "uncalibrated",
        ]
```

`summary` is already bound at line 265 from `editor.get_obsids_with_calibration_status()`. The expected list is unchanged.

At `test/test_wlevels_calc_calibr.py:1337-1339`, inside `legacy_startup`, replace:

```python
            editor.get_all_obsids_in_w_levels_logger()
            editor.get_uncalibrated_obsids()
```

with:

```python
            # Two separate logger round-trips, as the pre-optimization path made.
            editor.get_obsids_with_calibration_status()
            editor.get_uncalibrated_obsids()
```

This test simulates the legacy round-trip *count*, which stays at two.

- [ ] **Step 8: Run the tests**

Run: `python3 -m pytest test/test_wlevels_calc_calibr.py -q`
Expected: all pass. Also run the sibling loggereditor suites:
Run: `python3 -m pytest test/test_loggereditor_series.py test/test_loggereditor_dupes.py test/test_loggereditor_plot_interaction.py -q`
Expected: all pass.

- [ ] **Step 9: Format and commit**

```bash
ruff check --fix . && ruff format .
git add tools/loggereditor.py test/test_wlevels_calc_calibr.py
git commit -m "refactor: centralise the uncalibrated obsid label helpers"
```

---

### Task 10: Simplify `_load_plot_rows_from_db` and drop the defensive attribute reads

**Problem:** `_load_plot_rows_from_db` returns `has_created_at, has_comment` through a 4-tuple even though both are derived from `self._existing_columns`, which the caller already owns. Its `source_col` and `no_source` branches are identical apart from one SQL expression. It also reads `getattr(self, "_existing_columns", [])` even though `_load_database_startup_state` sets that attribute unconditionally — the default silently produces a wrong query if the attribute is ever missing, instead of failing loudly. `_refresh_after_save` has the same pattern with `hasattr`/`getattr`.

**Note:** the `series_join` branch keeps its own SQL string. Merging all three into one assembled string would trade three readable queries for four conditional fragments — that is not an improvement, and this task deliberately does not do it.

**Files:**
- Modify: `tools/loggereditor.py:1093-1153`, `:1192-1198`, `:1345-1359`
- Test: `test/test_wlevels_calc_calibr.py`, `test/test_loggereditor_series.py`

**Interfaces:**
- Produces: `LoggerEditor._load_plot_rows_from_db(self, obsid, dbconnection) -> tuple[list, dict]` — returns `(head_level_masl_list, series_buf)`. The two booleans are no longer returned; callers derive them from `self._existing_columns`.

- [ ] **Step 1: Confirm existing coverage is green**

Run: `python3 -m pytest test/test_wlevels_calc_calibr.py test/test_loggereditor_series.py -q`
Expected: PASS. Record the counts.

- [ ] **Step 2: Rewrite `_load_plot_rows_from_db`**

Replace `tools/loggereditor.py:1093-1153` in full with:

```python
    def _load_plot_rows_from_db(self, obsid, dbconnection) -> tuple[list, dict]:
        """Load one plot's database rows using the caller-owned connection."""
        ph = dbconnection.placeholder()
        self._ensure_meas_ts(obsid, dbconnection)

        has_created_at = "created_at" in self._existing_columns
        has_comment = "comment" in self._existing_columns
        series_join = self._schema_variant == "series_join"

        if series_join:
            extra_cols = self._build_optional_extra_cols(
                has_created_at, has_comment, prefix="l."
            )
            head_level_masl_sql = (
                f"SELECT l.date_time, l.head_cm / 100, l.level_masl,"
                f" TRIM(COALESCE(s.source, '')), l.series_id{extra_cols}"
                f" FROM w_levels_logger l"
                f" LEFT JOIN w_logger_series s ON s.id = l.series_id"
                f" WHERE l.obsid = {ph} ORDER BY l.date_time"
            )
        else:
            # Both non-join variants read the same table; only the source
            # expression differs, so they share one query.
            source_expr = (
                "TRIM(COALESCE(source, ''))"
                if self._schema_variant == "source_col"
                else "'' as source"
            )
            extra_cols = self._build_optional_extra_cols(has_created_at, has_comment)
            head_level_masl_sql = (
                f"SELECT date_time, head_cm / 100, level_masl,"
                f" {source_expr}, NULL AS series_id{extra_cols}"
                f" FROM w_levels_logger WHERE obsid = {ph}"
                f" ORDER BY date_time"
            )

        head_level_masl_list = db_utils.sql_load_fr_db(
            head_level_masl_sql, dbconnection=dbconnection, execute_args=(obsid,)
        )[1]

        series_buf: dict = {}
        if series_join:
            series_rows = dbconnection.execute_and_fetchall(
                f"SELECT id, obsid, source, instrument, description, comment"
                f" FROM w_logger_series WHERE obsid = {ph}",
                (obsid,),
            )
            series_buf = {
                row[0]: {
                    "obsid": row[1],
                    "source": row[2],
                    "instrument": row[3],
                    "description": row[4],
                    "comment": row[5],
                }
                for row in series_rows
            }

        return head_level_masl_list, series_buf
```

- [ ] **Step 3: Update the caller**

Replace `tools/loggereditor.py:1192-1198`:

```python
            with use_or_create_connection(None) as dbconnection:
                (
                    head_level_masl_list,
                    self._series_buf,
                    has_created_at,
                    has_comment,
                ) = self._load_plot_rows_from_db(obsid, dbconnection)
```

with:

```python
            with use_or_create_connection(None) as dbconnection:
                head_level_masl_list, self._series_buf = self._load_plot_rows_from_db(
                    obsid, dbconnection
                )
            has_created_at = "created_at" in self._existing_columns
            has_comment = "comment" in self._existing_columns
```

`has_created_at` / `has_comment` are consumed a few lines further down at `:1211-1214`, so they must stay bound in this scope.

- [ ] **Step 4: Drop the defensive reads in `_refresh_after_save`**

Replace `tools/loggereditor.py:1345-1359` with:

```python
    def _refresh_after_save(self) -> None:
        """Refresh only UI state whose database-backed data may have changed."""
        if self.tab_widget.currentWidget() is self._series_tab:
            self._update_series_tab()
        if any(
            series.get("table") == "w_levels_logger" for series in self._ref_series
        ):
            self._ref_subplot_dirty = True
            self._draw_reference_subplot()
```

- [ ] **Step 5: Prove the attributes really are always set before use**

`_refresh_after_save` runs only from `_on_save_clicked`, which is a widget signal — so `show()` has already run `_load_database_startup_state`. Confirm `_series_tab`, `tab_widget` and `_ref_series` are assigned unconditionally in `show()`/`_setup_ref_dock()`:

```bash
grep -n "self._series_tab\s*=\|self.tab_widget\s*=\|self._ref_series\s*=" tools/loggereditor.py
```

Expected: each has at least one unconditional assignment inside `show()` or `__init__`. **If any assignment is inside a conditional, revert Step 4 for that attribute** and leave its guard in place — the guard is then load-bearing, not defensive.

- [ ] **Step 6: Run the tests**

Run: `python3 -m pytest test/test_wlevels_calc_calibr.py test/test_loggereditor_series.py test/test_loggereditor_dupes.py test/test_loggereditor_plot_interaction.py -q`
Expected: all pass, same counts as Step 1.

- [ ] **Step 7: Format and commit**

```bash
ruff check --fix . && ruff format .
git add tools/loggereditor.py
git commit -m "refactor: simplify plot row loading and drop defensive attribute reads"
```

---

### Task 11: Initialise the importer's wait-cursor flag in the constructor

**Problem:** `general_import` sets `self._manage_wait_cursor`, but `_cleanup` reads it twice via `getattr(self, "_manage_wait_cursor", True)`. If `_cleanup` ever runs before `general_import` sets the attribute, the default silently guesses. Instance state belongs in `__init__`.

**Files:**
- Modify: `tools/import_data_to_db.py:76-85` (`__init__`), `:747`, `:761`
- Test: `test/test_import_data_to_db.py`

**Interfaces:**
- Produces: `MidvDataImporter._manage_wait_cursor: bool` — initialised to `True` in `__init__`, overwritten per call by `general_import`.

- [ ] **Step 1: Write the failing test**

Append to `test/test_import_data_to_db.py`:

```python
def test_importer_manages_the_wait_cursor_by_default():
    importer = import_data_to_db.MidvDataImporter()
    assert importer._manage_wait_cursor is True
```

Confirm `import_data_to_db` is already imported in that test module; if it is imported under another name, use that name.

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest test/test_import_data_to_db.py::test_importer_manages_the_wait_cursor_by_default -v`
Expected: FAIL with `AttributeError: 'MidvDataImporter' object has no attribute '_manage_wait_cursor'`.

- [ ] **Step 3: Initialise the attribute**

In `tools/import_data_to_db.py`, add one line to `__init__` (after `self.confirmation_handled = None` at line 84):

```python
        self._manage_wait_cursor = True
```

- [ ] **Step 4: Read it directly**

At `tools/import_data_to_db.py:747`, change:

```python
            if getattr(self, "_manage_wait_cursor", True):
```

to:

```python
            if self._manage_wait_cursor:
```

At `tools/import_data_to_db.py:761`, make the identical change.

- [ ] **Step 5: Run the tests**

Run: `python3 -m pytest test/test_import_data_to_db.py test/test_import_logger_workers.py -q`
Expected: all pass, including the new test.

- [ ] **Step 6: Format and commit**

```bash
ruff check --fix . && ruff format .
git add tools/import_data_to_db.py test/test_import_data_to_db.py
git commit -m "refactor: initialise the importer wait-cursor flag in __init__"
```

---

### Task 12: Harden the cross-thread log payload and restore per-table timezone determinism

**Problem, part A:** `_MessageDispatcher` emits a positional 6-tuple that `_log_on_main_thread(*payload)` unpacks. Reordering or inserting a parameter in either signature produces silently mis-assigned log arguments rather than a `TypeError`, and there is no test for the dispatcher at all.

**Problem, part B:** `get_timezones_from_db` dropped the `LIMIT 1` that `get_timezone_from_db` used to carry. If `about_db` holds more than one `date_time` row for a table, the *last* row now wins nondeterministically instead of the first.

**Problem, part C (low value, do last):** the ragged-delimiter branch builds a `scores` list, then `max()`, then `.index()` — three passes to pick a maximum.

**Files:**
- Modify: `tools/utils/message_utils.py:26-40`, `:77-107`
- Modify: `tools/utils/db_utils/helpers.py:196-225`
- Modify: `tools/utils/file_utils.py:117-127`
- Test: `test/test_midvatten_utils.py`, `test/test_db_utils.py`, `test/test_file_utils.py`

**Interfaces:**
- `MessagebarAndLog.log(...)` and `_log_on_main_thread(...)` keep their signatures. The queued payload becomes a `dict[str, object]` of keyword arguments.
- `get_timezones_from_db(tablenames, dbconnection=None, about_db_columns=None) -> dict[str, str | None]` — unchanged signature; first matching row now wins per table.

- [ ] **Step 1: Write the failing test for the payload**

Append to `test/test_midvatten_utils.py`:

```python
    def test_queued_log_payload_is_delivered_by_keyword(self):
        from midvatten.tools.utils import message_utils

        delivered = {}

        def fake_deliver(**kwargs):
            delivered.update(kwargs)

        with mock.patch.object(
            message_utils.MessagebarAndLog,
            "_log_on_main_thread",
            side_effect=fake_deliver,
        ):
            message_utils._message_dispatcher._deliver(
                {
                    "bar_msg": "bar",
                    "log_msg": "log",
                    "duration": 5,
                    "messagebar_level": 1,
                    "log_level": 2,
                    "button": False,
                }
            )

        assert delivered == {
            "bar_msg": "bar",
            "log_msg": "log",
            "duration": 5,
            "messagebar_level": 1,
            "log_level": 2,
            "button": False,
        }
```

Place it inside the existing `TestDecoratorMetadata` class or a new class in the same file — match the file's surrounding style.

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest test/test_midvatten_utils.py -k queued_log_payload -v`
Expected: FAIL — `_deliver` currently calls `_log_on_main_thread(*payload)`, which unpacks a dict into its *keys* as positional arguments.

- [ ] **Step 3: Switch the payload to keyword arguments**

At `tools/utils/message_utils.py:35-37`, replace:

```python
    @pyqtSlot(object)
    def _deliver(self, payload) -> None:
        MessagebarAndLog._log_on_main_thread(*payload)
```

with:

```python
    @pyqtSlot(object)
    def _deliver(self, payload: dict) -> None:
        MessagebarAndLog._log_on_main_thread(**payload)
```

At `tools/utils/message_utils.py:86-96`, replace the emit block:

```python
            _message_dispatcher.requested.emit(
                (
                    bar_msg,
                    log_msg,
                    duration,
                    messagebar_level,
                    log_level,
                    button,
                )
            )
            return None
```

with:

```python
            _message_dispatcher.requested.emit(
                {
                    "bar_msg": bar_msg,
                    "log_msg": log_msg,
                    "duration": duration,
                    "messagebar_level": messagebar_level,
                    "log_level": log_level,
                    "button": button,
                }
            )
            return None
```

- [ ] **Step 4: Run the message tests**

Run: `python3 -m pytest test/test_midvatten_utils.py -q`
Expected: all pass, including the new test.

- [ ] **Step 5: Write the failing test for timezone determinism**

Append to `test/test_db_utils.py`, following that file's existing fixture and marker style (`@pytest.mark.spatialite` if the surrounding tests use it):

```python
def test_get_timezones_from_db_keeps_the_first_matching_row():
    from midvatten.tools.utils.db_utils import helpers

    class FakeConnection:
        schema = "public"

        def placeholder(self):
            return "?"

        def ident(self, name):
            return f'"{name}"'

        def in_clause(self, values):
            return "(?)", tuple(values)

        def is_sqlite(self):
            return True

        def execute_and_fetchall(self, sql, args=None):
            return [
                ("w_levels_logger", "Local time (GMT+1)"),
                ("w_levels_logger", "Local time (GMT+9)"),
            ]

    result = helpers.get_timezones_from_db(
        ("w_levels_logger",),
        dbconnection=FakeConnection(),
        about_db_columns=["tablename", "columnname", "description"],
    )
    assert result == {"w_levels_logger": "GMT+1"}
```

- [ ] **Step 6: Run it to verify it fails**

Run: `python3 -m pytest test/test_db_utils.py -k keeps_the_first_matching_row -v`
Expected: FAIL — currently returns `{"w_levels_logger": "GMT+9"}` because the loop overwrites.

- [ ] **Step 7: Keep the first row per table**

At `tools/utils/db_utils/helpers.py`, replace the result loop:

```python
        for table_name, description in rows:
            timezones[table_name] = _parse_timezone_description(description)
        return timezones
```

with:

```python
        # about_db may hold several date_time rows for one table; the previous
        # per-table query took the first with LIMIT 1, so keep that rule.
        resolved: set[str] = set()
        for table_name, description in rows:
            if table_name in resolved:
                continue
            resolved.add(table_name)
            timezones[table_name] = _parse_timezone_description(description)
        return timezones
```

- [ ] **Step 8: Simplify the ragged-delimiter selection**

At `tools/utils/file_utils.py:117-127`, replace:

```python
        if allow_ragged_rows:
            # A logger row may legitimately omit a measurement. Prefer the
            # delimiter that produces the expected width on the most complete
            # rows instead of requiring every row to have the same width.
            scores = [
                sum(_count_columns(row, candidate) == num_fields for row in rows)
                for candidate in delimiters
            ]
            best_score = max(scores, default=0)
            if best_score:
                return delimiters[scores.index(best_score)]
            return None
```

with:

```python
        if allow_ragged_rows:
            # A logger row may legitimately omit a measurement. Prefer the
            # delimiter that produces the expected width on the most complete
            # rows instead of requiring every row to have the same width.
            def matching_rows(candidate: str) -> int:
                return sum(
                    _count_columns(row, candidate) == num_fields for row in rows
                )

            best = max(delimiters, key=matching_rows, default=None)
            if best is not None and matching_rows(best) > 0:
                return best
            return None
```

`max` returns the first maximum on a tie, matching the old `scores.index(best_score)`.

- [ ] **Step 9: Run the tests**

Run: `python3 -m pytest test/test_midvatten_utils.py test/test_db_utils.py test/test_file_utils.py test/test_import_logger.py -q`
Expected: all pass.

- [ ] **Step 10: Format and commit**

```bash
ruff check --fix . && ruff format .
git add tools/utils/message_utils.py tools/utils/db_utils/helpers.py \
  tools/utils/file_utils.py test/test_midvatten_utils.py test/test_db_utils.py
git commit -m "fix: deliver queued log payloads by keyword and keep first timezone row"
```

---

### Phase 1 checkpoint

- [ ] **Run the full suite.** It takes roughly 33-43 minutes.

```bash
python3 -m pytest test/ -q 2>&1 | tail -20
```

Expected: identical pass/fail counts to the Prerequisites baseline. **Do not start Phase 2 on a regression.** If something fails, bisect with `git bisect` across the Phase 1 commits.

- [ ] **Report to the user before continuing.** Phase 2 changes the shape of two large methods; that is a natural review gate.

---

# Phase 2 — Decompose the two oversized methods

Both targets are pure extractions: move a contiguous block into a named method, pass in what it reads, return what it writes. No logic changes. Run the owning test file after every single extraction.

---

### Task 13: Extract DiverOffice metadata reading

**Problem:** `DiverOfficeParser._parse` is ~300 lines even after Task 7. The first ~40 lines are pure file reading plus section parsing and have no dependency on anything below them.

**Files:**
- Modify: `tools/import_logger/parsers.py` — add `_ParsedMonMetadata` and `_read_metadata`, then call from `_parse`
- Test: `test/test_import_logger.py`

**Interfaces:**
- Produces:
  - `_ParsedMonMetadata` — frozen dataclass with fields `sections: dict[str, dict[str, str]]`, `raw_rows: list[str]`, `rows: list[str]`, `data_start_row: int | None`.
  - `DiverOfficeParser._read_metadata(path: str, charset: str) -> _ParsedMonMetadata` — static method.

- [ ] **Step 1: Confirm the parser suite is green**

Run: `python3 -m pytest test/test_import_logger.py -q`
Expected: PASS. Record the count — it must be identical after every step in Phase 2.

- [ ] **Step 2: Add the result dataclass**

Insert into `tools/import_logger/parsers.py` immediately after the `_ScannedMonRow` dataclass (after line 199):

```python
@dataclass(frozen=True)
class _ParsedMonMetadata:
    """Everything the DiverOffice header pass produces, before column mapping."""

    sections: dict[str, dict[str, str]]
    raw_rows: list[str]
    rows: list[str]
    data_start_row: int | None
```

- [ ] **Step 3: Extract the reader**

Add this static method to `DiverOfficeParser`, immediately before `parse` (before `tools/import_logger/parsers.py:508`):

```python
    @staticmethod
    def _read_metadata(path: str, charset: str) -> _ParsedMonMetadata:
        """Read the file and parse its header sections into key/value maps."""
        section = None
        data_start_row = None
        metadata: dict[str, dict[str, str]] = {}
        with open(path, encoding=str(charset)) as f:
            raw_rows = [ru(rawrow).rstrip("\n").rstrip("\r") for rawrow in f]
        rows = [rawrow.strip() for rawrow in raw_rows]

        for rownr, row in enumerate(rows):
            if (
                path.lower().endswith(".csv")
                and "Date/time" in row
                and not row.startswith("[")
            ):
                data_start_row = rownr + 1
                break

            if row.startswith("["):
                section = row.strip().lstrip("[").rstrip("]").lower()

                if section == "data":
                    data_start_row = rownr + 2
                    break
                else:
                    continue

            if section:
                # Support both '=' (classic .mon) and ';' (channel identification) separators
                if "=" in row:
                    kv = [x.strip() for x in row.split("=")]
                    metadata.setdefault(section, {})[kv[0].lower()] = "=".join(kv[1:])
                elif ";" in row:
                    kv = [x.strip() for x in row.split(";", 1)]
                    metadata.setdefault(section, {})[kv[0].lower()] = (
                        kv[1] if len(kv) > 1 else ""
                    )
            elif "=" in row and not row.startswith("["):
                # Legacy flat CSV: bare key=value lines before Date/time header
                kv = [x.strip() for x in row.split("=", 1)]
                key = kv[0].lower()
                if key in ("location", "instrument number", "serial number"):
                    metadata.setdefault("flat", {})[key] = kv[1] if len(kv) > 1 else ""

        return _ParsedMonMetadata(
            sections=metadata,
            raw_rows=raw_rows,
            rows=rows,
            data_start_row=data_start_row,
        )
```

This is the body of `_parse` lines 533-574 moved verbatim, with `metadata`/`raw_rows`/`rows`/`data_start_row` returned instead of left as locals.

- [ ] **Step 4: Call it from `_parse`**

In `_parse`, replace lines 532-574 (from `filename = os.path.basename(path)` through the end of the metadata `for` loop) with:

```python
        filename = os.path.basename(path)
        parsed_metadata = DiverOfficeParser._read_metadata(path, charset)
        metadata = parsed_metadata.sections
        raw_rows = parsed_metadata.raw_rows
        rows = parsed_metadata.rows
        data_start_row = parsed_metadata.data_start_row
```

Everything below `_parse` keeps referring to the same local names, so no further edits are needed in this step.

- [ ] **Step 5: Run the tests**

Run: `python3 -m pytest test/test_import_logger.py test/test_import_logger_workers.py -q`
Expected: all pass, same count as Step 1.

- [ ] **Step 6: Format and commit**

```bash
ruff check --fix . && ruff format .
git add tools/import_logger/parsers.py
git commit -m "refactor: extract DiverOffice metadata reading from _parse"
```

---

### Task 14: Extract DiverOffice channel-header resolution

**Problem:** `_parse` still mixes channel-identification parsing with declared-channel-count validation and the data-row-range calculation.

**Files:**
- Modify: `tools/import_logger/parsers.py` — add `_resolve_declared_channels`, call from `_parse`
- Test: `test/test_import_logger.py`

**Interfaces:**
- Consumes: `_first_metadata_value` (Task 7).
- Produces: `DiverOfficeParser._resolve_declared_channels(metadata: dict[str, dict[str, str]], data_headers: dict[int, str], filename: str) -> int | None` — static method. Returns the declared channel count, or `None` when the file does not declare one. Raises `DiverOfficeParseError` when the declaration and the identified channels disagree.

- [ ] **Step 1: Extract the validator**

Add this static method to `DiverOfficeParser`, immediately after `_read_metadata`:

```python
    @staticmethod
    def _resolve_declared_channels(
        metadata: dict[str, dict[str, str]],
        data_headers: dict[int, str],
        filename: str,
    ) -> int | None:
        """Return the declared channel count, proving it matches the headers."""
        declared_channels_raw = _first_metadata_value(
            metadata,
            (
                ("logger settings", "number of channels"),
                ("series settings", "number of channels"),
            ),
        )
        if not declared_channels_raw:
            return None

        try:
            declared_channels = int(declared_channels_raw.strip())
        except ValueError as error:
            raise DiverOfficeParseError(
                filename,
                f"invalid declared channel count {declared_channels_raw!r}",
            ) from error

        identified_channels = set(data_headers) - {0}
        expected_channels = set(range(1, declared_channels + 1))
        if identified_channels != expected_channels:
            raise DiverOfficeParseError(
                filename,
                f"file declares {declared_channels} channels but identifies "
                f"channels {sorted(identified_channels)}",
            )
        return declared_channels
```

Note this replaces the inline `or`-chained lookup with `_first_metadata_value`, keeping the same two sections in the same order.

- [ ] **Step 2: Call it from `_parse`**

In `_parse`, replace the block that currently starts `declared_channels: int | None = None` and ends with the `raise DiverOfficeParseError(... f"channels {sorted(identified_channels)}",)` block, with:

```python
        declared_channels = DiverOfficeParser._resolve_declared_channels(
            metadata, data_headers, filename
        )
```

- [ ] **Step 3: Run the tests**

Run: `python3 -m pytest test/test_import_logger.py -q`
Expected: all pass, same count as Task 13 Step 1.

- [ ] **Step 4: Format and commit**

```bash
ruff check --fix . && ruff format .
git add tools/import_logger/parsers.py
git commit -m "refactor: extract DiverOffice declared-channel validation"
```

---

### Task 15: Extract DiverOffice CSV header reconciliation

**Problem:** the `if is_csv:` block is the single densest part of `_parse` — ~75 lines that validate the header, cross-check it against channel metadata, and rebuild `data_headers`. It has four outputs and is entirely self-contained.

**Files:**
- Modify: `tools/import_logger/parsers.py` — add `_resolve_csv_header`, call from `_parse`
- Test: `test/test_import_logger.py`

**Interfaces:**
- Produces: `DiverOfficeParser._resolve_csv_header(rows: list[str], raw_rows: list[str], header_row_idx: int, data_headers: dict[int, str], declared_channels: int | None, mapped_output_name: Callable[[str], str | None], filename: str) -> tuple[dict[int, str], int, int, str]` — static method returning `(data_headers, expected_num_fields, date_col_idx, header_delimiter)`.

- [ ] **Step 1: Add the `Callable` import**

`tools/import_logger/parsers.py` does not currently import `Callable`. Add to the top-level imports:

```python
from collections.abc import Callable
```

- [ ] **Step 2: Extract the reconciler**

Add this static method to `DiverOfficeParser`, immediately after `_resolve_declared_channels`. The body is `_parse` lines 694-765 moved verbatim, with the outer `if header_row_idx >= 0:` guard kept at the call site:

```python
    @staticmethod
    def _resolve_csv_header(
        rows: list[str],
        raw_rows: list[str],
        header_row_idx: int,
        data_headers: dict[int, str],
        declared_channels: int | None,
        mapped_output_name: Callable[[str], str | None],
        filename: str,
    ) -> tuple[dict[int, str], int, int, str]:
        """Reconcile the authoritative CSV header against channel metadata.

        A data row may legitimately omit a measurement, so the header — not the
        widest data row — decides the field count and column identities.
        """
        header_row = rows[header_row_idx]
        hdr_delim = file_utils.get_delimiter_from_file_rows(
            [header_row],
            delimiters=["\t", ";", ","],
            filename=filename,
        )
        if hdr_delim is None:
            hdr_delim = ","
        header_cols = [
            c.strip() for c in next(csv.reader([header_row], delimiter=hdr_delim))
        ]
        expected_num_fields = len(header_cols)

        date_columns = [
            index
            for index, column in enumerate(header_cols)
            if column.lower() == "date/time"
        ]
        if len(date_columns) != 1:
            raise DiverOfficeParseError(
                filename,
                "CSV header must contain exactly one Date/time column",
                header_row_idx + 1,
                raw_rows[header_row_idx],
            )
        if declared_channels is not None and expected_num_fields != declared_channels + 1:
            raise DiverOfficeParseError(
                filename,
                f"CSV header has {expected_num_fields - 1} channels but file "
                f"declares {declared_channels}",
                header_row_idx + 1,
                raw_rows[header_row_idx],
            )

        metadata_outputs = {
            mapped
            for index, header in data_headers.items()
            if index != 0 and (mapped := mapped_output_name(header)) is not None
        }
        date_col_idx = date_columns[0]
        header_data_headers = {date_col_idx: "date_time"}
        header_outputs: set[str] = set()
        for colidx, colname in enumerate(header_cols):
            if colidx == date_col_idx:
                continue
            mapped = mapped_output_name(colname)
            if mapped is None:
                continue
            if mapped in header_outputs:
                raise DiverOfficeParseError(
                    filename,
                    f"CSV header maps more than one column to {mapped}",
                    header_row_idx + 1,
                    raw_rows[header_row_idx],
                )
            header_outputs.add(mapped)
            header_data_headers[colidx] = colname
        if metadata_outputs and metadata_outputs != header_outputs:
            raise DiverOfficeParseError(
                filename,
                "CSV header channels disagree with channel metadata",
                header_row_idx + 1,
                raw_rows[header_row_idx],
            )

        return header_data_headers, expected_num_fields, date_col_idx, hdr_delim
```

- [ ] **Step 3: Call it from `_parse`**

Replace the whole `if is_csv:` block in `_parse` (the block beginning `if is_csv:` and ending `data_headers = header_data_headers`) with:

```python
        if is_csv:
            header_row_idx = data_start_row - 1
            if header_row_idx >= 0:
                (
                    data_headers,
                    expected_num_fields,
                    date_col_idx,
                    header_delimiter,
                ) = DiverOfficeParser._resolve_csv_header(
                    rows,
                    raw_rows,
                    header_row_idx,
                    data_headers,
                    declared_channels,
                    mapped_output_name,
                    filename,
                )
```

- [ ] **Step 4: Run the tests**

Run: `python3 -m pytest test/test_import_logger.py test/test_import_logger_workers.py -q`
Expected: all pass, same count as Task 13 Step 1.

- [ ] **Step 5: Confirm `_parse` actually shrank**

```bash
python3 - <<'PY'
import ast, pathlib
tree = ast.parse(pathlib.Path("tools/import_logger/parsers.py").read_text())
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == "_parse":
        print("_parse lines:", node.end_lineno - node.lineno)
PY
```

Expected: ~217 lines from these three extractions (329 - 112). The plan originally claimed "under 150"; that was a miscalculation. 150 IS reachable, but needs four further extractions (identity resolution, data-row slicing, column selection, delimiter boundary predicate) — done as Task 15b, which brought it to 147.

- [ ] **Step 6: Format and commit**

```bash
ruff check --fix . && ruff format .
git add tools/import_logger/parsers.py
git commit -m "refactor: extract DiverOffice CSV header reconciliation"
```

---

### Task 16: Decompose `LoggerImport.start_import`

**Problem:** `start_import` runs ~275 lines inside one `try`. Phase 1 removed the meteo-seeding block; three further stages are self-contained and each has one clear input and output.

**Files:**
- Modify: `tools/import_logger/importer.py:626-901`
- Test: `test/test_import_logger.py`

**Interfaces:**
- Produces, all on `LoggerImport`:
  - `_report_parse_failures(self, summary: LoggerImportSummary) -> None`
  - `_accept_parsed_files(self, parse_batch: LoggerParseBatchResult, summary: LoggerImportSummary) -> list[ParsedLoggerFile]` — emits notices, runs the timezone-error dialog, drops empty frames, records skips on `summary`.
  - `_resolve_obsids(self, parsed_files: list[ParsedLoggerFile], confirm_names: bool, summary: LoggerImportSummary) -> list[tuple[ParsedLoggerFile, str]]`
  - `_import_one_prepared_file(self, prepared: PreparedLoggerFile, series: LoggerSeriesSpec | None, progress: QtWidgets.QProgressDialog, summary: LoggerImportSummary) -> None`
  - module-level `_parse_gui_date_bound(value, name: str) -> pd.Timestamp | None`
- `start_import`'s signature and return values are unchanged.

- [ ] **Step 1: Confirm the dialog suite is green**

Run: `python3 -m pytest test/test_import_logger.py -q`
Expected: PASS. Record the count.

- [ ] **Step 2: Extract parse-failure reporting**

Add to `LoggerImport`, immediately after `_report_import_summary`:

```python
    def _report_parse_failures(self, summary: LoggerImportSummary) -> None:
        """Log one warning per file that failed before obsid resolution."""
        for failure in summary.parse_failures:
            message_utils.MessagebarAndLog.warning(
                log_msg=QCoreApplication.translate(
                    "LoggerImport", "%s failed during %s: %s"
                )
                % (failure.filename, failure.stage, failure.reason)
            )
```

In `start_import`, replace the `for failure in summary.parse_failures:` loop (currently lines 680-686) with:

```python
            self._report_parse_failures(summary)
```

- [ ] **Step 3: Run and commit**

Run: `python3 -m pytest test/test_import_logger.py -q` — expected: same count, all pass.

```bash
ruff check --fix . && ruff format .
git add tools/import_logger/importer.py
git commit -m "refactor: extract parse-failure reporting from start_import"
```

- [ ] **Step 4: Extract the parsed-file acceptance loop**

Add to `LoggerImport`, after `_report_parse_failures`:

```python
    def _accept_parsed_files(
        self,
        parse_batch: LoggerParseBatchResult,
        summary: LoggerImportSummary,
    ) -> list:
        """Surface notices, resolve timezone errors, and drop unusable files."""
        parsed_files = []
        for parsed in parse_batch.parsed_files:
            for notice in parsed.notices:
                message_utils.MessagebarAndLog.info(log_msg=notice.message)
            if parsed.timezone_error:
                msg = QCoreApplication.translate(
                    "LoggerImport",
                    "Reading timezone in file %s failed,\n"
                    " no conversion done:\n%s\n\nSkip file?",
                ) % (ru(parsed.filename), parsed.timezone_error)
                common_utils.stop_waiting_cursor()
                question = dialog_utils.Askuser(
                    question="YesNo",
                    msg=msg,
                    dialogtitle=QCoreApplication.translate(
                        "askuser", "File timezone error!"
                    ),
                    include_cancel_button=True,
                )
                common_utils.start_waiting_cursor()
                if question.result:
                    summary.skipped.append(parsed.source_path)
                    continue
            if parsed.data.empty:
                summary.skipped.append(parsed.source_path)
                continue
            parsed_files.append(parsed)
        return parsed_files
```

In `start_import`, replace the `parsed_files = []` block through `parsed_files.append(parsed)` (currently lines 688-714) with:

```python
            parsed_files = self._accept_parsed_files(parse_batch, summary)
```

- [ ] **Step 5: Run and commit**

Run: `python3 -m pytest test/test_import_logger.py -q` — expected: same count, all pass.

```bash
ruff check --fix . && ruff format .
git add tools/import_logger/importer.py
git commit -m "refactor: extract parsed-file acceptance from start_import"
```

- [ ] **Step 6: Extract obsid resolution**

Add to `LoggerImport`, after `_accept_parsed_files`:

```python
    def _resolve_obsids(
        self,
        parsed_files: list,
        confirm_names: bool,
        summary: LoggerImportSummary,
    ) -> list:
        """Match each file to an obsid, asking the user where needed."""
        filename_location_obsid = [["filename", "location", "obsid"]]
        filename_location_obsid.extend(
            [parsed.source_path, parsed.location, parsed.location]
            for parsed in parsed_files
        )
        existing_obsids = db_utils.get_all_obsids()
        common_utils.stop_waiting_cursor()
        resolved_metadata = common_utils.filter_nonexisting_values_and_ask(
            file_data=filename_location_obsid,
            header_value="obsid",
            existing_values=existing_obsids,
            try_capitalize=not confirm_names,
            always_ask_user=confirm_names,
        )
        common_utils.start_waiting_cursor()
        paths_obsid = {row[0]: row[2] for row in resolved_metadata[1:]}
        summary.skipped.extend(
            parsed.source_path
            for parsed in parsed_files
            if parsed.source_path not in paths_obsid
        )
        return [
            (parsed, paths_obsid[parsed.source_path])
            for parsed in parsed_files
            if parsed.source_path in paths_obsid
        ]
```

In `start_import`, replace lines 726-751 (from `filename_location_obsid = [...]` through the `summary.skipped.extend(...)` block) with:

```python
            resolved_files = self._resolve_obsids(parsed_files, confirm_names, summary)
```

- [ ] **Step 7: Run and commit**

Run: `python3 -m pytest test/test_import_logger.py -q` — expected: same count, all pass.

```bash
ruff check --fix . && ruff format .
git add tools/import_logger/importer.py
git commit -m "refactor: extract obsid resolution from start_import"
```

- [ ] **Step 8: Hoist and rename the GUI date-bound parser**

`start_import` defines a nested `typed_bound` (line 651) whose name collides with `pipeline._typed_bound`. They are *not* duplicates — the importer's parses user text into a `Timestamp`, the pipeline's asserts a value was already parsed and rejects text — but the shared name reads as if one is redundant. Hoisting and renaming makes the two roles obvious.

Add at module level in `tools/import_logger/importer.py`, immediately after `logger_schema_capabilities` (after line 84):

```python
def _parse_gui_date_bound(value, name: str) -> pd.Timestamp | None:
    """Parse one date-filter widget value into a Timestamp.

    This is the GUI's parse boundary. ``pipeline._typed_bound`` is the
    downstream *assertion* boundary and deliberately rejects text.
    """
    if value in (None, ""):
        return None
    if isinstance(value, (pd.Timestamp, _datetime)):
        return pd.Timestamp(value)
    parsed = date_utils.to_date(value)
    if parsed is None:
        raise ValueError(f"Invalid {name}: {value!r}")
    return pd.Timestamp(parsed)
```

Delete the nested `def typed_bound(...)` from `start_import` (lines 651-659) and update its two call sites:

```python
            from_date=_parse_gui_date_bound(from_date, "from_date"),
            to_date=_parse_gui_date_bound(to_date, "to_date"),
```

Run: `python3 -m pytest test/test_import_logger.py -q` — expected: same count, all pass.

```bash
ruff check --fix . && ruff format .
git add tools/import_logger/importer.py
git commit -m "refactor: hoist and rename the GUI date-bound parser"
```

- [ ] **Step 9: Extract the per-file database import**

Add to `LoggerImport`, after `_resolve_obsids`:

```python
    def _import_one_prepared_file(
        self,
        prepared: PreparedLoggerFile,
        series: LoggerSeriesSpec | None,
        progress: QtWidgets.QProgressDialog,
        summary: LoggerImportSummary,
    ) -> None:
        """Run one file's database import and record its outcome."""
        result = self._run_db_worker(
            LoggerDbImportRequest(
                filename=prepared.source_path,
                dest_table=_DESTINATION_TABLES[prepared.kind],
                frame=prepared.data,
                series=series,
            ),
            progress,
        )
        if result.imported:
            summary.imported.append(prepared.source_path)
        elif result.reason == NO_NEW_ROWS_REASON:
            summary.no_new_rows.append(prepared.source_path)
        else:
            summary.database_failures.append(
                LoggerFileFailure(
                    prepared.source_path,
                    "database",
                    result.reason or "import failed",
                )
            )
```

In `start_import`, replace the `if import_to_db:` branch inside the `for prepared in prepared_files:` loop (currently lines 856-878) with:

```python
                if import_to_db:
                    self._import_one_prepared_file(prepared, series, progress, summary)
```

Leave the `elif export_csv:` branch exactly as it is.

- [ ] **Step 10: Run the tests and confirm the size drop**

Run: `python3 -m pytest test/test_import_logger.py test/test_import_logger_workers.py -q`
Expected: all pass, same count as Step 1.

```bash
python3 - <<'PY'
import ast, pathlib
tree = ast.parse(pathlib.Path("tools/import_logger/importer.py").read_text())
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == "start_import":
        print("start_import lines:", node.end_lineno - node.lineno)
PY
```

Expected: ~167 lines. The plan originally claimed "under 130" from a ~275-line base; both numbers were wrong — the base was 255 (Phase 1 had already removed the meteo block), and these five extractions remove 88. Reaching 130 would need further extractions (parse-request builder, series-spec construction, preparation loop); deliberately NOT done, because the goal is a readable sequence of named stages, which 167 achieves, not a line count I invented.

- [ ] **Step 11: Format and commit**

```bash
ruff check --fix . && ruff format .
git add tools/import_logger/importer.py
git commit -m "refactor: extract per-file database import from start_import"
```

---

### Phase 2 checkpoint

- [ ] **Run the full suite.**

```bash
python3 -m pytest test/ -q 2>&1 | tail -20
```

Expected: identical counts to the Prerequisites baseline.

- [ ] **Report to the user before starting Phase 3.** Phase 3 changes shared infrastructure used by roughly 40 call sites and is the one part of this plan that can be declined on its own.

---

# Phase 3 — Reference-counted waiting cursor

---

### Task 17: Replace the cursor marker flags with a counted stack

**Problem:** `waiting_cursor` mutates the function it wraps (`setattr(func, _MANAGES_WAITING_CURSOR, True)` at `common_utils.py:435-437`) so that `general_exception_handler`'s already-built wrapper will skip its own `stop_waiting_cursor()`. It works, but it is action-at-a-distance that depends on decorator application order, and it papers over the real defect: `general_exception_handler` calls `stop_waiting_cursor()` in `finally` without ever calling `start_waiting_cursor()` — an unbalanced pop of Qt's cursor stack.

**The fix:** make the stack countable, so the handler can unwind exactly the levels pushed beneath it and the marker flags become unnecessary.

**Risk this task accepts:** `stop_waiting_cursor()` becomes a no-op when nothing was pushed. Call sites that today pop a cursor pushed by an *unrelated* caller will stop doing so. That is the correct behaviour and is precisely what commit 55b51e9 was working around, but it is a real semantic change to a util with ~40 call sites — hence its own task, its own commit, and a full-suite run.

**Files:**
- Modify: `tools/utils/common_utils.py:95-99` (constants), `:423-445` (decorator + cursor functions), `:507-531` (`general_exception_handler`)
- Test: `test/test_midvatten_utils.py`

**Interfaces:**
- Produces:
  - `start_waiting_cursor() -> None` — pushes and increments.
  - `stop_waiting_cursor() -> None` — pops and decrements; no-op at depth 0.
  - `waiting_cursor_depth() -> int` — current depth.
  - `unwind_waiting_cursor(depth: int) -> None` — pops until the recorded depth is restored.
- Removes: `_GENERAL_EXCEPTION_HANDLER`, `_MANAGES_WAITING_CURSOR`.
- `waiting_cursor` and `general_exception_handler` keep their signatures.

- [ ] **Step 1: Write the failing test**

Append to `test/test_midvatten_utils.py`, in the same class as the existing cursor tests:

```python
    def test_cursor_depth_unwinds_exactly_once_per_push(self):
        with mock.patch("qgis.PyQt.QtWidgets.QApplication") as app:
            assert common_utils.waiting_cursor_depth() == 0
            common_utils.start_waiting_cursor()
            common_utils.start_waiting_cursor()
            assert common_utils.waiting_cursor_depth() == 2

            common_utils.stop_waiting_cursor()
            common_utils.stop_waiting_cursor()
            assert common_utils.waiting_cursor_depth() == 0

            # An extra pop must not steal a cursor pushed by someone else.
            common_utils.stop_waiting_cursor()
            assert common_utils.waiting_cursor_depth() == 0
            assert app.restoreOverrideCursor.call_count == 2

    def test_exception_handler_unwinds_a_leaked_cursor(self):
        @common_utils.general_exception_handler
        def leaks_a_cursor():
            common_utils.start_waiting_cursor()

        with mock.patch("qgis.PyQt.QtWidgets.QApplication") as app:
            leaks_a_cursor()
            assert common_utils.waiting_cursor_depth() == 0
            assert app.restoreOverrideCursor.call_count == 1
```

These tests mock `QApplication` rather than `start_waiting_cursor`/`stop_waiting_cursor`, so they exercise the real depth accounting. The two existing tests from commit 55b51e9 (`test_waiting_cursor_restores_after_exception`, `test_cursor_and_exception_handlers_restore_once`) mock the two functions themselves and must keep passing unchanged — do not edit them.

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest test/test_midvatten_utils.py -k "cursor_depth_unwinds or unwinds_a_leaked" -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'waiting_cursor_depth'`.

- [ ] **Step 3: Add the counted cursor functions**

Replace `tools/utils/common_utils.py:440-445` with:

```python
_cursor_depth = 0


def start_waiting_cursor() -> None:
    """Push one wait-cursor level owned by this process."""
    global _cursor_depth
    qgis.PyQt.QtWidgets.QApplication.setOverrideCursor(qgis.PyQt.QtCore.Qt.WaitCursor)
    _cursor_depth += 1


def stop_waiting_cursor() -> None:
    """Pop one wait-cursor level.

    Popping below zero is a no-op: an unbalanced call must never restore a
    cursor that some other caller is still relying on.
    """
    global _cursor_depth
    if _cursor_depth <= 0:
        return
    qgis.PyQt.QtWidgets.QApplication.restoreOverrideCursor()
    _cursor_depth -= 1


def waiting_cursor_depth() -> int:
    """Return how many wait-cursor levels this process currently holds."""
    return _cursor_depth


def unwind_waiting_cursor(depth: int) -> None:
    """Pop wait-cursor levels until *depth* is restored."""
    while _cursor_depth > depth:
        stop_waiting_cursor()
```

- [ ] **Step 4: Simplify the `waiting_cursor` decorator**

Replace `tools/utils/common_utils.py:423-438` with:

```python
def waiting_cursor(func: Callable) -> Callable:
    @wraps(func)
    def func_wrapper(*args, **kwargs):
        start_waiting_cursor()
        try:
            return func(*args, **kwargs)
        finally:
            stop_waiting_cursor()

    return func_wrapper
```

- [ ] **Step 5: Make the exception handler unwind instead of pop**

In `general_exception_handler`, replace the wrapper's opening line and its `finally` block:

```python
    @wraps(func)
    def new_func(*args, **kwargs):
        entry_depth = waiting_cursor_depth()
        try:
            result = func(*args, **kwargs)
```

and:

```python
        finally:
            # Restore whatever levels the wrapped call pushed and did not pop.
            unwind_waiting_cursor(entry_depth)

    return new_func
```

Delete the `setattr(new_func, _GENERAL_EXCEPTION_HANDLER, True)` line.

- [ ] **Step 6: Delete the marker constants**

Delete `tools/utils/common_utils.py:98-99`:

```python
_GENERAL_EXCEPTION_HANDLER = "_midvatten_general_exception_handler"
_MANAGES_WAITING_CURSOR = "_midvatten_manages_waiting_cursor"
```

Then confirm nothing else references them:

```bash
grep -rn "_MANAGES_WAITING_CURSOR\|_GENERAL_EXCEPTION_HANDLER\|_midvatten_manages_waiting_cursor" \
  --include=*.py . | grep -v "\.worktrees\|_pkgroot"
```

Expected: no output.

- [ ] **Step 7: Run the focused tests**

Run: `python3 -m pytest test/test_midvatten_utils.py test/test_wlevels_calc_calibr.py test/test_import_logger.py test/test_import_data_to_db.py -q`
Expected: all pass — including the two unmodified tests from commit 55b51e9.

- [ ] **Step 8: Run the full suite**

```bash
python3 -m pytest test/ -q 2>&1 | tail -20
```

Expected: identical counts to the Prerequisites baseline. This task touches shared infrastructure; the full suite is not optional here.

- [ ] **Step 9: Format and commit**

```bash
ruff check --fix . && ruff format .
git add tools/utils/common_utils.py test/test_midvatten_utils.py
git commit -m "refactor: count wait-cursor levels instead of tagging decorators"
```

---

## Finishing up

- [ ] **Run the midv_addons compatibility suite.** Several tasks touched shared modules (`common_utils`, `db_utils.helpers`, `message_utils`, `file_utils`, `import_data_to_db`), which are public API for that repo.

```bash
cd ~/dev/midv_addons && python3 -m pytest test/test_midvatten_compat.py -q
```

Expected: all pass. If it fails, the break is in this plan's changes, not in midv_addons.

- [ ] **Run the security scan.**

```bash
.venv/bin/python3 -m bandit -r . 2>&1 | tail -20
```

Expected: no new findings compared to the pre-plan state.

- [ ] **Confirm the review's targets are gone.**

```bash
grep -rn "_DESTINATION_PREPARERS\|_MISSING_HEAD_POLICIES\|_water_destination\|_BARO_METEO_PARAMS" \
  --include=*.py tools/
grep -rn "no non-duplicate rows" --include=*.py tools/
grep -rn "get_all_obsids_in_w_levels_logger" --include=*.py tools/
grep -rn 'getattr(self, "_manage_wait_cursor"\|getattr(self, "_existing_columns"' --include=*.py tools/
```

Expected: no output from any of them.

- [ ] **Invoke `superpowers:finishing-a-development-branch`** to decide how the worktree branch is integrated back into `ai_test`.

---

## Deferred — considered and deliberately not planned

- **Merging all three `_load_plot_rows_from_db` SQL branches into one assembled string.** Task 10 merges the two non-join branches only. Collapsing the join branch as well would trade three readable queries for four conditional fragments spliced into one string — harder to read and harder to verify. Not an improvement.
- **Deleting `MidvDataImporter.list_to_table`.** It has no production callers, but seven tests in `test_import_data_to_db.py` exercise the legacy list-of-lists entry point through it, which is still a supported `general_import` input shape. Removing it would delete that coverage. Revisit if the list input is ever dropped.
- **Removing the per-function `validate_logger_frame` calls in `pipeline.py`.** Each pipeline function is public and independently tested, so its input contract check is load-bearing. Task 2 removes the two wasteful `.loc[:, CANONICAL_COLUMNS]` copies without weakening any check.
