> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-07-22 · modified: 2026-07-22 · archived: 2026-07-31

# Logger Import DataFrame Refactor — Fresh-Agent Handover

**Date:** 2026-07-22

**Planning base:** `ai_test` at `3d75727`

**Status:** Specification accepted; implementation has not started.

This handover is for an implementation agent with no conversation history.
Read it before touching code, then read the specification and plan completely.

## Kickoff prompt

> Implement the logger-import DataFrame-first refactor in Midvatten. Start from
> current `ai_test` in a new isolated worktree and execute the implementation
> plan in reviewable slices. Read `CLAUDE.md`, this handover, the design spec,
> and the implementation plan completely before editing. Treat the documents
> as the source of truth; preserve legacy intent and safety, not old internal
> APIs or accidental behavior. Begin with Task 1 and keep tests green at each
> checkpoint. Do not attempt the twelve tasks as one unreviewed rewrite.

## Required reading

1. `CLAUDE.md`
2. `docs/superpowers/specs/2026-07-22-logger-import-dataframe-refactor-HANDOVER.md`
3. `docs/superpowers/specs/2026-07-21-logger-import-dataframe-refactor-design.md`
4. `docs/superpowers/plans/2026-07-21-logger-import-dataframe-refactor.md`
5. Current production and tests:
   - `tools/import_logger/parsers.py`
   - `tools/import_logger/workers.py`
   - `tools/import_logger/importer.py`
   - `tools/import_data_to_db.py`
   - `test/test_import_logger.py`
   - `test/test_import_logger_workers.py`

## Mission

Each supported format parser takes a source file and returns the same canonical
typed pandas DataFrame plus named metadata. Parser selection is the final branch
on source format. From that point onward, all files use the same ordered,
vectorized postprocessing pipeline through export/database preparation.

The final logger package must not convert measurement data to header-bearing
lists, rebuild DataFrames, stringify and reparse dates, mutate positional parser
tuples, or implement equivalent postprocessing separately per format.

## Accepted architecture

- Add `tools/import_logger/models.py` with `ParsedLoggerFile`,
  `LoggerDataKind`, schema capabilities, requests/results/notices, and canonical
  columns.
- Add `tools/import_logger/pipeline.py` with pure DataFrame transforms and two
  shared orchestration entry points around the GUI obsid-resolution boundary.
- All parsers return exactly the canonical union columns:
  `date_time`, `head_cm`, `temp_degc`, `cond_mscm`, `baro_cmh2o`.
- Missing measurements are numeric nulls. Dates remain datetime dtype and
  measurements remain numeric until the destination boundary.
- Semantic water/Baro differences use centralized `LoggerDataKind` policies,
  never parser names.
- `MidvDataImporter` accepts legacy lists or DataFrames at one compatibility
  boundary and is DataFrame-native internally. Non-logger callers remain
  compatible.
- Database schema, bulk insertion, per-file transaction atomicity,
  cancellation, parse isolation, and one immutable latest-date snapshot remain.

## Preserve intent, not implementation

Preserve supported formats, units, metadata meaning, user options, database
compatibility, validation guarantees, transaction behavior, and useful
summaries. Do not preserve list layouts, tuple returns, sentinel strings,
parser-specific filters, duplicated GUI branches, incidental row loops, or
inconsistent operation order.

Before converting behavior into a regression test, classify it as required
intent, an inconsistent implementation of shared intent, or a legacy artifact.
The accepted common rule wins over an old inconsistency.

## Reported regression that must be fixed

With an old database whose last logger row is `2025-05-05 14:00:00`, importing
`failure2.MON` with **Import all data** disabled loses day 01 00:00 through day
04 23:00 in June through December 2025. With **Import all data** enabled there
are no gaps. The database was cleared between tests. Data in January through
June 2026 imports normally.

The exact seven-month × four-day × 24-hour signature is 672 rows and is
consistent with reparsing canonical year-first strings using day-first
heuristics before latest-date comparison. For example, `2025-06-01` can become
`2025-01-06` and appear older than the cutoff. Do not depend on the user's
database or `/home/hsai1/share/failure2.MON` in tests; generate an equivalent
hourly fixture.

Relevant old-schema facts supplied by the user:

- no `w_logger_series`;
- no `source` column;
- expression index only:
  `CREATE INDEX ... ON w_levels_logger (obsid, datetime(date_time))`.

The fix is architectural: parse source timestamps once with an explicit
format, retain datetime dtype, and perform latest-date comparison directly.

## Final timezone and DST policy

Use pandas' vectorized APIs:

1. Parse source text with an explicit format. `errors="coerce"` may construct
   an immediately inspected invalid mask; it is not a DST policy and must not
   silently hide malformed input.
2. Only localize/convert when a timezone transformation is actually requested.
3. Use `Series.dt.tz_localize(source_tz, ambiguous="infer",
   nonexistent="shift_forward")`.
4. If `ambiguous="infer"` cannot choose a fold, retry with
   `ambiguous=False`, selecting standard time. Ordinary DST conditions are
   non-fatal and never prompt or abort the file.
5. Convert with `.dt.tz_convert(target_tz)` and remove timezone metadata only
   for the naive database boundary.
6. Reconcile timestamps only if that actual transformation creates an exact
   naive destination collision. No transformation or no collision means no
   reconciliation and no advance row removal.
7. Reconcile a collision column by column in source order:
   - null + value keeps the value;
   - equal values keep the value;
   - differing non-null values keep the first non-null value;
   - never discard a whole row before examining all measurements;
   - never average values.
8. Only genuinely discarded differing non-null values need a concise non-fatal
   log notice. Lossless coalescing and expected DST adjustment need no prompt.

This policy is intentionally tolerant because a one-hour DST discrepancy is
acceptable to the product owner. Invalid timezone identifiers and structurally
invalid timestamp text are different from expected DST behavior.

## Repository/worktree state

- The primary checkout has unrelated untracked `.claude/`, `.swo`, and
  `.logger-import-worktree/`; preserve them.
- The three new planning documents are currently untracked. Ensure they are
  committed or copied into the implementation worktree before relying on
  relative paths there.
- Do **not** reuse `.logger-import-worktree`: its
  `codex/logger-import-diagnosis` branch is clean but at `869c056`, eleven
  logger-related commits behind the planning base, with no unique commits.
- Create a fresh worktree from the current `ai_test`, after verifying that
  `ai_test` has not advanced.
- Never repoint the QGIS plugin symlink. Worktree tests use `_pkgroot` and root
  `conftest.py`.
- Follow `CLAUDE.md`: invoke the required worktree workflow before production
  edits and the required simplification review after code changes.

## Execution guidance

- Start with Task 1's intent matrix and synthetic regression.
- Use vertical, independently testable slices; temporary adapters must be
  removed within the migration task that introduced them.
- Run focused tests continuously and the prescribed full suite at slice
  boundaries.
- Preserve the robust DiverOffice raw-token/layout validation guarantees, but
  freely simplify their implementation if the proof remains covered.
- Do not change database schemas or add per-row SQL.
- Do not introduce parser-specific postprocessing after the parser boundary.
- Do not use `iterrows()`, incremental DataFrame concatenation, or full
  DataFrame/list duplication.

## Readiness

There are no known product decisions blocking Task 1. Choices marked optional
in the plan concern file placement or extraction of genuinely reusable helpers;
they may be resolved locally while keeping the accepted boundaries intact.
If implementation reveals a behavior not covered by the intent matrix, stop
that slice and amend the specification before encoding the behavior in tests.
