> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-07-21 · modified: 2026-07-21 · archived: 2026-07-31

# DiverOffice MON Import Robustness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make regular DiverOffice and DiverOffice Baro imports lossless across long, fixed-width and delimited files while isolating parse and database failures per file.

**Architecture:** Replace sample-based fixed-width inference with a deterministic right-edge parser and a full-file, losslessly validated pandas fallback. Carry structured per-file failures through the background workers, then import each validated file in its own transaction while retaining one immutable latest-date snapshot for the batch.

**Tech Stack:** Python 3.12, pandas, Python `csv` and `re`, PyQt/QGIS workers and signals, Midvatten's database abstraction and bulk importer, pytest with SpatiaLite integration coverage.

## Global Constraints

- Perform every edit, test, benchmark, and commit in `/home/hsai1/dev/midv/midvatten/.worktrees/diveroffice-mon-robustness` on branch `fix/diveroffice-mon-robustness`.
- Do not change database schemas.
- Do not change Levelogger or HOBO parsing behavior.
- Never accept a parsed DiverOffice file that altered, lost, duplicated, or moved a non-empty raw measurement token.
- Reject one ambiguous file atomically while continuing with other selected files.
- Keep logger-series creation and row insertion for one file in the same transaction.
- Take the per-obsid latest-date snapshot once before scheduling database jobs; never recalculate it between files.
- Continue using bulk row insertion within each file.
- A modest parser slowdown is acceptable; a 100,000-row primary-path median above twice baseline requires optimization.
- Preserve cancellation as a terminal batch action that rolls back the active file.

---

## File Structure

| File | Responsibility |
|---|---|
| `tools/import_logger/parsers.py` | Raw-line preservation, endpoint parser, guarded full-file fallback, strict validation, structured parse errors |
| `tools/import_logger/workers.py` | Structured parse batches, per-file database jobs, same-transaction logger-series creation |
| `tools/import_logger/importer.py` | Immutable date snapshot, per-file job orchestration, continuation and grouped summary |
| `test/test_import_logger.py` | Parser, importer, overlap, rollback, and summary regression coverage |
| `test/test_import_logger_workers.py` | Parse-batch, cancellation, and database-worker transaction tests |
| `scripts/benchmark_diveroffice_mon.py` | Reproducible 100,000-row before/after median benchmark |

---

### Task 1: Capture the regression and performance baseline

**Files:**
- Create: `scripts/benchmark_diveroffice_mon.py`
- Modify: `test/test_import_logger.py` in `TestDiverOfficeParser` and `TestDiverOfficeBaroParser`

**Interfaces:**
- Consumes: `DiverOfficeParser.parse(path, charset)` and `DiverOfficeBaroParser.parse(path, charset)`.
- Produces: `build_mon(row_count: int, baro: bool = False) -> str` and a benchmark CLI used unchanged after implementation.

- [ ] **Step 1: Add a benchmark generator and runner**

