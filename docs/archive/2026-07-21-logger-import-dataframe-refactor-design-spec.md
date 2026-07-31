> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-07-22 · modified: 2026-07-22 · archived: 2026-07-31

# Logger Import DataFrame-First Refactor Design

**Date:** 2026-07-21
**Status:** Proposed

## Problem

The unified logger importer uses pandas while parsing, but does not retain a
DataFrame as its working data model. Parsed data is serialized into a legacy
"header row plus data rows" list, reconstructed as a DataFrame for timezone
conversion, serialized again, split into a separate list for latest-date
filtering, reparsed as datetimes, mutated row by row to add database metadata,
and finally reconstructed as another DataFrame by `MidvDataImporter`.

The effective water-level path is:

```text
raw file
  -> parser-specific rows
  -> pandas DataFrame and typed dates/numbers (DiverOffice only)
  -> ISO date strings and numeric strings
  -> [header, row, row, ...]
  -> pandas DataFrame for timezone shifting
  -> [header, row, row, ...]
  -> list of date strings
  -> parsed datetime list for latest-date filtering
  -> row-by-row obsid/source/series mutation
  -> pandas DataFrame in MidvDataImporter
  -> database tuples or PostgreSQL COPY text
```

Levelogger and HOBO build the legacy list directly with parser-specific loops,
so equivalent operations have different implementations and failure behavior.
The Baro path loops over every row and channel to pivot wide readings into
`meteo` rows. CSV export separately rebuilds one header-bearing list across
files.

This repeated loss and reconstruction of type information is unnecessary. It
also makes correctness depend on heuristic date parsing after the parser has
already produced a known canonical timestamp. The reported `failure2.MON`
case demonstrates the risk: when the latest database date is
`2025-05-05 14:00:00`, a day-first interpretation can map `2025-06-01` to
`2025-01-06`, reject days 1-4 of June through December as old, retain day 5,
and retain 2026. That mapping produces the exact observed 672-row gap pattern.

The list representation also obscures ownership. Callers append columns and
values in place, worker request objects carry mutable nested lists, tuple return
positions carry metadata, and tests assert list indexes instead of named data
contracts. These patterns make extensions expensive and make it difficult to
prove that every transform preserved row alignment and data types.

The logger importer currently contains approximately 2,690 production lines
across `parsers.py`, `workers.py`, and `importer.py`, with at least 71 direct
uses of header-row/list slicing or DataFrame/list reconstruction across logger
production and tests. The fixed-width DiverOffice safety logic is necessarily
detailed; the surrounding representation plumbing is not.

## Goals

- Use one typed pandas DataFrame per parsed logger file from successful parsing
  until the database/export boundary.
- Give every format parser the same contract: source file in, one canonical
  frame plus named metadata out. No parser-specific postprocessing is allowed
  after that boundary.
- Run every accepted frame through the same ordered pipeline. Differences such
  as water-level versus Baro destination handling are declarative data-kind
  policies, not format-name branches.
- Parse each timestamp once, retain it as `datetime64[ns]`, and perform every
  date comparison and timezone shift on that typed column.
- Retain measurements as numeric columns with pandas nulls rather than numeric
  strings and a mixture of `None` and empty strings.
- Make file metadata named and typed rather than positional tuple elements.
- Separate file-format decoding from shared logger transformations.
- Apply date-range, timezone, missing-water-level, obsid, latest-date, source,
  series, Baro pivot, export, and database preparation through small,
  independently testable DataFrame operations.
- Preserve all supported DiverOffice, DiverOffice Baro, Levelogger, and HOBO
  formats and the lossless DiverOffice validation guarantees.
- Preserve per-file failure isolation, cancellation, bulk insertion, and
  transaction atomicity.
- Preserve new, source-column, and oldest logger database schemas without a
  schema migration.
- Preserve list-of-lists compatibility for non-logger callers of the generic
  importer while allowing logger imports to pass DataFrames directly.
- Delete compatibility plumbing from the logger package after each caller has
  migrated; do not leave permanent dual representations inside logger code.
- Reduce branching, row loops, positional unpacking, and duplicate export/import
  paths substantially. Line-count reduction is evidence, not the primary goal.

## Non-goals

- No database schema changes.
- No rewrite of the robust DiverOffice right-edge/fallback algorithms except
  where their typed DataFrame output contract becomes simpler.
