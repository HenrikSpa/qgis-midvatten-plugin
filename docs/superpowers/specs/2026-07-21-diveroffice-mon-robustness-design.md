# DiverOffice Logger Import Robustness Design

## Problem

The fixed-width DiverOffice `.mon` reader introduced in commit `cd11468`
uses `pandas.read_fwf()` with an inference window capped at 1,000 rows. The
"representative" row prepended to that window is selected by populated-token
count, not by the widest value in each channel. Complete rows normally tie, so
an early row wins.

DiverOffice right-aligns fixed-width measurements. If the inference window
contains `99.900` but a later row contains `100.308`, pandas can infer a field
whose left boundary starts one character too far right. The later value is then
read as `00.308`, and numeric conversion silently changes it to `0.308`. The
same shared reader is used by regular DiverOffice and DiverOffice Baro imports.

Logger imports feed calibration, level calculations, plots, and other
downstream workflows. Silent mutation, loss, duplication, or channel movement
of a measurement is therefore unacceptable.

## Goals

- Parse valid regular DiverOffice and DiverOffice Baro files without depending
  on a sample-sized fixed-width inference window.
- Preserve every raw measurement token exactly until strict numeric conversion.
- Support long files, numeric-width changes, missing values in any channel
  position, and numeric tokens consisting of an optional leading sign, integer
  or decimal digits using `.` or `,`, and an optional base-10 exponent.
- Keep delimited `.mon` and `.csv` inputs compatible while applying the same
  strict validation guarantees.
- Reject an individual file atomically if neither the primary parser nor the
  validated fallback can prove a lossless channel mapping.
- Continue parsing and importing other selected files after a per-file parse or
  database failure.
- Keep the normal import path fast enough for interactive use. A modest
  slowdown is acceptable when required for lossless validation, but a gross or
  order-of-magnitude regression is not.
- Report imported and skipped files clearly enough for a user to continue work
  and repair failed files separately.

## Non-goals

- No database schema changes.
- No changes to Levelogger or HOBO parsing.
- No broad rewrite of the generic CSV importer or `MidvDataImporter`.
- No best-effort salvage of ambiguous rows within a failed file.
- No silent coercion of invalid dates or non-empty measurement text to null.

## Accepted Design

### Format routing

The existing high-level routing remains:

1. Delimited DiverOffice `.mon` and `.csv` files use deterministic CSV parsing.
2. Non-delimited `.mon` files first use a deterministic right-edge parser.
3. If, and only if, the right-edge layout is incomplete without being
   contradictory, a full-file fixed-width fallback is attempted.
4. Every path feeds the same strict validation stage before date filtering,
   missing-head filtering, timezone conversion, or database work.

The fallback is not allowed after the primary parser detects contradictory
structure such as an unexpected extra endpoint or extra token. Those cases are
file errors rather than alternate valid layouts.

### Raw-line preservation and diagnostics

File loading must retain the physical line number and preserve leading and
trailing spaces for data rows. Metadata matching may use stripped views, but
the fixed-width parser operates on the original row text. Data-section record
count, start line, and end marker are retained for validation and error
reporting.

The parser raises a dedicated DiverOffice parse exception containing:

- filename;
- physical line number when the error belongs to one row;
- the offending raw text or token;
- a concise reason;
- both primary and fallback reasons when both safe strategies fail.

### Primary fixed-width parser: stable right edges

The primary parser uses the format's stable right-edge alignment rather than
the variable left edge of a numeric string.

For each data row, a precompiled expression identifies the date/time prefix and
the non-whitespace measurement tokens after it. During a single scan it records
each token's raw text, start, and absolute end position. Stable end positions
collected across the complete file identify physical channel boundaries.

The endpoint set is compared with `[Channel N]` metadata:

- each observed endpoint maps to exactly one physical channel;
- a row may omit a value at a known endpoint, producing `None` for that channel;
- numeric strings may grow leftward without changing their channel;
- no token may overlap the date/time prefix or two channel regions;
- no row may introduce an unexpected endpoint;
- the mapping must be unique before output is produced.

If the observed endpoints cannot establish every required channel but do not
contradict the metadata, the parser records a structured "incomplete layout"
result and permits the fallback. It does not guess which metadata channel an
ambiguous endpoint belongs to.