```python
"""Benchmark fixed-width DiverOffice MON parsing without database work."""

from __future__ import annotations

import argparse
import statistics
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

from midvatten.tools.import_logger import DiverOfficeParser


def build_mon(row_count: int, baro: bool = False) -> str:
    channel_1 = "PRESSURE" if baro else "WATER HEAD (WC)"
    location = "benchmark_baro" if baro else "benchmark_head"
    start = datetime(2025, 1, 1)
    rows = [
        "[Logger settings]",
        f"  Location                ={location}",
        "  Number of channels      =2",
        "[Channel 1]",
        f"  Identification          ={channel_1}",
        "[Channel 2]",
        "  Identification          =TEMPERATURE",
        "[Data]",
        str(row_count),
    ]
    for index in range(row_count):
        stamp = start + timedelta(minutes=index)
        head = 100.308 if index == row_count - 1 else 99.900
        rows.append(
            f"{stamp:%Y/%m/%d %H:%M:%S}.0"
            f"{head:13.3f}{5.0:12.3f}"
        )
    rows.append("END OF DATA FILE OF DATALOGGER FOR WINDOWS")
    return "\n".join(rows) + "\n"


def median_runtime(row_count: int, repeats: int) -> float:
    content = build_mon(row_count)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".mon", delete=False
    ) as handle:
        handle.write(content)
        path = Path(handle.name)
    try:
        DiverOfficeParser.parse(str(path), "utf-8", interactive=False)
        timings = []
        for _ in range(repeats):
            started = time.perf_counter()
            DiverOfficeParser.parse(str(path), "utf-8", interactive=False)
            timings.append(time.perf_counter() - started)
        return statistics.median(timings)
    finally:
        path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    median = median_runtime(args.rows, args.repeats)
    print(f"rows={args.rows} repeats={args.repeats} median_seconds={median:.6f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run and record the current median before production changes**

Run:

```bash
python3 scripts/benchmark_diveroffice_mon.py --rows 100000 --repeats 5
```

Expected: one `median_seconds=` line. Record the value in the implementation notes; do not commit a machine-specific timing file.

- [ ] **Step 3: Add failing regular and Baro boundary tests**

```python
def test_parse_mon_preserves_wider_head_after_inference_window(self):
    rows = [
        "[Logger settings]",
        "  Location                =rb1",
        "  Number of channels      =2",
        "[Channel 1]",
        "  Identification          =WATER HEAD (WC)",
        "[Channel 2]",
        "  Identification          =TEMPERATURE",
        "[Data]",
        "1001",
    ]
    rows.extend(
        f"2025/01/01 00:00:00.0{99.900:13.3f}{5.0:12.3f}"
        for _ in range(1000)
    )
    rows.append(f"2025/01/01 00:01:00.0{100.308:13.3f}{5.0:12.3f}")
    with file_utils.tempinput("\n".join(rows), "utf-8", suffix=".mon") as path:
        file_data, *_ = DiverOfficeParser.parse(path, "utf-8")
    assert file_data[-1][1] == "100.308"


def test_parse_baro_mon_preserves_wider_pressure_after_inference_window(self):
    content = build_mon(1001, baro=True)
    with file_utils.tempinput(content, "utf-8", suffix=".mon") as path:
        file_data, *_ = DiverOfficeBaroParser.parse(path, "utf-8")
    assert file_data[-1][1] == "100.308"
```

Import `build_mon` from `scripts.benchmark_diveroffice_mon` for the Baro test.

- [ ] **Step 4: Run the regression tests and verify the current failure**

Run:

```bash
python3 -m pytest test/test_import_logger.py::TestDiverOfficeParser::test_parse_mon_preserves_wider_head_after_inference_window test/test_import_logger.py::TestDiverOfficeBaroParser::test_parse_baro_mon_preserves_wider_pressure_after_inference_window -q
```

Expected: both fail because the final value is `0.308`.

---

### Task 2: Implement lossless fixed-width parsing and strict validation

**Files:**
- Modify: `tools/import_logger/parsers.py:219-590`
- Modify: `test/test_import_logger.py` in both DiverOffice parser classes

**Interfaces:**
- Consumes: metadata-derived `expected_num_fields`, `usecols`, and `colnames`.
- Produces: `DiverOfficeParseError`, `_SourceLine`, and the unchanged successful public five-tuple from `DiverOfficeParser.parse()`.

- [ ] **Step 1: Add parser data structures and a structured exception**

```python
@dataclass(frozen=True)
class _SourceLine:
    number: int
    text: str


@dataclass(frozen=True)
class _MonToken:
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class _ScannedMonRow:
    source: _SourceLine
    date_time: str
    tokens: tuple[_MonToken, ...]


class _IncompleteMonLayout(Exception):
    pass


class DiverOfficeParseError(ValueError):
    def __init__(
        self,
        filename: str,
        reason: str,
        line_number: int | None = None,
        raw_text: str | None = None,
        fallback_reason: str | None = None,
    ):
        self.filename = filename
        self.reason = reason
        self.line_number = line_number
        self.raw_text = raw_text
        self.fallback_reason = fallback_reason
        location = f" line {line_number}" if line_number is not None else ""
        details = f"{filename}{location}: {reason}"
        if raw_text is not None:
            details += f" [raw={raw_text!r}]"
        if fallback_reason is not None:
            details += f" [fallback={fallback_reason}]"
        super().__init__(details)
