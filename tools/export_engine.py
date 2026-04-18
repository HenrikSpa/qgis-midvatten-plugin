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

    def _export_table(
        self,
        tname: str,
        source_conn: DbConnectionManager,
        dest_conn: DbConnectionManager,
        obsids: tuple[str, ...] | None,
        dest_srid: str,
        replace: bool,
        progress_cb: Callable[[str, int, int], None],
        cancel_flag: threading.Event,
    ) -> None:
        obsids = obsids or ()
        is_migration = tname == "w_levels_logger" and self._needs_logger_migration(
            source_conn, dest_conn
        )
        src_cols, dst_cols = self._get_exportable_columns(
            tname, source_conn, dest_conn, is_migration=is_migration
        )
        if not src_cols:
            log.warning("No exportable columns for table %s — skipping", tname)
            return

        total = self._count_source_rows(tname, source_conn, obsids)
        progress_cb(tname, 0, total)

        dest_snapshot: list[tuple] | None = None
        snap_cols: list[str] | None = None
        if replace:
            dest_snapshot, snap_cols = self._snapshot_and_clear_dest_table(
                tname, dest_conn
            )

        select_sql, select_args = self._build_select_sql(
            tname, source_conn, src_cols, dest_srid, obsids
        )
        insert_sql = self._build_insert_sql(tname, dest_conn, dst_cols)

        key_to_sid: dict[tuple, int] = {}
        if select_args:
            source_conn.cursor.execute(select_sql, select_args)
        else:
            source_conn.cursor.execute(select_sql)

        rows_written = 0
        while True:
            if cancel_flag.is_set():
                raise ExportCancelledError()
            chunk = list(source_conn.cursor.fetchmany(self.CHUNK_SIZE))
            if not chunk:
                break
            if is_migration:
                chunk = self._migrate_logger_chunk(
                    chunk, src_cols, dest_conn, key_to_sid
                )
            dest_conn.cursor.executemany(insert_sql, chunk)
            rows_written += len(chunk)
            progress_cb(tname, rows_written, total)

        if replace and dest_snapshot is not None:
            self._reinsert_dest_snapshot(tname, dest_conn, dest_snapshot, snap_cols)

    # ---- Stubs (replaced in Tasks 6 and 7) ----

    def _needs_logger_migration(
        self,
        source_conn: DbConnectionManager,
        dest_conn: DbConnectionManager,
    ) -> bool:
        """True when source has old 'source' column and dest has new series schema."""
        if "w_levels_logger" not in db_utils.get_tables(source_conn, skip_views=True):
            return False
        src_cols = set(self._get_columns("w_levels_logger", source_conn))
        if "source" not in src_cols:
            return False
        dest_tables = db_utils.tables_columns(dbconnection=dest_conn)
        if "w_logger_series" not in dest_tables:
            return False
        if "series_id" not in dest_tables.get("w_levels_logger", []):
            return False
        return True

    def _snapshot_and_clear_dest_table(
        self,
        tname: str,
        dest_conn: DbConnectionManager,
    ) -> tuple[list[tuple], list[str]]:
        """Read all dest rows, clear the table. Returns (rows, col_names).

        FK constraints are disabled only for the DELETE step so that lookup
        tables (zz_*) can be cleared even when referenced by data tables.
        The snapshot is immediately re-inserted after the source rows are
        written, so referential integrity is restored within the same export.
        """
        dest_conn.execute_safe(f"SELECT * FROM {db_utils.ident(tname)}")
        cols = [x[0].lower() for x in dest_conn.cursor.description]
        rows = list(dest_conn.cursor.fetchall())
        if rows:
            dest_conn.execute("PRAGMA foreign_keys = OFF")
            try:
                dest_conn.execute_safe(f"DELETE FROM {db_utils.ident(tname)}")
            finally:
                dest_conn.execute("PRAGMA foreign_keys = ON")
        return rows, cols

    def _reinsert_dest_snapshot(
        self,
        tname: str,
        dest_conn: DbConnectionManager,
        snapshot: list[tuple],
        snap_cols: list[str],
    ) -> None:
        """Re-insert the snapshot with INSERT OR IGNORE (source rows take priority)."""
        if not snapshot:
            return
        insert_sql = self._build_insert_sql(tname, dest_conn, snap_cols)
        dest_conn.cursor.executemany(insert_sql, snapshot)

    def _migrate_logger_chunk(
        self,
        chunk: list[tuple],
        src_cols: list[str],
        dest_conn: DbConnectionManager,
        key_to_sid: dict[tuple, int],
    ) -> list[tuple]:
        """Replace 'source' text values with w_logger_series.id integers in chunk."""
        src_idx = src_cols.index("source")
        obsid_idx = src_cols.index("obsid")

        migrated: list[tuple] = []
        for row in chunk:
            row_list = list(row)
            obsid = row_list[obsid_idx]
            source_val = row_list[src_idx]
            key = (obsid, source_val)
            if key not in key_to_sid:
                dest_conn.execute(
                    "INSERT INTO w_logger_series (obsid, source) VALUES (?, ?)",
                    (obsid, source_val),
                )
                key_to_sid[key] = db_utils.get_last_insert_id(dest_conn)
            row_list[src_idx] = key_to_sid[key]
            migrated.append(tuple(row_list))
        return migrated

    def export(
        self,
        source_conn: DbConnectionManager,
        dest_conn: DbConnectionManager,
        obsid_points: tuple[str, ...],
        obsid_lines: tuple[str, ...],
        dest_srid: str,
        progress_cb: Callable[[str, int, int], None],
        cancel_flag: threading.Event,
    ) -> str:
        """Run full export. Returns stats string. Raises ExportCancelledError if cancelled."""
        table_groups: list[tuple[list[str], tuple[str, ...] | None, bool]] = [
            (defs.get_subset_of_tables_fr_db("data_domains"), None, True),
            (defs.get_subset_of_tables_fr_db("obs_points"), obsid_points, False),
            (defs.get_subset_of_tables_fr_db("obs_lines"), obsid_lines, False),
            (defs.get_subset_of_tables_fr_db("extra_data_tables"), obsid_points, False),
            (
                defs.get_subset_of_tables_fr_db("interlab4_import_table"),
                obsid_points,
                False,
            ),
        ]

        for tables, obsids, replace in table_groups:
            for tname in tables:
                if not db_utils.verify_table_exists(
                    tname, dbconnection=source_conn
                ):
                    log.warning("Source table %s missing — skipping", tname)
                    continue
                if not db_utils.verify_table_exists(tname, dbconnection=dest_conn):
                    log.warning("Dest table %s missing — skipping", tname)
                    continue
                self._export_table(
                    tname,
                    source_conn,
                    dest_conn,
                    obsids,
                    dest_srid,
                    replace,
                    progress_cb,
                    cancel_flag,
                )
                dest_conn.commit()

        db_utils.delete_srids(dest_conn, dest_srid)
        dest_conn.commit()
        dest_conn.vacuum()

        return self._build_stats(source_conn, dest_conn)

    def _build_stats(
        self,
        source_conn: DbConnectionManager,
        dest_conn: DbConnectionManager,
    ) -> str:
        """Return human-readable diff of row counts between source and exported DB."""
        results: dict[str, dict[str, int]] = {}
        for alias, conn in [("source", source_conn), ("exported", dest_conn)]:
            for tname in db_utils.get_tables(dbconnection=conn, skip_views=True):
                try:
                    n = conn.execute_and_fetchall(
                        f"SELECT count(*) FROM {db_utils.ident(tname)}"
                    )[0][0]
                    results.setdefault(tname, {})[alias] = n
                except Exception:
                    pass

        differing = [
            (tname, counts)
            for tname, counts in sorted(results.items())
            if counts.get("source") != counts.get("exported")
        ]

        if not differing:
            return "All exported tables have matching row counts."

        header = f"{'table':40}{'exported':15}{'source':15}"
        lines = [header] + [
            f"{t:40}{str(c.get('exported', '?')):15}{str(c.get('source', '?')):15}"
            for t, c in differing
        ]
        return "\n".join(lines)

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
