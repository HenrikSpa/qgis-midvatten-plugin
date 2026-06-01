# General CSV import — logger-series metadata section

**Date:** 2026-06-01
**Status:** Design approved, pending spec review
**Area:** `tools/import_general_csv_gui.py`, `tools/import_data_to_db.py` (read-only), tests

## Problem

`w_logger_series` (id, obsid, source, instrument, description, comment) holds
batch-level metadata for `w_levels_logger`; each logger row links back through
`w_levels_logger.series_id`. The general CSV import GUI can already populate
`source` when importing to `w_levels_logger`: `load_gui()` injects a *virtual*
`source` column into the `w_levels_logger` chooser, and
`_route_source_to_logger_series()` creates one `w_logger_series` row per distinct
`(obsid, source)` group, rewriting the virtual `source` value into the real
`series_id` before insert.

That only covers `source`. Users need to set the rest of the series metadata
(`instrument`, `description`, `comment`) at import time, mapped from CSV columns
or static values, exactly like the regular destination columns.

## Goal

When the import target is `w_levels_logger` **and** the database carries the new
schema, show a dedicated "Logger series metadata (w_logger_series)" block at the
bottom of the column-chooser grid. It exposes `source`, `instrument`,
`description`, and `comment`, each mapped with the same controls as a normal
column (file-column dropdown or static value). On import, the mapped values
create/reuse `w_logger_series` rows and tag each logger row with the right
`series_id`.

## Decisions (from brainstorming)

1. **Fields exposed:** `source`, `instrument`, `description`, `comment` — every
   editable `w_logger_series` field. `id` is auto; `obsid` is taken from each
   logger row, not mapped separately.
2. **Series identity:** one `w_logger_series` row per distinct
   `(obsid, source, instrument, description, comment)` tuple. This generalizes
   today's `(obsid, source)` grouping. When the extra fields are static (the
   common case — one deployment = one set of metadata), the tuple collapses back
   to `(obsid, source)`, preserving current behavior exactly.
3. **`source` relocation:** remove the virtual-`source` injection from
   `w_levels_logger`; `source` now lives only in the series block. Single home
   for series metadata, no double-mapping.
4. **UI layout:** same column grid, divided by a horizontal line and a
   "Logger series metadata (w_logger_series)" sub-header, then one row per series
   field rendered with the existing `ColumnEntry` widgets.
5. **Empty mapping:** if no series field is mapped, no `w_logger_series` row is
   created and logger rows import with `series_id = NULL` (valid, as for direct
   SQL inserts). Series metadata is entirely optional.

## Schema gating (multi-schema compatibility)

The series block appears **only when both**:
- `w_logger_series` exists in the DB, **and**
- `w_levels_logger` has a `series_id` column.

On the old schema neither holds: `source` is still a real `w_levels_logger`
column and shows up as a normal chooser row, unchanged. Detection uses the same
introspection already in `load_gui()` (`has_series_id`,
`"w_logger_series" in self.tables_columns_info`).

## Design

### The `comment` / shared-name collision (why a separate list)

`comment` exists in **both** `w_levels_logger` and `w_logger_series`. The current
source routing works because `source` is unique to the series table after the
move. If series fields were folded into the shared `translation_dict` keyed by
bare column name, mapping both the logger `comment` and the series `comment`
would produce `["comment", "comment"]` — indistinguishable downstream — and
`ColumnEntry`'s prefill (`file_column_name = self.db_column`, line 944) would make
a series `comment` entry silently grab any file column named `comment`.

Therefore series entries are kept **out of `translation_dict` entirely**, in a
separate list, and carried to the routing step under sentinel column names that
cannot collide with real columns.

### UI: `ImportTableChooser`

- Add `self.series_columns: list[ColumnEntry]` alongside `self.columns`.
- In `choose_method()`, after building the normal `self.columns` rows, if the
  target is `w_levels_logger` and schema gating passes:
  - append a full-width separator (`get_line()`) and a bold
    `QLabel("Logger series metadata (w_logger_series)")` spanning the grid,
  - for each of `source, instrument, description, comment`, build a `ColumnEntry`
    from the corresponding `w_logger_series` column-info tuple and append its
    widgets to the same `RowEntryGrid`, collecting the entry into
    `self.series_columns`.
- Series `ColumnEntry`s reuse all existing behavior (file-column dropdown, static
  value, prefill). All four series fields are nullable, so the not-null guard
  never fires. The `factor` widget stays hidden for these text columns.
- `load_gui()` **no longer injects** the virtual `source` column into
  `w_levels_logger`.
- New accessor `get_series_translation()` returns
  `{db_field: file_column_name}` for each series entry whose mapping is non-empty,
  where `file_column_name` is either a file-header string or a `StaticValue`
  (same shape `get_translation_dict()` already yields).

### Import: `GeneralCsvImportGui.start_import()`

