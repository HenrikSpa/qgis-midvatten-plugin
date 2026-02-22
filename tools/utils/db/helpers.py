"""
Higher-level helpers: cast_date_time_as_epoch, cast_null, backup_db, get_srid_name, etc.
"""

import ast
import datetime
import os
import re
import zipfile
from typing import Any, Optional

import psycopg2
import qgis.core
from qgis.PyQt.QtCore import QCoreApplication

from midvatten.tools.utils.common_utils import MessagebarAndLog, returnunicode as ru
from midvatten.tools.utils.db.connection import DbConnectionManager
from midvatten.tools.utils.db.execution import (
    sql_load_fr_db,
    use_or_create_connection,
)
from midvatten.tools.utils.db.schema import (
    get_sql_result_as_dict,
    get_table_info,
    tables_columns,
)


def add_insert_or_ignore_to_sql(sql: str, dbconnection: DbConnectionManager) -> str:
    """Return SQL with INSERT OR IGNORE (SQLite) or ON CONFLICT DO NOTHING (PG)."""
    return dbconnection._backend.add_insert_or_ignore_to_sql(sql)


def backup_db(dbconnection: Optional[DbConnectionManager] = None) -> None:
    try:
        compression = zipfile.ZIP_DEFLATED
    except Exception:
        compression = zipfile.ZIP_STORED
    with use_or_create_connection(dbconnection) as dbconnection:
        if dbconnection.dbtype == "spatialite":
            dbconnection.cursor.execute("begin immediate")
            bkupname = (
                dbconnection.dbpath
                + datetime.datetime.now().strftime("%Y%m%dT%H%M")
                + ".zip"
            )
            zf = zipfile.ZipFile(bkupname, mode="w")
            zf.write(dbconnection.dbpath, compress_type=compression)
            zf.close()
            dbconnection.conn.rollback()
            MessagebarAndLog.info(
                bar_msg=ru(
                    QCoreApplication.translate(
                        "backup_db", "Database backup was written to %s "
                    )
                )
                % bkupname,
                duration=15,
            )
        else:
            MessagebarAndLog.info(
                bar_msg=ru(
                    QCoreApplication.translate(
                        "backup_db",
                        "Backup of PostGIS database not supported yet!",
                    )
                ),
                duration=15,
            )


def cast_date_time_as_epoch(
    dbconnection: Optional[DbConnectionManager] = None,
    date_time: Optional[str] = None,
) -> str:
    with use_or_create_connection(dbconnection) as dbconnection:
        return dbconnection._backend.cast_date_time_as_epoch(date_time)