```

Add `dataclass` to the imports and export `DiverOfficeParseError` from `tools/import_logger/__init__.py`.

- [ ] **Step 2: Preserve physical data lines**

Replace the one stripped row list with parallel raw and stripped views:

```python
with open(path, encoding=str(charset)) as handle:
    raw_rows = [
        ru(raw_row).rstrip("\n").rstrip("\r")
        for raw_row in handle
    ]
rows = [raw_row.strip() for raw_row in raw_rows]
```

After resolving `data_start_row` and `stop_row`, construct:

```python
data_stop = stop_row if stop_row is not None else len(raw_rows)
source_lines = [
    _SourceLine(number=index + 1, text=raw_rows[index])
    for index in range(data_start_row, data_stop)
]
```

Read the line immediately after `[Data]` as `declared_count` only when its stripped text is an integer. Validate it against `len(source_lines)` before date filtering.

- [ ] **Step 3: Add the single-pass right-edge scanner**

```python
_MON_DATE_TIME_RE = re.compile(
    r"^\s*(?P<date>\S+)\s+(?P<time>\S+)"
)


def _scan_mon_rows(
    source_lines: list[_SourceLine],
    filename: str,
) -> list[_ScannedMonRow]:
    scanned = []
    for source in source_lines:
        date_match = _MON_DATE_TIME_RE.match(source.text)
        if date_match is None:
            raise DiverOfficeParseError(
                filename,
                "data row has no date/time prefix",
                source.number,
                source.text,
            )
        tokens = tuple(
            _MonToken(
                text=token.group(),
                start=token.start(),
                end=token.end(),
            )
            for token in re.finditer(r"\S+", source.text[date_match.end() :])
        )
        tokens = tuple(
            _MonToken(
                text=token.text,
                start=token.start + date_match.end(),
                end=token.end + date_match.end(),
            )
            for token in tokens
        )
        scanned.append(
            _ScannedMonRow(
                source=source,
                date_time=f"{date_match.group('date')} {date_match.group('time')}",
                tokens=tokens,
            )
        )
    return scanned
```

- [ ] **Step 4: Build a physical DataFrame from stable endpoints**

```python
def _frame_from_right_edges(
    scanned_rows: list[_ScannedMonRow],
    channel_count: int,
    filename: str,
) -> pd.DataFrame:
    endpoints = sorted(
        {token.end for row in scanned_rows for token in row.tokens}
    )
    if len(endpoints) != channel_count:
        raise _IncompleteMonLayout(
            f"observed {len(endpoints)} of {channel_count} channel endpoints"
        )
    endpoint_to_channel = {
        endpoint: index + 1 for index, endpoint in enumerate(endpoints)
    }
    records = []
    for row in scanned_rows:
        record = [row.date_time, *([None] * channel_count)]
        seen_channels = set()
        for token in row.tokens:
            channel = endpoint_to_channel.get(token.end)
            if channel is None or channel in seen_channels:
                raise DiverOfficeParseError(
                    filename,
                    "row has an ambiguous channel endpoint",
                    row.source.number,
                    row.source.text,
                )
            record[channel] = token.text
            seen_channels.add(channel)
        records.append(record)
    return pd.DataFrame(records, columns=range(channel_count + 1), dtype=object)
```

- [ ] **Step 5: Add the complete-file pandas fallback and losslessness proof**

```python
def _frame_from_full_fwf(
    source_lines: list[_SourceLine],
    scanned_rows: list[_ScannedMonRow],
    channel_count: int,
    filename: str,
) -> pd.DataFrame:
    raw = pd.read_fwf(
        StringIO("\n".join(line.text for line in source_lines)),
        header=None,
        dtype=str,
        infer_nrows=len(source_lines),
    )
    if raw.shape[1] != channel_count + 2:
        raise DiverOfficeParseError(
            filename,
            f"fallback found {raw.shape[1] - 2} channels; expected {channel_count}",
        )
    date_time = (
        raw.iloc[:, 0].fillna("").str.strip()
        + " "
        + raw.iloc[:, 1].fillna("").str.strip()
    ).str.strip()
    frame = pd.concat(
        [date_time, raw.iloc[:, 2:].reset_index(drop=True)],
        axis=1,
    )
    frame.columns = range(channel_count + 1)
    for row_index, scanned in enumerate(scanned_rows):
        parsed_tokens = [
            str(value).strip()
            for value in frame.iloc[row_index, 1:].tolist()
            if pd.notna(value) and str(value).strip()
        ]
        source_tokens = [token.text for token in scanned.tokens]
        if parsed_tokens != source_tokens:
            raise DiverOfficeParseError(
                filename,
                "fallback did not preserve measurement tokens",
                scanned.source.number,
                scanned.source.text,
            )
        if str(frame.iloc[row_index, 0]) != scanned.date_time:
            raise DiverOfficeParseError(
                filename,
                "fallback did not preserve date/time",
                scanned.source.number,
                scanned.source.text,
            )
    return frame
