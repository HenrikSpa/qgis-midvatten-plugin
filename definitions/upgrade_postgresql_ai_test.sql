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
--   comments, w_flow, and meteo before creating unique indexes on those
--   tables. Duplicate rows are data errors (typically identical timestamps
--   entered more than once). The earliest physical row for each duplicate
--   group is kept, matching the behaviour of the export-to-SpatiaLite tool.
--   Review your data BEFORE running this script if you are unsure.
--
-- To inspect current FK constraint names on any table:
--   SELECT conname FROM pg_constraint WHERE conrelid = '<table>'::regclass;

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
    UNIQUE (obsid, screenid),
    FOREIGN KEY (obsid) REFERENCES obs_points(obsid)
);

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

CREATE UNIQUE INDEX IF NOT EXISTS w_qual_logger_unit_unique_index_null
    ON w_qual_logger (obsid, parameter, instrument, date_time, COALESCE(unit, '<NULL>'));

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
-- to (obsid, parameter, date_time, COALESCE(...)). Drop old, create new.
-- =============================================================================

DROP INDEX IF EXISTS w_qual_field_unit_unique_index_null;
CREATE UNIQUE INDEX IF NOT EXISTS w_qual_field_unit_unique_index_null
    ON w_qual_field (obsid, parameter, date_time, COALESCE(unit, '<NULL>'));

-- =============================================================================
-- 12. Deduplicate datetime-PK tables
--
-- WARNING: ROWS MAY BE DELETED.
--
-- SpatiaLite databases can contain rows with different raw date_time strings
-- that represent the same instant (e.g. '2020-01-01 12:00' vs
-- '2020-01-01 12:00:00'). When such a database was migrated to PostgreSQL,
-- both rows were preserved because there was no normalising unique index.
-- The unique indexes created in section 13 would fail on those duplicates.
--
-- For each affected table, the earliest physical row (lowest ctid) for each
-- duplicate group is kept and all later duplicates are deleted. This matches
-- the behaviour of the export-to-SpatiaLite tool (export_spatialite.py).
--
-- If you want to review duplicates before deletion, run this query first:
--   SELECT obsid, date_time, COUNT(*) FROM w_levels
--   GROUP BY obsid, date_time HAVING COUNT(*) > 1;
-- (Adjust table and columns for other tables as needed.)
-- =============================================================================

-- w_levels
WITH dups AS (
    SELECT ctid,
           ROW_NUMBER() OVER (PARTITION BY obsid, date_time ORDER BY ctid) AS rn
    FROM w_levels
)
DELETE FROM w_levels WHERE ctid IN (SELECT ctid FROM dups WHERE rn > 1);

-- w_levels_logger
WITH dups AS (
    SELECT ctid,
           ROW_NUMBER() OVER (PARTITION BY obsid, date_time ORDER BY ctid) AS rn
    FROM w_levels_logger
)
DELETE FROM w_levels_logger WHERE ctid IN (SELECT ctid FROM dups WHERE rn > 1);

-- comments
WITH dups AS (
    SELECT ctid,
           ROW_NUMBER() OVER (PARTITION BY obsid, date_time ORDER BY ctid) AS rn
    FROM comments
)
DELETE FROM comments WHERE ctid IN (SELECT ctid FROM dups WHERE rn > 1);

-- w_flow
WITH dups AS (
    SELECT ctid,
           ROW_NUMBER() OVER (PARTITION BY obsid, flowtype, instrumentid, date_time ORDER BY ctid) AS rn
    FROM w_flow
)
DELETE FROM w_flow WHERE ctid IN (SELECT ctid FROM dups WHERE rn > 1);

-- meteo
WITH dups AS (
    SELECT ctid,
           ROW_NUMBER() OVER (PARTITION BY obsid, parameter, instrumentid, date_time ORDER BY ctid) AS rn
    FROM meteo
)
DELETE FROM meteo WHERE ctid IN (SELECT ctid FROM dups WHERE rn > 1);

-- =============================================================================
-- 13. New unique indexes on datetime-PK tables
-- =============================================================================

CREATE UNIQUE INDEX IF NOT EXISTS uq_w_levels_obsid_dt
    ON w_levels (obsid, date_time);

CREATE UNIQUE INDEX IF NOT EXISTS uq_w_levels_logger_obsid_dt
    ON w_levels_logger (obsid, date_time);

CREATE UNIQUE INDEX IF NOT EXISTS uq_comments_obsid_dt
    ON comments (obsid, date_time);

CREATE UNIQUE INDEX IF NOT EXISTS uq_w_flow_obsid_dt
    ON w_flow (obsid, flowtype, instrumentid, date_time);

CREATE UNIQUE INDEX IF NOT EXISTS uq_meteo_obsid_dt
    ON meteo (obsid, parameter, instrumentid, date_time);

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
    ('default',   'none', 'black', '///', 1.0),
    ('JWS',       'none', 'black', '|||', 1.0),
    ('PVC solid', 'none', 'black', '',    1.5),
    ('stainless', 'none', 'black', 'xx',  1.0)
ON CONFLICT DO NOTHING;
