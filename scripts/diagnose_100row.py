"""Diagnose the obs_points 100-row cap bug.

Usage:
    python3 /tmp/midv_diagnose_100row.py /path/to/your/problematic.sqlite

Runs a battery of featureCount / schema probes against YOUR DB so we can see
exactly what QGIS's SpatiaLite provider returns for obs_points under a few
URI variants — no GUI required.

Also creates a fresh synthetic DB at /tmp/midv_repro_fresh.sqlite so you can
compare behavior by loading BOTH in QGIS's Midvatten plugin.
"""

from __future__ import annotations

import os
import sqlite3
import sys

FRESH_DB = "/tmp/midv_repro_fresh.sqlite"


def _open_spatialite(path: str):
    """Open a SpatiaLite-enabled connection, trying qgis.utils.spatialite_connect
    first (works in any QGIS Python env) and falling back to loading
    mod_spatialite on a plain sqlite3 connection.
    """
    try:
        from qgis.utils import spatialite_connect

        return spatialite_connect(path)
    except Exception:
        pass
    con = sqlite3.connect(path)
    con.enable_load_extension(True)
    for ext in (
        "mod_spatialite",
        "libspatialite",
        "libspatialite.so.8",
        "libspatialite.so.7",
    ):
        try:
            con.execute(f"SELECT load_extension('{ext}')")
            return con
        except sqlite3.OperationalError:
            continue
    raise RuntimeError(
        "Could not open SpatiaLite connection. Install mod_spatialite:\n"
        "  sudo apt install libsqlite3-mod-spatialite"
    )


def sqlite_introspect(path: str) -> None:
    """Print everything relevant about obs_points in the given DB."""
    con = _open_spatialite(path)
    print(f"\n=== SQLite introspection of {path} ===")

    def q(label: str, sql: str) -> None:
        try:
            rows = con.execute(sql).fetchall()
            print(f"  {label}: {rows}")
        except Exception as exc:
            print(f"  {label}: ERROR {exc}")

    q("obs_points type", "SELECT type FROM sqlite_master WHERE name='obs_points'")
    q("row count", "SELECT count(*) FROM obs_points")
    q("PK", "PRAGMA table_info(obs_points)")
    q(
        "geometry_columns columns",
        "SELECT name FROM pragma_table_info('geometry_columns')",
    )
    q(
        "geometry_columns row for obs_points",
        "SELECT * FROM geometry_columns WHERE f_table_name='obs_points'",
    )
    q(
        "stat tables/views",
        "SELECT name, type FROM sqlite_master WHERE name LIKE '%statist%'",
    )
    q(
        "vector_layers_statistics for obs_points",
        "SELECT * FROM vector_layers_statistics WHERE table_name='obs_points'",
    )
    try:
        q(
            "layer_statistics for obs_points",
            "SELECT * FROM layer_statistics WHERE table_name='obs_points' OR f_table_name='obs_points'",
        )
    except Exception:
        pass
    q(
        "views obs_*",
        "SELECT name FROM sqlite_master WHERE type='view' AND name LIKE '%obs_%'",
    )
    q(
        "spatial_ref_sys count",
        "SELECT count(*) FROM spatial_ref_sys",
    )
    q(
        "spatialite version / target_cpu",
        "SELECT spatialite_version(), spatialite_target_cpu()",
    )

    con.close()


_qgs_app = None


def _ensure_qgs():
    global _qgs_app
    if _qgs_app is None:
        from qgis.core import QgsApplication

        _qgs_app = QgsApplication([], False)
        _qgs_app.setPrefixPath("/usr", True)
        _qgs_app.initQgis()
    return _qgs_app