def cast_null(
    data_type: str,
    dbconnection: Optional[DbConnectionManager] = None,
) -> str:
    with use_or_create_connection(dbconnection) as dbconnection:
        return dbconnection._backend.cast_null(data_type)


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
        if dbconnection.dbtype == "spatialite":
            ref_sys_name = dbconnection.execute_and_fetchall(
                "SELECT ref_sys_name FROM spatial_ref_sys WHERE srid = ?",
                (srid,),
            )[0][0]
        else:
            # PostGIS spatial_ref_sys uses srtext (WKT); extract short name (caller appends ", EPSG:srid")
            srtext = dbconnection.execute_and_fetchall(
                "SELECT srtext FROM spatial_ref_sys WHERE srid = %s",
                (srid,),
            )[0][0]
            # WKT starts with PROJCS["name", or GEOGCS["name", – use first quoted part as name
            match = re.search(r'^(?:PROJCS|GEOGCS)\["([^"]+)"', srtext)
            ref_sys_name = match.group(1) if match else srtext
        return ref_sys_name


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
                msg = ru(
                    QCoreApplication.translate(
                        "get_spatialite_db_path_from_dbsettings_string",
                        "Error message failed! Could not be converted to string!",
                    )
                )
            MessagebarAndLog.info(
                log_msg=ru(
                    QCoreApplication.translate(
                        "get_spatialite_db_path_from_dbsettings_string",
                        '%s error msg from db_settings string "%s": %s',
                    )
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
    if dbconnection.dbtype == "postgis":
        return "IS DISTINCT FROM"
    return "IS NOT"


def is_not_distinct_from(dbconnection: DbConnectionManager) -> str:
    if dbconnection.dbtype == "postgis":
        return "IS NOT DISTINCT FROM"
    return "IS"


def test_not_null_and_not_empty_string(
    table: str,
    column: str,
    dbconnection: Optional[DbConnectionManager] = None,
) -> str:
    with use_or_create_connection(dbconnection) as dbconnection:
        col_ident = dbconnection.ident(column)
        if dbconnection.dbtype == "spatialite":
            return f"{col_ident} IS NOT NULL AND {col_ident} !='' "
        table_info = [
            col
            for col in get_table_info(table, dbconnection)
            if col and col[1] == column
        ]
        if not table_info:
            return f"{col_ident} IS NOT NULL AND {col_ident} !='' "
        data_type = table_info[0][2]
        if data_type in postgresql_numeric_data_types():
            return f"{col_ident} IS NOT NULL"
        return f"{col_ident} IS NOT NULL AND {col_ident} !='' "


def postgresql_numeric_data_types() -> list:
    return [
        "smallint",
        "integer",
        "bigint",
        "decimal",
        "numeric",
        "real",
        "double precision",
    ]


def postgresql_cast_null_types() -> list:
    return [
        "text",
        "character varying",
        "timestamp with time zone",
        "timestamp without time zone",
        "date",
        "boolean",
        "geometry",
    ]


def sqlite_numeric_data_types() -> list:
    return ["integer", "double"]


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
        if dbconnection.dbtype == "spatialite":
            sql = "SELECT obsid, Y(Transform(geometry, 4326)) as lat, X(Transform(geometry, 4326)) as lon from obs_points"
        else:
            sql = "SELECT obsid, ST_Y(ST_Transform(geometry, 4326)) as lat, ST_X(ST_Transform(geometry, 4326)) as lon from obs_points"
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
    from midvatten.tools.utils.db.execution import sql_load_fr_db
    from qgis.PyQt.QtCore import QCoreApplication

    sqlstring = r"""select %s, %s from %s""" % (params)
    connection_ok, list_of_tuples = sql_load_fr_db(sqlstring)
    if not connection_ok:
        textstring = ru(
            QCoreApplication.translate(
                "create_dict_from_db_2_cols",
                """Cannot create dictionary from columns %s and %s in table %s!""",
            )
        ) % (params,)
        MessagebarAndLog.warning(
            bar_msg=QCoreApplication.translate(
                "create_dict_from_db_2_cols",
                "Some sql failure, see log for additional info.",
            ),
            log_msg=textstring,
            duration=4,
            button=True,
        )
        return False, {"": ""}
    return True, dict((k, v) for k, v in list_of_tuples)


def rowid_string(
    dbconnection: Optional[DbConnectionManager] = None,
) -> str:
    with use_or_create_connection(dbconnection) as dbconnection:
        if dbconnection.dbtype == "spatialite":
            return "ROWID"
        return "ctid"


def delete_duplicate_values(
    dbconnection: DbConnectionManager,
    tablename: str,
    primary_keys: list,
) -> None:
    if dbconnection.dbtype == "spatialite":
        rowid = "rowid"
    else:
        rowid = "ctid"
    dbconnection.execute(
        """DELETE FROM %s WHERE %s NOT IN (SELECT MIN(%s) FROM %s GROUP BY %s);"""
        % (tablename, rowid, rowid, tablename, ", ".join(primary_keys))
    )


def activate_foreign_keys(
    activated: bool = True,
    dbconnection: Optional[DbConnectionManager] = None,
) -> None:
    with use_or_create_connection(dbconnection) as dbconnection:
        if dbconnection.dbtype == "spatialite":
            if activated:
                dbconnection.execute("PRAGMA foreign_keys = ON")
            else:
                dbconnection.execute("PRAGMA foreign_keys = OFF")


def test_if_numeric(
    column: str,
    dbconnection: Optional[DbConnectionManager] = None,
) -> str:
    with use_or_create_connection(dbconnection) as dbconnection:
        col_ident = dbconnection.ident(column)
        if dbconnection.dbtype == "spatialite":
            return (
                f"(typeof({col_ident})=typeof(0.01) OR typeof({col_ident})=typeof(1))"
            )
        type_list = ", ".join("'" + dt + "'" for dt in postgresql_numeric_data_types())
        return f"pg_typeof({col_ident}) in ({type_list})"


def numeric_datatypes(
    dbconnection: Optional[DbConnectionManager] = None,
) -> list:
    with use_or_create_connection(dbconnection) as dbconnection:
        if dbconnection.dbtype == "spatialite":
            return sqlite_numeric_data_types()
        return postgresql_numeric_data_types()


def calculate_median_value(
    table: str,
    column: str,
    obsid: str,
    dbconnection: Optional[DbConnectionManager] = None,
) -> Optional[float]:
    sql = ""
    with use_or_create_connection(dbconnection) as dbconnection:
        if dbconnection.dbtype == "spatialite":
            ph = dbconnection.placeholder()
            col_ident = dbconnection.ident(column)
            table_ident = dbconnection.ident(table)
            sql = (
                f"SELECT AVG({col_ident}) "
                f"FROM (SELECT {col_ident} "
                f"      FROM {table_ident} "
                f"      WHERE obsid = {ph} "
                f"      ORDER BY {col_ident} "
                f"      LIMIT 2 - (SELECT COUNT(*) FROM {table_ident} WHERE obsid = {ph}) % 2 "
                f"      OFFSET (SELECT (COUNT(*) - 1) / 2 FROM {table_ident} WHERE obsid = {ph}))"
            )
            connection_ok, median_value = sql_load_fr_db(
                sql, dbconnection=dbconnection, execute_args=(obsid, obsid, obsid)
            )
        else:
            ph = dbconnection.placeholder()
            col_ident = dbconnection.ident(column)
            table_ident = dbconnection.ident(table)
            if not sql_load_fr_db(
                f"SELECT {col_ident} FROM {table_ident} WHERE obsid = {ph} AND {col_ident} IS NOT NULL LIMIT 1",
                dbconnection,
                execute_args=(obsid,),
            )[1]:
                return None
            sql = (
                f"SELECT median({col_ident}) FROM {table_ident} t1 WHERE obsid = {ph};"
            )
            connection_ok, median_value = sql_load_fr_db(
                sql, dbconnection, execute_args=(obsid,)
            )
        try:
            return median_value[0][0] if median_value else None
        except (IndexError, TypeError):
            MessagebarAndLog.warning(
                bar_msg=ru(
                    QCoreApplication.translate(
                        "calculate_median_value",
                        "Median calculation error, see log message panel",
                    )
                ),
                log_msg=ru(
                    QCoreApplication.translate(
                        "calculate_median_value", "Sql failed: %s"
                    )
                )
                % sql,
            )
            return None


def delete_srids(
    execute_able_object: Any,
    keep_epsg_code: str,
) -> None:
    from midvatten.tools.utils.db.connection import DbConnectionManager

    if isinstance(execute_able_object, DbConnectionManager):
        if execute_able_object.dbtype != "spatialite":
            return None
    delete_srid_sql_aux = (
        r"""delete from spatial_ref_sys_aux where srid NOT IN ('%s', '4326');"""
        % keep_epsg_code
    )
    try:
        execute_able_object.execute(delete_srid_sql_aux)
    except Exception:
        pass
    delete_srid_sql = (
        r"""delete from spatial_ref_sys where srid NOT IN ('%s', '4326');"""
        % keep_epsg_code
    )
    try:
        execute_able_object.execute(delete_srid_sql)
    except Exception:
        MessagebarAndLog.info(
            log_msg=ru(
                QCoreApplication.translate(
                    "delete_srids", "Removing srids failed using: %s"
                )
            )
            % str(delete_srid_sql)
        )


def export_bytea_as_bytes(dbconnection: DbConnectionManager) -> None:
    if dbconnection.dbtype == "spatialite":
        return

    def bytea2bytes(value: Any, cur: Any) -> Any:
        m = psycopg2.BINARY(value, cur)
        if m is not None:
            return m.tobytes()

    bytea2bytes_type = psycopg2.extensions.new_type(
        psycopg2.BINARY.values, "BYTEA2BYTES", bytea2bytes
    )
    psycopg2.extensions.register_type(bytea2bytes_type, dbconnection.conn)
