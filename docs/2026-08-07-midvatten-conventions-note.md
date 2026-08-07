# Midvatten coding & workflow conventions

> Source: distilled from Claude memory, 2026-08-07. Background context, not a living spec.

Durable conventions that guide how new code, schema, and tests are written in
this repo. These complement, and do not restate, the rules already in
`CLAUDE.md` (SQL safety, import-from-source-module, test import isolation,
"never change test reference data unless told", user-facing string translation).

## Imports live at module level, never inside functions

Never put `import` / `from ... import` inside a function or method body. All
imports go at the top of the file. This is a PEP 8 rule the owner enforces
explicitly (it was flagged on a plan that placed `from midvatten.tools.utils
import db_utils` inside a `show()` method). If a method needs another module,
add the import to the file's top-of-module block, not the method.

This is a separate rule from the `CLAUDE.md` guidance about *which* module to
import from (source modules, not the `common_utils`/`midvatten_utils`
aggregators).

## Don't add soft-delete / "active" flags by default

When designing new tables, do not add `active` / `archived` / `retired`
boolean state columns by default. If a record is no longer wanted, users should
delete it (with appropriate FK cascade), not toggle a flag.

**Why:** State flags create maintenance burden — users must remember to toggle
them, every UI has to filter by them, and the "soft-deleted" state rarely adds
value. The owner rejected an `active INTEGER DEFAULT 1` column on
`w_logger_series` on exactly this ground: a retired series should be deleted to
save space, and making users babysit a flag is bad UX.

**How to apply:** Only add a status column when it captures a concrete invariant
that hard-delete cannot (e.g. a row that must survive for FK integrity but be
hidden from dropdowns). For "show recent only" UI filtering, sort by `id DESC`
/ `created_at DESC` and cap the list length instead of inventing a flag. If a
cascade delete would destroy data the user might still want, question the
cascade rather than adding a flag to work around it.

## Free-text provenance is never a uniqueness or match key

User-typed free-text fields such as `w_levels_logger.source` (and comparable
provenance strings for staff, instruments, etc.) are non-unique **by design**.
Users intentionally reuse the same source text across distinct series — it
describes where data came from, not which series it belongs to. (The
`LOGGER_SERIES_MIGRATION.md` doc states this specifically for `source`; the
general rule below applies to all such fields.)

**Rule:** Never auto-match or dedupe against free text. Match only on explicit
integer ids. Grouping/matching logic should default to creating a new group per
import event and only append to an existing group when the user explicitly picks
it from a dropdown (by id). If you find yourself writing `WHERE source = ? AND
active = 1` to "find the right series", stop — that is the anti-pattern. For CSV
imports specifically, each `(obsid, source)` group must become a *new* series so
a bad import stays revertible; reusing an old series merges new data in and
destroys that revert handle.

## New schema features are optional-but-beneficial, never mandatory

New linkage columns added to existing tables should be **nullable**, not
`NOT NULL`. Users who opt in through the plugin UI or the general CSV importer
get the benefit; users doing direct SQL (`INSERT INTO w_levels_logger ...
SELECT ... FROM temp_csv`) keep working with the new column `NULL` and simply
don't get the new grouping/feature.

**Why:** Forcing users to learn a new multi-step SQL idiom just because a feature
shipped is bad UX ("Adding 'features' that clashes with your workflow is bad UX.
Optional, but beneficial."). The schema change must be additive from the
existing workflow's perspective. `w_levels_logger.series_id` is the canonical
example (see `LOGGER_SERIES_MIGRATION.md`): nullable FK, direct-SQL inserts
without it still work.

**How to apply:** Default new FK columns to NULL-allowed unless there is a hard
data-integrity reason otherwise. Downstream tools (loggereditor, plotters,
exporters) must handle NULL linkage gracefully — show "unassigned" or skip
grouping, never crash. Write a test that confirms a direct-SQL insert without the
new column still succeeds. Batch/revert operations only working for opted-in rows
is acceptable — document it, don't force adoption.

## Schema evolution: solve the real pain points additively, not via a rewrite

The standing architectural stance is to evolve the Midv 1.0 schema **additively**
rather than to start a "midv20" rewrite. The rewrite was only ever motivated by a
short list of concrete pain points, so solving those in place removes the reason
to rewrite. When planning schema work, prioritize these drivers and don't spend
effort on midv20-only wins that none of them require:

1. **Per-series logger metadata.** `w_levels_logger` historically repeats
   `source` on every row with no row-per-series for import date / series comment /
   source, which makes bad imports hard to revert. This is what the nullable
   `w_logger_series` / `series_id` linkage (see the optional-features section and
   the multi-schema invariant) addresses.
2. **Renaming an `obsid` is hard.** `obsid` is a TEXT primary key and the FKs
   carry no `ON UPDATE CASCADE`, so renames need a dedicated tool (and are harder
   on PostgreSQL). Cascade-on-update would make renames trivial but requires a
   migration handled the export-to-SpatiaLite way.
3. **`obs_points.screen` is a single string.** A separate multi-filter table is
   needed so SectionPlot can plot individual filter levels — long blocked by
   "we're about to do midv20".
4. **`obs_points.type` is heterogeneous free text.** A `zz_obs_point_type` lookup
   would let QGIS symbology branch cleanly on well type.

Parameter translation is **not** a driver — it ships as a separate plugin and
works well; do not cite it as a reason for a schema rewrite.

## Choose message style by intent; instructional popups are a UX smell

Do not blanket-migrate `QMessageBox` to `MessagebarAndLog`. Classify each
user-message site by intent:

1. **Decision required** (confirm a destructive action, choose an option) → modal
   `QMessageBox` is correct, because the program cannot proceed without an
   answer. Route through the `dialog_utils` helpers for uniformity.
2. **Outcome report** (success, non-blocking failure) → `MessagebarAndLog`, so it
   is logged and searchable.
3. **Instructional popup** ("you must first do X") → a UX smell. "The user should
   not have to read the message boxes to understand the next step." Redesign
   instead: disable the action until preconditions hold (with a tooltip
   explaining why), validate inline, or put the remedy on a dialog button rather
   than in prose. The `midvatten_plugin.py` `_dispatch` precondition checks that
   block a tool from opening with a clear reason are the good in-repo pattern.

**Why:** The message bar is easy to miss, so a modal is right when user attention
is mandatory — but needing a popup to *explain the workflow* means the UI design
is leaking the next step into prose.

## Testing conventions

**Integration tests exercise the user-facing flow.** Lead with a test that drives
the full trigger path the user actually takes — `show()` / the OK button /
`_run_report()` — with a mocked `iface` and a real/realistic QGIS layer plus
selected features, and assert the real outcome (e.g. the HTML file is created
with the right content). Don't settle for calling `get_data()` or
`write_html_report()` in isolation; helper-method unit tests are welcome but
secondary. "Widgets the user interacts with should do what we expect."

**Run targeted tests between slices; run the full suite only at checkpoints.**
The full `pytest test/` run takes several minutes (longer with PostGIS). Between
small localized changes, run only the test file that exercises the changed code
(find it by grepping `test/` for the function name) — usually under a minute.
Reserve the full suite for natural checkpoints: before requesting review / opening
a PR, at the end of a multi-slice sprint, or when a targeted test fails
unexpectedly and you need to know whether it is isolated.
