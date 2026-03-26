"""
Connection factory and DbConnectionManager facade.
"""

import ast
import os
from typing import Any, Optional

import qgis.core
from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import QgsProject

from midvatten.tools.utils.common_utils import (
    MessagebarAndLog,
    returnunicode as ru,
    UsageError,
)
from midvatten.tools.utils.db_utils.backends.base import Backend
from midvatten.tools.utils.db_utils.backends.postgresql import PostgreSQLBackend
from midvatten.tools.utils.db_utils.backends.sqlite import SQLiteBackend
from midvatten.tools.utils.db_utils.errors import DatabaseLockedError
from midvatten.tools.utils.db_utils.settings import get_postgis_connections


def _parse_db_settings(db_settings: Optional[str]) -> tuple:
    """Return (dbtype, connection_settings) from db_settings string or dict."""
    if db_settings is None:
        db_settings = qgis.core.QgsProject.instance().readEntry(
            "Midvatten", "database"
        )[0]
    if isinstance(db_settings, str):
        if os.path.isfile(db_settings):
            db_settings = {"spatialite": {"dbpath": db_settings}}
        else:
            if not db_settings:
                raise UsageError(
                    QCoreApplication.translate(
                        "DbConnectionManager",
                        "Database setting was empty. Check DB tab in Midvatten settings.",
                    )
                )
            try:
                db_settings = ast.literal_eval(db_settings)
            except Exception:
                raise UsageError(
                    QCoreApplication.translate(
                        "DbConnectionManager",
                        "Database could not be set. Check DB tab in Midvatten settings.",
                    )
                )
    elif not isinstance(db_settings, dict):
        raise Exception(
            QCoreApplication.translate(
                "DbConnectionManager",
                "DbConnectionManager programming error: db_settings must be either a dict like {'spatialite': {'dbpath': 'x'} or a string representation of it. Was: %s",
            )
            % ru(db_settings)
        )
    db_settings = ru(db_settings, keep_containers=True)
    dbtype = list(db_settings.keys())[0]
    connection_settings = list(db_settings.values())[0]
    return dbtype, connection_settings, db_settings


def create_backend(db_settings: Optional[str] = None) -> Backend:
    """Create and return a Backend (SQLiteBackend or PostgreSQLBackend)."""
    dbtype, connection_settings, _ = _parse_db_settings(db_settings)
    if dbtype == "spatialite":
        return SQLiteBackend(dbpath=connection_settings["dbpath"])
    if dbtype == "postgis":
        return PostgreSQLBackend(
            connection_name=connection_settings["connection"].split("/")[0],
        )
    raise UsageError(
        QCoreApplication.translate(
            "DbConnectionManager",
            "Unsupported database type: %s",
        )
        % dbtype
    )