### Full-file fixed-width fallback

The compatibility fallback runs `pandas.read_fwf()` across the complete data
section. `infer_nrows` covers every data row; there is no 1,000-row cap and no
single synthetic representative row.

Fallback output is provisional. It is accepted only when losslessness checks
prove all of the following before numeric conversion:

- every physical data row produced exactly one parsed row;
- every non-empty raw measurement token appears exactly once and unchanged in
  the corresponding parsed row;
- no parsed non-empty value lacks a raw source token;
- token order and expected channel count are preserved;
- blank fixed-width slots remain null in the correct channel;
- date/time text belongs to the date/time field rather than a measurement.

If the proof fails, the entire file is rejected. Fallback use is logged so
unusual valid layouts remain observable without presenting a blocking warning
to the user.

### Strict shared validation

Delimited, primary fixed-width, and fallback results pass through one strict
validator. Validation occurs on the complete data section before user-requested
date or missing-head filters, so a filter cannot conceal corrupt input.

The validator checks:

- declared data-record count, when present, equals the number of physical data
  rows before filtering;
- every row is consumed exactly once;
- every date/time parses successfully;
- every non-empty measurement token converts successfully with the documented
  decimal-comma normalization;
- parsed channel count and channel order match metadata;
- raw-to-parsed token accounting is exact;
- missing values remain attached to their original channel.

Date and numeric conversion use vectorized pandas operations. Invalid masks are
used to locate and report the first bad physical row; `errors="coerce"` is never
treated as permission to return a null for non-empty invalid input.

### Performance

The normal right-edge path performs one regex scan of each raw row. It stores
the small per-row token/endpoint record gathered during that scan, builds
column arrays directly, and performs date and numeric conversion by complete
columns. It must not use `DataFrame.iterrows()`, per-cell `DataFrame.apply()`,
repeated regex compilation, or per-row database calls.

The full-file pandas inference and its additional proof run only when the
primary layout is incomplete. Normal valid right-aligned files do not pay the
fallback cost.

Before implementation changes, record the current parser's median runtime over
five warm runs of a reproducible synthetic 100,000-row, two-channel `.mon`
file. Run the same benchmark on the same machine after implementation. A modest
slowdown is acceptable because lossless parsing has priority; a median above
twice the baseline requires profiling and optimization before completion. The
benchmark reports times but is not a wall-clock assertion in the normal
unit-test suite, avoiding flaky CI failures.

### Per-file parse isolation

`LoggerParseWorker` catches expected file-level parse/decode failures inside its
file loop. Its finished result carries both successfully parsed files and
structured failures. Cancellation and unexpected worker/programming failures
remain terminal signals rather than being mislabeled as bad input.

One failed file does not remove or invalidate successfully parsed files. If all
selected files fail, no database work begins.

### Per-file database isolation

Each validated file becomes one database import job. Jobs run sequentially so
the current progress dialog and cooperative cancellation model remain intact.
Rows within a file continue to use the generic bulk importer.

Latest-date filtering is completed for every successfully parsed file before
the first database job starts. When **Import all data** is unchecked, every
file in the selected batch is filtered against one immutable snapshot of the
database's per-obsid latest dates. The importer must not recalculate that
snapshot between per-file jobs: an early job containing only a late segment
must not cause an overlapping, fuller file later in the batch to lose the
missing interval. When **Import all data** is checked, no latest-date cutoff is
applied; exact timestamp duplicates are still excluded by the generic bulk
importer.

For water-level imports using the new logger-series schema, creation of the
`w_logger_series` row, assignment of its `series_id`, and bulk insertion of that
file's `w_levels_logger` rows occur on the same worker-owned connection and in
the same transaction. A failure therefore rolls back both metadata and rows;
best-effort cleanup is not the atomicity mechanism. Old-schema imports retain
their per-row `source` column behavior within the same per-file transaction.

For DiverOffice Baro, each file is pivoted independently and inserted into
`meteo` in its own transaction. Required shared `zz_meteoparam` seeding remains
idempotent. A failed Baro job does not roll back successful Baro files.

The importer records each database failure and continues with later file jobs.
Cancellation stops scheduling new jobs and interrupts the active job, whose
transaction rolls back.

