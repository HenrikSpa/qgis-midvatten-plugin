> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-04-17 · modified: 2026-04-17 · archived: 2026-07-31

# Interlab4 s_qual_lab Destination Table Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a radio-button toggle to the interlab4 import dialog so users can direct imports to either `w_qual_lab` (water, default) or `s_qual_lab` (soil), with on-demand table creation when `s_qual_lab` doesn't exist.

**Architecture:** A `QGroupBox` with two `QRadioButton`s is added to the existing button panel. A `dest_table` property reads the radio state and is used everywhere the table name was hardcoded. `_on_dest_table_changed()` checks for table existence and offers creation by extracting the `CREATE TABLE s_qual_lab` block from `create_db.sql` at runtime. As a prerequisite, `s_qual_lab` is promoted to a standard schema table (removed from the extra-tables file and optional-tables list).

**Tech Stack:** Python 3, PyQt5 (via `qgis.PyQt`), SpatiaLite/SQLite, pytest, `mock.patch`

---

## Files Modified

| File | Change |
|---|---|
| `definitions/create_db.sql` | Update `s_qual_lab` comment |
| `definitions/create_db_extra_data_tables.sql` | Remove `s_qual_lab` block |
| `definitions/midvatten_defs.py` | Remove `"s_qual_lab"` from `extra_data_tables` list |
| `tools/import_interlab4.py` | All new logic: UI, property, creation flow, data flow |
| `test/test_import_interlab4.py` | New tests: extract helper, default table, creation flow, skip query |

---

## Task 1: Schema clean-up — promote s_qual_lab to standard table

**Files:**
- Modify: `definitions/create_db.sql:265`
- Modify: `definitions/create_db_extra_data_tables.sql:3-18`
- Modify: `definitions/midvatten_defs.py:435-437`

- [ ] **Step 1: Update s_qual_lab comment in create_db.sql**

  In `definitions/create_db.sql` line 265, change:
  ```sql
  CREATE TABLE s_qual_lab /*Soil quality data*/(
  ```
  to:
  ```sql
  CREATE TABLE s_qual_lab /*Soil sample analyses*/(
  ```

- [ ] **Step 2: Remove s_qual_lab from create_db_extra_data_tables.sql**

  In `definitions/create_db_extra_data_tables.sql`, remove lines 3–18:
  ```sql
  CREATE TABLE s_qual_lab /*Soil quality data*/(
  obsid text not null
  , depth double
  , report text not null
  , project text
  , staff text
  , date_time text
  , anameth text
  , parameter text not null
  , reading_num double
  , reading_txt text
  , unit text
  , comment text
  , primary key(report, parameter)
  , foreign key(obsid) references obs_points(obsid) ON UPDATE CASCADE ON DELETE CASCADE
  );
  ```

  Leave the file header comment and whatever follows s_qual_lab intact.

- [ ] **Step 3: Remove s_qual_lab from midvatten_defs.py extra_data_tables**

  In `definitions/midvatten_defs.py`, the `elif category == "extra_data_tables":` block (around line 435) currently returns:
  ```python
  return ["s_qual_lab", "w_qual_logger", "spatial_history"]
  ```
  Change to:
  ```python
  return ["w_qual_logger", "spatial_history"]
  ```

- [ ] **Step 4: Run full test suite to confirm no regressions**

  ```bash
  cd /home/hsai1/dev/midv/midvatten
  python3 -m pytest test/ -x -m "not postgis" -q
  ```
  Expected: all spatialite tests pass, 0 failures.

- [ ] **Step 5: Commit**

  ```bash
  git add definitions/create_db.sql definitions/create_db_extra_data_tables.sql definitions/midvatten_defs.py
  git commit -F - <<'EOF'
  refactor: promote s_qual_lab to standard schema table

  Remove from create_db_extra_data_tables.sql and midvatten_defs extra_data_tables
  list. Update comment to "Soil sample analyses" for consistency.

  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
  EOF
  ```

---

## Task 2: `_extract_create_table` static helper

**Files:**
- Modify: `tools/import_interlab4.py`
- Modify: `test/test_import_interlab4.py`

This pure static method has no QGIS dependencies and can be tested in isolation.

