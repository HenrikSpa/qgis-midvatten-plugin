# Logger Import Performance & UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make DiverOffice/logger imports fast on large databases, add progress feedback, and remove the unnecessary FK confirmation dialog.

**Architecture:** Three independent changes to `import_data_to_db.py` (duplicate-check query fix, progress callback, skip-confirmation fix) plus one caller-side change in `import_logger/importer.py` (create QProgressDialog, pass callback and skip_confirmation flag).

**Tech Stack:** Python 3, PyQt5 (QProgressDialog, QApplication.processEvents), SQLite/PostgreSQL SQL

---

### Task 1: Fix duplicate datetime query to use index-friendly range scan

**Files:**
- Modify: `tools/import_data_to_db.py:690-737` — `delete_existing_date_times_from_temptable`

This is the root cause of the performance problem. The current code applies `strftime('%Y-%m-%d %H:%M', ...)` to every row in the destination table, preventing index use. Replace with a range-based comparison.

- [ ] **Step 1: Run existing tests to confirm they pass before changes**

Run: `python3 -m pytest test/test_import_data_to_db.py::TestDeleteExistingDateTimesFromTemptableSpatialite -xvs`
Expected: All 5 tests PASS

- [ ] **Step 2: Replace the strftime equality with a range-based condition**

In `tools/import_data_to_db.py`, replace the method `delete_existing_date_times_from_temptable` (lines 690-737) with:

```python
    def delete_existing_date_times_from_temptable(
        self,
        primary_keys: List[str],
        dest_table: str,
        dbconnection: DbConnectionManager,
    ) -> int:
        """Delete temp rows whose minute-level date_time already exists in dest.

        Two date_times are considered duplicates when they fall in the same minute.
        Uses a range comparison on the destination side so the PK index on
        (obsid, date_time) is used for each lookup instead of a full table scan.
        """
        pks_non_dt = [pk for pk in primary_keys if pk != "date_time"]

        temp_ident = dbconnection.ident(self.temptable_name)
        dest_ident = (
            dbconnection.ident(f"{dbconnection.schema}.{dest_table}")
            if dbconnection.is_postgresql()
            else dbconnection.ident(dest_table)
        )

        dt = dbconnection.ident("date_time")

        if dbconnection.is_postgresql():
            minute_start = f"date_trunc('minute', {temp_ident}.{dt}::timestamp)"
            minute_end = f"date_trunc('minute', {temp_ident}.{dt}::timestamp) + interval '1 minute'"
        else:
            minute_start = f"(substr({temp_ident}.{dt}, 1, 16) || ':00')"
            minute_end = f"(substr({temp_ident}.{dt}, 1, 16) || ':60')"

        conditions = [
            f"d.{q} = {temp_ident}.{q}"
            for pk in pks_non_dt
            for q in (dbconnection.ident(pk),)
        ]
        conditions.append(f"d.{dt} >= {minute_start}")
        conditions.append(f"d.{dt} < {minute_end}")

        sql = (
            f"DELETE FROM {temp_ident} WHERE EXISTS ("
            f"SELECT 1 FROM {dest_ident} d WHERE {' AND '.join(conditions)})"
        )
        dbconnection.execute(sql)
        return dbconnection.cursor.rowcount
```

- [ ] **Step 3: Run the duplicate datetime tests**

Run: `python3 -m pytest test/test_import_data_to_db.py::TestDeleteExistingDateTimesFromTemptableSpatialite -xvs`
Expected: All 5 tests PASS with identical semantics (same minute = duplicate)

- [ ] **Step 4: Run full import test suite to check for regressions**

Run: `python3 -m pytest test/test_import_data_to_db.py -x`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add tools/import_data_to_db.py
git commit -m "perf: use index-friendly range scan for duplicate datetime check

Replace strftime equality with range-based comparison (>= minute_start,
< minute_end) so SQLite can use the PK index on (obsid, date_time).
Eliminates full table scans on large w_levels_logger tables."
```

---

### Task 2: Strengthen skip_confirmation to suppress dialog in both branches

**Files:**
- Modify: `tools/import_data_to_db.py:405-442` — `_ask_user_to_proceed`

Currently `skip_confirmation=True` only suppresses the dialog when no rows were removed. When duplicates exist (common case), the "There are X out of Y rows" dialog still appears. Fix: when `skip_confirmation` is set, skip the dialog entirely in both branches and log the info instead.

- [ ] **Step 1: Modify `_ask_user_to_proceed` to respect skip_confirmation in both branches**

In `tools/import_data_to_db.py`, replace `_ask_user_to_proceed` (lines 405-442) with:

```python
    def _ask_user_to_proceed(
        self,
        remaining_rownumbers: Tuple,
        all_rownumbers: Tuple,
        import_messages: List[str],
    ):
        """Assemble the confirmation message and ask the user whether to proceed.

        Raises UserInterruptError if the user chooses not to import.
        """
        if self.foreign_keys_import_question:
            if len(remaining_rownumbers) != len(all_rownumbers):
                common_utils.MessagebarAndLog.info(
                    log_msg=QCoreApplication.translate(
                        "midv_data_importer",
                        "Skipping confirmation dialog: %s out of %s rows to import (duplicates removed).",
                    )
                    % (str(len(remaining_rownumbers)), str(len(all_rownumbers)))
                )
            return

        if len(remaining_rownumbers) == len(all_rownumbers):
            import_messages.append(
                QCoreApplication.translate(
                    "midv_data_importer", "Proceed with import?"
                )
            )
            self.foreign_keys_import_question = 1
        else:
            import_messages.append(
                QCoreApplication.translate(
                    "midv_data_importer",
                    """There are %s out of %s number of rows to import (see log for more info about removed rows).\n\nProceed with import?""",
                )
                % (str(len(remaining_rownumbers)), str(len(all_rownumbers)))
            )

        if import_messages:
            stop_question = common_utils.Askuser(
                "YesNo",
                "\n".join(import_messages),
                QCoreApplication.translate("midv_data_importer", "Info"),
            )
            if stop_question.result == 0:
                raise UserInterruptError()
