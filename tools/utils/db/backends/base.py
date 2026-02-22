"""
Abstract base for database backends. All dialect-specific logic lives in
SQLiteBackend and PostgreSQLBackend; callers use isinstance(backend, ...)
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

    @property
    @abstractmethod
    def conn(self):  # sqlite3.Connection or psycopg2 connection
        pass

    @property
    @abstractmethod
    def cursor(self):  # cursor
        pass

    @property
    def schema(self) -> str:
        """Schema name (e.g. 'public' for PostgreSQL)."""
        return "public"

    # --- Execution (single sql string, args optional) ---

    @abstractmethod
    def execute(self, sql: str, args: Optional[Sequence[Any]] = None) -> None:
        """Execute a single SQL statement. No commit."""
        pass

    @abstractmethod
    def execute_and_fetchall(
        self, sql: str, args: Optional[Sequence[Any]] = None
    ) -> list[Any]:
        """Execute and return cursor.fetchall()."""
        pass

    def execute_and_commit(
        self, sql: str, args: Optional[Sequence[Any]] = None
    ) -> None:
        """Execute and commit."""
        self.execute(sql, args=args)
        self.commit()

    def commit_and_closedb(self) -> None:
        self.commit()
        self.closedb()

    @abstractmethod
    def commit(self) -> None:
        pass

    @abstractmethod
    def closedb(self) -> None:
        pass

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
    def placeholder_sign(self) -> str:
        """Return '?' for SQLite, '%s' for PostgreSQL."""
        pass

    def placeholder_string(self, count: int) -> str:
        """Return placeholders for count parameters, e.g. '?,?,?' or '%s,%s,%s'."""
        if count <= 0:
            return ""
        return ", ".join([self.placeholder_sign()] * count)

    def ident(self, name: str, *, allowed: Optional[Iterable[str]] = None) -> str:
        """Safely quote an identifier."""
        from midvatten.tools.utils.db.dialect import ident as _ident

        return _ident(name, allowed=allowed)

    def sql_ident(self, template: str, /, **identifiers: str) -> str:
        """Format template with identifier substitutions only."""
        from midvatten.tools.utils.db.dialect import sql_ident as _sql_ident

        return _sql_ident(template, **identifiers)

    def in_clause(self, values: Sequence[Any]) -> tuple[str, list[Any]]:
        """Return (sql_fragment, args) for IN (...)."""
        from midvatten.tools.utils.db.dialect import in_clause as _in_clause

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

    def is_distinct_from_sql(self) -> str:
        """Return 'IS NOT' (SQLite) or 'IS DISTINCT FROM' (PG)."""
        raise NotImplementedError

    def is_not_distinct_from_sql(self) -> str:
        """Return 'IS' (SQLite) or 'IS NOT DISTINCT FROM' (PG)."""
        raise NotImplementedError

    def connect2db(self) -> bool:
        """Check connection is ok (e.g. not locked). Return True if ok."""
        self.check_db_is_locked()
        return self.cursor is not None

    def dump_table_2_csv(self, table_name: Optional[str] = None) -> None:
        """Export table to a temp CSV file."""
        import os
        import tempfile
        from midvatten.tools.utils.common_utils import write_printlist_to_file

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
