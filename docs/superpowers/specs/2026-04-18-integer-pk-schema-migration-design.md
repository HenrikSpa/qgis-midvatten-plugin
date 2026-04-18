# Integer Primary Key Schema Migration — Design Spec

**Date:** 2026-04-18
**Status:** Draft — under review
**Branch:** ai_test

---

## Context

Midvatten's QGIS layers are affected by a "100-row bug": QGIS truncates the attribute table to 100 rows when it cannot resolve an efficient integer feature ID for a layer. The primary cause is `obs_points` and `obs_lines`, which use `obsid text PRIMARY KEY`. QGIS picks up `obsid` (a text column) as the feature ID, which it cannot page past 100 rows efficiently.

The fix is to introduce `id INTEGER PRIMARY KEY` on the affected tables and demote the current PK to a `UNIQUE NOT NULL` constraint. In SQLite/SpatiaLite, `INTEGER PRIMARY KEY` is a ROWID alias — no extra storage, just a named exposed column.

**Scope:** New databases and databases migrated via the export-to-spatialite path. Existing databases that are not migrated are unaffected.

---

## Option A — obs_points and obs_lines only (Recommended)

### What changes

**`obs_points`**
```sql
-- Before
obsid text PRIMARY KEY

-- After
id    INTEGER PRIMARY KEY AUTOINCREMENT,
obsid text NOT NULL UNIQUE
```

**`obs_lines`**
```sql
-- Before
obsid text PRIMARY KEY

-- After
id    INTEGER PRIMARY KEY AUTOINCREMENT,
obsid text NOT NULL UNIQUE
```

All foreign keys on other tables (`w_levels.obsid → obs_points(obsid)`, etc.) are unaffected — both SQLite and PostgreSQL allow FK references to UNIQUE columns, not only PKs.

### Why this fixes the bug

QGIS layer loading (`tools/utils/layer_build.py`) already falls back through: autodetect → `"obsid"` → `"rowid"`. With `id INTEGER PRIMARY KEY` present, QGIS autodetects `id` as the integer FID and pages the full dataset correctly.

### Import code impact

obs_points imports look up by `obsid` for conflict detection but do not use the heavy composite-PK deduplication path that time-series importers use. The main change needed is that any conflict detection that currently checks `WHERE obsid = ?` remains correct — it's checking the UNIQUE column, not the PK column. Low risk.

### Storage impact

- **SQLite/SpatiaLite:** `INTEGER PRIMARY KEY` is a ROWID alias. Zero extra storage per row. The ROWID already existed as a hidden column; this just names it.
- **PostgreSQL:** `id SERIAL PRIMARY KEY` adds an 8-byte integer per row and a sequence object. Negligible.

### Pros
- Fixes the primary pain point with minimal diff
- No import logic overhaul required
- Easy to test: load obs_points in QGIS and verify full attribute table
- Low blast radius

### Cons
- Rare 100-row bug on composite-PK tables (w_levels, w_qual_field, etc.) remains
- Schema stays partially inconsistent

---

## Option B — Integer PK on all tables

### What changes

Every table that currently has a composite or text PK gets:
- `id INTEGER PRIMARY KEY AUTOINCREMENT` as the new single-column PK
- Old PK columns demoted to `UNIQUE(col1, col2, ...)` or `UNIQUE(col)` constraints

Affected tables (in addition to obs_points/obs_lines):
- `w_levels` — `UNIQUE(obsid, date_time)`
- `w_levels_logger` — `UNIQUE(obsid, date_time)`
- `w_qual_field` — `UNIQUE(obsid, date_time, parameter, unit)`
- `w_qual_lab` — `UNIQUE(report, parameter)` (+ existing `obsid` FK)
- `w_qual_logger` — `UNIQUE(obsid, date_time, instrument, parameter, unit)`
- `w_flow` — `UNIQUE(obsid, instrumentid, flowtype, date_time)`
- `meteo` — `UNIQUE(obsid, instrumentid, parameter, date_time)`
- `seismic_data` — `UNIQUE(obsid, length)`
- `vlf_data` — `UNIQUE(obsid, length)`
- `comments` — `UNIQUE(obsid, date_time)`
- `s_qual_lab` — `UNIQUE(report, parameter)` (+ existing `obsid` FK)
- `zz_interlab4_obsid_assignment` — `UNIQUE(specifik_provplats, provplatsnamn)`
- Lookup tables with text PKs: `zz_staff`, `zz_flowtype`, `zz_meteoparam`, `zz_strat`, `zz_stratigraphy_plots`, `zz_screen_plots`, `zz_capacity`, `zz_capacity_plots`

