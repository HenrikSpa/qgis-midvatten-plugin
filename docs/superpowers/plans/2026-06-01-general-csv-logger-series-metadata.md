# General CSV import — logger-series metadata section: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users populate `w_logger_series` metadata (source, instrument, description, comment) while importing to `w_levels_logger` through the general CSV GUI, via a dedicated mapping block at the bottom of the column chooser.

**Architecture:** Add a separate `series_columns` list of reused `ColumnEntry` widgets rendered under a separator in the same chooser grid. At import, series mappings merge into the existing `translation_dict` under namespaced carrier targets (`__series_<field>`) so the existing StaticValue/reorder/filter pipeline carries them through row-aligned. A generalized `_route_series_metadata()` then groups rows by `(obsid, source, instrument, description, comment)`, creates one `w_logger_series` row per distinct tuple capturing each id at INSERT time, stamps `series_id` onto each logger row, and strips the carriers before `general_import()`.

**Tech Stack:** Python 3, PyQt/QGIS, pytest (spatialite + postgis markers), SpatiaLite/PostgreSQL via the `db_utils` backend abstraction.

**Spec:** `docs/superpowers/specs/2026-06-01-general-csv-logger-series-metadata-design.md`

---

## File Structure

- **Modify** `tools/import_general_csv_gui.py`
  - `GeneralCsvImportGui.load_gui()` — remove the virtual-`source` injection block.
  - `ImportTableChooser.__init__` / `choose_method` — add `self.series_columns`, render the series block when gated.
  - `ImportTableChooser.get_series_translation()` — new accessor (translation_dict-shaped, carrier targets).
  - `GeneralCsvImportGui.start_import()` — merge series translation into `translation_dict`.
  - `GeneralCsvImportGui._route_source_to_logger_series` → renamed/generalized `_route_series_metadata`.
- **Modify** `test/test_import_general_csv_gui_backends.py`
  - Adapt `test_import_w_levels_logger_with_source_routes_to_series` to map `source` via the series block.
  - Add new backend tests (static metadata, mixed, comment collision, no-mapping NULL, old-schema fallback).
- **Modify** `test/test_import_general_csv_gui.py`
  - Add a lighter GUI test that the series block builds for `w_levels_logger` and not for other tables.

The series block reuses `ColumnEntry` unchanged — no new widget class.

---

## Task 1: Render the logger-series block in the chooser grid

Additive GUI change. Routing and the virtual-source path are untouched in this task, so the full suite stays green.

**Files:**
- Modify: `tools/import_general_csv_gui.py` (`ImportTableChooser.__init__`, `choose_method`, new `get_series_translation`)
- Test: `test/test_import_general_csv_gui.py`

- [ ] **Step 1: Write the failing test**

Add to `test/test_import_general_csv_gui.py`. Check the existing imports at the top of that file; it already imports `mock`, `MagicMock`, `OrderedDict`, and `GeneralCsvImportGui` (mirror whatever the neighbouring tests use — do not add duplicate imports).

```python
def test_series_block_built_for_w_levels_logger(self):
    """Choosing w_levels_logger on the new schema builds a series block with
    one ColumnEntry per editable w_logger_series field; choosing another
    table builds none."""
    db_utils.sql_alter_db("""INSERT INTO obs_points (obsid) VALUES ('rb1')""")

    ms = MagicMock()
    ms.settingsdict = OrderedDict()
    gui = GeneralCsvImportGui(self.iface, ms)
    gui.load_gui()
    # A non-None file_header is required for choose_method to build the grid.
    gui.table_chooser.file_header = ["obsid", "date_time", "head_cm", "source"]

    gui.table_chooser.import_method = "w_levels_logger"
    series_fields = sorted(c.db_column for c in gui.table_chooser.series_columns)
    assert series_fields == ["comment", "description", "instrument", "source"]

    gui.table_chooser.import_method = "obs_points"
    assert gui.table_chooser.series_columns == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest test/test_import_general_csv_gui.py -k series_block_built -x`
