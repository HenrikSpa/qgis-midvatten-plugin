"""
Schema/metadata helpers: get_tables, get_table_info, get_foreign_keys, etc.
"""

import re
from typing import Any, Optional, Union
from collections import defaultdict
from collections.abc import Sequence

from qgis.PyQt.QtCore import QCoreApplication

from midvatten.tools.utils import message_utils
from midvatten.tools.utils.db_utils.connection import DbConnectionManager
from midvatten.tools.utils.db_utils.execution import (
    sql_load_fr_db,
    use_or_create_connection,
)
from midvatten.tools.utils.db_utils.backends.postgresql import postgis_internal_tables


def get_tables(
    dbconnection: Optional[DbConnectionManager] = None,
    skip_views: bool = False,
) -> list[str]:
    with use_or_create_connection(dbconnection) as dbconnection:
        tables_args: Optional[tuple] = None
        if dbconnection.is_sqlite():
            if skip_views:
                tabletype = "type='table'"
            else:
                tabletype = "type = 'table' or type = 'view'"
            tables_sql = (
                f"SELECT tbl_name FROM sqlite_master WHERE ({tabletype}) "
                f"AND tbl_name NOT IN {dbconnection.internal_tables()} "
                f"ORDER BY tbl_name"
            )
        else:
            ph = dbconnection.placeholder()
            args_list: list[str] = [dbconnection.schema]
            if skip_views:
                tabletype = "AND table_type='BASE TABLE'"
                pg_mat_views = ""
            else:
                tabletype = ""
                pg_mat_views = "UNION SELECT relname FROM pg_class WHERE relkind = 'm'"
                if dbconnection.schema.lower() != "public":
                    pg_mat_views += (
                        " AND TRIM(TRIM(REPLACE(oid::regclass::text, relname, ''), '.'), '\"') = "
                        + ph
                        + " "
                    )
                    args_list.append(dbconnection.schema)
            tables_sql = (
                "SELECT table_name FROM ("
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = " + ph + " " + tabletype + " "
                "AND table_name NOT IN "
                + postgis_internal_tables()
                + " "
                + pg_mat_views
                + ") foo "
                "ORDER BY table_name"
            )
            tables_args = tuple(args_list)
        tables = dbconnection.execute_and_fetchall(tables_sql, args=tables_args)
        return [col[0] for col in tables]


def get_table_info(
    tablename: str,
    dbconnection: Optional[DbConnectionManager] = None,
) -> Optional[
    list[
        Union[tuple[int, str, str, int, str, int], tuple[int, str, str, int, None, int]]
    ]
]:
    with use_or_create_connection(dbconnection) as dbconnection:
        if dbconnection.is_sqlite():
            columns_sql = dbconnection.sql_ident("PRAGMA table_info({t})", t=tablename)
            try:
                columns = dbconnection.execute_and_fetchall(columns_sql)
            except Exception as e:
                message_utils.MessagebarAndLog.warning(
                    bar_msg=message_utils.sql_failed_msg(),
                    log_msg=QCoreApplication.translate(
                        "get_table_info", "Sql failed: %s\nmsg:%s"
                    )
                    % (columns_sql, str(e)),
                )
                return None
        else:
            ph = dbconnection.placeholder()
            columns_sql = (
                "SELECT ordinal_position, column_name, data_type, CASE WHEN is_nullable = 'NO' THEN 1 ELSE 0 END AS notnull, column_default, 0 AS primary_key FROM information_schema.columns WHERE table_schema = "
                + ph
                + " AND table_name = "
                + ph
            )
            columns = [
                list(x)
                for x in dbconnection.execute_and_fetchall(
                    columns_sql, args=(dbconnection.schemas(), tablename)
                )
            ]
            primary_keys_sql = (
                "SELECT a.attname, format_type(a.atttypid, a.atttypmod) AS data_type "
                "FROM pg_index i "
                "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
                "WHERE i.indrelid = (SELECT (n.nspname || '.' || c.relname)::regclass FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = "
                + ph
                + " AND c.relname = "
                + ph
                + ") AND i.indisprimary;"
            )
            primary_keys = [
                x[0]
                for x in dbconnection.execute_and_fetchall(
                    primary_keys_sql,
                    args=(dbconnection.schemas(), tablename),
                )
            ]
            for column in columns:
                if column[1] in primary_keys:
                    column[5] = 1
            if not columns:
                columns_sql = (
                    "SELECT a.attnum, a.attname, pg_catalog.format_type(a.atttypid, a.atttypmod) as datatype, "
                    "a.attnotnull, NULL AS default, NULL as primary_key "
                    "FROM pg_attribute a "
                    "JOIN pg_class t on a.attrelid = t.oid "
                    "JOIN pg_namespace s on t.relnamespace = s.oid "
                    "WHERE a.attnum > 0 AND NOT a.attisdropped AND t.relname = "
                    + ph
                    + " AND s.nspname = "
                    + ph
                    + " ORDER BY a.attnum;"
                )
                columns = dbconnection.execute_and_fetchall(
                    columns_sql,
                    args=(tablename, dbconnection.schemas()),
                )
            columns = [tuple(column) for column in columns]
        return columns