### Import code overhaul required

`import_data_to_db.py` detects which columns form the "natural key" for deduplication via:
```python
primary_keys = [row[1] for row in table_info if int(row[5])]
```
This reads `PRAGMA table_info`, column 5 = PK flag. With `id INTEGER PRIMARY KEY`, this returns `['id']` — wrong for deduplication of incoming data (new rows don't have an `id` yet).

The fix requires reading UNIQUE constraints instead of (or in addition to) the PK:
- SQLite: `PRAGMA index_list(table)` + `PRAGMA index_info(index_name)` for each UNIQUE index
- PostgreSQL: query `information_schema.table_constraints` + `information_schema.key_column_usage`

The import function is already complex (decomposed into 7 private methods). This adds meaningful new logic.

### Pros
- Eliminates 100-row bug everywhere, including non-spatial attribute tables
- Fully consistent schema
- In SQLite: still just ROWID aliases — zero storage overhead
- PostgreSQL: eliminates ctid reliance (ctid is not stable across VACUUMs)
- Better third-party tool compatibility

### Cons
- Import logic overhaul: deduplication must switch from PK detection to UNIQUE constraint detection — non-trivial across both SQLite and PostgreSQL
- ~13 more tables to change in `definitions/create_db.sql` and the export-to-spatialite schema recreation path
- More surface area for bugs during migration
- Higher testing burden: every importer needs verification

---

## Current schema baseline (reference)

Tables already using `INTEGER PRIMARY KEY` (no change needed):
- `about_db.id`
- `w_logger_series.id`
- `screen.id`
- `tem_data.id`
- `profile_images.id`
- `spatial_history.id`

QGIS layer loading fallback chain (from `tools/utils/layer_build.py`):
```python
_KEY_COLUMN_FALLBACKS = (None, "obsid", "rowid")
```
`None` = autodetect; the fallback fires only for views without a declared PK. For tables, autodetect runs first. Adding `id INTEGER PRIMARY KEY` makes autodetect succeed everywhere.

SpatiaLite geometric views already expose `rowid` explicitly and are registered in `views_geometry_columns` — these are unaffected by either option.

---

## Verification

For either option, after implementation:
1. Create a new SpatiaLite database via the plugin
2. Load `obs_points` as a QGIS layer — confirm all rows appear in attribute table (not capped at 100)
3. Verify import into `obs_points` works: duplicate `obsid` values are rejected, new `obsid` values are inserted
4. Run the test suite: `python3 -m pytest test/ -m spatialite -x`
5. (Option B only) Run import tests for each affected table type

---

## Recommendation

Implement **Option A**. The 100-row bug is overwhelmingly an `obs_points`/`obs_lines` problem. Option B's main cost — reworking import deduplication to use UNIQUE constraints — is substantial and independent enough to be its own task if ever needed.

---

## Review (2026-04-18)

### Premise is obsolete — real root cause is a missing SpatiaLite stats row

The spec attributes the 100-row bug to QGIS picking up `obsid` (text) as the feature ID and failing to page past 100 rows. The actual root cause, confirmed by diagnostic probes against a real problematic DB and documented in commit `9a90835`, is different:

> `geometry_columns_statistics` was missing the row for `obs_points` entirely. In that state, `UpdateLayerStatistics` alone returns 1 but silently refuses to insert — only `RecoverGeometryColumn` (or an explicit INSERT) seeds the row, after which `UpdateLayerStatistics` populates `row_count` and extents.

Note that `9a90835` also explicitly reverts the earlier `c4a1feb` "prime featureCount" hypothesis as ineffective — neither `reloadData`, `updateExtents`, nor `estimatedmetadata=false` lifted `featureCount` off 0 for this DB state. The `LayerSpec` / `GROUPS` refactor from `c4a1feb` is kept; only the fix claim was reverted.

The current fix: `refresh_spatialite_layer_statistics()` in `tools/utils/db_utils/helpers.py`, exposed as a **user-triggered** menu entry ("Fix 100-row attribute-table cap" under Database management). It iterates `geometry_columns`, runs `RecoverGeometryColumn` per column to seed any missing stats row, then `UpdateLayerStatistics` to populate counts. User-triggered because concurrent writers could otherwise surprise each other. Test: `test/test_refresh_spatialite_stats.py`.

This has two implications for the spec:

1. **The FID-detection story is still wrong.** The fallback-chain comment in `tools/utils/layer_build.py:47-51` explicitly notes that `None` (autodetect) handles composite text PKs correctly — the named `"obsid"` / `"rowid"` fallbacks only fire for views without a declared PK. Adding `id INTEGER PRIMARY KEY` does not populate a missing `geometry_columns_statistics` row, so it would not by itself fix the actual bug.
2. **The current fix is manual, not automatic.** Users who haven't run the menu action still hit the bug. That's a legitimate motivation to want a more robust fix — but the robust fix is "seed stats on DB creation / export-to-spatialite" or "run the refresh on layer load", not "change the PK shape". The spec's proposed change doesn't target the true root cause.

**Recommendation:** Drop integer-PK as a 100-row-bug fix. If the manual menu action is unsatisfying, scope the next step as "when should `refresh_spatialite_layer_statistics()` run automatically?" — not a schema migration.

### If pursued for other reasons, the analysis is sound

The spec would need a rewritten motivation section (e.g. third-party tool compatibility, PG `ctid` instability across VACUUMs — which the spec already mentions under Option B, simpler FID semantics for future work). With that re-framed, the rest stands up:

- **Option A vs B trade-off is framed well.** Option B's import-code cost is real: `import_data_to_db.py`'s natural-key detection (`primary_keys = [row[1] for row in table_info if int(row[5])]`) would need to switch to reading UNIQUE indexes via `PRAGMA index_list` + `PRAGMA index_info` on SQLite and `information_schema.table_constraints` on PG. Non-trivial, and adds surface area to an already decomposed 7-method `general_import()`.
- **FK-to-UNIQUE claim is correct** on both backends.

### Gaps worth closing before planning

- **PostgreSQL DDL not shown.** The spec shows `INTEGER PRIMARY KEY AUTOINCREMENT` (SQLite syntax) but not the PG equivalent. PG would need `GENERATED BY DEFAULT AS IDENTITY` (or `SERIAL`, though `IDENTITY` is the modern choice). Since PG users migrate manually, the DDL should be explicit.
- **`AUTOINCREMENT` is a silent choice.** On SQLite, `AUTOINCREMENT` adds a `sqlite_sequence` table and guarantees monotonic non-reuse of IDs — stronger than the default rowid behavior. If rowid reuse is acceptable, drop it; if stability across external tools matters, keep it and say so.
- **Scope reality.** "New databases and databases migrated via the export-to-spatialite path" means existing PG users get no fix until they manually migrate, and existing SpatiaLite users get no fix until they run the export migration. Worth stating plainly.
- **`obs_lines` migration path.** The export-to-spatialite migration (`tools/export_spatialite.py`) is the on-ramp; whether it currently preserves referential integrity while swapping the PK shape on these two tables should be verified, not assumed.

### Bottom line

Solid engineering analysis wrapped around a stale premise. Pause and reconfirm the motivation before writing an implementation plan; if the motivation is re-grounded on tool-compat / FID-semantics rather than the 100-row bug, Option A remains the right level of ambition.