Expected: FAIL — `AttributeError: 'ImportTableChooser' object has no attribute 'series_columns'`.

- [ ] **Step 3: Initialize `series_columns` in `ImportTableChooser.__init__`**

In `ImportTableChooser.__init__`, next to `self.columns = []` (around line 670), add:

```python
        self.columns = []
        self.series_columns = []
```

- [ ] **Step 4: Reset and populate `series_columns` in `choose_method`**

In `choose_method`, find `self.columns = []` (around line 768) and add a reset beside it:

```python
        self.columns = []
        self.series_columns = []
```

Then, after the existing `for index, tables_columns_info in enumerate(...)` loop that appends `ColumnEntry`s for the chosen table (the loop ending around line 823, right before `self.grid.layout().setColumnStretch(5, 5)`), insert the series block:

```python
        self._append_series_block(import_method_name, file_header)
```

And add this new method to `ImportTableChooser`:

```python
    def _append_series_block(self, import_method_name, file_header):
        """For w_levels_logger on the new schema, render a separated block of
        ColumnEntry rows mapping the editable w_logger_series fields."""
        if import_method_name != "w_levels_logger":
            return
        series_info = self.tables_columns.get("w_logger_series")
        wll_info = self.tables_columns.get("w_levels_logger", [])
        has_series_id = any(col[1] == "series_id" for col in wll_info)
        if not series_info or not has_series_id:
            return

        rownr = self.grid.layout().rowCount()
        self.grid.layout().addWidget(get_line(), rownr, 0, 1, 5)
        rownr = self.grid.layout().rowCount()
        self.grid.layout().addWidget(
            qgis.PyQt.QtWidgets.QLabel(
                QCoreApplication.translate(
                    "ImportTableChooser",
                    "Logger series metadata (w_logger_series)",
                )
            ),
            rownr,
            0,
            1,
            5,
        )

        info_by_name = {col[1]: col for col in series_info}
        for field in ("source", "instrument", "description", "comment"):
            col_info = info_by_name.get(field)
            if col_info is None:
                continue
            column = ColumnEntry(col_info, file_header, self.numeric_datatypes)
            rownr = self.grid.layout().rowCount()
            for colnr, wid in enumerate(column.column_widgets):
                self.grid.layout().addWidget(wid, rownr, colnr)
            self.series_columns.append(column)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest test/test_import_general_csv_gui.py -k series_block_built -x`
Expected: PASS.

- [ ] **Step 6: Add the `get_series_translation` accessor**

Add to `ImportTableChooser`, next to `get_translation_dict`:

```python
    def get_series_translation(self):
        """translation_dict-shaped mapping for series fields, but every target
        is the namespaced carrier ``__series_<field>`` so it can never collide
        with a real column (notably ``comment``, which exists in both tables)."""
        series_translation = {}
        for column_entry in self.series_columns:
            file_column_name = column_entry.file_column_name
            if file_column_name:
                carrier = "__series_" + column_entry.db_column
                existing = series_translation.get(file_column_name, [])
                series_translation[file_column_name] = existing + [carrier]
        return series_translation
```

- [ ] **Step 7: Run the GUI test file**

Run: `python3 -m pytest test/test_import_general_csv_gui.py -x`
Expected: PASS (existing tests unaffected; new one green).

- [ ] **Step 8: Lint and commit**

```bash
ruff check --fix tools/import_general_csv_gui.py test/test_import_general_csv_gui.py
ruff format tools/import_general_csv_gui.py test/test_import_general_csv_gui.py
git add tools/import_general_csv_gui.py test/test_import_general_csv_gui.py
git commit -m "feat: render logger-series metadata block in general CSV chooser"
```

---

## Task 2: Carrier merge + generalized routing, remove virtual source

This is the behavioral core. It (a) removes the virtual-`source` injection, (b) merges series mappings into `translation_dict` under carrier names, (c) generalizes routing to read carriers with two-pass id-capture, and (d) adapts the existing backward-compat test to drive `source` through the series block.

