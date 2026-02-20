"""
/***************************************************************************
 This part of the Midvatten plugin tests the module that prepares midvatten
 tables for Qgis2Threejs.

                             -------------------
        begin                : 2019-03-11
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
from unittest.mock import MagicMock
from nose.plugins.attrib import attr

from midvatten.test import utils_for_tests
from midvatten.tools.utils import common_utils
from midvatten.tools.utils import db_utils


#
@attr(status="on")
class TestPrepareQgis2Threejs(utils_for_tests.MidvattenTestSpatialiteDbSv):
    """This test has conflicts with sectionplot, so its off!"""

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    @mock.patch("qgis.utils.iface", autospec=True)
    def test_prepare_qgis2threejs(self, mock_iface, mock_messagebar):
        dbconnection = db_utils.DbConnectionManager()
        dbconnection.execute(
            """INSERT INTO obs_points (obsid, h_gs, geometry) VALUES ('1', 1, ST_GeomFromText('POINT(1 1)', 3006)); """
        )
        dbconnection.execute(
            """INSERT INTO stratigraphy (obsid, stratid, depthtop, depthbot, geoshort) VALUES ('1', 1, 0, 1, 'torv'); """
        )
        dbconnection.execute(
            """INSERT INTO stratigraphy (obsid, stratid, depthtop, depthbot, geoshort) VALUES ('1', 2, 1, 2, 'fyll'); """
        )
        dbconnection.commit_and_closedb()
        # print(str(db_utils.sql_load_fr_db('''SELECT * FROM stratigraphy;''')))

        canvas = MagicMock()
        mock_iface.mapCanvas.return_value = canvas

        self.midvatten.prepare_layers_for_qgis2threejs()

        layers = [
            "strat_torv",
            "strat_fyll",
            "strat_lera",
            "strat_silt",
            "strat_finsand",
            "strat_mellansand",
            "strat_sand",
            "strat_grovsand",
            "strat_fingrus",
            "strat_mellangrus",
            "strat_grus",
            "strat_grovgrus",
            "strat_morn",
            "strat_berg",
            "strat_obs_p_for_qgsi2threejs",
        ]

        dbconnection = db_utils.DbConnectionManager()
        try:
            view_contents = []
            for layer_name in layers:
                if layer_name != "strat_obs_p_for_qgsi2threejs":
                    sql = dbconnection.sql_ident(
                        "SELECT rowid, obsid, z_coord, height, ST_AsText(geometry) FROM {t}",
                        t=layer_name,
                    )
                    view_contents.append(
                        db_utils.sql_load_fr_db(
                            sql, dbconnection=dbconnection
                        )[1]
                    )
            sql = dbconnection.sql_ident(
                "SELECT rowid, obsid, ST_AsText(geometry) FROM {t}",
                t="strat_obs_p_for_qgsi2threejs",
            )
            view_contents.append(
                db_utils.sql_load_fr_db(sql, dbconnection=dbconnection)[1]
            )
        finally:
            dbconnection.closedb()
        test = common_utils.anything_to_string_representation(view_contents)
        print(str(test))
        ref = """[[(1, "1", 1.0, -1.0, "POINT(1 1)", )], [(2, "1", 0.0, -1.0, "POINT(1 1)", )], [], [], [], [], [], [], [], [], [], [], [], [], [(1, "1", "POINT(1 1)", )]]"""
        assert test == ref

        print(f"{mock_messagebar.mock_calls=}")
        assert not mock_messagebar.mock_calls
