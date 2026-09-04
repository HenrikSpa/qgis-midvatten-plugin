"""Behaviour of the normalized-timestamp index build when the DB is locked.

Field report (2026-09-04, Midvatten 2.0.0)::

    Import to w_flow starting
    Sql failed, see log message panel.
    SQL causing this error: CREATE INDEX IF NOT EXISTS
        "idx_midv_import_w_flow_instant"
        ON "w_flow" ("obsid","instrumentid","flowtype", datetime("date_time"))
    Msg: database is locked
    The normalized timestamp index required for importing to w_flow could not
    be created. The import was stopped to avoid a very slow duplicate scan.

The failing statement is the normalized-timestamp index that 2.0.0 builds
*before* importing (``ensure_normalized_datetime_index``). It only runs on
databases whose destination table lacks the normalized unique index -- i.e.
schemas older than 2.0.0 -- because building the expression index needs an
exclusive write lock on the whole table. In a live QGIS session another
connection (QGIS's SpatiaLite pool, the Browser panel, another open tool) can
hold that lock, so the build cannot be guaranteed to succeed.

The index is only a *speed-up* for the duplicate scan; the import is correct
without it. So a locked/failing index build must NOT abort the import: it warns
and continues (the slower duplicate scan still runs). These tests pin that
graceful behaviour. The lock is at the SQLite layer, so no live QGIS GUI is
needed to reproduce it.
"""

import contextlib
from sqlite3 import OperationalError

from unittest import mock

import pytest
from qgis.utils import spatialite_connect

from midvatten.test import utils_for_tests
from midvatten.tools.utils import db_utils


# Matches the schema index a fresh 2.0.0 DB carries (definitions/create_db.sql).
# Older DBs lack it, which is exactly when the importer builds its own index.
_NORMALIZED_UNIQUE_INDEX = "uq_w_flow_obsid_dt"
# The index the importer tries to build (tools/import_data_to_db.py).
_IMPORT_INDEX = "idx_midv_import_w_flow_instant"

_WFLOW_FILE_DATA = [
    ["obsid", "instrumentid", "flowtype", "date_time", "reading", "unit", "comment"],
    ["obsid1", "testid", "Momflow", "2011-10-19 12:30:00", "2", "l/s", "testcomment"],
]


@contextlib.contextmanager
def _reserved_lock(dbpath):
    """Hold a RESERVED write lock on *dbpath* from a separate connection.

    ``BEGIN IMMEDIATE`` takes a RESERVED lock: other connections may still read
    (so the importer's schema introspection succeeds) but no other connection
    can write -- which is what makes the CREATE INDEX fail, mirroring a loaded
    layer / another process / a flaky network share holding the file.
    """
    conn = spatialite_connect(dbpath)
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    finally:
        try:
            conn.rollback()
        finally:
            conn.close()


def _wflow_file_data():
    """Fresh copy of the import rows (general_import may mutate file_data)."""
    return [list(row) for row in _WFLOW_FILE_DATA]


def _index_names():
    ok, rows = db_utils.sql_load_fr_db(
        "SELECT name FROM sqlite_master WHERE type = 'index'"
    )
    assert ok
    return {row[0] for row in rows}


def _warning_texts(mock_messagebar):
    """All bar_msg/log_msg strings passed to MessagebarAndLog.warning."""
    texts = []
    for _name, args, kwargs in mock_messagebar.warning.mock_calls:
        texts.extend(str(a) for a in args)
        texts.extend(str(v) for v in kwargs.values())
    return texts


