> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-07-29 · modified: 2026-07-29 · archived: 2026-07-31

# Cursor Suspension Scope + Destination Table Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two defects carried forward from the post-review cleanup: 13 hand-rolled cursor-suspension sites that leave the wait cursor up during a modal when nested, and a kind→table mapping that lives in a different layer from the kind→shape mapping it must agree with.

**Architecture:** Part A adds one `suspended_waiting_cursor()` context manager on top of the existing depth counter and converts the 13 sites to it. Part B moves the destination table onto `PreparedLoggerFile`, set where the frame shape is already chosen, and deletes the dialog-side lookup table. The two parts share no code and can be executed, reviewed, or rejected independently.

**Tech Stack:** Python 3, PyQt5/QGIS, pandas, pytest, ruff.

## Scope note

These are two independent subsystems — shared GUI infrastructure (Part A) and logger-import domain modelling (Part B). They are in one document because both are small and were requested together. **Nothing in Part B depends on Part A.** If you want to split them, cut at the `# Part B` heading; each part is independently shippable and independently testable.

## Global Constraints

- Use `python3`, never `python`.
- **No user-visible behaviour may change except the two defects being fixed.** Specifically: (a) at cursor-suspension sites the wait cursor must now actually disappear during the modal, including when nested; (b) `dest_table` must resolve to the same string it does today for both logger kinds.
- **Never weaken or change an existing test's assertion values.** Existing tests may be edited only where a task explicitly says so.
- **`ruff check --fix` and `ruff format` on the files the task touched** — never on `.`, which reformats `tools/utils/matplotlib_replacements.py` (pre-existing drift) and sweeps an unrelated file into the commit. **F401 is disabled in this repo's ruff config**, so orphaned imports need `ruff check --select F401 <files>` explicitly.
- **Never use bare `git stash` / `git stash pop`** — the stash stack is shared with other worktrees and concurrent sessions.
- Add type hints to new function/method arguments.
- Run tests with `-m "not postgis"` while other agents may be active; a shared PostgreSQL test database produces spurious `UniqueViolation` failures. Run `-m postgis` once at the end on an uncontended database.
- Commit after every task.

## Prerequisites

- [ ] **Work in an isolated worktree.** Invoke the `superpowers:using-git-worktrees` skill. Branch from `ai_test`. The project convention is `.worktrees/<name>` (gitignored); the native worktree tool defaults to branching from `origin/master`, which is **wrong** here — `ai_test` is the living branch.
- [ ] **Record the baseline.**

```bash
python3 -m pytest test/ -q -m "not postgis" 2>&1 | tail -3
```

Expected: `975 passed, 1 skipped, 290 deselected`. If it differs, stop and report — do not start on a red or unexpected baseline.

---

# Part A — One cursor-suspension scope

## The defect, precisely

13 sites do this:

```python
common_utils.stop_waiting_cursor()
<show a modal / prompt the user>
common_utils.start_waiting_cursor()
```

`stop_waiting_cursor()` pops exactly **one** level. When the caller is nested inside another operation that already pushed a cursor (depth 2 — e.g. anything running under `@common_utils.waiting_cursor`), one pop leaves depth 1, so Qt still has an override cursor and **the wait cursor stays up while the modal is on screen**. That is the whole point of the idiom, silently defeated.

Second failure mode: if the modal raises, or the code between returns early, the matching `start_waiting_cursor()` never runs and the caller silently loses the cursor it was holding.

`unwind_waiting_cursor(depth)` — added by the previous cleanup — is already exactly the primitive both halves need. Nothing uses it except `general_exception_handler`.

## File structure — Part A

| File | Responsibility after this part |
|---|---|
| `tools/utils/common_utils.py` | Owns the cursor stack. Gains `suspended_waiting_cursor()`, the one place that knows how to drop and restore *all* levels. |
| `test/test_midvatten_utils.py` | Owns the cursor-mechanism tests, in `TestDecoratorMetadata` (which already has the `zero_cursor_depth` autouse fixture). |
| `tools/import_logger/importer.py` | 2 call sites converted. |
| `tools/create_db.py` | 9 call sites converted. **5 other `stop_waiting_cursor()` calls in this file are terminal pops, not suspensions — do not touch them.** |
| `tools/export_data.py` | 1 call site converted; needs a small restructure (see Task A4). |
| `tools/export_fieldlogger.py` | 1 call site converted. |

---

### Task A1: Add `suspended_waiting_cursor()`