- No migration of Fieldlogger, Interlab, general CSV, flow, or other generic
  import callers to DataFrames in this project. They continue using the legacy
  input adapter.
- No change to normalized-second duplicate semantics or database uniqueness.
- No parallel database writes; per-file jobs remain sequential.
- No replacement of pandas or the existing database abstraction.
- No attempt to preserve the parser classes' positional five-tuple return API
  as a public interface. It is internal plugin code and will be migrated as one
  refactor.
- No silent salvage of invalid dates or non-empty invalid measurements.

## Legacy Intent and Requirements

The refactor preserves the intent of the existing importer, not its internal
implementation or every accidental behavior. Existing tuple layouts,
list-of-lists payloads, parser arguments, string conversions, operation order,
branch structure, and row ordering where the destination has no ordering
contract are explicitly disposable.

Before implementation, characterization tests must be classified as either:

- **required behavior** because it expresses a supported input, user-facing
  option, data meaning, database contract, or safety property; or
- **legacy artifact** that should be replaced by the simpler documented rule.

When formats currently disagree about an operation that should have one
meaning, the common rule in this specification wins. Tests must assert that
rule rather than fossilize the discrepancy.

### Supported inputs

- DiverOffice fixed-width `.mon` files, including long files, missing channel
  slots, width changes, decimal commas, signs, exponents, and guarded fallback
  layouts.
- Delimited DiverOffice `.mon` and `.csv` files with channel metadata/header
  validation.
- DiverOffice Baro input using the shared DiverOffice parser but mapping
  pressure and temperature to `meteo` parameters.
- Levelogger CSV variants, unit conversion for level and conductivity, location
  lookup, and serial-number lookup.
- HOBO quoted CSV input, AM/PM handling including the existing `EM` variant,
  source timezone extraction, location label, and logger serial extraction.
- UTF-8 first and CP1252 fallback.

### User operations

- Optional inclusive from/to date window.
- Optional removal of rows without water head for water-level formats.
- Optional confirmation/remapping of file location to an existing observation
  ID.
- Optional conversion from a file timezone to the selected logger/database
  timezone.
- **Import all data** bypasses the latest-date cutoff but does not bypass exact
  database duplicate removal.
- With **Import all data** unchecked, every file in one selected batch uses the
  same immutable pre-import snapshot of latest dates.
- Import to database and export to semicolon-delimited UTF-8 CSV.
- Old-schema per-row source, new-schema logger-series metadata, and oldest
  schemas containing neither feature.
- Per-file summaries for imported, no-new-data, skipped, parse-failed, and
  database-failed files.

### Safety and operational behavior

- Complete raw-file validation precedes user filtering, so a date window or
  missing-head option cannot conceal corrupt input.
- One bad parse does not discard other successfully parsed files.
- One database failure rolls back that file and its series metadata but does
  not roll back earlier files.
- Cancellation is terminal for the batch, interrupts the active connection,
  rolls back its transaction, and prevents later jobs.
- Duplicate detection preserves the first in-file row and removes rows already
  stored at the same normalized second and primary key.
- Inserts remain bulk operations; no per-row SQL is introduced.

## Accepted Data Model

### `ParsedLoggerFile`

Add a small models module and make a named object, not a tuple or nested list,
the unit passed between parser, worker, importer, exporter, and database job.
A representative contract is:

```python
class LoggerDataKind(Enum):
    WATER_LEVEL = "water_level"
    BAROMETRIC = "barometric"

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
```

It lives in `models.py` rather than `workers.py` so parsers, pure transforms,
workers, and the UI can share it without circular imports. `kind` describes
the data's meaning and destination; it must not encode the source file format.

Metadata must not be stored in `DataFrame.attrs`; attrs are easy to lose during
copy, concat, melt, and filtering. Data is mutable during a pipeline stage, but
stage boundaries return a frame copy or a replaced model rather than mutating
an object owned by another stage.

### Canonical parser frame

Every parser, including Baro, produces exactly these columns in this order:

| Column | Internal dtype | Meaning |
|---|---|---|
| `date_time` | `datetime64[ns]` | Naive timestamp in the frame's current declared timezone |
| `head_cm` | numeric | Water head in centimetres; missing when the source lacks it |
| `temp_degc` | numeric | Temperature in degrees Celsius; missing when absent |
| `cond_mscm` | numeric | Conductivity in mS/cm; missing when absent |
| `baro_cmh2o` | numeric | Barometric pressure in cm H2O; missing when absent |

This union schema is intentionally small. Absent measurements are created once
as numeric null columns, so the shared pipeline never needs to ask which parser
produced the data. Empty strings are not an internal missing-value
representation.

For `BAROMETRIC`, the destination preparation stage reshapes `baro_cmh2o` and
`temp_degc` with `DataFrame.melt()` and mapping tables into the existing
`meteo` columns:

```text
obsid, instrumentid, parameter, date_time, reading_num, unit
```

Null measurements are dropped after melting; no Python row/channel nested loop
is used.

### Frame invariants

- `date_time` exists, is datetime dtype, contains no `NaT`, and is not the
  DataFrame index.
- The DataFrame uses a unique `RangeIndex` after every row-removing or reshaping
  stage.
- Source order is preserved unless an operation explicitly documents sorting.
- Numeric measurement columns contain numeric values or pandas nulls only.
- Column names are unique and exactly match the canonical parser schema.
- A parser never returns a header-only pseudo-frame. Empty data is represented
  by a frame with the canonical columns and zero rows.
- Invalid non-empty source values raise a structured parse error; they are not
  converted to null and later dropped.
- Logger transformations never stringify `date_time` or numeric measurements.

## Accepted Data Flow

```text
GUI snapshot (immutable request)
  -> parse worker, once per file
       -> decode and extract metadata
       -> parser returns the canonical typed DataFrame + metadata
       -> validate complete raw file
       -> run the common pre-resolution pipeline
            -> normalize source timezone to requested target timezone
            -> apply inclusive user date window
            -> apply the selected missing-value policy
       -> ParsedLoggerFile / failure
  -> GUI obsid resolution (small metadata list only)
  -> take one latest-date snapshot for the selected batch if needed
  -> run the common post-resolution pipeline
       -> assign scalar obsid
       -> apply typed cutoff unless Import all data is selected
       -> prepare destination frame from declarative data-kind mapping
       -> add old-source or series metadata where required by schema
  -> optional concat + CSV export
  -> one DataFrame database request per file
       -> same-transaction series creation where supported
       -> DataFrame-aware generic bulk importer
       -> duplicate removal and insert
  -> grouped summary
```

The only list-of-lists retained in this flow is the small
`filename/location/obsid` structure passed to the existing observation mapping
dialog. Logger measurements never enter that structure.

## Parsing Responsibilities

### Uniform parser protocol

All format parsers implement one protocol equivalent to:

```python
class LoggerParser(Protocol):
    def parse(self, source_path: str) -> ParsedLoggerFile: ...
```

Parser selection is the only place that switches on source format. Once
`parse()` returns, no downstream function receives or tests a parser/format
name. Any downstream distinction must come from named semantic metadata such
as `LoggerDataKind`, never from DiverOffice/Levelogger/HOBO identity.

### File-specific parsers

Parsers are responsible only for:

- decoding and file-structure recognition;
- extracting location, serial number, and source timezone metadata;
- mapping source columns/channels to canonical measurement columns;
- unit normalization;
- complete-file validation and source-line diagnostics;
- returning the exact canonical typed frame plus named metadata required by
  the uniform protocol.

Parsers do not know about:

- GUI from/to selections;
- **Import all data** or database latest dates;
- observation-point assignment;
- database schema variants, source text, series IDs, or created timestamps;
- CSV export;
- progress dialogs or interactive questions.

Expected file problems raise format-specific structured exceptions. Empty
valid files return an empty canonical frame. Sentinel strings such as `skip`,
`cancel`, and `ignore`, positional five-tuples, and parser-level interactive
dialogs are removed.

### DiverOffice

Retain `_SourceLine`, token scanning, deterministic right-edge mapping,
validated fallback, declared-row count checking, metadata/channel agreement,
and strict conversion. These helpers already naturally produce DataFrames.
The final parser stops stringifying its typed columns and stops building
`filedata`. Existing helpers may be retained, replaced, or simplified; only
their lossless parsing and validation guarantees are requirements.

