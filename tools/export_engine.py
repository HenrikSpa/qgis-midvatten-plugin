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
        conn.execute(f"SELECT * FROM {db_utils.ident(tname)} LIMIT 0")
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
        wkb_srid: int,
        obsids: tuple[str, ...],
        geom_cols: set[str],
    ) -> tuple[str, list]:
        """Return (SELECT sql, args) streaming select_cols from source.

        The SRID for each geometry column is parameter-bound via
        ``ST_Transform(geom, <ph>)`` — one binding per geometry column, added
        to ``args`` in column order. ``obsids`` IN-clause values (if any)
        follow. The backend-specific placeholder (``?`` on SQLite, ``%s`` on
        PostgreSQL) is queried from ``source_conn``.
        """
        ph = source_conn.placeholder()
        exprs: list[str] = []
        srid_args: list = []
        for col in select_cols:
            if col in geom_cols:
                qcol = db_utils.ident(col)
                exprs.append(f"ST_AsBinary(ST_Transform({qcol}, {ph}))")
                srid_args.append(int(wkb_srid))
            else:
                exprs.append(db_utils.ident(col))

        sql = f"SELECT {', '.join(exprs)} FROM {db_utils.ident(tname)}"
        args: list = list(srid_args)
        if obsids:
            clause, in_args = source_conn.in_clause(obsids)
            sql += f" WHERE {db_utils.ident('obsid')} IN {clause}"
            args.extend(in_args)
        return sql, args

    def _build_insert_sql(
        self,
        tname: str,
        dest_conn: DbConnectionManager,
        dest_cols: list[str],
        wkb_srid: int | None = None,
    ) -> tuple[str, list[tuple[int, tuple[int, ...]]]]:
        """Return (INSERT sql, geom_srid_slots) for dest table (SpatiaLite).

        The returned SQL uses ``?`` placeholders everywhere, including for
        SRID arguments inside ``ST_GeomFromWKB`` and ``ST_Transform``. The
        second element is a list of ``(dest_col_index, extra_srid_values)``
        pairs: callers must splice the extra values into each chunk row
        immediately after the geometry column's WKB value so the positional
        bindings line up. ``_insert_chunk`` does this rewrite.

        ``wkb_srid`` is the SRID of the incoming WKB bytes. When it differs
        from the destination table's SRID (cross-CRS export), an
        ``ST_Transform`` is added so coordinates are re-projected.
        """
        geom_cols = set(
            db_utils.get_geometry_types(tname, dbconnection=dest_conn).keys()
        )

        dest_srid: int | None = None
        if geom_cols:
            dest_srid = dest_conn.get_srid(tname)

        col_list = ", ".join(db_utils.ident(c) for c in dest_cols)
        value_exprs: list[str] = []
        geom_srid_slots: list[tuple[int, tuple[int, ...]]] = []
        for idx, col in enumerate(dest_cols):
            if col in geom_cols and dest_srid is not None:
                effective_wkb_srid = wkb_srid if wkb_srid is not None else dest_srid
                effective_int = int(effective_wkb_srid)
                dest_int = int(dest_srid)
                if effective_int != dest_int:
                    value_exprs.append("ST_Transform(ST_GeomFromWKB(?, ?), ?)")
                    geom_srid_slots.append((idx, (effective_int, dest_int)))
                else:
                    value_exprs.append("ST_GeomFromWKB(?, ?)")
                    geom_srid_slots.append((idx, (dest_int,)))
            else:
                value_exprs.append("?")

        sql = (
            f"INSERT OR IGNORE INTO {db_utils.ident(tname)} "
            f"({col_list}) VALUES ({', '.join(value_exprs)})"
        )
        return sql, geom_srid_slots

    @staticmethod
    def _expand_chunk_with_geom_srids(
        chunk: list[tuple],
        geom_srid_slots: list[tuple[int, tuple[int, ...]]],
    ) -> list[tuple]:
        """Rewrite each row so geom-col slots gain the SRID bindings expected
        by the INSERT SQL returned from ``_build_insert_sql``.

        For each ``(idx, extras)`` pair, the row's value at position ``idx``
        (the raw WKB) is kept and followed by the SRID values in ``extras``.
        All other positions pass through unchanged.
        """
        if not geom_srid_slots:
            return chunk
        # Build a position-indexed lookup for O(1) access per row.
        extras_by_idx = dict(geom_srid_slots)
        out: list[tuple] = []
        for row in chunk:
            new_row: list = []
            for i, value in enumerate(row):
                new_row.append(value)
                if i in extras_by_idx:
                    new_row.extend(extras_by_idx[i])
            out.append(tuple(new_row))
        return out

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

        # Use WGS84 (4326) as intermediate when CRS differs: always present in both DBs' spatial_ref_sys.
        geom_cols = set(
            db_utils.get_geometry_types(tname, dbconnection=source_conn).keys()
        )
        source_srid = source_conn.get_srid(tname) if geom_cols else None
        dest_srid_int = int(dest_srid)
        wkb_srid = (
            dest_srid_int
            if source_srid is None or int(source_srid) == dest_srid_int
            else 4326
        )

        select_sql, select_args = self._build_select_sql(
            tname, source_conn, src_cols, wkb_srid, obsids, geom_cols
        )
        insert_sql, geom_srid_slots = self._build_insert_sql(
            tname, dest_conn, dst_cols, wkb_srid
        )

        key_to_sid: dict[tuple, int] = {}
        if select_args:
            source_conn.cursor.execute(select_sql, select_args)
        else:
            source_conn.cursor.execute(select_sql)

        rows_written = 0
        total_ignored = 0
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
            expanded = self._expand_chunk_with_geom_srids(chunk, geom_srid_slots)
            dest_conn.cursor.executemany(insert_sql, expanded)
            total_ignored += len(chunk) - dest_conn.cursor.rowcount
            rows_written += len(chunk)
            progress_cb(tname, rows_written, total)

        if total_ignored > 0:
            log.warning(
                "Table %s: %d rows skipped (duplicate key or FK violation)",
                tname,
                total_ignored,
            )

        if replace and dest_snapshot is not None:
            self._reinsert_dest_snapshot(
                tname, dest_conn, dest_snapshot, snap_cols, dest_srid
            )

    def _needs_logger_migration(
        self,
        source_conn: DbConnectionManager,
        dest_conn: DbConnectionManager,
    ) -> bool:
        """True when source has old 'source' column and dest has new series schema."""
        if not db_utils.verify_table_exists(
            "w_levels_logger", dbconnection=source_conn
        ):
            return False
        src_cols = set(self._get_columns("w_levels_logger", source_conn))
        if "source" not in src_cols:
            return False
        if not db_utils.verify_table_exists("w_logger_series", dbconnection=dest_conn):
            return False
        wll_info = db_utils.get_table_info("w_levels_logger", dbconnection=dest_conn)
        if not wll_info or not any(col[1].lower() == "series_id" for col in wll_info):
            return False
        return True

    def _snapshot_and_clear_dest_table(
        self,
        tname: str,
        dest_conn: DbConnectionManager,
    ) -> tuple[list[tuple], list[str]]:
        """Read all dest rows, clear the table. Returns (rows, col_names).

        The caller MUST have opened a ``dest_conn.transaction()`` block and
        issued ``PRAGMA defer_foreign_keys = ON`` inside it. Deferring FK
        checks (instead of the previous ``PRAGMA foreign_keys = OFF/ON``
        window) keeps FK enforcement active but postpones the check to
        COMMIT. By COMMIT the snapshot has been re-inserted alongside the
        source rows, so any data rows that FK-reference this lookup table
        (e.g. ``w_flow.flowtype`` → ``zz_flowtype.type``) stay satisfied.
        SQLite's ``defer_foreign_keys`` auto-resets at each COMMIT/ROLLBACK,
        so callers must set it per transaction.
        """
        dest_conn.execute(f"SELECT * FROM {db_utils.ident(tname)}")
        cols = [x[0].lower() for x in dest_conn.cursor.description]
        rows = list(dest_conn.cursor.fetchall())
        if rows:
            dest_conn.execute(f"DELETE FROM {db_utils.ident(tname)}")
        return rows, cols

    def _reinsert_dest_snapshot(
        self,
        tname: str,
        dest_conn: DbConnectionManager,
        snapshot: list[tuple],
        snap_cols: list[str],
        dest_srid: str,
    ) -> None:
        """Re-insert the snapshot with INSERT OR IGNORE (source rows take priority).

        Snapshot bytes are already in dest_srid (fetched from dest), so pass
        dest_srid explicitly — no cross-CRS transform is applied. Must run
        inside the same ``transaction()`` block that performed the snapshot
        + clear, so deferred FK checks clear at COMMIT time.
        """
        if not snapshot:
            return
        insert_sql, geom_srid_slots = self._build_insert_sql(
            tname, dest_conn, snap_cols, wkb_srid=int(dest_srid)
        )
        expanded = self._expand_chunk_with_geom_srids(snapshot, geom_srid_slots)
        dest_conn.cursor.executemany(insert_sql, expanded)

    def _migrate_logger_chunk(
        self,
        chunk: list[tuple],
        src_cols: list[str],
        dest_conn: DbConnectionManager,
        key_to_sid: dict[tuple, int],
    ) -> list[tuple]:
        """Replace 'source' text values with w_logger_series.id integers in chunk."""
        assert "source" in src_cols and "obsid" in src_cols, (
            "_migrate_logger_chunk called but src_cols missing 'source' or 'obsid'"
        )
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
                    f"INSERT INTO {db_utils.ident('w_logger_series')}"
                    f" ({db_utils.ident('obsid')}, {db_utils.ident('source')},"
                    f" {db_utils.ident('description')}) VALUES (?, ?, ?)",
                    (obsid, source_val, "Upgraded from Midv 1.x"),
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
                if not db_utils.verify_table_exists(tname, dbconnection=source_conn):
                    log.warning("Source table %s missing — skipping", tname)
                    continue
                if not db_utils.verify_table_exists(tname, dbconnection=dest_conn):
                    log.warning("Dest table %s missing — skipping", tname)
                    continue
                # Each per-table cycle (snapshot → DELETE → insert source →
                # reinsert snapshot) runs atomically. defer_foreign_keys
                # suspends FK *checks* until COMMIT while leaving enforcement
                # on, so FK-referenced lookup rows (e.g. zz_flowtype pointed
                # at by w_flow) can be cleared mid-transaction without
                # violating the constraint — the snapshot reinsert restores
                # integrity before COMMIT runs the deferred check.
                #
                # SQLite quirks that dictate the shape of this block:
                #   - ``defer_foreign_keys`` is only honored *inside* an open
                #     transaction; it is silently reset the next time SQLite
                #     transitions out of a transaction. Python's sqlite3
                #     deferred-isolation mode does not issue BEGIN until the
                #     first DML, so we issue ``BEGIN`` explicitly here to
                #     guarantee an active transaction before the pragma.
                #   - The pragma auto-resets at each COMMIT/ROLLBACK, so it
                #     must be set fresh per transaction.
                with dest_conn.transaction():
                    dest_conn.execute("BEGIN")
                    dest_conn.execute("PRAGMA defer_foreign_keys = ON")
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

        with dest_conn.transaction():
            db_utils.delete_srids(dest_conn, dest_srid)
        # VACUUM is non-transactional by definition; keep it outside
        # transaction() per the connection manager's contract.
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
                    log.warning(
                        "Could not count rows in %s (%s)", tname, alias, exc_info=True
                    )

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
        """Count rows in tname, filtered by obsids if non-empty."""
        sql = f"SELECT count(*) FROM {db_utils.ident(tname)}"
        args: list = []
        if obsids:
            clause_sql, clause_args = source_conn.in_clause(obsids)
            sql += f" WHERE {db_utils.ident('obsid')} IN {clause_sql}"
            args = clause_args
        rows = source_conn.execute_and_fetchall(sql, args if args else None)
        return rows[0][0]
