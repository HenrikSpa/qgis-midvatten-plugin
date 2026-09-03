-- PostgreSQL schema upgrade: master → ai_test
--
-- Applies all schema changes introduced on the ai_test branch to an existing
-- PostgreSQL (PostGIS) Midvatten database that was created from the master
-- branch schema.
--
-- This script is a superset of docs/obsid_cascade_migration_postgresql.sql.
-- If you have already run that script, running this one is still safe — all
-- structural changes are idempotent.
--
-- Usage:
--   psql -d <your_db> -f upgrade_postgresql_ai_test.sql
--
-- WARNING — DATA DELETION (section 12):
--   This script removes duplicate rows from w_levels, w_levels_logger,
--   comments, w_flow, meteo, w_qual_field, and w_qual_logger before creating
--   unique indexes on those tables. "Duplicate" means two rows with the same
--   key columns whose date_time strings represent the same instant when parsed
--   (e.g. '2020-01-01 12:00' and '2020-01-01 12:00:00').  Raw date_time values
--   are NOT modified — only the later physical row (higher ctid) is deleted.
--   Rows with unparseable date_time values are left untouched and reported.
--   The earliest physical row for each duplicate group is kept, matching the
--   behaviour of the export-to-SpatiaLite tool.
--   Review your data BEFORE running this script if you are unsure.
--
-- To inspect current FK constraint names on any table:
--   SELECT conname FROM pg_constraint WHERE conrelid = '<table>'::regclass;

-- =============================================================================
-- 0. Helper function: midv_to_instant
--
-- Converts a text date_time value to a PostgreSQL timestamp, returning NULL
-- for any value that cannot be parsed.  Used in expression-based unique indexes
-- so that rows with malformed date_time values escape uniqueness checking
-- (mirroring SQLite's datetime() → NULL behaviour).
--
-- CREATE OR REPLACE makes this idempotent — safe to run even if the function
-- already exists from a previous execution or from create_db.py for new DBs.
--
-- NOTE: The plpgsql body contains internal semicolons.  This file is executed
-- via "psql -f" (not via execute_sqlfile), so dollar-quoting works correctly.
-- =============================================================================

CREATE OR REPLACE FUNCTION midv_to_instant(t text) RETURNS timestamp AS $$
BEGIN
    RETURN t::timestamp;
EXCEPTION WHEN others THEN
    RETURN NULL;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- =============================================================================
-- 1. New data-domain table: zz_screen_plots
-- =============================================================================

CREATE TABLE IF NOT EXISTS zz_screen_plots (
    screenshort        text NOT NULL,
    color_mplot        text,
    edgecolor_mplot    text,
    hatch_mplot        text,
    linewidth_mplot    double precision,
    PRIMARY KEY (screenshort)
);

-- =============================================================================
-- 2. New table: w_logger_series
-- =============================================================================

CREATE TABLE IF NOT EXISTS w_logger_series (
    id          SERIAL PRIMARY KEY,
    obsid       text NOT NULL,
    source      text,
    instrument  text,
    description text,
    comment     text,
    FOREIGN KEY (obsid) REFERENCES obs_points(obsid) ON UPDATE CASCADE ON DELETE CASCADE
);

-- =============================================================================
-- 3. Migrate w_levels_logger: source → series_id + created_at
--
-- Adds series_id (FK to w_logger_series) and created_at columns if missing.
-- If the old "source" column still exists, migrates its values into
-- w_logger_series (one row per distinct obsid+source pair), links rows via
-- series_id, then drops the source column.
-- The DO block makes the migration idempotent.
-- =============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name   = 'w_levels_logger'
          AND column_name  = 'series_id'
    ) THEN
        ALTER TABLE w_levels_logger ADD COLUMN series_id integer;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name   = 'w_levels_logger'
          AND column_name  = 'created_at'
    ) THEN
        ALTER TABLE w_levels_logger
            ADD COLUMN created_at text NOT NULL DEFAULT CURRENT_TIMESTAMP;
    END IF;

    -- Migrate source → w_logger_series only while the source column still exists.
    -- Rows with NULL source stay unlinked (series_id remains NULL), which is valid.
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name   = 'w_levels_logger'
          AND column_name  = 'source'
    ) THEN
        INSERT INTO w_logger_series (obsid, source)
        SELECT DISTINCT obsid, source
        FROM w_levels_logger
        WHERE source IS NOT NULL;

        UPDATE w_levels_logger wll
        SET series_id = ws.id
        FROM w_logger_series ws
        WHERE wll.obsid = ws.obsid
          AND wll.source = ws.source;

        ALTER TABLE w_levels_logger DROP COLUMN source;
    END IF;