The date parser uses an explicit year-first rule appropriate to DiverOffice
source dates. Numeric conversion continues normalizing decimal commas and
rejecting invalid non-empty tokens.

### Levelogger

Read the data section into one source DataFrame after metadata/header discovery.
Build one date-time Series from the Date and Time columns, parse it once, and
convert available measurement columns vectorially. Apply level and conductivity
unit factors to numeric Series. Preserve current column-name variants and
metadata rules.

### HOBO

Read quoted rows into one source DataFrame after locating the header. The
special AM/PM/`EM` compatibility rule may use a Series mapping helper if pandas
cannot express it safely, but the result is assigned once to the canonical
`date_time` column. Temperature conversion is vectorized. Source timezone is
returned as metadata; the parser does not perform the target conversion.

## Shared Transformations

Add `tools/import_logger/pipeline.py` for pure or nearly pure DataFrame
operations. Keeping these out of the GUI and worker classes makes their order
and contracts directly testable.

Every parsed file enters the same public pipeline functions in the same order.
The pipeline must not switch on parser format. Applicability differences are
expressed by `LoggerDataKind` and schema capabilities, preferably through
small mapping/configuration objects rather than scattered conditionals. The
individual transforms remain separately testable, while orchestration calls
the common pre-resolution and post-resolution entry points so a format cannot
accidentally omit or reorder a stage.

### Timezone normalization

Timezone conversion operates directly on `frame["date_time"]` with a single
timedelta or timezone transform. It never sets the date as an index and never
formats it to text.

The resulting naive datetime values represent the requested target/database
timezone, matching the existing storage convention. An unreadable source
timezone remains a structured `timezone_error` so the existing skip/continue
question can be preserved.

Named timezones can produce repeated local clock timestamps during the autumn
DST rollback. Those readings are distinct instants while timezone-aware, but
the current database schema stores naive local timestamps and cannot represent
two conflicting values under the same observation/date key.

Collision handling is conditional. The pipeline retains both the original
timestamps and source-row ordinals, and reconciles rows only when a timezone
transformation was actually applied **and** that transformation maps multiple
source rows to the same naive destination timestamp. With no transformation,
or with a one-to-one transformation, this stage leaves the frame untouched.

When a transformed destination timestamp collides, combine its rows column by
column in source order:

- zero non-null values remain null;
- one non-null value is retained, regardless of which row contains it;
- multiple equal non-null values retain that value without a conflict; and
- multiple differing non-null values retain the first non-null source value
  and record the later values as discarded conflicts.

Thus complementary rows such as one head reading plus one temperature reading
are coalesced without losing either value. The implementation must not discard
a whole row merely because another transformed row has the same timestamp, and
must not average differing measurements. Only actual competing non-null values
are lost. A concise non-fatal notice may report those discarded conflicts; it
must never prompt the user or fail the import.

DST clock irregularities are expected input conditions rather than application
errors. Use pandas' vectorized localization controls instead of implementing a
custom DST algorithm:

```python
localized = parsed.dt.tz_localize(
    source_timezone,
    ambiguous="infer",
    nonexistent="shift_forward",
)
converted = localized.dt.tz_convert(target_timezone).dt.tz_localize(None)
```

`ambiguous="infer"` uses source order for an autumn repeated hour. If pandas
cannot infer a fold, retry with `ambiguous=False`, consistently choosing the
standard-time occurrence. `nonexistent="shift_forward"` moves a spring gap
timestamp to the nearest valid time. The later collision stage handles any
overlap these choices produce. These adjustments do not abort or skip the
file.

`pd.to_datetime(..., errors="coerce")` is a parsing option, not a DST ambiguity
policy. It may be used to build an invalid-input mask, but `NaT` values must be
examined immediately. Likewise, `ambiguous="NaT"` or `nonexistent="NaT"` must
not be used here: they would discard readings before the pipeline knows whether
timezone conversion creates a destination conflict. Invalid timezone names or
structurally invalid timestamp text remain genuine input errors.

A future schema that stores UTC or an offset could preserve every distinct
rollback instant without reconciliation; that schema change is outside this
refactor.

### User date window

The from/to controls are parsed once when building the immutable request. The
inclusive mask is applied to the normalized target-timezone timestamps.

