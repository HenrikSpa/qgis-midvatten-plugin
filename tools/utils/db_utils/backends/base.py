"""
Abstract base for database backends. All dialect-specific logic lives in
SQLiteBackend and PostgreSQLBackend; callers use is_sqlite()/is_postgresql()
or the common interface only.
"""

import atexit
import os
import shutil
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from typing import Any, Optional, Union

from midvatten.tools.utils.file_utils import write_printlist_to_file
from midvatten.tools.utils import message_utils

# Each dump_table_2_csv() call creates a fresh, private mkdtemp() dir for its
# CSV file. Track them here and sweep on process exit so a long QGIS session
# doesn't accumulate one orphaned dir per CSV dump.
_created_tmp_dirs: list[str] = []


def _cleanup_csv_dirs() -> None:
    """Remove every CSV-dump temp dir created this session. Registered
    with atexit; also callable directly (e.g. from tests)."""
    for d in _created_tmp_dirs:
        shutil.rmtree(d, ignore_errors=True)


atexit.register(_cleanup_csv_dirs)

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

    def _execute(
        self,
        sql: Union[str, Composable],
        args: Optional[Sequence[Any]],
        *,
        normalize_args: bool,
    ) -> None:
        """Run cursor.execute, logging and re-raising on error.

        ``normalize_args`` mirrors the historical difference between the two
        public callers: execute() coerces args to a list, execute_and_fetchall()
        passes them through unchanged.
        """
        try:
            if args is None:
                self.cursor.execute(sql)  # type: ignore[arg-type]
            else:
                exec_args = list(args) if normalize_args else args
                self.cursor.execute(sql, exec_args)  # type: ignore[arg-type]
        except Exception as e:
            Backend.log_execute_error(sql, args, e)
            raise

    def execute(
        self,
        sql: Union[str, Composable],
        args: Optional[Sequence[Any]] = None,
    ) -> None:
        """Execute a single SQL statement (string or, for PostgreSQL,
        psycopg2.sql.Composable). No commit. Logs and re-raises on error."""
        self._execute(sql, args, normalize_args=True)

    def execute_and_fetchall(
        self, sql: str, args: Optional[Sequence[Any]] = None
    ) -> list[Any]:
        """Execute and return cursor.fetchall()."""
        self._execute(sql, args, normalize_args=False)
        return self.cursor.fetchall()

    def execute_and_commit(
        self, sql: str, args: Optional[Sequence[Any]] = None
    ) -> None:
        """Execute and commit."""
        self.execute(sql, args=args)
        self.commit()

    def executemany(self, sql: str, args_list: Sequence[Sequence[Any]]) -> None:
        """Execute sql once per row in args_list using cursor.executemany()."""
        try:
            self.cursor.executemany(sql, args_list)
        except Exception as e:
            Backend.log_execute_error(sql, args_list, e)
            raise

    def commit_and_closedb(self) -> None:
        self.commit()
        self.closedb()

    def commit(self) -> None:
        self._conn.commit()

    def cancel(self) -> None:
        """Interrupt the statement currently running on this connection."""
        interrupt = getattr(self._conn, "interrupt", None)
        if interrupt is not None:
            interrupt()
            return
        cancel = getattr(self._conn, "cancel", None)
        if cancel is not None:
            cancel()

    def closedb(self) -> None:
        """Close the database connection. Override in subclasses that need cleanup before close."""
        self._conn.close()

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

    def cast_date_time_as_epoch(
        self, date_time: Optional[str] = None
    ) -> tuple[str, tuple]:
        """Return a (sql_fragment, args) pair for casting to an epoch number.

        When ``date_time`` is None the fragment references the column
        ``date_time`` and ``args`` is empty. When ``date_time`` is a string,
        the fragment embeds a backend placeholder and ``args`` is a 1-tuple
        with the value — callers must splice both into the composed SQL so
        the value is parameter-bound, never concatenated.
        """
        raise NotImplementedError

    def truncate_to_minute_sql(self, col_expr: str) -> str:
        """Return SQL expression that truncates col_expr to minute precision."""
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
    def normalized_instant_sql(self, col_expr: str) -> str:
        """SQL expression normalizing a date_time column to a comparable second instant.

        Used so duplicate detection matches the unique-index definition on each
        backend. col_expr is an already-safe SQL column reference (e.g. a quoted
        identifier or 'd."date_time"').
        """
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
    def median_sql(
        self, col_ident: str, table_ident: str, ph: str, obsid: Any
    ) -> tuple[str, tuple]:
        """Return (sql, args) for a median query over obsid.

        args is the tuple to pass directly to execute; the caller does not need
        to know how many placeholders the SQL contains.
        """
        pass

    @abstractmethod
    def backup(self, dbconnection: Any) -> None:
        """Perform a database backup (SQLite: zip file; PG: not supported)."""
        pass

    # --- Error logging (shared across backends) ---

    @staticmethod
    def log_execute_error(sql: Union[str, Composable], args: Any, e: Exception) -> None:
        """Log a DB execute error via message_utils.MessagebarAndLog."""
        from midvatten.tools.utils.string_utils import returnunicode as ru
        from qgis.PyQt.QtCore import QCoreApplication

        sql_text = sql if isinstance(sql, str) else str(sql)
        if args is None:
            textstring = QCoreApplication.translate(
                "sql_load_fr_db",
                """DB error!\n SQL causing this error:%s\nMsg:\n%s""",
            ) % (ru(sql_text), str(e))
        else:
            textstring = QCoreApplication.translate(
                "sql_load_fr_db",
                """DB error!\n SQL causing this error:%s\nusing args %s\nMsg:\n%s""",
            ) % (ru(sql_text), ru(args), str(e))
        message_utils.MessagebarAndLog.warning(
            bar_msg=message_utils.sql_failed_msg(), log_msg=textstring
        )

    def connect2db(self) -> bool:
        """Check connection is ok (e.g. not locked). Return True if ok."""
        self.check_db_is_locked()
        return self.cursor is not None

    def dump_table_2_csv(self, table_name: Optional[str] = None) -> None:
        """Export table to a temp CSV file."""
        if table_name is None:
            raise ValueError("table_name is required")
        self.execute(self.sql_ident("SELECT * FROM {t}", t=table_name))
        if self.cursor.description is None:
            raise ValueError(f"dump_table_2_csv: no result set for {table_name!r}")
        header = [col[0] for col in self.cursor.description]
        rows = self.cursor.fetchall()
        if rows:
            csv_dir = tempfile.mkdtemp(prefix="midvatten_csv_")
            _created_tmp_dirs.append(csv_dir)
            filename = os.path.join(csv_dir, f"{table_name}.csv")
            printlist = [header]
            printlist.extend(rows)
            write_printlist_to_file(filename, printlist)
