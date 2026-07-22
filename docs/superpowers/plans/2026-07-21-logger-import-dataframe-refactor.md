# Logger Import DataFrame-First Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task by task. Use the
> repository-required worktree workflow before editing production code and run
> the required simplification review after code changes.

**Goal:** Keep logger measurements in one typed pandas DataFrame from parsing
through filtering, timezone conversion, export, and database preparation,
removing the legacy list-of-lists conversion cycle while preserving all logger
formats, database variants, and operational safety.

**Architecture:** Give every format parser one uniform `file -> canonical typed
frame + metadata` contract, then run every result through the same DataFrame
pipeline. Format selection ends at the parser boundary; later differences use
declarative data-kind/schema policies. Let the generic importer accept
DataFrames at one compatibility boundary. Keep the GUI as an orchestrator and
workers as execution/transaction boundaries.

**Tech Stack:** Python 3.12, pandas, Python `csv`/`re`, PyQt/QGIS workers and
signals, Midvatten database abstraction, SQLite/SpatiaLite, PostgreSQL/PostGIS,
pytest, ruff.

**Design:**
`docs/superpowers/specs/2026-07-21-logger-import-dataframe-refactor-design.md`

## Global Constraints

- Work in an isolated git worktree created through the repository-required
  worktree workflow; do not implement directly in the primary checkout.
- Do not modify database schemas.
- Do not weaken the DiverOffice raw-token losslessness proof or file-level
  atomicity.
- Keep all four formats: DiverOffice, DiverOffice Baro, Levelogger, and HOBO.
- Preserve legacy intent—supported data meanings, user options, database
  contracts, and safety properties—not incidental implementation behavior.
- Parser selection is the final source-format branch. No parser-specific
  filtering, timezone handling, obsid/latest-date logic, reshaping, export, or
  database preparation may remain after parsing.
- All parsers return the same canonical union columns. Format-specific absent
  measurements are numeric null columns; semantic destination differences are
  represented by `LoggerDataKind`.
- Keep oldest, source-column, and logger-series database schema compatibility.
- Keep one immutable latest-date snapshot for all selected files.
- Keep per-file sequential database jobs, bulk insertion, cancellation, and
  transaction rollback behavior.
- Keep legacy list input working for non-logger `MidvDataImporter` callers.
- Do not maintain both list and DataFrame representations inside the completed
  logger package.
- Do not use `iterrows()`, row-wise DataFrame concatenation, or per-row SQL.
- Invalid non-empty dates/numbers must fail visibly; `errors="coerce"` requires
  an immediately checked invalid mask.
- Preserve source row order and reset to a `RangeIndex` after row filtering.
- Format datetime text only at CSV/database boundaries.
- Run a simplification pass after each production-code slice, deleting adapters
  and branches made obsolete by that slice.

## Target File Structure

| File | Responsibility |
|---|---|
| `tools/import_logger/models.py` | Named frame, request/result, and schema capability models; canonical columns |
| `tools/import_logger/pipeline.py` | Pure typed DataFrame transformations and invariant checks |
| `tools/import_logger/parsers.py` | File-specific decoding, metadata, mapping, units, and complete-file validation |
| `tools/import_logger/workers.py` | Parse execution, shared post-parse transforms, cancellation, and per-file DB transactions |
| `tools/import_logger/importer.py` | GUI interaction, obsid resolution, immutable DB snapshot, job scheduling, summary |
| `tools/import_data_to_db.py` | One list/DataFrame compatibility boundary and DataFrame-native internal staging |
| `tools/utils/file_utils.py` | Existing legacy CSV writer remains; logger-specific DataFrame export may live in pipeline/importer |
| `test/test_import_logger_pipeline.py` | Pure DataFrame contract and transform tests |
| `test/test_import_logger.py` | Parser, GUI/import integration, schema variants, export, summaries |
| `test/test_import_logger_workers.py` | Parse isolation, typed requests, transactions, cancellation |
| `test/test_import_data_to_db.py` | List/DataFrame parity and duplicate/null handling |
| `scripts/benchmark_diveroffice_mon.py` | Existing parser benchmark plus optional transformation benchmark |

---

## Task 1: Specify legacy intent and capture the reported regression

**Files:**
- Modify: `test/test_import_logger.py`
- Create: `test/test_import_logger_pipeline.py`
- Modify: `scripts/benchmark_diveroffice_mon.py`

