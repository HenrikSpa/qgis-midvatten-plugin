"""
/***************************************************************************
 This part of the Midvatten plugin tests the db_utils.

 This part is to a big extent based on QSpatialite plugin.
                             -------------------
        begin                : 2016-03-08
        copyright            : (C) 2016 by joskal (HenrikSpa)
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

from unittest import mock

import pytest

from midvatten.test import utils_for_tests
from midvatten.tools.utils import db_utils
from midvatten.tools.utils.db_utils.backends.sqlite import SQLiteBackend


class DbTablesColumnsInfoMixin:
    def test_tables_columns_info_all_tables(self):
        """ """
        # Assert that obsid is primary key and not null in obs_points
        # {'tablename': (ordernumber, name, type, notnull, defaultvalue, primarykey)}
        tables_columns_info = db_utils.db_tables_columns_info()
        col_obsid = [
            col for col in tables_columns_info["obs_points"] if col[1] == "obsid"
        ][0]
        assert len(tables_columns_info) > 1
        if isinstance(self, utils_for_tests.MidvattenTestPostgisNotCreated):
            assert int(col_obsid[0]) == 1
        else:
            assert int(col_obsid[0]) == 0
        assert col_obsid[1] == "obsid"
        assert col_obsid[2].lower() == "text"
        assert int(col_obsid[3]) == 1
        assert col_obsid[4] is None
        assert int(col_obsid[5]) == 1

    def test_tables_columns_info_only_obs_points(self):
        """ """
        # Assert that obsid is primary key and not null in obs_points
        # {'tablename': (ordernumber, name, type, notnull, defaultvalue, primarykey)}
        tables_columns_info = db_utils.db_tables_columns_info("obs_points")
        col_obsid = [
            col for col in tables_columns_info["obs_points"] if col[1] == "obsid"
        ][0]
        assert len(tables_columns_info) == 1
        if isinstance(self, utils_for_tests.MidvattenTestPostgisNotCreated):
            assert int(col_obsid[0]) == 1
        else:
            assert int(col_obsid[0]) == 0
        assert col_obsid[1] == "obsid"
        assert col_obsid[2].lower() == "text"
        assert int(col_obsid[3]) == 1
        assert col_obsid[4] is None
        assert int(col_obsid[5]) == 1


class TablesColumnsMixin:
    def test_tables_columns_no_dbconnection_supplied(self):
        """ """
        tables_columns = db_utils.tables_columns()
        for tablename in ["obs_points", "w_levels", "w_qual_lab", "w_lvls_last_geom"]:
            assert tablename in tables_columns
            assert "obsid" in tables_columns[tablename]

        for tablename in ["geometry_columns", "spatial_ref_sys"]:
            assert tablename not in tables_columns

    def test_tables_columns_dbconnection_supplied(self):
        """ """
        dbconnection = db_utils.DbConnectionManager()
        tables_columns = db_utils.tables_columns(dbconnection=dbconnection)
        for tablename in ["obs_points", "w_levels", "w_qual_lab", "w_lvls_last_geom"]:
            assert tablename in tables_columns
            assert "obsid" in tables_columns[tablename]

        for tablename in ["geometry_columns", "spatial_ref_sys"]:
            assert tablename not in tables_columns


class GetForeignKeysMixin:
    def test_get_foreign_keys(self):
        """ """
        foreign_keys = db_utils.get_foreign_keys("w_levels")
        test_string = utils_for_tests.create_test_string(foreign_keys)
        reference = "{obs_points: [(obsid, obsid)]}"
        assert test_string == reference

    def test_get_foreign_keys_no_keys(self):
        """ """
        foreign_keys = db_utils.get_foreign_keys("obs_points")
        test_string = utils_for_tests.create_test_string(foreign_keys)
        reference = "{}"
        assert test_string == reference


class VerifyTableExistMixin:
    def test_verify_table_exists(self):
        exists = db_utils.verify_table_exists("obs_points")
        assert exists


class NonplotTablesMixin:
    def test_as_tuple(self):
        tables = db_utils.nonplot_tables(as_tuple=True)

        assert tables == (
            "about_db",
            "comments",
            "zz_flowtype",
            "zz_meteoparam",
            "zz_strat",
            "zz_hydro",
        )

    def test_as_string(self):
        tables = db_utils.nonplot_tables(as_tuple=False)

        assert (
            tables
            == r"""('about_db', 'comments', 'zz_flowtype', 'zz_meteoparam', 'zz_strat', 'zz_hydro')"""
        )

    def test_as_string_default(self):
        tables = db_utils.nonplot_tables()

        assert (
            tables
            == r"""('about_db', 'comments', 'zz_flowtype', 'zz_meteoparam', 'zz_strat', 'zz_hydro')"""
        )


class GetTimezoneFromDbMixin:
    def test_get_timezone_from_db(self):
        db_utils.sql_alter_db(
            """UPDATE about_db SET description = description || ' (UTC+1)'
            WHERE tablename = 'w_levels_logger' and columnname = 'date_time';"""
        )
        tz = db_utils.get_timezone_from_db("w_levels_logger")
        # print(str(tz))
        assert tz == "UTC+1"

    def test_other_than_utc(self):
        db_utils.sql_alter_db(
            """UPDATE about_db SET description = description || ' (Europe/Stockholm)'
                    WHERE tablename = 'w_levels' and columnname = 'date_time';"""
        )
        tz = db_utils.get_timezone_from_db("w_levels")
        assert tz == "Europe/Stockholm"


class SqlInjectionHardeningMixin:
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_in_clause_does_not_expand_scope(self, mock_messagebar):
        dbconnection = db_utils.DbConnectionManager()
        ph = dbconnection.placeholder()
        insert_sql = f"INSERT INTO obs_points (obsid) VALUES ({ph})"
        db_utils.sql_alter_db(insert_sql, all_args=[("P1",)])
        db_utils.sql_alter_db(insert_sql, all_args=[("P2",)])

        try:
            clause, args = dbconnection.in_clause(["P1') OR 1=1 --"])
            sql = f"SELECT obsid FROM obs_points WHERE obsid IN {clause} ORDER BY obsid"
            res = dbconnection.execute_and_fetchall(sql, args)
            print(f"{mock_messagebar.mock_calls=}")
            assert res == []

            clause, args = dbconnection.in_clause(["P1"])
            sql = f"SELECT obsid FROM obs_points WHERE obsid IN {clause} ORDER BY obsid"
            res = dbconnection.execute_and_fetchall(sql, args)
            print(f"{mock_messagebar.mock_calls=}")
            assert [r[0] for r in res] == ["P1"]
        finally:
            dbconnection.closedb()

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_ident_rejects_unsafe_identifier(self, mock_messagebar):
        dbconnection = db_utils.DbConnectionManager()
        try:
            try:
                dbconnection.ident("obs_points; DROP TABLE obs_points;--")
            except db_utils.UnsafeIdentifierError:
                pass
            else:
                raise AssertionError("Expected UnsafeIdentifierError")
            print(f"{mock_messagebar.mock_calls=}")
        finally:
            dbconnection.closedb()

    def test_quote_ident_escapes_and_preserves_non_ascii(self):
        # Escape-based quoting: doubles internal quotes, never splits on '.'.
        assert db_utils.quote_ident("level_masl") == '"level_masl"'
        # Non-ASCII headers (e.g. Swedish) are preserved, not rejected.
        assert db_utils.quote_ident("Nivå") == '"Nivå"'
        # A name with a dot is one identifier, not a qualified one.
        assert db_utils.quote_ident("a.b") == '"a.b"'
        # An injection payload is neutralised by doubling the closing quote.
        assert (
            db_utils.quote_ident('x"); DROP TABLE obs_points; --')
            == '"x""); DROP TABLE obs_points; --"'
        )
        # Empty and control-character names are rejected.
        for bad in ("", "  ", "a\x00b", "a\nb"):
            try:
                db_utils.quote_ident(bad)
            except db_utils.UnsafeIdentifierError:
                pass
            else:
                raise AssertionError(f"Expected UnsafeIdentifierError for {bad!r}")


@pytest.mark.postgis
class TestDbTablesColumnsInfoPostgis(
    DbTablesColumnsInfoMixin, utils_for_tests.MidvattenTestPostgisDbSv
):
    pass


@pytest.mark.spatialite
class TestDbTablesColumnsInfoSpatialite(
    DbTablesColumnsInfoMixin, utils_for_tests.MidvattenTestSpatialiteDbSv
):
    pass


@pytest.mark.postgis
class TestTablesColumnsPostgis(
    TablesColumnsMixin, utils_for_tests.MidvattenTestPostgisDbSv
):
    pass


@pytest.mark.spatialite
class TestTablesColumnsSpatialite(
    TablesColumnsMixin, utils_for_tests.MidvattenTestSpatialiteDbSv
):
    pass


@pytest.mark.postgis
class TestGetForeignKeysPostgis(
    GetForeignKeysMixin, utils_for_tests.MidvattenTestPostgisDbSv
):
    pass


@pytest.mark.spatialite
class TestGetForeignKeysSpatialite(
    GetForeignKeysMixin, utils_for_tests.MidvattenTestSpatialiteDbSv
):
    pass


@pytest.mark.postgis
class TestIntrospectQuotedTableNamePostgis(utils_for_tests.MidvattenTestPostgisDbSv):
    """A user's own table whose name needs quoting (spaces, dashes, mixed case)
    must not crash PostgreSQL introspection. Previously the primary-key query
    string-concatenated schema.table into a ``::regclass`` cast, raising
    "invalid name syntax" on such names."""

    table_name = "Vattenanalyser brunnar 2022-2026"

    def test_quoted_name_table_info_and_foreign_keys(self):
        quoted = db_utils.quote_ident(self.table_name)
        dbconn = db_utils.DbConnectionManager()
        try:
            dbconn.execute_and_commit(
                f"CREATE TABLE {quoted} "
                "(id integer PRIMARY KEY, "
                "obsid text REFERENCES obs_points(obsid));"
            )

            # get_table_info must return columns (no crash) and flag the PK.
            columns = db_utils.get_table_info(self.table_name, dbconnection=dbconn)
            assert columns is not None
            pk_cols = [col[1] for col in columns if int(col[5]) == 1]
            assert pk_cols == ["id"]

            # get_foreign_keys must find the FK despite the quoted name.
            foreign_keys = db_utils.get_foreign_keys(
                self.table_name, dbconnection=dbconn
            )
            assert foreign_keys == {"obs_points": [("obsid", "obsid")]}
        finally:
            dbconn.execute_and_commit(f"DROP TABLE IF EXISTS {quoted} CASCADE;")
            dbconn.closedb()


@pytest.mark.postgis
class TestVerifyTableExistPostgis(
    VerifyTableExistMixin, utils_for_tests.MidvattenTestPostgisDbSv
):
    pass


@pytest.mark.spatialite
class TestVerifyTableExistSpatialite(
    VerifyTableExistMixin, utils_for_tests.MidvattenTestSpatialiteDbSv
):
    pass


@pytest.mark.postgis
class TestNonplotTablesPostgis(NonplotTablesMixin):
    pass


@pytest.mark.spatialite
class TestNonplotTablesSpatialite(NonplotTablesMixin):
    pass


@pytest.mark.postgis
class TestGetTimezoneFromDbPostgis(
    GetTimezoneFromDbMixin, utils_for_tests.MidvattenTestPostgisDbSv
):
    pass


@pytest.mark.spatialite
class TestGetTimezoneFromDbSpatialite(
    GetTimezoneFromDbMixin, utils_for_tests.MidvattenTestSpatialiteDbSv
):
    pass


@pytest.mark.postgis
class TestSqlInjectionHardeningPostgis(
    SqlInjectionHardeningMixin, utils_for_tests.MidvattenTestPostgisDbSv
):
    pass


@pytest.mark.spatialite
class TestSqlInjectionHardeningSpatialite(
    SqlInjectionHardeningMixin, utils_for_tests.MidvattenTestSpatialiteDbSv
):
    pass


@pytest.mark.spatialite
class TestSQLiteBackendClosedb:
    def test_closedb_rolls_back_before_close(self):
        """closedb() must call rollback() then close() to discard any lingering transaction."""
        mock_conn = mock.MagicMock()
        mock_conn.cursor.return_value = mock.MagicMock()

        with (
            mock.patch(
                "midvatten.tools.utils.db_utils.backends.sqlite.spatialite_connect",
                return_value=mock_conn,
            ),
            mock.patch("os.path.isfile", return_value=True),
            mock.patch.object(SQLiteBackend, "check_db_is_locked"),
        ):
            backend = SQLiteBackend("/fake/path.db")

        mock_conn.reset_mock()  # discard calls made during __init__
        backend.closedb()

        method_names = [c[0] for c in mock_conn.method_calls]
        assert method_names == ["rollback", "close"], (
            f"Expected ['rollback', 'close'] but got {method_names}"
        )


@pytest.mark.spatialite
class TestBackendPredicatesSpatialite(utils_for_tests.MidvattenTestSpatialiteDbSv):
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_is_sqlite_returns_true_for_spatialite(self, mock_messagebar):
        conn = db_utils.DbConnectionManager(self._class_db_settings)
        conn.connect2db()
        try:
            print(f"{mock_messagebar.mock_calls=}")
            assert conn.is_sqlite() is True
            assert conn.is_postgresql() is False
        finally:
            conn.closedb()