```

- [ ] **Step 6: Add vectorized strict conversion**

```python
def _strict_mon_conversion(
    frame: pd.DataFrame,
    scanned_rows: list[_ScannedMonRow],
    filename: str,
) -> pd.DataFrame:
    parsed_dates = pd.to_datetime(frame.iloc[:, 0], errors="coerce")
    invalid_dates = parsed_dates.isna()
    if invalid_dates.any():
        index = int(invalid_dates.to_numpy().nonzero()[0][0])
        source = scanned_rows[index].source
        raise DiverOfficeParseError(
            filename, "invalid date/time", source.number, source.text
        )
    frame.iloc[:, 0] = parsed_dates
    for column in frame.columns[1:]:
        raw = frame[column]
        normalized = raw.astype("string").str.replace(",", ".", regex=False)
        converted = pd.to_numeric(normalized, errors="coerce")
        invalid = raw.notna() & converted.isna()
        if invalid.any():
            index = int(invalid.to_numpy().nonzero()[0][0])
            source = scanned_rows[index].source
            raise DiverOfficeParseError(
                filename,
                f"invalid numeric value {raw.iloc[index]!r}",
                source.number,
                source.text,
            )
        frame[column] = converted
    return frame
```

- [ ] **Step 7: Replace `_read_mon_data()` with primary/fallback orchestration**

Scan once, attempt `_frame_from_right_edges()`, catch only `_IncompleteMonLayout`, then call `_frame_from_full_fwf()`. Run strict conversion, select `usecols`, assign `colnames`, and return the DataFrame. Do not catch `DiverOfficeParseError` from contradictory layouts.

- [ ] **Step 8: Add parser integrity tests**

Add parametrized tests for:

```python
@pytest.mark.parametrize(
    ("before", "after"),
    [(9.999, 10.001), (99.999, 100.001), (999.999, 1000.001)],
)
def test_parse_mon_preserves_digit_width_crossings(self, before, after):
    content = make_fixed_mon([before] * 1000 + [after])
    with file_utils.tempinput(content, "utf-8", suffix=".mon") as path:
        file_data, *_ = DiverOfficeParser.parse(path, "utf-8")
    assert float(file_data[-1][1]) == pytest.approx(after)
```

Add explicit strictness tests using these concrete assertions:

```python
def test_parse_mon_preserves_missing_channel_positions(self):
    content = make_three_channel_mon(
        [("1.0", None, "3.0"), (None, "2.0", "3.0"), ("1.0", "2.0", None)]
    )
    with file_utils.tempinput(content, "utf-8", suffix=".mon") as path:
        file_data, *_ = DiverOfficeParser.parse(path, "utf-8")
    assert [row[1:] for row in file_data[1:]] == [
        ["1.0", None, "3.0"],
        [None, "2.0", "3.0"],
        ["1.0", "2.0", None],
    ]


@pytest.mark.parametrize("value", ["-100.308", "+1,25", "1.25e3"])
def test_parse_mon_accepts_supported_numeric_tokens(self, value):
    content = make_fixed_mon([value])
    with file_utils.tempinput(content, "utf-8", suffix=".mon") as path:
        file_data, *_ = DiverOfficeParser.parse(path, "utf-8")
    assert float(file_data[1][1]) == pytest.approx(
        float(value.replace(",", "."))
    )