**Files:**
- Modify: `tools/import_general_csv_gui.py` (`load_gui`, `start_import`, rename `_route_source_to_logger_series` → `_route_series_metadata`)
- Test: `test/test_import_general_csv_gui_backends.py` (adapt existing test)

- [ ] **Step 1: Adapt the existing backward-compat test to use the series block**

In `test/test_import_general_csv_gui_backends.py`, in `test_import_w_levels_logger_with_source_routes_to_series`, replace the column-mapping loop (around lines 1523-1531) with logger-column mapping plus an explicit series-block mapping for `source`:

```python
                for column in importer.table_chooser.columns:
                    names = {
                        "obsid": "obsid",
                        "date_time": "date_time",
                        "head_cm": "head_cm",
                    }
                    if column.db_column in names:
                        column.file_column_name = names[column.db_column]

                for column in importer.table_chooser.series_columns:
                    if column.db_column == "source":
                        column.file_column_name = "source"
                    else:
                        column.file_column_name = None
```

Leave every assertion in that test exactly as-is — the resulting DB state is identical, so they are the backward-compat proof. (This is an allowed UI-setup adaptation, not a reference-data change.)

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest test/test_import_general_csv_gui_backends.py -k with_source_routes_to_series -x`
Expected: FAIL — series block not yet wired into `start_import` (source carrier never created → no `w_logger_series` rows / NULL `series_id`), and/or virtual `source` still present causes a stale path. Confirm it fails before implementing.

- [ ] **Step 3: Remove the virtual-`source` injection from `load_gui`**

In `GeneralCsvImportGui.load_gui()`, delete the block that injects the virtual `source` column (the lines from the `# On the new schema, source has moved...` comment through `self.tables_columns_info["w_levels_logger"] = wll_cols`, around lines 77-89). The result is:

```python
        self.tables_columns_info = {
            k: v
            for (k, v) in db_utils.db_tables_columns_info(
                dbconnection=self.dbconnection
            ).items()
            if not k.endswith("_geom")
        }
        self.table_chooser = ImportTableChooser(
            self.tables_columns_info,
            file_header=None,
            embed_chooser_in_layout=False,
        )
```

- [ ] **Step 4: Merge series translation into `translation_dict` in `start_import`**

In `start_import`, immediately after `translation_dict = self.table_chooser.get_translation_dict()` (around line 322), add:

```python
        translation_dict = self.table_chooser.get_translation_dict()

        dest_table = self.table_chooser.import_method
        if dest_table == "w_levels_logger":
            for file_column, carriers in (
                self.table_chooser.get_series_translation().items()
            ):
                translation_dict[file_column] = (
                    translation_dict.get(file_column, []) + carriers
                )
```

Then delete the now-duplicate `dest_table = self.table_chooser.import_method` line that previously sat a few lines below (around line 326) so `dest_table` is assigned once.

- [ ] **Step 5: Replace `_route_source_to_logger_series` with `_route_series_metadata`**

Rename the method and rewrite its body. Delete the entire existing `_route_source_to_logger_series` method (lines ~420-533) and the call site `file_data = self._route_source_to_logger_series(file_data)` (line ~406), replacing the call with:

```python
        if dest_table == "w_levels_logger":
            file_data = self._route_series_metadata(file_data)
```

New method:

