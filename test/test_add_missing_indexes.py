"""Piece 3: the "add missing timestamp indexes" maintenance feature.

Older (pre-2.0.0) databases can lack the normalized-timestamp index on the
time-series tables, which makes every import to those tables slow (and, when
the database is briefly locked, fall back with a warning). This feature lets
the user add the non-unique speed-up index to all affected tables in one pass,
with a long busy timeout, when the database is not otherwise in use.

It is non-destructive: it only adds indexes, never deletes rows, and does not
touch duplicates (uniqueness is a separate, upgrade-time concern).
"""

from unittest import mock

import pytest

from midvatten.test import utils_for_tests
from midvatten.tools import import_data_to_db
from midvatten.tools.utils import db_utils


def _index_names():
    ok, rows = db_utils.sql_load_fr_db(
        "SELECT name FROM sqlite_master WHERE type = 'index'"
    )
    assert ok
    return {row[0] for row in rows}


@pytest.mark.spatialite
class TestAddMissingIndexesSpatialite(utils_for_tests.MidvattenTestSpatialiteDbSv):
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_builds_missing_indexes_and_reports_status(self, mock_messagebar):
        # Two tables in the pre-2.0.0 state (no normalized index); the rest keep
        # their schema-defined unique index.
        db_utils.sql_alter_db("DROP INDEX IF EXISTS uq_w_flow_obsid_dt")
        db_utils.sql_alter_db("DROP INDEX IF EXISTS uq_w_levels_obsid_dt")
        assert "idx_midv_import_w_flow_instant" not in _index_names()

        results = import_data_to_db.add_missing_normalized_datetime_indexes()

        print(f"{mock_messagebar.mock_calls=}")
        print(f"{results=}")
        assert results["w_flow"] == "created"
        assert results["w_levels"] == "created"
        assert results["comments"] == "exists"
        # Every listed table is accounted for.
        assert set(results) == set(import_data_to_db.NORMALIZED_DATETIME_INDEX_TABLES)
        assert "idx_midv_import_w_flow_instant" in _index_names()
        assert "idx_midv_import_w_levels_instant" in _index_names()

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_missing_table_is_reported_not_fatal(self, mock_messagebar):
        db_utils.sql_alter_db("DROP TABLE IF EXISTS meteo")

        results = import_data_to_db.add_missing_normalized_datetime_indexes()

        print(f"{mock_messagebar.mock_calls=}")
        assert results["meteo"] == "missing"
        # Other tables already have their index on a fresh DB.
        assert results["w_flow"] == "exists"

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_dialog_add_indexes_builds_and_accepts(self, mock_messagebar):
        from midvatten.tools.add_missing_indexes_dialog import AddMissingIndexesDialog

        db_utils.sql_alter_db("DROP INDEX IF EXISTS uq_w_flow_obsid_dt")
        dlg = AddMissingIndexesDialog()
        try:
            with mock.patch.object(dlg, "accept") as mock_accept:
                dlg.run_add_indexes()
            assert "idx_midv_import_w_flow_instant" in _index_names()
            mock_accept.assert_called_once()
        finally:
            dlg.deleteLater()

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_dialog_backup_button_disables_after_success(self, mock_messagebar):
        from midvatten.tools.add_missing_indexes_dialog import AddMissingIndexesDialog

        dlg = AddMissingIndexesDialog()
        try:
            with mock.patch(
                "midvatten.tools.add_missing_indexes_dialog.db_utils.backup_db"
            ) as mock_backup:
                dlg.run_backup()
            mock_backup.assert_called_once()
            assert dlg.backup_done is True
            assert dlg.backup_button.isEnabled() is False
        finally:
            dlg.deleteLater()

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_dialog_backup_failure_keeps_button_enabled(self, mock_messagebar):
        from midvatten.tools.add_missing_indexes_dialog import AddMissingIndexesDialog

        dlg = AddMissingIndexesDialog()
        try:
            with mock.patch(
                "midvatten.tools.add_missing_indexes_dialog.db_utils.backup_db",
                side_effect=RuntimeError("disk full"),
            ):
                dlg.run_backup()
            assert dlg.backup_done is False
            assert dlg.backup_button.isEnabled() is True
            assert mock_messagebar.critical.called
        finally:
            dlg.deleteLater()
