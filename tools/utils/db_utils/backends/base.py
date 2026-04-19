"""
Abstract base for database backends. All dialect-specific logic lives in
SQLiteBackend and PostgreSQLBackend; callers use is_sqlite()/is_postgresql()
or the common interface only.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from typing import Any, Optional, Union

# Optional to avoid hard dependency on psycopg2 at import
try:
    import psycopg2.sql

    Composable = psycopg2.sql.Composable
except Exception:
    Composable = Any  # type: ignore[misc, assignment]


class Backend(ABC):
    """Common interface for SQLite and PostgreSQL backends."""

    # Backend type string for backward compatibility (db_settings key).
    # One of "spatialite", "postgis".
    dbtype: str

    def is_sqlite(self) -> bool:
        return False

    def is_postgresql(self) -> bool:
        return False

    # Subclasses must assign self._conn and self._cursor in __init__.
    @property
    def conn(self):  # sqlite3.Connection or psycopg2 connection
        return self._conn

    @property
    def cursor(self):  # cursor
        return self._cursor

    @property
    def schema(self) -> str:
        return "public"

    @schema.setter
    def schema(self, value: str) -> None:
        """No-op for backends without schema support (e.g. SQLite)."""
        pass

    # --- Execution (single sql string, args optional) ---

    def execute(self, sql: str, args: Optional[Sequence[Any]] = None) -> None:
        """Execute a single SQL statement. No commit."""
        if args is None:
            try:
                self.cursor.execute(sql)
            except Exception as e:
                Backend.log_execute_error(sql, None, e)
                raise
        else:
            try:
                self.cursor.execute(sql, list(args))
            except Exception as e:
                Backend.log_execute_error(sql, args, e)
                raise

    def execute_and_fetchall(
        self, sql: str, args: Optional[Sequence[Any]] = None
    ) -> list[Any]:
        """Execute and return cursor.fetchall()."""
        try:
            if args is not None:
                self.cursor.execute(sql, args)
            else:
                self.cursor.execute(sql)
        except Exception as e:
            Backend.log_execute_error(sql, args, e)
            raise
        return self.cursor.fetchall()

    def execute_and_commit(
        self, sql: str, args: Optional[Sequence[Any]] = None
    ) -> None:
        """Execute and commit."""
        self.execute(sql, args=args)
        self.commit()

    def commit_and_closedb(self) -> None:
        self.commit()
        self.closedb()

    def commit(self) -> None:
        self._conn.commit()

    def closedb(self) -> None:
        """Close the database connection. Override in subclasses that need cleanup before close."""
        self._conn.close()

    def execute_safe(
        self,
        sql: Union[str, Composable],
        args: Optional[Sequence[Any]] = None,
    ) -> None:
        """Execute SQL (string or, for PostgreSQL, psycopg2.sql.Composable)."""
        if args is None:
            self.cursor.execute(sql)  # type: ignore[arg-type]
        else:
            self.cursor.execute(sql, list(args))  # type: ignore[arg-type]

    # --- Placeholders and identifiers ---

    @abstractmethod
    def placeholder(self) -> str:
        """Return '?' for SQLite, '%s' for PostgreSQL."""
        pass

    def placeholders(self, count: int) -> str:
        """Return placeholders for count parameters, e.g. '?,?,?' or '%s,%s,%s'."""
        if count <= 0:
            return ""
        return ", ".join([self.placeholder()] * count)

    def ident(self, name: str, *, allowed: Optional[Iterable[str]] = None) -> str:
        """Safely quote an identifier."""
        from midvatten.tools.utils.db_utils.dialect import ident as _ident

        return _ident(name, allowed=allowed)

    def sql_ident(self, template: str, /, **identifiers: str) -> str:
        """Format template with identifier substitutions only."""
        from midvatten.tools.utils.db_utils.dialect import sql_ident as _sql_ident

        return _sql_ident(template, **identifiers)

    def in_clause(self, values: Sequence[Any]) -> tuple[str, list[Any]]:
        """Return (sql_fragment, args) for IN (...)."""
        from midvatten.tools.utils.db_utils.dialect import in_clause as _in_clause

        return _in_clause(self, values)

    # --- Schema / metadata ---

    @abstractmethod
    def internal_tables(self) -> str:
        """Return SQL tuple string of internal table names to exclude from listings."""
        pass

    def schemas(self) -> str:
        """Alias for schema (backward compat)."""
        return self.schema

    @abstractmethod
    def get_srid(
        self, table_name: str, geometry_column: str = "geometry"
    ) -> Optional[int]:
        pass

    # --- Temporary tables, views, maintenance ---

    @abstractmethod
    def create_temporary_table_for_import(
        self,
        temptable_name: str,
        fieldnames_types: list[str],
        geometry_colname_type_srid: Optional[tuple[str, str, int]] = None,
    ) -> str:
        """Create temp table; return its name (e.g. 'mem.temp_foo' for SQLite)."""
        pass

    @abstractmethod
    def drop_temporary_table(self, temptable_name: str) -> None:
        pass

    @abstractmethod
    def drop_view(self, view_name: str) -> None:
        pass

    @abstractmethod
    def check_db_is_locked(self) -> None:
        """Raise DatabaseLockedError if SQLite has -journal/-wal/-shm. No-op for PG."""
        pass

    @abstractmethod
    def vacuum(self) -> None:
        pass

    # --- Dialect-specific SQL fragments (for helpers) ---

    def add_insert_or_ignore_to_sql(self, sql: str) -> str:
        """Return SQL with INSERT OR IGNORE (SQLite) or ON CONFLICT DO NOTHING (PG)."""
        raise NotImplementedError

    def cast_date_time_as_epoch(self, date_time: Optional[str] = None) -> str:
        """Return SQL expression for casting date_time column to epoch number."""
        raise NotImplementedError

    def cast_null(self, data_type: str) -> str:
        """Return SQL for NULL cast to data_type (e.g. NULL::text for PG)."""
        raise NotImplementedError

    @abstractmethod
    def get_srid_name(self, srid: int) -> str:
        """Return the CRS name string for the given SRID."""
        pass

    @abstractmethod
    def latlon_sql(self) -> str:
        """Return SELECT SQL for obsid, lat, lon from obs_points (Y/X vs ST_Y/ST_X)."""
        pass

    @abstractmethod
    def rowid_string(self) -> str:
        """Return the row-id pseudo-column name: 'ROWID' for SQLite, 'ctid' for PG."""
        pass

    @abstractmethod
    def numeric_test_sql(self, col_ident: str) -> str:
        """Return SQL expression that is true when col_ident contains a numeric value."""
        pass

    @abstractmethod
    def not_null_sql(self, col_ident: str, data_type: Optional[str] = None) -> str:
        """Return SQL fragment asserting col_ident is NOT NULL (and not empty string for text).

        ``data_type`` is the column's declared SQL type (used by PostgreSQL to omit
        the empty-string check for numeric columns).  SQLite ignores ``data_type``.

        For SQLite (and PG text types): ``col_ident IS NOT NULL AND col_ident !=''``
        For PG numeric types: ``col_ident IS NOT NULL``
        """
        pass

    @abstractmethod
    def is_distinct_from(self) -> str:
        """Return 'IS NOT' (SQLite) or 'IS DISTINCT FROM' (PG)."""
        pass

    @abstractmethod
    def is_not_distinct_from(self) -> str:
        """Return 'IS' (SQLite) or 'IS NOT DISTINCT FROM' (PG)."""
        pass

    @abstractmethod
    def numeric_datatypes(self) -> list:
        """Return list of numeric data type names for this backend."""
        pass

    @abstractmethod
    def activate_foreign_keys(self, activated: bool) -> None:
        """Enable or disable foreign key enforcement (SQLite only; no-op for PG)."""
        pass

    @abstractmethod
    def median_sql(self, col_ident: str, table_ident: str, ph: str) -> tuple:
        """Return (sql, arg_count) for a median query over obsid."""
        pass

    @abstractmethod
    def backup(self, dbconnection: Any) -> None:
        """Perform a database backup (SQLite: zip file; PG: not supported)."""
        pass

    # --- Error logging (shared across backends) ---

    @staticmethod
    def log_execute_error(sql: str, args: Any, e: Exception) -> None:
        """Log a DB execute error via MessagebarAndLog."""
        from midvatten.tools.utils.message_utils import MessagebarAndLog, sql_failed_msg
        from midvatten.tools.utils.string_utils import returnunicode as ru
        from qgis.PyQt.QtCore import QCoreApplication

        if args is None:
            textstring = QCoreApplication.translate(
                "sql_load_fr_db",
                """DB error!\n SQL causing this error:%s\nMsg:\n%s""",
            ) % (ru(sql), str(e))
        else:
            textstring = QCoreApplication.translate(
                "sql_load_fr_db",
                """DB error!\n SQL causing this error:%s\nusing args %s\nMsg:\n%s""",
            ) % (ru(sql), ru(args), str(e))
        MessagebarAndLog.warning(bar_msg=sql_failed_msg(), log_msg=textstring)

    def connect2db(self) -> bool:
        """Check connection is ok (e.g. not locked). Return True if ok."""
        self.check_db_is_locked()
        return self.cursor is not None

    def dump_table_2_csv(self, table_name: Optional[str] = None) -> None:
        """Export table to a temp CSV file."""
        import os
        import tempfile
        from midvatten.tools.utils.file_utils import write_printlist_to_file

        if table_name is None:
            raise ValueError("table_name is required")
        self.execute_safe(self.sql_ident("SELECT * FROM {t}", t=table_name))
        header = [col[0] for col in self.cursor.description]
        rows = self.cursor.fetchall()
        if rows:
            filename = os.path.join(tempfile.gettempdir(), f"{table_name}.csv")
            printlist = [header]
            printlist.extend(rows)
            write_printlist_to_file(filename, printlist)