@pytest.mark.parametrize(
    ("row", "reason"),
    [
        ("not-a-date                         1.0", "date/time"),
        ("2025/01/01 00:00:00.0          invalid", "numeric"),
    ],
)
def test_parse_mon_rejects_invalid_rows(self, row, reason):
    content = make_fixed_mon_from_rows([row], declared_count=1)
    with file_utils.tempinput(content, "utf-8", suffix=".mon") as path:
        with pytest.raises(DiverOfficeParseError, match=reason):
            DiverOfficeParser.parse(path, "utf-8")


def test_parse_mon_rejects_declared_count_mismatch(self):
    content = make_fixed_mon([1.0], declared_count=2)
    with file_utils.tempinput(content, "utf-8", suffix=".mon") as path:
        with pytest.raises(DiverOfficeParseError, match="record count"):
            DiverOfficeParser.parse(path, "utf-8")


def test_parse_mon_fallback_accepts_lossless_left_aligned_fields(self):
    content = make_left_aligned_mon([9.9, 100.308])
    with file_utils.tempinput(content, "utf-8", suffix=".mon") as path:
        file_data, *_ = DiverOfficeParser.parse(path, "utf-8")
    assert [float(row[1]) for row in file_data[1:]] == [9.9, 100.308]


def test_parse_mon_fallback_rejects_token_loss(self):
    content = make_ambiguous_mon()
    with file_utils.tempinput(content, "utf-8", suffix=".mon") as path:
        with pytest.raises(DiverOfficeParseError, match="preserve"):
            DiverOfficeParser.parse(path, "utf-8")
```

- [ ] **Step 9: Run focused tests**

Run:

```bash
python3 -m pytest test/test_import_logger.py::TestDiverOfficeParser test/test_import_logger.py::TestDiverOfficeBaroParser -q
```

Expected: all parser tests pass, including the two Task 1 regressions.

- [ ] **Step 10: Commit the parser**

```bash
git add tools/import_logger/parsers.py tools/import_logger/__init__.py test/test_import_logger.py scripts/benchmark_diveroffice_mon.py
git commit -m "fix: parse DiverOffice MON values losslessly"
```

---

### Task 3: Make parse failures per-file results

**Files:**
- Modify: `tools/import_logger/workers.py:25-190`
- Modify: `tools/import_logger/importer.py:540-650`
- Modify: `test/test_import_logger_workers.py`

**Interfaces:**
- Produces: `LoggerFileFailure` and `LoggerParseBatchResult`.
- Consumes: `DiverOfficeParseError` from Task 2.

- [ ] **Step 1: Write failing worker tests**

```python
def test_parse_worker_collects_bad_file_and_continues():
    request = make_parse_request(("bad.mon", "good.mon"))
    worker = LoggerParseWorker(request)
    finished = []
    errors = []
    worker.finished.connect(finished.append)
    worker.error.connect(errors.append)
    with mock.patch.object(
        worker,
        "_parse_file",
        side_effect=[
            DiverOfficeParseError("bad.mon", "ambiguous endpoints", 12),
            ParsedLoggerFile(
                [["date_time", "head_cm"], ["2025-01-01 00:00:00", "1.0"]],
                "good.mon",
                "obs1",
                None,
            ),
        ],
    ):
        worker.run()
    assert errors == []
    assert [item.filename for item in finished[0].parsed_files] == ["good.mon"]
    assert [item.filename for item in finished[0].failures] == ["bad.mon"]
```

Keep the existing cancellation test and update its finished-result expectations.

- [ ] **Step 2: Add structured parse batch types**

```python
@dataclass(frozen=True)
class LoggerFileFailure:
    filename: str
    stage: str
    reason: str


@dataclass
class LoggerParseBatchResult:
    parsed_files: list[ParsedLoggerFile]
    failures: list[LoggerFileFailure]