@pytest.mark.spatialite
class TestWflowImportDbLockSpatialite(
    utils_for_tests.MidvattenTestSpatialiteDbSvImportInstance
):
    def _simulate_older_db(self):
        """Put the DB in the pre-2.0.0 state that triggers the index build."""
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('obsid1')")
        db_utils.sql_alter_db(f'DROP INDEX IF EXISTS "{_NORMALIZED_UNIQUE_INDEX}"')
        assert _NORMALIZED_UNIQUE_INDEX not in _index_names()

    @mock.patch("midvatten.tools.utils.dialog_utils.Askuser", mock.MagicMock())
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_wflow_import_builds_index_and_succeeds_without_external_lock(
        self, mock_messagebar
    ):
        """Control: with no other connection holding the DB, the import builds
        the index and succeeds. Proves the plugin does not lock itself."""
        self._simulate_older_db()

        nr_imported = self.importinstance.general_import(
            dest_table="w_flow",
            file_data=_wflow_file_data(),
            skip_confirmation=True,
        )

        print(f"{mock_messagebar.mock_calls=}")
        assert nr_imported == 1
        assert _IMPORT_INDEX in _index_names()
        ok, rows = db_utils.sql_load_fr_db("SELECT obsid, reading FROM w_flow")
        assert ok
        assert rows == [("obsid1", 2.0)]

    @mock.patch("midvatten.tools.utils.dialog_utils.Askuser", mock.MagicMock())
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_wflow_import_completes_when_index_build_is_locked(self, mock_messagebar):
        """The field failure, but with the fix: the index build fails with
        'database is locked', the importer warns, and the import still
        completes with the row inserted (via the slower duplicate scan)."""
        self._simulate_older_db()

        # Fail only the CREATE INDEX statement (as a live lock would), while the
        # rest of the import -- temp table, dedup scan, INSERT -- runs normally.
        importer_conn = db_utils.DbConnectionManager()
        real_execute = importer_conn.execute

        def execute_locking_index(sql, *args, **kwargs):
            text = sql if isinstance(sql, str) else str(sql)
            if "CREATE INDEX" in text and _IMPORT_INDEX in text:
                raise OperationalError("database is locked")
            return real_execute(sql, *args, **kwargs)

        try:
            with mock.patch.object(
                importer_conn, "execute", side_effect=execute_locking_index
            ):
                nr_imported = self.importinstance.general_import(
                    dest_table="w_flow",
                    file_data=_wflow_file_data(),
                    _dbconnection=importer_conn,
                    skip_confirmation=True,
                )
        finally:
            importer_conn.closedb()

        print(f"{mock_messagebar.mock_calls=}")
        assert nr_imported == 1
        # The speed-up index could not be created, but the data still imported.
        assert _IMPORT_INDEX not in _index_names()
        ok, rows = db_utils.sql_load_fr_db("SELECT obsid, reading FROM w_flow")
        assert ok
        assert rows == [("obsid1", 2.0)]
        # The user was warned, and the warning names the table and the cause.
        warnings = " ".join(_warning_texts(mock_messagebar))
        assert "database is locked" in warnings
        assert "w_flow" in warnings

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_index_build_uses_short_busy_timeout_then_restores(self, mock_messagebar):
        """The index build runs under a short busy_timeout (so a locked DB
        falls back quickly), and the connection's original timeout is restored
        for the row inserts that follow."""
        self._simulate_older_db()
        primary_keys = ["obsid", "instrumentid", "flowtype", "date_time"]

        conn = db_utils.DbConnectionManager()
        conn.execute("PRAGMA busy_timeout = 7000")
        seen = {}
        real_execute = conn.execute

        def spy(sql, *args, **kwargs):
            text = sql if isinstance(sql, str) else str(sql)
            if "CREATE INDEX" in text and _IMPORT_INDEX in text:
                seen["during"] = conn.execute_and_fetchall("PRAGMA busy_timeout")[0][0]
            return real_execute(sql, *args, **kwargs)

        try:
            with mock.patch.object(conn, "execute", side_effect=spy):
                created = self.importinstance.ensure_normalized_datetime_index(
                    conn, "w_flow", primary_keys
                )
            after = conn.execute_and_fetchall("PRAGMA busy_timeout")[0][0]
        finally:
            conn.closedb()

        assert created is True
        assert seen["during"] == 2000
        assert after == 7000

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_ensure_normalized_datetime_index_warns_and_returns_false_when_locked(
        self, mock_messagebar
    ):
        """Isolate the failing step: building the index on a genuinely locked DB
        no longer raises -- it warns and reports that no index was created."""
        self._simulate_older_db()
        primary_keys = ["obsid", "instrumentid", "flowtype", "date_time"]

        # Short busy_timeout keeps the test fast; production default is 5 s.
        importer_conn = db_utils.DbConnectionManager()
        importer_conn.execute("PRAGMA busy_timeout = 300")
        try:
            with _reserved_lock(self.TEMP_DBPATH):
                created = self.importinstance.ensure_normalized_datetime_index(
                    importer_conn, "w_flow", primary_keys
                )
        finally:
            importer_conn.closedb()

        assert created is False
        assert _IMPORT_INDEX not in _index_names()
        warnings = " ".join(_warning_texts(mock_messagebar))
        print(f"{warnings=}")
        assert "database is locked" in warnings
        assert "w_flow" in warnings
