"""
Database connection and query utilities.

Backends: SQLiteBackend, PostgreSQLBackend (use isinstance, not dbtype strings).
Factory: create_backend(db_settings) -> backend.
Facade: DbConnectionManager(db_settings) holds a backend and delegates.
"""

from midvatten.tools.utils.db.connection import DbConnectionManager, create_backend
from midvatten.tools.utils.db.settings import get_postgis_connections
from midvatten.tools.utils.db.backends.base import Backend
from midvatten.tools.utils.db.backends.sqlite import (
    SQLiteBackend,
    sqlite_internal_tables,
)
from midvatten.tools.utils.db.backends.postgresql import (
    PostgreSQLBackend,
    postgis_internal_tables,
)
from midvatten.tools.utils.db.dialect import (
    UnsafeIdentifierError,
    ident,
    in_clause,
    sql_ident,
    sql_literal,
    sql_literal_list,
)
from midvatten.tools.utils.db.execution import (
    check_connection_ok,
    if_connection_ok,
    placeholder,
    sql_alter_db,
    sql_load_fr_db,
    use_or_create_connection,
)
from midvatten.tools.utils.db.schema import (
    db_tables_columns_info,
    get_foreign_keys,
    get_table_info,
    get_tables,
    get_geometry_types,
    get_sql_result_as_dict,
    tables_columns,
    verify_table_exists,
    change_cast_type_for_geometry_columns,
)
from midvatten.tools.utils.db.helpers import (
    activate_foreign_keys,
    add_insert_or_ignore_to_sql,
    backup_db,
    calculate_median_value,
    cast_date_time_as_epoch,
    cast_null,
    create_dict_from_db_2_cols,
    delete_duplicate_values,
    delete_srids,
    get_dbtype,
    get_srid_name,
    get_spatialite_db_path_from_dbsettings_string,
    is_distinct_from,
    is_not_distinct_from,
    nonplot_tables,
    numeric_datatypes,
    postgresql_cast_null_types,
    postgresql_numeric_data_types,
    rowid_string,
    sqlite_numeric_data_types,
    test_if_numeric,
    test_not_null_and_not_empty_string,
)
from midvatten.tools.utils.db.sqlfile import (
    execute_sqlfile,
    execute_sqlfile_using_func,
)

# Re-export for code that expects DatabaseLockedError, connect_with_spatialite_connect, etc.
from midvatten.tools.utils.db.errors import DatabaseLockedError
from midvatten.tools.utils.db.backends.sqlite import connect_with_spatialite_connect
from midvatten.tools.utils.db.helpers import (
    export_bytea_as_bytes,
    get_all_obsids,
    get_latlon_for_all_obsids,
    get_timezone_from_db,
)

__all__ = [
    "Backend",
    "activate_foreign_keys",
    "calculate_median_value",
    "create_dict_from_db_2_cols",
    "delete_duplicate_values",
    "delete_srids",
    "DbConnectionManager",
    "PostgreSQLBackend",
    "SQLiteBackend",
    "UnsafeIdentifierError",
    "add_insert_or_ignore_to_sql",
    "backup_db",
    "cast_date_time_as_epoch",
    "cast_null",
    "change_cast_type_for_geometry_columns",
    "check_connection_ok",
    "connect_with_spatialite_connect",
    "create_backend",
    "DatabaseLockedError",
    "db_tables_columns_info",
    "execute_sqlfile",
    "execute_sqlfile_using_func",
    "export_bytea_as_bytes",
    "get_all_obsids",
    "get_dbtype",
    "get_foreign_keys",
    "get_geometry_types",
    "get_latlon_for_all_obsids",
    "get_postgis_connections",
    "get_srid_name",
    "get_sql_result_as_dict",
    "get_spatialite_db_path_from_dbsettings_string",
    "get_table_info",
    "rowid_string",
    "get_tables",
    "get_timezone_from_db",
    "ident",
    "if_connection_ok",
    "in_clause",
    "is_distinct_from",
    "is_not_distinct_from",
    "nonplot_tables",
    "numeric_datatypes",
    "placeholder",
    "postgis_internal_tables",
    "postgresql_cast_null_types",
    "postgresql_numeric_data_types",
    "sql_alter_db",
    "sql_ident",
    "sql_literal",
    "sql_literal_list",
    "sql_load_fr_db",
    "rowid_string",
    "sqlite_internal_tables",
    "sqlite_numeric_data_types",
    "tables_columns",
    "test_if_numeric",
    "test_not_null_and_not_empty_string",
    "use_or_create_connection",
    "verify_table_exists",
]