```python
    SERIES_FIELDS = ("source", "instrument", "description", "comment")

    def _route_series_metadata(
        self, file_data: List[List[Any]]
    ) -> List[List[Any]]:
        """Turn ``__series_*`` carrier columns into ``w_logger_series`` rows and
        a ``series_id`` column on each w_levels_logger row.

        One series row is created per distinct
        ``(obsid, source, instrument, description, comment)`` tuple. Ids are
        captured at INSERT time (never re-queried), so two batches that reuse the
        same metadata still get distinct series. Always creates new series rows;
        never matches existing ones.
        """
        if not file_data or len(file_data) < 2:
            return file_data

        header = list(file_data[0])
        rows = [list(r) for r in file_data[1:]]

        carrier_cols = [c for c in header if c.startswith("__series_")]
        if not carrier_cols:
            return [header] + rows

        # Drop any stray CSV series_id: cross-database ids do not translate.
        if "series_id" in header:
            idx = header.index("series_id")
            header.pop(idx)
            for row in rows:
                if idx < len(row):
                    row.pop(idx)
            common_utils.MessagebarAndLog.warning(
                log_msg=QCoreApplication.translate(
                    "GeneralCsvImportGui",
                    "Ignoring 'series_id' column from CSV on import to"
                    " w_levels_logger: cross-database ids do not translate."
                    " Use the logger series metadata fields to group rows into"
                    " new series instead.",
                )
            )

        def _strip_carriers(hdr, data_rows):
            keep = [i for i, c in enumerate(hdr) if c not in carrier_cols]
            new_hdr = [hdr[i] for i in keep]
            new_data = [
                [r[i] if i < len(r) else None for i in keep] for r in data_rows
            ]
            return [new_hdr] + new_data

        existing_tables = db_utils.tables_columns(dbconnection=self.dbconnection)
        if "w_logger_series" not in existing_tables:
            return _strip_carriers(header, rows)
        if "series_id" not in existing_tables.get("w_levels_logger", []):
            return _strip_carriers(header, rows)
        if "obsid" not in header:
            common_utils.MessagebarAndLog.warning(
                log_msg=QCoreApplication.translate(
                    "GeneralCsvImportGui",
                    "Logger series metadata supplied but no 'obsid' column;"
                    " cannot create w_logger_series rows. Series metadata will"
                    " be dropped.",
                )
            )
            return _strip_carriers(header, rows)

        present_fields = [
            f for f in self.SERIES_FIELDS if ("__series_" + f) in header
        ]
        obsid_idx = header.index("obsid")
        field_idx = {f: header.index("__series_" + f) for f in present_fields}

        def _norm(value):
            return value if value not in ("", None) else None

        def _key(row):
            obsid = row[obsid_idx] if obsid_idx < len(row) else None
            vals = tuple(
                _norm(row[field_idx[f]]) if field_idx[f] < len(row) else None
                for f in present_fields
            )
            return obsid, vals

        dbconn = (
            self.dbconnection
            if self.dbconnection is not None
            else db_utils.DbConnectionManager()
        )
        close_dbconn = self.dbconnection is None
        colnames = ", ".join(["obsid"] + present_fields)
        try:
            ph = dbconn.placeholder()
            placeholders = ", ".join([ph] * (1 + len(present_fields)))
            key_to_sid: Dict[Tuple[Any, Tuple[Any, ...]], int] = {}
            # Atomic: a mid-loop failure rolls back every series row rather than
            # leaving key_to_sid pointing at uncommitted ids.
            with dbconn.transaction():
                for row in rows:
                    obsid, vals = _key(row)
                    if not obsid:
                        continue
                    key = (obsid, vals)
                    if key in key_to_sid:
                        continue
                    dbconn.execute(
                        f"INSERT INTO w_logger_series ({colnames})"
                        f" VALUES ({placeholders})",
                        (obsid,) + vals,
                    )
                    key_to_sid[key] = db_utils.get_last_insert_id(dbconn)
        finally:
            if close_dbconn:
                dbconn.closedb()

        keep = [i for i, c in enumerate(header) if c not in carrier_cols]
        new_header = [header[i] for i in keep] + ["series_id"]
        new_rows = []
        for row in rows:
            obsid, vals = _key(row)
            sid = key_to_sid.get((obsid, vals)) if obsid else None
            new_row = [row[i] if i < len(row) else None for i in keep]
            new_row.append(sid)
            new_rows.append(new_row)
        return [new_header] + new_rows
```

- [ ] **Step 6: Run the adapted backward-compat test**

