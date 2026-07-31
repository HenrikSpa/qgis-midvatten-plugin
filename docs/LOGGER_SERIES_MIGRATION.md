# Logger series — upgrade and direct-SQL reference

This document covers two things that come up when moving to the new
`w_logger_series` schema (DB version `1.10.0` and later):

1. How to upgrade an existing database to the new schema.
2. How to use the new schema from direct SQL (spatialite_gui, psql, or
   any other SQL client) without going through the Midvatten plugin.

For the design rationale behind the new schema, see the archived planning
docs under `docs/archive/` — notably
`docs/archive/2026-04-17-instrument-serial-import-design-spec.md` and
`docs/archive/2026-06-01-general-csv-logger-series-metadata-design-spec.md` —
and `/home/hsai1/dev/midv20/midv20/docs/schema-analysis-midv1-vs-midv20.md`.

## What changed in the schema

* New table `w_logger_series (id, obsid, source, instrument,
  description, comment)`. Each row represents one logger deployment or
  one discrete import batch; the batch-level metadata that used to be
  repeated on every `w_levels_logger` row lives here now.
* `w_levels_logger` gains:
  * `series_id INTEGER` (nullable) — foreign key to
    `w_logger_series(id)`, `ON DELETE CASCADE`
  * `created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP` — stamped when
    the row entered the database
* `w_levels_logger.source` is removed; `source` now lives on
  `w_logger_series`.

`series_id` is nullable by design: rows inserted by direct SQL without
creating a series keep working exactly as they do today. Series-level
features (batch revert, shared metadata) only apply to rows that opted
in.

## Upgrading an existing SpatiaLite database

Use the plugin's **Export to SpatiaLite** feature (Database menu). It
creates a fresh DB on the current schema and copies your data into it.
During the copy, the old `w_levels_logger.source` column is mapped to
new `w_logger_series` rows: one series per distinct `(obsid, source)`
pair, with `description = "Upgraded from Midv 1.x"`. Rows in the new
DB link to those series via `series_id`. `created_at` is the default
(the export timestamp) — the original import time is not recoverable.

After the export, point QGIS/Midvatten at the new `.sqlite` file and
archive the old one.

## Upgrading an existing PostgreSQL/PostGIS database

Midvatten does not automate PostgreSQL upgrades because schema DDL
permissions vary per deployment. A DBA (or a user with the required
permissions) should run this SQL:

```sql
BEGIN;

-- 1. Create the new table. No need to prefix with schema in the common
-- case; adapt if you run Midvatten in a non-default schema.
CREATE TABLE w_logger_series (
  id serial PRIMARY KEY,
  obsid text NOT NULL,
  source text,
  instrument text,
  description text,
  comment text,
  FOREIGN KEY (obsid) REFERENCES obs_points(obsid) ON UPDATE CASCADE
);
CREATE INDEX idx_wlogger_series_obsid ON w_logger_series(obsid);

-- 2. Populate one series row per distinct (obsid, source) pair.
INSERT INTO w_logger_series (obsid, source, description)
SELECT DISTINCT obsid, source, 'Upgraded from Midv 1.x'
FROM w_levels_logger;

-- 3. Add the new columns on w_levels_logger.
ALTER TABLE w_levels_logger
  ADD COLUMN series_id integer REFERENCES w_logger_series(id) ON DELETE CASCADE,
  ADD COLUMN created_at text NOT NULL DEFAULT CURRENT_TIMESTAMP;
CREATE INDEX idx_wlvllogger_series ON w_levels_logger(series_id);

-- 4. Link each existing row to its new series. IS NOT DISTINCT FROM is
-- the NULL-safe comparison; it matches rows where both sides are NULL.
UPDATE w_levels_logger l
SET series_id = s.id
FROM w_logger_series s
WHERE s.obsid = l.obsid
  AND s.source IS NOT DISTINCT FROM l.source;

-- 5. Drop the legacy column. Skip this step if you want to keep the
-- old column around as dead metadata during a transition period.
ALTER TABLE w_levels_logger DROP COLUMN source;

-- 6. Update the recorded DB version. The exact row depends on how
-- about_db is populated on your installation; adjust the WHERE clause
-- accordingly, or re-create the DB with the plugin to refresh it.
UPDATE about_db
SET description = REPLACE(description, 'version 1.9.0', 'version 1.10.0')
WHERE description LIKE '%version 1.9.0%';

COMMIT;
```

Test against a backup first. This migration is additive except for the
column drop in step 5; keeping the source column around for a while
costs little and gives you a fallback.

## Direct-SQL inserts against the new schema

### The simple case — `series_id` optional

Nothing changes. Inserts that omit `series_id` still work; the row has
`series_id = NULL` and does not participate in series-level features.

```sql
INSERT INTO w_levels_logger (obsid, date_time, head_cm)
VALUES ('MW-01', '2026-04-17 08:00:00', 120.5);
```

### Opting in to series tracking

To get batch-revert and shared metadata for a bulk SQL load, create one
`w_logger_series` row per logical batch and tag the rows that belong to
it. Typical pattern after loading a CSV into a temp table:

```sql
-- 1. Create one series row per distinct (obsid, source) in the CSV.
INSERT INTO w_logger_series (obsid, source, description)
SELECT DISTINCT obsid, source, 'Direct SQL import 2026-04-17'
FROM csv_temp;

-- 2. Insert the data rows, joining back on (obsid, source) to pick up
-- the right series_id. The description literal disambiguates from any
-- pre-existing series that happen to share the same (obsid, source).
INSERT INTO w_levels_logger
  (obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment, series_id)
SELECT
  c.obsid, c.date_time, c.head_cm, c.temp_degc, c.cond_mscm,
  c.level_masl, c.comment, s.id
FROM csv_temp AS c
JOIN w_logger_series AS s
  ON s.obsid = c.obsid
 AND (s.source = c.source OR (s.source IS NULL AND c.source IS NULL))
 AND s.description = 'Direct SQL import 2026-04-17';
-- created_at is populated by the column default.
```

Reverting that batch is then one DELETE:

```sql
DELETE FROM w_logger_series WHERE description = 'Direct SQL import 2026-04-17';
-- Cascades to w_levels_logger rows with matching series_id.
```

### Merging two series after the fact

If you re-imported a logger file and it created a separate series when
you actually wanted it to extend an existing series, merge them with
one UPDATE and one DELETE:

```sql
UPDATE w_levels_logger SET series_id = <keep_id>
WHERE series_id = <merge_id>;
DELETE FROM w_logger_series WHERE id = <merge_id>;
```

### Scheduled / recurring imports

External scripts that append hourly data should pick their target
`series_id` once at setup time (or resolve it by selecting from
`w_logger_series` using a convention the operator defines) and use it
for every insert. When the operator swaps loggers, they create a new
series in `w_logger_series` and point the script at the new id.

Midvatten does not enforce a convention here because `source` is
free-form text and deliberately not a uniqueness key — two distinct
series can share the same source text.