```

- [ ] **Step 3: Catch only expected file failures inside the loop**

```python
def run(self) -> None:
    parsed_files = []
    failures = []
    try:
        for file_idx, selected_file in enumerate(self.request.files):
            self._check_cancelled()
            self.progress.emit(
                QCoreApplication.translate(
                    "LoggerImport", "Parsing file %s of %s..."
                )
                % (file_idx + 1, len(self.request.files))
            )
            try:
                result = self._parse_file(selected_file)
            except (DiverOfficeParseError, UnicodeDecodeError) as exc:
                failures.append(
                    LoggerFileFailure(
                        filename=os.path.basename(selected_file),
                        stage="parse",
                        reason=str(exc),
                    )
                )
                continue
            self._check_cancelled()
            if result is not None:
                parsed_files.append(result)
        self.finished.emit(LoggerParseBatchResult(parsed_files, failures))
    except LoggerImportCancelledError:
        self.cancelled.emit()
    except Exception:
        self.error.emit(traceback.format_exc())
```

When both UTF-8 and cp1252 decoding fail, re-raise the second `UnicodeDecodeError` so the loop records it.

- [ ] **Step 4: Teach the importer to consume the batch object**

Change `_run_parse_worker()` to return `LoggerParseBatchResult`, initialize the import summary with `batch.failures`, and iterate `batch.parsed_files` for observation-point assignment.

- [ ] **Step 5: Run worker and focused importer tests**

Run:

```bash
python3 -m pytest test/test_import_logger_workers.py test/test_import_logger.py::TestDiverOfficeParser -q
```

Expected: pass.

- [ ] **Step 6: Commit parse isolation**

```bash
git add tools/import_logger/workers.py tools/import_logger/importer.py test/test_import_logger_workers.py test/test_import_logger.py
git commit -m "fix: isolate logger parse failures by file"
```

---

### Task 4: Make each database job atomic, including logger-series metadata

**Files:**
- Modify: `tools/import_logger/workers.py:190-260`
- Modify: `test/test_import_logger_workers.py`

**Interfaces:**
- Produces: `LoggerSeriesSpec`, `LoggerDbImportRequest`, and `LoggerDbImportResult`.
- Consumes: one validated file's header and rows.

- [ ] **Step 1: Add failing transaction tests**

```python
def test_database_worker_rolls_back_series_and_rows_together():
    connection = FakeConnection()
    request = LoggerDbImportRequest(
        filename="bad.mon",
        dest_table="w_levels_logger",
        file_data=[
            ["date_time", "head_cm", "obsid"],
            ["2025-01-01 00:00:00", "100.308", "rb1"],
        ],
        series=LoggerSeriesSpec(
            obsid="rb1",
            source="test",
            description="bad.mon",
            instrument="SN1",
            created_at="2026-07-21 12:00:00",
        ),
    )
    worker = LoggerDbImportWorker({}, request)
    results = []
    worker.finished.connect(results.append)
    with (
        mock.patch(
            "midvatten.tools.import_logger.workers.db_utils.DbConnectionManager",
            return_value=connection,
        ),
        mock.patch(
            "midvatten.tools.import_logger.workers.import_data_to_db.MidvDataImporter.general_import",
            side_effect=RuntimeError("insert failed"),
        ),
    ):
        worker.run()
    assert connection.rollbacks == 1
    assert connection.commits == 0
    assert results == [
        LoggerDbImportResult("bad.mon", imported=False, reason=mock.ANY)
    ]
```

Add companion success and cancellation tests using the same request. The
success test asserts one commit and `imported=True`; the cancellation test
sets the worker cancel event during `general_import()` and asserts the
`cancelled` signal instead of a finished result.

- [ ] **Step 2: Add immutable database request/result types**

```python
@dataclass(frozen=True)
class LoggerSeriesSpec:
    obsid: str
    source: str | None
    description: str | None
    instrument: str | None
    created_at: str | None


@dataclass(frozen=True)
class LoggerDbImportRequest:
    filename: str
    dest_table: str
    file_data: list
    series: LoggerSeriesSpec | None = None


@dataclass(frozen=True)
class LoggerDbImportResult:
    filename: str
    imported: bool
    reason: str | None = None
