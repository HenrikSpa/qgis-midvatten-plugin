> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-06-16 · modified: 2026-06-16 · archived: 2026-07-31

# CSV import UX cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the General CSV importer's three sequential load popups with one consolidated dialog (file + encoding + live preview + header), and make the start-import confirmation fire only on actual row loss while the foreign-key note becomes a quiet log message.

**Architecture:** Part 1 adds a `CsvFileLoadDialog(QDialog)` in `tools/import_general_csv_gui.py` and rewrites `GeneralCsvImportGui.load_files()` to drive it; the downstream parse/header pipeline is unchanged. Part 2 edits shared importer code in `tools/import_data_to_db.py` (`general_import`, `_ask_user_to_proceed`, `_handle_foreign_keys`) so the change applies to all importers (CSV / Fieldlogger / Interlab4); it builds on the landed duplicate-message work (`bc65dd9`).

**Tech Stack:** Python 3, PyQt (qgis.PyQt), QGIS plugin, SpatiaLite/PostGIS, pytest.

**Spec:** `docs/superpowers/specs/2026-06-16-csv-import-ux-design.md`

**Pre-flight:** Work in an isolated git worktree (branch `csv-import-ux` from `ai_test`), created via `superpowers:using-git-worktrees`. If the worktree predates the `_pkgroot/` test fix, run `git merge ai_test` first. Use `python3`, never `python`.

---

## File Structure

- **Modify** `tools/import_general_csv_gui.py` — add module constants + two encoding-persistence helpers + `CsvFileLoadDialog`; rewrite `GeneralCsvImportGui.load_files()`.
- **Modify** `tools/import_data_to_db.py` — `general_import` (drop FK-note seed), `_ask_user_to_proceed` (modal only on row loss), `_handle_foreign_keys` (quiet FK log).
- **Modify** `test/test_import_general_csv_gui.py` — new unit tests for helpers + dialog; update `_run_w_levels_logger_import` to mock `CsvFileLoadDialog`.
- **Modify** `test/test_import_general_csv_gui_backends.py` — update any mocking of `ask_for_charset` / `QFileDialog.getOpenFileName` / header `Askuser` in the file-load path.
- **Modify** `test/test_import_data_to_db.py` — new tests for the modal-only-on-row-loss behavior and the quiet FK log.

---

## Task 1: Encoding constants + persistence helpers

**Files:**
- Modify: `tools/import_general_csv_gui.py` (top-level, near the existing `SERIES_FIELDS` constants; and the import line `from qgis.PyQt.QtCore import QCoreApplication`)
- Test: `test/test_import_general_csv_gui.py`

- [ ] **Step 1: Write the failing tests**

Add to `test/test_import_general_csv_gui.py` (top-level, after the existing imports — `from unittest import mock` is already imported there):

```python
class TestCsvEncodingHelpers:
    def test_last_encoding_returns_stored_value(self):
        with mock.patch("midvatten.tools.import_general_csv_gui.QSettings") as mock_qs:
            mock_qs.return_value.value.return_value = "cp1252"
            assert import_general_csv_gui._last_csv_encoding() == "cp1252"

    def test_last_encoding_falls_back_to_locale(self):
        with mock.patch(
            "midvatten.tools.import_general_csv_gui.QSettings"
        ) as mock_qs, mock.patch(
            "midvatten.tools.import_general_csv_gui.midvatten_utils.getcurrentlocale",
            return_value=("sv_SE", "iso-8859-1"),
        ):
            mock_qs.return_value.value.return_value = None
            assert import_general_csv_gui._last_csv_encoding() == "iso-8859-1"

    def test_save_encoding_writes_setting(self):
        with mock.patch("midvatten.tools.import_general_csv_gui.QSettings") as mock_qs:
            import_general_csv_gui._save_csv_encoding("utf-8")
            mock_qs.return_value.setValue.assert_called_once_with(
                import_general_csv_gui.CSV_ENCODING_SETTING, "utf-8"
            )
```

Make sure the module is importable as `import_general_csv_gui` in the test file. It already imports `from midvatten.tools.import_general_csv_gui import GeneralCsvImportGui, ImportTableChooser`; add at the top:

```python
from midvatten.tools import import_general_csv_gui
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest test/test_import_general_csv_gui.py::TestCsvEncodingHelpers -v`
Expected: FAIL — `AttributeError: module ... has no attribute '_last_csv_encoding'` (and `CSV_ENCODING_SETTING`).

- [ ] **Step 3: Implement constants + helpers**

In `tools/import_general_csv_gui.py`, change the QtCore import line:

```python
from qgis.PyQt.QtCore import QCoreApplication, QSettings
```

Then add, just after the `SERIES_CARRIER_PREFIX`/`series_carrier` block near the top of the module:

```python
# Persisted across sessions so the importer reopens with the user's last choice
# (encoding cannot be reliably auto-detected, so we never guess silently).
CSV_ENCODING_SETTING = "Midvatten/csv_import_encoding"
COMMON_ENCODINGS = ["utf-8", "iso-8859-1", "cp1250", "cp1252"]


def _last_csv_encoding() -> str:
    """Last-used encoding from QSettings, else the OS locale, else utf-8."""
    stored = QSettings().value(CSV_ENCODING_SETTING)
    if stored:
        return str(stored)
    try:
        return midvatten_utils.getcurrentlocale()[1]
    except Exception:
        return "utf-8"


def _save_csv_encoding(encoding: str) -> None:
    QSettings().setValue(CSV_ENCODING_SETTING, encoding)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest test/test_import_general_csv_gui.py::TestCsvEncodingHelpers -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add tools/import_general_csv_gui.py test/test_import_general_csv_gui.py
git commit -m "feat: add CSV import encoding persistence helpers"
```

---

## Task 2: CsvFileLoadDialog

**Files:**
- Modify: `tools/import_general_csv_gui.py` (new `CsvFileLoadDialog` class; place it directly above `class GeneralCsvImportGui`)
- Test: `test/test_import_general_csv_gui.py`

- [ ] **Step 1: Write the failing tests**

Add to `test/test_import_general_csv_gui.py`. These construct the dialog directly (never call `exec()`, which would block). The existing spatialite test base / `qgis` app fixture provides a QApplication; place this class next to the other dialog tests and reuse the same imports (`qgis`, `file_utils`).

```python
@pytest.mark.spatialite
class TestCsvFileLoadDialog(utils_for_tests.MidvattenTestSpatialiteDbSv):
    def _dialog(self):
        with mock.patch("midvatten.tools.import_general_csv_gui.QSettings") as mock_qs:
            mock_qs.return_value.value.return_value = "utf-8"
            return import_general_csv_gui.CsvFileLoadDialog()

    def test_ok_disabled_until_file_chosen(self):
        dlg = self._dialog()
        assert dlg._ok_button().isEnabled() is False

    def test_properties_reflect_widgets(self):
        dlg = self._dialog()
        dlg._encoding.setEditText("cp1252")
        dlg._header.setChecked(False)
        assert dlg.charset == "cp1252"
        assert dlg.has_header is False

    def test_preview_renders_readable_text_with_correct_encoding(self):
        csv_text = "obsid;date_time;level\nBjörkån;2024-01-01;3,14\n"
        with file_utils.tempinput(csv_text, "utf-8", suffix=".csv") as filename:
            dlg = self._dialog()
            dlg._filename = filename
            dlg._encoding.setEditText("utf-8")
            dlg._refresh_preview()
            assert "Björkån" in dlg._preview.toPlainText()

    def test_preview_shows_mojibake_with_wrong_encoding(self):
        # File written as utf-8, read as cp1252 -> the å/ä/ö become mojibake.
        csv_text = "obsid\nBjörkån\n"
        with file_utils.tempinput(csv_text, "utf-8", suffix=".csv") as filename:
            dlg = self._dialog()
            dlg._filename = filename
            dlg._encoding.setEditText("cp1252")
            dlg._refresh_preview()
            preview = dlg._preview.toPlainText()
            assert "Björkån" not in preview
            assert "BjÃ" in preview  # mis-decoded utf-8 multibyte sequence
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest test/test_import_general_csv_gui.py::TestCsvFileLoadDialog -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'CsvFileLoadDialog'`.

