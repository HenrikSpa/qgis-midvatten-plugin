"""ExportEngine — pure-Python, chunk-based export from any DbConnectionManager
source to a SpatiaLite destination."""

import logging
import threading
from typing import Callable

from midvatten.tools.utils import db_utils
from midvatten.tools.utils.db_utils import DbConnectionManager
from midvatten.definitions import midvatten_defs as defs

log = logging.getLogger(__name__)


class ExportCancelledError(Exception):
    pass


class ExportEngine:
    CHUNK_SIZE = 5_000

    def _get_columns(self, tname: str, conn: DbConnectionManager) -> list[str]:
        """Return column names for a table, lowercased, in definition order."""
        conn.execute_safe(f"SELECT * FROM {db_utils.ident(tname)} LIMIT 0")
        return [x[0].lower() for x in conn.cursor.description]

    def _get_exportable_columns(
        self,
        tname: str,
        source_conn: DbConnectionManager,
        dest_conn: DbConnectionManager,
        is_migration: bool = False,
    ) -> tuple[list[str], list[str]]:
        """Return (src_select_cols, dst_insert_cols).

        Only columns present in both (after optional name mapping) are included.
        For migration mode, the source 'source' column maps to dest 'series_id'.
        """
        src_cols = self._get_columns(tname, source_conn)
        dst_cols_set = set(self._get_columns(tname, dest_conn))

        src_select: list[str] = []
        dst_insert: list[str] = []
        for col in src_cols:
            mapped = "series_id" if (is_migration and col == "source") else col
            if mapped in dst_cols_set:
                src_select.append(col)
                dst_insert.append(mapped)
        return src_select, dst_insert

    def _build_select_sql(
        self,
        tname: str,
        source_conn: DbConnectionManager,
        select_cols: list[str],
        dest_srid: str,
        obsids: tuple[str, ...],
    ) -> tuple[str, list]:
        """Return (SELECT sql, args) that streams select_cols from source.

        Geometry columns are wrapped in ST_AsBinary(ST_Transform(col, dest_srid)).
        """
        geom_cols = set(
            db_utils.get_geometry_types(tname, dbconnection=source_conn).keys()
        )

        exprs: list[str] = []
        for col in select_cols:
            if col in geom_cols:
                qcol = db_utils.ident(col)
                exprs.append(f"ST_AsBinary(ST_Transform({qcol}, {dest_srid}))")
            else:
                exprs.append(db_utils.ident(col))

        sql = f"SELECT {', '.join(exprs)} FROM {db_utils.ident(tname)}"
        args: list = []
        if obsids:
            clause, args = source_conn.in_clause(obsids)
            sql += f" WHERE obsid IN {clause}"
        return sql, args

    def _build_insert_sql(
        self,
        tname: str,
        dest_conn: DbConnectionManager,
        dest_cols: list[str],
    ) -> str:
        """Return INSERT OR IGNORE SQL for dest table (always SpatiaLite, ? placeholders)."""
        geom_cols = set(
            db_utils.get_geometry_types(tname, dbconnection=dest_conn).keys()
        )

        dest_srid: int | None = None
        if geom_cols:
            dest_srid = dest_conn.get_srid(tname)

        col_list = ", ".join(db_utils.ident(c) for c in dest_cols)
        value_exprs: list[str] = []
        for col in dest_cols:
            if col in geom_cols and dest_srid is not None:
                value_exprs.append(f"ST_GeomFromWKB(?, {dest_srid})")
            else:
                value_exprs.append("?")

        return (
            f"INSERT OR IGNORE INTO {db_utils.ident(tname)} "
            f"({col_list}) VALUES ({', '.join(value_exprs)})"
        )

    def _count_source_rows(
        self,
        tname: str,
        source_conn: DbConnectionManager,
        obsids: tuple[str, ...],
    ) -> int:
        """Count rows in a table, optionally filtered by obsids.

        Args:
            tname: Table name to count rows from.
            source_conn: Database connection to query.
            obsids: Tuple of obsid values to filter by; empty tuple = no filter.

        Returns:
            Number of rows matching the filter (or all rows if obsids is empty).
        """
        sql = f"SELECT count(*) FROM {db_utils.ident(tname)}"
        args: list = []
        if obsids:
            clause_sql, clause_args = source_conn.in_clause(obsids)
            sql += f" WHERE obsid IN {clause_sql}"
            args = clause_args
        rows = source_conn.execute_and_fetchall(sql, args if args else None)
        return rows[0][0]
