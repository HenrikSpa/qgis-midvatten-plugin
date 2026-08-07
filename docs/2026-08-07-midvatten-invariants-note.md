# Midvatten load-bearing invariants

> Source: distilled from Claude memory, 2026-08-07. Background context, not a living spec.

Code and data invariants that look like removable cruft but are load-bearing.
Breaking any of these has caused real bugs or would break downstream users.
Read this before "simplifying" the areas it names.

## `returnunicode()` is an active encoding firewall

`returnunicode()` in `tools/utils/string_utils.py` exists to stop
wrongly-decoded characters (mojibake) from entering users' databases. It is an
active defense, **not** Python-2 migration leftover — despite ~123 call sites
that look like legacy noise.

What it does: passes `str` through unchanged; maps `None` and QGIS `NULL` to
`""`; decodes `bytes` via the cascade utf-8 → cp1252 → iso-8859-1 → ascii; and
recurses into containers.

**Why keep it:** a redundant call on an already-`str` value costs nothing; a
*removed* call on a path carrying `bytes`/`QVariant` can write mojibake into a
user database, which is expensive to clean. The asymmetry means keep-by-default.

**How to apply:** Never bulk-remove call sites, reorder the charset cascade, or
"simplify" the bytes / QGIS-NULL branches. Per-importer encoding lists differ
intentionally (e.g. interlab4 tries utf-16 first) — any consolidation helper
must take the encoding list as a *parameter*, not hardcode one. Any change near
input decoding needs regression tests with å/ä/ö in utf-8 and cp1252 (and utf-16
for interlab4) asserting the exact stored DB strings.

## QGIS `NULL` handling must survive any `returnunicode()` change

QGIS `NULL` is a null `QVariant`, **not** Python `None`, so `x is None` does not
catch it. Without explicit handling, `str(QGIS_NULL)` yields the 4-character
string `"NULL"` instead of `""` — which then flows into `float()` and raises,
and produces spurious dialogs. Removing the "dead" PyQt QVariant branches once
broke exactly this (`test_stratigraphy_missing_h_gs`,
`test_ok_button_generates_html_from_active_layer`).

The correct guard, placed **before** the `isinstance(anything, bytes)` check:

```python
if hasattr(anything, "isNull") and anything.isNull():
    return ""
```

## Read-side code must support multiple schema variants in the wild

Midvatten users run databases created by plugin versions spanning many years and
rarely upgrade unless forced. **Read/display code must handle all schema
variants, not just the current one.** Forcing an upgrade before the plugin works
is bad UX — many users (PostgreSQL DBAs, production DBs) cannot migrate on
demand.

Example: the loggereditor must read at least three shapes of `w_levels_logger` —
very old (no `source` column at all), current (`source` as a direct column), and
new (no `source` column; `source` read via LEFT JOIN to `w_logger_series` on
`series_id`).

**How to apply:** Use the schema introspection in
`tools/utils/db_utils/schema.py` (`get_tables`, `get_table_info`) to detect which
columns/tables exist **before** composing queries, and branch query templates by
detected shape — not by DB version number (version numbers can lie). Write-side
code (importers) may target the current schema only; read-side code must cover
the zoo. Tests should build DBs in each shape via helper fixtures in
`test/utils_for_tests.py`. Applies to every read path touching `w_levels_logger`
(loggereditor, customplot time-series, sectionplot, export) and to `w_qual_logger`.

## Schema upgrades go through export-to-spatialite, never in-place ALTER

- **SQLite/SpatiaLite:** upgrades happen through the **Export to SpatiaLite**
  feature (`tools/export_spatialite.py`, `ExportSpatialite`, invoked from
  `midvatten_plugin.py`). It reads the old DB and writes a new DB on the current
  schema; when a schema changes, the export path is responsible for mapping old
  rows into the new structure (creating linking rows, splitting denormalized
  data, etc.). This *is* the migration.
- **PostgreSQL/PostGIS:** not upgraded automatically. Required DDL permissions
  vary per deployment (many users lack `CREATE TABLE` on the prod DB — the DBA
  has it). Provide a manual SQL upgrade snippet for the DBA and document it; do
  not automate.

**How to apply:** When planning any schema change, describe (1) what
`export_spatialite.py` must do to map old → new on export, and (2) a manual SQL
snippet for PostgreSQL users. Do **not** propose `ALTER TABLE` upgrades against
existing databases. `LOGGER_SERIES_MIGRATION.md` is a worked example of this
pattern.

## `date_time` uniqueness is per normalized second; stored text is exact

For the timestamped tables (`w_levels`, `w_levels_logger`, `comments`, `w_flow`,
`meteo`, `w_qual_field`, `w_qual_logger`) the duplicate rule is: **one row per
obsid (plus any extra key columns) per normalized-second instant, identical on
both backends.**

- `00:00` ≡ `00:00:00` (duplicates); `00:00` ≠ `00:00:01` (distinct — do **not**
  truncate seconds).
- **`date_time` is stored exactly as observed — never padded or canonicalized.**
  Date-only (`2015-06-01`) and unknown-time data keep their precision; padding to
  `00:00:00` fabricates provenance and is rejected. Normalization happens only
  inside the uniqueness check, never in storage. SQLite does this with
  `datetime(date_time)` expression indexes; PostgreSQL needs an equivalent
  `IMMUTABLE midv_to_instant(text)` (returning `NULL` on unparseable input) so it
  normalizes the same way rather than comparing raw text.
- **Malformed dates** stay raw and escape uniqueness (NULL key) on both backends.
- **Keep all seven unique indexes on both backends.** External (non-Midvatten)
  queries extract from these tables and rely on them; they are not redundant once
  they index a normalized expression the raw-text PK lacks.