- [ ] **Step 3: Implement CsvFileLoadDialog**

In `tools/import_general_csv_gui.py`, add this class directly above `class GeneralCsvImportGui`:

```python
class CsvFileLoadDialog(qgis.PyQt.QtWidgets.QDialog):
    """One dialog to choose a file, its encoding (with a live decoded preview),
    and whether the first row is a header. Replaces three sequential popups."""

    PREVIEW_LINES = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(
            QCoreApplication.translate("CsvFileLoadDialog", "Load data from file")
        )
        self._filename = None

        self._path_edit = qgis.PyQt.QtWidgets.QLineEdit()
        self._path_edit.setReadOnly(True)
        browse_button = qgis.PyQt.QtWidgets.QPushButton(
            QCoreApplication.translate("CsvFileLoadDialog", "Browse…")
        )
        browse_button.clicked.connect(lambda x: self._browse())
        file_row = qgis.PyQt.QtWidgets.QHBoxLayout()
        file_row.addWidget(self._path_edit)
        file_row.addWidget(browse_button)

        self._encoding = qgis.PyQt.QtWidgets.QComboBox()
        self._encoding.setEditable(True)
        self._encoding.addItems(COMMON_ENCODINGS)
        self._encoding.setEditText(_last_csv_encoding())
        self._encoding.currentTextChanged.connect(lambda x: self._refresh_preview())

        self._header = qgis.PyQt.QtWidgets.QCheckBox(
            QCoreApplication.translate("CsvFileLoadDialog", "First row is a header")
        )
        self._header.setChecked(True)

        self._preview = qgis.PyQt.QtWidgets.QPlainTextEdit()
        self._preview.setReadOnly(True)

        self._buttons = qgis.PyQt.QtWidgets.QDialogButtonBox(
            qgis.PyQt.QtWidgets.QDialogButtonBox.Ok
            | qgis.PyQt.QtWidgets.QDialogButtonBox.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        self._ok_button().setEnabled(False)

        form = qgis.PyQt.QtWidgets.QFormLayout()
        form.addRow(QCoreApplication.translate("CsvFileLoadDialog", "File:"), file_row)
        form.addRow(
            QCoreApplication.translate("CsvFileLoadDialog", "Encoding:"), self._encoding
        )
        form.addRow(self._header)
        form.addRow(
            QCoreApplication.translate("CsvFileLoadDialog", "Preview:"), self._preview
        )

        layout = qgis.PyQt.QtWidgets.QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(self._buttons)
        self.setLayout(layout)
        self.resize(700, 400)

    def _ok_button(self):
        return self._buttons.button(qgis.PyQt.QtWidgets.QDialogButtonBox.Ok)

    def _browse(self):
        chosen = midvatten_utils.select_files(
            only_one_file=True,
            extension=QCoreApplication.translate(
                "GeneralCsvImportGui",
                "Comma or semicolon separated csv file %s;;Comma or semicolon separated csv text file %s;;Comma or semicolon separated file %s",
            )
            % ("(*.csv)", "(*.txt)", "(*.*)"),
        )
        if isinstance(chosen, (list, tuple)):
            chosen = chosen[0] if chosen else None
        if not chosen:
            return
        self._filename = ru(chosen)
        self._path_edit.setText(self._filename)
        self._ok_button().setEnabled(True)
        self._refresh_preview()

    def _refresh_preview(self):
        if not self._filename:
            return
        enc = self.charset
        try:
            # errors="replace" keeps a wrong charset visible as mojibake instead
            # of raising, so the user can see the problem before importing.
            with open(self._filename, encoding=enc, errors="replace") as f:
                lines = [next(f, "") for _ in range(self.PREVIEW_LINES)]
            self._preview.setPlainText("".join(lines))
        except Exception as e:
            self._preview.setPlainText(
                QCoreApplication.translate(
                    "CsvFileLoadDialog", "Cannot read file with encoding %s: %s"
                )
                % (enc, str(e))
            )

    def accept(self):
        _save_csv_encoding(self.charset)
        super().accept()

    @property
    def filename(self):
        return self._filename

    @property
    def charset(self):
        return ru(self._encoding.currentText()).strip()

    @property
    def has_header(self):
        return self._header.isChecked()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest test/test_import_general_csv_gui.py::TestCsvFileLoadDialog -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add tools/import_general_csv_gui.py test/test_import_general_csv_gui.py
git commit -m "feat: add consolidated CsvFileLoadDialog with live encoding preview"
```