```

- [ ] **Step 3: Move series creation into the worker transaction**

Inside `LoggerDbImportWorker.run()`, copy the file data, begin one connection transaction, optionally insert `w_logger_series`, append `series_id` and `created_at`, and then call:

```python
importer.general_import(
    request.dest_table,
    file_data,
    _dbconnection=connection,
    skip_confirmation=True,
    defer_commit=True,
    progress_callback=self._on_progress,
    manage_wait_cursor=False,
)
```

On success emit `LoggerDbImportResult(request.filename, True)`. On a non-cancellation exception, allow the transaction context to roll back and emit `LoggerDbImportResult(request.filename, False, traceback.format_exc())`. Remove `cleanup_series_ids` and `_cleanup_created_series()`.

- [ ] **Step 4: Remove empty series rows inside the transaction**

After bulk import, when a series was created, query `w_levels_logger` for the new `series_id`. If its row count is zero, delete the `w_logger_series` row before commit and return `imported=False` with reason `"no non-duplicate rows"`.

- [ ] **Step 5: Run database worker tests**

Run:

```bash
python3 -m pytest test/test_import_logger_workers.py -q
```

Expected: pass.

- [ ] **Step 6: Commit database atomicity**

```bash
git add tools/import_logger/workers.py test/test_import_logger_workers.py
git commit -m "fix: import each logger file atomically"
```

---

### Task 5: Orchestrate per-file jobs without creating date gaps

**Files:**
- Modify: `tools/import_logger/importer.py:540-910`
- Modify: `test/test_import_logger.py`

**Interfaces:**
- Consumes: `LoggerParseBatchResult` and `LoggerDbImportRequest`.
- Produces: per-file jobs and one grouped completion summary.

- [ ] **Step 1: Add failing overlap and continuation integration tests**

Seed `rb1` at `2025-01-01 00:00:00`. Select two files in this order:

- late segment: January 10-12;
- full period: January 1-12.

Assert that both `import_all_data=False` and `True` leave every expected timestamp present. Add another test where the first database job returns failure and the second succeeds; assert the successful file's rows and series remain committed.

- [ ] **Step 2: Add an import summary model**

```python
@dataclass
class LoggerImportSummary:
    imported: list[str] = field(default_factory=list)
    no_new_rows: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    parse_failures: list[LoggerFileFailure] = field(default_factory=list)
    database_failures: list[LoggerFileFailure] = field(default_factory=list)
```

Import `dataclass` and `field` from `dataclasses`.

- [ ] **Step 3: Preserve one pre-job latest-date snapshot**

```python
last_dates = None
if not import_all_data:
    last_dates = db_utils.get_last_logger_dates()
    for parsed_file in parsed_files_with_obsid:
        parsed_file[0] = filter_dates_from_filedata(
            parsed_file[0], last_dates
        )
```

This block must remain before the first `_run_db_worker()` call. Remove empty files into `summary.no_new_rows`; never call `get_last_logger_dates()` inside the per-file job loop.

- [ ] **Step 4: Build and run one regular DiverOffice job per file**

For each remaining parsed file, copy its rows, append old-schema `source`
when required, and construct the exact job:

```python
series = None
if has_series_id:
    series = LoggerSeriesSpec(
        obsid=filenames_obsid[filename],
        source=source_text or None,
        description=os.path.basename(filename) if filename else None,
        instrument=serial_number,
        created_at=batch_created_at if has_created_at else None,
    )
request = LoggerDbImportRequest(
    filename=filename,
    dest_table="w_levels_logger",
    file_data=file_data,
    series=series,
)
result = self._run_db_worker(request, progress)
if result.imported:
    summary.imported.append(filename)
else:
    summary.database_failures.append(
        LoggerFileFailure(filename, "database", result.reason or "import failed")
    )
