> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-04-17 · modified: 2026-04-17 · archived: 2026-07-31

# Instrument Serial Number Import — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **WORKTREE REQUIRED:** Before starting Task 1, create a dedicated git worktree using the `superpowers:using-git-worktrees` skill. All work happens in that worktree.

**Goal:** Extract instrument serial numbers from DiverOffice, Levelogger, and HOBO logger files during import and store them automatically in `w_logger_series.instrument`.

**Architecture:** Each of the four parse methods grows its return tuple from 4 to 5 elements (`serial_number` added last). `start_import()` carries the value through `parsed_files` → `parsed_files_with_obsid` → the `INSERT INTO w_logger_series` call. All changes are in two files.

**Tech Stack:** Python 3, pytest, SpatiaLite (integration test)

---

## File map

| File | Role |
|---|---|
| `tools/import_logger.py` | Add serial extraction to 4 parse methods; update all tuple return sites; extend start_import() plumbing |
| `test/test_import_logger.py` | 6 new unit tests + 1 integration test; ~10 existing unpack sites updated to 5-tuple |

---

## Important: test commands per task

Tasks 1–4 update parsers to return 5-tuples. `start_import()` still unpacks 4 — so spatialite integration tests will fail until Task 5. Run **without spatialite** for Tasks 1–4:

```
python3 -m pytest test/test_import_logger.py -m "not spatialite" -x
```

Task 5 fixes `start_import()` — run the **full suite** at the end:

```
python3 -m pytest test/ -x
```

---

## Task 1: DiverOfficeParser.parse() — serial extraction

**Files:**
- Modify: `tools/import_logger.py` — `DiverOfficeParser.parse()` (~lines 247–488)
- Test: `test/test_import_logger.py` — `TestDiverOfficeParser`

- [ ] **Step 1: Write two failing tests**

Add to the `TestDiverOfficeParser` class in `test/test_import_logger.py`:

```python
def test_parse_serial_number(self):
    file_content = (
        "[Logger settings]\n"
        "Serial number=..00-R2717  214.\n"
        "Location=rb1\n"
        "[data]\n"
        "Date/time;Water head[cm];Temperature[\u00b0C]\n"
        "2016/03/15 10:30:00;1.0;10.0\n"
    )
    with common_utils.tempinput(file_content, "utf-8") as f:
        result = DiverOfficeParser.parse(
            path=f, charset="utf-8",
            skip_rows_without_water_level=False,
            begindate=None, enddate=None,
        )
    _, _, _, _, serial_number = result
    assert serial_number == "R2717"

def test_parse_serial_number_absent(self):
    file_content = (
        "[Logger settings]\n"
        "Location=rb1\n"
        "[data]\n"
        "Date/time;Water head[cm]\n"
        "2016/03/15 10:30:00;1.0\n"
    )
    with common_utils.tempinput(file_content, "utf-8") as f:
        result = DiverOfficeParser.parse(
            path=f, charset="utf-8",
            skip_rows_without_water_level=False,
            begindate=None, enddate=None,
        )
    _, _, _, _, serial_number = result
    assert serial_number is None
```

- [ ] **Step 2: Run to see them fail**

```
python3 -m pytest test/test_import_logger.py::TestDiverOfficeParser::test_parse_serial_number test/test_import_logger.py::TestDiverOfficeParser::test_parse_serial_number_absent -v
```

Expected: `FAILED` — "not enough values to unpack (expected 5, got 4)"

- [ ] **Step 3: Add serial extraction to DiverOfficeParser.parse()**

In `tools/import_logger.py`, locate the block that resolves the UTC offset (the three `utc_offset = metadata.get(...)` lines ending with `utc_offset = metadata.get("channel identification", ...).get("utc offset (hh:mm)", "")`). Immediately **after** that block and **before** the `# Resolve location` comment, insert:

```python
        serial_raw = metadata.get("logger settings", {}).get("serial number", "")
        if not serial_raw:
            serial_raw = metadata.get("series settings", {}).get("serial number", "")
        serial_number = serial_raw.split('-')[-1].split()[0] if serial_raw.strip() else None
```

Then find every `return filedata, filename, location, utc_offset or None` line (there are four, including the final return at the bottom of the method) and add `, serial_number` to each:

```python
return filedata, filename, location, utc_offset or None, serial_number
```

The `return "skip"` line and the `return common_utils.ask_user_about_stopping(...)` line are **not** tuples — leave them unchanged.

- [ ] **Step 4: Update existing test unpack sites in TestDiverOfficeParser**

