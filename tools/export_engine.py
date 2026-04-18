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