**Purpose:** Separate supported intent from accidental implementation behavior,
then demonstrate the day/month-sensitive latest-date case independently of the
future implementation.

- [ ] Build a behavior matrix covering every format and option. For each row,
  classify the current result as `required intent`, `intent with inconsistent
  implementations`, or `legacy artifact`.
- [ ] Turn only required intent and accepted unified semantics into durable
  assertions. Characterization tests for artifacts may assist migration but
  must be deleted or changed when the new rule lands.

- [ ] Add a focused regression fixture containing canonical timestamps around
  `2025-05-05 14:00:00`, including:
  - `2025-06-01 00:00:00`;
  - `2025-06-04 23:00:00`;
  - `2025-06-05 00:00:00`;
  - `2025-12-04 23:00:00`;
  - `2026-01-01 00:00:00`.
- [ ] Add an end-to-end DiverOffice integration regression generated from the
  `failure2.MON` shape: a last existing row at `2025-05-05 14:00:00`, followed
  by an hourly file through 2026. Assert **Import all data** on and off produce
  the same complete result when the file contains no already-stored rows.
- [ ] Do not add `/home/hsai1/share/failure2.MON` as a test dependency. Extend
  the existing deterministic MON generator or build a compact equivalent in
  the test.
- [ ] Specify and assert intended behavior for:
  - inclusive from/to endpoints;
  - DiverOffice timezone shift relative to the GUI date window;
  - HOBO timezone shift relative to the GUI date window;
  - skip-missing-head behavior;
  - source-column, logger-series, and oldest schemas;
  - regular and Baro CSV export column order, delimiter, and null rendering.
- [ ] Define target-timezone date-window behavior once for every format. Where
  current DiverOffice/HOBO ordering differs, assert the unified rule and
  document that the old discrepancy was an artifact.
- [ ] Extend the benchmark script with an optional transform benchmark using a
  100,000-row canonical frame. Measure date-window mask, timezone shift,
  latest-date cutoff, obsid assignment, and database-boundary normalization.
- [ ] Record baseline production line counts for the three logger modules and
  benchmark medians in the implementation notes or commit message; do not add
  timing assertions to pytest.

**Run:**

```bash
python3 -m pytest \
  test/test_import_logger.py::TestFilterDatesFromFiledata \
  test/test_import_logger.py::TestLoggerImportDiverOfficeSpatialite \
  -q
python3 scripts/benchmark_diveroffice_mon.py --rows 100000 --repeats 5
```

**Checkpoint:** Commit the intent matrix and accepted-behavior tests separately.
Tests that expose the reported bug may be committed as an expected failure only
if repository policy allows it; otherwise keep the failing assertion ready and
make it pass in Task 3 before committing. Do not retain artifact tests as
compatibility requirements.

---

## Task 2: Introduce shared models and canonical frame contracts

**Files:**
- Create: `tools/import_logger/models.py`
- Create: `tools/import_logger/pipeline.py`
- Modify: `tools/import_logger/__init__.py`
- Create: `test/test_import_logger_pipeline.py`

**Interfaces:**

```python
CANONICAL_COLUMNS = (
    "date_time", "head_cm", "temp_degc", "cond_mscm", "baro_cmh2o",
)
METEO_COLUMNS = (
    "obsid", "instrumentid", "parameter",
    "date_time", "reading_num", "unit",
)

@dataclass
class ParsedLoggerFile:
    data: pd.DataFrame
    filename: str
    source_path: str
    kind: LoggerDataKind
    location: str | None
    serial_number: str | None
    source_timezone: str | None = None
    timezone_error: str | None = None

@dataclass(frozen=True)
class LoggerSchemaCapabilities:
    has_series_id: bool
    has_created_at: bool
    has_source_column: bool
```

- [ ] Add `LoggerDataKind`, canonical union-column constants, and the named
  models. Move existing
  request/result/series dataclasses from `workers.py` only when doing so does
  not create a partially migrated circular import.
- [ ] Add `validate_logger_frame(frame)` that checks the one exact canonical
  column set/order, datetime dtype/no `NaT`, numeric measurement dtypes,
  allowed nulls, and unique `RangeIndex`.
- [ ] Add a tiny `empty_logger_frame()` helper that creates the one canonical
  schema with correct dtypes and no header pseudo-row.
- [ ] Define copy ownership: every public pipeline transform returns a new
  frame/model and does not mutate its argument. Add tests proving this.
