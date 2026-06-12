"""
Higher-level helpers: cast_date_time_as_epoch, cast_null, backup_db, get_srid_name, etc.
"""

import ast
import os
import re
import traceback
from collections import defaultdict
from typing import Any, Optional

try:
    import psycopg2
except ImportError:
    psycopg2 = None
from qgis.PyQt.QtCore import QCoreApplication

from midvatten.tools.utils import message_utils
from midvatten.tools.utils.common_utils import waiting_cursor
from midvatten.tools.utils.string_utils import returnunicode as ru
from midvatten.tools.utils.db_utils.connection import DbConnectionManager
from midvatten.tools.utils.db_utils.execution import (
    sql_load_fr_db,
    use_or_create_connection,
)
from midvatten.tools.utils.db_utils.schema import (
    get_sql_result_as_dict,
    get_table_info,
    tables_columns,
)


def add_insert_or_ignore_to_sql(sql: str, dbconnection: DbConnectionManager) -> str:
    """Return SQL with INSERT OR IGNORE (SQLite) or ON CONFLICT DO NOTHING (PG)."""
    return dbconnection.add_insert_or_ignore_to_sql(sql)


def get_last_insert_id(dbconnection: DbConnectionManager) -> int:
    """Return the auto-generated id of the most recent INSERT on this connection.

    Uses ``last_insert_rowid()`` on SpatiaLite and ``lastval()`` on PostgreSQL.
    Both are connection-scoped, so callers must use the same dbconnection that
    performed the INSERT without committing / closing in between.
    """
    if dbconnection.is_sqlite():
        sql = "SELECT last_insert_rowid()"
    else:
        sql = "SELECT lastval()"
    return dbconnection.execute_and_fetchall(sql)[0][0]


def backup_db(dbconnection: Optional[DbConnectionManager] = None) -> None:
    with use_or_create_connection(dbconnection) as dbconn:
        dbconn.backup()


def vacuum_db(dbconnection: Optional[DbConnectionManager] = None) -> None:
    with use_or_create_connection(dbconnection) as dbconn:
        dbconn.vacuum()


def cast_date_time_as_epoch(
    dbconnection: Optional[DbConnectionManager] = None,
    date_time: Optional[str] = None,
) -> tuple[str, tuple]:
    """Return (sql_fragment, args) for an epoch cast.

    When ``date_time`` is provided the fragment uses a backend placeholder
    and ``args`` carries the value — callers must parameter-bind the
    returned args alongside any surrounding SQL. See F1 in
    docs/superpowers/specs/2026-04-19-stabilisation-followups.md.
    """
    with use_or_create_connection(dbconnection) as dbconnection:
        return dbconnection.cast_date_time_as_epoch(date_time)


def cast_null(
    data_type: str,
    dbconnection: Optional[DbConnectionManager] = None,
) -> str:
    with use_or_create_connection(dbconnection) as dbconnection:
        return dbconnection.cast_null(data_type)


def get_dbtype(dbtype: str) -> str:
    """For QgsVectorLayer, dbtype has to be 'postgres' instead of 'postgis'."""
    if dbtype == "postgis":
        return "postgres"
    return dbtype


def get_srid_name(
    srid: int,
    dbconnection: Optional[DbConnectionManager] = None,
) -> str:
    with use_or_create_connection(dbconnection) as dbconnection:
        return dbconnection.get_srid_name(srid)


def get_spatialite_db_path_from_dbsettings_string(db_settings: str) -> str:
    if isinstance(db_settings, str):
        if os.path.isfile(db_settings):
            return db_settings
        try:
            db_settings = ast.literal_eval(db_settings)
        except Exception as e:
            try:
                msg = str(e)
            except Exception:
                msg = QCoreApplication.translate(
                    "get_spatialite_db_path_from_dbsettings_string",
                    "Error message failed! Could not be converted to string!",
                )

            message_utils.MessagebarAndLog.info(
                log_msg=QCoreApplication.translate(
                    "get_spatialite_db_path_from_dbsettings_string",
                    '%s error msg from db_settings string "%s": %s',
                )
                % (
                    "get_spatialite_db_path_from_dbsettings_string",
                    db_settings,
                    msg,
                )
            )
            return ""
        return db_settings.get("spatialite", {}).get("dbpath", "")
    if isinstance(db_settings, dict):
        return db_settings.get("spatialite", {}).get("dbpath", "")
    return ""


