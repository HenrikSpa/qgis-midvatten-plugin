# Simplify date_utils with dateutil.parser

## Context

`tools/utils/date_utils.py` contains `find_date_format` which brute-forces 28 strptime format strings to parse dates, and `datestring_to_date` which wraps it with dead-code fallbacks (relative dates, epoch timestamps). The `dateutil` package (ships with pandas, already a mandatory dependency) handles all these formats out of the box with `dateutil.parser.parse`.

The format-string-preservation feature of `find_date_format` (returning the format for reuse in strftime) is only exercised in dead code paths — the production callers either pass datetime objects or only need parsed results.

## Design

### Replace `find_date_format` with `dateutil.parser.parse`

Delete `find_date_format` entirely. Replace all 5 call sites:

| Caller | Current | New |
|--------|---------|-----|
| `datestring_to_date()` | Calls `find_date_format` + `strptime` | Use `dateutil.parser.parse` directly |
| `reformat_date_time()` | Inspects format string to build output | Always output `%Y-%m-%d %H:%M:%S` |
| `change_timezone()` | Uses format to preserve input style | Always return datetime object |
| `DiverOfficeParser.parse_old()` | `find_date_format` + `strptime` | `dateutil.parser.parse` |
| `HoboParser.parse()` | Validation only | `datestring_to_date(dt) is not None` |

### Simplified `datestring_to_date`

```python
from dateutil import parser as dateutil_parser

def datestring_to_date(astring: str) -> datetime.datetime | None:
    if isinstance(astring, (datetime.datetime, datetime.date)):
        return astring
    try:
        return dateutil_parser.parse(str(astring), dayfirst=True)
    except (ValueError, TypeError, OverflowError):
        return None
```

- Drop `now` parameter (only used by dead relative-date code)
- Drop `df` parameter (one caller `long_dateformat` passes it; inline `strptime` there instead)
- `dayfirst=True` matches the current format ordering (day-first before month-first)

### Simplified `reformat_date_time`

```python
def reformat_date_time(astring: str) -> str | None:
    dt = datestring_to_date(astring)
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%d %H:%M:%S")
```

### Simplified `change_timezone`

Always returns a naive datetime (tzinfo stripped after conversion):

```python
def change_timezone(date_or_string, from_tz: str, to_tz: str) -> datetime.datetime:
    tz_naive = datestring_to_date(date_or_string) if isinstance(date_or_string, str) else date_or_string
    from_zone = pytz.timezone(from_tz)
    to_zone = pytz.timezone(to_tz)
    localized = from_zone.localize(tz_naive)
    return localized.astimezone(to_zone).replace(tzinfo=None)
```

### Dead code to remove

- `find_date_format` function (entire)
- `find_time_format` function (never called anywhere)
- `date_formats_to_try` list constant
- Relative date fallback in `datestring_to_date` (lines 180-183)
- Epoch timestamp fallback in `datestring_to_date` (line 186)

### `long_dateformat` update

Currently passes `df=dateformat` to `datestring_to_date`. Simplify to:

```python
def long_dateformat(astring: str, dateformat: str = None) -> str:
    if dateformat:
        dt = datetime.datetime.strptime(str(astring), dateformat)
    else:
        dt = datestring_to_date(astring)
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%d %H:%M:%S")
```

### Caller updates in parsers.py

**DiverOfficeParser.parse_old():** Replace:
```python
dateformat = find_date_format(cols[date_col])
date = _datetime.strptime(cols[date_col], dateformat)
```
With:
```python
date = date_utils.datestring_to_date(cols[date_col])
```

**HoboParser.parse():** Replace format detection with:
```python
if date_utils.datestring_to_date(dt) is None:
    dt = first_data_row[date_colnr][:-2].rstrip()
    if date_utils.datestring_to_date(dt) is None:
        # error handling...
```

**LeveloggerParser.parse():** Line 957 has a bug (calls `datestring_to_date` where `find_date_format` was intended). Simplify to just call `datestring_to_date` per row without pre-detecting format. The `df=` parameter usage on line 979 goes away.

### `dayfirst=True` rationale

The current format list tries ISO (unambiguous) first, then `%d-%m-%Y` patterns before the single `%m/%d/%y` pattern. Using `dayfirst=True` preserves this behavior. Ambiguous dates like "05/12/20" will parse as Dec 5 (day-first), same as today.

### What stays unchanged

- `dateshift()` — used directly by import UI code
- `parse_timezone_to_timedelta()` — timezone string parsing
- `get_pytz_timezones()` — timezone list helper
- `date_to_epoch()` — simplified to use new `datestring_to_date`

## Verification

1. Run existing test suite: `python3 -m pytest test/ -x`
2. Key test files: `test_wlevels_calc_calibr.py` (change_timezone tests), `test_import_logger.py` (parser tests)
3. Verify no test expects specific format-string returns from `find_date_format`
4. Check that HOBO logger imports still parse US-format dates correctly (the `fix_date` function in parsers.py hardcodes `%m/%d/%y %I:%M:%S` and doesn't use `find_date_format`)