- [ ] Do not add list conversion helpers to the models or pipeline modules.
- [ ] Export only stable models/constants from `import_logger.__init__`; keep
  private transform helpers module-qualified in tests.

**Run:**

```bash
python3 -m pytest test/test_import_logger_pipeline.py -q
ruff check tools/import_logger/models.py tools/import_logger/pipeline.py \
  test/test_import_logger_pipeline.py
```

**Checkpoint:** Models and invariant tests pass without changing production
callers.

---

## Task 3: Implement the shared DataFrame transformation pipeline

**Files:**
- Modify: `tools/import_logger/pipeline.py`
- Modify: `test/test_import_logger_pipeline.py`
- Modify: `tools/utils/date_utils.py` only if a general typed-date helper is
  genuinely shared outside logger import
- Modify: `test/test_date_utils.py` only if `date_utils.py` changes

**Interfaces:**

```python
def run_pre_resolution_pipeline(
    parsed: ParsedLoggerFile,
    options: LoggerImportOptions,
) -> ParsedLoggerFile: ...
def run_post_resolution_pipeline(
    parsed: ParsedLoggerFile,
    obsid: str,
    latest_dates: Mapping[str, pd.Timestamp | None],
    options: LoggerImportOptions,
) -> PreparedLoggerFile: ...
def normalize_timezone(parsed: ParsedLoggerFile, target: str | None) -> ParsedLoggerFile: ...
def reconcile_transformed_timestamp_collisions(
    before: ParsedLoggerFile,
    after: ParsedLoggerFile,
) -> ParsedLoggerFile: ...
def filter_date_window(data: pd.DataFrame, start, end) -> pd.DataFrame: ...
def drop_missing_water_head(data: pd.DataFrame) -> pd.DataFrame: ...
def assign_obsid(data: pd.DataFrame, obsid: str) -> pd.DataFrame: ...
def parse_latest_dates(snapshot: dict[str, object]) -> dict[str, pd.Timestamp | None]: ...
def filter_after_latest_date(
    data: pd.DataFrame,
    obsid: str,
    latest_dates: Mapping[str, pd.Timestamp | None],
) -> pd.DataFrame: ...
def baro_to_meteo(
    data: pd.DataFrame,
    obsid: str,
    instrumentid: str,
) -> pd.DataFrame: ...
```

- [ ] Implement vectorized timezone shifting on the datetime column. Preserve
  the current file-timezone error information instead of silently assuming an
  offset.
- [ ] Preserve original timestamps and source-row ordinals through
  normalization. Record whether a timezone transformation was actually
  applied; an unchanged/no-op conversion must bypass collision reconciliation.
- [ ] Localize the parsed Series with pandas
  `ambiguous="infer", nonexistent="shift_forward"`. If inference cannot resolve
  an autumn fold, retry with `ambiguous=False` to choose standard time
  deterministically. Neither expected DST condition may fail or skip the file;
  do not hand-code timezone arithmetic.
- [ ] Keep `pd.to_datetime(errors="coerce")` limited to parsing plus an
  immediately inspected invalid mask. Do not use `ambiguous="NaT"` or
  `nonexistent="NaT"`, because either would discard rows before an actual
  transformed destination collision exists.
- [ ] Reconcile only exact naive destination timestamps newly collided by the
  applied transformation. Leave all timestamps untouched when conversion is
  absent or one-to-one.
- [ ] Coalesce each collision group column by column in source order: retain a
  sole non-null value, collapse equal non-null values, and choose the first
  non-null value only when multiple non-null values differ. Never drop an
  entire row before inspecting all measurement columns and never average.
- [ ] Return a non-fatal conflict notice only for genuinely discarded differing
  non-null values. Do not prompt for expected DST adjustments. Invalid timezone
  identifiers and structurally invalid timestamps remain errors.
- [ ] Implement inclusive date-window filtering against already parsed request
  datetimes. Apply it after timezone normalization.
- [ ] Implement missing-head filtering with `dropna` and a reset index.
- [ ] Implement scalar obsid assignment.
- [ ] Normalize the legacy latest-date snapshot once per observation using a
  deterministic year-first parser. Reject/log invalid non-null maxima; do not
  silently interpret them day-first.
- [ ] Implement latest-date filtering as one typed Series/scalar comparison.
  It must not call `to_dates`, `pd.to_datetime` on file rows, or stringify the
  frame.