def probe_with_qgis(path: str) -> None:
    from qgis.core import Qgis, QgsDataSourceUri, QgsVectorLayer

    _ensure_qgs()
    print(f"  QGIS_VERSION_INT={Qgis.QGIS_VERSION_INT}", flush=True)

    def try_layer(tablename: str, keycol: str = "", label: str = "") -> None:
        uri = QgsDataSourceUri()
        uri.setDatabase(path)
        uri.setDataSource("", tablename, "geometry", "", keycol)
        layer = QgsVectorLayer(uri.uri(), tablename, "spatialite")
        fc = layer.featureCount() if layer.isValid() else -1
        # Force an iterator-based recount for comparison
        iter_count = (
            sum(1 for _ in layer.getFeatures()) if layer.isValid() else -1
        )
        print(
            f"  [{label or tablename + ' keycol=' + (keycol or 'auto')}] "
            f"valid={layer.isValid()} featureCount={fc} iterCount={iter_count}",
            flush=True,
        )

    print(f"\n=== QGIS featureCount probes for {path} ===", flush=True)
    try_layer("obs_points", "", "obs_points auto")
    try_layer("obs_points", "obsid", "obs_points obsid")
    try_layer("obs_points", "rowid", "obs_points rowid")
    try:
        try_layer("view_obs_points", "", "view_obs_points auto")
        try_layer("view_obs_points", "rowid", "view_obs_points rowid")
    except Exception as exc:
        print(f"  view_obs_points: {exc}", flush=True)


def probe_fixes(path: str) -> None:
    """Test each candidate fix IN PLACE against the given DB. Writes are
    made, then the DB is restored from a backup so the user's file is left
    untouched.
    """
    import shutil

    from qgis.core import QgsDataSourceUri, QgsVectorLayer

    _ensure_qgs()

    backup = path + ".diagnostic.bak"
    shutil.copy2(path, backup)
    print(f"\n=== Candidate-fix probes against {path} ===", flush=True)
    print(f"  (backup copy: {backup})", flush=True)

    def build_layer(estimated: str = "", tablename: str = "obs_points"):
        uri = QgsDataSourceUri()
        uri.setDatabase(path)
        uri.setDataSource("", tablename, "geometry", "", "")
        if estimated:
            uri.setParam("estimatedmetadata", estimated)
        return QgsVectorLayer(uri.uri(), tablename, "spatialite")

    def show_stats(label: str) -> None:
        con = _open_spatialite(path)
        try:
            gcs = con.execute(
                "SELECT f_table_name, f_geometry_column, last_verified, row_count, extent_min_x, extent_min_y, extent_max_x, extent_max_y FROM geometry_columns_statistics WHERE f_table_name='obs_points'"
            ).fetchall()
            vls = con.execute(
                "SELECT * FROM vector_layers_statistics WHERE table_name='obs_points'"
            ).fetchall()
            try:
                vgc = con.execute(
                    "SELECT * FROM views_geometry_columns WHERE view_name LIKE 'obs_p%' OR view_name LIKE 'view_obs%'"
                ).fetchall()
            except Exception:
                vgc = "(no views_geometry_columns)"
        finally:
            con.close()
        print(f"  [{label}] geometry_columns_statistics={gcs}", flush=True)
        print(f"  [{label}] vector_layers_statistics={vls}", flush=True)
        print(f"  [{label}] views_geometry_columns={vgc}", flush=True)

    show_stats("initial")

    print(f"\n  [baseline obs_points]                            fc={build_layer().featureCount()}", flush=True)
    print(f"  [baseline view_obs_points]                       fc={build_layer(tablename='view_obs_points').featureCount()}", flush=True)

    # 1. Try explicit INSERT of stats row with the real count.
    con = _open_spatialite(path)
    try:
        con.execute("DELETE FROM geometry_columns_statistics WHERE f_table_name='obs_points'")
        con.execute(
            "INSERT INTO geometry_columns_statistics (f_table_name, f_geometry_column, row_count) VALUES ('obs_points', 'geometry', 120)"
        )
        con.commit()
    finally:
        con.close()
    show_stats("after explicit INSERT row_count=120")
    print(f"  [after explicit INSERT]                          fc={build_layer().featureCount()}", flush=True)

    # 2. Try UpdateLayerStatistics with (table, geom) and capture return value.
    con = _open_spatialite(path)
    try:
        r = con.execute(
            "SELECT UpdateLayerStatistics('obs_points','geometry')"
        ).fetchone()
        con.commit()
    finally:
        con.close()
    show_stats("after UpdateLayerStatistics('obs_points','geometry')")
    print(f"  UpdateLayerStatistics(obs_points,geometry) returned {r}", flush=True)
    print(f"  [after arg'd UpdateLayerStatistics]              fc={build_layer().featureCount()}", flush=True)

    # 3. Try UpdateLayerStatistics with NO args (updates all tables).
    con = _open_spatialite(path)
    try:
        r2 = con.execute("SELECT UpdateLayerStatistics()").fetchone()
        con.commit()
    finally:
        con.close()
    show_stats("after UpdateLayerStatistics()")
    print(f"  UpdateLayerStatistics() returned {r2}", flush=True)
    print(f"  [after argless UpdateLayerStatistics]            fc={build_layer().featureCount()}", flush=True)

    # 4. Try RecoverGeometryColumn to re-register the column.
    con = _open_spatialite(path)
    try:
        r3 = con.execute(
            "SELECT RecoverGeometryColumn('obs_points','geometry',3006,'POINT','XY')"
        ).fetchone()
        con.commit()
    finally:
        con.close()
    show_stats("after RecoverGeometryColumn")
    print(f"  RecoverGeometryColumn returned {r3}", flush=True)
    print(f"  [after RecoverGeometryColumn]                    fc={build_layer().featureCount()}", flush=True)

    # 5. Try CreateSpatialIndex + UpdateLayerStatistics.
    con = _open_spatialite(path)
    try:
        try:
            r4 = con.execute(
                "SELECT CreateSpatialIndex('obs_points','geometry')"
            ).fetchone()
            con.commit()
        except Exception as exc:
            r4 = f"ERR {exc}"
        con.execute("SELECT UpdateLayerStatistics('obs_points','geometry')")
        con.commit()
    finally:
        con.close()
    show_stats("after CreateSpatialIndex + UpdateLayerStatistics")
    print(f"  CreateSpatialIndex returned {r4}", flush=True)
    print(f"  [after CreateSpatialIndex + UpdateStats]         fc={build_layer().featureCount()}", flush=True)

    # Restore the backup so we leave the DB untouched.
    shutil.copy2(backup, path)
    os.remove(backup)
    print(f"  (DB restored from backup; backup removed)", flush=True)