---

## Task 3: Drive load_files() from the new dialog

**Files:**
- Modify: `tools/import_general_csv_gui.py` — `GeneralCsvImportGui.load_files()`
- Test: `test/test_import_general_csv_gui.py` (`_run_w_levels_logger_import`), `test/test_import_general_csv_gui_backends.py`

- [ ] **Step 1: Update the integration test to mock the new dialog**

In `test/test_import_general_csv_gui.py`, replace the popup mocks inside `_run_w_levels_logger_import` with a `CsvFileLoadDialog` mock. Replace the decorator stack + `_run` signature + the encoding/file/header mock setup with the following (the rest of `_run` — building the importer, mapping columns, calling `start_import()` — stays the same):

```python
        with file_utils.tempinput(csv_text, "utf-8", suffix=".csv") as filename:

            @mock.patch("midvatten.tools.utils.dialog_utils.Askuser", mock.MagicMock())
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info", autospec=True
            )
            @mock.patch("midvatten.tools.import_general_csv_gui.CsvFileLoadDialog")
            def _run(self, filename, mock_dialog, mock_popup, mock_iface):
                instance = mock_dialog.return_value
                instance.exec.return_value = qgis.PyQt.QtWidgets.QDialog.Accepted
                instance.filename = filename
                instance.charset = "utf-8"
                instance.has_header = True

                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = GeneralCsvImportGui(self.iface, ms)
                importer.load_gui()
                importer.load_files()
                importer.table_chooser.import_method = "w_levels_logger"
                # ... existing column-mapping + importer.start_import() unchanged ...
```

Keep the existing body below `importer.load_files()` exactly as it is.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest "test/test_import_general_csv_gui.py::TestGeneralCsvImportSpatialite::test_start_import_into_w_levels_logger_routes_source_to_series" -m spatialite -v`
Expected: FAIL — `load_files()` still calls `ask_for_charset()` / `QInputDialog` / header `Askuser`, so the mocked dialog is never used and the flow errors (e.g. `UserInterruptError` or missing file_data).

- [ ] **Step 3: Rewrite load_files()**

In `tools/import_general_csv_gui.py`, replace the entire body of `GeneralCsvImportGui.load_files()` with:

```python
    def load_files(self):
        dlg = CsvFileLoadDialog(self)
        if dlg.exec() != qgis.PyQt.QtWidgets.QDialog.Accepted:
            raise exceptions.UserInterruptError()

        filename = dlg.filename
        charset = dlg.charset
        has_header = dlg.has_header

        delimiter = file_utils.get_delimiter(
            filename=filename, charset=charset, delimiters=[",", ";"]
        )
        self.file_data = self.file_to_list(filename, charset, delimiter)

        if has_header:
            # Remove duplicate header entries
            header = self.file_data[0]
            seen = set()
            seen_add = seen.add
            remove_cols = [
                idx for idx, x in enumerate(header) if x and (x in seen or seen_add(x))
            ]
            self.file_data = [
                [col for idx, col in enumerate(row) if idx not in remove_cols]
                for row in self.file_data
            ]
            self.table_chooser.file_header = self.file_data[0]
        else:
            header = ["Column " + str(colnr) for colnr in range(len(self.file_data[0]))]
            self.table_chooser.file_header = header
            self.file_data.reverse()
            self.file_data.append(header)
            self.file_data.reverse()
```

Note: this removes the `midvatten_utils.ask_for_charset()` call, the `midvatten_utils.select_files()` call, the `dialog_utils.Askuser("Does the file contain a header?")` call, and the surrounding `start_waiting_cursor()`/`stop_waiting_cursor()` toggles (the dialog is modal and `file_to_list` manages its own cursor). `ask_for_charset` stays defined in `midvatten_utils` for the other importers.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest test/test_import_general_csv_gui.py -v`
Expected: PASS (all, including the series-routing integration test).

