-- Opt-in companion to upgrade_postgresql_to_2_0_0.sql: delete same-instant
-- duplicate rows, keeping the earliest physical row of every group.
--
-- WARNING — THIS SCRIPT DELETES ROWS.
--
-- Run it only after upgrade_postgresql_to_2_0_0.sql has stopped at its
-- duplicate gate (section 0a) and you have reviewed the report it printed
-- and the midv_upgrade_duplicates_<table> views it left behind. Groups
-- whose data_identical column is true lose nothing but a duplicate spelling
-- of the same timestamp. Groups where it is false carry conflicting data:
-- this script keeps the earliest physical row (lowest ctid) and deletes the
-- rest, so decide first whether that is the row you want to keep, or fix
-- those rows by hand instead of running this script.
--
-- Usage:
--   psql -d <your_db> -f upgrade_postgresql_to_2_0_0_dedup_keep_earliest.sql
--   psql -d <your_db> -f upgrade_postgresql_to_2_0_0.sql
--
-- "Duplicate" means two rows with the same key columns whose date_time strings
-- represent the same instant when parsed (e.g. '2020-01-01 12:00' and
-- '2020-01-01 12:00:00'). Raw date_time values are NOT modified. Rows with
-- unparseable date_time values are never deleted. psql prints "DELETE n" after
-- each statement with the number of rows removed.

-- midv_to_instant is installed by the upgrade script before its duplicate
-- gate, so it normally exists already. CREATE OR REPLACE keeps this script
-- runnable on its own. Keep this definition identical to section 0 of
-- upgrade_postgresql_to_2_0_0.sql.
CREATE OR REPLACE FUNCTION midv_to_instant(t text) RETURNS timestamp AS $$
BEGIN
    RETURN t::timestamp;
EXCEPTION WHEN others THEN
    RETURN NULL;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

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

-- Now run upgrade_postgresql_to_2_0_0.sql again. Its duplicate gate will
-- pass and it drops the midv_upgrade_duplicates_<table> report views.
