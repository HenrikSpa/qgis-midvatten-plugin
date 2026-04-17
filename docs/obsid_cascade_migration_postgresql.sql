-- obsid CASCADE migration for existing PostgreSQL databases
--
-- New databases created by the plugin already include ON UPDATE CASCADE ON DELETE CASCADE
-- on all foreign keys that reference obs_points(obsid) or obs_lines(obsid).
--
-- Run this script on existing PostgreSQL databases to retrofit cascade behaviour:
--   - ON UPDATE CASCADE: renaming an obsid in obs_points/obs_lines via the QGIS
--     attribute table will propagate to all child tables automatically.
--   - ON DELETE CASCADE: deleting an obs_points/obs_lines row will delete all
--     dependent rows in child tables automatically.
--
-- Usage:
--   psql -d <your_db> -f obsid_cascade_migration_postgresql.sql
--
-- PostgreSQL assigns default constraint names of the form <table>_<column>_fkey.
-- If your database uses different constraint names, adjust the DROP CONSTRAINT lines.
-- To inspect current names: SELECT conname FROM pg_constraint WHERE conrelid = '<table>'::regclass;

-- obs_points children

ALTER TABLE w_levels
    DROP CONSTRAINT IF EXISTS w_levels_obsid_fkey,
    ADD CONSTRAINT w_levels_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_points(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE w_logger_series
    DROP CONSTRAINT IF EXISTS w_logger_series_obsid_fkey,
    ADD CONSTRAINT w_logger_series_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_points(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE w_levels_logger
    DROP CONSTRAINT IF EXISTS w_levels_logger_obsid_fkey,
    ADD CONSTRAINT w_levels_logger_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_points(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE stratigraphy
    DROP CONSTRAINT IF EXISTS stratigraphy_obsid_fkey,
    ADD CONSTRAINT stratigraphy_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_points(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE w_qual_field
    DROP CONSTRAINT IF EXISTS w_qual_field_obsid_fkey,
    ADD CONSTRAINT w_qual_field_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_points(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE w_qual_lab
    DROP CONSTRAINT IF EXISTS w_qual_lab_obsid_fkey,
    ADD CONSTRAINT w_qual_lab_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_points(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE w_flow
    DROP CONSTRAINT IF EXISTS w_flow_obsid_fkey,
    ADD CONSTRAINT w_flow_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_points(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE meteo
    DROP CONSTRAINT IF EXISTS meteo_obsid_fkey,
    ADD CONSTRAINT meteo_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_points(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE comments
    DROP CONSTRAINT IF EXISTS comments_obsid_fkey,
    ADD CONSTRAINT comments_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_points(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE zz_interlab4_obsid_assignment
    DROP CONSTRAINT IF EXISTS zz_interlab4_obsid_assignment_obsid_fkey,
    ADD CONSTRAINT zz_interlab4_obsid_assignment_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_points(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE w_qual_logger
    DROP CONSTRAINT IF EXISTS w_qual_logger_obsid_fkey,
    ADD CONSTRAINT w_qual_logger_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_points(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE s_qual_lab
    DROP CONSTRAINT IF EXISTS s_qual_lab_obsid_fkey,
    ADD CONSTRAINT s_qual_lab_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_points(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE spatial_history
    DROP CONSTRAINT IF EXISTS spatial_history_obsid_fkey,
    ADD CONSTRAINT spatial_history_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_points(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

-- obs_lines children

ALTER TABLE seismic_data
    DROP CONSTRAINT IF EXISTS seismic_data_obsid_fkey,
    ADD CONSTRAINT seismic_data_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_lines(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE vlf_data
    DROP CONSTRAINT IF EXISTS vlf_data_obsid_fkey,
    ADD CONSTRAINT vlf_data_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_lines(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE tem_data
    DROP CONSTRAINT IF EXISTS tem_data_obsid_fkey,
    ADD CONSTRAINT tem_data_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_lines(obsid) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE profile_images
    DROP CONSTRAINT IF EXISTS profile_images_obsid_fkey,
    ADD CONSTRAINT profile_images_obsid_fkey
        FOREIGN KEY (obsid) REFERENCES obs_lines(obsid) ON UPDATE CASCADE ON DELETE CASCADE;
