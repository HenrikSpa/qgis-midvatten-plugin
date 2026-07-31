> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-06-01 · modified: 2026-06-01 · archived: 2026-07-31

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
- New accessor `get_series_translation()` returns a **`translation_dict`-shaped**
  mapping `{file_column_name: ["__series_<db_field>"]}` for each series entry
  whose mapping is non-empty. The key is the same `file_column_name` shape
  `get_translation_dict()` yields (a file-header string or a `StaticValue`); the
  value targets the **carrier** db-name `__series_<db_field>`, never the bare
  field name. Two series entries that point at the same file column merge into one
  list of carriers.

### Import: `GeneralCsvImportGui.start_import()`

Series values must stay aligned with logger rows through date filtering, the
obsid filter, comma/factor conversion, etc. To guarantee alignment, series
values ride along as ordinary extra columns under sentinel ("carrier") names
(`__series_source`, `__series_instrument`, `__series_description`,
`__series_comment`) and are consumed + stripped at the end.

**Why merge into `translation_dict` rather than inject separately:**
`translate_and_reorder_file_data()` rebuilds `file_data` from `translation_dict`
and **drops every column not referenced there**. So a carrier column injected as
a standalone pre-step would be discarded. Instead the carriers are merged into the
main `translation_dict` under their `__series_*` targets, and the *existing*
StaticValue-injection + reorder machinery carries them through for free. Using the
namespaced carrier name as the target (not the bare `source`/`comment`) is exactly
what avoids the `comment` double-map: `w_levels_logger.comment` maps to
`comment`, series comment maps to `__series_comment` — distinct targets, even if
both read the same file column.

1. Read `series_translation = self.table_chooser.get_series_translation()` (empty
   on old schema / non-`w_levels_logger` targets).
2. **Right after** building the logger `translation_dict`, merge each
   `series_translation` entry into it (append carriers to any existing list for a
   shared file-column key). From here the existing pipeline does everything:
   - the StaticValue loop injects a constant carrier column for static series
     fields and sets `translation_dict["__series_<f>"] = ["__series_<f>"]`;
   - `translate_and_reorder_file_data` emits the carrier columns alongside the
     logger columns;
   - carriers are plain text, so comma-to-point, factor, and `date_time`
     reformatting skip them; they ride row-aligned through the obsid filter.
3. Run the existing pipeline unchanged (translate/reorder, comma, factor, strip,
   obsid filter, date reformat) — carriers flow through automatically.
4. Replace `_route_source_to_logger_series()` with
   `_route_series_metadata()` (rename, generalized):
   - If no `__series_*` columns present → return `file_data` unchanged
     (series_id stays absent/NULL).
   - Drop any stray `series_id` column from the CSV with the existing warning
     (cross-DB ids don't translate).
   - Run the **two-pass id-capture** described below to create series rows and
     stamp `series_id` onto each logger row.
   - Keep the existing guards: bail to a plain import (no series rows) if
     `w_logger_series` is missing, if `w_levels_logger` lacks `series_id`, or if
     there is no `obsid` column (warn that series metadata is dropped).
5. `general_import()` is unchanged and never sees the sentinel columns.

### How each logger row gets its `series_id` (two-pass id-capture)

`series_id` is **captured at INSERT time and remembered in a dict** — never
re-queried with a `SELECT`. This is exactly the mechanism today's
`_route_source_to_logger_series()` uses for `(obsid, source)`, widened to the
full tuple. It MUST NOT be degraded into a post-insert lookup query (a `SELECT`
on the series fields cannot distinguish two batches that legitimately reuse the
same metadata, and would reattach to a pre-existing series).

Let `key(row) = (obsid, source, instrument, description, comment)` computed from
the row's `obsid` plus its `__series_*` carrier columns, with `""`/`None`
normalized to `None`.

- **Pass 1 — create series, remember ids.** Hold a `key_to_sid: dict[tuple, int]`.
  Iterate rows; for each `key` not yet in `key_to_sid` (skip rows with no obsid),
  `INSERT INTO w_logger_series (obsid, source, instrument, description, comment)
  VALUES (...)` and immediately capture the new id via
  `db_utils.get_last_insert_id(dbconn)`, storing `key_to_sid[key] = id`. A key
  already present is skipped — no duplicate insert. The entire loop runs inside
  one `dbconn.transaction()`, so the ids are valid and the batch is atomic: a
  mid-loop failure rolls back every series row rather than leaving `key_to_sid`
  pointing at uncommitted ids.
- **Pass 2 — stamp each logger row.** Append a real `series_id` column. Iterate
  rows again; recompute `key(row)` and write `key_to_sid[key]` into the row's
  `series_id` (or `None` when the row has no obsid). Then **remove all
  `__series_*` carrier columns** so `general_import()` only sees real columns.

The id flow is `INSERT → get_last_insert_id → key_to_sid → row`. No `SELECT`
round-trip; it works identically on SpatiaLite and PostgreSQL because
`get_last_insert_id` already abstracts the backend difference. Correctness
depends on the carrier columns staying row-aligned through date filtering and the
obsid filter (step 2/3), so the key recomputed in Pass 2 matches the key used in
Pass 1 for that same row.

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
- **Dropped auto-description (intentional behavior change):** the old
  `_route_source_to_logger_series` always stamped
  `description = "Imported from general CSV"` on every series row. The new routing
  only writes the series fields the user actually mapped; an unmapped `description`
  is `NULL`. This is consistent with decision 5 (series fields fully optional) and
  is the only intentional behavior change for the source-only path. The existing
  backward-compat test does not assert `description`, so it stays green.
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
