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

import io
import os
import unittest


# Use a non-interactive matplotlib backend to avoid Qt event loop issues during tests
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from unittest import mock
import qgis
import qgis.PyQt
import qgis.core
from qgis.PyQt import QtCore
from qgis.PyQt.QtCore import QSettings
from qgis.PyQt.QtWidgets import QWidget, QDialog
from qgis.core import QgsApplication
from qgis.core import QgsProject, QgsVectorLayer, QgsFeature, QgsFields

from midvatten.midvatten_plugin import Midvatten
from midvatten.test.mocks_for_tests import DummyInterface2
from midvatten.tools.import_data_to_db import MidvDataImporter
from midvatten.tools.utils import common_utils
from midvatten.tools.utils import db_utils


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
        result_list.append(common_utils.returnunicode(adict))  # .encode('utf-8'))
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
    return common_utils.anything_to_string_representation(anything, compact=True)


class ContextualStringIO(io.StringIO):
    """Copied function from stackoverflow"""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()  # icecrime does it, so I guess I should, too
        return False  # Indicate that we haven't handled the exception, if received


class MidvattenTestBase:
    def __init__(self):
        self.stop_show()

    def setup_method(self):
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


class MidvattenTestSpatialiteNotCreated(MidvattenTestBase):
    def __init__(self):
        super().__init__()
        self.TEMP_DBPATH = "/tmp/tmp_midvatten_temp_db.sqlite"

    def setup_method(self):
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
    def setup_method(self):
        super().setup_method()

        def side_effect(*args, **kwargs):
            mock_result = mock.MagicMock()
            if kwargs.get("combobox_label", None) == "Locales":
                mock_result.answer = "ok"
                mock_result.value = "sv_SE"
            elif kwargs.get("combobox_label", None) == "Timezone":
                mock_result.answer = "ok"
                mock_result.value = ""
            return mock_result

        with mock.patch("qgis.PyQt.QtWidgets.QFileDialog.getSaveFileName") as mock_savefilename, \
             mock.patch("midvatten.tools.create_db.qgis.PyQt.QtWidgets.QInputDialog.getInt") as mock_crs_question, \
             mock.patch("midvatten.tools.utils.common_utils.Askuser") as mock_answer_yes, \
             mock.patch("midvatten.tools.create_db.common_utils.NotFoundQuestion") as mock_not_found:
            mock_not_found.side_effect = side_effect
            mock_answer_yes.return_value.result = 1
            mock_crs_question.return_value.__getitem__.return_value = 3006
            mock_savefilename.return_value = (self.TEMP_DBPATH, "Spatialite (*.sqlite)")
            self.midvatten.new_db()


class MidvattenTestSpatialiteDbEn(MidvattenTestSpatialiteNotCreated):
    def setup_method(self):
        super().setup_method()

        def side_effect(*args, **kwargs):
            mock_result = mock.MagicMock()
            if kwargs.get("combobox_label", None) == "Locales":
                mock_result.answer = "ok"
                mock_result.value = "en_US"
            elif kwargs.get("combobox_label", None) == "Timezone":
                mock_result.answer = "ok"
                mock_result.value = ""
            return mock_result

        with mock.patch("qgis.PyQt.QtWidgets.QFileDialog.getSaveFileName") as mock_savefilename, \
             mock.patch("midvatten.tools.create_db.qgis.PyQt.QtWidgets.QInputDialog.getInt") as mock_crs_question, \
             mock.patch("midvatten.tools.utils.common_utils.Askuser") as mock_answer_yes, \
             mock.patch("midvatten.tools.create_db.common_utils.NotFoundQuestion") as mock_not_found:
            mock_not_found.side_effect = side_effect
            mock_answer_yes.return_value.result = 1
            mock_crs_question.return_value.__getitem__.return_value = 3006
            mock_savefilename.return_value = (self.TEMP_DBPATH, "Spatialite (*.sqlite)")
            self.midvatten.new_db()


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

    def __init__(self):
        super().__init__()

    def setup_method(self):
        super().setup_method()
        QgsProject.instance().writeEntry(
            "Midvatten",
            "database",
            common_utils.anything_to_string_representation(
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
            db_utils.sql_alter_db("DROP SCHEMA public CASCADE;")
            db_utils.sql_alter_db("CREATE SCHEMA public;")
        except common_utils.UserInterruptError as e:
            raise unittest.SkipTest("PostGIS not available (no password): %s" % e)
        except Exception as e:
            if (
                "password" in str(e).lower()
                or "connect" in str(e).lower()
                or "could not connect" in str(e).lower()
            ):
                raise unittest.SkipTest("PostGIS not available: %s" % e)
            print("Failure resetting db: " + str(e))

        # Skip if PostGIS extension cannot be created (e.g. insufficient privileges)
        try:
            dbconnection = db_utils.DbConnectionManager()
            dbconnection.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
            dbconnection.commit()
            dbconnection.closedb()
        except common_utils.UserInterruptError:
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
        with mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog") as mock_messagebar:
            try:
                db_utils.sql_alter_db("DROP SCHEMA public CASCADE;")
                db_utils.sql_alter_db("CREATE SCHEMA public;")
            except Exception as e:
                print("Failure resetting db: " + str(e))
                print(
                    "MidvattenTestPostgisNotCreated teardown_method problem: "
                    + str(mock_messagebar.mock_calls)
                )
        super().teardown_method()


class MidvattenTestPostgisDbSv(MidvattenTestPostgisNotCreated):
    def setup_method(self):
        super().setup_method()

        def side_effect(*args, **kwargs):
            mock_result = mock.MagicMock()
            if kwargs.get("combobox_label", None) == "Locales":
                mock_result.answer = "ok"
                mock_result.value = "sv_SE"
            elif kwargs.get("combobox_label", None) == "Timezone":
                mock_result.answer = "ok"
                mock_result.value = ""
            return mock_result

        with mock.patch("midvatten.tools.create_db.qgis.PyQt.QtWidgets.QInputDialog.getInt") as mock_crs_question, \
             mock.patch("midvatten.tools.utils.common_utils.Askuser") as mock_answer_yes, \
             mock.patch("midvatten.tools.create_db.common_utils.NotFoundQuestion") as mock_not_found:
            mock_not_found.side_effect = side_effect
            mock_answer_yes.return_value.result = 1
            mock_crs_question.return_value.__getitem__.return_value = 3006
            self.midvatten.new_postgis_db()


class MidvattenTestPostgisDbEn(MidvattenTestPostgisNotCreated):
    def setup_method(self):
        super().setup_method()

        def side_effect(*args, **kwargs):
            mock_result = mock.MagicMock()
            if kwargs.get("combobox_label", None) == "Locales":
                mock_result.answer = "ok"
                mock_result.value = "en_US"
            elif kwargs.get("combobox_label", None) == "Timezone":
                mock_result.answer = "ok"
                mock_result.value = ""
            return mock_result

        with mock.patch("midvatten.tools.create_db.qgis.PyQt.QtWidgets.QInputDialog.getInt") as mock_crs_question, \
             mock.patch("midvatten.tools.utils.common_utils.Askuser") as mock_answer_yes, \
             mock.patch("midvatten.tools.create_db.common_utils.NotFoundQuestion") as mock_not_found:
            mock_not_found.side_effect = side_effect
            mock_answer_yes.return_value.result = 1
            mock_crs_question.return_value.__getitem__.return_value = 3006
            self.midvatten.new_postgis_db()


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