## loggereditor performance invariants

The loggereditor's performance rework introduced invariants that future edits
must respect (they exist to hold ~200k-row interaction times down):

- **Recarray `date_time` strings are lazy.** `_build_ts_recarray` leaves
  `date_time` empty; only `_fill_ts_date_strings()` fills it. Any new consumer of
  `head_ts` / `level_masl_ts` / `head_ts_for_plot` `.date_time` must call
  `_fill_ts_date_strings()` first.
- **`_buf` mutation contract.** Every `_buf` mutation must go through
  `_history_push` (which bumps `_buf_version`) or the recarray cache goes stale.
  Equal-length value mutations without a version bump plot stale values.
- **The picker artist has no marker.** `logger_artist` is linestyle "none", no
  marker, alpha 0, `picker=5`; picking works by point proximity. Re-adding a
  marker costs ~320 ms per pan frame at 200k rows.
- **Plot x is `datetime64`**, taken from `buf.index.to_numpy()` — never strftime
  strings. The old string→`datestr2num` path cost ~10 s per redraw at 200k rows;
  read artist x via `date2num(get_xdata())` or `get_xdata(orig=False)`.
- **Legend picker lifecycle.** `reset_cid()` reconnects `_legend_picker`;
  exclusive pick modes disconnect it *after* calling reset. New exclusive modes
  must follow the same order.
- **One render per `update_plot`.** `_finish_plot` / `_draw_reference_subplot`
  use `draw_idle()` so draws coalesce; do not add a synchronous `canvas.draw()`
  into the update_plot chain.

## Matplotlib global pyplot/backend state is shared across the whole test run

pytest imports **all** test modules during collection (alphabetically) before
running anything, so a module-level `matplotlib.use()` in any test file flips the
global backend for the entire run. `tools/calculate_level.py` sets
`mpl.use("Qt5Agg")` at import time as a module-level side effect, and production
plotters that use pyplot's global backend (`plt.figure()` + `fig.show()`, e.g.
piper/tsplot/xyplot, and the loggereditor detach-figure button) may depend on it
— so do **not** remove it casually. Code that must create a real Qt window should
reference an explicit Qt backend (e.g. `mpl_compat.qt_backend`) rather than
pyplot's global `_backend_mod`, which a stray `matplotlib.use("Agg")` in some
other test can have swapped out from under it.

## Shared PostgreSQL test DB: concurrent runs cause bogus failures

Every worktree and every concurrently running agent shares one local PostgreSQL
instance for the `@pytest.mark.postgis` tests, and each postgis `setup_class`
runs `DROP SCHEMA public CASCADE; CREATE SCHEMA public;`. Two pytest runs at once
clobber each other's schema mid-run.

The signature is a `psycopg2.errors.UniqueViolation` on `about_db_pkey` during
`setup_class`, with the **set of failing tests changing between identical runs**
and each failing test passing when run in isolation. That pattern means
contention, not a code regression. Before trusting a postgis failure, check for
other agents (`ps aux | grep -iE "claude|codex"` and look for running pytest).
A single green baseline run does **not** disprove contention — only a quiet
machine does. (`POSTGIS_TEST_SETUP.md` documents the DROP-SCHEMA reset mechanism
but not this concurrency hazard.)

## `midv_addons` depends on a specific import surface — never break it

The `midv_addons` repo (`~/dev/midv_addons`) imports a fixed surface of midvatten
modules. Changes in midvatten must not break it. `CLAUDE.md` already states the
headline (the `common_utils` / `midvatten_utils` re-export blocks and the
`db_utils.X` names exist only as this public API and must not be removed); the
contract surface and verification procedure are below.

The surface `midv_addons` imports includes:

- Aggregator modules `midvatten.tools.utils.{common_utils, midvatten_utils,
  db_utils, date_utils, gui_utils}` **including their re-exported names** — e.g.
  `common_utils.MessagebarAndLog / Askuser / returnunicode / rstrip / UsageError
  / pop_up_info`, `db_utils.sql_load_fr_db / sql_alter_db / DbConnectionManager /
  tables_columns / rowid_string / is_distinct_from / is_not_distinct_from`,
  `gui_utils.set_combobox`.
- `midvatten.definitions.midvatten_defs`,
  `midvatten.tools.midvsettings.MidvSettings`,
  `midvatten.midvsettingsdialog.PostgisSettings`,
  `midvatten.tools.utils.layer_specs.LayerSpec`,
  `midvatten.tools.utils.layer_build.build_layer`,
  `midvatten.test.utils_for_tests` (test helpers are public API too).
- `midvatten.tools.import_general_csv_gui.GeneralCsvImportGui`, constructed as
  `GeneralCsvImportGui(iface, ms=..., dbconnection=...)`, with `.show()` and the
  `destroyed` signal.

**How to apply:** Never delete or rename anything on this surface; in-repo callers
may move to source modules, but the re-exports stay. After a slice touching these
modules, run `midv_addons/test/test_midvatten_compat.py` (the purpose-built
guard). That test is hard to run headless from a worktree (it hardcodes another
user's plugin path and can hang on QGIS init). When it cannot run, verify the
contract **statically**: confirm the diff changes none of the contract files
(the aggregator modules, `midvatten_defs`, `utils_for_tests`) and that
`GeneralCsvImportGui.__init__(self, iface, ms, dbconnection=None)` is unchanged.

## Keep `create_markdown_table_from_table` despite zero callers

`create_markdown_table_from_table` in `tools/utils/midvatten_utils.py` has no
in-repo call sites but is **not** dead code — the owner invokes it manually to
generate markdown tables for documentation. Never flag or delete it as unused.
More generally: a zero-caller utility in this repo may be an intentional
manual-use tool; ask before deleting one.