- [ ] **Step 1: Write the failing test**

  In `test/test_import_interlab4.py`, after the existing imports, add a new test class (no DB required):

  ```python
  class TestExtractCreateTable:
      def test_extracts_block(self):
          sql = (
              "CREATE TABLE foo (id text);\n"
              "CREATE TABLE s_qual_lab /*comment*/(\n"
              "obsid text not null\n"
              ", primary key(report, parameter)\n"
              ");\n"
              "CREATE TABLE bar (x text);\n"
          )
          result = Interlab4Import._extract_create_table(sql, "s_qual_lab")
          assert "CREATE TABLE s_qual_lab" in result
          assert "primary key(report, parameter)" in result
          assert "CREATE TABLE bar" not in result
          assert "CREATE TABLE foo" not in result

      def test_raises_if_not_found(self):
          with pytest.raises(ValueError, match="CREATE TABLE missing"):
              Interlab4Import._extract_create_table("CREATE TABLE foo (id text);", "missing")
  ```

- [ ] **Step 2: Run to verify it fails**

  ```bash
  python3 -m pytest test/test_import_interlab4.py::TestExtractCreateTable -v
  ```
  Expected: FAIL — `AttributeError: type object 'Interlab4Import' has no attribute '_extract_create_table'`

- [ ] **Step 3: Implement `_extract_create_table` in import_interlab4.py**

  Add this static method to the `Interlab4Import` class (after `compare_duplicate_parameters`, before `MetaFilterSelection`):

  ```python
  @staticmethod
  def _extract_create_table(sql_text: str, table_name: str) -> str:
      """Extract a single CREATE TABLE block from sql_text by table name."""
      lines = sql_text.splitlines()
      result = []
      inside = False
      prefix = f"CREATE TABLE {table_name.upper()}"
      for line in lines:
          if not inside and line.strip().upper().startswith(prefix):
              inside = True
          if inside:
              result.append(line)
              if line.strip() == ");":
                  break
      if not result:
          raise ValueError(f"CREATE TABLE {table_name} not found in SQL text")
      return "\n".join(result)
  ```

- [ ] **Step 4: Run to verify it passes**

  ```bash
  python3 -m pytest test/test_import_interlab4.py::TestExtractCreateTable -v
  ```
  Expected: 2 tests PASS.

- [ ] **Step 5: Ruff**

  ```bash
  ruff check --fix tools/import_interlab4.py && ruff format tools/import_interlab4.py
  ```

- [ ] **Step 6: Commit**

  ```bash
  git add tools/import_interlab4.py test/test_import_interlab4.py
  git commit -F - <<'EOF'
  feat: add _extract_create_table static helper to Interlab4Import

  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
  EOF
  ```

---

## Task 3: `dest_table` property and radio button GroupBox

**Files:**
- Modify: `tools/import_interlab4.py`
- Modify: `test/test_import_interlab4.py`

- [ ] **Step 1: Write the failing test**

  In `test/test_import_interlab4.py`, add to the existing `TestInterlab4Importer` class:

  ```python
  def test_dest_table_defaults_to_w_qual_lab(self):
      assert self.importinstance.dest_table == "w_qual_lab"

  def test_dest_table_returns_s_qual_lab_when_selected(self):
      self.importinstance.radio_s_qual_lab.setChecked(True)
      assert self.importinstance.dest_table == "s_qual_lab"
  ```

  Note: `TestInterlab4Importer` extends `MidvattenTestSpatialiteNotCreated`, which does NOT create a DB. These tests only check widget state, not DB presence.

- [ ] **Step 2: Run to verify they fail**

  ```bash
  python3 -m pytest test/test_import_interlab4.py::TestInterlab4Importer::test_dest_table_defaults_to_w_qual_lab -v
  ```
  Expected: FAIL — `AttributeError: 'Interlab4Import' object has no attribute 'dest_table'`