Run: `python3 -m pytest test/test_import_general_csv_gui_backends.py -k with_source_routes_to_series -x`
Expected: PASS (both spatialite and postgis parametrizations). Note: column-name identifiers in the INSERT come from the fixed `SERIES_FIELDS` allowlist, never user input, matching the existing hardcoded-name style of the original method.

- [ ] **Step 7: Run the full general-csv backend + gui test files**

Run: `python3 -m pytest test/test_import_general_csv_gui_backends.py test/test_import_general_csv_gui.py -x`
Expected: PASS.

- [ ] **Step 8: Lint and commit**

```bash
ruff check --fix tools/import_general_csv_gui.py test/test_import_general_csv_gui_backends.py
ruff format tools/import_general_csv_gui.py test/test_import_general_csv_gui_backends.py
git add tools/import_general_csv_gui.py test/test_import_general_csv_gui_backends.py
git commit -m "feat: route full logger-series metadata via carrier columns in CSV import"
```

---

## Task 3: New backend tests for the full metadata path

Lock in the new behavior: static metadata, mixed source-from-column, the comment-collision regression guard, no-mapping NULL, and old-schema fallback.

**Files:**
- Test: `test/test_import_general_csv_gui_backends.py`

For all tests below, reuse the exact harness shape from `test_import_w_levels_logger_with_source_routes_to_series` (the nested `_test` with the same five `@mock.patch` decorators and the same `side_effect`). Only the CSV `file`, the column mappings, and the assertions differ. Print `mock_messagebar.mock_calls` is not needed here since these go through the full flow; instead assert on DB state.

- [ ] **Step 1: Write `test_import_w_levels_logger_series_static_metadata`**

```python
    def test_import_w_levels_logger_series_static_metadata(self):
        """source from file column, instrument+description as static values →
        one series row per (obsid, source) carrying the static metadata."""
        file = [
            "obsid,date_time,head_cm,source",
            "rb1,2016-03-15 10:30:00,100.0,fileA",
            "rb1,2016-03-15 11:00:00,101.0,fileA",
        ]
        db_utils.sql_alter_db("""INSERT INTO obs_points (obsid) VALUES ('rb1')""")

        with common_utils.tempinput("\n".join(file), "utf-8") as filename:
            # ... same nested @mock.patch _test harness as the routing test ...
            # Inside _test, after import_method = "w_levels_logger":
            #   map obsid/date_time/head_cm on importer.table_chooser.columns
            #   on importer.table_chooser.series_columns:
            #     source      -> file_column_name = "source"
            #     instrument  -> static_checkbox.setChecked(True);
            #                    combobox.setEditText("Diver-A")
            #     description -> static_checkbox.setChecked(True);
            #                    combobox.setEditText("wellhead")
            #     comment     -> file_column_name = None
            # then importer.start_import()

            rows = db_utils.sql_load_fr_db(
                "SELECT obsid, source, instrument, description, comment"
                " FROM w_logger_series ORDER BY obsid, source"
            )[1]
            assert [tuple(r) for r in rows] == [
                ("rb1", "fileA", "Diver-A", "wellhead", None),
            ]
            sids = db_utils.sql_load_fr_db(
                "SELECT series_id FROM w_levels_logger ORDER BY date_time"
            )[1]
            assert sids[0][0] is not None and sids[0][0] == sids[1][0]
```

When fleshing out the `_test` harness, set a static value on a `ColumnEntry` like this (matches how `ColumnEntry.file_column_name` reads static values):

```python
                for column in importer.table_chooser.series_columns:
                    if column.db_column == "source":
                        column.file_column_name = "source"
                    elif column.db_column == "instrument":
                        column.static_checkbox.setChecked(True)
                        column.combobox.setEditText("Diver-A")
                    elif column.db_column == "description":
                        column.static_checkbox.setChecked(True)
                        column.combobox.setEditText("wellhead")
                    else:
                        column.file_column_name = None
```

- [ ] **Step 2: Run it**