This intentionally resolves a current inconsistency: DiverOffice currently
applies the GUI range before timezone shifting while HOBO applies it after
conversion. The accepted meaning is that the GUI range refers to timestamps as
they will be stored and displayed in the target/database timezone.

### Missing water head

The shared missing-value stage applies the request's policy to the canonical
columns. For water-level data, "skip missing water level" uses
`dropna(subset=["head_cm"])`; for data kinds without water head it is a
declared no-op. The result is reset to a `RangeIndex`.

### Observation ID assignment

After the existing mapping dialog resolves a file path to an observation ID,
assign the value as one scalar column operation:

```python
frame = frame.assign(obsid=resolved_obsid)
```

No row loop or header mutation is used.

### Latest-date filtering

Rename the concept to `filter_after_latest_dates` internally. The helper
accepts typed frames and a snapshot whose legacy database strings are parsed
once per observation. It compares the typed `date_time` Series to a scalar
cutoff for that file. No file date is reparsed.

The snapshot remains immutable across all files in the selected batch. A
missing observation or unparseable/null database maximum leaves the file
unchanged. An invalid non-null maximum is logged explicitly rather than causing
silent row loss.

`failure2.MON` with cutoff `2025-05-05 14:00:00` is a required regression:
all 9,915 rows survive the latest-date filter, and dates 1-4 of June through
December remain present.

### Baro reshape

Replace `_pivot_baro_to_meteo()` with shared destination preparation based on
`LoggerDataKind`. The Baro mapping uses `melt`, column-to-parameter/unit maps,
and scalar assignment of `instrumentid`; the water mapping selects/renames its
destination columns. Drop only null measurement values. Source-row ordering is
preserved only where it affects diagnostics or an explicit interface contract.

### Export preparation

Water and Baro branches both produce destination-shaped frames. Concatenate
successful frames with `pd.concat(ignore_index=True)`. One CSV writer formats
`date_time` as `%Y-%m-%d %H:%M:%S` at the boundary and preserves the current
semicolon delimiter, UTF-8 encoding, header row, column order, minimal quoting,
and blank representation for nulls.

## Generic Importer Boundary

`MidvDataImporter.general_import()` accepts either the existing list-of-lists
input or a DataFrame. At entry, a small adapter converts legacy input once and
copies DataFrame input defensively. All internal column inspection, row counts,
row samples, in-file deduplication, null normalization, and temporary-table
loading operate on that normalized frame.

This is the only dual-representation compatibility layer. Logger callers pass
DataFrames; existing non-logger callers remain unchanged.

Before sending values to a database driver:

- datetime columns are formatted once as `%Y-%m-%d %H:%M:%S`;
- pandas `NaN`, `NaT`, and `pd.NA` become Python `None`;
- numeric values remain numeric;
- the synthetic temporary row-number column preserves original source order
  for diagnostics;
- in-file datetime duplicate keys use the already typed Series when available
  and retain the current raw-string fallback for legacy inputs.

SQLite `executemany` and PostgreSQL COPY/`execute_values` remain bulk paths.
The normalized-instant destination lookup and supporting expression index are
unchanged.

## Workers and Transactions

`LoggerParseRequest` remains immutable but carries parsed from/to datetime
values rather than strings. `LoggerParseWorker` selects a parser, obtains one
`ParsedLoggerFile`, then invokes shared transforms. It continues collecting expected
per-file failures and treats programming failures and cancellation as terminal.

`LoggerDbImportRequest.file_data` becomes a DataFrame field named `frame`.
`LoggerDbImportWorker` copies the frame before adding series columns. Series
creation, scalar `series_id`/`created_at` assignment, generic import, and the
post-insert non-empty check remain in one transaction on the worker-owned
connection.

No DataFrame is shared for concurrent mutation. Database jobs remain
sequential, and Qt signals continue carrying Python objects.

## Importer/UI Responsibilities

`LoggerImport.start_import()` remains responsible for user interaction and
high-level orchestration only:

- snapshot controls into a request;
- run parse worker;
- present timezone questions and parse failures;
- resolve observation IDs;
- obtain schema capabilities and one latest-date snapshot;
- build destination jobs through shared transforms;
- schedule database jobs or one CSV export;
- report the grouped summary.

