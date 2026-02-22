"""
SQLite (Spatialite) backend. Connection via spatialite_connect.
"""

import ast
import os
import traceback
from collections.abc import Sequence
from sqlite3 import Connection
from typing import Any, Optional

import qgis.core
from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import QgsDataSourceUri
from qgis.utils import spatialite_connect

import sqlite3 as sqlite

from midvatten.tools.utils.common_utils import (
    MessagebarAndLog,
    returnunicode as ru,
    UsageError,
    sql_failed_msg,
)
from midvatten.tools.utils.db_utils.backends.base import Backend
from midvatten.tools.utils.db_utils.errors import DatabaseLockedError


def sqlite_internal_tables(as_tuple: bool = False) -> str:
    astring = """('ElementaryGeometries',
                'geom_cols_ref_sys',
                'geometry_columns',
                'geometry_columns_time',
                'spatial_ref_sys',
                'spatial_ref_sys_aux',
                'spatial_ref_sys_all',
                'spatialite_history',
                'vector_layers',
                'views_geometry_columns',
                'virts_geometry_columns',
                'geometry_columns_auth',
                'geometry_columns_fields_infos',
                'geometry_columns_field_infos',
                'geometry_columns_statistics',
                'sql_statements_log',
                'layer_statistics',
                'sqlite_sequence',
                'sqlite_stat1',
                'sqlite_stat3',
                'views_layer_statistics',
                'virts_layer_statistics',
                'vector_layers_auth',
                'vector_layers_field_infos',
                'vector_layers_statistics',
                'views_geometry_columns_auth',
                'views_geometry_columns_field_infos',
                'views_geometry_columns_statistics',
                'virts_geometry_columns_auth',
                'virts_geometry_columns_field_infos',
                'virts_geometry_columns_statistics' ,
                'geometry_columns',
                'spatialindex',
                'SpatialIndex',
                'KNN',
                'KNN2',
                'data_licenses')"""
    if as_tuple:
        return ast.literal_eval(astring)
    return astring


def connect_with_spatialite_connect(dbpath: str) -> Connection:
    conn = spatialite_connect(
        dbpath, detect_types=sqlite.PARSE_DECLTYPES | sqlite.PARSE_COLNAMES
    )
    return conn


