"""
SQLite (Spatialite) backend. Connection via spatialite_connect.
"""

import ast
import os
import traceback
from sqlite3 import Connection
from typing import Any, Optional

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import QgsDataSourceUri
from qgis.utils import spatialite_connect

import sqlite3 as sqlite

from midvatten.tools.utils.message_utils import MessagebarAndLog
from midvatten.tools.utils.string_utils import returnunicode as ru
from midvatten.tools.utils.exceptions import UsageError
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

    def is_sqlite(self) -> bool:
        return True

    def __init__(
        self,
        dbpath: str,
        conn: Optional[Connection] = None,
    ):
        self._dbpath = ru(dbpath)
        if not os.path.isfile(self._dbpath):
            raise UsageError(
                QCoreApplication.translate(
                    "DbConnectionManager",
                    'Database error! File "%s" not found! Check db tab in Midvatten settings!',
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
                    bar_msg=QCoreApplication.translate(
                        "DbConnectionManager",
                        "Connecting to spatialite db %s failed! Check that the file or path exists.",
                    )
                    % self._dbpath,
                    log_msg=QCoreApplication.translate("DbConnectionManager", "msg %s")
                    % str(e),
                )
                raise
        self._cursor = self._conn.cursor()
        self.uri = QgsDataSourceUri()
        self.uri.setDatabase(self._dbpath)

    @property
    def dbpath(self) -> str:
        return self._dbpath

    def closedb(self) -> None:
        try:
            self._conn.rollback()
        except Exception:
            pass
        self._conn.close()

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
                MessagebarAndLog.info(
                    log_msg=QCoreApplication.translate(
                        "create_temporary_table_for_import",
                        "attaching memory database failed, %s",
                    )
                    % traceback.format_exc()
                )
        quoted_name = self.ident(temptable_name)
        if geometry_colname_type_srid is not None:
            fieldnames_types.append("geometry %s" % geometry_colname_type_srid[0])
            cols = ", ".join(fieldnames_types)
            sql = f"CREATE table {quoted_name} (id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, {cols})"
            self.execute(sql)
            self._conn.commit()
        else:
            cols = ", ".join(fieldnames_types)
            sql = f"CREATE table {quoted_name} ({cols})"
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
        for ext in ("journal", "wal"):
            msg = (
                QCoreApplication.translate(
                    "DbConnectionManager",
                    "Error, The database is already in use (a %s-file was found)",
                )
                % ext
            )
            if os.path.exists(f"{self._dbpath}-{ext}"):
                raise DatabaseLockedError(msg)

    def vacuum(self) -> None:
        # Workaround https://bugs.python.org/issue28518 — VACUUM cannot run
        # inside a transaction; set isolation_level=None (autocommit) first.
        self._conn.isolation_level = None
        self._cursor.execute("VACUUM")
        self._conn.isolation_level = ""  # reset to default (deferred)

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

    def get_srid_name(self, srid: int) -> str:
        return self.execute_and_fetchall(
            "SELECT ref_sys_name FROM spatial_ref_sys WHERE srid = ?",
            (srid,),
        )[0][0]

    def latlon_sql(self) -> str:
        return "SELECT obsid, Y(Transform(geometry, 4326)) as lat, X(Transform(geometry, 4326)) as lon from obs_points"

    def rowid_string(self) -> str:
        return "ROWID"

    def numeric_test_sql(self, col_ident: str) -> str:
        return f"(typeof({col_ident})=typeof(0.01) OR typeof({col_ident})=typeof(1))"

    def not_null_sql(self, col_ident: str, data_type: Optional[str] = None) -> str:
        return f"{col_ident} IS NOT NULL AND {col_ident} !='' "

    def is_distinct_from(self) -> str:
        return "IS NOT"

    def is_not_distinct_from(self) -> str:
        return "IS"

    _NUMERIC_DATATYPES = ["integer", "double"]

    def numeric_datatypes(self) -> list:
        return self._NUMERIC_DATATYPES

    def activate_foreign_keys(self, activated: bool) -> None:
        if activated:
            self.execute("PRAGMA foreign_keys = ON")
        else:
            self.execute("PRAGMA foreign_keys = OFF")

    def median_sql(self, col_ident: str, table_ident: str, ph: str) -> tuple:
        sql = (
            f"SELECT AVG({col_ident}) "
            f"FROM (SELECT {col_ident} "
            f"      FROM {table_ident} "
            f"      WHERE obsid = {ph} "
            f"      ORDER BY {col_ident} "
            f"      LIMIT 2 - (SELECT COUNT(*) FROM {table_ident} WHERE obsid = {ph}) % 2 "
            f"      OFFSET (SELECT (COUNT(*) - 1) / 2 FROM {table_ident} WHERE obsid = {ph}))"
        )
        return sql, 3

    def backup(self, dbconnection: Any) -> None:
        import datetime
        import zipfile

        from midvatten.tools.utils.message_utils import MessagebarAndLog
        from qgis.PyQt.QtCore import QCoreApplication

        try:
            compression = zipfile.ZIP_DEFLATED
        except Exception:
            compression = zipfile.ZIP_STORED
        self._conn.rollback()
        self._cursor.execute("begin immediate")
        bkupname = (
            self._dbpath + datetime.datetime.now().strftime("%Y%m%dT%H%M") + ".zip"
        )
        try:
            with zipfile.ZipFile(bkupname, mode="w") as zf:
                zf.write(self._dbpath, compress_type=compression)
        finally:
            self._conn.rollback()
        MessagebarAndLog.info(
            bar_msg=QCoreApplication.translate(
                "backup_db", "Database backup was written to %s "
            )
            % bkupname,
            duration=15,
        )