```

- [ ] **Step 2: Run import tests to verify no regressions**

Run: `python3 -m pytest test/test_import_data_to_db.py -x`
Expected: All tests PASS. Tests that mock `Askuser` are unaffected because the mock already returns without blocking. Tests that use `skip_confirmation=True` will now skip both branches.

- [ ] **Step 3: Commit**

```bash
git add tools/import_data_to_db.py
git commit -m "fix: skip_confirmation suppresses dialog even when rows removed

Previously skip_confirmation only skipped the dialog when all rows
remained. Now it skips both branches and logs duplicate counts instead."
```

---

### Task 3: Add progress_callback parameter to general_import

**Files:**
- Modify: `tools/import_data_to_db.py:48-59` — `general_import` signature
- Modify: `tools/import_data_to_db.py:99-189` — add callback calls at phase boundaries

- [ ] **Step 1: Add progress_callback parameter and call it at phase boundaries**

In `tools/import_data_to_db.py`, update the `general_import` signature (line 48-59) to add the parameter:

```python
    def general_import(
        self,
        dest_table: str,
        file_data: Any,
        allow_obs_fk_import: bool = False,
        _dbconnection: Optional[DbConnectionManager] = None,
        dump_temptable: bool = False,
        source_srid: Optional[int] = None,
        skip_confirmation: bool = False,
        binary_geometry: bool = False,
        defer_commit: bool = False,
        progress_callback: Optional[Callable[[str], None]] = None,
    ):
```

Then insert callback calls at the phase boundaries in the method body. After line 99 (`common_utils.start_waiting_cursor()`), before `self._validate_and_connect`:

```python
            if progress_callback:
                progress_callback(
                    QCoreApplication.translate(
                        "midv_data_importer", "Validating columns..."
                    )
                )
```

Before `self.list_to_table` (line 116):

```python
            if progress_callback:
                progress_callback(
                    QCoreApplication.translate(
                        "midv_data_importer", "Creating temporary table..."
                    )
                )
```

Before `self._remove_duplicate_datetimes` (line 137):

```python
            if progress_callback:
                progress_callback(
                    QCoreApplication.translate(
                        "midv_data_importer", "Checking for duplicate timestamps..."
                    )
                )
```

Before `self._build_and_execute_insert` (line 180):

```python
            if progress_callback:
                progress_callback(
                    QCoreApplication.translate(
                        "midv_data_importer", "Importing rows..."
                    )
                )
```

- [ ] **Step 2: Run import tests to confirm nothing breaks**

Run: `python3 -m pytest test/test_import_data_to_db.py -x`
Expected: All tests PASS (callback is optional, defaults to None)

- [ ] **Step 3: Commit**

```bash
git add tools/import_data_to_db.py
git commit -m "feat: add progress_callback to general_import

Optional callback called at phase boundaries (validate, temp table,
duplicate check, insert) so callers can update progress UI."
```

---

### Task 4: Add QProgressDialog to the logger importer

**Files:**
- Modify: `tools/import_logger/importer.py:460-520` — file-parsing loop progress
- Modify: `tools/import_logger/importer.py:733-735` — baro import path (skip_confirmation + callback)
- Modify: `tools/import_logger/importer.py:843-851` — water-level import path (skip_confirmation + callback)

- [ ] **Step 1: Add QProgressDialog import**

In `tools/import_logger/importer.py`, add to the existing QtWidgets import area (near line 12):

```python
from qgis.PyQt.QtWidgets import QProgressDialog, QApplication
```

Since `QtWidgets` is already imported as `qgis.PyQt.QtWidgets as QtWidgets`, you can use `QtWidgets.QProgressDialog` and `QtWidgets.QApplication` instead. Either form is fine; using the already-imported module alias is consistent with existing code.

- [ ] **Step 2: Create the progress dialog at the start of start_import and add per-file updates**

In `tools/import_logger/importer.py`, in `start_import()` (line 464), after `common_utils.start_waiting_cursor()` (line 475), add the progress dialog creation and a helper:

```python
        progress = QtWidgets.QProgressDialog(
            QCoreApplication.translate("LoggerImport", "Importing logger data..."),
            QCoreApplication.translate("LoggerImport", "Cancel"),
            0, 0,
            self,
        )
        progress.setWindowModality(2)  # Qt.WindowModal
        progress.setMinimumDuration(0)
        progress.show()
        QtWidgets.QApplication.processEvents()

        def _progress_callback(msg: str) -> None:
            if progress.wasCanceled():
                raise import_data_to_db.UserInterruptError()
            progress.setLabelText(msg)
            QtWidgets.QApplication.processEvents()