class SQLiteBackend(Backend):
    """SQLite (Spatialite) backend. dbtype is 'spatialite' for settings compatibility."""

    dbtype = "spatialite"

    def __init__(
        self,
        dbpath: str,
        conn: Optional[Connection] = None,
    ):
        self._dbpath = ru(dbpath)
        if not os.path.isfile(self._dbpath):
            raise UsageError(
                ru(
                    QCoreApplication.translate(
                        "DbConnectionManager",
                        'Database error! File "%s" not found! Check db tab in Midvatten settings!',
                    )
                )
                % self._dbpath
            )
        self.check_db_is_locked()
        if conn is not None:
            self._conn = conn
        else:
            try:
                self._conn = spatialite_connect(
                    self._dbpath,
                    detect_types=sqlite.PARSE_DECLTYPES | sqlite.PARSE_COLNAMES,
                )
            except Exception as e:
                MessagebarAndLog.critical(
                    bar_msg=ru(
                        QCoreApplication.translate(
                            "DbConnectionManager",
                            "Connecting to spatialite db %s failed! Check that the file or path exists.",
                        )
                    )
                    % self._dbpath,
                    log_msg=ru(
                        QCoreApplication.translate("DbConnectionManager", "msg %s")
                    )
                    % str(e),
                )
                raise
        self._cursor = self._conn.cursor()
        self.uri = QgsDataSourceUri()
        self.uri.setDatabase(self._dbpath)

    @property
    def conn(self) -> Connection:
        return self._conn

    @property
    def cursor(self):
        return self._cursor

    @property
    def dbpath(self) -> str:
        return self._dbpath

    def connect2db(self) -> bool:
        self.check_db_is_locked()
        return self._cursor is not None

    def execute(self, sql: str, args: Optional[Sequence[Any]] = None) -> None:
        if args is None:
            try:
                self._cursor.execute(sql)
            except Exception as e:
                _log_execute_error(sql, None, e)
                raise
        else:
            try:
                self._cursor.execute(sql, list(args))
            except Exception as e:
                _log_execute_error(sql, args, e)
                raise

    def execute_and_fetchall(
        self, sql: str, args: Optional[Sequence[Any]] = None
    ) -> list[Any]:
        try:
            if args is not None:
                self._cursor.execute(sql, args)
            else:
                self._cursor.execute(sql)
        except (sqlite.OperationalError, Exception) as e:
            textstring = ru(
                QCoreApplication.translate(
                    "sql_load_fr_db",
                    """DB error!\n SQL causing this error:%s\nMsg:\n%s""",
                )
            ) % (ru(sql), ru(str(e)))
            MessagebarAndLog.warning(bar_msg=sql_failed_msg(), log_msg=textstring)
            raise
        return self._cursor.fetchall()

    def commit(self) -> None:
        self._conn.commit()

    def closedb(self) -> None:
        self._conn.close()

    def execute_safe(
        self,
        sql: Any,
        args: Optional[Sequence[Any]] = None,
    ) -> None:
        if args is None:
            self._cursor.execute(str(sql))
        else:
            self._cursor.execute(str(sql), list(args))

    def placeholder(self) -> str:
        return "?"

    def internal_tables(self) -> str:
        return sqlite_internal_tables()

    def get_srid(
        self, table_name: str, geometry_column: str = "geometry"
    ) -> Optional[int]:
        srid = self.execute_and_fetchall(
            "SELECT srid FROM geometry_columns WHERE f_table_name = ?",
            (table_name,),
        )
        if not srid:
            return None
        return int(srid[0][0])

    def create_temporary_table_for_import(
        self,
        temptable_name: str,
        fieldnames_types: list[str],
        geometry_colname_type_srid: Optional[tuple[str, str, int]] = None,
    ) -> str:
        if not temptable_name.startswith("temp_"):
            temptable_name = f"temp_{temptable_name}"
        temptable_name = "mem." + temptable_name
        try:
            self._cursor.execute("""ATTACH DATABASE ':memory:' AS mem""")
        except Exception as e:
            if "database mem is already in use" not in str(e):
                try:
                    MessagebarAndLog.info(
                        log_msg=ru(
                            QCoreApplication.translate(
                                "create_temporary_table_for_import",
                                "attaching memory database failed, %s",
                            )
                        )
                        % traceback.format_exc()
                    )
                except Exception:
                    pass
        if geometry_colname_type_srid is not None:
            fieldnames_types.append("geometry %s" % geometry_colname_type_srid[0])
            sql = (
                """CREATE table %s (id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, %s)"""
                % (temptable_name, ", ".join(fieldnames_types))
            )
            self.execute(sql)
            self._conn.commit()
        else:
            sql = """CREATE table %s (%s)""" % (
                temptable_name,
                ", ".join(fieldnames_types),
            )
            self.execute(sql)
        return temptable_name

    def drop_temporary_table(self, temptable_name: str) -> None:
        self.execute_safe(self.sql_ident("DROP TABLE {t}", t=temptable_name))

    def drop_view(self, view_name: str) -> None:
        try:
            self._cursor.execute(
                "DELETE FROM views_geometry_columns WHERE view_name = ?",
                (view_name,),
            )
            self.execute_safe(self.sql_ident("DROP VIEW IF EXISTS {v}", v=view_name))
        except Exception:
            MessagebarAndLog.warning(log_msg=traceback.format_exc())

    def check_db_is_locked(self) -> None:
        for ext in ("journal", "wal", "shm"):
            msg = (
                ru(
                    QCoreApplication.translate(
                        "DbConnectionManager",
                        "Error, The database is already in use (a %s-file was found)",
                    )
                )
                % ext
            )
            if os.path.exists(f"{self._dbpath}-{ext}"):
                raise DatabaseLockedError(msg)

    def vacuum(self) -> None:
        self.execute("VACUUM")

    def add_insert_or_ignore_to_sql(self, sql: str) -> str:
        return sql.replace("INSERT", "INSERT OR IGNORE")

    def cast_date_time_as_epoch(self, date_time: Optional[str] = None) -> str:
        if date_time is None:
            date_time = "date_time"
        else:
            date_time = f"'{date_time}'"
        return f"""CAST(strftime('%s', {date_time}) AS NUMERIC)"""

    def cast_null(self, data_type: str) -> str:
        return "NULL"

    def is_distinct_from_sql(self) -> str:
        return "IS NOT"

    def is_not_distinct_from_sql(self) -> str:
        return "IS"


def _log_execute_error(sql: str, args: Any, e: Exception) -> None:
    if args is None:
        textstring = ru(
            QCoreApplication.translate(
                "sql_load_fr_db",
                """DB error!\n SQL causing this error:%s\nMsg:\n%s""",
            )
        ) % (ru(sql), ru(str(e)))
    else:
        textstring = ru(
            QCoreApplication.translate(
                "sql_load_fr_db",
                """DB error!\n SQL causing this error:%s\nusing args %s\nMsg:\n%s""",
            )
        ) % (ru(sql), ru(args), ru(str(e)))
    MessagebarAndLog.warning(bar_msg=sql_failed_msg(), log_msg=textstring)