Series values must stay aligned with logger rows through date filtering, the
obsid filter, comma/factor conversion, etc. To guarantee alignment, series
values ride along as ordinary extra columns under sentinel names
(`__series_source`, `__series_instrument`, `__series_description`,
`__series_comment`) and are consumed + stripped at the end.

1. Read `series_translation = self.table_chooser.get_series_translation()` (empty
   on old schema / non-`w_levels_logger` targets).
2. **Before** `translate_and_reorder_file_data`, inject one sentinel column per
   mapped series field into `file_data`:
   - `StaticValue` → constant value in every row;
   - file-column name → copy that file column's values per row.
   This mirrors the existing `StaticValue`/`Obsids_from_selection` injection loop.
   Sentinel columns are plain text, so they are untouched by comma-to-point,
   factor, and `date_time` reformatting; they survive row filtering because they
   are real rows-aligned columns.
3. Run the existing pipeline unchanged (translate/reorder of the *logger*
   columns, comma, factor, strip, obsid filter, date reformat).
4. Replace `_route_source_to_logger_series()` with
   `_route_series_metadata()` (rename, generalized):
   - If no `__series_*` columns present → return `file_data` unchanged
     (series_id stays absent/NULL).
   - Drop any stray `series_id` column from the CSV with the existing warning
     (cross-DB ids don't translate).
   - Group rows by `(obsid, source, instrument, description, comment)` using the
     sentinel columns (empty string / None normalized to `None`). Skip rows with
     no obsid. In one transaction, `INSERT INTO w_logger_series
     (obsid, source, instrument, description, comment) VALUES (...)` once per
     distinct tuple, recording `key -> series_id`.
   - Append a real `series_id` column, fill each row from its tuple's id (or
     `None` if the row had no obsid), and **remove all `__series_*` columns**.
   - Keep the existing guards: bail to a plain import (no series rows) if
     `w_logger_series` is missing, if `w_levels_logger` lacks `series_id`, or if
     there is no `obsid` column (warn that series metadata is dropped).
5. `general_import()` is unchanged and never sees the sentinel columns.

### Data flow

```
chooser ──► translation_dict (logger cols only)
        └─► series_translation (source/instrument/description/comment)
                    │
start_import: inject __series_* carrier columns into file_data
                    │
   existing pipeline (translate logger cols, comma, factor, strip,
                      obsid filter, date reformat)  ── carriers ride along
                    │
   _route_series_metadata: group by (obsid + 4 fields) → INSERT w_logger_series,
                           append series_id, strip __series_* columns
                    │
   general_import(dest_table="w_levels_logger", file_data with series_id)
```

## Error handling / edge cases

- **Old schema:** gating fails → no series block, `source` is a normal column,
  behavior identical to before this change.
- **No series field mapped:** no carrier columns injected → `_route_series_metadata`
  is a no-op → `series_id` NULL.
- **`source` mapped but no `obsid` column:** existing warning path; series
  metadata dropped, logger rows import with NULL series_id.
- **Stray `series_id` in CSV:** dropped with the existing warning.
- **Orphan series (pre-existing, out of scope):** routing commits series rows in
  its own transaction before `general_import`; rows rejected *inside*
  `general_import` (e.g. PK conflict) could leave a childless series row. This
  already exists for `source` today and is not addressed here. Noted only.

## Testing

- **Preserve** `test_import_w_levels_logger_with_source_routes_to_series`
  (backend test): its DB-state assertions are the backward-compat proof and must
  stay green. Only its *GUI setup* changes — the `source` mapping now targets the
  series block instead of the removed virtual column. This is an allowed UI
  adaptation, **not** a forbidden reference-data change; the resulting DB state is
  identical.
- **New backend tests** (`@pytest.mark.spatialite` + `@pytest.mark.postgis`,
  mirroring the existing parametrized style):
  - source + instrument + description as static values → one series row per
    obsid with all metadata populated; every logger row carries its series_id.
  - mixed: source from a file column, instrument static → distinct series per
    distinct source within an obsid; static instrument shared.
  - series `comment` mapped alongside logger `comment` mapped to a different file
    column → both land in their own table, no cross-contamination (the collision
    regression guard).
  - no series field mapped → logger rows import with `series_id` NULL, zero
    `w_logger_series` rows created.
  - old schema (no `w_logger_series` / no `series_id`) → `source` imports as a
    normal column, no series block, no errors.
- **GUI-level test** (lighter, mocked): selecting `w_levels_logger` builds the
  series block with four entries; selecting another table does not.
- Lead with the user-facing `show()`/`start_import()` flow per project testing
  conventions; print `mock_messagebar.mock_calls` before assert groups.

## Out of scope

- `w_qual_logger` series (a separate follow-up plan already noted in the schema
  comment).
- Editing existing series (that is `loggereditor`'s job).
- Any schema change — none required; all columns already exist.