```

Note: `import_data_to_db` is already imported. `UserInterruptError` is defined in `midvatten.tools.utils.exceptions` but is also importable from the already-imported `import_data_to_db` module. Check which is already in scope — use `from midvatten.tools.utils.exceptions import UserInterruptError` which is not currently imported in importer.py, so add it to the imports at the top:

```python
from midvatten.tools.utils.exceptions import UserInterruptError
```

Then in the file-parsing loop (line 482, `for selected_file in files:`), at the top of the loop body, add:

```python
            _progress_callback(
                QCoreApplication.translate("LoggerImport", "Parsing file %s of %s...")
                % (files.index(selected_file) + 1, len(files))
            )
```

- [ ] **Step 3: Pass skip_confirmation and progress_callback to general_import calls**

For the **water-level path** (line 846), change:
```python
                importer.general_import("w_levels_logger", file_to_import_to_db)
```
to:
```python
                importer.general_import(
                    "w_levels_logger",
                    file_to_import_to_db,
                    skip_confirmation=True,
                    progress_callback=_progress_callback,
                )
```

For the **baro path** (line 735), change:
```python
                    importer.general_import("meteo", meteo_rows)
```
to:
```python
                    importer.general_import(
                        "meteo",
                        meteo_rows,
                        skip_confirmation=True,
                        progress_callback=_progress_callback,
                    )
```

- [ ] **Step 4: Close the progress dialog on all exit paths**

The `start_import` method has several early-return paths where `stop_waiting_cursor()` is called. Add `progress.close()` before each `common_utils.stop_waiting_cursor()` call and also at the end of the method. The relevant locations in `start_import`:

- Line 536-537 (cancel from parser): add `progress.close()` before `common_utils.stop_waiting_cursor()`
- Line 637 (no existing obsids): add `progress.close()` before `common_utils.stop_waiting_cursor()`
- Line 645 (filter_nonexisting returned nothing): add `progress.close()` before `common_utils.stop_waiting_cursor()`
- Line 711-712 (baro no data): add `progress.close()` before `common_utils.stop_waiting_cursor()`
- Line 750 (baro end): add `progress.close()` before `common_utils.stop_waiting_cursor()`
- Line 826-827 (no new data): add `progress.close()` before `common_utils.stop_waiting_cursor()`
- Line 860 (end of method): add `progress.close()` before `common_utils.stop_waiting_cursor()`

Since there are many exit points, a cleaner approach is to wrap the progress dialog in a try/finally. After creating the progress dialog and `_progress_callback`, wrap the rest of the method body in:

```python
        try:
            # ... existing code from the for loop through to the end ...
        finally:
            progress.close()
```

This ensures the dialog is always closed, even on exceptions. The existing `common_utils.stop_waiting_cursor()` calls remain as-is.

- [ ] **Step 5: Run the logger import tests**

Run: `python3 -m pytest test/test_import_diveroffice.py -x`
Expected: All tests PASS

If there are no specific DiverOffice import tests, run the general CSV import tests that touch w_levels_logger:
Run: `python3 -m pytest test/test_import_general_csv_gui.py -x -k "w_levels_logger"`

- [ ] **Step 6: Run the full test suite**

Run: `python3 -m pytest test/ -x`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add tools/import_logger/importer.py
git commit -m "feat: add progress dialog and skip confirmation for logger imports

Show QProgressDialog during file parsing and database import phases.
Pass skip_confirmation=True to suppress the unnecessary FK dialog.
Progress updates at phase boundaries via the new progress_callback."
```

---

### Task 5: Run ruff and final verification

**Files:**
- All modified files

- [ ] **Step 1: Run ruff check and format**

```bash
ruff check --fix tools/import_data_to_db.py tools/import_logger/importer.py
ruff format tools/import_data_to_db.py tools/import_logger/importer.py
```

- [ ] **Step 2: Run the full test suite one final time**

Run: `python3 -m pytest test/ -x`
Expected: All tests PASS

- [ ] **Step 3: Commit any ruff fixes if needed**

```bash
git add tools/import_data_to_db.py tools/import_logger/importer.py
git commit -m "style: ruff fixes for logger import performance changes"
```