def make_fresh_db() -> None:
    if os.path.exists(FRESH_DB):
        os.remove(FRESH_DB)
    con = _open_spatialite(FRESH_DB)
    con.execute("SELECT InitSpatialMetadata(1)")
    con.execute(
        "CREATE TABLE obs_points (obsid TEXT NOT NULL, name TEXT, PRIMARY KEY (obsid))"
    )
    con.execute(
        "SELECT AddGeometryColumn('obs_points','geometry',3006,'POINT','XY',0)"
    )
    con.commit()
    cur = con.cursor()
    for i in range(150):
        cur.execute(
            "INSERT INTO obs_points(obsid, name, geometry) VALUES (?, ?, GeomFromText(?, 3006))",
            (f"rb{i}", f"name{i}", f"POINT({i} {i})"),
        )
    con.commit()
    con.execute(
        "CREATE VIEW IF NOT EXISTS view_obs_points AS SELECT rowid, obsid, name, geometry FROM obs_points"
    )
    con.commit()
    con.close()


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python3 midv_diagnose_100row.py /path/to/problematic.sqlite")
        sys.exit(1)

    user_db = sys.argv[1]
    if not os.path.exists(user_db):
        print(f"DB not found: {user_db}")
        sys.exit(1)

    print("### YOUR DB ###")
    sqlite_introspect(user_db)
    try:
        probe_with_qgis(user_db)
    except Exception as exc:
        print(f"(QGIS probe failed on your DB: {exc})")
    try:
        probe_fixes(user_db)
    except Exception:
        import traceback

        print("(Candidate-fix probe failed on your DB:)")
        traceback.print_exc()

    print("\n### FRESH SYNTHETIC DB (control) ###")
    make_fresh_db()
    sqlite_introspect(FRESH_DB)
    try:
        probe_with_qgis(FRESH_DB)
    except Exception as exc:
        print(f"(QGIS probe failed on synthetic: {exc})")

    print(
        "\nPlease paste the full output so we can see the difference between "
        "your DB and the synthetic control."
    )


if __name__ == "__main__":
    main()