```

Continue the loop after a failed result. Keep `batch_created_at` common to the
selected batch.

- [ ] **Step 5: Build and run one Baro job per file**

Pivot each file separately with `_pivot_baro_to_meteo()`. Seed `zz_meteoparam` once, then submit one `LoggerDbImportRequest` per non-empty pivot. Record failures and continue.

- [ ] **Step 6: Add grouped reporting**

Implement:

```python
def _report_import_summary(self, summary: LoggerImportSummary) -> None:
    bar_message = QCoreApplication.translate(
        "LoggerImport",
        "Logger import complete: %s imported, %s skipped or failed.",
    ) % (
        len(summary.imported),
        len(summary.no_new_rows)
        + len(summary.skipped)
        + len(summary.parse_failures)
        + len(summary.database_failures),
    )
    detail_lines = [f"Imported: {name}" for name in summary.imported]
    detail_lines.extend(f"No new rows: {name}" for name in summary.no_new_rows)
    detail_lines.extend(f"Skipped: {name}" for name in summary.skipped)
    detail_lines.extend(
        f"Parse failure: {failure.filename}: {failure.reason}"
        for failure in summary.parse_failures
    )
    detail_lines.extend(
        f"Database failure: {failure.filename}: {failure.reason}"
        for failure in summary.database_failures
    )
    message_utils.MessagebarAndLog.info(
        bar_msg=bar_message,
        log_msg="\n".join(detail_lines),
    )
```

If nothing imports, use a warning or critical message rather than an unqualified completion message.

- [ ] **Step 7: Run focused SpatiaLite integration tests**

Run:

```bash
python3 -m pytest test/test_import_logger.py -m "active or spatialite" -q
```

Expected: pass.

- [ ] **Step 8: Commit importer orchestration**

```bash
git add tools/import_logger/importer.py test/test_import_logger.py
git commit -m "fix: continue logger import after per-file failures"
```

---

### Task 6: Verify performance, compatibility, and code quality

**Files:**
- Modify only if verification exposes a defect: files already listed above

**Interfaces:**
- Consumes: all completed tasks.
- Produces: verified implementation and benchmark comparison.

- [ ] **Step 1: Run the post-change benchmark**

```bash
python3 scripts/benchmark_diveroffice_mon.py --rows 100000 --repeats 5
```

Expected: median no more than twice the Task 1 baseline. If it exceeds 2×, profile the primary path and remove duplicate scans or copies before proceeding.

- [ ] **Step 2: Run focused parser and worker tests**

```bash
python3 -m pytest test/test_import_logger.py::TestDiverOfficeParser test/test_import_logger.py::TestDiverOfficeBaroParser test/test_import_logger_workers.py -q
```

Expected: pass.

- [ ] **Step 3: Run the complete logger import module**

```bash
python3 -m pytest test/test_import_logger.py -m "not postgis" -q
```

Expected: pass.

- [ ] **Step 4: Run relevant general-import regressions**

```bash
python3 -m pytest test/test_import_data_to_db.py test/test_w_logger_series.py -m "not postgis" -q
```

Expected: pass.

- [ ] **Step 5: Run PostgreSQL tests when configured**

```bash
python3 -m pytest test/test_import_logger.py test/test_import_data_to_db.py -m postgis -q
```

Expected: pass when the PostgreSQL test backend is configured; otherwise report the environment skip/failure separately.

- [ ] **Step 6: Run lint and formatting**

```bash
ruff check --fix tools/import_logger/parsers.py tools/import_logger/workers.py tools/import_logger/importer.py test/test_import_logger.py test/test_import_logger_workers.py scripts/benchmark_diveroffice_mon.py
ruff format tools/import_logger/parsers.py tools/import_logger/workers.py tools/import_logger/importer.py test/test_import_logger.py test/test_import_logger_workers.py scripts/benchmark_diveroffice_mon.py
```

- [ ] **Step 7: Re-run focused tests after formatting**

```bash
python3 -m pytest test/test_import_logger.py::TestDiverOfficeParser test/test_import_logger.py::TestDiverOfficeBaroParser test/test_import_logger_workers.py -q
```

Expected: pass.

- [ ] **Step 8: Run the full non-PostgreSQL suite**

```bash
python3 -m pytest test/ -m "not postgis" -q
```

Expected: pass. Investigate any failure before claiming completion.

- [ ] **Step 9: Commit verification-only corrections**

If lint, formatting, or verification required source changes:

```bash
git add tools/import_logger/parsers.py tools/import_logger/workers.py tools/import_logger/importer.py test/test_import_logger.py test/test_import_logger_workers.py scripts/benchmark_diveroffice_mon.py
git commit -m "test: verify robust DiverOffice imports"
```

If no files changed, do not create an empty commit.
