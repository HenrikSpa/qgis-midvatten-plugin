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
--   psql -d <your_db> -f upgrade_postgresql_to_2_0_0.sql
--
-- DUPLICATE ROWS STOP THE UPGRADE (section 0a):
--   Section 13 creates unique indexes on w_levels, w_levels_logger, comments,
--   w_flow, meteo, w_qual_field and w_qual_logger where two rows are treated
--   as the same when their key columns match and their date_time strings
--   represent the same instant when parsed (e.g. '2020-01-01 12:00' and
--   '2020-01-01 12:00:00'). Databases created before that rule may contain
--   such rows. This script never deletes them. Instead section 0a, which runs
--   before any change is made, reports every group and stops the script.
--   The full report is left in one view per affected table,
--   midv_upgrade_duplicates_<table>, with the raw date_time values and every
--   other column aggregated per group, so you can see whether the rows carry
--   identical data or conflicting data.
--   Fix the rows yourself, or run upgrade_postgresql_to_2_0_0_dedup_keep_earliest.sql
--   to keep the earliest physical row of every group, then run this script
--   again. The report views are dropped when the upgrade completes.
--   Rows with unparseable date_time values escape uniqueness, are never
--   deleted, and are only counted in the report.
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
-- 0a. Duplicate gate — report same-instant duplicates and stop, before any
--     schema change
--
-- Two DO blocks on purpose: the first builds the report views and commits
-- (psql runs each statement in its own transaction), the second raises the
-- error. Raising inside the first block would roll the views back.
--
-- Per table: one view midv_upgrade_duplicates_<table> with one row per
-- same-instant group: the key columns, the parsed instant, row_count,
-- data_identical (true when all rows in the group agree on every column
-- except date_time), and every other column aggregated as a comma-separated
-- list in physical row order (earliest first). Views for tables without
-- duplicates are dropped again.
-- =============================================================================

DO $gate$
DECLARE
    spec        record;
    key_exprs   text;
    agg_cols    text;
    view_name   text;
    n_groups    bigint;
    n_rows      bigint;
    n_conflict  bigint;
    n_malformed bigint;
    grp         record;