**Files:**
- Modify: `tools/utils/common_utils.py` (after `unwind_waiting_cursor`, ~line 461)
- Test: `test/test_midvatten_utils.py` (class `TestDecoratorMetadata`, after the existing cursor tests)

**Interfaces:**
- Consumes: `waiting_cursor_depth() -> int`, `unwind_waiting_cursor(depth: int) -> None`, `start_waiting_cursor() -> None` — all already in `common_utils.py`. `from contextlib import contextmanager` is already imported at line 29.
- Produces: `suspended_waiting_cursor()` — a context manager. On enter it unwinds the cursor stack to zero; on exit it restores exactly the depth that was held on entry, including when the body raises.

- [ ] **Step 1: Write the failing tests**

Append inside class `TestDecoratorMetadata` in `test/test_midvatten_utils.py`. The class already has an `autouse` `zero_cursor_depth` fixture, so `_cursor_depth` is reset around each of these automatically.

```python
    def test_suspended_cursor_drops_every_level_not_just_one(self):
        """A bare stop() pops one level; at depth 2 the wait cursor stayed up."""
        with mock.patch("qgis.PyQt.QtWidgets.QApplication") as app:
            common_utils.start_waiting_cursor()
            common_utils.start_waiting_cursor()
            assert common_utils.waiting_cursor_depth() == 2

            with common_utils.suspended_waiting_cursor():
                # Qt must hold no override cursor while the modal is up.
                assert common_utils.waiting_cursor_depth() == 0
                assert app.restoreOverrideCursor.call_count == 2

            assert common_utils.waiting_cursor_depth() == 2

    def test_suspended_cursor_restores_depth_after_exception(self):
        """The old idiom skipped its start() when the modal raised."""
        with mock.patch("qgis.PyQt.QtWidgets.QApplication"):
            common_utils.start_waiting_cursor()

            with pytest.raises(RuntimeError, match="modal blew up"):
                with common_utils.suspended_waiting_cursor():
                    raise RuntimeError("modal blew up")

            assert common_utils.waiting_cursor_depth() == 1

    def test_suspended_cursor_is_a_noop_at_depth_zero(self):
        with mock.patch("qgis.PyQt.QtWidgets.QApplication") as app:
            with common_utils.suspended_waiting_cursor():
                assert common_utils.waiting_cursor_depth() == 0
            assert common_utils.waiting_cursor_depth() == 0
            assert app.setOverrideCursor.call_count == 0
            assert app.restoreOverrideCursor.call_count == 0
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest test/test_midvatten_utils.py -k suspended_cursor -v`
Expected: FAIL, `AttributeError: module 'midvatten.tools.utils.common_utils' has no attribute 'suspended_waiting_cursor'`.

- [ ] **Step 3: Implement**

Insert into `tools/utils/common_utils.py` immediately after `unwind_waiting_cursor`:

```python
@contextmanager
def suspended_waiting_cursor():
    """Drop the wait cursor for a modal prompt, then restore it.

    A bare ``stop_waiting_cursor()`` pops one level, so a caller nested inside
    another wait-cursor scope still shows the wait cursor while the modal is on
    screen — the exact thing the caller was trying to avoid. And if the prompt
    raises or the caller returns early, the matching ``start_waiting_cursor()``
    never runs and the outer scope silently loses its cursor.

    This unwinds every level on entry and restores the entry depth in a
    ``finally``, so both hold regardless of nesting or control flow.
    """
    depth = waiting_cursor_depth()
    unwind_waiting_cursor(0)
    try:
        yield
    finally:
        for _ in range(depth):
            start_waiting_cursor()
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest test/test_midvatten_utils.py -q -m "not postgis"`
Expected: all pass, 3 more than the previous count for this file.

- [ ] **Step 5: Format and commit**

```bash
ruff check --fix tools/utils/common_utils.py test/test_midvatten_utils.py
ruff format tools/utils/common_utils.py test/test_midvatten_utils.py
git add tools/utils/common_utils.py test/test_midvatten_utils.py
git commit -m "feat: add suspended_waiting_cursor for modal prompts"
```

---

### Task A2: Convert the two logger-import sites

**Files:**
- Modify: `tools/import_logger/importer.py:647-656` (`_accept_parsed_files`), `:679-687` (`_resolve_obsids`)
- Test: `test/test_import_logger.py` (existing coverage is the gate — three end-to-end tests already drive the timezone-error dialog)

**Interfaces:**
- Consumes: `common_utils.suspended_waiting_cursor()` from Task A1.
- Produces: no new interface.