- [ ] Add the exact 672-row synthetic regression or a full 9,915-row generated
  regression. With cutoff `2025-05-05 14:00:00`, assert every source timestamp
  is retained.
- [ ] Implement Baro reshape with `melt`, mapping parameter/unit columns, and
  null removal. Define deterministic destination order as source row, then
  pressure before temperature, because that makes exported files predictable;
  do not preserve the nested-loop implementation itself. If pandas melt
  column-major order differs, sort with a temporary ordinal and remove it
  before returning.
- [ ] Add the two public pipeline entry points. They call the tested transforms
  in one fixed order for every `ParsedLoggerFile`; callers must not assemble
  their own format-specific sequences.
- [ ] Prohibit parser-name/format checks in `pipeline.py`. Use
  `LoggerDataKind` mapping tables for missing-value and destination policy.
- [ ] Add parameterized cross-kind tests showing that every applicable common
  stage is called once and in the same order.
- [ ] Add DST regressions for:
  - two distinct instants mapping to the same autumn rollback clock timestamp;
  - multiple samples within the repeated hour;
  - no reconciliation when no timezone transformation was applied;
  - no reconciliation when transformation produces no collision;
  - complementary null/non-null rows retaining every available value;
  - equal non-null values producing no data-loss notice;
  - differing non-null values retaining the first and reporting the discarded
    conflict;
  - no removal outside exact destination collisions;
  - a spring-forward nonexistent time being adjusted without failing import.
  Run the assertions against the pandas version supported by the plugin rather
  than mocking localization behavior.
- [ ] Add tests for empty frames, no cutoff, unknown obsid, invalid DB maximum,
  inclusive endpoints, nullable measurements, and non-mutation.

**Run:**

```bash
python3 -m pytest test/test_import_logger_pipeline.py test/test_date_utils.py -q
```

**Checkpoint:** The reported gap is fixed in a pure transform before parser or
GUI migration.

---

## Task 4: Make the generic importer DataFrame-native internally

**Files:**
- Modify: `tools/import_data_to_db.py`
- Modify: `test/test_import_data_to_db.py`
- Modify: `test/test_datetime_parity.py`

**Interfaces:**

```python
ImportData = list[list[object]] | pd.DataFrame

def _as_import_frame(file_data: ImportData) -> pd.DataFrame: ...
```

- [ ] Add one entry adapter that converts the legacy header/list format to a
  DataFrame or defensively copies DataFrame input. Reject duplicate column
  names and non-DataFrame/non-list input with `MidvDataImporterError`.
- [ ] Normalize input immediately in `general_import()` and use DataFrame
  columns/row count thereafter.
- [ ] Replace header indexing and row-number samples with `frame.columns` and
  `frame.iloc`.
- [ ] Rename the internal staging path to reflect DataFrames
  (`dataframe_to_table`/`load_import_frame`) and pass the already normalized
  frame into it. Keep a thin `list_to_table` wrapper only if tests or downstream
  compatibility require it; mark it as legacy and do not call it internally.
- [ ] Preserve the original source-row ordinal in the temporary row-id column
  before in-file duplicate removal.
- [ ] For typed datetime columns, build duplicate keys at second precision
  directly. For legacy string columns, retain `instant_key(value) or value`.
- [ ] At the driver boundary, format datetime columns to canonical seconds and
  replace all pandas null representations with Python `None`.
- [ ] Preserve numeric types rather than converting the whole frame to strings.
- [ ] Keep SQLite `executemany`, PostgreSQL COPY, and `execute_values` fallback.
- [ ] Parameterize representative generic importer tests over equivalent list
  and DataFrame inputs. Cover:
  - normal insert;
  - in-file duplicates;
  - already-in-database duplicates;
  - malformed/raw date fallback;
  - nulls and empty strings;
  - required/missing columns;
  - row-number diagnostics;
  - SQLite and available PostgreSQL paths.
- [ ] Run the entire generic importer test module before migrating logger
  callers.

**Run:**

```bash
python3 -m pytest test/test_import_data_to_db.py test/test_datetime_parity.py \
  -m "not postgis" -q
```

**Checkpoint:** Every old caller still passes lists unchanged, while a typed
logger-shaped DataFrame imports with identical rows and diagnostics.

---

## Task 5: Convert DiverOffice and DiverOffice Baro parsers to typed frames