def is_distinct_from(dbconnection: DbConnectionManager) -> str:
    return dbconnection.is_distinct_from()


def is_not_distinct_from(dbconnection: DbConnectionManager) -> str:
    return dbconnection.is_not_distinct_from()


def test_not_null_and_not_empty_string(
    table: str,
    column: str,
    dbconnection: Optional[DbConnectionManager] = None,
) -> str:
    with use_or_create_connection(dbconnection) as dbconnection:
        col_ident = dbconnection.ident(column)
        table_info = [
            col
            for col in get_table_info(table, dbconnection)
            if col and col[1] == column
        ]
        data_type = table_info[0][2] if table_info else None
        return dbconnection.not_null_sql(col_ident, data_type)


def get_all_obsids(
    table: str = "obs_points",
    dbconnection: Optional[DbConnectionManager] = None,
) -> list:
    with use_or_create_connection(dbconnection) as dbconnection:
        sql = dbconnection.sql_ident(
            "SELECT DISTINCT obsid FROM {t} ORDER BY obsid", t=table
        )
        connection_ok, result = sql_load_fr_db(sql, dbconnection=dbconnection)
        if connection_ok:
            return [row[0] for row in result]
        return []


def get_latlon_for_all_obsids(
    dbconnection: Optional[DbConnectionManager] = None,
) -> dict:
    with use_or_create_connection(dbconnection) as dbconnection:
        sql = dbconnection.latlon_sql()
        latlon_dict = get_sql_result_as_dict(sql, dbconnection=dbconnection)[1]
        return dict((obsid, lat_lon[0]) for obsid, lat_lon in latlon_dict.items())


def get_timezone_from_db(
    tablename: str,
    dbconnection: Optional[DbConnectionManager] = None,
) -> Optional[str]:
    with use_or_create_connection(dbconnection) as dbconnection:
        about_db_cols = tables_columns("about_db", dbconnection).get("about_db", [])
        ph = dbconnection.placeholder()
        if "tablename" in about_db_cols:
            res = dbconnection.execute_and_fetchall(
                f"SELECT description FROM about_db WHERE tablename = {ph} AND columnname = 'date_time' LIMIT 1;",
                (tablename,),
            )
        else:
            res = dbconnection.execute_and_fetchall(
                f'SELECT description FROM about_db WHERE "table" = {ph} AND "column" = \'date_time\' LIMIT 1;',
                (tablename,),
            )
        if not res:
            return None
        pattern = r"[(]*[\-a-zA-Z0-9 \t]*(gmt|utc)([\+\-]*)([0-9]+)([\:]*[0-9]*)\)[)]*"
        m = re.search(pattern, res[0][0], re.IGNORECASE)
        if m is not None:
            return m.group(0).lstrip("(").rstrip(")")
        m = re.search(r"\([a-zA-Z0-9åäöÅÄÖ+-/]+\)", res[0][0], re.IGNORECASE)
        if m is not None:
            return m.group(0).lstrip("(").rstrip(")")
        return None


def nonplot_tables(
    as_tuple: bool = False,
) -> Any:
    tables = (
        "about_db",
        "comments",
        "zz_flowtype",
        "zz_meteoparam",
        "zz_strat",
        "zz_hydro",
    )
    if as_tuple:
        return tables
    return "({})".format(", ".join([f"'{x}'" for x in tables]))


def create_dict_from_db_2_cols(params: tuple) -> tuple:
    """params are (col1=keys, col2=values, db-table)."""
    col1, col2, table = params
    with use_or_create_connection(None) as dbconnection:
        sqlstring = dbconnection.sql_ident(
            "SELECT {c1}, {c2} FROM {t}", c1=col1, c2=col2, t=table
        )
        connection_ok, list_of_tuples = sql_load_fr_db(
            sqlstring, dbconnection=dbconnection
        )
    if not connection_ok:
        textstring = QCoreApplication.translate(
            "create_dict_from_db_2_cols",
            """Cannot create dictionary from columns %s and %s in table %s!""",
        ) % (col1, col2, table)
        message_utils.MessagebarAndLog.warning(
            bar_msg=QCoreApplication.translate(
                "create_dict_from_db_2_cols",
                "Some sql failure, see log for additional info.",
            ),
            log_msg=textstring,
            duration=4,
            button=True,
        )
        return False, {"": ""}
    return True, dict(list_of_tuples)