- [ ] **Step 3: Add the UI GroupBox and `dest_table` property**

  In `tools/import_interlab4.py`, make these changes:

  **3a. Update the window title in `__init__`** (line ~64):
  ```python
  # Before:
  self.setWindowTitle(
      QCoreApplication.translate(
          "Interlab4Import", "Import interlab4 data to w_qual_lab table"
      )
  )
  # After:
  self.setWindowTitle(
      QCoreApplication.translate(
          "Interlab4Import", "Import interlab4 data"
      )
  )
  ```

  **3b. Add `dest_table` property** (add after `__init__`, before `show`):
  ```python
  @property
  def dest_table(self) -> str:
      return "s_qual_lab" if self.radio_s_qual_lab.isChecked() else "w_qual_lab"
  ```

  **3c. Build the destination table GroupBox in `init_gui`**

  At the **top** of `init_gui`, before the splitter is built, add:

  ```python
  dest_table_group = qgis.PyQt.QtWidgets.QGroupBox(
      QCoreApplication.translate("Interlab4Import", "Destination table")
  )
  dest_table_group.setLayout(qgis.PyQt.QtWidgets.QVBoxLayout())

  self.radio_w_qual_lab = qgis.PyQt.QtWidgets.QRadioButton("w_qual_lab")
  self.radio_w_qual_lab.setChecked(True)
  self.radio_w_qual_lab.setToolTip(
      QCoreApplication.translate("Interlab4Import", "Water sample analyses")
  )

  self.radio_s_qual_lab = qgis.PyQt.QtWidgets.QRadioButton("s_qual_lab")
  self.radio_s_qual_lab.setChecked(False)
  self.radio_s_qual_lab.setToolTip(
      QCoreApplication.translate("Interlab4Import", "Soil sample analyses")
  )
  self.radio_s_qual_lab.toggled.connect(self._on_dest_table_changed)

  dest_table_group.layout().addWidget(self.radio_w_qual_lab)
  dest_table_group.layout().addWidget(self.radio_s_qual_lab)
  ```

  **3d. Insert the GroupBox at row 0** in the existing grid additions block.

  Currently, the button grid starts at (find the block near line 181):
  ```python
  self.grid_layout_buttons.addWidget(self.skip_imported_reports, 0, 0)
  self.grid_layout_buttons.addWidget(self.select_files_button, 1, 0)
  self.grid_layout_buttons.addWidget(get_line(), 2, 0)
  self.grid_layout_buttons.addWidget(self.close_after_import, 3, 0)
  self.grid_layout_buttons.addWidget(self.dump_2_temptable, 4, 0)
  self.grid_layout_buttons.addWidget(self.use_obsid_assignment_table, 5, 0)
  self.grid_layout_buttons.addWidget(self.start_import_button, 6, 0)
  self.grid_layout_buttons.addWidget(self.help_label, 7, 0)
  self.grid_layout_buttons.setRowStretch(8, 1)
  ```

  Replace with (all rows shifted +1, new GroupBox at row 0):
  ```python
  self.grid_layout_buttons.addWidget(dest_table_group, 0, 0)
  self.grid_layout_buttons.addWidget(self.skip_imported_reports, 1, 0)
  self.grid_layout_buttons.addWidget(self.select_files_button, 2, 0)
  self.grid_layout_buttons.addWidget(get_line(), 3, 0)
  self.grid_layout_buttons.addWidget(self.close_after_import, 4, 0)
  self.grid_layout_buttons.addWidget(self.dump_2_temptable, 5, 0)
  self.grid_layout_buttons.addWidget(self.use_obsid_assignment_table, 6, 0)
  self.grid_layout_buttons.addWidget(self.start_import_button, 7, 0)
  self.grid_layout_buttons.addWidget(self.help_label, 8, 0)
  self.grid_layout_buttons.setRowStretch(9, 1)
  ```

  **3e. Add a stub `_on_dest_table_changed`** (so the signal connection doesn't break; real implementation is Task 4):
  ```python
  def _on_dest_table_changed(self, checked: bool = True) -> None:
      pass
  ```

- [ ] **Step 4: Run to verify tests pass**

  ```bash
  python3 -m pytest test/test_import_interlab4.py::TestInterlab4Importer::test_dest_table_defaults_to_w_qual_lab test/test_import_interlab4.py::TestInterlab4Importer::test_dest_table_returns_s_qual_lab_when_selected -v
  ```
  Expected: 2 tests PASS.

- [ ] **Step 5: Ruff**

  ```bash
  ruff check --fix tools/import_interlab4.py && ruff format tools/import_interlab4.py
  ```

- [ ] **Step 6: Commit**

  ```bash
  git add tools/import_interlab4.py test/test_import_interlab4.py
  git commit -F - <<'EOF'
  feat: add destination table radio buttons to interlab4 import dialog

  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
  EOF
  ```

---

## Task 4: `_on_dest_table_changed` — on-demand s_qual_lab creation

**Files:**
- Modify: `tools/import_interlab4.py`
- Modify: `test/test_import_interlab4_backends.py`

Tests that touch the DB go in the backends file which uses `MidvattenTestSpatialiteDbSv` (full created database). We DROP `s_qual_lab` at the start of each test to simulate a missing table.

- [ ] **Step 1: Write the failing tests**

  Add these two tests to `Interlab4ImporterDBMixin` in `test/test_import_interlab4_backends.py`:

  ```python
  @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
  @mock.patch(
      "qgis.PyQt.QtWidgets.QMessageBox.question",
      return_value=qgis.PyQt.QtWidgets.QMessageBox.Yes,
  )
  def test_s_qual_lab_created_on_demand(self, mock_question, mock_messagebar):
      print(mock_messagebar.mock_calls)
      db_utils.sql_alter_db("DROP TABLE IF EXISTS s_qual_lab")
      assert "s_qual_lab" not in db_utils.tables_columns()
      self.importinstance.radio_s_qual_lab.setChecked(True)
      self.importinstance._on_dest_table_changed(checked=True)
      assert "s_qual_lab" in db_utils.tables_columns()
      assert self.importinstance.dest_table == "s_qual_lab"

  @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
  @mock.patch(
      "qgis.PyQt.QtWidgets.QMessageBox.question",
      return_value=qgis.PyQt.QtWidgets.QMessageBox.No,
  )
  def test_s_qual_lab_reverts_when_creation_declined(self, mock_question, mock_messagebar):
      print(mock_messagebar.mock_calls)
      db_utils.sql_alter_db("DROP TABLE IF EXISTS s_qual_lab")
      self.importinstance.radio_s_qual_lab.setChecked(True)
      self.importinstance._on_dest_table_changed(checked=True)
      assert "s_qual_lab" not in db_utils.tables_columns()
      assert self.importinstance.dest_table == "w_qual_lab"
  ```

- [ ] **Step 2: Run to verify they fail**

  ```bash
  python3 -m pytest test/test_import_interlab4_backends.py::TestInterlab4ImporterDBSpatialite::test_s_qual_lab_created_on_demand -v
  ```
  Expected: FAIL — `_on_dest_table_changed` does nothing (stub from Task 3).

- [ ] **Step 3: Add get_full_filename import to import_interlab4.py**

  In `tools/import_interlab4.py`, add one import at module level (after the existing imports):
  ```python
  from midvatten.tools.utils.file_utils import get_full_filename
  ```

- [ ] **Step 4: Implement `_on_dest_table_changed` and `_create_s_qual_lab`**

  Replace the stub `_on_dest_table_changed` with:

  ```python
  def _on_dest_table_changed(self, checked: bool = True) -> None:
      if not self.radio_s_qual_lab.isChecked():
          return
      if "s_qual_lab" in tables_columns():
          return
      answer = qgis.PyQt.QtWidgets.QMessageBox.question(
          self,
          QCoreApplication.translate("Interlab4Import", "Create table"),
          QCoreApplication.translate(
              "Interlab4Import",
              "Table s_qual_lab does not exist. Create it now?",
          ),
      )
      if answer == qgis.PyQt.QtWidgets.QMessageBox.Yes:
          self._create_s_qual_lab()
      else:
          self.radio_w_qual_lab.setChecked(True)

  def _create_s_qual_lab(self) -> None:
      sql_path = get_full_filename("create_db.sql")
      with open(sql_path, encoding="utf-8") as f:
          sql_text = f.read()
      ddl = self._extract_create_table(sql_text, "s_qual_lab")
      dbconnection = db_utils.DbConnectionManager()
      try:
          dbconnection.execute(ddl)
          dbconnection.commit()
      finally:
          dbconnection.closedb()
  ```

- [ ] **Step 5: Run to verify tests pass**

  ```bash
  python3 -m pytest test/test_import_interlab4_backends.py::TestInterlab4ImporterDBSpatialite::test_s_qual_lab_created_on_demand test/test_import_interlab4_backends.py::TestInterlab4ImporterDBSpatialite::test_s_qual_lab_reverts_when_creation_declined -v
  ```
  Expected: 2 tests PASS.

- [ ] **Step 6: Ruff**

  ```bash
  ruff check --fix tools/import_interlab4.py && ruff format tools/import_interlab4.py
  ```

- [ ] **Step 7: Commit**

  ```bash
  git add tools/import_interlab4.py test/test_import_interlab4_backends.py
  git commit -F - <<'EOF'
  feat: create s_qual_lab on demand when selected in interlab4 import dialog

  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
  EOF
  ```

---

## Task 5: Data flow fixes — skip query and start_import

**Files:**
- Modify: `tools/import_interlab4.py`
- Modify: `test/test_import_interlab4.py`

- [ ] **Step 1: Write the failing test**

  Add to `TestInterlab4Importer` in `test/test_import_interlab4.py`:

  ```python
  @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
  @mock.patch(
      "midvatten.tools.import_interlab4.midvatten_utils.select_files",
      return_value=[],
  )
  @mock.patch(
      "midvatten.tools.import_interlab4.sql_load_fr_db",
      return_value=(True, []),
  )
  def test_skip_reports_queries_dest_table(
      self, mock_sql_load, mock_select_files, mock_messagebar
  ):
      print(mock_messagebar.mock_calls)
      self.importinstance.skip_imported_reports.setChecked(True)
      self.importinstance.radio_s_qual_lab.setChecked(True)
      self.importinstance.load_files()
      call_sql = mock_sql_load.call_args[0][0]
      assert '"s_qual_lab"' in call_sql
      assert '"w_qual_lab"' not in call_sql
  ```

- [ ] **Step 2: Run to verify it fails**

  ```bash
  python3 -m pytest test/test_import_interlab4.py::TestInterlab4Importer::test_skip_reports_queries_dest_table -v
  ```
  Expected: FAIL — the skip query still uses hardcoded `w_qual_lab`.

- [ ] **Step 3: Add `ident` import**

  In `tools/import_interlab4.py`, extend the existing `from midvatten.tools.utils.db_utils import sql_load_fr_db, tables_columns` line to also import `ident`:

  ```python
  from midvatten.tools.utils.db_utils import sql_load_fr_db, tables_columns
  from midvatten.tools.utils.db_utils.dialect import ident
  ```

- [ ] **Step 4: Fix `load_files()` skip query**

  In `load_files()`, replace (around line 206):
  ```python
  skip_reports = [
      str(x[0])
      for x in sql_load_fr_db("""SELECT DISTINCT report FROM w_qual_lab;""")[1]
  ]
  ```
  with:
  ```python
  tbl = ident(self.dest_table, allowed=["w_qual_lab", "s_qual_lab"])
  skip_reports = [
      str(x[0])
      for x in sql_load_fr_db(f"SELECT DISTINCT report FROM {tbl};")[1]
  ]
  ```

- [ ] **Step 5: Fix `start_import()` dest_table argument**

  In `start_import()`, replace (around line 325):
  ```python
  answer = importer.general_import(
      dest_table="w_qual_lab",
      file_data=self.wquallab_data_table,
      dump_temptable=self.dump_2_temptable.isChecked(),
  )
  ```
  with:
  ```python
  answer = importer.general_import(
      dest_table=self.dest_table,
      file_data=self.wquallab_data_table,
      dump_temptable=self.dump_2_temptable.isChecked(),
  )
  ```

- [ ] **Step 6: Run skip test to verify it passes**

  ```bash
  python3 -m pytest test/test_import_interlab4.py::TestInterlab4Importer::test_skip_reports_queries_dest_table -v
  ```
  Expected: PASS.

- [ ] **Step 7: Run full interlab4 test suite**

  ```bash
  python3 -m pytest test/test_import_interlab4.py test/test_import_interlab4_backends.py -v -m "not postgis"
  ```
  Expected: all tests PASS, 0 failures.

- [ ] **Step 8: Run full test suite**

  ```bash
  python3 -m pytest test/ -x -m "not postgis" -q
  ```
  Expected: all spatialite tests pass, 0 failures.

- [ ] **Step 9: Ruff**

  ```bash
  ruff check --fix tools/import_interlab4.py && ruff format tools/import_interlab4.py
  ```

- [ ] **Step 10: Commit**

  ```bash
  git add tools/import_interlab4.py test/test_import_interlab4.py
  git commit -F - <<'EOF'
  feat: wire dest_table into skip-reports query and general_import call

  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
  EOF
  ```