END $$;

ALTER TABLE w_levels_logger
    DROP CONSTRAINT IF EXISTS w_levels_logger_series_id_fkey,
    ADD  CONSTRAINT w_levels_logger_series_id_fkey
        FOREIGN KEY (series_id) REFERENCES w_logger_series(id) ON DELETE CASCADE;

-- =============================================================================
-- 4. New table: screen
-- =============================================================================

CREATE TABLE IF NOT EXISTS screen (
    id          SERIAL PRIMARY KEY,
    obsid       text NOT NULL,
    screenid    integer NOT NULL,
    depthtop    double precision,
    depthbot    double precision,
    screenshort text,
    screen      text,
    comment     text,
    diam_inner  double precision,
    diam_outer  double precision,
    UNIQUE (obsid, screenid),
    FOREIGN KEY (obsid) REFERENCES obs_points(obsid)
);

-- diam_inner/diam_outer must also be added when `screen` already exists from a
-- partial earlier run (CREATE TABLE IF NOT EXISTS would skip the block above).
ALTER TABLE screen ADD COLUMN IF NOT EXISTS diam_inner double precision;
ALTER TABLE screen ADD COLUMN IF NOT EXISTS diam_outer double precision;

-- =============================================================================
-- 5. New table: tem_data
-- =============================================================================

CREATE TABLE IF NOT EXISTS tem_data (
    id              SERIAL PRIMARY KEY,
    obsid           text NOT NULL,
    inversion_name  text NOT NULL,
    length          double precision NOT NULL,
    elevation       double precision,
    data_fit        double precision,
    doi             double precision,
    thickness       text,
    resistivity     text,
    comment         text,
    UNIQUE (obsid, inversion_name, length),
    FOREIGN KEY (obsid) REFERENCES obs_lines(obsid) ON UPDATE CASCADE ON DELETE CASCADE
);

-- =============================================================================
-- 6. New table: profile_images
-- =============================================================================

CREATE TABLE IF NOT EXISTS profile_images (
    id                          SERIAL PRIMARY KEY,
    obsid                       text NOT NULL,
    alias                       text NOT NULL,
    path                        text NOT NULL,
    clip_left_right_top_bottom  text,
    extent_left_right_top_bottom text NOT NULL,
    source                      text,
    comment                     text,
    UNIQUE (obsid, alias),
    FOREIGN KEY (obsid) REFERENCES obs_lines(obsid) ON UPDATE CASCADE ON DELETE CASCADE
);

-- =============================================================================
-- 7. New table: s_qual_lab
-- =============================================================================

CREATE TABLE IF NOT EXISTS s_qual_lab (
    obsid       text NOT NULL,
    depth       double precision,
    report      text NOT NULL,
    project     text,
    staff       text,
    date_time   text,
    anameth     text,
    parameter   text NOT NULL,
    reading_num double precision,
    reading_txt text,
    unit        text,
    comment     text,
    PRIMARY KEY (report, parameter),
    FOREIGN KEY (obsid) REFERENCES obs_points(obsid) ON UPDATE CASCADE ON DELETE CASCADE
);

-- =============================================================================
-- 8. New table: w_qual_logger + unique index
-- =============================================================================

CREATE TABLE IF NOT EXISTS w_qual_logger (
    obsid       text NOT NULL,
    date_time   text NOT NULL,
    instrument  text,
    parameter   text NOT NULL,
    reading_num double precision,
    unit        text,
    comment     text,
    PRIMARY KEY (obsid, date_time, instrument, parameter, unit),
    FOREIGN KEY (obsid) REFERENCES obs_points(obsid) ON UPDATE CASCADE ON DELETE CASCADE
);

-- NOTE: The unique index on this table (w_qual_logger_unit_unique_index_null)
-- is created in section 13 after deduplication in section 12, so it is not
-- built here where it might fail if same-instant rows exist in an edge case.

-- =============================================================================
-- 9. New table: spatial_history
-- =============================================================================