def rowid_string(
    dbconnection: Optional[DbConnectionManager] = None,
) -> str:
    with use_or_create_connection(dbconnection) as dbconnection:
        return dbconnection.rowid_string()


def activate_foreign_keys(
    activated: bool = True,
    dbconnection: Optional[DbConnectionManager] = None,
) -> None:
    with use_or_create_connection(dbconnection) as dbconnection:
        dbconnection.activate_foreign_keys(activated)


def test_if_numeric(
    column: str,
    dbconnection: Optional[DbConnectionManager] = None,
) -> str:
    with use_or_create_connection(dbconnection) as dbconnection:
        col_ident = dbconnection.ident(column)
        return dbconnection.numeric_test_sql(col_ident)


def numeric_datatypes(
    dbconnection: Optional[DbConnectionManager] = None,
) -> list:
    with use_or_create_connection(dbconnection) as dbconnection:
        return dbconnection.numeric_datatypes()


def calculate_median_value(
    table: str,
    column: str,
    obsid: str,
    dbconnection: Optional[DbConnectionManager] = None,
) -> Optional[float]:
    sql = ""
    with use_or_create_connection(dbconnection) as dbconnection:
        ph = dbconnection.placeholder()
        col_ident = dbconnection.ident(column)
        table_ident = dbconnection.ident(table)
        sql, execute_args = dbconnection.median_sql(col_ident, table_ident, ph, obsid)
        # PostgreSQL's median aggregate requires at least one non-null value to exist
        # (the AVG-based subquery SQLite uses handles empty sets natively).
        if dbconnection.is_postgresql():
            if not sql_load_fr_db(
                f"SELECT {col_ident} FROM {table_ident} WHERE obsid = {ph} AND {col_ident} IS NOT NULL LIMIT 1",
                dbconnection,
                execute_args=(obsid,),
            )[1]:
                return None
        connection_ok, median_value = sql_load_fr_db(
            sql, dbconnection=dbconnection, execute_args=execute_args
        )
        try:
            return median_value[0][0] if median_value else None
        except (IndexError, TypeError):
            message_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "calculate_median_value",
                    "Median calculation error, see log message panel",
                ),
                log_msg=QCoreApplication.translate(
                    "calculate_median_value", "Sql failed: %s"
                )
                % sql,
            )
            return None


def delete_srids(
    execute_able_object: Any,
    keep_epsg_code: str,
) -> None:
    if isinstance(execute_able_object, DbConnectionManager):
        if execute_able_object.is_postgresql():
            return None
    ph = (
        execute_able_object.placeholder()
        if hasattr(execute_able_object, "placeholder")
        else "?"
    )
    delete_srid_sql_aux = (
        f"DELETE FROM spatial_ref_sys_aux WHERE srid NOT IN ({ph}, '4326')"
    )
    try:
        execute_able_object.execute(delete_srid_sql_aux, args=(keep_epsg_code,))
    except Exception:
        message_utils.MessagebarAndLog.info(log_msg=traceback.format_exc())
    delete_srid_sql = f"DELETE FROM spatial_ref_sys WHERE srid NOT IN ({ph}, '4326')"
    try:
        execute_able_object.execute(delete_srid_sql, args=(keep_epsg_code,))
    except Exception:
        message_utils.MessagebarAndLog.info(
            log_msg=QCoreApplication.translate(
                "delete_srids", "Removing srids failed using: %s"
            )
            % str(delete_srid_sql)
        )


def export_bytea_as_bytes(dbconnection: DbConnectionManager) -> None:
    if not dbconnection.is_postgresql():
        return

    def bytea2bytes(value: Any, cur: Any) -> Any:
        m = psycopg2.BINARY(value, cur)
        if m is not None:
            return m.tobytes()

    bytea2bytes_type = psycopg2.extensions.new_type(
        psycopg2.BINARY.values, "BYTEA2BYTES", bytea2bytes
    )
    psycopg2.extensions.register_type(bytea2bytes_type, dbconnection.conn)


# ---------------------------------------------------------------------------
# Domain-level DB query helpers (moved from midvatten_utils.py)
# ---------------------------------------------------------------------------


def get_last_used_flow_instruments() -> tuple:
    """Return dict-like {obsid: (flowtype, instrumentid, last_date)} from w_flow."""
    return get_sql_result_as_dict(
        "SELECT obsid, flowtype, instrumentid, max(date_time) FROM w_flow GROUP BY obsid, flowtype, instrumentid"
    )