### Completion reporting

The final result distinguishes:

- files imported successfully;
- files with no new rows after the user's date/import-all selection;
- files skipped by user choices such as observation-point assignment;
- files rejected during parsing, with concise reasons;
- files rolled back after database failure, with concise reasons.

The message bar presents counts. Detailed filenames and reasons are written to
the log in one grouped summary. Any skipped or failed file is visible; the
operation must not look like an unqualified success. If at least one file
imports, the user can continue working with it while repairing failed files.

## Components and Responsibilities

### `tools/import_logger/parsers.py`

- Preserve physical data-row text and line numbers.
- Implement deterministic endpoint parsing and guarded full-file fallback.
- Provide strict shared DiverOffice validation and structured parse errors.
- Keep the existing public parser return contract for successful files.

Focused private helpers should separate raw data-section extraction, endpoint
mapping, fallback parsing, and losslessness validation. This keeps each unit
testable without splitting the established parser module solely for this fix.

### `tools/import_logger/workers.py`

- Return successful parses and expected per-file failures together.
- Keep cancellation and unexpected worker errors terminal.
- Accept one per-file database job.
- Create logger-series metadata inside the same transaction as that file's row
  import when required.
- Return a structured per-file database success or failure.

### `tools/import_logger/importer.py`

- Assign observation points only to successfully parsed files.
- Build and execute one database job per validated file.
- Continue after expected per-file database failures.
- Preserve bulk insertion within each job.
- Present the grouped completion summary.

### `test/test_import_logger.py`

Add parser and importer regression coverage for both DiverOffice modes,
right-edge and fallback paths, strict rejection, and per-file transaction
isolation.

### `test/test_import_logger_workers.py`

Add worker-level coverage proving parse failures are collected per file,
cancellation remains terminal, and a failed database job rolls back only its
own transaction and logger-series metadata.

### `scripts/benchmark_diveroffice_mon.py`

Provide the reproducible 100,000-row benchmark fixture generator and median
timing runner. It performs no database writes and reports enough environment
information to compare baseline and implementation runs on the same machine.

## Verification Matrix

Parser tests cover:

- regular DiverOffice values crossing `9` to `10`, `99` to `100`, and `999` to
  `1000`;
- the reported `100.308` case after more than 1,000 lower-width rows;
- equivalent DiverOffice Baro width changes;
- the widest value near the end of a long file;
- missing first, middle, and final channel values;
- signed values, decimal commas, and optional base-10 exponents;
- deterministic right-edge success;
- a valid alternate layout accepted through the fallback;
- fallback rejection after truncation, duplication, loss, or channel movement;
- invalid dates, invalid numeric text, extra tokens, inconsistent endpoints,
  ambiguous layouts, and record-count mismatch;
- existing valid delimited `.mon` and `.csv` inputs.

Worker and integration tests cover:

- one malformed file plus one valid file: the valid file remains available for
  import and the malformed file appears in failures;
- one database job failing while another commits;
- rollback removes both rows and logger-series metadata for the failed file;
- two overlapping files for one obsid, where a late-segment file is scheduled
  before a full-period file, produce no gap with either **Import all data**
  setting;
- successful regular and Baro files still use bulk insertion;
- cancellation rolls back the active file and prevents later jobs;
- completion summaries enumerate imported, skipped, and failed files.

Regression verification runs the focused parser and worker tests first, then
the complete logger-import test module, relevant SpatiaLite integration tests,
and finally the full test suite. PostgreSQL-marked tests run when a configured
PostgreSQL test backend is available.

## Success Criteria

- `100.308` is imported as `100.308` regardless of where it occurs in a file.
- No accepted parse can silently alter, lose, duplicate, or move a raw
  measurement token.
- Regular DiverOffice and DiverOffice Baro receive identical integrity
  guarantees.
- A bad file produces no rows or series metadata from that file.
- Other valid selected files still import after a parse or database failure.
- Per-file transaction ordering cannot create gaps between overlapping files
  selected in the same batch.
- The grouped summary makes every failed or skipped file visible.
- The 100,000-row primary-path benchmark remains within twice the recorded
  current median on the same machine; smaller regressions are accepted when
  they are the cost of the approved integrity checks.
- Focused and full regression suites pass without schema changes.