Replace positional `parsed_files` and `parsed_files_with_obsid` lists with
`ParsedLoggerFile` objects. Replace duplicated water/Baro accumulation, save-dialog,
and summary branches with one prepared-frame/export path wherever destination
differences do not require separate behavior.

Schema capability detection should be represented by a named immutable object,
for example:

```python
@dataclass(frozen=True)
class LoggerSchemaCapabilities:
    has_series_id: bool
    has_created_at: bool
    has_source_column: bool
```

This replaces three loosely related booleans and makes old-schema tests clearer.

## Error Handling

- Parser errors include filename and source line where available.
- Invalid dates and non-empty invalid numeric values fail the file before any
  user filter.
- Shared transformation errors identify the stage (`timezone`, `date window`,
  `latest date`, `baro reshape`, `export`, or `database`).
- Expected DST ambiguity/nonexistence and resolved transformation collisions
  are non-fatal. Only discarded competing non-null values need a concise
  notice; null/non-null coalescing is not data loss.
- No shared transform uses `errors="coerce"` without immediately checking the
  invalid mask and raising for non-empty invalid input.
- Empty frames after a legitimate user/latest-date filter become `no_new_rows`,
  not parse failures.
- Empty frames because a valid file contains no supported measurements remain
  visible as skipped/no-data outcomes with the existing user-facing intent.
- Database failures retain tracebacks in detailed logs and concise summaries.

## Performance and Memory

- Each file has one canonical DataFrame allocation plus bounded copies at
  explicit stage boundaries.
- Avoid `DataFrame.iterrows()`, per-row DataFrame concatenation, Python nested
  row/channel pivots, and repeated whole-column date parsing.
- Use boolean masks, scalar assignment, `dropna`, `melt`, and one `concat` for
  multi-file export.
- Continue the existing 100,000-row DiverOffice parser benchmark and add an
  end-to-end transformation benchmark that includes timezone shift,
  latest-date filtering, obsid assignment, and database-boundary normalization
  without database I/O.
- Record peak frame memory or at least DataFrame deep memory usage before and
  after. The refactor must not retain both a full list-of-lists and full frame
  for every parsed file.

## Components and Responsibilities

### `tools/import_logger/models.py` (new)

- Shared `ParsedLoggerFile` model and canonical schema.
- Immutable parse and database request/result models.
- Schema capability model.
- Canonical column constants or small schema definitions.

### `tools/import_logger/pipeline.py` (new)

- Frame invariant validation.
- Timezone normalization.
- Inclusive date-window filtering.
- Missing-head filtering.
- Observation ID assignment.
- Latest-date filtering.
- Baro-to-meteo reshape.
- Destination/export formatting helpers.

### `tools/import_logger/parsers.py`

- File decoding, metadata, format-specific extraction, unit normalization, and
  complete raw validation.
- Return canonical typed frames and named metadata.
- Remove GUI filtering, database concerns, stringification, list construction,
  positional result tuples, and sentinel results.

### `tools/import_logger/workers.py`

- Run file parsers and shared post-parse transforms off the GUI thread.
- Carry named frame models in signals and requests.
- Preserve parse isolation, cancellation, and per-file database transactions.
- Add database metadata columns vectorially.

### `tools/import_logger/importer.py`

- GUI snapshot and questions.
- Observation mapping and schema capability discovery.
- One immutable latest-date snapshot.
- Schedule prepared per-file frames for export/import.
- One common completion path.

### `tools/import_data_to_db.py`

- Normalize list or DataFrame input at one entry point.
- Use the normalized DataFrame internally and pass it to bulk temporary-table
  insertion without reconstruction.
- Preserve behavior for every legacy caller.

### Tests

- Parser tests assert named metadata, frame columns, dtypes, values, and nulls.
- Pure pipeline tests cover operation ordering and the reported date regression.
- Worker tests assert frames and transactions rather than header/row indexes.
- Generic importer tests run representative imports once with legacy lists and
  once with equivalent DataFrames.
- Integration tests cover all formats, both import-all settings, export, schema
  variants, failure isolation, and cancellation.

## Migration Strategy

The refactor is performed vertically in small slices while keeping tests green.
Migration adapters may bridge old and new callers, but must never become a
second parser-specific postprocessing path:

1. Inventory legacy behavior, classify intent versus artifact, and add the
   reported regression plus tests for the accepted common semantics.