def get_last_logger_dates() -> Any:
    """Return dict {obsid: last_imported_date} from w_levels_logger."""
    ok_or_not, obsid_last_imported_dates = get_sql_result_as_dict(
        "select obsid, max(date_time) from w_levels_logger group by obsid"
    )
    return ru(obsid_last_imported_dates, True)


def get_quality_instruments() -> tuple:
    """Return (True, tuple_of_instrument_ids) from w_qual_field, or (False, ())."""
    sql = "SELECT distinct instrument from w_qual_field"
    connection_ok, result_list = sql_load_fr_db(sql)
    if not connection_ok:
        message_utils.MessagebarAndLog.critical(
            bar_msg=message_utils.sql_failed_msg(),
            log_msg=QCoreApplication.translate(
                "get_quality_instruments",
                "Failed to get quality instruments from sql\n%s",
            )
            % sql,
        )
        return False, tuple()
    return True, ru([x[0] for x in result_list], True)


def calculate_db_table_rows() -> None:
    """Log a table of row counts for all user tables in the database."""
    results = {}
    tablenames = list(tables_columns().keys())
    sql_failed = []
    with use_or_create_connection(None) as dbconnection:
        for tablename in sorted(tablenames):
            sql = dbconnection.sql_ident("SELECT count(*) FROM {t}", t=tablename)
            connection_ok, nr_of_rows = sql_load_fr_db(sql, dbconnection=dbconnection)
            if not connection_ok:
                sql_failed.append(sql)
                continue
            results[tablename] = str(nr_of_rows[0][0])

    if sql_failed:
        message_utils.MessagebarAndLog.warning(
            bar_msg=message_utils.sql_failed_msg(),
            log_msg=QCoreApplication.translate(
                "calculate_db_table_rows", "Sql failed:\n%s\n"
            )
            % "\n".join(sql_failed),
        )

    if results:
        printable_msg = "{0:40}{1:15}".format("Tablename", "Nr of rows\n")
        printable_msg += "\n".join(
            [
                f"{table_name:40}{_nr_of_rows:15}"
                for table_name, _nr_of_rows in sorted(results.items())
            ]
        )
        message_utils.MessagebarAndLog.info(
            bar_msg=QCoreApplication.translate(
                "calculate_db_table_rows", "Calculation done, see log for results."
            ),
            log_msg=printable_msg,
        )


@waiting_cursor
def refresh_spatialite_layer_statistics() -> None:
    """Fix the "attribute table shows only 100 rows" symptom for SpatiaLite.

    Root cause: some SpatiaLite DBs (notably migrated old ones, and Midvatten
    DBs created by ``new_db()``) have a registered geometry column in
    ``geometry_columns`` but no corresponding row in
    ``geometry_columns_statistics``. QGIS's SpatiaLite provider returns
    ``featureCount() = 0`` in that state, and
    ``QgsVectorLayerCache::setFullCache(true)`` sizes its row cache as
    ``featureCount() + 100`` — capping the attribute table at 100 rows.

    Plain ``UpdateLayerStatistics()`` is not enough: if the stats row is
    missing, it returns 1 but silently refuses to insert. We have to run
    ``RecoverGeometryColumn`` first (which seeds the row) and then
    ``UpdateLayerStatistics`` to populate row_count and extents.

    No-op on PostgreSQL (PostGIS uses ANALYZE-driven statistics and is not
    affected by this bug).
    """
    with use_or_create_connection(None) as dbconnection:
        if not dbconnection.is_sqlite():
            message_utils.MessagebarAndLog.info(
                bar_msg=QCoreApplication.translate(
                    "refresh_spatialite_layer_statistics",
                    "This fix only applies to SpatiaLite databases. No action taken.",
                ),
            )
            return

        try:
            registered = dbconnection.execute_and_fetchall(
                "SELECT f_table_name, f_geometry_column, geometry_type, "
                "coord_dimension, srid FROM geometry_columns"
            )
        except Exception:
            message_utils.MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "refresh_spatialite_layer_statistics",
                    "Could not read geometry_columns — is this a SpatiaLite database?",
                ),
                log_msg=traceback.format_exc(),
            )
            return

        recovered: list[str] = []
        failed: list[str] = []
        try:
            for table, geom_col, geom_type_code, coord_dim, srid in registered:
                type_name = _SPATIALITE_GEOMETRY_TYPES.get(geom_type_code)
                dim_name = _SPATIALITE_DIMENSION_NAMES.get(coord_dim)
                if type_name is None or dim_name is None:
                    failed.append(
                        f"{table}.{geom_col} "
                        f"(unsupported geometry_type={geom_type_code!r} "
                        f"coord_dimension={coord_dim!r})"
                    )
                    continue
                ret = dbconnection.execute_and_fetchall(
                    "SELECT RecoverGeometryColumn(?, ?, ?, ?, ?)",
                    (table, geom_col, srid, type_name, dim_name),
                )
                if not ret or ret[0][0] != 1:
                    failed.append(f"{table}.{geom_col} (RecoverGeometryColumn={ret})")
                    continue
                recovered.append(f"{table}.{geom_col}")
            dbconnection.execute_and_fetchall("SELECT UpdateLayerStatistics()")
            dbconnection.commit()
        except Exception:
            message_utils.MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "refresh_spatialite_layer_statistics",
                    "Failed to refresh SpatiaLite layer statistics. The "
                    "database may be locked by another writer — try again "
                    "when no one else has the database open.",
                ),
                log_msg=traceback.format_exc(),
            )
            return

    log_lines = [
        f"Recovered {len(recovered)} geometry columns: {', '.join(recovered) or '(none)'}"
    ]
    if failed:
        log_lines.append(f"Failed on {len(failed)}: {', '.join(failed)}")

    message_utils.MessagebarAndLog.info(
        bar_msg=QCoreApplication.translate(
            "refresh_spatialite_layer_statistics",
            "Layer statistics refreshed. Reload the default layers (or the "
            "single layer) to see the full row count.",
        ),
        log_msg="\n".join(log_lines),
    )