def get_foreign_keys(
    table: str,
    dbconnection: Optional[DbConnectionManager] = None,
) -> dict[str, list[tuple[str, str]]]:
    with use_or_create_connection(dbconnection) as dbconnection:
        foreign_keys: defaultdict[str, list[tuple[str, str]]] = defaultdict(list)
        if dbconnection.is_sqlite():
            pragma_sql = dbconnection.sql_ident("PRAGMA foreign_key_list({t})", t=table)
            result_list = dbconnection.execute_and_fetchall(pragma_sql)
            for row in result_list:
                foreign_keys[row[2]].append((row[3], row[4]))
        else:
            ph = dbconnection.placeholder()
            sql = (
                "SELECT "
                "  conrelid::regclass AS table_from, "
                "  conname, "
                "  pg_get_constraintdef(c.oid) AS cdef "
                "FROM pg_constraint c "
                "JOIN pg_namespace n "
                "  ON n.oid = c.connamespace "
                "WHERE contype IN ('f') "
                "AND n.nspname = " + ph + " "
                "AND conrelid::regclass::text = " + ph + " "
                "ORDER BY conrelid::regclass::text, contype DESC;"
            )
            result_list = dbconnection.execute_and_fetchall(
                sql, args=(dbconnection.schema, table)
            )
            for row in result_list:
                info = row[2]
                m = re.search(
                    r"FOREIGN KEY \(([a-zA-ZåäöÅÄÖ0-9\-\_]+)\) REFERENCES ([a-zA-ZåäöÅÄÖ0-9\-\_\.]+)\(([a-zA-ZåäöÅÄÖ0-9\-\_]+)\)",
                    info,
                )
                if m:
                    res = m.groups()
                    foreign_keys[res[1]].append((res[0], res[2]))
        return dict(foreign_keys)


def get_sql_result_as_dict(
    sql: str,
    dbconnection: Optional[DbConnectionManager] = None,
    execute_args: Optional[Sequence[Any]] = None,
) -> tuple[bool, dict]:
    with use_or_create_connection(dbconnection) as dbconnection:
        connection_ok, result_list = sql_load_fr_db(
            sql,
            dbconnection=dbconnection,
            execute_args=execute_args,
        )
        if not connection_ok:
            return False, {}
        result_dict: defaultdict = defaultdict(list)
        for res in result_list:
            result_dict[res[0]].append(tuple(res[1:]))
        return True, dict(result_dict)


def verify_table_exists(
    tablename: str,
    dbconnection: Optional[DbConnectionManager] = None,
) -> bool:
    return tablename in get_tables(dbconnection=dbconnection)


def change_cast_type_for_geometry_columns(
    dbconnection: DbConnectionManager,
    table_info: list[tuple[int, str, str, int, None, int]],
    tablename: str,
) -> dict[str, str]:
    if dbconnection.is_sqlite():
        newtype = "BLOB"
    else:
        newtype = "geometry"
    geometry_columns_types = get_geometry_types(tablename, dbconnection=dbconnection)
    return dict(
        (row[1], newtype if row[1] in geometry_columns_types else row[2])
        for row in table_info
    )


def get_geometry_types(
    tablename: str,
    dbconnection: Optional[DbConnectionManager] = None,
) -> dict:
    with use_or_create_connection(dbconnection) as dbconnection:
        if dbconnection.is_sqlite():
            sql = """SELECT f_geometry_column, geometry_type FROM geometry_columns WHERE f_table_name = ?"""
            execute_args = (tablename,)
        else:
            ph = dbconnection.placeholder()
            sql = (
                "SELECT f_geometry_column, type "
                "FROM geometry_columns "
                "WHERE f_table_schema = " + ph + " "
                "AND f_table_name = " + ph + ";"
            )
            execute_args = (dbconnection.schema, tablename)
        result = get_sql_result_as_dict(
            sql,
            dbconnection=dbconnection,
            execute_args=execute_args,
        )[1]
        return result


def tables_columns(
    table: Optional[str] = None,
    dbconnection: Optional[DbConnectionManager] = None,
) -> dict[str, list[str]]:
    return dict(
        (k, [col[1] for col in v])
        for k, v in db_tables_columns_info(
            table=table, dbconnection=dbconnection
        ).items()
    )


def get_available_schemas(dbconnection: DbConnectionManager) -> list[str]:
    """Return user-visible schema names for a PostgreSQL connection.

    Returns an empty list for SQLite (no schema concept).
    Excludes PostgreSQL internal schemas (information_schema, pg_catalog, pg_toast).
    """
    if not dbconnection.is_postgresql():
        return []
    rows = dbconnection.execute_and_fetchall(
        """
        SELECT schema_name
        FROM information_schema.schemata
        WHERE schema_name NOT IN ('information_schema', 'pg_catalog', 'pg_toast')
        ORDER BY schema_name
        """
    )
    return [row[0] for row in rows]


def db_tables_columns_info(
    table: Optional[str] = None,
    dbconnection: Optional[DbConnectionManager] = None,
) -> dict[str, Any]:
    with use_or_create_connection(dbconnection) as dbconnection:
        existing_tablenames = get_tables(dbconnection=dbconnection)
        if table is not None and table not in existing_tablenames:
            return {}
        if table is None:
            tablenames = existing_tablenames
        elif not isinstance(table, (list, tuple)):
            tablenames = [table]
        else:
            tablenames = list(table)
        tables_dict = {}
        for tablename in tablenames:
            try:
                columns = get_table_info(tablename, dbconnection=dbconnection)
            except Exception:
                columns = None
            if columns is None:
                message_utils.MessagebarAndLog.warning(
                    log_msg=QCoreApplication.translate(
                        "db_tables_columns_info",
                        "Getting columns from table %s failed!",
                    )
                    % tablename
                )
                continue
            tables_dict[tablename] = columns
        return tables_dict