**Files:**
- Modify: `tools/import_logger/parsers.py`
- Modify: `tools/import_logger/models.py`
- Modify: `tools/import_logger/workers.py` with only the adapter needed for this
  slice
- Modify: `test/test_import_logger.py`
- Modify: `scripts/benchmark_diveroffice_mon.py`

- [ ] Change the successful DiverOffice parser result from a five-tuple to a
  named parsed-file model containing the canonical DataFrame and metadata.
- [ ] Keep source path assignment in the worker if the parser should remain
  path-focused; do not reintroduce positional wrapping.
- [ ] Remove final `strftime`, numeric `str` conversion, `None` conversion,
  header-list construction, and `.values.tolist()`.
- [ ] Return canonical empty frames for valid empty/no-supported-data cases and
  raise `DiverOfficeParseError` for malformed files.
- [ ] Remove `begindate`, `enddate`, `skip_rows_without_water_level`, and
  `interactive` from parser responsibility. The worker/pipeline owns those
  operations.
- [ ] Preserve raw-line validation, right-edge mapping, fallback proof, channel
  metadata rules, decimal comma handling, and strict invalid masks unchanged.
- [ ] Ensure `_strict_frame_conversion` produces explicit canonical column
  names/dtypes and a `RangeIndex`.
- [ ] Make Baro use the same parser core and return the exact canonical union
  schema with `kind=BAROMETRIC`, without any list adapter.
- [ ] Migrate DiverOffice and Baro parser tests from positional list assertions
  to named metadata plus `pandas.testing.assert_frame_equal`, dtype assertions,
  and scalar value assertions.
- [ ] Delete the temporary worker adapter after the worker can carry the model;
  do not support both parser return forms beyond this task.
- [ ] Re-run and compare the existing 100,000-row benchmark. Investigate a
  median above twice baseline or a material memory regression.

**Run:**

```bash
python3 -m pytest \
  test/test_import_logger.py::TestDiverOfficeParser \
  test/test_import_logger.py::TestDiverOfficeBaroParser -q
python3 scripts/benchmark_diveroffice_mon.py --rows 100000 --repeats 5
```

**Checkpoint:** No DiverOffice parser caller or test consumes a five-tuple or
header-bearing measurement list.

---

## Task 6: Convert Levelogger and HOBO parsers to typed frames

**Files:**
- Modify: `tools/import_logger/parsers.py`
- Modify: `tools/import_logger/workers.py`
- Modify: `test/test_import_logger.py`
- Modify: `test/test_import_logger_workers.py`

- [ ] Refactor Levelogger data rows into one source DataFrame after metadata and
  delimiter/header discovery.
- [ ] Parse the combined Date/Time Series once with a format rule appropriate to
  Levelogger input. Validate every non-empty date before shared filtering.
- [ ] Convert level, temperature, and conductivity columns vectorially; apply
  unit factors as Series operations; create missing canonical columns once.
- [ ] Refactor HOBO rows into one source DataFrame. Preserve quoted fields,
  `fix_date` AM/PM/`EM` compatibility, source timezone extraction, location,
  and serial extraction.
- [ ] Keep an unavoidable special-date Series mapping localized and documented;
  remove list construction and per-row measurement conversion.
- [ ] Return the same named parsed-file model and canonical union frame from
  both parsers.
- [ ] Remove tuple/sentinel handling from `LoggerParseWorker`. Expected empty
  and bad-file outcomes use frames and structured exceptions.
- [ ] Migrate parser and parse-worker tests to frame contracts.
- [ ] Add cross-format contract tests proving every supported parser, including
  Baro, produces the exact same columns and dtypes for equivalent fields.
- [ ] Confirm parser methods accept only file/source parsing inputs. Remove GUI
  filters, database state, target timezone, obsid, and destination concerns
  from every parser signature.

**Run:**

```bash
python3 -m pytest \
  test/test_import_logger.py::TestLeveloggerParser \
  test/test_import_logger.py::TestHoboParser \
  test/test_import_logger_workers.py -q
```

**Checkpoint:** Every logger parser returns the same named/typed abstraction;
no parser builds `filedata`.

---

## Task 7: Move timezone and user filters into the shared worker pipeline

**Files:**
- Modify: `tools/import_logger/models.py`
- Modify: `tools/import_logger/pipeline.py`
- Modify: `tools/import_logger/workers.py`
- Modify: `tools/import_logger/importer.py`
- Modify: `test/test_import_logger_pipeline.py`
- Modify: `test/test_import_logger_workers.py`
- Modify: `test/test_import_logger.py`