Run: `python3 -m pytest test/test_import_general_csv_gui_backends.py -k series_static_metadata -x`
Expected: PASS.

- [ ] **Step 3: Write `test_import_w_levels_logger_series_comment_collision`**

Guards the `comment` double-map. Logger `comment` and series `comment` read different file columns and must land in their own tables.

```python
    def test_import_w_levels_logger_series_comment_collision(self):
        file = [
            "obsid,date_time,head_cm,row_comment,series_comment",
            "rb1,2016-03-15 10:30:00,100.0,row-note,batch-note",
        ]
        db_utils.sql_alter_db("""INSERT INTO obs_points (obsid) VALUES ('rb1')""")

        with common_utils.tempinput("\n".join(file), "utf-8") as filename:
            # In _test, map on importer.table_chooser.columns:
            #   obsid->obsid, date_time->date_time, head_cm->head_cm,
            #   comment -> "row_comment"
            # on importer.table_chooser.series_columns:
            #   comment -> "series_comment"; all other series fields -> None
            # then importer.start_import()

            logger = db_utils.sql_load_fr_db(
                "SELECT comment FROM w_levels_logger"
            )[1]
            assert [tuple(r) for r in logger] == [("row-note",)]
            series = db_utils.sql_load_fr_db(
                "SELECT comment FROM w_logger_series"
            )[1]
            assert [tuple(r) for r in series] == [("batch-note",)]
```

Mapping the logger `comment` inside `_test`:

```python
                for column in importer.table_chooser.columns:
                    names = {
                        "obsid": "obsid",
                        "date_time": "date_time",
                        "head_cm": "head_cm",
                        "comment": "row_comment",
                    }
                    if column.db_column in names:
                        column.file_column_name = names[column.db_column]
                for column in importer.table_chooser.series_columns:
                    if column.db_column == "comment":
                        column.file_column_name = "series_comment"
                    else:
                        column.file_column_name = None
```

- [ ] **Step 4: Run it**

Run: `python3 -m pytest test/test_import_general_csv_gui_backends.py -k series_comment_collision -x`
Expected: PASS.

- [ ] **Step 5: Write `test_import_w_levels_logger_no_series_mapped_null_series_id`**

```python
    def test_import_w_levels_logger_no_series_mapped_null_series_id(self):
        """No series field mapped → no w_logger_series rows, series_id NULL."""
        file = [
            "obsid,date_time,head_cm",
            "rb1,2016-03-15 10:30:00,100.0",
        ]
        db_utils.sql_alter_db("""INSERT INTO obs_points (obsid) VALUES ('rb1')""")

        with common_utils.tempinput("\n".join(file), "utf-8") as filename:
            # In _test: map obsid/date_time/head_cm; set every
            # series_columns entry file_column_name = None; start_import()

            count = db_utils.sql_load_fr_db(
                "SELECT count(*) FROM w_logger_series"
            )[1]
            assert int(count[0][0]) == 0
            sids = db_utils.sql_load_fr_db(
                "SELECT series_id FROM w_levels_logger"
            )[1]
            assert sids[0][0] is None
```

- [ ] **Step 6: Run it**

Run: `python3 -m pytest test/test_import_general_csv_gui_backends.py -k no_series_mapped_null -x`
Expected: PASS.

- [ ] **Step 7: Write the old-schema fallback test**

This one must run against a DB **without** `w_logger_series` / `series_id`. Add it to the existing class but drop the new objects first so the chooser sees the old shape:

```python
    def test_import_w_levels_logger_old_schema_source_is_plain_column(self):
        """Without w_logger_series / series_id, source is a normal column and
        no series block is built."""
        db_utils.sql_alter_db("DROP TABLE IF EXISTS w_logger_series")
        # Recreate w_levels_logger without series_id/created_at to emulate old
        # schema, OR skip if the test DB cannot be reshaped — see note below.
        ...
```