**Why these first:** these two are already covered end-to-end. `test/test_import_logger.py` drives the timezone dialog in all three branches (don't-skip, skip, cancel), and the cancel case proves an exception still propagates correctly through the surrounding decorators. If a conversion breaks, you find out here rather than in `create_db.py`, which has thinner coverage.

- [ ] **Step 1: Confirm the gate is green**

Run: `python3 -m pytest test/test_import_logger.py -q -m "not postgis"`
Expected: PASS. Record the count; it must be identical after.

- [ ] **Step 2: Convert `_accept_parsed_files`**

In `tools/import_logger/importer.py`, replace:

```python
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
```

with:

```python
                with common_utils.suspended_waiting_cursor():
                    question = dialog_utils.Askuser(
                        question="YesNo",
                        msg=msg,
                        dialogtitle=QCoreApplication.translate(
                            "askuser", "File timezone error!"
                        ),
                        include_cancel_button=True,
                    )
```

- [ ] **Step 3: Convert `_resolve_obsids`**

Replace:

```python
        common_utils.stop_waiting_cursor()
        resolved_metadata = common_utils.filter_nonexisting_values_and_ask(
            file_data=filename_location_obsid,
            header_value="obsid",
            existing_values=existing_obsids,
            try_capitalize=not confirm_names,
            always_ask_user=confirm_names,
        )
        common_utils.start_waiting_cursor()
```

with:

```python
        with common_utils.suspended_waiting_cursor():
            resolved_metadata = common_utils.filter_nonexisting_values_and_ask(
                file_data=filename_location_obsid,
                header_value="obsid",
                existing_values=existing_obsids,
                try_capitalize=not confirm_names,
                always_ask_user=confirm_names,
            )
```

- [ ] **Step 4: Verify no cursor calls remain in this file**

```bash
grep -n "stop_waiting_cursor()\|start_waiting_cursor()" tools/import_logger/importer.py
```

Expected: **no output.** `start_import` uses the `@common_utils.waiting_cursor` decorator, and these were the last two manual calls.

- [ ] **Step 5: Run the tests**

Run: `python3 -m pytest test/test_import_logger.py test/test_import_logger_workers.py -q -m "not postgis"`
Expected: same count as Step 1, all pass.

- [ ] **Step 6: Format and commit**

```bash
ruff check --fix tools/import_logger/importer.py
ruff format tools/import_logger/importer.py
git add tools/import_logger/importer.py
git commit -m "refactor: suspend the wait cursor via one scope in logger import"
```

---

### Task A3: Convert the nine `create_db.py` sites

**Files:**
- Modify: `tools/create_db.py` — lines 88, 96, 109, 118, 125 (in `create_new_db`) and 311, 318, 328, 337 (in `populate_postgis_db`)
- Test: `test/test_create_spatialite_db.py`, `test/test_create_postgis_db.py`

**Interfaces:**
- Consumes: `common_utils.suspended_waiting_cursor()` from Task A1.

**CRITICAL — do not convert these five.** `tools/create_db.py` has 14 `stop_waiting_cursor()` calls. Only nine are suspensions. Lines **146, 173, 191** are terminal pops immediately before `return ""`, and **266, 448** are terminal pops at the end of a method. Converting any of them to a `with` block would restore a cursor the code is deliberately dropping. Verify each site matches the `stop → prompt → start` shape before touching it.

- [ ] **Step 1: Confirm the gate is green**

Run: `python3 -m pytest test/test_create_spatialite_db.py -q -m "not postgis"`
Expected: PASS. Record the count.

- [ ] **Step 2: Convert the five sites in `create_new_db`**

Replace each block. Site 1 (locale):

```python
        if locale is None:
            with common_utils.suspended_waiting_cursor():
                set_locale = self.ask_for_locale()
        else:
            set_locale = locale
```

Site 2 (CRS):

```python
        if user_select_crs == "y":
            with common_utils.suspended_waiting_cursor():
                epsg_id = str(self.ask_for_CRS(set_locale))
        else:
            epsg_id = epsg_code
```

Site 3 (`w_levels_logger` timezone):

```python
        if w_levels_logger_timezone is None:
            with common_utils.suspended_waiting_cursor():
                default_ts = "UTC+1" if set_locale.lower() == "sv_se" else ""
                w_levels_logger_timezone = self.ask_for_timezone(
                    "w_levels_logger", default_ts
                )
```

Site 4 (`w_levels` timezone):

```python
        if w_levels_timezone is None:
            with common_utils.suspended_waiting_cursor():
                default_ts = "Europe/Stockholm" if set_locale.lower() == "sv_se" else ""
                w_levels_timezone = self.ask_for_timezone("w_levels", default_ts)
```

Site 5 (database path):

```python
        if dbpath is None:
            with common_utils.suspended_waiting_cursor():
                dbpath = ru(
                    common_utils.get_save_file_name_no_extension(
                        parent=None,
                        caption="New DB",
                        directory="midv_obsdb.sqlite",
                        filter="Spatialite (*.sqlite)",
                    )
                )
```

Note the `# print("Got timezone:" + ...)` comments that sat between the prompt and the old `start_waiting_cursor()` — keep them inside the `with` block where they are, or drop them; they are commented-out debug lines either way. Do not move live code out of the block.

- [ ] **Step 3: Convert the four sites in `populate_postgis_db`**

Site 6 (locale):

```python
        if locale is None:
            with common_utils.suspended_waiting_cursor():
                supplied_locale = self.ask_for_locale()
        else:
            supplied_locale = locale
```

Site 7 (CRS):

```python
        if user_select_crs == "y":
            with common_utils.suspended_waiting_cursor():
                epsg_id = str(self.ask_for_CRS(supplied_locale))
        else:
            epsg_id = epsg_code
```

Site 8 (`w_levels_logger` timezone):

```python
        if w_levels_logger_timezone is None:
            with common_utils.suspended_waiting_cursor():
                default_ts = "UTC+1" if supplied_locale.lower() == "sv_se" else ""
                w_levels_logger_timezone = self.ask_for_timezone(
                    "w_levels_logger", default_ts
                )
```

Site 9 (`w_levels` timezone):

```python
        if w_levels_timezone is None:
            with common_utils.suspended_waiting_cursor():
                default_ts = (
                    "Europe/Stockholm" if supplied_locale.lower() == "sv_se" else ""
                )
                w_levels_timezone = self.ask_for_timezone("w_levels", default_ts)
```

- [ ] **Step 4: Verify exactly five `stop_waiting_cursor()` calls remain**

```bash
grep -n "stop_waiting_cursor()\|start_waiting_cursor()" tools/create_db.py
```

Expected: exactly five lines, all `stop_waiting_cursor()`, at the terminal-pop sites (originally 146, 173, 191, 266, 448 — line numbers will have shifted). **Zero `start_waiting_cursor()` calls should remain.** If any `start_waiting_cursor()` survives, a suspension was missed.

- [ ] **Step 5: Run the tests**

Run: `python3 -m pytest test/test_create_spatialite_db.py -q -m "not postgis"`
Expected: same count as Step 1, all pass.

- [ ] **Step 6: Format and commit**

```bash
ruff check --fix tools/create_db.py
ruff format tools/create_db.py
git add tools/create_db.py
git commit -m "refactor: suspend the wait cursor via one scope in create_db"
```

---

### Task A4: Convert `export_data.py` — restructure required

**Files:**
- Modify: `tools/export_data.py:178-192` (`show`)
- Test: `test/test_export_data.py`

**Interfaces:**
- Consumes: `common_utils.suspended_waiting_cursor()` from Task A1, `common_utils.waiting_cursor` (existing decorator).

**Read this before editing — a mechanical conversion here introduces a bug.** The current method is:

```python
    def show(self) -> None:
        common_utils.start_waiting_cursor()
        obsid_p = layer_utils.get_selected_features_as_tuple("obs_points")
        obsid_l = layer_utils.get_selected_features_as_tuple("obs_lines")
        common_utils.stop_waiting_cursor()

        dlg = ExportCsvDialog(None)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        common_utils.start_waiting_cursor()
        self.ID_obs_points = obsid_p
        self.ID_obs_lines = obsid_l
        self.export_2_csv(dlg.export_folder, dlg.strip_html)
        common_utils.stop_waiting_cursor()
```

The `return` on the rejected-dialog path sits *between* the stop and the start, so today it happens to be balanced. If you wrap the dialog in `with suspended_waiting_cursor():` and leave the `return` inside, the `finally` restores depth 1 and the method returns holding a cursor nobody pops — a **leak this task would introduce**. Keep the `return` outside the `with`, and let the decorator own the outer level so an exception in `export_2_csv` is also covered.

- [ ] **Step 1: Confirm the gate is green**

Run: `python3 -m pytest test/test_export_data.py -q -m "not postgis"`
Expected: PASS. Record the count.

- [ ] **Step 2: Rewrite `show`**

```python
    @common_utils.waiting_cursor
    def show(self) -> None:
        obsid_p = layer_utils.get_selected_features_as_tuple("obs_points")
        obsid_l = layer_utils.get_selected_features_as_tuple("obs_lines")

        with common_utils.suspended_waiting_cursor():
            dlg = ExportCsvDialog(None)
            accepted = dlg.exec() == QDialog.DialogCode.Accepted

        if not accepted:
            return

        self.ID_obs_points = obsid_p
        self.ID_obs_lines = obsid_l
        self.export_2_csv(dlg.export_folder, dlg.strip_html)
```

The decorator pushes one level and pops it in its own `finally`, so every exit path — accepted, rejected, or an exception from `export_2_csv` — is balanced.

- [ ] **Step 3: Verify balance directly**

The tests mock the cursor, so they cannot catch an imbalance. Prove it:

```bash
python3 - <<'PY'
import sys; sys.path.insert(0, "_pkgroot")
from unittest import mock
from midvatten.tools.utils import common_utils

with mock.patch("qgis.PyQt.QtWidgets.QApplication") as app:
    @common_utils.waiting_cursor
    def rejected():
        with common_utils.suspended_waiting_cursor():
            accepted = False
        if not accepted:
            return
    @common_utils.waiting_cursor
    def raises():
        with common_utils.suspended_waiting_cursor():
            pass
        raise RuntimeError("export failed")

    common_utils._cursor_depth = 0
    rejected()
    print("rejected  -> depth", common_utils.waiting_cursor_depth(), "(want 0)")
    common_utils._cursor_depth = 0
    try:
        raises()
    except RuntimeError:
        pass
    print("exception -> depth", common_utils.waiting_cursor_depth(), "(want 0)")
    print("balanced:", app.setOverrideCursor.call_count == app.restoreOverrideCursor.call_count)
PY
```

Expected: both depths 0, `balanced: True`.

- [ ] **Step 4: Run the tests**

Run: `python3 -m pytest test/test_export_data.py -q -m "not postgis"`
Expected: same count as Step 1, all pass.

- [ ] **Step 5: Format and commit**

```bash
ruff check --fix tools/export_data.py
ruff format tools/export_data.py
git add tools/export_data.py
git commit -m "refactor: scope the export dialog's cursor suspension"
```

---

### Task A5: Convert `export_fieldlogger.py`

**Files:**
- Modify: `tools/export_fieldlogger.py:914-923` (`write_to_file`)
- Test: `test/test_export_fieldlogger.py`

**Interfaces:**
- Consumes: `common_utils.suspended_waiting_cursor()` from Task A1.

Note this module imports the cursor functions by name at line 52 (`from midvatten.tools.utils.common_utils import start_waiting_cursor, stop_waiting_cursor`) rather than via the `common_utils` namespace, and it also imports `common_utils` itself (it calls `common_utils.get_save_file_name_no_extension`). Use the namespace form for the new call to match the surrounding line.

- [ ] **Step 1: Confirm the gate is green**

Run: `python3 -m pytest test/test_export_fieldlogger.py -q -m "not postgis"`
Expected: PASS. Record the count.

- [ ] **Step 2: Convert `write_to_file`**

Replace:

```python
        stop_waiting_cursor()
        filename = common_utils.get_save_file_name_no_extension(
            parent=None,
            caption=QCoreApplication.translate(
                "ExportToFieldLogger", "Choose a file name"
            ),
            directory="",
            filter=filter,
        )
        start_waiting_cursor()
```

with:

```python
        with common_utils.suspended_waiting_cursor():
            filename = common_utils.get_save_file_name_no_extension(
                parent=None,
                caption=QCoreApplication.translate(
                    "ExportToFieldLogger", "Choose a file name"
                ),
                directory="",
                filter=filter,
            )
```

- [ ] **Step 3: Check whether the named imports are now orphaned**

```bash
grep -n "start_waiting_cursor\|stop_waiting_cursor" tools/export_fieldlogger.py
ruff check --select F401 tools/export_fieldlogger.py
```

`stop_waiting_cursor()` is still used at line 771 (a terminal pop — leave it). `start_waiting_cursor()` is used at line 748. If either grep shows a name is now unused, remove it from the line 52 import; otherwise leave the import alone. **Do not guess — F401 is disabled in this repo's default ruff config, so the explicit `--select F401` is the only check that reports it.**

- [ ] **Step 4: Run the tests**

Run: `python3 -m pytest test/test_export_fieldlogger.py -q -m "not postgis"`
Expected: same count as Step 1, all pass.

- [ ] **Step 5: Format and commit**

```bash
ruff check --fix tools/export_fieldlogger.py
ruff format tools/export_fieldlogger.py
git add tools/export_fieldlogger.py
git commit -m "refactor: scope the fieldlogger save dialog's cursor suspension"
```

---

### Part A checkpoint

- [ ] **Confirm every suspension is converted.**

```bash
grep -rn "stop_waiting_cursor()" --include=*.py tools/ | grep -v "_pkgroot" | wc -l
grep -rn -A 6 "stop_waiting_cursor()" --include=*.py tools/ | grep -v "_pkgroot" | grep -c "start_waiting_cursor()"
```

The second number is the count of remaining `stop … start` pairs within six lines of each other. Expected: **0**. Any non-zero result is a suspension this plan missed — report it rather than converting it blind; it may be one of the deliberate terminal pops.

- [ ] **Run the full suite.**

```bash
python3 -m pytest test/ -q -m "not postgis" 2>&1 | tail -3
```

Expected: `978 passed, 1 skipped, 290 deselected` — the baseline 975 plus Task A1's three new tests. Any other number needs explaining before Part B.

---

# Part B — Destination table travels with the frame shape

## The defect, precisely

`tools/import_logger/pipeline.py` decides the frame **shape** per logger kind:

```python
if parsed.kind is LoggerDataKind.BAROMETRIC:
    destination = baro_to_meteo(data, obsid, instrumentid)
elif parsed.kind is LoggerDataKind.WATER_LEVEL:
    destination = data.loc[:, WATER_LEVEL_COLUMNS].copy()
```

`tools/import_logger/importer.py:105` separately decides the **table**:

```python
_DESTINATION_TABLES = {
    LoggerDataKind.WATER_LEVEL: "w_levels_logger",
    LoggerDataKind.BAROMETRIC: "meteo",
}
```

These two must agree — a meteo-shaped frame written to `w_levels_logger` is a data-corruption class of failure — yet they are edited in different layers, and only the pipeline half fails loudly on an unknown kind. Setting the table where the shape is already chosen makes disagreement impossible.

**Note:** this deliberately does *not* reintroduce a registry keyed on `LoggerDataKind`. The previous cleanup removed two such registries; adding the field is the smaller change that closes the split without reversing that.

## File structure — Part B

| File | Responsibility after this part |
|---|---|
| `tools/import_logger/models.py` | Gains `WATER_LEVEL_TABLE` / `METEO_TABLE` constants, placed directly beside the column tuples they pair with, and a `dest_table` field on `PreparedLoggerFile`. |
| `tools/import_logger/pipeline.py` | Sets `dest_table` in the same branch that selects the columns. |
| `tools/import_logger/importer.py` | Reads `prepared.dest_table`; `_DESTINATION_TABLES` deleted. |

`PreparedLoggerFile` has exactly one construction site (`pipeline.py:408`) — verified — so a required field breaks nothing.

---

### Task B1: Pair the table name with the shape

**Files:**
- Modify: `tools/import_logger/models.py` (constants beside the column tuples; `dest_table` field on `PreparedLoggerFile`), `tools/import_logger/pipeline.py` (`run_post_resolution_pipeline`)
- Test: `test/test_import_logger_pipeline.py`

**Interfaces:**
- Produces:
  - `models.WATER_LEVEL_TABLE: str` = `"w_levels_logger"`
  - `models.METEO_TABLE: str` = `"meteo"`
  - `PreparedLoggerFile.dest_table: str` — a required field, positioned after `obsid` and before `notices` (which has a default, so it must stay last).

- [ ] **Step 1: Write the failing test**

Append to `test/test_import_logger_pipeline.py`. This asserts the invariant the whole change exists to protect — that the columns and the table always agree — rather than just that a field exists.

```python
@pytest.mark.parametrize(
    ("kind", "expected_columns", "expected_table"),
    [
        (LoggerDataKind.WATER_LEVEL, WATER_LEVEL_COLUMNS, "w_levels_logger"),
        (LoggerDataKind.BAROMETRIC, METEO_COLUMNS, "meteo"),
    ],
)
def test_prepared_file_table_always_matches_its_shape(
    kind, expected_columns, expected_table
) -> None:
    """The destination table and the frame shape are chosen together.

    They used to be decided in different modules; a meteo-shaped frame routed
    to w_levels_logger is a data-corruption failure, so pin them as one fact.
    """
    parsed = parsed_file(
        logger_frame(["2025-01-01 00:00:00"], head=[1.0], baro=[2.0]), kind=kind
    )

    prepared = run_post_resolution_pipeline(
        parsed, "rb1", {}, LoggerImportOptions(import_all_data=True)
    )

    assert tuple(prepared.data.columns) == expected_columns
    assert prepared.dest_table == expected_table
```

Add `METEO_COLUMNS` and `WATER_LEVEL_COLUMNS` to the existing `from midvatten.tools.import_logger.models import (...)` block in that file if they are not already imported.

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest test/test_import_logger_pipeline.py -k table_always_matches -v`
Expected: FAIL, `AttributeError: 'PreparedLoggerFile' object has no attribute 'dest_table'`.

- [ ] **Step 3: Add the constants beside their column tuples**

In `tools/import_logger/models.py`, place each table name directly after the column tuple it pairs with, so the pairing is visible in one glance:

```python
WATER_LEVEL_COLUMNS = (
    "date_time",
    "head_cm",
    "temp_degc",
    "cond_mscm",
    "obsid",
)
WATER_LEVEL_TABLE = "w_levels_logger"

METEO_COLUMNS = (
    "obsid",
    "instrumentid",
    "parameter",
    "date_time",
    "reading_num",
    "unit",
)
METEO_TABLE = "meteo"
```

- [ ] **Step 4: Add the field**

In `tools/import_logger/models.py`, add `dest_table` to `PreparedLoggerFile` after `obsid` and before `notices`:

```python
@dataclass
class PreparedLoggerFile:
    data: pd.DataFrame
    filename: str
    source_path: str
    kind: LoggerDataKind
    location: str | None
    serial_number: str | None
    obsid: str
    dest_table: str
    notices: tuple[LoggerPipelineNotice, ...] = field(default_factory=tuple)
```

- [ ] **Step 5: Set it where the shape is chosen**

In `tools/import_logger/pipeline.py`, extend the `.models` import to include `METEO_TABLE` and `WATER_LEVEL_TABLE`, then change the branch:

```python
    if parsed.kind is LoggerDataKind.BAROMETRIC:
        destination = baro_to_meteo(data, obsid, instrumentid)
        dest_table = METEO_TABLE
    elif parsed.kind is LoggerDataKind.WATER_LEVEL:
        destination = data.loc[:, WATER_LEVEL_COLUMNS].copy()
        dest_table = WATER_LEVEL_TABLE
    else:
        # The registry this replaced raised KeyError on an unknown kind. Keep
        # failing loudly: silently shaping a new kind as water level would
        # write it to the wrong destination table.
        raise LoggerPipelineError(f"unsupported logger kind {parsed.kind!r}")
```

and pass it in the constructor call below:

```python
    return PreparedLoggerFile(
        data=destination,
        filename=parsed.filename,
        source_path=parsed.source_path,
        kind=parsed.kind,
        location=parsed.location,
        serial_number=parsed.serial_number,
        obsid=obsid,
        dest_table=dest_table,
        notices=parsed.notices,
    )
```

- [ ] **Step 6: Run the tests**

Run: `python3 -m pytest test/test_import_logger_pipeline.py test/test_import_logger.py -q -m "not postgis"`
Expected: all pass, **two** more than before — the new test is parametrized over both logger kinds.

- [ ] **Step 7: Format and commit**

```bash
ruff check --fix tools/import_logger/models.py tools/import_logger/pipeline.py test/test_import_logger_pipeline.py
ruff format tools/import_logger/models.py tools/import_logger/pipeline.py test/test_import_logger_pipeline.py
git add tools/import_logger/models.py tools/import_logger/pipeline.py test/test_import_logger_pipeline.py
git commit -m "refactor: carry the destination table on the prepared file"
```

---

### Task B2: Consume it and delete the dialog-side table

**Files:**
- Modify: `tools/import_logger/importer.py:105-108` (delete `_DESTINATION_TABLES`), `:712` (read the field)
- Test: `test/test_import_logger.py` — existing end-to-end coverage is the gate. `TestLoggerImportBaroSpatialite` asserts baro rows land in `meteo` and *not* in `w_levels_logger`, which is exactly the routing this change protects.

**Interfaces:**
- Consumes: `PreparedLoggerFile.dest_table` from Task B1.

- [ ] **Step 1: Read the field**

In `tools/import_logger/importer.py`, in `_import_one_prepared_file`:

```python
            LoggerDbImportRequest(
                filename=prepared.source_path,
                dest_table=prepared.dest_table,
                frame=prepared.data,
                series=series,
            ),
```

- [ ] **Step 2: Delete the module constant**

Remove from `tools/import_logger/importer.py`:

```python
_DESTINATION_TABLES = {
    LoggerDataKind.WATER_LEVEL: "w_levels_logger",
    LoggerDataKind.BAROMETRIC: "meteo",
}
```

- [ ] **Step 3: Confirm it is gone and nothing else referenced it**

```bash
grep -rn "_DESTINATION_TABLES" --include=*.py . | grep -v "_pkgroot\|\.worktrees"
ruff check --select F401 tools/import_logger/importer.py
```

Expected: no output from the first. `LoggerDataKind` is still used elsewhere in the file (the baro-seeding check and the series-spec branch), so its import stays — but confirm with the F401 run rather than assuming.

- [ ] **Step 4: Run the tests**

Run: `python3 -m pytest test/test_import_logger.py test/test_import_logger_workers.py test/test_import_logger_pipeline.py -q -m "not postgis"`
Expected: all pass, same count as Task B1 Step 6.

- [ ] **Step 5: Format and commit**

```bash
ruff check --fix tools/import_logger/importer.py
ruff format tools/import_logger/importer.py
git add tools/import_logger/importer.py
git commit -m "refactor: drop the dialog-side kind-to-table map"
```

---

## Finishing up

- [ ] **Full suite.**

```bash
python3 -m pytest test/ -q -m "not postgis" 2>&1 | tail -3
```

Expected: `980 passed, 1 skipped, 290 deselected` — baseline 975, plus three from Task A1 and **two** from Task B1 (its test is parametrized over both logger kinds, so it collects as two).

- [ ] **PostGIS suite, on an uncontended database.** Both parts touch code with PostGIS twins (`create_db.populate_postgis_db` in Part A, the logger import path in Part B).

```bash
pgrep -af "python3 -m pytest" | grep -v grep    # confirm nothing else is running
python3 -m pytest test/ -q -m postgis 2>&1 | tail -3
```

Expected: `289 passed, 1 skipped`.

- [ ] **midv_addons contract.** Part A changes `common_utils`, whose cursor functions are in the addons re-export contract.

```bash
cd ~/dev/midv_addons
W=<path to your worktree>
PYTHONPATH=$W/_pkgroot python3 -m pytest midv_addons/test/test_midvatten_compat.py -q 2>&1 | tail -3
```

Expected: `73 passed, 2 failed` — the two failures are pre-existing on `ai_test` and unrelated (`water_quality_standard has no column named description`, and `dbconnection.schema` not writable). **This only runs if the `fix/compat-test-qapplication-hang` branch is merged in that repo**; without it the suite hangs at collection. If it hangs, note it and move on — it is not this plan's regression.

- [ ] **Invoke `superpowers:finishing-a-development-branch`** to decide how the branch integrates back into `ai_test`.

---

## Deferred — deliberately not in this plan

- **Pushing suspension inside `Askuser` / `filter_nonexisting_values_and_ask` / the file-dialog helpers**, so call sites stop touching the cursor entirely. Considered and declined: it changes behaviour at every modal that does *not* currently suspend, which is a wider surface than these two defects justify. `suspended_waiting_cursor()` makes that a later one-line change per helper if wanted.
- **`import_data_to_db.py:1296`**, where `import_exception_handler` still does a bare single `stop_waiting_cursor()` rather than `unwind_waiting_cursor(entry_depth)`. Two restoration policies for one job. Out of scope: it is shared infrastructure used by every importer, not just the ones this plan touches.
- **Making `start_waiting_cursor` / `stop_waiting_cursor` no-ops off the GUI thread**, which would let the `manage_wait_cursor` flag be deleted from `import_data_to_db` (a public parameter, an attribute, and three guards, all encoding a thread-affinity fact in the data layer). A genuinely good fix, and a separate one.
- **`LoggerKindSpec` holding columns + table + required lookup rows**, which would also give `BARO_METEO_PARAMS` a home and let the worker seed lookups inside its own transaction. Declined in favour of the `dest_table` field because it re-adds a `LoggerDataKind`-keyed registry that the previous cleanup deliberately removed. Revisit if a third logger kind ever appears — at that point the registry earns its keep.
- **`ImportOutcome` enum** replacing the `reason`-string classification in `LoggerDbImportResult`. Design change, not cleanup.
