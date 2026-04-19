"""
PostgreSQL (PostGIS) backend. Connection via psycopg2; connector logic merged in.
"""

import os
import re
import traceback
from typing import Any, Optional

import psycopg2
import psycopg2.extensions
import psycopg2.sql
from qgis.PyQt.QtCore import QCoreApplication, QFile
from qgis.core import QgsCredentials, QgsDataSourceUri

from midvatten.tools.utils.message_utils import MessagebarAndLog
from midvatten.tools.utils.exceptions import UserInterruptError
from midvatten.tools.utils.db_utils.backends.base import Backend
from midvatten.tools.utils.db_utils.dialect import UnsafeIdentifierError
from midvatten.tools.utils.db_utils.settings import get_postgis_connections

_ALLOWED_GEOM_TYPES: tuple[str, ...] = (
    "GEOMETRY",
    "POINT",
    "LINESTRING",
    "POLYGON",
    "MULTIPOINT",
    "MULTILINESTRING",
    "MULTIPOLYGON",
    "GEOMETRYCOLLECTION",
    "GEOMETRYZ",
    "POINTZ",
    "LINESTRINGZ",
    "POLYGONZ",
    "MULTIPOINTZ",
    "MULTILINESTRINGZ",
    "MULTIPOLYGONZ",
    "GEOMETRYCOLLECTIONZ",
    "GEOMETRYM",
    "POINTM",
    "LINESTRINGM",
    "POLYGONM",
    "GEOMETRYZM",
    "POINTZM",
    "LINESTRINGZM",
    "POLYGONZM",
)


def postgis_internal_tables(as_tuple: bool = False) -> str:
    import ast

    astring = """('geography_columns',
               'geometry_columns',
               'spatial_ref_sys',
               'raster_columns',
               'raster_overviews')"""
    if as_tuple:
        return ast.literal_eval(astring)
    return astring


def _clear_ssl_temp_certs_if_any(connection_info: str) -> None:
    expanded_uri = QgsDataSourceUri(connection_info)

    def remove_cert(cert_file: str) -> None:
        cert_file = cert_file.replace("'", "")
        file = QFile(cert_file)
        if not file.setPermissions(QFile.Permission.WriteOwner):
            raise Exception(
                f"Cannot change permissions on {file.fileName()}: error code: {file.error()}"
            )
        if not file.remove():
            raise Exception(
                f"Cannot remove {file.fileName()}: error code: {file.error()}"
            )

    for param in ("sslcert", "sslkey", "sslrootcert"):
        path = expanded_uri.param(param)
        if path:
            remove_cert(path)


