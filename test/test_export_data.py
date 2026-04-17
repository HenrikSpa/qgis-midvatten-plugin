"""
/***************************************************************************
 This part of the Midvatten plugin tests the module that handles exports to
  csv format.

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
import tempfile
from unittest import mock

from midvatten.tools.export_spatialite import ExportSpatialite
from midvatten.tools.utils import common_utils, db_utils
from midvatten.test import utils_for_tests
from midvatten.test.mocks_for_tests import MockUsingReturnValue, MockReturnUsingDictIn
from midvatten.definitions import db_defs

EXPORT_DB_PATH = "/tmp/tmp_midvatten_export_db.sqlite"


# Unique path per test run to avoid cross-test pollution (shared path caused
# test_export_spatialite_zz_tables to see wrong data when other tests left a file).
def _unique_export_path(test_self):
    return os.path.join(
        tempfile.gettempdir(),
        f"tmp_midvatten_export_{os.getpid()}_{id(test_self)}.sqlite",
    )


TEMP_DIR = "/tmp/"
import pytest


class ExportMixin:
    answer_yes_obj = MockUsingReturnValue()
    answer_yes_obj.result = 1
    answer_no_obj = MockUsingReturnValue()
    answer_no_obj.result = 0
    answer_yes = MockUsingReturnValue(answer_yes_obj)
    crs_question = MockUsingReturnValue([3006])
    mock_askuser = MockReturnUsingDictIn(
        {"It is a strong": answer_no_obj, "Please note!\nThere are ": answer_yes_obj}, 1
    )
    skip_popup = MockUsingReturnValue("")
    mock_selection = MockReturnUsingDictIn(
        {"obs_points": ("P1",), "obs_lines": ("L1",)}, 0
    )
    mock_no_selection = MockReturnUsingDictIn(
        {"obs_points": tuple(), "obs_lines": tuple()}, 0
    )
    exported_csv_files = [
        os.path.join(TEMP_DIR, filename)
        for filename in [
            "obs_points.csv",
            "comments.csv",
            "w_levels.csv",
            "w_flow.csv",
            "w_qual_lab.csv",
            "w_qual_field.csv",
            "screen.csv",
            "stratigraphy.csv",
            "meteo.csv",
            "obs_lines.csv",
            "seismic_data.csv",
            "zz_flowtype.csv",
            "zz_meteoparam.csv",
            "zz_staff.csv",
            "zz_strat.csv",
            "zz_capacity.csv",
        ]
    ]
    exported_csv_files_no_zz = [
        os.path.join(TEMP_DIR, filename)
        for filename in [
            "obs_points.csv",
            "comments.csv",
            "w_levels.csv",
            "w_flow.csv",
            "w_qual_lab.csv",
            "w_qual_field.csv",
            "screen.csv",
            "stratigraphy.csv",
            "meteo.csv",
            "obs_lines.csv",
            "seismic_data.csv",
        ]
    ]

    @mock.patch(
        "midvatten.tools.utils.common_utils.get_selected_features_as_tuple",
        mock_selection.get_v,
    )
    @mock.patch("qgis.PyQt.QtWidgets.QFileDialog.getExistingDirectory")
    @mock.patch("qgis.utils.iface", autospec=True)
    def test_export_csv(self, mock_iface, mock_savepath):
        mock_savepath.return_value = "/tmp/"
        db_utils.sql_alter_db(
            """INSERT INTO obs_points (obsid, geometry) VALUES ('P1', ST_GeomFromText('POINT(633466 711659)', 3006))"""
        )
        db_utils.sql_alter_db("""INSERT INTO zz_staff (staff) VALUES ('s1')""")
        db_utils.sql_alter_db(
            """INSERT INTO comments (obsid, date_time, staff, comment) VALUES ('P1', '2015-01-01 00:00:00', 's1', 'comment1')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_qual_lab (obsid, parameter, report, staff) VALUES ('P1', 'labpar1', 'report1', 's1')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_qual_field (obsid, parameter, staff, date_time, unit) VALUES ('P1', 'labpar1', 's1', '2015-01-01 01:00:00', 'unit1')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_flow (obsid, instrumentid, flowtype, date_time, unit) VALUES ('P1', 'inst1', 'Momflow', '2015-04-13 00:00:00', 'l/s')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels (obsid, date_time, meas) VALUES ('P1', '2015-01-02 00:00:01', '2')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO stratigraphy (obsid, stratid, depthtop, depthbot) VALUES ('P1', 1, 0, 10)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO screen (obsid, screenid, depthtop, depthbot) VALUES ('P1', 1, 5, 8)"""
        )
        db_utils.sql_alter_db("""INSERT INTO obs_lines (obsid) VALUES ('L1')""")
        db_utils.sql_alter_db(
            """INSERT INTO seismic_data (obsid, length) VALUES ('L1', '5')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO meteo (obsid, instrumentid, parameter, date_time) VALUES ('P1', 'meteoinst', 'precip', '2017-01-01 00:19:00')"""
        )

        self.midvatten.export_csv()
        file_contents = []
        for filename in ExportMixin.exported_csv_files_no_zz:
            with open(filename, encoding="utf-8") as f:
                file_contents.append(os.path.basename(filename) + "\n")
                if os.path.basename(filename) == "obs_points.csv":
                    file_contents.append(
                        [
                            ";".join(line.replace("\r", "").split(";")[:-1]) + "\n"
                            for line in f
                        ]
                    )
                else:
                    file_contents.append([line.replace("\r", "") for line in f])
        test_string = utils_for_tests.create_test_string(file_contents)

        with open("/tmp/refstring.txt", "w", encoding="utf-8") as of:
            of.write(test_string)

        reference_string = "\n".join(
            [
                "[obs_points.csv",
                ", [obsid;name;place;type;length;drillstop;diam;material;screen;capacity;drilldate;wmeas_yn;wlogg_yn;east;north;ne_accur;ne_source;h_toc;h_tocags;h_gs;h_accur;h_syst;h_source;source;com_onerow;com_html",
                ", P1;;;;;;;;;;;;;633466.0;711659.0;;;;;;;;;;;",
                "], comments.csv",
                ", [obsid;date_time;comment;staff;type",
                ", P1;2015-01-01 00:00:00;comment1;s1;",
                "], w_levels.csv",
                ", [obsid;date_time;meas;h_toc;level_masl;comment",
                ", P1;2015-01-02 00:00:01;2.0;;;",
                "], w_flow.csv",
                ", [obsid;instrumentid;flowtype;date_time;reading;unit;comment",
                ", P1;inst1;Momflow;2015-04-13 00:00:00;;l/s;",
                "], w_qual_lab.csv",
                ", [obsid;depth;report;project;staff;date_time;anameth;parameter;reading_num;reading_txt;unit;comment",
                ", P1;;report1;;s1;;;labpar1;;;;",
                "], w_qual_field.csv",
                ", [obsid;staff;date_time;instrument;parameter;reading_num;reading_txt;unit;depth;comment",
                ", P1;s1;2015-01-01 01:00:00;;labpar1;;;unit1;;",
                "], screen.csv",
                ", [id;obsid;screenid;depthtop;depthbot;screenshort;screen;comment",
                ", 1;P1;1;5.0;8.0;;;",
                "], stratigraphy.csv",
                ", [obsid;stratid;depthtop;depthbot;geology;geoshort;capacity;development;comment",
                ", P1;1;0.0;10.0;;;;;",
                "], meteo.csv",
                ", [obsid;instrumentid;parameter;date_time;reading_num;reading_txt;unit;comment",
                ", P1;meteoinst;precip;2017-01-01 00:19:00;;;;",
                "], obs_lines.csv",
                ", [obsid;name;place;type;source;geometry",
                ", L1;;;;;",
                "], seismic_data.csv",
                ", [obsid;length;ground;bedrock;gw_table;comment",
                ", L1;5.0;;;;",
                "]]",
            ]
        )
        print(test_string)
        print(reference_string)
        assert test_string == reference_string

    @mock.patch(
        "midvatten.tools.utils.common_utils.get_selected_features_as_tuple",
        mock_no_selection.get_v,
    )
    @mock.patch("qgis.PyQt.QtWidgets.QFileDialog.getExistingDirectory")
    @mock.patch("qgis.utils.iface", autospec=True)
    def test_export_csv_no_selection(self, mock_iface, mock_savepath):
        mock_savepath.return_value = "/tmp/"
        db_utils.sql_alter_db(
            """INSERT INTO obs_points (obsid, geometry) VALUES ('P1', ST_GeomFromText('POINT(633466 711659)', 3006))"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO obs_points (obsid, geometry) VALUES ('P2', ST_GeomFromText('POINT(1 2)', 3006))"""
        )
        db_utils.sql_alter_db("""INSERT INTO zz_staff (staff) VALUES ('s1')""")
        db_utils.sql_alter_db(
            """INSERT INTO comments (obsid, date_time, staff, comment) VALUES ('P1', '2015-01-01 00:00:00', 's1', 'comment1')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_qual_lab (obsid, parameter, report, staff) VALUES ('P1', 'labpar1', 'report1', 's1')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_qual_field (obsid, parameter, staff, date_time, unit) VALUES ('P1', 'labpar1', 's1', '2015-01-01 01:00:00', 'unit1')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_flow (obsid, instrumentid, flowtype, date_time, unit) VALUES ('P1', 'inst1', 'Momflow', '2015-04-13 00:00:00', 'l/s')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels (obsid, date_time, meas) VALUES ('P1', '2015-01-02 00:00:01', '2')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO stratigraphy (obsid, stratid, depthtop, depthbot) VALUES ('P1', 1, 0, 10)"""
        )
        db_utils.sql_alter_db("""INSERT INTO obs_lines (obsid) VALUES ('L1')""")
        db_utils.sql_alter_db(
            """INSERT INTO seismic_data (obsid, length) VALUES ('L1', '5')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO meteo (obsid, instrumentid, parameter, date_time) VALUES ('P1', 'meteoinst', 'precip', '2017-01-01 00:19:00')"""
        )

        self.midvatten.export_csv()
        file_contents = []
        for filename in ExportMixin.exported_csv_files_no_zz:
            with open(filename, encoding="utf-8") as f:
                file_contents.append(os.path.basename(filename) + "\n")
                if os.path.basename(filename) == "obs_points.csv":
                    file_contents.append(
                        [
                            ";".join(line.replace("\r", "").split(";")[:-1]) + "\n"
                            for line in f
                        ]
                    )
                else:
                    file_contents.append([line.replace("\r", "") for line in f])
        test_string = utils_for_tests.create_test_string(file_contents)

        with open("/tmp/refstring.txt", "w", encoding="utf-8") as of:
            of.write(test_string)

        reference_string = "\n".join(
            [
                "[obs_points.csv",
                ", [obsid;name;place;type;length;drillstop;diam;material;screen;capacity;drilldate;wmeas_yn;wlogg_yn;east;north;ne_accur;ne_source;h_toc;h_tocags;h_gs;h_accur;h_syst;h_source;source;com_onerow;com_html",
                ", P1;;;;;;;;;;;;;633466.0;711659.0;;;;;;;;;;;",
                ", P2;;;;;;;;;;;;;1.0;2.0;;;;;;;;;;;",
                "], comments.csv",
                ", [obsid;date_time;comment;staff;type",
                ", P1;2015-01-01 00:00:00;comment1;s1;",
                "], w_levels.csv",
                ", [obsid;date_time;meas;h_toc;level_masl;comment",
                ", P1;2015-01-02 00:00:01;2.0;;;",
                "], w_flow.csv",
                ", [obsid;instrumentid;flowtype;date_time;reading;unit;comment",
                ", P1;inst1;Momflow;2015-04-13 00:00:00;;l/s;",
                "], w_qual_lab.csv",
                ", [obsid;depth;report;project;staff;date_time;anameth;parameter;reading_num;reading_txt;unit;comment",
                ", P1;;report1;;s1;;;labpar1;;;;",
                "], w_qual_field.csv",
                ", [obsid;staff;date_time;instrument;parameter;reading_num;reading_txt;unit;depth;comment",
                ", P1;s1;2015-01-01 01:00:00;;labpar1;;;unit1;;",
                "], screen.csv",
                ", [id;obsid;screenid;depthtop;depthbot;screenshort;screen;comment",
                "], stratigraphy.csv",
                ", [obsid;stratid;depthtop;depthbot;geology;geoshort;capacity;development;comment",
                ", P1;1;0.0;10.0;;;;;",
                "], meteo.csv",
                ", [obsid;instrumentid;parameter;date_time;reading_num;reading_txt;unit;comment",
                ", P1;meteoinst;precip;2017-01-01 00:19:00;;;;",
                "], obs_lines.csv",
                ", [obsid;name;place;type;source;geometry",
                ", L1;;;;;",
                "], seismic_data.csv",
                ", [obsid;length;ground;bedrock;gw_table;comment",
                ", L1;5.0;;;;",
                "]]",
            ]
        )
        print(test_string)
        print(reference_string)
        assert test_string == reference_string

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    @mock.patch("midvatten.tools.export_spatialite.NewSpatialiteDbDialog")
    @mock.patch(
        "midvatten.tools.utils.common_utils.get_selected_features_as_tuple",
        mock_selection.get_v,
    )
    @mock.patch(
        "midvatten.tools.utils.midvatten_utils.verify_msettings_loaded_and_layer_edit_mode",
        autospec=True,
    )
    @mock.patch("midvatten.tools.utils.midvatten_utils.find_layer", autospec=True)
    @mock.patch("qgis.utils.iface", autospec=True)
    @mock.patch("midvatten.tools.export_data.common_utils.pop_up_info", autospec=True)
    def test_export_spatialite(
        self,
        mock_skip_popup,
        mock_iface,
        mock_find_layer,
        mock_verify,
        mock_dialog_cls,
        mock_messagebar,
    ):
        mock_find_layer.return_value.crs.return_value.authid.return_value = "EPSG:3006"
        mock_verify.return_value = 0
        dbconnection = db_utils.DbConnectionManager()
        export_path = _unique_export_path(self)
        mock_dlg = mock.MagicMock()
        mock_dialog_cls.return_value = mock_dlg
        mock_dlg.exec.return_value = 1
        mock_dlg.locale = "sv_SE"
        mock_dlg.epsg_code = 3006
        mock_dlg.w_levels_logger_timezone = ""
        mock_dlg.w_levels_timezone = ""
        mock_dlg.dbpath = export_path

        db_utils.sql_alter_db(
            """INSERT INTO obs_points (obsid, geometry) VALUES ('P1', ST_GeomFromText('POINT(633466 711659)', 3006))""",
            dbconnection=dbconnection,
        )
        db_utils.sql_alter_db(
            """INSERT INTO zz_staff (staff) VALUES ('s1')""", dbconnection=dbconnection
        )
        db_utils.sql_alter_db(
            """INSERT INTO comments (obsid, date_time, staff, comment) VALUES ('P1', '2015-01-01 00:00:00', 's1', 'comment1')""",
            dbconnection=dbconnection,
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_qual_lab (obsid, parameter, report, staff) VALUES ('P1', 'labpar1', 'report1', 's1')""",
            dbconnection=dbconnection,
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_qual_field (obsid, parameter, staff, date_time, unit) VALUES ('P1', 'par1', 's1', '2015-01-01 01:00:00', 'unit1')""",
            dbconnection=dbconnection,
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_flow (obsid, instrumentid, flowtype, date_time, unit) VALUES ('P1', 'inst1', 'Momflow', '2015-04-13 00:00:00', 'l/s')""",
            dbconnection=dbconnection,
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels (obsid, date_time, meas) VALUES ('P1', '2015-01-02 00:00:01', '2')""",
            dbconnection=dbconnection,
        )
        db_utils.sql_alter_db(
            """INSERT INTO stratigraphy (obsid, stratid, depthtop, depthbot) VALUES ('P1', 1, 0, 10)""",
            dbconnection=dbconnection,
        )
        db_utils.sql_alter_db(
            """INSERT INTO screen (obsid, screenid, depthtop, depthbot) VALUES ('P1', 1, 5, 8)""",
            dbconnection=dbconnection,
        )
        db_utils.sql_alter_db(
            """INSERT INTO obs_lines (obsid) VALUES ('L1')""", dbconnection=dbconnection
        )
        db_utils.sql_alter_db(
            """INSERT INTO seismic_data (obsid, length) VALUES ('L1', '5')""",
            dbconnection=dbconnection,
        )
        db_utils.sql_alter_db(
            """INSERT INTO meteo (obsid, instrumentid, parameter, date_time) VALUES ('P1', 'meteoinst', 'precip', '2017-01-01 00:19:00')""",
            dbconnection=dbconnection,
        )

        dbconnection.commit_and_closedb()

        ExportSpatialite(self.iface, self.midvatten.ms).show()

        conn = db_utils.connect_with_spatialite_connect(export_path)
        sql_list = [
            """select obsid, ST_AsText(geometry) from obs_points""",
            """select staff from zz_staff""",
            """select obsid, date_time, staff, comment from comments""",
            """select obsid, parameter, report, staff from w_qual_lab""",
            """select obsid, parameter, staff, date_time, comment from w_qual_field""",
            """select obsid, instrumentid, flowtype, date_time, unit from w_flow""",
            """select obsid, date_time, meas from w_levels""",
            """select obsid, stratid, depthtop, depthbot from stratigraphy""",
            """select obsid, screenid, depthtop, depthbot from screen""",
            """select obsid from obs_lines""",
            """select obsid, length from seismic_data""",
            """select obsid, instrumentid, parameter, date_time from meteo""",
        ]

        curs = conn.cursor()
        test_list = []
        for sql in sql_list:
            test_list.append("\n" + sql + "\n")
            test_list.append(curs.execute(sql).fetchall())

        conn.commit()
        conn.close()

        test_string = utils_for_tests.create_test_string(test_list)
        reference_string = [
            """[""",
            """select obsid, ST_AsText(geometry) from obs_points""",
            """, [(P1, POINT(633466 711659))], """,
            """select staff from zz_staff""",
            """, [(s1)], """,
            """select obsid, date_time, staff, comment from comments""",
            """, [(P1, 2015-01-01 00:00:00, s1, comment1)], """,
            """select obsid, parameter, report, staff from w_qual_lab""",
            """, [(P1, labpar1, report1, s1)], """,
            """select obsid, parameter, staff, date_time, comment from w_qual_field""",
            """, [(P1, par1, s1, 2015-01-01 01:00:00, None)], """,
            """select obsid, instrumentid, flowtype, date_time, unit from w_flow""",
            """, [(P1, inst1, Momflow, 2015-04-13 00:00:00, l/s)], """,
            """select obsid, date_time, meas from w_levels""",
            """, [(P1, 2015-01-02 00:00:01, 2.0)], """,
            """select obsid, stratid, depthtop, depthbot from stratigraphy""",
            """, [(P1, 1, 0.0, 10.0)], """,
            """select obsid, screenid, depthtop, depthbot from screen""",
            """, [(P1, 1, 5.0, 8.0)], """,
            """select obsid from obs_lines""",
            """, [(L1)], """,
            """select obsid, length from seismic_data""",
            """, [(L1, 5.0)], """,
            """select obsid, instrumentid, parameter, date_time from meteo""",
            """, [(P1, meteoinst, precip, 2017-01-01 00:19:00)]]""",
        ]
        reference_string = "\n".join(reference_string)
        print("Ref:")
        print(str(reference_string))
        print("Test:")
        print(str(test_string))
        assert test_string == reference_string

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    @mock.patch("midvatten.tools.export_spatialite.NewSpatialiteDbDialog")
    @mock.patch(
        "midvatten.tools.utils.common_utils.get_selected_features_as_tuple",
        mock_no_selection.get_v,
    )
    @mock.patch(
        "midvatten.tools.utils.midvatten_utils.verify_msettings_loaded_and_layer_edit_mode",
        autospec=True,
    )
    @mock.patch("midvatten.tools.utils.midvatten_utils.find_layer", autospec=True)
    @mock.patch("qgis.utils.iface", autospec=True)
    @mock.patch("midvatten.tools.export_data.common_utils.pop_up_info", autospec=True)
    def test_export_spatialite_no_selected(
        self,
        mock_skip_popup,
        mock_iface,
        mock_find_layer,
        mock_verify,
        mock_dialog_cls,
        mock_messagebar,
    ):
        mock_find_layer.return_value.crs.return_value.authid.return_value = "EPSG:3006"
        mock_verify.return_value = 0
        dbconnection = db_utils.DbConnectionManager()
        export_path = _unique_export_path(self)
        mock_dlg = mock.MagicMock()
        mock_dialog_cls.return_value = mock_dlg
        mock_dlg.exec.return_value = 1
        mock_dlg.locale = "sv_SE"
        mock_dlg.epsg_code = 3006
        mock_dlg.w_levels_logger_timezone = ""
        mock_dlg.w_levels_timezone = ""
        mock_dlg.dbpath = export_path

        db_utils.sql_alter_db(
            """INSERT INTO obs_points (obsid, geometry) VALUES ('P1', ST_GeomFromText('POINT(633466 711659)', 3006))""",
            dbconnection=dbconnection,
        )
        db_utils.sql_alter_db(
            """INSERT INTO obs_points (obsid, geometry) VALUES ('P2', ST_GeomFromText('POINT(1 2)', 3006))"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO zz_staff (staff) VALUES ('s1')""", dbconnection=dbconnection
        )
        db_utils.sql_alter_db(
            """INSERT INTO comments (obsid, date_time, staff, comment) VALUES ('P1', '2015-01-01 00:00:00', 's1', 'comment1')""",
            dbconnection=dbconnection,
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_qual_lab (obsid, parameter, report, staff) VALUES ('P1', 'labpar1', 'report1', 's1')""",
            dbconnection=dbconnection,
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_qual_field (obsid, parameter, staff, date_time, unit) VALUES ('P1', 'par1', 's1', '2015-01-01 01:00:00', 'unit1')""",
            dbconnection=dbconnection,
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_flow (obsid, instrumentid, flowtype, date_time, unit) VALUES ('P1', 'inst1', 'Momflow', '2015-04-13 00:00:00', 'l/s')""",
            dbconnection=dbconnection,
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels (obsid, date_time, meas) VALUES ('P1', '2015-01-02 00:00:01', '2')""",
            dbconnection=dbconnection,
        )
        db_utils.sql_alter_db(
            """INSERT INTO stratigraphy (obsid, stratid, depthtop, depthbot) VALUES ('P1', 1, 0, 10)""",
            dbconnection=dbconnection,
        )
        db_utils.sql_alter_db(
            """INSERT INTO obs_lines (obsid) VALUES ('L1')""", dbconnection=dbconnection
        )
        db_utils.sql_alter_db(
            """INSERT INTO seismic_data (obsid, length) VALUES ('L1', '5')""",
            dbconnection=dbconnection,
        )
        db_utils.sql_alter_db(
            """INSERT INTO meteo (obsid, instrumentid, parameter, date_time) VALUES ('P1', 'meteoinst', 'precip', '2017-01-01 00:19:00')""",
            dbconnection=dbconnection,
        )

        dbconnection.commit_and_closedb()

        ExportSpatialite(self.iface, self.midvatten.ms).show()

        sql_list = [
            """select obsid, ST_AsText(geometry) from obs_points""",
            """select staff from zz_staff""",
            """select obsid, date_time, staff, comment from comments""",
            """select obsid, parameter, report, staff from w_qual_lab""",
            """select obsid, parameter, staff, date_time, comment from w_qual_field""",
            """select obsid, instrumentid, flowtype, date_time, unit from w_flow""",
            """select obsid, date_time, meas from w_levels""",
            """select obsid, stratid, depthtop, depthbot from stratigraphy""",
            """select obsid from obs_lines""",
            """select obsid, length from seismic_data""",
            """select obsid, instrumentid, parameter, date_time from meteo""",
        ]

        conn = db_utils.connect_with_spatialite_connect(export_path)
        curs = conn.cursor()

        test_list = []
        for sql in sql_list:
            test_list.append("\n" + sql + "\n")
            test_list.append(curs.execute(sql).fetchall())

        conn.commit()
        conn.close()

        test_string = utils_for_tests.create_test_string(test_list)
        reference_string = [
            """[""",
            """select obsid, ST_AsText(geometry) from obs_points""",
            """, [(P1, POINT(633466 711659)), (P2, POINT(1 2))], """,
            """select staff from zz_staff""",
            """, [(s1)], """,
            """select obsid, date_time, staff, comment from comments""",
            """, [(P1, 2015-01-01 00:00:00, s1, comment1)], """,
            """select obsid, parameter, report, staff from w_qual_lab""",
            """, [(P1, labpar1, report1, s1)], """,
            """select obsid, parameter, staff, date_time, comment from w_qual_field""",
            """, [(P1, par1, s1, 2015-01-01 01:00:00, None)], """,
            """select obsid, instrumentid, flowtype, date_time, unit from w_flow""",
            """, [(P1, inst1, Momflow, 2015-04-13 00:00:00, l/s)], """,
            """select obsid, date_time, meas from w_levels""",
            """, [(P1, 2015-01-02 00:00:01, 2.0)], """,
            """select obsid, stratid, depthtop, depthbot from stratigraphy""",
            """, [(P1, 1, 0.0, 10.0)], """,
            """select obsid from obs_lines""",
            """, [(L1)], """,
            """select obsid, length from seismic_data""",
            """, [(L1, 5.0)], """,
            """select obsid, instrumentid, parameter, date_time from meteo""",
            """, [(P1, meteoinst, precip, 2017-01-01 00:19:00)]]""",
        ]
        reference_string = "\n".join(reference_string)
        print(test_string)
        print(str(mock_messagebar.mock_calls))
        assert test_string == reference_string

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    @mock.patch("midvatten.tools.export_spatialite.NewSpatialiteDbDialog")
    @mock.patch("midvatten.tools.utils.common_utils.get_selected_features_as_tuple")
    @mock.patch(
        "midvatten.tools.utils.midvatten_utils.verify_msettings_loaded_and_layer_edit_mode",
        autospec=True,
    )
    @mock.patch("midvatten.tools.utils.midvatten_utils.find_layer", autospec=True)
    @mock.patch("qgis.utils.iface", autospec=True)
    @mock.patch("midvatten.tools.export_data.common_utils.pop_up_info", autospec=True)
    def test_export_spatialite_with_umlauts(
        self,
        mock_skip_popup,
        mock_iface,
        mock_find_layer,
        mock_verify,
        mock_selection,
        mock_dialog_cls,
        mock_messagebar,
    ):
        mock_selection.return_value = ("åäö",)
        mock_find_layer.return_value.crs.return_value.authid.return_value = "EPSG:3006"
        mock_verify.return_value = 0
        export_path = _unique_export_path(self)
        mock_dlg = mock.MagicMock()
        mock_dialog_cls.return_value = mock_dlg
        mock_dlg.exec.return_value = 1
        mock_dlg.locale = "sv_SE"
        mock_dlg.epsg_code = 3006
        mock_dlg.w_levels_logger_timezone = ""
        mock_dlg.w_levels_timezone = ""
        mock_dlg.dbpath = export_path

        db_utils.sql_alter_db(
            """INSERT INTO obs_points (obsid, geometry) VALUES ('åäö', ST_GeomFromText('POINT(633466 711659)', 3006))"""
        )
        db_utils.sql_alter_db("""INSERT INTO zz_staff (staff) VALUES ('s1')""")
        db_utils.sql_alter_db(
            """INSERT INTO comments (obsid, date_time, staff, comment) VALUES ('åäö', '2015-01-01 00:00:00', 's1', 'comment1')"""
        )

        ExportSpatialite(self.iface, self.midvatten.ms).show()

        sql_list = [
            """select obsid, ST_AsText(geometry) from obs_points""",
            """select staff from zz_staff""",
            """select obsid, date_time, staff, comment from comments""",
        ]

        conn = db_utils.connect_with_spatialite_connect(export_path)
        curs = conn.cursor()

        test_list = []
        for sql in sql_list:
            test_list.append("\n" + sql + "\n")
            test_list.append(curs.execute(sql).fetchall())

        conn.commit()
        conn.close()

        test_string = utils_for_tests.create_test_string(test_list)
        reference_string = [
            """[""",
            """select obsid, ST_AsText(geometry) from obs_points""",
            """, [(åäö, POINT(633466 711659))], """,
            """select staff from zz_staff""",
            """, [(s1)], """,
            """select obsid, date_time, staff, comment from comments""",
            """, [(åäö, 2015-01-01 00:00:00, s1, comment1)]]""",
        ]
        reference_string = "\n".join(reference_string)

        print("Ref")
        print(reference_string)
        print("Test")
        print(test_string)
        print(str(mock_messagebar.mock_calls))
        assert test_string == reference_string

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    @mock.patch("midvatten.tools.export_spatialite.NewSpatialiteDbDialog")
    @mock.patch(
        "midvatten.tools.utils.common_utils.get_selected_features_as_tuple",
        mock_selection.get_v,
    )
    @mock.patch(
        "midvatten.tools.utils.midvatten_utils.verify_msettings_loaded_and_layer_edit_mode",
        autospec=True,
    )
    @mock.patch("midvatten.tools.utils.midvatten_utils.find_layer", autospec=True)
    @mock.patch("qgis.utils.iface", autospec=True)
    @mock.patch("midvatten.tools.export_data.common_utils.pop_up_info", autospec=True)
    def test_export_spatialite_transform_coordinates(
        self,
        mock_skip_popup,
        mock_iface,
        mock_find_layer,
        mock_verify,
        mock_dialog_cls,
        mock_messagebar,
    ):
        mock_find_layer.return_value.crs.return_value.authid.return_value = "EPSG:3006"
        mock_verify.return_value = 0
        mock_dlg = mock.MagicMock()
        mock_dialog_cls.return_value = mock_dlg
        mock_dlg.exec.return_value = 1
        mock_dlg.locale = "sv_SE"
        mock_dlg.epsg_code = 3010
        mock_dlg.w_levels_logger_timezone = ""
        mock_dlg.w_levels_timezone = ""
        mock_dlg.dbpath = EXPORT_DB_PATH

        db_utils.sql_alter_db(
            """INSERT INTO obs_points (obsid, geometry) VALUES ('P1', ST_GeomFromText('POINT(1 1)', 3006))"""
        )
        db_utils.sql_alter_db("""INSERT INTO zz_staff (staff) VALUES ('s1')""")
        db_utils.sql_alter_db(
            """INSERT INTO comments (obsid, date_time, staff, comment) VALUES ('P1', '2015-01-01 00:00:00', 's1', 'comment1')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_qual_lab (obsid, parameter, report, staff) VALUES ('P1', 'labpar1', 'report1', 's1')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_qual_field (obsid, parameter, staff, date_time, unit) VALUES ('P1', 'par1', 's1', '2015-01-01 01:00:00', 'unit1')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_flow (obsid, instrumentid, flowtype, date_time, unit) VALUES ('P1', 'inst1', 'Momflow', '2015-04-13 00:00:00', 'l/s')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels (obsid, date_time, meas) VALUES ('P1', '2015-01-02 00:00:01', '2')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO stratigraphy (obsid, stratid, depthtop, depthbot) VALUES ('P1', 1, 0, 10)"""
        )
        db_utils.sql_alter_db("""INSERT INTO obs_lines (obsid) VALUES ('L1')""")
        db_utils.sql_alter_db(
            """INSERT INTO seismic_data (obsid, length) VALUES ('L1', '5')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO meteo (obsid, instrumentid, parameter, date_time) VALUES ('P1', 'meteoinst', 'precip', '2017-01-01 00:19:00')"""
        )

        ExportSpatialite(self.iface, self.midvatten.ms).show()

        sql_list = [
            """select obsid, ST_AsText(geometry) from obs_points""",
            """select staff from zz_staff""",
            """select obsid, date_time, staff, comment from comments""",
            """select obsid, parameter, report, staff from w_qual_lab""",
            """select obsid, parameter, staff, date_time, comment from w_qual_field""",
            """select obsid, instrumentid, flowtype, date_time, unit from w_flow""",
            """select obsid, date_time, meas from w_levels""",
            """select obsid, stratid, depthtop, depthbot from stratigraphy""",
            """select obsid from obs_lines""",
            """select obsid, length from seismic_data""",
            """select obsid, instrumentid, parameter, date_time from meteo""",
        ]

        conn = db_utils.connect_with_spatialite_connect(EXPORT_DB_PATH)
        curs = conn.cursor()

        test_list = []
        for sql in sql_list:
            test_list.append("\n" + sql + "\n")
            test_list.append(curs.execute(sql).fetchall())

        conn.commit()
        conn.close()

        test_string = utils_for_tests.create_test_string(test_list)
        """
        # The coordinates aquired from st_transform differs from Linux Mint 18.2 to Linux Mint 19
        # In Mint 18, it's -517888.383773 for both postgis and spatialite
        # In Mint 19, it's -517888.383737 for both postgis and spatialite
        # In Ubuntu 20.04 it's -517888.384559 for both postgis and spatialite
        #// I've made changes to the transformation so the above values no longer exists, but the previous issue probably does.
        # !!! No idea why
        # In Ubuntu 22.10, (1, 1) in 3006 turns into 'POINT(10.511265 0.000009)' in WGS84 and into POINT(-517888.39291 1.000667) in 3010!
        # The problem must be rounding related. 
        
        reference_string = ['''[''',
                            '''select obsid, ST_AsText(geometry) from obs_points''',
                            ''', [(P1, POINT(-517888.392089 1.000667))], ''',
                            '''select staff from zz_staff''',
                            ''', [(s1)], ''',
                            '''select obsid, date_time, staff, comment from comments''',
                            ''', [(P1, 2015-01-01 00:00:00, s1, comment1)], ''',
                            '''select obsid, parameter, report, staff from w_qual_lab''',
                            ''', [(P1, labpar1, report1, s1)], ''',
                            '''select obsid, parameter, staff, date_time, comment from w_qual_field''',
                            ''', [(P1, par1, s1, 2015-01-01 01:00:00, None)], ''',
                            '''select obsid, instrumentid, flowtype, date_time, unit from w_flow''',
                            ''', [(P1, inst1, Momflow, 2015-04-13 00:00:00, l/s)], ''',
                            '''select obsid, date_time, meas from w_levels''',
                            ''', [(P1, 2015-01-02 00:00:01, 2.0)], ''',
                            '''select obsid, stratid, depthtop, depthbot from stratigraphy''',
                            ''', [(P1, 1, 0.0, 10.0)], ''',
                            '''select obsid from obs_lines''',
                            ''', [(L1)], ''',
                            '''select obsid, length from seismic_data''',
                            ''', [(L1, 5.0)], ''',
                            '''select obsid, instrumentid, parameter, date_time from meteo''',
                            ''', [(P1, meteoinst, precip, 2017-01-01 00:19:00)]]''']
        """
        reference_string = [
            """[""",
            """select obsid, ST_AsText(geometry) from obs_points""",
            """, [(P1, POINT(-517888.384559 1.002821))], """,
            """select staff from zz_staff""",
            """, [(s1)], """,
            """select obsid, date_time, staff, comment from comments""",
            """, [(P1, 2015-01-01 00:00:00, s1, comment1)], """,
            """select obsid, parameter, report, staff from w_qual_lab""",
            """, [(P1, labpar1, report1, s1)], """,
            """select obsid, parameter, staff, date_time, comment from w_qual_field""",
            """, [(P1, par1, s1, 2015-01-01 01:00:00, None)], """,
            """select obsid, instrumentid, flowtype, date_time, unit from w_flow""",
            """, [(P1, inst1, Momflow, 2015-04-13 00:00:00, l/s)], """,
            """select obsid, date_time, meas from w_levels""",
            """, [(P1, 2015-01-02 00:00:01, 2.0)], """,
            """select obsid, stratid, depthtop, depthbot from stratigraphy""",
            """, [(P1, 1, 0.0, 10.0)], """,
            """select obsid from obs_lines""",
            """, [(L1)], """,
            """select obsid, length from seismic_data""",
            """, [(L1, 5.0)], """,
            """select obsid, instrumentid, parameter, date_time from meteo""",
            """, [(P1, meteoinst, precip, 2017-01-01 00:19:00)]]""",
        ]

        reference_string = "\n".join(reference_string)
        print("Test\n" + test_string)
        print("Ref\n" + reference_string)
        assert test_string == reference_string

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    @mock.patch("midvatten.tools.export_spatialite.NewSpatialiteDbDialog")
    @mock.patch(
        "midvatten.tools.utils.common_utils.get_selected_features_as_tuple",
        mock_selection.get_v,
    )
    @mock.patch(
        "midvatten.tools.utils.midvatten_utils.verify_msettings_loaded_and_layer_edit_mode",
        autospec=True,
    )
    @mock.patch("midvatten.tools.utils.midvatten_utils.find_layer", autospec=True)
    @mock.patch("qgis.utils.iface", autospec=True)
    @mock.patch("midvatten.tools.export_data.common_utils.pop_up_info", autospec=True)
    def test_export_spatialite_zz_tables(
        self,
        mock_skip_popup,
        mock_iface,
        mock_find_layer,
        mock_verify,
        mock_dialog_cls,
        mock_messagebar,
    ):
        mock_find_layer.return_value.crs.return_value.authid.return_value = "EPSG:3006"
        mock_verify.return_value = 0
        dbconnection = db_utils.DbConnectionManager()
        export_path = _unique_export_path(self)
        for suffix in ["", "-journal", "-wal", "-shm"]:
            try:
                os.remove(export_path + suffix)
            except OSError:
                pass
        mock_dlg = mock.MagicMock()
        mock_dialog_cls.return_value = mock_dlg
        mock_dlg.exec.return_value = 1
        mock_dlg.locale = "en_US"
        mock_dlg.epsg_code = 3006
        mock_dlg.w_levels_logger_timezone = ""
        mock_dlg.w_levels_timezone = ""
        mock_dlg.dbpath = export_path

        """
        insert into zz_strat(geoshort,strata) values('land fill','fyll');
        insert into zz_stratigraphy_plots (strata,color_mplot,hatch_mplot,color_qt,brush_qt) values('torv','DarkGray','+','darkGray','NoBrush');
        insert into zz_capacity (capacity,explanation) values('6 ','mycket god');
        insert into zz_capacity (capacity,explanation) values('6+','mycket god');
        insert into zz_capacity_plots (capacity,color_qt) values('', 'gray');
        """

        db_utils.sql_alter_db(
            """INSERT INTO obs_points (obsid, geometry) VALUES ('P1', ST_GeomFromText('POINT(633466 711659)', 3006))""",
            dbconnection=dbconnection,
        )
        if dbconnection.dbtype == "spatialite":
            dbconnection.execute("""PRAGMA foreign_keys='off'  """)
        dbconnection.execute(
            """UPDATE zz_strat SET strata = 'filling' WHERE geoshort = 'land fill' """
        )
        dbconnection.execute(
            """INSERT INTO zz_stratigraphy_plots (strata,color_mplot,hatch_mplot,color_qt,brush_qt) values ('filling','Yellow','+','darkGray','NoBrush') """
        )
        dbconnection.execute(
            """UPDATE zz_stratigraphy_plots SET color_mplot = 'OrangeFIX' WHERE strata = 'made ground' """
        )
        dbconnection.execute(
            """UPDATE zz_capacity SET explanation = 'anexpl' WHERE capacity = '0' """
        )
        dbconnection.execute(
            """UPDATE zz_capacity_plots SET color_qt = 'whiteFIX' WHERE capacity = '0' """
        )

        # print(str(dbconnection.execute_and_fetchall('select * from zz_strat')))
        sql_list = [
            """SELECT geoshort, strata FROM zz_strat WHERE geoshort IN ('land fill', 'rock') """,
            """SELECT strata, color_mplot FROM zz_stratigraphy_plots WHERE strata IN ('made ground', 'rock', 'filling') """,
            """SELECT capacity, explanation FROM zz_capacity WHERE capacity IN ('0', '1')""",
            """SELECT capacity, color_qt FROM zz_capacity_plots WHERE capacity IN ('0', '1') """,
        ]
        test_list = []
        curs = dbconnection.cursor
        for sql in sql_list:
            test_list.append("\n" + sql + "\n")
            curs.execute(sql)
            test_list.append(curs.fetchall())

        dbconnection.commit_and_closedb()

        ExportSpatialite(self.iface, self.midvatten.ms).show()

        conn = db_utils.connect_with_spatialite_connect(export_path)
        curs = conn.cursor()

        test_list = []
        for sql in sql_list:
            test_list.append("\n" + sql + "\n")
            test_list.append(curs.execute(sql).fetchall())

        conn.commit()
        conn.close()

        test_string = utils_for_tests.create_test_string(test_list)

        reference_string = [
            """[""",
            """SELECT geoshort, strata FROM zz_strat WHERE geoshort IN ('land fill', 'rock') """,
            """, [(land fill, filling), (rock, rock)], """,
            """SELECT strata, color_mplot FROM zz_stratigraphy_plots WHERE strata IN ('made ground', 'rock', 'filling') """,
            """, [(filling, Yellow), (made ground, OrangeFIX), (rock, red)], """,
            """SELECT capacity, explanation FROM zz_capacity WHERE capacity IN ('0', '1')""",
            """, [(0, anexpl), (1, above gwl)], """,
            """SELECT capacity, color_qt FROM zz_capacity_plots WHERE capacity IN ('0', '1') """,
            """, [(0, whiteFIX), (1, red)]]""",
        ]

        reference_string = "\n".join(reference_string)
        print("Test")
        print(str(test_string))
        print("Ref")
        print(str(reference_string))
        assert test_string == reference_string

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    @mock.patch("midvatten.tools.export_spatialite.NewSpatialiteDbDialog")
    @mock.patch(
        "midvatten.tools.utils.common_utils.get_selected_features_as_tuple",
        mock_selection.get_v,
    )
    @mock.patch(
        "midvatten.tools.utils.midvatten_utils.verify_msettings_loaded_and_layer_edit_mode",
        autospec=True,
    )
    @mock.patch("midvatten.tools.utils.midvatten_utils.find_layer", autospec=True)
    @mock.patch("qgis.utils.iface", autospec=True)
    @mock.patch("midvatten.tools.export_data.common_utils.pop_up_info", autospec=True)
    def test_export_spatialite_extra_tables(
        self,
        mock_skip_popup,
        mock_iface,
        mock_find_layer,
        mock_verify,
        mock_dialog_cls,
        mock_messagebar,
    ):
        mock_find_layer.return_value.crs.return_value.authid.return_value = "EPSG:3006"
        dbconnection = db_utils.DbConnectionManager()
        mock_verify.return_value = 0
        mock_dlg = mock.MagicMock()
        mock_dialog_cls.return_value = mock_dlg
        mock_dlg.exec.return_value = 1
        mock_dlg.locale = "sv_SE"
        mock_dlg.epsg_code = 3006
        mock_dlg.w_levels_logger_timezone = ""
        mock_dlg.w_levels_timezone = ""
        mock_dlg.dbpath = EXPORT_DB_PATH

        db_utils.execute_sqlfile(
            db_defs.extra_datatables_sqlfile(), dbconnection, merge_newlines=True
        )
        db_utils.sql_alter_db(
            """INSERT INTO obs_points (obsid, geometry) VALUES ('P1', ST_GeomFromText('POINT(633466 711659)', 3006))""",
            dbconnection=dbconnection,
        )
        db_utils.sql_alter_db(
            """INSERT INTO zz_staff (staff) VALUES ('s1')""", dbconnection=dbconnection
        )
        db_utils.sql_alter_db(
            """INSERT INTO comments (obsid, date_time, staff, comment) VALUES ('P1', '2015-01-01 00:00:00', 's1', 'comment1')""",
            dbconnection=dbconnection,
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_qual_lab (obsid, parameter, report, staff) VALUES ('P1', 'labpar1', 'report1', 's1')""",
            dbconnection=dbconnection,
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_qual_field (obsid, parameter, staff, date_time, unit) VALUES ('P1', 'par1', 's1', '2015-01-01 01:00:00', 'unit1')""",
            dbconnection=dbconnection,
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_flow (obsid, instrumentid, flowtype, date_time, unit) VALUES ('P1', 'inst1', 'Momflow', '2015-04-13 00:00:00', 'l/s')""",
            dbconnection=dbconnection,
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels (obsid, date_time, meas) VALUES ('P1', '2015-01-02 00:00:01', '2')""",
            dbconnection=dbconnection,
        )
        db_utils.sql_alter_db(
            """INSERT INTO stratigraphy (obsid, stratid, depthtop, depthbot) VALUES ('P1', 1, 0, 10)""",
            dbconnection=dbconnection,
        )
        db_utils.sql_alter_db(
            """INSERT INTO obs_lines (obsid) VALUES ('L1')""", dbconnection=dbconnection
        )
        db_utils.sql_alter_db(
            """INSERT INTO seismic_data (obsid, length) VALUES ('L1', '5')""",
            dbconnection=dbconnection,
        )
        db_utils.sql_alter_db(
            """INSERT INTO meteo (obsid, instrumentid, parameter, date_time) VALUES ('P1', 'meteoinst', 'precip', '2017-01-01 00:19:00')""",
            dbconnection=dbconnection,
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_qual_logger (obsid, date_time, instrument, parameter, unit) VALUES ('P1', '2021-08-11 11:14', 'testinst', 'testpar', 'm')""",
            dbconnection=dbconnection,
        )

        dbconnection.commit_and_closedb()

        print(str(db_utils.sql_load_fr_db("""select * From s_qual_lab""")))

        ExportSpatialite(self.iface, self.midvatten.ms).show()

        sql_list = [
            """select obsid, ST_AsText(geometry) from obs_points""",
            """select staff from zz_staff""",
            """select obsid, date_time, staff, comment from comments""",
            """select obsid, parameter, report, staff from w_qual_lab""",
            """select obsid, parameter, staff, date_time, comment from w_qual_field""",
            """select obsid, instrumentid, flowtype, date_time, unit from w_flow""",
            """select obsid, date_time, meas from w_levels""",
            """select obsid, stratid, depthtop, depthbot from stratigraphy""",
            """select obsid from obs_lines""",
            """select obsid, length from seismic_data""",
            """select obsid, instrumentid, parameter, date_time from meteo""",
            """select obsid, parameter, report, staff from s_qual_lab""",
            """select obsid, date_time, instrument, parameter, unit from w_qual_logger""",
        ]

        conn = db_utils.connect_with_spatialite_connect(EXPORT_DB_PATH)
        curs = conn.cursor()

        test_list = []
        for sql in sql_list:
            test_list.append("\n" + sql + "\n")
            test_list.append(curs.execute(sql).fetchall())

        conn.commit()
        conn.close()

        test_string = utils_for_tests.create_test_string(test_list)
        reference_string = [
            """[""",
            """select obsid, ST_AsText(geometry) from obs_points""",
            """, [(P1, POINT(633466 711659))], """,
            """select staff from zz_staff""",
            """, [(s1)], """,
            """select obsid, date_time, staff, comment from comments""",
            """, [(P1, 2015-01-01 00:00:00, s1, comment1)], """,
            """select obsid, parameter, report, staff from w_qual_lab""",
            """, [(P1, labpar1, report1, s1)], """,
            """select obsid, parameter, staff, date_time, comment from w_qual_field""",
            """, [(P1, par1, s1, 2015-01-01 01:00:00, None)], """,
            """select obsid, instrumentid, flowtype, date_time, unit from w_flow""",
            """, [(P1, inst1, Momflow, 2015-04-13 00:00:00, l/s)], """,
            """select obsid, date_time, meas from w_levels""",
            """, [(P1, 2015-01-02 00:00:01, 2.0)], """,
            """select obsid, stratid, depthtop, depthbot from stratigraphy""",
            """, [(P1, 1, 0.0, 10.0)], """,
            """select obsid from obs_lines""",
            """, [(L1)], """,
            """select obsid, length from seismic_data""",
            """, [(L1, 5.0)], """,
            """select obsid, instrumentid, parameter, date_time from meteo""",
            """, [(P1, meteoinst, precip, 2017-01-01 00:19:00)], """,
            """select obsid, parameter, report, staff from s_qual_lab""",
            """, [], """,
            """select obsid, date_time, instrument, parameter, unit from w_qual_logger""",
            """, [(P1, 2021-08-11 11:14, testinst, testpar, m)]]""",
        ]
        reference_string = "\n".join(reference_string)
        print("Ref:")
        print(str(reference_string))
        print("Test:")
        print(str(test_string))
        assert test_string == reference_string

    def teardown_method(self):
        # Delete database
        try:
            os.remove(EXPORT_DB_PATH)
        except OSError:
            pass

        for filename in ExportMixin.exported_csv_files:
            try:
                os.remove(filename)
            except OSError:
                pass

        super().teardown_method()


@pytest.mark.postgis
class TestExportPostgis(ExportMixin, utils_for_tests.MidvattenTestPostgisDbEn):
    pass


@pytest.mark.spatialite
class TestExportSpatialite(ExportMixin, utils_for_tests.MidvattenTestSpatialiteDbEn):
    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    @mock.patch("midvatten.tools.export_spatialite.NewSpatialiteDbDialog")
    @mock.patch(
        "midvatten.tools.utils.midvatten_utils.verify_msettings_loaded_and_layer_edit_mode",
        autospec=True,
    )
    @mock.patch("midvatten.tools.utils.midvatten_utils.find_layer", autospec=True)
    @mock.patch("qgis.utils.iface", autospec=True)
    @mock.patch("midvatten.tools.export_data.common_utils.pop_up_info", autospec=True)
    @mock.patch(
        "midvatten.tools.utils.common_utils.get_selected_features_as_tuple",
        ExportMixin.mock_no_selection.get_v,
    )
    @mock.patch(
        "midvatten.tools.utils.common_utils.Askuser", ExportMixin.mock_askuser.get_v
    )
    def test_export_spatialite_migrates_old_logger_source_to_series(
        self,
        mock_skip_popup,
        mock_iface,
        mock_find_layer,
        mock_verify,
        mock_dialog_cls,
        mock_messagebar,
    ):
        """Old-schema source DB (w_levels_logger.source column, no
        w_logger_series) exports cleanly into the new schema: one
        w_logger_series row per distinct (obsid, source) pair, and every
        w_levels_logger row on the target linked to the right series.
        """
        mock_find_layer.return_value.crs.return_value.authid.return_value = (
            "EPSG:3006"
        )
        mock_verify.return_value = 0
        export_path = _unique_export_path(self)
        mock_dlg = mock.MagicMock()
        mock_dialog_cls.return_value = mock_dlg
        mock_dlg.exec.return_value = 1
        mock_dlg.locale = "en_US"
        mock_dlg.epsg_code = 3006
        mock_dlg.w_levels_logger_timezone = ""
        mock_dlg.w_levels_timezone = ""
        mock_dlg.dbpath = export_path

        dbconn = db_utils.DbConnectionManager()
        try:
            # Mutate the source DB to look like Midv 1.x:
            #   drop w_logger_series, drop w_levels_logger.series_id and
            #   created_at, add back w_levels_logger.source.
            dbconn.execute("PRAGMA foreign_keys = OFF")
            dbconn.execute("DROP INDEX IF EXISTS idx_wlvllogger_series")
            dbconn.execute("DROP INDEX IF EXISTS idx_wlogger_series_obsid")
            dbconn.execute("DROP VIEW IF EXISTS obs_p_w_lvl_logger")
            dbconn.execute(
                "DELETE FROM views_geometry_columns"
                " WHERE view_name = 'obs_p_w_lvl_logger'"
            )
            dbconn.execute("DROP TABLE IF EXISTS w_logger_series")
            # SQLite versions that ship with QGIS can be older; rebuild the
            # table with a CREATE/INSERT/DROP/RENAME pattern so we do not
            # rely on ALTER TABLE ... DROP COLUMN.
            dbconn.execute(
                "CREATE TABLE w_levels_logger_old ("
                "obsid text NOT NULL,"
                " date_time text NOT NULL,"
                " head_cm double,"
                " temp_degc double,"
                " cond_mscm double,"
                " level_masl double,"
                " comment text,"
                " source text,"
                " PRIMARY KEY (obsid, date_time),"
                " FOREIGN KEY(obsid) REFERENCES obs_points(obsid)"
                ")"
            )
            dbconn.execute(
                "INSERT INTO w_levels_logger_old"
                " (obsid, date_time, head_cm, temp_degc, cond_mscm,"
                "  level_masl, comment)"
                " SELECT obsid, date_time, head_cm, temp_degc, cond_mscm,"
                "  level_masl, comment FROM w_levels_logger"
            )
            dbconn.execute("DROP TABLE w_levels_logger")
            dbconn.execute(
                "ALTER TABLE w_levels_logger_old RENAME TO w_levels_logger"
            )
            # Recreate the obs_p_w_lvl_logger view that was dropped above.
            dbconn.execute(
                "CREATE VIEW obs_p_w_lvl_logger AS"
                " SELECT a.rowid, a.obsid, a.geometry FROM obs_points a"
                " WHERE EXISTS ("
                "SELECT obsid FROM w_levels_logger b"
                " WHERE b.obsid = a.obsid LIMIT 1)"
            )
            dbconn.execute(
                "INSERT INTO views_geometry_columns"
                " (view_name, view_geometry, view_rowid,"
                "  f_table_name, f_geometry_column, read_only)"
                " VALUES ('obs_p_w_lvl_logger', 'geometry', 'rowid',"
                "  'obs_points', 'geometry', 1)"
            )
            dbconn.execute("PRAGMA foreign_keys = ON")
            dbconn.commit()

            # Populate with two wells, three distinct (obsid, source) groups.
            dbconn.execute(
                "INSERT INTO obs_points (obsid, geometry) VALUES"
                " ('P1', ST_GeomFromText('POINT(633466 711659)', 3006))"
            )
            dbconn.execute(
                "INSERT INTO obs_points (obsid, geometry) VALUES"
                " ('P2', ST_GeomFromText('POINT(633500 711700)', 3006))"
            )
            dbconn.execute(
                "INSERT INTO w_levels_logger"
                " (obsid, date_time, head_cm, source) VALUES"
                " ('P1', '2015-01-01 00:00:00', 100.0, 'fileA'),"
                " ('P1', '2015-01-01 01:00:00', 101.0, 'fileA'),"
                " ('P1', '2015-01-02 00:00:00', 102.0, 'fileB'),"
                " ('P2', '2015-01-01 00:00:00', 200.0, 'fileA')"
            )
            dbconn.commit()
        finally:
            dbconn.closedb()

        ExportSpatialite(self.iface, self.midvatten.ms).show()

        # Inspect the exported DB.
        conn = db_utils.connect_with_spatialite_connect(export_path)
        curs = conn.cursor()
        series_rows = curs.execute(
            "SELECT obsid, source, description FROM w_logger_series"
            " ORDER BY obsid, source"
        ).fetchall()
        levels_rows = curs.execute(
            "SELECT l.obsid, l.date_time, l.head_cm, s.source"
            " FROM w_levels_logger l"
            " LEFT JOIN w_logger_series s ON s.id = l.series_id"
            " ORDER BY l.obsid, l.date_time"
        ).fetchall()
        # Confirm the two (P1, fileA) rows share a series_id, distinct
        # from (P1, fileB) and (P2, fileA).
        p1a_sids = [
            r[0]
            for r in curs.execute(
                "SELECT series_id FROM w_levels_logger l"
                " WHERE obsid='P1' AND date_time IN"
                " ('2015-01-01 00:00:00', '2015-01-01 01:00:00')"
                " ORDER BY date_time"
            ).fetchall()
        ]
        p1b_sid = curs.execute(
            "SELECT series_id FROM w_levels_logger"
            " WHERE obsid='P1' AND date_time = '2015-01-02 00:00:00'"
        ).fetchone()[0]
        p2_sid = curs.execute(
            "SELECT series_id FROM w_levels_logger"
            " WHERE obsid='P2'"
        ).fetchone()[0]
        conn.close()

        assert series_rows == [
            ("P1", "fileA", "Upgraded from Midv 1.x"),
            ("P1", "fileB", "Upgraded from Midv 1.x"),
            ("P2", "fileA", "Upgraded from Midv 1.x"),
        ]
        assert levels_rows == [
            ("P1", "2015-01-01 00:00:00", 100.0, "fileA"),
            ("P1", "2015-01-01 01:00:00", 101.0, "fileA"),
            ("P1", "2015-01-02 00:00:00", 102.0, "fileB"),
            ("P2", "2015-01-01 00:00:00", 200.0, "fileA"),
        ]
        assert p1a_sids[0] == p1a_sids[1]
        assert p1a_sids[0] != p1b_sid
        assert p1a_sids[0] != p2_sid
        assert p1b_sid != p2_sid