In `test/test_import_logger.py`, find these four unpack lines in `TestDiverOfficeParser` and add the fifth variable:

```python
# test_parse_utf8:
filedata, filename, location, utc_offset, serial_number = result

# test_parse_cp1252:
filedata, filename, location, utc_offset, serial_number = result

# test_parse_warning_missing_head_cm:
filedata, filename, location, utc_offset, serial_number = result

# test_parse_get_timezone:
_, _, _, utc_offset, _ = result
```

- [ ] **Step 5: Run tests (not spatialite)**

```
python3 -m pytest test/test_import_logger.py::TestDiverOfficeParser -v -m "not spatialite"
```

Expected: all `TestDiverOfficeParser` tests **PASS**.

- [ ] **Step 6: Commit**

```bash
git add tools/import_logger.py test/test_import_logger.py
git commit -m "feat: extract serial number from DiverOffice .parse() files"
```

---

## Task 2: DiverOfficeParser.parse_old() — serial extraction

**Files:**
- Modify: `tools/import_logger.py` — `DiverOfficeParser.parse_old()` (~lines 491–706)
- Test: `test/test_import_logger.py` — `TestDiverOfficeParser`

- [ ] **Step 1: Write failing test**

Add to `TestDiverOfficeParser` in `test/test_import_logger.py`:

```python
def test_parse_old_serial_number(self):
    file_content = (
        "Serial number=..00-R2717  214.\n"
        "Location=rb1\n"
        "Date/time,Water head[cm],Temperature[\u00b0C]\n"
        "2016/03/15 10:30:00,1.0,10.0\n"
        "2016/03/15 11:00:00,2.0,11.0\n"
    )
    with common_utils.tempinput(file_content, "utf-8") as f:
        result = DiverOfficeParser.parse_old(
            path=f, charset="utf-8",
            skip_rows_without_water_level=False,
            begindate=None, enddate=None,
        )
    _, _, _, _, serial_number = result
    assert serial_number == "R2717"
```

- [ ] **Step 2: Run to see it fail**

```
python3 -m pytest test/test_import_logger.py::TestDiverOfficeParser::test_parse_old_serial_number -v
```

Expected: `FAILED` — "not enough values to unpack (expected 5, got 4)"

- [ ] **Step 3: Implement serial extraction in parse_old()**

In `DiverOfficeParser.parse_old()`, find the line `utc_offset = None` (near the top of the method body) and add `serial_number = None` on the next line:

```python
        utc_offset = None
        serial_number = None
```

Find the `with open(path, ...) as f:` block. Inside its loop, there is already a block for `Instrument number`:

```python
                if row.lower().startswith("Instrument number".lower()):
                    try:
                        utc_offset = row.split("=")[1].strip()
                    except IndexError:
                        pass
                    continue
```

Add the `Serial number` block **immediately after** it (same indentation level):

```python
                if row.lower().startswith("serial number"):
                    try:
                        serial_raw = row.split("=")[1].strip()
                        serial_number = serial_raw.split('-')[-1].split()[0] if serial_raw else None
                    except IndexError:
                        pass
                    continue
```

Find the single tuple return at the very end of `parse_old()`:

```python
        return filedata, filename, location, utc_offset
```

Change it to:

```python
        return filedata, filename, location, utc_offset, serial_number
```

The two `return common_utils.ask_user_about_stopping(...)` and any `return "skip"` lines are string returns — leave them unchanged.

- [ ] **Step 4: Run tests (not spatialite)**

```
python3 -m pytest test/test_import_logger.py::TestDiverOfficeParser -v -m "not spatialite"
```

Expected: all `TestDiverOfficeParser` tests **PASS**.

- [ ] **Step 5: Commit**

```bash
git add tools/import_logger.py test/test_import_logger.py
git commit -m "feat: extract serial number from DiverOffice .parse_old() files"
```

---

## Task 3: LeveloggerParser.parse() — serial extraction

**Files:**
- Modify: `tools/import_logger.py` — `LeveloggerParser.parse()` (~lines 709–920)
- Test: `test/test_import_logger.py` — `TestLeveloggerParser`

- [ ] **Step 1: Write two failing tests**

Add to `TestLeveloggerParser` in `test/test_import_logger.py`:

```python
def test_parse_serial_number_next_line(self):
    """Serial_number: on its own line, value on the next line."""
    file_content = (
        "Serial_number:\n"
        "12345\n"
        "Location: rb1\n"
        "LEVEL\n"
        "UNIT: cm\n"
        "Date;Time;ms;LEVEL\n"
        "2016-03-15;10:30:00;0;1\n"
    )
    with common_utils.tempinput(file_content, "utf-8") as f:
        result = LeveloggerParser.parse(
            path=f, charset="utf-8",
            skip_rows_without_water_level=False,
            begindate=None, enddate=None,
        )
    _, _, _, _, serial_number = result
    assert serial_number == "12345"

def test_parse_serial_number_same_line(self):
    """Serial_number: value on the same line."""
    file_content = (
        "Serial_number: 12345\n"
        "Location: rb1\n"
        "LEVEL\n"
        "UNIT: cm\n"
        "Date;Time;ms;LEVEL\n"
        "2016-03-15;10:30:00;0;1\n"
    )
    with common_utils.tempinput(file_content, "utf-8") as f:
        result = LeveloggerParser.parse(
            path=f, charset="utf-8",
            skip_rows_without_water_level=False,
            begindate=None, enddate=None,
        )
    _, _, _, _, serial_number = result
    assert serial_number == "12345"
```

- [ ] **Step 2: Run to see them fail**

```
python3 -m pytest test/test_import_logger.py::TestLeveloggerParser::test_parse_serial_number_next_line test/test_import_logger.py::TestLeveloggerParser::test_parse_serial_number_same_line -v
```

Expected: `FAILED` — "not enough values to unpack (expected 5, got 4)"

- [ ] **Step 3: Add serial extraction to LeveloggerParser.parse()**

The method builds `col1 = [row[0] for row in rows]` and then immediately extracts `location` from it. After the entire `location` extraction block (which ends with the `else:` fallback loop for `"Location:"`), insert the serial extraction block:

```python
        try:
            sn_idx = col1.index("Serial_number:")
            serial_number = col1[sn_idx + 1].strip() or None
        except ValueError:
            serial_number = None
            for cell in col1:
                if cell.startswith("Serial_number:"):
                    v = cell[len("Serial_number:"):].strip()
                    serial_number = v or None
                    break
```

Now update **all** tuple return sites in `LeveloggerParser.parse()`. There are two groups:

**Early returns that occur before col1 is built** (the `data_header_idx` not-found return and the `delimiter is None` return — both before the `rows = [row.split(";") ...]` line): these can only use `None`:

```python
return [], filename, location, timezone, None
```

**All returns that occur after col1 is built** (two "no data" / "bad date" early returns and the normal return at the bottom): `serial_number` is already set by the extraction block:

```python
return [], filename, location, timezone, serial_number
```

The normal return at the end of the method:

```python
return filedata, filename, location, timezone, serial_number
```

- [ ] **Step 4: Update existing test unpack sites in TestLeveloggerParser**

In `test/test_import_logger.py`, update these lines inside `TestLeveloggerParser`:

```python
# test_parse_basic:
filedata, filename, location, timezone, serial_number = result

# test_parse_level_as_m:
filedata, _, _, _, _ = result

# test_returns_4_tuple — rename to test_returns_5_tuple, update docstring and assertions:
def test_returns_5_tuple(self):
    """LeveloggerParser.parse must always return a 5-tuple."""
    file_content = "Date;Time\n"
    with common_utils.tempinput(file_content, "utf-8") as f:
        result = LeveloggerParser.parse(
            path=f, charset="utf-8",
            skip_rows_without_water_level=False,
            begindate=None, enddate=None,
        )
    assert len(result) == 5
    assert result[0] == []
    assert result[3] is None
    assert result[4] is None
```

- [ ] **Step 5: Run tests (not spatialite)**

```
python3 -m pytest test/test_import_logger.py::TestLeveloggerParser -v -m "not spatialite"
```

Expected: all `TestLeveloggerParser` tests **PASS**.

- [ ] **Step 6: Commit**

```bash
git add tools/import_logger.py test/test_import_logger.py
git commit -m "feat: extract serial number from Levelogger files"
```

---

## Task 4: HoboParser.parse() — serial extraction

**Files:**
- Modify: `tools/import_logger.py` — `HoboParser.parse()` (~lines 923–1064)
- Test: `test/test_import_logger.py` — `TestHoboParser`

- [ ] **Step 1: Write failing test**

Add to `TestHoboParser` in `test/test_import_logger.py`:

```python
@mock.patch("midvatten.tools.import_logger.common_utils.MessagebarAndLog")
def test_parse_serial_number(self, mock_messagebar):
    file_content = (
        '"Plot Title: temp"\n'
        '"#","Date Time, GMT+01:00","Temp, \u00b0C (LGR S/N: 5678, SEN S/N: 5678, LBL: Rb1)"\n'
        '1,"07/19/18 10:00:00 fm",4.558\n'
    )
    tz_converter = TzConverter()
    with common_utils.tempinput(file_content, "utf-8") as f:
        result = HoboParser.parse(
            path=f, charset="utf-8",
            tz_converter=tz_converter,
            begindate=None, enddate=None,
        )
    _, _, _, _, serial_number = result
    assert serial_number == "5678"
```

- [ ] **Step 2: Run to see it fail**

```
python3 -m pytest test/test_import_logger.py::TestHoboParser::test_parse_serial_number -v
```

Expected: `FAILED` — "not enough values to unpack (expected 5, got 4)"

- [ ] **Step 3: Add serial extraction to HoboParser.parse()**

In `HoboParser.parse()`, find the block that extracts `location` from `rows[1][temp_colnr]` using `re.search(r"LBL: ...")`. It ends with an `else:` that sets `location = match.group(1)`. Immediately **after** that entire `if/else` block (same indentation as the `match = re.search(...)` line), add:

```python
        sn_match = re.search(r'LGR S/N:\s*(\w+)', rows[data_header_idx][temp_colnr])
        serial_number = sn_match.group(1) if sn_match else None
```

Now update **all** tuple return sites in `HoboParser.parse()`:

**Early return before data_header_idx is found** (before temp_colnr / serial extraction): uses `None`:

```python
return [], filename, location, None, None   # 4-tuple fix → 5-tuple fix
```

**Returns after serial extraction** (two early returns and the normal return at bottom):

```python
return [], filename, location, None, serial_number   # 5-tuple fix
```

The normal return at the bottom:

```python
return filedata, filename, location, None, serial_number   # 5-tuple fix
```

Note: the 4th element stays `None` throughout HoboParser because HOBO files have no UTC offset.

- [ ] **Step 4: Update existing test unpack sites in TestHoboParser**

In `test/test_import_logger.py`, update these lines inside `TestHoboParser`:

```python
# test_parse_utf8:
filedata, filename, location, utc_offset, serial_number = result  # must be 5-tuple

# test_parse_convert_tz:
filedata, _, _, _, _ = result

# test_parse_always_returns_4_tuple — rename to test_parse_always_returns_5_tuple:
def test_parse_always_returns_5_tuple(self, mock_messagebar):
    """HoboParser must return a 5-tuple even on parse failure."""
    file_content = '"Plot Title: temp"\n'
    tz_converter = TzConverter()
    with common_utils.tempinput(file_content, "utf-8") as f:
        result = HoboParser.parse(
            path=f, charset="utf-8",
            tz_converter=tz_converter,
            begindate=None, enddate=None,
        )
    assert len(result) == 5
    assert result[3] is None
    assert result[4] is None
```

- [ ] **Step 5: Run tests (not spatialite)**

```
python3 -m pytest test/test_import_logger.py::TestHoboParser -v -m "not spatialite"
```

Expected: all `TestHoboParser` tests **PASS**.

- [ ] **Step 6: Commit**

```bash
git add tools/import_logger.py test/test_import_logger.py
git commit -m "feat: extract serial number from HOBO files"
```

---

## Task 5: start_import() plumbing + integration test

**Files:**
- Modify: `tools/import_logger.py` — `LoggerImport.start_import()` (~lines 1396–1716)
- Test: `test/test_import_logger.py` — `TestLoggerImportDiverOfficeSpatialite`

- [ ] **Step 1: Write failing integration test**

Add to `TestLoggerImportDiverOfficeSpatialite` in `test/test_import_logger.py`:

```python
def test_diveroffice_import_instrument_serial(self):
    """Serial number extracted from file is stored in w_logger_series.instrument."""
    db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
    file_content = "\n".join([
        "[Logger settings]",
        "Serial number=..00-R2717  214.",
        "Location=rb1",
        "[data]",
        "Date/time;Water head[cm];Temperature[\u00b0C]",
        "2016/03/15 10:30:00;1.0;10.0",
    ])
    with common_utils.tempinput(file_content, "utf-8") as f:

        @mock.patch("midvatten.tools.import_data_to_db.common_utils.NotFoundQuestion")
        @mock.patch("midvatten.tools.import_data_to_db.common_utils.Askuser")
        @mock.patch("qgis.utils.iface", autospec=True)
        @mock.patch("midvatten.tools.import_data_to_db.common_utils.pop_up_info", autospec=True)
        @mock.patch("midvatten.tools.import_logger.midvatten_utils.select_files")
        def _run(self, filename, mock_select_files, mock_popup, mock_iface, mock_askuser, mock_notfound):
            mock_notfound.return_value.answer = "ok"
            mock_notfound.return_value.value = "rb1"
            mock_notfound.return_value.reuse_column = "location"
            mock_select_files.return_value = [filename]

            ms = MagicMock()
            ms.settingsdict = OrderedDict()
            importer = LoggerImport(self.iface, ms)
            importer.load_gui()
            importer.format_combo.setCurrentText(LoggerImport.FORMAT_DIVEROFFICE)
            importer.select_files()
            importer.start_import(
                files=importer.files,
                skip_rows_without_water_level=importer.skip_rows.checked,
                confirm_names=importer.confirm_names.checked,
                import_all_data=importer.import_all_data.checked,
            )

        _run(self, f)

    test_string = utils_for_tests.create_test_string(
        db_utils.sql_load_fr_db(
            "SELECT instrument FROM w_logger_series WHERE obsid='rb1'"
        )
    )
    assert test_string == "(True, [(R2717,)])"
```

- [ ] **Step 2: Run to see it fail**

```
python3 -m pytest test/test_import_logger.py::TestLoggerImportDiverOfficeSpatialite::test_diveroffice_import_instrument_serial -v
```

Expected: `FAILED` — the test runs but `instrument` is `None` (start_import hasn't been updated yet) OR a ValueError from unpacking 5 values into 4 variables.

- [ ] **Step 3: Update start_import() — unpack**

In `start_import()`, find:

```python
            try:
                file_data, filename, location, file_utc_offset = res
```

Change to:

```python
            try:
                file_data, filename, location, file_utc_offset, serial_number = res
```

- [ ] **Step 4: Update start_import() — parsed_files append**

Find:

```python
            parsed_files.append((file_data, filename, location))
```

Change to:

```python
            parsed_files.append((file_data, filename, location, serial_number))
```

- [ ] **Step 5: Update start_import() — parsed_files_with_obsid loop**

Find:

```python
        parsed_files_with_obsid = []
        for file_data, filename, location in parsed_files:
```

Change to:

```python
        parsed_files_with_obsid = []
        for file_data, filename, location, serial_number in parsed_files:
```

Find the line that appends to `parsed_files_with_obsid`:

```python
                parsed_files_with_obsid.append([file_data, filename, location])
```

Change to:

```python
                parsed_files_with_obsid.append([file_data, filename, location, serial_number])
```

- [ ] **Step 6: Update start_import() — INSERT loop**

Find the `for parsed_file in parsed_files_with_obsid:` loop that contains the `INSERT INTO w_logger_series` call. Change the loop header and the execute call:

```python
                for file_data, filename, location, serial_number in parsed_files_with_obsid:
                    obsid = filenames_obsid[filename]
                    description = (
                        os.path.basename(filename) if filename else None
                    )
                    dbconn.execute(
                        f"INSERT INTO w_logger_series "
                        f"(obsid, source, description, instrument) VALUES ({ph}, {ph}, {ph}, {ph})",
                        (obsid, source_for_series, description, serial_number or None),
                    )
```

Note: the `file_data` and `location` variables are not used in this loop body — they're bound just to unpack the tuple. The rest of the loop body (series_id retrieval, appending to file_data) is unchanged.

- [ ] **Step 7: Run full test suite**

```
python3 -m pytest test/ -x
```

Expected: all tests **PASS** (including spatialite integration tests).

- [ ] **Step 8: Run ruff**

```
ruff check --fix tools/import_logger.py test/test_import_logger.py
ruff format tools/import_logger.py test/test_import_logger.py
```

Expected: no errors. Re-run the tests if ruff made changes.

- [ ] **Step 9: Commit**

```bash
git add tools/import_logger.py test/test_import_logger.py
git commit -m "feat: store instrument serial number in w_logger_series.instrument"
```

---

## Self-review notes

- All 4 parse methods covered (spec Section 1 ✓)
- 5-tuple return documented for all return sites including early exits (spec Section 2 ✓)
- All three start_import() plumbing edits covered (spec Section 3 ✓)
- All 6 unit tests + 1 integration test covered (spec Section 4 ✓)
- Existing test unpack sites updated in all 3 test classes ✓
- The `"skip"` / `ask_user_about_stopping` returns are not tuples — correctly left unchanged ✓