NOTE: reshaping `w_levels_logger` mid-test is invasive. If the test DB-creation fixtures do not offer an old-schema variant, implement this as a **GUI-level** check in `test/test_import_general_csv_gui.py` instead, by constructing `ImportTableChooser` directly with a `tables_columns` dict that has no `w_logger_series` and a `w_levels_logger` entry without `series_id`, then asserting `series_columns == []` and that a `source` column appears in `columns`. Prefer the GUI-level form unless an old-schema DB fixture already exists. Implement exactly one of the two; do not leave a placeholder.

GUI-level form:

```python
def test_old_schema_source_is_plain_column_no_series_block(self):
    tables_columns = {
        "w_levels_logger": [
            (0, "obsid", "text", 1, None, 1),
            (1, "date_time", "text", 1, None, 2),
            (2, "head_cm", "double", 0, None, 0),
            (3, "source", "text", 0, None, 0),
        ],
    }
    chooser = ImportTableChooser(tables_columns, file_header=["obsid", "source"])
    chooser.import_method = "w_levels_logger"
    assert chooser.series_columns == []
    assert "source" in [c.db_column for c in chooser.columns]
```

(`ImportTableChooser` is constructible standalone — `embed_chooser_in_layout` defaults to True and it needs no DB. Import it from `midvatten.tools.import_general_csv_gui` at the top of the test file if not already imported.)

- [ ] **Step 8: Run it**

Run: `python3 -m pytest test/test_import_general_csv_gui.py -k old_schema_source -x`
(or the backend variant path you chose)
Expected: PASS.

- [ ] **Step 9: Run both general-csv test files in full**

Run: `python3 -m pytest test/test_import_general_csv_gui.py test/test_import_general_csv_gui_backends.py`
Expected: PASS (all spatialite + postgis parametrizations).

- [ ] **Step 10: Lint and commit**

```bash
ruff check --fix test/test_import_general_csv_gui_backends.py test/test_import_general_csv_gui.py
ruff format test/test_import_general_csv_gui_backends.py test/test_import_general_csv_gui.py
git add test/test_import_general_csv_gui_backends.py test/test_import_general_csv_gui.py
git commit -m "test: cover full logger-series metadata CSV import paths"
```

---

## Task 4: Simplify pass and full suite

**Files:** any touched above.

- [ ] **Step 1: Invoke the `simplify` skill** on the changed code (required by CLAUDE.md after code changes). Apply its cleanups.

- [ ] **Step 2: Run the broader suite**

Run (per CLAUDE.md ordering): first DB-creation, then the feature files, then the full suite.

```bash
python3 -m pytest test/test_create_spatialite_db.py test/test_create_postgis_db.py -x
python3 -m pytest test/test_import_general_csv_gui.py test/test_import_general_csv_gui_backends.py -x
python3 -m pytest test/
```
Expected: PASS (or only pre-existing unrelated failures — compare against a clean `ai_test` baseline if anything fails).

- [ ] **Step 3: Final commit if simplify changed anything**

```bash
git add -A
git commit -m "refactor: simplify logger-series CSV import per simplify skill"
```

---

## Self-Review Notes

- **Spec coverage:** fields exposed (T1), schema gating (T1 + T3 old-schema), series identity / two-pass id-capture (T2), source relocation / virtual-source removal (T2 step 3), same-grid UI with separator+sub-header (T1 `_append_series_block`), empty-mapping NULL (T3 no-series test), comment collision (T2 carrier naming + T3 collision test), stray `series_id` drop (T2 routing), dropped auto-description (T2; existing test doesn't assert it). All covered.
- **Type consistency:** `series_columns` (list of `ColumnEntry`), `get_series_translation()` → `{file_column_name: ["__series_<field>"]}`, `_route_series_metadata(file_data) -> file_data`, carrier prefix `"__series_"`, `SERIES_FIELDS` tuple — used consistently across tasks.
- **No placeholders:** the only branch ("old-schema as backend vs GUI-level test") gives a concrete decision rule and full code for the preferred form; implement exactly one.