class DbConnectionManager:
    """
    Facade that holds a backend and delegates all operations.
    Keeps .dbtype, .db_settings, .connection_settings, .uri, .dbpath, .postgis_settings
    for backward compatibility with code that reads these attributes.
    """

    def __init__(self, db_settings: Optional[str] = None):
        dbtype, connection_settings, db_settings = _parse_db_settings(db_settings)
        self.dbtype = dbtype
        self.connection_settings = connection_settings
        self.db_settings = db_settings
        self._backend = create_backend(db_settings)
        # Backward-compat attributes (some code reads .dbpath, .uri, .postgis_settings)
        self.dbpath = getattr(self._backend, "dbpath", None)
        self.uri = getattr(self._backend, "uri", None)
        self.postgis_settings = getattr(self._backend, "postgis_settings", None)
        self.schema = self._backend.schema

    @property
    def conn(self):
        return self._backend.conn

    @property
    def cursor(self):
        return self._backend.cursor

    def connect2db(self) -> bool:
        return self._backend.connect2db()

    def execute(
        self, sql: str, args: Optional[Any] = None, all_args: Optional[Any] = None
    ) -> None:
        a = args if args is not None else all_args
        # One-row list: all_args=[(v1,..)] -> pass (v1,..); do not unwrap tuple ("P1",)
        if isinstance(a, list) and len(a) == 1:
            a = a[0]
        self._backend.execute(sql, args=a)

    def execute_and_fetchall(self, sql: str, args: Optional[Any] = None) -> list:
        return self._backend.execute_and_fetchall(sql, args=args)

    def execute_and_commit(
        self, sql: str, args: Optional[Any] = None, all_args: Optional[Any] = None
    ) -> None:
        a = args if args is not None else all_args
        # One-row list: all_args=[(v1,..)] -> pass (v1,..); do not unwrap tuple ("P1",)
        if isinstance(a, list) and len(a) == 1:
            a = a[0]
        self._backend.execute_and_commit(sql, args=a)

    def commit(self) -> None:
        self._backend.commit()

    def commit_and_closedb(self) -> None:
        self._backend.commit_and_closedb()

    def closedb(self) -> None:
        self._backend.closedb()

    def schemas(self) -> str:
        return self._backend.schemas()

    def internal_tables(self) -> str:
        return self._backend.internal_tables()

    def check_db_is_locked(self) -> None:
        self._backend.check_db_is_locked()

    def vacuum(self) -> None:
        self._backend.vacuum()

    def create_temporary_table_for_import(
        self,
        temptable_name: str,
        fieldnames_types: list,
        geometry_colname_type_srid: Optional[tuple] = None,
    ) -> str:
        return self._backend.create_temporary_table_for_import(
            temptable_name,
            fieldnames_types,
            geometry_colname_type_srid,
        )

    def drop_temporary_table(self, temptable_name: str) -> None:
        self._backend.drop_temporary_table(temptable_name)

    def dump_table_2_csv(self, table_name: Optional[str] = None) -> None:
        self._backend.dump_table_2_csv(table_name)

    def get_srid(
        self, table_name: str, geometry_column: str = "geometry"
    ) -> Optional[int]:
        return self._backend.get_srid(table_name, geometry_column)

    def placeholder(self) -> str:
        return self._backend.placeholder()

    def placeholders(self, count: int) -> str:
        return self._backend.placeholders(count)

    def ident(self, name: str, *, allowed: Optional[Any] = None) -> str:
        return self._backend.ident(name, allowed=allowed)

    def sql_ident(self, template: str, /, **identifiers: str) -> str:
        return self._backend.sql_ident(template, **identifiers)

    def in_clause(self, values: Any) -> tuple:
        return self._backend.in_clause(values)

    def execute_safe(self, sql: Any, args: Optional[Any] = None) -> None:
        self._backend.execute_safe(sql, args=args)

    def drop_view(self, view_name: str) -> None:
        self._backend.drop_view(view_name)

    def add_insert_or_ignore_to_sql(self, sql: str) -> str:
        return self._backend.add_insert_or_ignore_to_sql(sql)

    def cast_date_time_as_epoch(self, date_time: Optional[str] = None) -> str:
        return self._backend.cast_date_time_as_epoch(date_time)

    def cast_null(self, data_type: str) -> str:
        return self._backend.cast_null(data_type)

    def get_srid_name(self, srid: int) -> str:
        return self._backend.get_srid_name(srid)

    def latlon_sql(self) -> str:
        return self._backend.latlon_sql()

    def rowid_string(self) -> str:
        return self._backend.rowid_string()

    def numeric_test_sql(self, col_ident: str) -> str:
        return self._backend.numeric_test_sql(col_ident)

    def not_null_sql(self, col_ident: str, data_type: Optional[str] = None) -> str:
        return self._backend.not_null_sql(col_ident, data_type)

    def is_distinct_from(self) -> str:
        return self._backend.is_distinct_from()

    def is_not_distinct_from(self) -> str:
        return self._backend.is_not_distinct_from()

    def is_postgresql(self) -> bool:
        """Return True if the backend is PostgreSQL (PostGIS)."""
        from midvatten.tools.utils.db_utils.backends.postgresql import PostgreSQLBackend

        return isinstance(self._backend, PostgreSQLBackend)

    def numeric_datatypes(self) -> list:
        return self._backend.numeric_datatypes()

    def activate_foreign_keys(self, activated: bool) -> None:
        self._backend.activate_foreign_keys(activated)

    def median_sql(self, col_ident: str, table_ident: str, ph: str) -> tuple:
        return self._backend.median_sql(col_ident, table_ident, ph)

    def backup(self) -> None:
        self._backend.backup(self)