- [ ] Parse GUI from/to values once while constructing `LoggerParseRequest` and
  store datetime values in the immutable request.
- [ ] After a parser validates a complete file, have the parse worker call, in
  one documented order:
  1. timezone normalization;
  2. conditional, value-aware destination-collision reconciliation;
  3. inclusive user date window;
  4. optional missing-water-head filtering;
  5. invariant validation.
- [ ] Invoke `run_pre_resolution_pipeline()` for every parser result. Do not
  switch on DiverOffice, Levelogger, HOBO, or Baro in the worker.
- [ ] Replace `_shift_file_data()` with the shared frame operation and delete
  its DataFrame reconstruction/string formatting.
- [ ] Move HOBO target conversion out of `fix_date`/parser and through the same
  shared normalization path where possible. Keep format-specific source-zone
  extraction in the parser.
- [ ] Preserve the existing timezone-error user question by carrying structured
  error metadata on the parsed model.
- [ ] Carry non-fatal timezone-conflict notices through the worker result. Log
  only actual discarded differing non-null values; expected DST adjustment and
  lossless coalescing do not prompt or fail the import.
- [ ] Classify a valid frame emptied by user filters as no data for that file,
  not a parse failure.
- [ ] Add tests proving target-timezone window semantics across DiverOffice and
  HOBO and confirming source rows are validated before filters.
- [ ] Remove unused `TzConverter` coupling from parser signatures. Retain only
  GUI state needed to build the request.

**Run:**

```bash
python3 -m pytest \
  test/test_import_logger_pipeline.py \
  test/test_import_logger_workers.py \
  test/test_import_logger.py -m "active or not spatialite" -q
```

**Checkpoint:** Every post-parse date operation uses the same datetime column;
no worker formats or reparses timestamps.

---

## Task 8: Convert obsid resolution and latest-date filtering to frames

**Files:**
- Modify: `tools/import_logger/importer.py`
- Modify: `tools/import_logger/pipeline.py`
- Modify: `test/test_import_logger_pipeline.py`
- Modify: `test/test_import_logger.py`

- [ ] Replace positional `parsed_files` and `parsed_files_with_obsid` structures
  with named parsed-file models.
- [ ] Keep the small `filename/location/obsid` list solely for
  `filter_nonexisting_values_and_ask`; convert its result to a path-to-obsid
  mapping immediately.
- [ ] Assign obsid with the shared scalar-column transform.
- [ ] Read `get_last_logger_dates()` once before any database job when import-all
  is false, normalize that snapshot once, and apply the typed scalar cutoff to
  every accepted frame.
- [ ] Invoke `run_post_resolution_pipeline()` for every resolved frame. Its
  data-kind policy selects destination preparation; importer code must not
  reintroduce format-specific sequences.
- [ ] Delete `filter_dates_from_filedata`, `_get_last_date_str`, their imports,
  and their list-based tests after equivalent pipeline/integration coverage is
  green.
- [ ] Add the full generated `failure2.MON` regression through
  `LoggerImport.start_import()` on an old schema with latest row
  `2025-05-05 14:00:00`. Run with import-all false, reset, then true; assert no
  gaps and identical stored timestamps.
- [ ] Add the same cutoff regression on the current logger-series schema.
- [ ] Preserve the immutable-snapshot overlapping-files regression.

**Run:**

```bash
python3 -m pytest \
  test/test_import_logger_pipeline.py \
  test/test_import_logger.py -m "active or spatialite" -q
```

**Checkpoint:** The logger package contains no date-list extraction or
latest-date reparsing of file rows.

---

## Task 9: Convert database requests and schema metadata assignment

**Files:**
- Modify: `tools/import_logger/models.py`
- Modify: `tools/import_logger/workers.py`
- Modify: `tools/import_logger/importer.py`
- Modify: `test/test_import_logger_workers.py`
- Modify: `test/test_import_logger.py`

- [ ] Change `LoggerDbImportRequest.file_data` to a DataFrame field named
  `frame` and update every request construction/test.
- [ ] Add `LoggerSchemaCapabilities` creation in one helper and replace loose
  booleans.
- [ ] For source-column legacy schemas, add `source` by scalar assignment on a
  frame copy.
- [ ] For series schemas, create the series inside the worker transaction and
  add `series_id`/`created_at` by scalar assignment on a frame copy.