BEGIN
    FOR spec IN
        SELECT * FROM (VALUES
            ('w_levels',        ARRAY['obsid']),
            ('w_levels_logger', ARRAY['obsid']),
            ('comments',        ARRAY['obsid']),
            ('w_flow',          ARRAY['obsid', 'flowtype', 'instrumentid']),
            ('meteo',           ARRAY['obsid', 'parameter', 'instrumentid']),
            ('w_qual_field',    ARRAY['obsid', 'parameter', 'unit']),
            ('w_qual_logger',   ARRAY['obsid', 'parameter', 'instrument', 'unit'])
        ) AS t(tbl, keys)
    LOOP
        view_name := 'midv_upgrade_duplicates_' || spec.tbl;
        -- Left behind by an earlier stopped run. Checked first so psql does
        -- not print a "does not exist, skipping" notice for every table.
        IF EXISTS (SELECT 1 FROM pg_views
                    WHERE schemaname = current_schema() AND viewname = view_name) THEN
            EXECUTE format('DROP VIEW %I', view_name);
        END IF;

        -- Older databases have w_qual_logger as a view, or not at all; it is
        -- created as a table in section 8 and cannot hold duplicates yet.
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.tables
             WHERE table_schema = current_schema()
               AND table_name = spec.tbl
               AND table_type = 'BASE TABLE'
        ) THEN
            RAISE NOTICE '%: not a table in this database, skipped', spec.tbl;
            CONTINUE;
        END IF;

        SELECT string_agg(format('%I', k), ', ') INTO key_exprs
          FROM unnest(spec.keys) AS k;

        SELECT string_agg(
                   format('string_agg(coalesce(%I::text, ''NULL''), '', '' ORDER BY ctid) AS %I',
                          column_name, column_name),
                   ', ' ORDER BY ordinal_position)
          INTO agg_cols
          FROM information_schema.columns
         WHERE table_schema = current_schema()
           AND table_name = spec.tbl
           AND column_name <> 'date_time'
           AND NOT (column_name = ANY (spec.keys));

        EXECUTE format($v$
            CREATE VIEW %I AS
            SELECT %s,
                   midv_to_instant(date_time) AS instant,
                   count(*) AS row_count,
                   count(DISTINCT to_jsonb(t) - 'date_time') = 1 AS data_identical,
                   string_agg(date_time, ', ' ORDER BY ctid) AS date_time,
                   %s
              FROM %I t
             WHERE midv_to_instant(date_time) IS NOT NULL
             GROUP BY %s, midv_to_instant(date_time)
            HAVING count(*) > 1
        $v$, view_name, key_exprs, agg_cols, spec.tbl, key_exprs);

        EXECUTE format(
            'SELECT count(*), coalesce(sum(row_count), 0), '
            'count(*) FILTER (WHERE NOT data_identical) FROM %I', view_name)
          INTO n_groups, n_rows, n_conflict;
        EXECUTE format(
            'SELECT count(*) FROM %I WHERE date_time IS NOT NULL '
            'AND date_time <> '''' AND midv_to_instant(date_time) IS NULL', spec.tbl)
          INTO n_malformed;

        RAISE NOTICE '%: % same-instant group(s) covering % row(s), % with conflicting data; % malformed date_time value(s) left as is',
            spec.tbl, n_groups, n_rows, n_conflict, n_malformed;

        IF n_groups = 0 THEN
            EXECUTE format('DROP VIEW %I', view_name);
            CONTINUE;
        END IF;

        -- row_to_json keeps the view's column order (jsonb would sort keys).
        FOR grp IN EXECUTE format(
            'SELECT row_to_json(v)::text AS line FROM %I v ORDER BY %s, instant LIMIT 20',
            view_name, key_exprs)
        LOOP
            RAISE NOTICE '    %', grp.line;
        END LOOP;
        IF n_groups > 20 THEN
            RAISE NOTICE '    ... % more group(s). Full list: SELECT * FROM %;',
                n_groups - 20, view_name;
        ELSE
            RAISE NOTICE '    Full list: SELECT * FROM %;', view_name;
        END IF;
    END LOOP;
END
$gate$;

DO $stop$
DECLARE
    views text;
BEGIN
    SELECT string_agg(viewname, ', ' ORDER BY viewname) INTO views
      FROM pg_views
     WHERE schemaname = current_schema()
       AND viewname LIKE 'midv_upgrade_duplicates_%';
    IF views IS NOT NULL THEN
        RAISE EXCEPTION 'UPGRADE STOPPED, nothing has been changed: same-instant duplicate rows found. See the report above and the view(s) %. Fix the rows yourself, or run upgrade_postgresql_to_2_0_0_dedup_keep_earliest.sql to keep the earliest row of every group. Then run this upgrade again.',
            views;
    END IF;
END
$stop$;

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
-- is created in section 13 together with the other normalised indexes, after
-- the duplicate gate in section 0a has verified that no same-instant rows exist.

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
-- section 12; the new normalised index is created in section 13.
-- =============================================================================

-- =============================================================================
-- 12. Drop old raw-text unique indexes (idempotent)
--
-- The pre-2.0.0 indexes compared date_time as raw text. They are dropped so
-- their definitions do not conflict with the normalised indexes created in
-- section 13.
-- =============================================================================

DROP INDEX IF EXISTS uq_w_levels_obsid_dt;
DROP INDEX IF EXISTS uq_w_levels_logger_obsid_dt;
DROP INDEX IF EXISTS uq_comments_obsid_dt;
DROP INDEX IF EXISTS uq_w_flow_obsid_dt;
DROP INDEX IF EXISTS uq_meteo_obsid_dt;
DROP INDEX IF EXISTS w_qual_field_unit_unique_index_null;
DROP INDEX IF EXISTS w_qual_logger_unit_unique_index_null;

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
--
-- Each CREATE UNIQUE INDEX fails if same-instant duplicates remain, so
-- reaching section 14 proves all seven tables are clean. To check by hand:
--   SELECT * FROM midv_upgrade_duplicates_w_levels;   (while the gate blocks)
--   SELECT obsid, midv_to_instant(date_time), count(*) FROM w_levels
--     WHERE midv_to_instant(date_time) IS NOT NULL
--     GROUP BY obsid, midv_to_instant(date_time) HAVING count(*) > 1;
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

-- =============================================================================
-- 17. Remove the duplicate report views
--
-- Section 0a leaves midv_upgrade_duplicates_<table> views behind when it
-- stops the script. Reaching this point means every table passed, so the
-- views are empty and no longer needed.
-- =============================================================================

DROP VIEW IF EXISTS
    midv_upgrade_duplicates_w_levels,
    midv_upgrade_duplicates_w_levels_logger,
    midv_upgrade_duplicates_comments,
    midv_upgrade_duplicates_w_flow,
    midv_upgrade_duplicates_meteo,
    midv_upgrade_duplicates_w_qual_field,
    midv_upgrade_duplicates_w_qual_logger;