class PostgreSQLBackend(Backend):
    """
    PostgreSQL (PostGIS) backend. dbtype is 'postgis' for settings compatibility.
    Connector logic from PostGisDBConnectorMod merged in.
    """

    dbtype = "postgis"

    def is_postgresql(self) -> bool:
        return True

    def __init__(self, connection_name: str, schema: str = "public") -> None:
        self._schema = schema
        self._connection_name = connection_name
        self.postgis_settings = get_postgis_connections()[connection_name]
        self.uri = QgsDataSourceUri()
        if self.postgis_settings.get("service", "").strip():
            self.uri.setConnection(
                aService=self.postgis_settings["service"],
                aDatabase=self.postgis_settings["database"],
                aUsername=self.postgis_settings.get("username"),
                aPassword=self.postgis_settings.get("password"),
            )
        else:
            self.uri.setConnection(
                self.postgis_settings["host"],
                self.postgis_settings["port"],
                self.postgis_settings["database"],
                self.postgis_settings.get("username"),
                self.postgis_settings.get("password"),
            )
        expanded_conn_info = str(self.uri.connectionInfo(True))
        username = self.uri.username() or os.environ.get("PGUSER")
        password = self.uri.password() or os.environ.get("PGPASSWORD")
        last_error: Optional[Exception] = None
        try:
            self._conn = psycopg2.connect(expanded_conn_info)
        except psycopg2.Error as e:
            last_error = e
            err = str(e)
            conninfo = self.uri.connectionInfo(False)
            for i in range(3):
                (ok, username, password) = QgsCredentials.instance().get(
                    conninfo, username, password, err
                )
                if not ok:
                    raise ConnectionError(e)
                if username:
                    self.uri.setUsername(username)
                if password:
                    self.uri.setPassword(password)
                new_expanded_conn_info = self.uri.connectionInfo(True)
                try:
                    self._conn = psycopg2.connect(new_expanded_conn_info)
                    QgsCredentials.instance().put(conninfo, username, password)
                    last_error = None
                    break
                except psycopg2.Error as e:
                    last_error = e
                    if i == 2:
                        raise ConnectionError(e)
                    err = str(e)
                finally:
                    _clear_ssl_temp_certs_if_any(new_expanded_conn_info)
        # NOTE: _clear_ssl_temp_certs_if_any is invoked twice on the retry path —
        # once per inner retry via the inner finally (for each
        # `new_expanded_conn_info`), and once after the loop via this outer
        # finally (for the original `expanded_conn_info`). In practice these
        # are different paths, so cleanup is correct; but if a retry ever
        # reused the same SSL cert path, the outer cleanup could delete a
        # cert that's still in use.
        # TODO: revisit only if that race is observed in the wild.
        finally:
            _clear_ssl_temp_certs_if_any(expanded_conn_info)
        if last_error:
            if "no password supplied" in str(last_error):
                MessagebarAndLog.warning(
                    bar_msg=QCoreApplication.translate(
                        "DbConnectionManager",
                        "No password supplied for postgis connection",
                    )
                )
                raise UserInterruptError()
            raise last_error
        self._conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        self._cursor = self._conn.cursor()
        self._set_search_path(self._schema)

    def _set_search_path(self, schema: str) -> None:
        """Execute SET search_path, always including public as fallback for PostGIS functions."""
        self._cursor.execute(
            psycopg2.sql.SQL("SET search_path = {}, public").format(
                psycopg2.sql.Identifier(schema)
            )
        )

    @property
    def schema(self) -> str:
        return self._schema

    @schema.setter
    def schema(self, value: str) -> None:
        self._schema = value
        self._set_search_path(value)

    def placeholder(self) -> str:
        return "%s"

    def internal_tables(self) -> str:
        return postgis_internal_tables()

    def get_srid(
        self, table_name: str, geometry_column: str = "geometry"
    ) -> Optional[int]:
        try:
            self._cursor.execute(
                "SELECT Find_SRID(%s, %s, %s);",
                (self.schema, table_name, geometry_column),
            )
        except Exception:
            return None
        rows = self._cursor.fetchall()
        if not rows:
            return None
        return int(rows[0][0])

    def create_temporary_table_for_import(
        self,
        temptable_name: str,
        fieldnames_types: list[str],
        geometry_colname_type_srid: Optional[tuple[str, str, int]] = None,
    ) -> str:
        if not temptable_name.startswith("temp_"):
            temptable_name = f"temp_{temptable_name}"
        table_ident = self.ident(temptable_name)
        self.execute(
            f"CREATE TEMPORARY TABLE {table_ident} ({', '.join(fieldnames_types)})"
        )
        if geometry_colname_type_srid is not None:
            geom_column, geom_type, srid = geometry_colname_type_srid
            if geom_type.upper() not in _ALLOWED_GEOM_TYPES:
                raise UnsafeIdentifierError(
                    f"Geometry type {geom_type!r} is not in the allowed list"
                )
            self.execute(
                f"ALTER TABLE {table_ident} ADD COLUMN {self.ident(geom_column)} geometry({geom_type.upper()}, {int(srid)})"
            )
        return temptable_name

    def drop_temporary_table(self, temptable_name: str) -> None:
        self.execute_safe(self.sql_ident("DROP TABLE IF EXISTS {t}", t=temptable_name))

    def drop_view(self, view_name: str) -> None:
        try:
            self.execute_safe(
                psycopg2.sql.SQL("DROP VIEW IF EXISTS {}").format(
                    psycopg2.sql.Identifier(view_name)
                )
            )
        except Exception:
            MessagebarAndLog.warning(log_msg=traceback.format_exc())

    def check_db_is_locked(self) -> None:
        pass

    def vacuum(self) -> None:
        self.execute("VACUUM ANALYZE")

    def add_insert_or_ignore_to_sql(self, sql: str) -> str:
        return sql + " ON CONFLICT DO NOTHING"

    def cast_date_time_as_epoch(self, date_time: Optional[str] = None) -> str:
        if date_time is None:
            date_time = "date_time"
        else:
            date_time = f"'{date_time}'"
        return f"""extract(epoch from {date_time}::timestamp)"""

    def cast_null(self, data_type: str) -> str:
        from midvatten.tools.utils.db_utils.dialect import UnsafeIdentifierError

        allowed = {
            "smallint",
            "integer",
            "bigint",
            "decimal",
            "numeric",
            "real",
            "double precision",
        } | {
            "text",
            "character varying",
            "timestamp with time zone",
            "timestamp without time zone",
            "date",
            "boolean",
            "geometry",
        }
        if data_type not in allowed:
            raise UnsafeIdentifierError(
                f"cast_null: data_type {data_type!r} not in allowed list"
            )
        return "NULL::" + data_type

    def get_srid_name(self, srid: int) -> str:
        srtext = self.execute_and_fetchall(
            "SELECT srtext FROM spatial_ref_sys WHERE srid = %s",
            (srid,),
        )[0][0]
        # WKT starts with PROJCS["name", or GEOGCS["name", – use first quoted part as name
        match = re.search(r'^(?:PROJCS|GEOGCS)\["([^"]+)"', srtext)
        return match.group(1) if match else srtext

    def latlon_sql(self) -> str:
        return "SELECT obsid, ST_Y(ST_Transform(geometry, 4326)) as lat, ST_X(ST_Transform(geometry, 4326)) as lon from obs_points"

    def rowid_string(self) -> str:
        return "ctid"

    def numeric_test_sql(self, col_ident: str) -> str:
        type_list = ", ".join("'" + dt + "'" for dt in self.numeric_datatypes())
        return f"pg_typeof({col_ident}) in ({type_list})"

    def not_null_sql(self, col_ident: str, data_type: Optional[str] = None) -> str:
        if data_type is not None and data_type in self.numeric_datatypes():
            return f"{col_ident} IS NOT NULL"
        return f"{col_ident} IS NOT NULL AND {col_ident} !='' "

    def is_distinct_from(self) -> str:
        return "IS DISTINCT FROM"

    def is_not_distinct_from(self) -> str:
        return "IS NOT DISTINCT FROM"

    _NUMERIC_DATATYPES = [
        "smallint",
        "integer",
        "bigint",
        "decimal",
        "numeric",
        "real",
        "double precision",
    ]

    def numeric_datatypes(self) -> list:
        return self._NUMERIC_DATATYPES

    def activate_foreign_keys(self, activated: bool) -> None:
        # PostgreSQL enforces foreign keys natively; this is a no-op.
        pass

    def median_sql(self, col_ident: str, table_ident: str, ph: str) -> tuple:
        sql = f"SELECT median({col_ident}) FROM {table_ident} t1 WHERE obsid = {ph};"
        return sql, 1

    def backup(self, dbconnection: Any) -> None:
        from midvatten.tools.utils.message_utils import MessagebarAndLog
        from qgis.PyQt.QtCore import QCoreApplication

        MessagebarAndLog.info(
            bar_msg=QCoreApplication.translate(
                "backup_db",
                "Backup of PostGIS database not supported yet!",
            ),
            duration=15,
        )