2. Add shared models and pure DataFrame pipeline helpers.
3. Make the generic importer accept DataFrames without changing logger callers.
4. Convert DiverOffice/Baro parser returns and tests.
5. Convert Levelogger and HOBO parser returns and tests.
6. Move timezone, user filters, obsid, and latest-date logic into the pipeline.
7. Convert database jobs and schema metadata assignment to frames.
8. Convert Baro reshape and CSV export, then unify completion branches.
9. Remove list helpers, tuple adapters, sentinels, and obsolete tests from the
   logger package.
10. Run simplification, performance, and complete regression verification.

Temporary adapters may exist within a single migration task, but no logger-side
list adapter remains at completion. Each task removes the compatibility code it
made obsolete before being considered complete.

## Verification Matrix

### Data contract

- Every parser implements the same input/output protocol and returns the exact
  same canonical columns with a datetime column and numeric measurements.
- Equivalent readings from different formats produce equivalent canonical
  frames, apart from named source metadata.
- Missing optional channels are numeric nulls, not empty strings.
- Frames are independent across files and transformations do not mutate the
  source model unexpectedly.
- Invalid non-empty date/numeric tokens identify the correct file/line.

### Date and timezone behavior

- `failure2.MON` plus cutoff `2025-05-05 14:00:00` retains all 9,915 rows.
- Explicit regression points include June 1, June 4, June 5, December 4, and
  January 1 of the following year.
- Import-all bypasses only the latest-date mask.
- From/to endpoints are inclusive and interpreted in target/database timezone.
- DiverOffice and HOBO apply the same documented timezone/filter ordering.
- DST reconciliation runs only when an actual timezone transformation creates
  a destination timestamp collision.
- Collision groups coalesce null/equal values and retain the first non-null
  value only where two non-null measurements genuinely disagree.
- Ambiguous autumn and nonexistent spring source-local hours use pandas
  `tz_localize` with documented deterministic, non-fatal arguments.
- No post-parser operation reparses frame timestamp strings.

### Format behavior

- Existing DiverOffice losslessness and fallback tests remain.
- Levelogger unit variants and metadata variants remain.
- HOBO AM/PM/`EM`, location, serial, and timezone variants remain.
- Baro wide-to-long output values remain; row order is asserted only if the
  database/export interface makes it meaningful.
- UTF-8/CP1252 fallback remains.

### Database and export

- Equivalent list and DataFrame generic imports yield identical database rows,
  duplicate counts, skipped-row diagnostics, and null handling.
- Oldest, source-column, and logger-series schemas all import correctly.
- Series creation and rows commit or roll back together.
- SQLite and PostgreSQL paths retain bulk behavior.
- CSV output preserves delimiter, encoding, headers, column order, nulls, and
  timestamp text.

### Operations

- One parse failure plus one valid file imports the valid file.
- One database failure does not invalidate prior committed files.
- Cancellation interrupts and rolls back the active job.
- Multi-file latest-date filtering uses one pre-import snapshot.
- Summary categories and file names remain accurate.

## Success Criteria

- Logger measurement data remains a DataFrame from successful parse through
  export/database preparation.
- Parser selection is the last format-specific branch. All subsequent stages
  use the same pipeline and semantic metadata.
- Each timestamp is parsed once and never converted to a list merely to be
  parsed again.
- The reported 672-row gap cannot occur under the latest-date filter.
- Repeated local timestamps created by timezone normalization cannot fail a
  file or reach the database as conflicting keys; complementary values are
  coalesced and only competing non-null values are discarded deterministically.
- No `file_data[0]`, `file_data[1:]`, header-row mutation,
  `DataFrame.from_records(file_data[1:])`, or `values.tolist()` remains in
  `tools/import_logger`.
- Parser returns are named objects, not positional five-tuples or string
  sentinels.
- Latest-date filtering, timezone shifting, missing-head filtering, obsid
  assignment, Baro reshape, and export aggregation each have one shared
  implementation.
- The generic importer has one input-normalization boundary and retains legacy
  caller compatibility.
- DiverOffice safety guarantees, all format behavior, per-file atomicity,
  cancellation, schema compatibility, and summaries remain covered and pass.
- Production logger code is materially smaller and has fewer branches and row
  loops; any remaining loop is justified by source-format parsing rather than
  representation conversion.