- [ ] Pass the DataFrame directly to `MidvDataImporter.general_import()`.
- [ ] Preserve the post-import series row count and deletion of an empty series.
- [ ] Preserve oldest schemas with neither series nor source.
- [ ] Update worker tests to use `assert_frame_equal` and verify the caller's
  frame was not mutated.
- [ ] Run source-column, oldest-schema, logger-series, rollback, duplicate-only,
  cancellation, SQLite, and available PostgreSQL tests.

**Run:**

```bash
python3 -m pytest test/test_import_logger_workers.py -q
python3 -m pytest test/test_import_logger.py -m spatialite -q
python3 -m pytest test/test_import_logger.py -m postgis -q
```

**Checkpoint:** Logger database jobs contain no header mutation or row loops;
series atomicity remains proven.

---

## Task 10: Vectorize Baro preparation and unify CSV export

**Files:**
- Modify: `tools/import_logger/pipeline.py`
- Modify: `tools/import_logger/importer.py`
- Modify: `tools/utils/file_utils.py` only if a reusable DataFrame CSV writer is
  appropriate
- Modify: `test/test_import_logger_pipeline.py`
- Modify: `test/test_import_logger.py`

- [ ] Replace `_pivot_baro_to_meteo()` and its nested loop with the data-kind
  destination policy tested in Task 3; delete the old helper and list-based
  tests.
- [ ] Build destination-shaped water and meteo frames before choosing export or
  database execution.
- [ ] Accumulate export frames in a list and call one
  `pd.concat(ignore_index=True)` after all successful files. Never concatenate
  incrementally in a loop.
- [ ] Add one DataFrame CSV writer or logger-local export helper that preserves
  current semicolon/UTF-8/header/null/timestamp behavior.
- [ ] Consolidate the duplicated Baro/water save-dialog and export-summary code
  into one completion path.
- [ ] Keep Baro parameter seeding idempotent and only on database imports.
- [ ] Verify export-only mode performs no database writes and still resolves
  observation IDs as currently required.
- [ ] Add byte-level or parsed-CSV equivalence tests for water and Baro exports,
  including multi-file aggregation and nulls.

**Run:**

```bash
python3 -m pytest \
  test/test_import_logger_pipeline.py \
  test/test_import_logger.py -m "active or spatialite" -q
```

**Checkpoint:** Water and Baro share one export path; no logger measurement
list is created for export.

---

## Task 11: Remove obsolete compatibility code and simplify the package

**Files:**
- Modify: `tools/import_logger/parsers.py`
- Modify: `tools/import_logger/pipeline.py`
- Modify: `tools/import_logger/models.py`
- Modify: `tools/import_logger/workers.py`
- Modify: `tools/import_logger/importer.py`
- Modify: `tools/import_logger/__init__.py`
- Modify: logger tests as needed

- [ ] Search production logger code for and remove every obsolete occurrence
  of:
  - `file_data[0]` / `file_data[1:]`;
  - `filedata` header-row construction;
  - `.values.tolist()`;
  - `DataFrame.from_records()` used to reconstruct logger payloads;
  - positional five-tuple parser unpacking;
  - `skip`/`cancel`/`ignore` parser sentinels;
  - row loops whose only purpose is scalar column assignment, filtering,
    reshaping, or export aggregation;
  - duplicate Baro/water completion branches.
- [ ] Search for post-parser checks of parser class, import format, or format
  name. Remove all such checks or replace genuine semantic distinctions with a
  centralized `LoggerDataKind` policy map.
- [ ] Remove stale imports, compatibility comments, and tests that assert the
  deleted representation instead of behavior.
- [ ] Review whether `TzConverter` can be reduced to GUI selection state or
  removed in favor of plain request values.
- [ ] Review every remaining helper: inline one-use trivial wrappers; split only
  functions that still mix parsing, transformation, UI, and database concerns.
- [ ] Run the repository-required simplification skill/review over all changed
  production files.
- [ ] Compare final production LOC, direct row loops, branch count by inspection,
  and conversion-boundary searches to the Task 1 baseline. Explain any retained
  conversion or loop in the design document or code comment.

**Run:**

