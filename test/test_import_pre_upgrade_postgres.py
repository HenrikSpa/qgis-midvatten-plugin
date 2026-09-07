"""
/***************************************************************************
 Importing to a time-series table on PostgreSQL must work even when the
 normalized-timestamp speed-up index cannot be created:

 - the connecting role has INSERT rights but does not own the table, so
   CREATE INDEX fails with "must be owner of table", and
 - the database has not been upgraded with upgrade_postgresql_to_2_0_0.sql,
   so midv_to_instant() does not exist at all.

 In both cases the index is only a speed-up; the import continues with the
 slower duplicate scan and the same-instant duplicate rule still applies.
                             -------------------
        begin                : 2026-09-07
        copyright            : (C) 2026 by HenrikSpa
        email                : groundwatergis [at] gmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import os
from unittest import mock

import pytest

from midvatten.test import utils_for_tests
from midvatten.tools.utils import db_utils

IMPORT_FILE = [
    ["obsid", "date_time", "comment", "staff"],
    ["o1", "2020-01-01 00:00:00", "same instant as existing row", "s"],
    ["o1", "2020-01-01 01:00", "new row", "s"],
]

EXPECTED_ROWS = [
    ("o1", "2020-01-01 00:00", "existing"),
    ("o1", "2020-01-01 01:00", "new row"),
]


@pytest.mark.postgis
class TestImportWithoutSpeedUpIndex(
    utils_for_tests.MidvattenTestPostgisDbSvImportInstance
):
    def setup_method(self):
        super().setup_method()
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('o1')")
        db_utils.sql_alter_db(
            "INSERT INTO comments (obsid, date_time, comment, staff) "
            "VALUES ('o1', '2020-01-01 00:00', 'existing', 's')"
        )
        # No normalized index on comments, so the importer tries to build one.
        db_utils.sql_alter_db("DROP INDEX IF EXISTS uq_comments_obsid_dt")

    @staticmethod
    def _comments_rows() -> list:
        return db_utils.sql_load_fr_db(
            "SELECT obsid, date_time, comment FROM comments ORDER BY date_time"
        )[1]

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    @mock.patch("midvatten.tools.utils.dialog_utils.Askuser", mock.MagicMock())
    def test_non_owner_role_can_still_import_to_comments(self, mock_messagebar):
        """A role with INSERT but no ownership cannot CREATE INDEX; the import
        must warn and continue instead of aborting."""
        role = f"midv_test_nonowner_{os.getpid()}"
        db_utils.sql_alter_db(f"CREATE ROLE {role} NOLOGIN")
        try:
            db_utils.sql_alter_db(f"GRANT USAGE ON SCHEMA public TO {role}")
            db_utils.sql_alter_db(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES "
                f"IN SCHEMA public TO {role}"
            )
            db_utils.sql_alter_db(
                f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}"
            )

            as_role = db_utils.DbConnectionManager()
            try:
                as_role.execute(f"SET ROLE {role}")
                self.importinstance.general_import(
                    dest_table="comments",
                    file_data=IMPORT_FILE,
                    _dbconnection=as_role,
                )
            finally:
                as_role.closedb()

            calls = str(mock_messagebar.mock_calls)
            print(calls)
            assert "Import error" not in calls
            assert "idx_midv_import_comments_instant" in calls
            assert "The import continues" in calls
            assert self._comments_rows() == EXPECTED_ROWS
        finally:
            db_utils.sql_alter_db(f"DROP OWNED BY {role}")
            db_utils.sql_alter_db(f"DROP ROLE IF EXISTS {role}")

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    @mock.patch("midvatten.tools.utils.dialog_utils.Askuser", mock.MagicMock())
    def test_import_without_midv_to_instant_function(self, mock_messagebar):
        """Before upgrade_postgresql_to_2_0_0.sql has been run there is no
        midv_to_instant(). The import must still work and still skip the
        same-instant duplicate."""
        db_utils.sql_alter_db(
            "ALTER FUNCTION midv_to_instant(text) RENAME TO midv_to_instant_hidden"
        )
        try:
            self.importinstance.general_import(
                dest_table="comments", file_data=IMPORT_FILE
            )

            calls = str(mock_messagebar.mock_calls)
            print(calls)
            assert "Import error" not in calls
            assert "upgrade_postgresql_to_2_0_0.sql" in calls
            assert self._comments_rows() == EXPECTED_ROWS
        finally:
            db_utils.sql_alter_db(
                "ALTER FUNCTION midv_to_instant_hidden(text) RENAME TO midv_to_instant"
            )
