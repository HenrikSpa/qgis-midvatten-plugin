# Design: Read instrument serial number during logger import

**Date:** 2026-04-17  
**Branch:** ai_test  
**Status:** Approved

## Goal

Extract the instrument serial number from each logger file during import and store it automatically in `w_logger_series.instrument`. If no serial is found, leave the column `NULL` silently.

## Scope

Four parse methods across three parser classes in `tools/import_logger.py`:

- `DiverOfficeParser.parse()` — `.mon` files and structured CSV
- `DiverOfficeParser.parse_old()` — legacy flat CSV files
- `LeveloggerParser.parse()` — Levelogger data wizard CSV
- `HoboParser.parse()` — HOBO temperature logger CSV

The `start_import()` method in `LoggerImport` already creates one `w_logger_series` row per imported file. We add `instrument` to that INSERT.

## Section 1: Extraction logic per parser

### DiverOfficeParser.parse() — `.mon` and structured CSV

The metadata dict is already built from `[Logger settings]` / `[Series settings]` sections. Add a lookup after the UTC offset lookup:

```python
serial_raw = metadata.get("logger settings", {}).get("serial number", "")
if not serial_raw:
    serial_raw = metadata.get("series settings", {}).get("serial number", "")
serial_number = serial_raw.split('-')[-1].split()[0] if serial_raw.strip() else None
```

**Extraction rule:** split on `-`, take the last segment, take the first whitespace-delimited token.  
Example: `..00-R2717  214.` → `R2717`. A clean value like `R2717` also works.

### DiverOfficeParser.parse_old() — legacy flat CSV

The existing line-by-line loop already looks for `Location=` and `Instrument number=`. Add:

```python
if row.lower().startswith("serial number"):
    try:
        serial_raw = row.split("=")[1].strip()
        serial_number = serial_raw.split('-')[-1].split()[0] if serial_raw else None
    except IndexError:
        pass
```

### LeveloggerParser.parse()

`col1` holds every first-column value. Mirror the existing `Location:` logic (handles both value-on-next-line and value-on-same-line):

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

**File format variants:**
- Value on next line: `Serial_number:\n12345`
- Value on same line: `Serial_number: 12345`

### HoboParser.parse()

The serial is in the temperature column header. After `temp_colnr` is resolved, add:

```python
sn_match = re.search(r'LGR S/N:\s*(\w+)', rows[data_header_idx][temp_colnr])
serial_number = sn_match.group(1) if sn_match else None
```

Example header: `Temp, °C (LGR S/N: 1234, SEN S/N: 1234, LBL: Rb1)` → `"1234"`.

## Section 2: Return signature change

All four parse methods extend from a 4-tuple to a 5-tuple with `serial_number` as the last element.

```python
return filedata, filename, location, utc_offset, serial_number
```

**Early-exit / error returns** (empty data, parse failure) add `None` as the 5th element:

```python
return [], filename, location, None, None
```

String sentinels (`"skip"`, `"cancel"`) are unchanged.

**Call site in start_import():**

```python
# before:
file_data, filename, location, file_utc_offset = res
# after:
file_data, filename, location, file_utc_offset, serial_number = res
```

**Tests:** ~10 unpack sites updated from 4-tuple to 5-tuple form.

## Section 3: start_import() plumbing

Three small edits carry `serial_number` from parse result to the INSERT.

**1. parsed_files (line ~1532):**
```python
# before:
parsed_files.append((file_data, filename, location))
# after:
parsed_files.append((file_data, filename, location, serial_number))
```

**2. parsed_files_with_obsid (lines ~1578–1599):**
```python
# before:
for file_data, filename, location in parsed_files:
    parsed_files_with_obsid.append([file_data, filename, location])
# after:
for file_data, filename, location, serial_number in parsed_files:
    parsed_files_with_obsid.append([file_data, filename, location, serial_number])
```

**3. INSERT (lines ~1636–1646):**
```python
# before:
dbconn.execute(
    f"INSERT INTO w_logger_series (obsid, source, description) VALUES ({ph}, {ph}, {ph})",
    (obsid, source_for_series, description),
)
# after:
for file_data, filename, location, serial_number in parsed_files_with_obsid:
    ...
    dbconn.execute(
        f"INSERT INTO w_logger_series (obsid, source, description, instrument) VALUES ({ph}, {ph}, {ph}, {ph})",
        (obsid, source_for_series, description, serial_number or None),
    )
```

The old-schema path (no `series_id` column) does not write to `w_logger_series` and requires no changes.

## Section 4: Testing

### Parser unit tests (test/test_import_logger.py)

New tests in existing test classes:

| Class | Test | Input | Expected serial_number |
|---|---|---|---|
| `TestDiverOfficeParser` | `test_parse_serial_number` | `Serial number =..00-R2717  214.` in `[Logger settings]` | `"R2717"` |
| `TestDiverOfficeParser` | `test_parse_serial_number_absent` | no `Serial number` line | `None` |
| `TestDiverOfficeParser` | `test_parse_old_serial_number` | `Serial number=..00-R2717  214.` line in flat CSV | `"R2717"` |
| `TestLeveloggerParser` | `test_parse_serial_number_next_line` | `Serial_number:\n12345` | `"12345"` |
| `TestLeveloggerParser` | `test_parse_serial_number_same_line` | `Serial_number: 12345` | `"12345"` |
| `TestHoboParser` | `test_parse_serial_number` | `LGR S/N: 1234,` in temp column header | `"1234"` |

### Integration test (spatialite)

Add one test in `TestLoggerImportDiverOfficeSpatialite`: import a DiverOffice file with `Serial number =..00-R2717  214.` and assert `w_logger_series.instrument = 'R2717'`.

## Files changed

- `tools/import_logger.py` — extraction logic, 5-tuple returns, start_import() plumbing
- `test/test_import_logger.py` — 6 new unit tests + 1 integration test; ~10 existing unpack sites updated