# SpatiaLite geometry_type integer codes -> string names accepted by
# RecoverGeometryColumn. See spatialite.org: the code is
# `2000 * (dimension - 2) + class`, where class is 1..7 for the seven
# primary geometry types. Midvatten only uses POINT (1) and LINESTRING (2),
# but we map the full set so the fix isn't surprised by user-added tables.
_SPATIALITE_GEOMETRY_TYPES: dict[int, str] = {
    1: "POINT",
    2: "LINESTRING",
    3: "POLYGON",
    4: "MULTIPOINT",
    5: "MULTILINESTRING",
    6: "MULTIPOLYGON",
    7: "GEOMETRYCOLLECTION",
    1001: "POINT",
    1002: "LINESTRING",
    1003: "POLYGON",
    1004: "MULTIPOINT",
    1005: "MULTILINESTRING",
    1006: "MULTIPOLYGON",
    1007: "GEOMETRYCOLLECTION",
    2001: "POINT",
    2002: "LINESTRING",
    2003: "POLYGON",
    2004: "MULTIPOINT",
    2005: "MULTILINESTRING",
    2006: "MULTIPOLYGON",
    2007: "GEOMETRYCOLLECTION",
    3001: "POINT",
    3002: "LINESTRING",
    3003: "POLYGON",
    3004: "MULTIPOINT",
    3005: "MULTILINESTRING",
    3006: "MULTIPOLYGON",
    3007: "GEOMETRYCOLLECTION",
}

_SPATIALITE_DIMENSION_NAMES: dict[int, str] = {
    2: "XY",
    3: "XYZ",
    4: "XYZM",
}


def sql_to_parameters_units_tuple(sql: str) -> tuple:
    """Execute sql and return a sorted tuple of (parameter, (unit, ...)) pairs."""
    parameters_from_table = ru(sql_load_fr_db(sql)[1], True)
    parameters_dict: defaultdict = defaultdict(list)
    for parameter, unit in parameters_from_table:
        parameters_dict[parameter].append(unit)
    return tuple([(k, tuple(v)) for k, v in sorted(parameters_dict.items())])


def list_of_lists_from_table(tablename: str) -> list:
    """Return table contents as list-of-lists (first row = column names)."""
    table_info = get_table_info(tablename)
    table_info = ru(table_info, keep_containers=True)
    column_names = [x[1] for x in table_info]
    result = [column_names]
    with use_or_create_connection(None) as dbconnection:
        sql = dbconnection.sql_ident("SELECT * FROM {t}", t=tablename)
        table_contents = sql_load_fr_db(sql, dbconnection=dbconnection)[1]
    table_contents = ru(table_contents, keep_containers=True)
    result.extend(table_contents)
    return result