```bash
rg -n "file_data\[0\]|file_data\[1:\]|filedata|values\.tolist|from_records" \
  tools/import_logger
ruff check --fix \
  tools/import_logger tools/import_data_to_db.py \
  test/test_import_logger.py test/test_import_logger_pipeline.py \
  test/test_import_logger_workers.py test/test_import_data_to_db.py
ruff format \
  tools/import_logger tools/import_data_to_db.py \
  test/test_import_logger.py test/test_import_logger_pipeline.py \
  test/test_import_logger_workers.py test/test_import_data_to_db.py
```

Expected `rg` result: no measurement-payload list conversions. Incidental small
metadata lists must be clearly unrelated to logger readings.

**Checkpoint:** The final architecture has one representation and no temporary
logger adapters.

---

## Task 12: Full verification and documentation closeout

**Files:**
- Modify: design/plan only if implementation discoveries require an explicit
  amendment
- Modify: `metadata.txt` or changelog only if required by repository release
  practice

- [ ] Run focused pure pipeline tests.
- [ ] Run all parser and worker tests.
- [ ] Run the complete logger import module for non-PostgreSQL backends.
- [ ] Run generic importer and datetime parity tests.
- [ ] Run PostgreSQL-marked logger/importer tests when configured.
- [ ] Run the complete test suite in the repository-prescribed order.
- [ ] Run ruff check/format and the repository-required simplification review.
- [ ] Run the 100,000-row parser and transformation benchmarks for five warm
  repetitions on the same machine as baseline.
- [ ] Confirm memory does not retain both full frame and full nested-list copies.
- [ ] Manually smoke-test in QGIS:
  - regular DiverOffice import-all on/off with the reported cutoff;
  - DiverOffice Baro import and export;
  - Levelogger import with unit conversion;
  - HOBO timezone conversion;
  - autumn DST rollback with repeated destination clock timestamps;
  - old database without source/series;
  - source-column database;
  - current logger-series database;
  - cancel during parse and database duplicate lookup;
  - grouped mixed-success summary.
- [ ] Confirm the current primary QGIS plugin symlink was never repointed.
- [ ] Record final architecture/behavior changes and intentional target-timezone
  date-window semantics in the final commit message or changelog.

**Run:**

```bash
python3 -m pytest test/test_import_logger_pipeline.py -q
python3 -m pytest \
  test/test_import_logger.py test/test_import_logger_workers.py \
  test/test_import_data_to_db.py test/test_datetime_parity.py \
  -m "not postgis" -q
python3 -m pytest test/test_import_logger.py test/test_import_data_to_db.py \
  -m postgis -q
python3 -m pytest test/test_create_spatialite_db.py -x
python3 -m pytest test/test_db_utils.py test/test_midvatten_utils_db.py -x
python3 -m pytest test/ -x
python3 scripts/benchmark_diveroffice_mon.py --rows 100000 --repeats 5
ruff check .
ruff format --check .
```

## Final Acceptance Checklist

- [ ] The complete generated `failure2.MON` regression imports without the
  seven 96-hour gaps when latest database data ends at
  `2025-05-05 14:00:00`.
- [ ] Import-all on/off differs only by the documented typed latest-date cutoff
  plus normal database de-duplication.
- [ ] All file timestamps are parsed once and remain datetime dtype internally.
- [ ] All measurements remain numeric internally.
- [ ] No logger measurement list-of-lists or positional parser tuple remains.
- [ ] All parsers implement one protocol and return the exact canonical union
  schema plus named metadata.
- [ ] No source-format identity is consulted after parser selection; every
  frame goes through the same two shared pipeline entry points.
- [ ] All shared transforms are vectorized and independently tested.
- [ ] Timestamp reconciliation runs only after a real timezone transformation
  creates a collision; no-op and collision-free transformations discard
  nothing.
- [ ] Collision groups preserve complementary/equal values and deterministically
  discard only competing non-null values without failing the file.
- [ ] Expected ambiguous and nonexistent DST clock times use pandas'
  documented localization arguments and never break the import.
- [ ] Generic importer list/DataFrame parity is proven.
- [ ] DiverOffice losslessness tests and benchmark pass.
- [ ] Levelogger, HOBO, Baro, encoding, units, and timezone behavior pass.
- [ ] Oldest, source-column, and logger-series schemas pass.
- [ ] Per-file transaction isolation and cancellation pass.
- [ ] CSV export compatibility passes.
- [ ] Production logger code is materially smaller with no duplicated data-flow
  implementations.
- [ ] Full non-PostgreSQL suite passes; PostgreSQL suite passes when available.
