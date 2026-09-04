"""general_import must release its connection on every exit path.

Root cause of the field "database is locked" reports (2026-09-04): a FieldLogger
import to a table whose rows all already exist logs "Nothing imported: every row
already exists" and hits an early ``return 0`` inside general_import's
``try`` block. That block used ``try/except/else`` with NO ``finally``, so an
early return skipped ``_cleanup`` entirely -- leaving the connection with an
uncommitted transaction (it had built the timestamp index and/or the staging
table). That leaked, still-open connection held a lock, which then blocked the
CREATE INDEX of the *next* table (w_flow) and any later Vacuum, until QGIS was
restarted. Exactly the sequence the users reported.

These tests pin that the connection is always cleaned up, even when nothing is
imported. The lock is at the SQLite layer, so no live QGIS GUI is needed.
"""

from unittest import mock

import pytest

from midvatten.test import utils_for_tests
from midvatten.tools.utils import db_utils


_WFLOW_ROW = [
    ["obsid", "instrumentid", "flowtype", "date_time", "reading", "unit", "comment"],
    ["obsid1", "testid", "Momflow", "2011-10-19 12:30:00", "2", "l/s", "testcomment"],
]


def _wflow_file_data():
    return [list(row) for row in _WFLOW_ROW]


@pytest.mark.spatialite
class TestImportConnectionLeakSpatialite(
    utils_for_tests.MidvattenTestSpatialiteDbSvImportInstance
):
    def _seed_existing_row(self):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('obsid1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_flow "
            "(obsid, instrumentid, flowtype, date_time, reading, unit, comment) "
            "VALUES ('obsid1', 'testid', 'Momflow', '2011-10-19 12:30:00', "
            "2, 'l/s', 'testcomment')"
        )

    @mock.patch("midvatten.tools.utils.dialog_utils.Askuser", mock.MagicMock())
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_all_duplicates_import_leaves_no_open_transaction(self, mock_messagebar):
        """When every row already exists, the import returns 0 and must leave the
        (external) connection with no open transaction -- i.e. cleanup ran."""
        self._seed_existing_row()

        conn = db_utils.DbConnectionManager()
        try:
            nr_imported = self.importinstance.general_import(
                dest_table="w_flow",
                file_data=_wflow_file_data(),
                _dbconnection=conn,
                skip_confirmation=True,
            )
            print(f"{mock_messagebar.mock_calls=}")
            assert nr_imported == 0
            # The bug left an uncommitted transaction here (a held lock).
            assert conn.conn.in_transaction is False
        finally:
            conn.closedb()

    @mock.patch("midvatten.tools.utils.dialog_utils.Askuser", mock.MagicMock())
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_all_duplicates_import_closes_internal_connection(self, mock_messagebar):
        """The real FieldLogger case uses an internal connection. _cleanup (which
        closes it) must run even on the early 'nothing to import' return."""
        self._seed_existing_row()

        with mock.patch.object(
            self.importinstance,
            "_cleanup",
            wraps=self.importinstance._cleanup,
        ) as cleanup_spy:
            nr_imported = self.importinstance.general_import(
                dest_table="w_flow",
                file_data=_wflow_file_data(),
                skip_confirmation=True,
            )

        print(f"{mock_messagebar.mock_calls=}")
        assert nr_imported == 0
        cleanup_spy.assert_called_once()
        # The internal connection was cleaned up with a real DbConnectionManager.
        cleaned = cleanup_spy.call_args.args[0]
        assert isinstance(cleaned, db_utils.DbConnectionManager)