CREATE TABLE IF NOT EXISTS spatial_history (
    id              SERIAL PRIMARY KEY,
    obsid           text NOT NULL,
    valid_from_date text NOT NULL,
    east            double precision,
    north           double precision,
    ne_accur        double precision,
    ne_source       text,
    h_toc           double precision,
    h_tocags        double precision,
    h_gs            double precision,
    h_accur         double precision,
    h_syst          text,
    h_source        text,
    valid           boolean,
    FOREIGN KEY (obsid) REFERENCES obs_points(obsid) ON UPDATE CASCADE ON DELETE CASCADE
);

-- =============================================================================
-- 10. FK CASCADE — retrofit ON UPDATE CASCADE ON DELETE CASCADE
--
-- All foreign keys referencing obs_points(obsid) or obs_lines(obsid) are
-- updated to cascade updates and deletes. PostgreSQL assigns default constraint
-- names of the form <table>_<column>_fkey; adjust the DROP lines if your
-- database uses different names.
-- The screen table FK is intentionally left without CASCADE (matching
-- create_db.sql).
-- =============================================================================

-- obs_points children

ALTER TABLE w_levels
    DROP CONSTRAINT IF EXISTS w_levels_obsid_fkey,
    ADD  CONSTRAINT w_levels_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_points(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE w_logger_series
    DROP CONSTRAINT IF EXISTS w_logger_series_obsid_fkey,
    ADD  CONSTRAINT w_logger_series_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_points(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE w_levels_logger
    DROP CONSTRAINT IF EXISTS w_levels_logger_obsid_fkey,
    ADD  CONSTRAINT w_levels_logger_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_points(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE stratigraphy
    DROP CONSTRAINT IF EXISTS stratigraphy_obsid_fkey,
    ADD  CONSTRAINT stratigraphy_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_points(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE w_qual_field
    DROP CONSTRAINT IF EXISTS w_qual_field_obsid_fkey,
    ADD  CONSTRAINT w_qual_field_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_points(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE w_qual_lab
    DROP CONSTRAINT IF EXISTS w_qual_lab_obsid_fkey,
    ADD  CONSTRAINT w_qual_lab_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_points(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE w_flow
    DROP CONSTRAINT IF EXISTS w_flow_obsid_fkey,
    ADD  CONSTRAINT w_flow_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_points(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE meteo
    DROP CONSTRAINT IF EXISTS meteo_obsid_fkey,
    ADD  CONSTRAINT meteo_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_points(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE comments
    DROP CONSTRAINT IF EXISTS comments_obsid_fkey,
    ADD  CONSTRAINT comments_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_points(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE zz_interlab4_obsid_assignment
    DROP CONSTRAINT IF EXISTS zz_interlab4_obsid_assignment_obsid_fkey,
    ADD  CONSTRAINT zz_interlab4_obsid_assignment_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_points(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE w_qual_logger
    DROP CONSTRAINT IF EXISTS w_qual_logger_obsid_fkey,
    ADD  CONSTRAINT w_qual_logger_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_points(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE s_qual_lab
    DROP CONSTRAINT IF EXISTS s_qual_lab_obsid_fkey,
    ADD  CONSTRAINT s_qual_lab_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_points(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE spatial_history
    DROP CONSTRAINT IF EXISTS spatial_history_obsid_fkey,
    ADD  CONSTRAINT spatial_history_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_points(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

-- obs_lines children

ALTER TABLE seismic_data
    DROP CONSTRAINT IF EXISTS seismic_data_obsid_fkey,
    ADD  CONSTRAINT seismic_data_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_lines(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE vlf_data
    DROP CONSTRAINT IF EXISTS vlf_data_obsid_fkey,
    ADD  CONSTRAINT vlf_data_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_lines(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE tem_data
    DROP CONSTRAINT IF EXISTS tem_data_obsid_fkey,
    ADD  CONSTRAINT tem_data_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_lines(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE profile_images
    DROP CONSTRAINT IF EXISTS profile_images_obsid_fkey,
    ADD  CONSTRAINT profile_images_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_lines(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

-- =============================================================================
-- 11. Fix w_qual_field unique index
--
-- The column order changed from (obsid, date_time, parameter, COALESCE(...))
-- to (obsid, parameter, date_time, COALESCE(...)), and the date_time column is
-- now wrapped in midv_to_instant() for instant-normalised uniqueness.
-- The old index is dropped together with all other old datetime indexes in
-- section 12b, before deduplication; the new normalised index is created in
-- section 13 after deduplication has been completed.
-- =============================================================================

-- =============================================================================
-- 12. Deduplicate datetime-PK tables (instant-normalised)
--
-- WARNING: ROWS MAY BE DELETED.
--
-- SpatiaLite databases can contain rows with different raw date_time strings
-- that represent the same instant (e.g. '2020-01-01 12:00' vs
-- '2020-01-01 12:00:00'). When such a database was migrated to PostgreSQL,
-- both rows were preserved because there was no normalising unique index.
-- The unique indexes created in section 13 would fail on those same-instant
-- duplicates.
--
-- Deduplication strategy:
--   - Uniqueness is determined by midv_to_instant(date_time), not raw text.
--   - Raw date_time values are NOT modified.
--   - Rows with unparseable date_time values (midv_to_instant → NULL) are left
--     untouched — they escape uniqueness and are reported in the NOTICE output.
--   - The earliest physical row (lowest ctid) for each duplicate group is kept.
--     This matches the behaviour of the export-to-SpatiaLite tool.
--
-- The old raw-text unique indexes (uq_* and w_qual_*) are dropped first so
-- they do not block the DELETE statements or conflict with the new normalized
-- indexes created in section 13.
-- =============================================================================

-- ---- 12a. Report same-instant collision groups and malformed dates ----------

DO $$ DECLARE c bigint; BEGIN
    SELECT count(*) INTO c FROM (
        SELECT 1 FROM w_levels
        WHERE midv_to_instant(date_time) IS NOT NULL
        GROUP BY obsid, midv_to_instant(date_time) HAVING count(*) > 1) s;
    RAISE NOTICE 'w_levels same-instant collision groups: %', c;
    SELECT count(*) INTO c FROM w_levels
        WHERE date_time IS NOT NULL AND date_time <> '' AND midv_to_instant(date_time) IS NULL;
    RAISE NOTICE 'w_levels malformed date_time (left raw, escape uniqueness): %', c;

    SELECT count(*) INTO c FROM (
        SELECT 1 FROM w_levels_logger
        WHERE midv_to_instant(date_time) IS NOT NULL
        GROUP BY obsid, midv_to_instant(date_time) HAVING count(*) > 1) s;
    RAISE NOTICE 'w_levels_logger same-instant collision groups: %', c;
    SELECT count(*) INTO c FROM w_levels_logger
        WHERE date_time IS NOT NULL AND date_time <> '' AND midv_to_instant(date_time) IS NULL;
    RAISE NOTICE 'w_levels_logger malformed date_time (left raw, escape uniqueness): %', c;

    SELECT count(*) INTO c FROM (
        SELECT 1 FROM comments
        WHERE midv_to_instant(date_time) IS NOT NULL
        GROUP BY obsid, midv_to_instant(date_time) HAVING count(*) > 1) s;
    RAISE NOTICE 'comments same-instant collision groups: %', c;
    SELECT count(*) INTO c FROM comments
        WHERE date_time IS NOT NULL AND date_time <> '' AND midv_to_instant(date_time) IS NULL;
    RAISE NOTICE 'comments malformed date_time (left raw, escape uniqueness): %', c;

    SELECT count(*) INTO c FROM (
        SELECT 1 FROM w_flow
        WHERE midv_to_instant(date_time) IS NOT NULL
        GROUP BY obsid, flowtype, instrumentid, midv_to_instant(date_time) HAVING count(*) > 1) s;
    RAISE NOTICE 'w_flow same-instant collision groups: %', c;
    SELECT count(*) INTO c FROM w_flow
        WHERE date_time IS NOT NULL AND date_time <> '' AND midv_to_instant(date_time) IS NULL;
    RAISE NOTICE 'w_flow malformed date_time (left raw, escape uniqueness): %', c;

    SELECT count(*) INTO c FROM (
        SELECT 1 FROM meteo
        WHERE midv_to_instant(date_time) IS NOT NULL
        GROUP BY obsid, parameter, instrumentid, midv_to_instant(date_time) HAVING count(*) > 1) s;
    RAISE NOTICE 'meteo same-instant collision groups: %', c;
    SELECT count(*) INTO c FROM meteo
        WHERE date_time IS NOT NULL AND date_time <> '' AND midv_to_instant(date_time) IS NULL;
    RAISE NOTICE 'meteo malformed date_time (left raw, escape uniqueness): %', c;

    SELECT count(*) INTO c FROM (
        SELECT 1 FROM w_qual_field
        WHERE midv_to_instant(date_time) IS NOT NULL
        GROUP BY obsid, parameter, COALESCE(unit, '<NULL>'), midv_to_instant(date_time) HAVING count(*) > 1) s;
    RAISE NOTICE 'w_qual_field same-instant collision groups: %', c;
    SELECT count(*) INTO c FROM w_qual_field
        WHERE date_time IS NOT NULL AND date_time <> '' AND midv_to_instant(date_time) IS NULL;
    RAISE NOTICE 'w_qual_field malformed date_time (left raw, escape uniqueness): %', c;

    SELECT count(*) INTO c FROM (
        SELECT 1 FROM w_qual_logger
        WHERE midv_to_instant(date_time) IS NOT NULL
        GROUP BY obsid, parameter, instrument, COALESCE(unit, '<NULL>'), midv_to_instant(date_time) HAVING count(*) > 1) s;
    RAISE NOTICE 'w_qual_logger same-instant collision groups: %', c;
    SELECT count(*) INTO c FROM w_qual_logger
        WHERE date_time IS NOT NULL AND date_time <> '' AND midv_to_instant(date_time) IS NULL;
    RAISE NOTICE 'w_qual_logger malformed date_time (left raw, escape uniqueness): %', c;
END $$;

-- ---- 12b. Drop old raw-text unique indexes (idempotent) --------------------
--
-- Must happen before the DELETE statements so existing raw-text indexes do not
-- block rows that share a raw string but differ in normalised instant, and
-- before section 13 so the old definitions do not conflict with the new ones.

DROP INDEX IF EXISTS uq_w_levels_obsid_dt;
DROP INDEX IF EXISTS uq_w_levels_logger_obsid_dt;
DROP INDEX IF EXISTS uq_comments_obsid_dt;
DROP INDEX IF EXISTS uq_w_flow_obsid_dt;
DROP INDEX IF EXISTS uq_meteo_obsid_dt;
DROP INDEX IF EXISTS w_qual_field_unit_unique_index_null;
DROP INDEX IF EXISTS w_qual_logger_unit_unique_index_null;

-- ---- 12c. Delete same-instant duplicates (keep earliest ctid) --------------
--
-- Only parseable rows are considered (midv_to_instant IS NOT NULL).
-- Rows with malformed date_time survive unchanged.

-- w_levels
DELETE FROM w_levels a USING w_levels b
WHERE a.obsid = b.obsid
  AND midv_to_instant(a.date_time) IS NOT NULL
  AND midv_to_instant(a.date_time) = midv_to_instant(b.date_time)
  AND a.ctid > b.ctid;

-- w_levels_logger
DELETE FROM w_levels_logger a USING w_levels_logger b
WHERE a.obsid = b.obsid
  AND midv_to_instant(a.date_time) IS NOT NULL
  AND midv_to_instant(a.date_time) = midv_to_instant(b.date_time)
  AND a.ctid > b.ctid;

-- comments
DELETE FROM comments a USING comments b
WHERE a.obsid = b.obsid
  AND midv_to_instant(a.date_time) IS NOT NULL
  AND midv_to_instant(a.date_time) = midv_to_instant(b.date_time)
  AND a.ctid > b.ctid;

-- w_flow (extra key: flowtype, instrumentid)
DELETE FROM w_flow a USING w_flow b
WHERE a.obsid = b.obsid
  AND a.flowtype = b.flowtype
  AND a.instrumentid = b.instrumentid
  AND midv_to_instant(a.date_time) IS NOT NULL
  AND midv_to_instant(a.date_time) = midv_to_instant(b.date_time)
  AND a.ctid > b.ctid;

-- meteo (extra key: parameter, instrumentid)
DELETE FROM meteo a USING meteo b
WHERE a.obsid = b.obsid
  AND a.parameter = b.parameter
  AND a.instrumentid = b.instrumentid
  AND midv_to_instant(a.date_time) IS NOT NULL
  AND midv_to_instant(a.date_time) = midv_to_instant(b.date_time)
  AND a.ctid > b.ctid;

-- w_qual_field (extra key: parameter, unit coalesced)
DELETE FROM w_qual_field a USING w_qual_field b
WHERE a.obsid = b.obsid
  AND a.parameter = b.parameter
  AND COALESCE(a.unit, '<NULL>') = COALESCE(b.unit, '<NULL>')
  AND midv_to_instant(a.date_time) IS NOT NULL
  AND midv_to_instant(a.date_time) = midv_to_instant(b.date_time)
  AND a.ctid > b.ctid;

-- w_qual_logger (extra key: parameter, instrument, unit coalesced)
DELETE FROM w_qual_logger a USING w_qual_logger b
WHERE a.obsid = b.obsid
  AND a.parameter = b.parameter
  AND a.instrument = b.instrument
  AND COALESCE(a.unit, '<NULL>') = COALESCE(b.unit, '<NULL>')
  AND midv_to_instant(a.date_time) IS NOT NULL
  AND midv_to_instant(a.date_time) = midv_to_instant(b.date_time)
  AND a.ctid > b.ctid;

-- =============================================================================
-- 13. Normalised unique indexes on datetime-PK tables
--
-- Each index uses midv_to_instant(date_time) so rows with different raw strings
-- that represent the same instant are treated as duplicates, while rows with
-- unparseable date_time values (midv_to_instant → NULL) escape the unique
-- constraint entirely (NULL ≠ NULL in index semantics).
--
-- IF NOT EXISTS makes each statement idempotent — safe if the index was already
-- created by a previous run of this script or by create_db.py for new DBs.
--
-- These definitions must match create_db.sql exactly (POSTGIS-prefixed lines).
-- =============================================================================

CREATE UNIQUE INDEX IF NOT EXISTS uq_w_levels_obsid_dt
    ON w_levels (obsid, midv_to_instant(date_time));

CREATE UNIQUE INDEX IF NOT EXISTS uq_w_levels_logger_obsid_dt
    ON w_levels_logger (obsid, midv_to_instant(date_time));

CREATE UNIQUE INDEX IF NOT EXISTS uq_comments_obsid_dt
    ON comments (obsid, midv_to_instant(date_time));

CREATE UNIQUE INDEX IF NOT EXISTS uq_w_flow_obsid_dt
    ON w_flow (obsid, flowtype, instrumentid, midv_to_instant(date_time));

CREATE UNIQUE INDEX IF NOT EXISTS uq_meteo_obsid_dt
    ON meteo (obsid, parameter, instrumentid, midv_to_instant(date_time));

CREATE UNIQUE INDEX IF NOT EXISTS w_qual_field_unit_unique_index_null
    ON w_qual_field (obsid, parameter, midv_to_instant(date_time), COALESCE(unit, '<NULL>'));

CREATE UNIQUE INDEX IF NOT EXISTS w_qual_logger_unit_unique_index_null
    ON w_qual_logger (obsid, parameter, instrument, midv_to_instant(date_time), COALESCE(unit, '<NULL>'));

-- =============================================================================
-- 13a. Verification gate
--
-- Each query below must return zero rows if the migration in sections 12–13
-- succeeded.  A non-empty result means same-instant duplicates remain, which
-- would have caused the corresponding CREATE UNIQUE INDEX above to fail.
-- If section 13's indexes built successfully — which they must have, or this
-- script would already have aborted — these queries return zero rows.
--
-- To verify interactively after running this script:
--   psql -d <your_db> -c "SELECT obsid, midv_to_instant(date_time), count(*) FROM w_levels WHERE midv_to_instant(date_time) IS NOT NULL GROUP BY obsid, midv_to_instant(date_time) HAVING count(*) > 1;"
-- (Adjust table and columns for other tables as needed.)
-- =============================================================================

DO $$ DECLARE c bigint; BEGIN
    SELECT count(*) INTO c FROM (
        SELECT 1 FROM w_levels
        WHERE midv_to_instant(date_time) IS NOT NULL
        GROUP BY obsid, midv_to_instant(date_time) HAVING count(*) > 1) s;
    IF c > 0 THEN
        RAISE EXCEPTION 'MIGRATION INCOMPLETE: w_levels still has % same-instant collision group(s) — unique index would not have built', c;
    END IF;

    SELECT count(*) INTO c FROM (
        SELECT 1 FROM w_levels_logger
        WHERE midv_to_instant(date_time) IS NOT NULL
        GROUP BY obsid, midv_to_instant(date_time) HAVING count(*) > 1) s;
    IF c > 0 THEN
        RAISE EXCEPTION 'MIGRATION INCOMPLETE: w_levels_logger still has % same-instant collision group(s) — unique index would not have built', c;
    END IF;

    SELECT count(*) INTO c FROM (
        SELECT 1 FROM comments
        WHERE midv_to_instant(date_time) IS NOT NULL
        GROUP BY obsid, midv_to_instant(date_time) HAVING count(*) > 1) s;
    IF c > 0 THEN
        RAISE EXCEPTION 'MIGRATION INCOMPLETE: comments still has % same-instant collision group(s) — unique index would not have built', c;
    END IF;

    SELECT count(*) INTO c FROM (
        SELECT 1 FROM w_flow
        WHERE midv_to_instant(date_time) IS NOT NULL
        GROUP BY obsid, flowtype, instrumentid, midv_to_instant(date_time) HAVING count(*) > 1) s;
    IF c > 0 THEN
        RAISE EXCEPTION 'MIGRATION INCOMPLETE: w_flow still has % same-instant collision group(s) — unique index would not have built', c;
    END IF;

    SELECT count(*) INTO c FROM (
        SELECT 1 FROM meteo
        WHERE midv_to_instant(date_time) IS NOT NULL
        GROUP BY obsid, parameter, instrumentid, midv_to_instant(date_time) HAVING count(*) > 1) s;
    IF c > 0 THEN
        RAISE EXCEPTION 'MIGRATION INCOMPLETE: meteo still has % same-instant collision group(s) — unique index would not have built', c;
    END IF;

    SELECT count(*) INTO c FROM (
        SELECT 1 FROM w_qual_field
        WHERE midv_to_instant(date_time) IS NOT NULL
        GROUP BY obsid, parameter, COALESCE(unit, '<NULL>'), midv_to_instant(date_time) HAVING count(*) > 1) s;
    IF c > 0 THEN
        RAISE EXCEPTION 'MIGRATION INCOMPLETE: w_qual_field still has % same-instant collision group(s) — unique index would not have built', c;
    END IF;

    SELECT count(*) INTO c FROM (
        SELECT 1 FROM w_qual_logger
        WHERE midv_to_instant(date_time) IS NOT NULL
        GROUP BY obsid, parameter, instrument, COALESCE(unit, '<NULL>'), midv_to_instant(date_time) HAVING count(*) > 1) s;
    IF c > 0 THEN
        RAISE EXCEPTION 'MIGRATION INCOMPLETE: w_qual_logger still has % same-instant collision group(s) — unique index would not have built', c;
    END IF;

    RAISE NOTICE 'Verification passed: all 7 tables have no same-instant duplicates among parseable rows.';
END $$;

-- =============================================================================
-- 14. Index changes for w_levels_logger
-- =============================================================================

DROP INDEX IF EXISTS idx_wlvllogger_o;

CREATE INDEX IF NOT EXISTS idx_wlvllogger_series
    ON w_levels_logger (series_id);

CREATE INDEX IF NOT EXISTS idx_wlogger_series_obsid
    ON w_logger_series (obsid);

-- =============================================================================
-- 15. Data domain inserts
-- =============================================================================

INSERT INTO zz_meteoparam (parameter, explanation)
VALUES ('pressure', 'Barometric pressure')
ON CONFLICT DO NOTHING;

INSERT INTO zz_screen_plots (screenshort, color_mplot, edgecolor_mplot, hatch_mplot, linewidth_mplot)
VALUES
    ('default',   'none', 'black', '', 1.0),
    ('JWS',       'none', 'black', '|||', 1.0),
    ('PVC solid', 'none', 'black', '',    1.5),
    ('stainless', 'none', 'black', 'xx',  1.0)
ON CONFLICT DO NOTHING;

-- =============================================================================
-- 16. Record the new database version
--
-- warn_about_old_database() reads the "created by Midvatten plugin ..." row,
-- extracts the version after "Midvatten plugin ", and warns if it is older than
-- latest_database_version(). Until now this upgrade left the old creation-version
-- in place, so an upgraded DB kept being flagged as old. Rewrite just that
-- version number to 2.0.0 (matching what a freshly-created 2.0 database stores),
-- preserving the QGIS and PostGIS parts of the string. Idempotent: re-running
-- rewrites 2.0.0 -> 2.0.0.
-- =============================================================================

UPDATE about_db
SET description = regexp_replace(
        description,
        'Midvatten plugin [0-9][0-9ab.]*',
        'Midvatten plugin 2.0.0'
    )
WHERE description LIKE 'This db was created by Midvatten plugin %';