- [ ] **Step 5: Update and run the backends test**

Inspect `test/test_import_general_csv_gui_backends.py` for any file-load mocking:

Run: `grep -n "ask_for_charset\|getOpenFileName\|QInputDialog\|Does the file contain a header\|load_files" test/test_import_general_csv_gui_backends.py`

For each file-load path found, apply the same `CsvFileLoadDialog` mock substitution as in Step 1 (patch `midvatten.tools.import_general_csv_gui.CsvFileLoadDialog`, set `instance.exec.return_value = qgis.PyQt.QtWidgets.QDialog.Accepted`, `instance.filename`, `instance.charset`, `instance.has_header`). Then:

Run: `python3 -m pytest test/test_import_general_csv_gui_backends.py -m spatialite -v`
Expected: PASS.

- [ ] **Step 6: Lint + commit**

```bash
ruff check --fix tools/import_general_csv_gui.py test/test_import_general_csv_gui.py test/test_import_general_csv_gui_backends.py
ruff format tools/import_general_csv_gui.py test/test_import_general_csv_gui.py test/test_import_general_csv_gui_backends.py
git add tools/import_general_csv_gui.py test/test_import_general_csv_gui.py test/test_import_general_csv_gui_backends.py
git commit -m "feat: load CSV files via one consolidated dialog (no pre/post popups)"
```

---

## Task 4: Start-import modal fires only on row loss

**Files:**
- Modify: `tools/import_data_to_db.py` — `MidvDataImporter._ask_user_to_proceed`
- Test: `test/test_import_data_to_db.py`

- [ ] **Step 1: Write the failing tests**

Add to `test/test_import_data_to_db.py` inside the existing `GeneralImportMixin` class (it provides `self.importinstance` and runs against a spatialite DB; mirror `test_skip_confirmation_suppresses_dialog_with_duplicates`):

```python
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
    def test_no_modal_when_no_rows_dropped(self, mock_askuser, mock_messagebar):
        file = [
            ("obsid", "date_time", "head_cm"),
            ("rb1", "2016-03-15 10:30:00", "1"),
            ("rb1", "2016-03-15 11:00:00", "2"),
        ]
        db_utils.sql_alter_db("""INSERT INTO obs_points (obsid) VALUES ('rb1')""")

        self.importinstance.general_import(
            dest_table="w_levels_logger", file_data=file
        )

        print(f"{mock_askuser.mock_calls=}")
        mock_askuser.assert_not_called()

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
    def test_modal_shown_once_when_rows_dropped(self, mock_askuser, mock_messagebar):
        mock_askuser.return_value.result = 1  # user clicks Yes
        file = [
            ("obsid", "date_time", "head_cm"),
            ("rb1", "2016-03-15 10:30:00", "1"),
            ("rb1", "2016-03-15 11:00:00", "2"),
        ]
        db_utils.sql_alter_db("""INSERT INTO obs_points (obsid) VALUES ('rb1')""")
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, head_cm)"""
            """ VALUES ('rb1', '2016-03-15 11:00:00', 3)"""
        )

        self.importinstance.general_import(
            dest_table="w_levels_logger", file_data=file
        )

        print(f"{mock_askuser.mock_calls=}")
        mock_askuser.assert_called_once()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest "test/test_import_data_to_db.py" -k "no_modal_when_no_rows_dropped" -m spatialite -v`
Expected: FAIL — today the modal is shown on every import, so `assert_not_called()` fails.

- [ ] **Step 3: Rewrite _ask_user_to_proceed**

In `tools/import_data_to_db.py`, replace the body of `_ask_user_to_proceed` with:

```python
    def _ask_user_to_proceed(
        self,
        remaining_rownumbers: Tuple,
        all_rownumbers: Tuple,
        import_messages: List[str],
    ) -> None:
        """Confirm only when rows would actually be dropped (real data loss).

        When nothing is dropped, clicking "Start import" is itself the
        go-ahead — no modal. Accumulated per-cause detail is always logged
        quietly so it is never lost. Raises UserInterruptError if the user
        declines. The ``foreign_keys_import_question`` latch preserves the
        "ask at most once per import session" behaviour for multi-table
        imports and ``skip_confirmation``.
        """
        if import_messages:
            message_utils.MessagebarAndLog.info(log_msg="\n".join(import_messages))

        rows_dropped = len(remaining_rownumbers) != len(all_rownumbers)
        if not rows_dropped:
            return

        if self.foreign_keys_import_question:
            message_utils.MessagebarAndLog.info(
                log_msg=QCoreApplication.translate(
                    "midv_data_importer",
                    "Skipping confirmation dialog: %s out of %s rows to import (duplicates removed).",
                )
                % (str(len(remaining_rownumbers)), str(len(all_rownumbers)))
            )
            return

        msg = QCoreApplication.translate(
            "midv_data_importer",
            "There are %s out of %s number of rows to import (see log for more info about removed rows).\n\nProceed with import?",
        ) % (str(len(remaining_rownumbers)), str(len(all_rownumbers)))

        self.foreign_keys_import_question = 1
        stop_question = dialog_utils.Askuser(
            "YesNo",
            msg,
            QCoreApplication.translate("midv_data_importer", "Info"),
        )
        if stop_question.result == 0:
            raise UserInterruptError()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest "test/test_import_data_to_db.py" -k "no_modal_when_no_rows_dropped or modal_shown_once_when_rows_dropped or skip_confirmation_suppresses" -m spatialite -v`
Expected: PASS (3 passed — including the pre-existing `test_skip_confirmation_suppresses_dialog_with_duplicates`).

- [ ] **Step 5: Commit**

```bash
git add tools/import_data_to_db.py test/test_import_data_to_db.py
git commit -m "feat: confirm import only when rows are dropped, not on every import"
```

---

## Task 5: Foreign-key note becomes a quiet log message

**Files:**
- Modify: `tools/import_data_to_db.py` — `general_import` (drop FK-note seed), `_handle_foreign_keys` (quiet log)
- Test: `test/test_import_data_to_db.py`

- [ ] **Step 1: Write the failing tests**

Add to `test/test_import_data_to_db.py`. The first asserts the FK note no longer appears in any modal; the second asserts a quiet FK log fires when the table has foreign keys. `w_levels_logger` has an `obsid` foreign key to `obs_points`, so importing into it triggers FK handling.

```python
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    @mock.patch("midvatten.tools.utils.dialog_utils.Askuser")
    def test_fk_note_not_in_any_modal(self, mock_askuser, mock_messagebar):
        mock_askuser.return_value.result = 1
        file = [
            ("obsid", "date_time", "head_cm"),
            ("rb1", "2016-03-15 10:30:00", "1"),
            ("rb1", "2016-03-15 11:00:00", "2"),
        ]
        db_utils.sql_alter_db("""INSERT INTO obs_points (obsid) VALUES ('rb1')""")
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, head_cm)"""
            """ VALUES ('rb1', '2016-03-15 11:00:00', 3)"""
        )

        self.importinstance.general_import(
            dest_table="w_levels_logger", file_data=file
        )

        for call in mock_askuser.call_args_list:
            joined = " ".join(str(a) for a in call.args)
            assert "Foreign keys will be imported" not in joined

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    @mock.patch("midvatten.tools.utils.dialog_utils.Askuser", mock.MagicMock())
    def test_fk_import_logs_quiet_note(self, mock_messagebar):
        file = [
            ("obsid", "date_time", "head_cm"),
            ("rb1", "2016-03-15 10:30:00", "1"),
        ]
        db_utils.sql_alter_db("""INSERT INTO obs_points (obsid) VALUES ('rb1')""")

        self.importinstance.general_import(
            dest_table="w_levels_logger", file_data=file
        )

        logged = " ".join(str(c) for c in mock_messagebar.mock_calls)
        assert "imported automatically" in logged
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest "test/test_import_data_to_db.py" -k "fk_note_not_in_any_modal or fk_import_logs_quiet_note" -m spatialite -v`
Expected: FAIL — the FK note is still seeded into the modal, and no "imported automatically" log exists yet.

- [ ] **Step 3: Drop the FK-note seed**

In `tools/import_data_to_db.py`, in `general_import`, replace:

```python
        self.temptable_name = None
        import_messages = [
            QCoreApplication.translate(
                "midv_data_importer",
                """Note:\nForeign keys will be imported silently.""",
            )
        ]
```

with:

```python
        self.temptable_name = None
        import_messages = []
```

- [ ] **Step 4: Add the quiet FK log**

In `tools/import_data_to_db.py`, in `_handle_foreign_keys`, add the log inside the inner `if foreign_keys:` block, right before the `self.import_foreign_keys(...)` call:

```python
            if foreign_keys:
                message_utils.MessagebarAndLog.info(
                    log_msg=QCoreApplication.translate(
                        "midv_data_importer",
                        "Foreign keys for %s were imported automatically.",
                    )
                    % dest_table
                )
                self.import_foreign_keys(
                    dbconnection,
                    dest_table,
                    self.temptable_name,
                    foreign_keys,
                    existing_columns_in_temptable,
                )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest "test/test_import_data_to_db.py" -k "fk_note_not_in_any_modal or fk_import_logs_quiet_note" -m spatialite -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Lint + commit**

```bash
ruff check --fix tools/import_data_to_db.py test/test_import_data_to_db.py
ruff format tools/import_data_to_db.py test/test_import_data_to_db.py
git add tools/import_data_to_db.py test/test_import_data_to_db.py
git commit -m "feat: foreign-key note becomes a quiet log message instead of a modal"
```

---

## Task 6: Verification & cleanup

**Files:** none (verification only)

- [ ] **Step 1: Run all directly-affected test files**

Run: `python3 -m pytest test/test_import_data_to_db.py test/test_import_general_csv_gui.py test/test_import_general_csv_gui_backends.py -m spatialite -v`
Expected: PASS (all). If a pre-existing test asserted the old FK-note modal text or the always-on confirmation, update it to the new behavior (modal only on row loss; FK note in the log). Do NOT change DB-state reference strings — only dialog/log expectations.

- [ ] **Step 2: Run the other importers that share general_import**

Run: `python3 -m pytest test/test_import_fieldlogger.py test/test_import_interlab4.py test/test_import_logger.py -m spatialite -v`
Expected: PASS. These share `general_import`; confirm Part 2 didn't regress them (especially `skip_confirmation` in the logger importer).

- [ ] **Step 3: midv_addons API compatibility**

`GeneralCsvImportGui.__init__` signature is unchanged, but verify the public-API contract. From the midv_addons repo, run its `test_midvatten_compat.py` (per the midv_addons API-contract note). If unavailable in this environment, log that it was skipped.

- [ ] **Step 4: Apply the simplify skill**

Per `CLAUDE.md`, invoke the `simplify` skill on the changed code (`tools/import_general_csv_gui.py`, `tools/import_data_to_db.py`) to review for reuse/altitude cleanups, then re-run the Task 6 Step 1 tests.

- [ ] **Step 5: Final lint**

Run: `ruff check . && ruff format --check .`
Expected: clean (or only pre-existing unrelated findings).

- [ ] **Step 6: Manual smoke (optional, recommended)**

In QGIS: open the CSV importer, click "Load data from file" → confirm one dialog with file/encoding/header/preview; pick a file, flip encoding, watch the preview re-render; OK; map columns; "Start import" → confirm no popup when nothing is dropped, and the "X of Y … Proceed?" modal only when re-importing rows that already exist. Check the Log Messages panel for the quiet "Foreign keys … imported automatically" note.

---

## Self-Review notes (for the implementer)

- **Spec coverage:** Part 1 → Tasks 1–3 (helpers, dialog with preview, `load_files`); Part 2 → Tasks 4–5 (modal-only-on-row-loss, quiet FK log); guardrails/tests → Task 6. All spec sections map to a task.
- **Type/name consistency:** `CsvFileLoadDialog`, `_last_csv_encoding`, `_save_csv_encoding`, `CSV_ENCODING_SETTING`, `COMMON_ENCODINGS`, and the `.filename` / `.charset` / `.has_header` properties are used identically across tasks and tests.
- **No reference-data changes:** DB end-state is unchanged; only dialog/log expectations move.
