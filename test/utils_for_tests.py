"""
/***************************************************************************
 This part of the Midvatten plugin with utilities used for testing.

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

import gc
import io
import os
import sqlite3 as _sqlite3
import tempfile
import unittest


# Use a non-interactive matplotlib backend to avoid Qt event loop issues during tests
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from unittest import mock
from qgis.PyQt.QtCore import QSettings
from qgis.PyQt.QtWidgets import QWidget, QDialog
from qgis.core import QgsApplication
from qgis.core import QgsProject, QgsVectorLayer, QgsFeature, QgsFields
from qgis.utils import spatialite_connect

from midvatten.midvatten_plugin import Midvatten
from midvatten.test.mocks_for_tests import DummyInterface2
from midvatten.tools.import_data_to_db import MidvDataImporter
from midvatten.tools.utils import common_utils, exceptions, string_utils
from midvatten.tools.utils import db_utils


# Tables that hold user data (populated during tests, not by new_db()/new_postgis_db()).
_DATA_TABLES = (
    "obs_points",
    "obs_lines",
    "w_levels",
    "w_levels_logger",
    "w_logger_series",
    "stratigraphy",
    "screen",
    "w_qual_field",
    "w_qual_lab",
    "w_flow",
    "meteo",
    "seismic_data",
    "vlf_data",
    "tem_data",
    "profile_images",
    "comments",
    "s_qual_lab",
    "w_qual_logger",
    "spatial_history",
)

# Reference tables populated by new_db()/new_postgis_db() that tests may also modify.
# These must also be reset between tests for the PostGIS class-level approach.
_REFERENCE_TABLES = (
    "about_db",
    "zz_capacity",
    "zz_capacity_plots",
    "zz_flowtype",
    "zz_interlab4_obsid_assignment",
    "zz_meteoparam",
    "zz_screen_plots",
    "zz_staff",
    "zz_strat",
    "zz_stratigraphy_plots",
)


class TestQapplicationIsRunning:
    """Tests that the QApplication is running"""

    def test_iface(self):
        assert QgsApplication.instance() is not None


def dict_to_sorted_list(adict):
    """
    Creates a list of a dict of dicts
    :param adict: a dict that may contain more dicts
    :return:

    >>> dict_to_sorted_list({'a': {'o':{'d': 1, 'c': 2}, 'e': ['u']}, 't': (5, 6)})
    ['a', 'e', 'u', 'o', 'c', '2', 'd', '1', 't', '5', '6']
    >>> dict_to_sorted_list({'a': {'o':{'d': 1, 'c': 2}, 'e': ['u']}, 't': (5, {'k': 8, 'i': 9})})
    ['a', 'e', 'u', 'o', 'c', '2', 'd', '1', 't', '5', 'i', '9', 'k', '8']
    >>> dict_to_sorted_list({'a': {'o':{'d': 1, 'c': 2}, 'e': ['u']}, 't': (5, {'k': 8, 'i': (9, 29)})})
    ['a', 'e', 'u', 'o', 'c', '2', 'd', '1', 't', '5', 'i', '9', 29, 'k', '8']

    """
    result_list = []
    if isinstance(adict, dict):
        for k, v in sorted(adict.items()):
            result_list.extend(dict_to_sorted_list(k))
            result_list.extend(dict_to_sorted_list(v))
    elif isinstance(adict, list) or isinstance(adict, tuple):
        for k in adict:
            result_list.extend(dict_to_sorted_list(k))
    else:
        result_list.append(string_utils.returnunicode(adict))  # .encode('utf-8'))
    return result_list


def create_test_string(anything=None):
    r"""Turns anything into a string used for testing.
    Delegates to common_utils.anything_to_string_representation with compact=True.
    :param anything: just about anything
    :return: A unicode string
     >>> create_test_string('123')
     '123'
     >>> create_test_string([1, 2, 3])
     '[1, 2, 3]'
     >>> create_test_string({3: 'a', 2: 'b', 1: ('c', 'd')})
     '{1: (c, d), 2: b, 3: a}'
    """
    return string_utils.anything_to_string_representation(anything, compact=True)


class ContextualStringIO(io.StringIO):
    """Copied function from stackoverflow"""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()  # icecrime does it, so I guess I should, too
        return False  # Indicate that we haven't handled the exception, if received


class MidvattenTestBase:
    def setup_method(self):
        self.stop_show()
        QgsProject.instance().clear()
        self.dummy_iface = DummyInterface2()
        self.iface = self.dummy_iface.mock
        self.midvatten = Midvatten(self.iface)
        self.midvatten.initGui()
        self.midvatten.setup()

    def stop_show(self):
        """Replace QWidget.show to stop the tests from producing a lot of dialogs.

        :return:
        """

        def show(self):
            # Do nothing
            pass

        QWidget.show = show
        QDialog.exec_ = show

    def teardown_method(self):
        plt.close("all")
        QgsProject.instance().clear()
        gc.collect()


class MidvattenTestSpatialiteNotCreated(MidvattenTestBase):
    def setup_method(self):
        # Use a unique path per test to avoid cross-test interference (disk I/O errors,
        # file-not-found when one test's teardown removes another test's DB).
        self.TEMP_DBPATH = os.path.join(
            tempfile.gettempdir(),
            f"tmp_midvatten_{os.getpid()}_{id(self)}.sqlite",
        )
        if self.TEMP_DBPATH and os.path.exists(self.TEMP_DBPATH):
            print(f"Error, the db did already exist: {self.TEMP_DBPATH}")
        self.remove_db()
        super().setup_method()

    def teardown_method(self):
        # Delete database
        self.remove_db()
        super().teardown_method()

    def remove_db(self):
        for ending in ["", "-journal", "-wal", "-shm"]:
            try:
                os.remove(self.TEMP_DBPATH + ending)
            except OSError:
                pass


class MidvattenTestSpatialiteDbSv(MidvattenTestSpatialiteNotCreated):
    """
    Base class for Spatialite tests using the Swedish locale.

    The database is created once per test class (in setup_class) and snapshotted
    into an in-memory SQLite connection via sqlite3.Connection.backup().  Each
    test restores the file from that snapshot (a fast page-level copy) instead of
    running the full new_db() schema creation for every test.
    """

    _class_dbpath: str = ""
    _class_snapshot: "_sqlite3.Connection" = None
    _class_db_settings: str = ""

    @classmethod
    def setup_class(cls):
        """Create the DB once and take an in-memory snapshot."""
        cls._class_dbpath = os.path.join(
            tempfile.gettempdir(),
            f"tmp_midvatten_cls_{os.getpid()}_{id(cls)}.sqlite",
        )
        # Remove any leftover from an interrupted previous run.
        for ending in ("", "-journal", "-wal", "-shm"):
            try:
                os.remove(cls._class_dbpath + ending)
            except OSError:
                pass

        QgsProject.instance().clear()
        dummy = DummyInterface2()
        mv = Midvatten(dummy.mock)
        mv.initGui()
        mv.setup()

        with mock.patch(
            "midvatten.midvatten_plugin.NewSpatialiteDbDialog"
        ) as mock_dialog_cls:
            mock_dlg = mock.MagicMock()
            mock_dialog_cls.return_value = mock_dlg
            mock_dlg.exec.return_value = 1
            mock_dlg.locale = "sv_SE"
            mock_dlg.epsg_code = 3006
            mock_dlg.w_levels_logger_timezone = ""
            mock_dlg.w_levels_timezone = ""
            mock_dlg.dbpath = cls._class_dbpath
            mv.new_db()

        cls._class_db_settings = mv.ms.settingsdict["database"]

        # Snapshot the freshly-created DB into memory via a page-level backup.
        src = spatialite_connect(
            cls._class_dbpath,
            detect_types=_sqlite3.PARSE_DECLTYPES | _sqlite3.PARSE_COLNAMES,
        )
        cls._class_snapshot = _sqlite3.connect(":memory:")
        src.backup(cls._class_snapshot)
        src.close()

        QgsProject.instance().clear()

    @classmethod
    def teardown_class(cls):
        """Release the in-memory snapshot and delete the DB file."""
        if cls._class_snapshot is not None:
            cls._class_snapshot.close()
            cls._class_snapshot = None
        for ending in ("", "-journal", "-wal", "-shm"):
            try:
                os.remove(cls._class_dbpath + ending)
            except OSError:
                pass

    def setup_method(self):
        """Restore the DB from the class-level snapshot, then reinitialise the plugin."""
        # Restore the on-disk file from the in-memory snapshot (fast page-level copy).
        restore_conn = spatialite_connect(
            self._class_dbpath,
            detect_types=_sqlite3.PARSE_DECLTYPES | _sqlite3.PARSE_COLNAMES,
        )
        self.__class__._class_snapshot.backup(restore_conn)
        restore_conn.close()

        # Preserve the TEMP_DBPATH interface used by test helpers.
        self.TEMP_DBPATH = self._class_dbpath

        # Reinitialise the QGIS plugin (cheap — no DB creation).
        MidvattenTestBase.setup_method(self)

        # Restore DB path in QgsProject (wiped by QgsProject.instance().clear() above).
        QgsProject.instance().writeEntry(
            "Midvatten", "database", self._class_db_settings
        )
        self.midvatten.ms.load_settings()

    def teardown_method(self):
        """Close plots and clear project. Do NOT delete the class-level DB file."""
        plt.close("all")
        QgsProject.instance().clear()
        gc.collect()

    def remove_db(self):
        """No-op: the class-level DB file is managed by setup_class/teardown_class."""
        pass


class MidvattenTestSpatialiteDbEn(MidvattenTestSpatialiteNotCreated):
    """
    Base class for Spatialite tests using the English locale.

    Same class-level snapshot strategy as MidvattenTestSpatialiteDbSv.
    """

    _class_dbpath: str = ""
    _class_snapshot: "_sqlite3.Connection" = None
    _class_db_settings: str = ""

    @classmethod
    def setup_class(cls):
        """Create the DB once and take an in-memory snapshot."""
        cls._class_dbpath = os.path.join(
            tempfile.gettempdir(),
            f"tmp_midvatten_cls_{os.getpid()}_{id(cls)}.sqlite",
        )
        for ending in ("", "-journal", "-wal", "-shm"):
            try:
                os.remove(cls._class_dbpath + ending)
            except OSError:
                pass

        QgsProject.instance().clear()
        dummy = DummyInterface2()
        mv = Midvatten(dummy.mock)
        mv.initGui()
        mv.setup()

        with mock.patch(
            "midvatten.midvatten_plugin.NewSpatialiteDbDialog"
        ) as mock_dialog_cls:
            mock_dlg = mock.MagicMock()
            mock_dialog_cls.return_value = mock_dlg
            mock_dlg.exec.return_value = 1
            mock_dlg.locale = "en_US"
            mock_dlg.epsg_code = 3006
            mock_dlg.w_levels_logger_timezone = ""
            mock_dlg.w_levels_timezone = ""
            mock_dlg.dbpath = cls._class_dbpath
            mv.new_db()

        cls._class_db_settings = mv.ms.settingsdict["database"]

        src = spatialite_connect(
            cls._class_dbpath,
            detect_types=_sqlite3.PARSE_DECLTYPES | _sqlite3.PARSE_COLNAMES,
        )
        cls._class_snapshot = _sqlite3.connect(":memory:")
        src.backup(cls._class_snapshot)
        src.close()

        QgsProject.instance().clear()

    @classmethod
    def teardown_class(cls):
        """Release the in-memory snapshot and delete the DB file."""
        if cls._class_snapshot is not None:
            cls._class_snapshot.close()
            cls._class_snapshot = None
        for ending in ("", "-journal", "-wal", "-shm"):
            try:
                os.remove(cls._class_dbpath + ending)
            except OSError:
                pass

    def setup_method(self):
        """Restore the DB from the class-level snapshot, then reinitialise the plugin."""
        restore_conn = spatialite_connect(
            self._class_dbpath,
            detect_types=_sqlite3.PARSE_DECLTYPES | _sqlite3.PARSE_COLNAMES,
        )
        self.__class__._class_snapshot.backup(restore_conn)
        restore_conn.close()

        self.TEMP_DBPATH = self._class_dbpath

        MidvattenTestBase.setup_method(self)

        QgsProject.instance().writeEntry(
            "Midvatten", "database", self._class_db_settings
        )
        self.midvatten.ms.load_settings()

    def teardown_method(self):
        plt.close("all")
        QgsProject.instance().clear()
        gc.collect()

    def remove_db(self):
        """No-op: the class-level DB file is managed by setup_class/teardown_class."""
        pass


class MidvattenTestSpatialiteDbSvImportInstance(MidvattenTestSpatialiteDbSv):
    def setup_method(self):
        super().setup_method()
        self.importinstance = MidvDataImporter()

    def teardown_method(self):
        self.importinstance = None
        super().teardown_method()


class MidvattenTestPostgisNotCreated(MidvattenTestBase):
    ALL_POSTGIS_SETTINGS = {
        "nosetests": {
            "estimatedMetadata": "false",
            "publicOnly": "false",
            "service": "",
            "database": "nosetests",
            "dontResolveType": "false",
            "saveUsername": "true",
            "sslmode": "1",
            "host": "127.0.0.1",
            "authcfg": "",
            "geometryColumnsOnly": "false",
            "allowGeometrylessTables": "false",
            "savePassword": "false",
            "port": "5432",
        }
    }
    TEMP_DB_SETTINGS = {"postgis": {"connection": "nosetests/127.0.0.1:5432/nosetests"}}

    def setup_method(self):
        super().setup_method()
        QgsProject.instance().writeEntry(
            "Midvatten",
            "database",
            string_utils.anything_to_string_representation(
                MidvattenTestPostgisNotCreated.TEMP_DB_SETTINGS
            ),
        )
        qs = QSettings()
        for k, v in MidvattenTestPostgisNotCreated.ALL_POSTGIS_SETTINGS[
            "nosetests"
        ].items():
            qs.setValue("PostgreSQL/connections/{}/{}".format("nosetests", k), v)
        # Clear the database; skip PostGIS tests when server is not available
        try:
            dbconn = db_utils.DbConnectionManager()
            dbconn.execute_and_commit("DROP SCHEMA IF EXISTS public CASCADE;")
            dbconn.execute_and_commit("CREATE SCHEMA public;")
            dbconn.closedb()
        except exceptions.UserInterruptError as e:
            raise unittest.SkipTest("PostGIS not available (no password): %s" % e)
        except Exception as e:
            if (
                "password" in str(e).lower()
                or "connect" in str(e).lower()
                or "could not connect" in str(e).lower()
            ):
                raise unittest.SkipTest("PostGIS not available: %s" % e)
            raise

        # Skip if PostGIS extension cannot be created (e.g. insufficient privileges)
        try:
            dbconnection = db_utils.DbConnectionManager()
            dbconnection.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
            dbconnection.commit()
            dbconnection.closedb()
        except exceptions.UserInterruptError:
            raise
        except Exception as e:
            err = str(e).lower()
            if (
                "privilege" in err
                or "superuser" in err
                or "extension" in err
                or "rättighet" in err
                or "saknas" in err
            ):
                raise unittest.SkipTest("PostGIS extension not available: %s" % e)

    def teardown_method(self):
        # Clear the database
        try:
            dbconn = db_utils.DbConnectionManager()
            dbconn.execute_and_commit("DROP SCHEMA IF EXISTS public CASCADE;")
            dbconn.execute_and_commit("CREATE SCHEMA public;")
            dbconn.closedb()
        except Exception as e:
            print("Failure resetting db: " + str(e))
        super().teardown_method()


class MidvattenTestPostgisDbSv(MidvattenTestPostgisNotCreated):
    """
    Base class for PostGIS tests using the Swedish locale.

    The schema is created once per test class (in setup_class).  Between tests,
    all tables are truncated and reference data is restored from an in-memory
    Python snapshot — much faster than DROP/CREATE SCHEMA per test.
    """

    _class_db_settings: str = ""
    # {table_name: (column_names_tuple, list_of_row_tuples)}
    _reference_snapshot: dict = {}

    @classmethod
    def setup_class(cls):
        """Create the PostGIS schema once and snapshot all reference-table data."""
        qs = QSettings()
        for k, v in MidvattenTestPostgisNotCreated.ALL_POSTGIS_SETTINGS[
            "nosetests"
        ].items():
            qs.setValue("PostgreSQL/connections/{}/{}".format("nosetests", k), v)

        QgsProject.instance().clear()
        QgsProject.instance().writeEntry(
            "Midvatten",
            "database",
            string_utils.anything_to_string_representation(
                MidvattenTestPostgisNotCreated.TEMP_DB_SETTINGS
            ),
        )

        try:
            dbconn = db_utils.DbConnectionManager()
            dbconn.execute_and_commit("DROP SCHEMA IF EXISTS public CASCADE;")
            dbconn.execute_and_commit("CREATE SCHEMA public;")
            dbconn.closedb()
        except exceptions.UserInterruptError as e:
            raise unittest.SkipTest("PostGIS not available (no password): %s" % e)
        except Exception as e:
            if (
                "password" in str(e).lower()
                or "connect" in str(e).lower()
                or "could not connect" in str(e).lower()
            ):
                raise unittest.SkipTest("PostGIS not available: %s" % e)
            raise

        try:
            dbconnection = db_utils.DbConnectionManager()
            dbconnection.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
            dbconnection.commit()
            dbconnection.closedb()
        except exceptions.UserInterruptError:
            raise
        except Exception as e:
            err = str(e).lower()
            if (
                "privilege" in err
                or "superuser" in err
                or "extension" in err
                or "rättighet" in err
                or "saknas" in err
            ):
                raise unittest.SkipTest("PostGIS extension not available: %s" % e)

        dummy = DummyInterface2()
        mv = Midvatten(dummy.mock)
        mv.initGui()
        mv.setup()

        with mock.patch(
            "midvatten.midvatten_plugin.NewPostgisDbDialog"
        ) as mock_dialog_cls:
            mock_dlg = mock.MagicMock()
            mock_dialog_cls.return_value = mock_dlg
            mock_dlg.exec.return_value = 1
            mock_dlg.locale = "sv_SE"
            mock_dlg.epsg_code = 3006
            mock_dlg.w_levels_logger_timezone = ""
            mock_dlg.w_levels_timezone = ""
            mv.new_postgis_db()

        cls._class_db_settings = mv.ms.settingsdict["database"]

        # Snapshot all reference tables so they can be restored cheaply per test.
        cls._reference_snapshot = {}
        dbconn = db_utils.DbConnectionManager()
        for table in _REFERENCE_TABLES:
            try:
                rows = dbconn.execute_and_fetchall(f"SELECT * FROM {table}")
                cols = tuple(desc[0] for desc in dbconn.cursor.description)
                cls._reference_snapshot[table] = (cols, list(rows))
            except Exception as e:
                print(f"Warning: could not snapshot reference table {table}: {e}")
        dbconn.closedb()

        QgsProject.instance().clear()

    @classmethod
    def teardown_class(cls):
        """Drop the public schema once after all tests in the class finish."""
        cls._reference_snapshot = {}
        # teardown_method clears QgsProject; restore DB settings before connecting.
        qs = QSettings()
        for k, v in MidvattenTestPostgisNotCreated.ALL_POSTGIS_SETTINGS[
            "nosetests"
        ].items():
            qs.setValue("PostgreSQL/connections/{}/{}".format("nosetests", k), v)
        QgsProject.instance().writeEntry(
            "Midvatten",
            "database",
            string_utils.anything_to_string_representation(
                MidvattenTestPostgisNotCreated.TEMP_DB_SETTINGS
            ),
        )
        try:
            dbconn = db_utils.DbConnectionManager()
            dbconn.execute_and_commit("DROP SCHEMA IF EXISTS public CASCADE;")
            dbconn.execute_and_commit("CREATE SCHEMA public;")
            dbconn.closedb()
        except Exception as e:
            print("MidvattenTestPostgisDbSv teardown_class failure: " + str(e))

    def setup_method(self):
        """Truncate all tables and restore reference data, then reinitialise the plugin."""
        # Ensure the persistent QgsSettings for the connection are present.
        qs = QSettings()
        for k, v in MidvattenTestPostgisNotCreated.ALL_POSTGIS_SETTINGS[
            "nosetests"
        ].items():
            qs.setValue("PostgreSQL/connections/{}/{}".format("nosetests", k), v)

        # Point QgsProject at the DB so db_utils can open a connection.
        QgsProject.instance().writeEntry(
            "Midvatten",
            "database",
            string_utils.anything_to_string_representation(
                MidvattenTestPostgisNotCreated.TEMP_DB_SETTINGS
            ),
        )

        # Truncate all tables (data + reference) in one shot; CASCADE handles FKs.
        all_tables = _DATA_TABLES + _REFERENCE_TABLES
        truncate_sql = "TRUNCATE TABLE {} CASCADE;".format(", ".join(all_tables))
        dbconn = db_utils.DbConnectionManager()
        try:
            dbconn.execute(truncate_sql)
            # Re-insert reference data using a single multi-row INSERT per table
            # (one round-trip per table instead of one per row).
            for table, (cols, rows) in self.__class__._reference_snapshot.items():
                if rows:
                    ph = dbconn.placeholder()
                    col_names = ", ".join(cols)
                    row_placeholders = "({})".format(", ".join([ph] * len(cols)))
                    all_row_placeholders = ", ".join([row_placeholders] * len(rows))
                    insert_sql = f"INSERT INTO {table} ({col_names}) VALUES {all_row_placeholders}"
                    flat_args = [val for row in rows for val in row]
                    dbconn.execute(insert_sql, flat_args)
        finally:
            dbconn.closedb()

        # Reinitialise the QGIS plugin (QgsProject.clear() happens inside here).
        MidvattenTestBase.setup_method(self)

        # Restore DB path (wiped by QgsProject.instance().clear() above).
        QgsProject.instance().writeEntry(
            "Midvatten", "database", self._class_db_settings
        )
        self.midvatten.ms.load_settings()

    def teardown_method(self):
        """Close plots and clear project. Schema cleanup is in teardown_class."""
        plt.close("all")
        QgsProject.instance().clear()
        gc.collect()


class MidvattenTestPostgisDbEn(MidvattenTestPostgisNotCreated):
    """
    Base class for PostGIS tests using the English locale.

    Same class-level snapshot strategy as MidvattenTestPostgisDbSv.
    """

    _class_db_settings: str = ""
    _reference_snapshot: dict = {}

    @classmethod
    def setup_class(cls):
        """Create the PostGIS schema once and snapshot all reference-table data."""
        qs = QSettings()
        for k, v in MidvattenTestPostgisNotCreated.ALL_POSTGIS_SETTINGS[
            "nosetests"
        ].items():
            qs.setValue("PostgreSQL/connections/{}/{}".format("nosetests", k), v)

        QgsProject.instance().clear()
        QgsProject.instance().writeEntry(
            "Midvatten",
            "database",
            string_utils.anything_to_string_representation(
                MidvattenTestPostgisNotCreated.TEMP_DB_SETTINGS
            ),
        )

        try:
            dbconn = db_utils.DbConnectionManager()
            dbconn.execute_and_commit("DROP SCHEMA IF EXISTS public CASCADE;")
            dbconn.execute_and_commit("CREATE SCHEMA public;")
            dbconn.closedb()
        except exceptions.UserInterruptError as e:
            raise unittest.SkipTest("PostGIS not available (no password): %s" % e)
        except Exception as e:
            if (
                "password" in str(e).lower()
                or "connect" in str(e).lower()
                or "could not connect" in str(e).lower()
            ):
                raise unittest.SkipTest("PostGIS not available: %s" % e)
            raise

        try:
            dbconnection = db_utils.DbConnectionManager()
            dbconnection.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
            dbconnection.commit()
            dbconnection.closedb()
        except exceptions.UserInterruptError:
            raise
        except Exception as e:
            err = str(e).lower()
            if (
                "privilege" in err
                or "superuser" in err
                or "extension" in err
                or "rättighet" in err
                or "saknas" in err
            ):
                raise unittest.SkipTest("PostGIS extension not available: %s" % e)

        dummy = DummyInterface2()
        mv = Midvatten(dummy.mock)
        mv.initGui()
        mv.setup()

        with mock.patch(
            "midvatten.midvatten_plugin.NewPostgisDbDialog"
        ) as mock_dialog_cls:
            mock_dlg = mock.MagicMock()
            mock_dialog_cls.return_value = mock_dlg
            mock_dlg.exec.return_value = 1
            mock_dlg.locale = "en_US"
            mock_dlg.epsg_code = 3006
            mock_dlg.w_levels_logger_timezone = ""
            mock_dlg.w_levels_timezone = ""
            mv.new_postgis_db()

        cls._class_db_settings = mv.ms.settingsdict["database"]

        cls._reference_snapshot = {}
        dbconn = db_utils.DbConnectionManager()
        for table in _REFERENCE_TABLES:
            try:
                rows = dbconn.execute_and_fetchall(f"SELECT * FROM {table}")
                cols = tuple(desc[0] for desc in dbconn.cursor.description)
                cls._reference_snapshot[table] = (cols, list(rows))
            except Exception as e:
                print(f"Warning: could not snapshot reference table {table}: {e}")
        dbconn.closedb()

        QgsProject.instance().clear()

    @classmethod
    def teardown_class(cls):
        """Drop the public schema once after all tests in the class finish."""
        cls._reference_snapshot = {}
        # teardown_method clears QgsProject; restore DB settings before connecting.
        qs = QSettings()
        for k, v in MidvattenTestPostgisNotCreated.ALL_POSTGIS_SETTINGS[
            "nosetests"
        ].items():
            qs.setValue("PostgreSQL/connections/{}/{}".format("nosetests", k), v)
        QgsProject.instance().writeEntry(
            "Midvatten",
            "database",
            string_utils.anything_to_string_representation(
                MidvattenTestPostgisNotCreated.TEMP_DB_SETTINGS
            ),
        )
        try:
            dbconn = db_utils.DbConnectionManager()
            dbconn.execute_and_commit("DROP SCHEMA IF EXISTS public CASCADE;")
            dbconn.execute_and_commit("CREATE SCHEMA public;")
            dbconn.closedb()
        except Exception as e:
            print("MidvattenTestPostgisDbEn teardown_class failure: " + str(e))

    def setup_method(self):
        """Truncate all tables and restore reference data, then reinitialise the plugin."""
        qs = QSettings()
        for k, v in MidvattenTestPostgisNotCreated.ALL_POSTGIS_SETTINGS[
            "nosetests"
        ].items():
            qs.setValue("PostgreSQL/connections/{}/{}".format("nosetests", k), v)

        QgsProject.instance().writeEntry(
            "Midvatten",
            "database",
            string_utils.anything_to_string_representation(
                MidvattenTestPostgisNotCreated.TEMP_DB_SETTINGS
            ),
        )

        all_tables = _DATA_TABLES + _REFERENCE_TABLES
        truncate_sql = "TRUNCATE TABLE {} CASCADE;".format(", ".join(all_tables))
        dbconn = db_utils.DbConnectionManager()
        try:
            dbconn.execute(truncate_sql)
            for table, (cols, rows) in self.__class__._reference_snapshot.items():
                if rows:
                    ph = dbconn.placeholder()
                    col_names = ", ".join(cols)
                    row_placeholders = "({})".format(", ".join([ph] * len(cols)))
                    all_row_placeholders = ", ".join([row_placeholders] * len(rows))
                    insert_sql = f"INSERT INTO {table} ({col_names}) VALUES {all_row_placeholders}"
                    flat_args = [val for row in rows for val in row]
                    dbconn.execute(insert_sql, flat_args)
        finally:
            dbconn.closedb()

        MidvattenTestBase.setup_method(self)

        QgsProject.instance().writeEntry(
            "Midvatten", "database", self._class_db_settings
        )
        self.midvatten.ms.load_settings()

    def teardown_method(self):
        plt.close("all")
        QgsProject.instance().clear()
        gc.collect()


class MidvattenTestPostgisDbSvImportInstance(MidvattenTestPostgisDbSv):
    def setup_method(self):
        super().setup_method()
        self.importinstance = MidvDataImporter()

    def teardown_method(self):
        self.importinstance = None
        super().teardown_method()


def foreign_key_test_from_exception(e, dbtype):
    if dbtype == "spatialite":
        return str(e) == "FOREIGN KEY constraint failed"
    elif dbtype == "postgis":
        return "is not present in table" in str(e)


def compare_strings(str1, str2):
    if str1 and not str2:
        return "Str2 was empty and str1 not."
    elif str2 and not str1:
        return "Str1 was empty and str2 not."

    def return20chars(astr, idx, numidx):
        min_idx = max(0, idx - numidx)
        max_idx = min(len(astr), idx + numidx)
        return astr[min_idx:max_idx]

    diff = False
    for idx in range(len(str1)):
        str1_t = return20chars(str1, idx, 40)
        str2_t = return20chars(str2, idx, 40)

        if str1[idx] != str2[idx]:
            # print(str(str1_t))
            # print(str(str2_t))
            diff = True
            break
    if diff:
        return f"diff at idx {str(idx)}, \nstr1:{str1_t}\nstr2:{str2_t}"
    else:
        return "The same"


def recursive_children(parent):
    try:
        children = parent.children()
    except AttributeError:
        children = []

    try:
        valid = parent.layer().isValid()
    except AttributeError:
        valid = ""

    return [parent.name(), valid, [recursive_children(child) for child in children]]


def create_vectorlayer(
    _fields,
    data,
    geometries=None,
    geomtype="Point",
    crs=4326,
    select_ids=False,
    hide_print=True,
):
    """From GroupStats"""
    vlayer = QgsVectorLayer(f"{geomtype}?crs=epsg:{str(crs)}", "test", "memory")
    provider = vlayer.dataProvider()
    # print(str(crs))
    fields = QgsFields()
    for _field in _fields:
        fields.append(_field)

    provider.addAttributes(_fields)
    vlayer.updateFields()
    feats = []
    for f_idx, features_attributes in enumerate(data):
        feature = QgsFeature(fields)
        for idx, attr in enumerate(features_attributes):
            feature[_fields[idx].name()] = attr
        if geometries:
            feature.setGeometry(geometries[f_idx])
        else:
            feature.setGeometry(None)
        # print("Feature valid: " + str(feature.isValid()))
        feats.append(feature)
    provider.addFeatures(feats)
    vlayer.updateExtents()

    features = [
        f for f in vlayer.getFeatures("True") if f.id() in vlayer.allFeatureIds()
    ]
    feature_ids = [feature.id() for feature in features]
    if select_ids:
        vlayer.selectByIds(feature_ids)

    QgsProject.instance().addMapLayer(vlayer)
    if not hide_print:
        print(f"1. Valid vlayer '{vlayer.isValid()}'")
        print("2. feature_ids: " + str(feature_ids))
        print(
            "5. QgsVectorLayer.getFeature(): "
            + str([vlayer.getFeature(x).id() for x in feature_ids])
        )
        print(
            "6. QgsVectorLayer.getFeature() type: "
            + str([str(type(vlayer.getFeature(x))) for x in feature_ids])
        )
        print(
            "7. QgsVectorLayer.getFeatures(): "
            + str([x.id() for x in vlayer.getFeatures(feature_ids)])
        )
        print("8. QgsVectorLayer.featureCount(): " + str(vlayer.featureCount()))

    root = QgsProject.instance().layerTreeRoot()
    root.addLayer(vlayer)
    return vlayer
