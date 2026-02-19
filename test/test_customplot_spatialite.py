# -*- coding: utf-8 -*-
"""
/***************************************************************************
 This part of the Midvatten plugin tests the sectionplot.

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

import tempfile

import mock
from nose.plugins.attrib import attr

from midvatten.test import utils_for_tests
from midvatten.tools.utils import db_utils, gui_utils


@attr(status="on")
class TestCustomPlot(utils_for_tests.MidvattenTestSpatialiteDbSv):
    """ """

    @mock.patch("midvatten.tools.sectionplot.common_utils.MessagebarAndLog")
    def test_save_to_csv_columns(self, mock_messagebar):
        db_utils.sql_alter_db("""INSERT INTO obs_points (obsid) VALUES ('o1')""")
        db_utils.sql_alter_db("""INSERT INTO obs_points (obsid) VALUES ('o2')""")
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o1', '2026-01-01 00:30', 5.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o1', '2026-01-01 10:31', 10.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o1', '2026-01-01 23:50', 17.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o2', '2026-01-01 00:30', 5.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o2', '2026-01-01 01:30', 5.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o2', '2026-01-01 02:30', 6.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o2', '2026-01-01 03:30', 7.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o2', '2026-01-02 09:00', 4.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o2', '2026-01-02 14:00', 10.0)"""
        )

        self.midvatten.plot_sqlite()
        customplot = self.midvatten.customplot
        gui_utils.set_combobox(customplot.table_ComboBox_1, "w_levels_logger")
        gui_utils.set_combobox(customplot.xcol_ComboBox_1, "date_time")
        gui_utils.set_combobox(customplot.ycol_ComboBox_1, "level_masl")
        gui_utils.set_combobox(customplot.Filter1_ComboBox_1, "obsid")
        customplot.Filter1_QListWidget_1.item(0).setSelected(True)

        gui_utils.set_combobox(customplot.table_ComboBox_2, "w_levels_logger")
        gui_utils.set_combobox(customplot.xcol_ComboBox_2, "date_time")
        gui_utils.set_combobox(customplot.ycol_ComboBox_2, "level_masl")
        gui_utils.set_combobox(customplot.Filter1_ComboBox_2, "obsid")
        customplot.Filter1_QListWidget_2.item(1).setSelected(True)

        customplot.start_csv_dialog()
        # tempinput(data, charset='UTF-8', suffix='.csv')
        temp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
        temp.close()
        customplot.save_file_dialog.filename.setFilePath(temp.name)

        customplot.save_file_dialog.as_columns.setChecked(True)
        customplot.save_file_dialog.save_data()

        with open(temp.name) as f:
            rows = tuple([tuple(x.rstrip().split(";")) for x in f.readlines()])
        print(f"{rows=}")
        assert rows == (
            ("rowid", "index", "o1", "o2"),
            ("0", "2026-01-01 00:30:00", "5.0", "5.0"),
            ("1", "2026-01-01 01:30:00", "", "5.0"),
            ("2", "2026-01-01 02:30:00", "", "6.0"),
            ("3", "2026-01-01 03:30:00", "", "7.0"),
            ("4", "2026-01-01 10:31:00", "10.0", ""),
            ("5", "2026-01-01 23:50:00", "17.0", ""),
            ("6", "2026-01-02 09:00:00", "", "4.0"),
            ("7", "2026-01-02 14:00:00", "", "10.0"),
        )

    @mock.patch("midvatten.tools.sectionplot.common_utils.MessagebarAndLog")
    def test_save_to_csv_rows(self, mock_messagebar):
        db_utils.sql_alter_db("""INSERT INTO obs_points (obsid) VALUES ('o1')""")
        db_utils.sql_alter_db("""INSERT INTO obs_points (obsid) VALUES ('o2')""")
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o1', '2026-01-01 00:30', 5.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o1', '2026-01-01 10:31', 10.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o1', '2026-01-01 23:50', 17.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o2', '2026-01-01 00:30', 5.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o2', '2026-01-01 01:30', 5.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o2', '2026-01-01 02:30', 6.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o2', '2026-01-01 03:30', 7.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o2', '2026-01-02 09:00', 4.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o2', '2026-01-02 14:00', 10.0)"""
        )

        self.midvatten.plot_sqlite()
        customplot = self.midvatten.customplot
        gui_utils.set_combobox(customplot.table_ComboBox_1, "w_levels_logger")
        gui_utils.set_combobox(customplot.xcol_ComboBox_1, "date_time")
        gui_utils.set_combobox(customplot.ycol_ComboBox_1, "level_masl")
        gui_utils.set_combobox(customplot.Filter1_ComboBox_1, "obsid")
        customplot.Filter1_QListWidget_1.item(0).setSelected(True)

        gui_utils.set_combobox(customplot.table_ComboBox_2, "w_levels_logger")
        gui_utils.set_combobox(customplot.xcol_ComboBox_2, "date_time")
        gui_utils.set_combobox(customplot.ycol_ComboBox_2, "level_masl")
        gui_utils.set_combobox(customplot.Filter1_ComboBox_2, "obsid")
        customplot.Filter1_QListWidget_2.item(1).setSelected(True)

        customplot.start_csv_dialog()
        # tempinput(data, charset='UTF-8', suffix='.csv')
        temp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
        temp.close()
        customplot.save_file_dialog.filename.setFilePath(temp.name)

        customplot.save_file_dialog.as_rows.setChecked(True)
        customplot.save_file_dialog.save_data()

        with open(temp.name) as f:
            rows = tuple([tuple(x.rstrip().split(";")) for x in f.readlines()])
        print(f"{rows=}")
        assert rows == (
            ("rowid", "index", "values", "label"),
            ("0", "2026-01-01 00:30:00", "5.0", "o1"),
            ("1", "2026-01-01 10:31:00", "10.0", "o1"),
            ("2", "2026-01-01 23:50:00", "17.0", "o1"),
            ("0", "2026-01-01 00:30:00", "5.0", "o2"),
            ("1", "2026-01-01 01:30:00", "5.0", "o2"),
            ("2", "2026-01-01 02:30:00", "6.0", "o2"),
            ("3", "2026-01-01 03:30:00", "7.0", "o2"),
            ("4", "2026-01-02 09:00:00", "4.0", "o2"),
            ("5", "2026-01-02 14:00:00", "10.0", "o2"),
        )

    @mock.patch("midvatten.tools.sectionplot.common_utils.MessagebarAndLog")
    def test_save_to_csv_1d(self, mock_messagebar):
        db_utils.sql_alter_db("""INSERT INTO obs_points (obsid) VALUES ('o1')""")
        db_utils.sql_alter_db("""INSERT INTO obs_points (obsid) VALUES ('o2')""")
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o1', '2026-01-01 00:30', 5.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o1', '2026-01-01 10:31', 10.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o1', '2026-01-01 23:50', 18.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o2', '2026-01-01 00:30', 5.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o2', '2026-01-01 01:30', 5.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o2', '2026-01-01 02:30', 6.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o2', '2026-01-01 03:30', 7.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o2', '2026-01-02 09:00', 4.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o2', '2026-01-02 14:00', 10.0)"""
        )

        self.midvatten.plot_sqlite()
        customplot = self.midvatten.customplot
        gui_utils.set_combobox(customplot.table_ComboBox_1, "w_levels_logger")
        gui_utils.set_combobox(customplot.xcol_ComboBox_1, "date_time")
        gui_utils.set_combobox(customplot.ycol_ComboBox_1, "level_masl")
        gui_utils.set_combobox(customplot.Filter1_ComboBox_1, "obsid")
        customplot.Filter1_QListWidget_1.item(0).setSelected(True)

        gui_utils.set_combobox(customplot.table_ComboBox_2, "w_levels_logger")
        gui_utils.set_combobox(customplot.xcol_ComboBox_2, "date_time")
        gui_utils.set_combobox(customplot.ycol_ComboBox_2, "level_masl")
        gui_utils.set_combobox(customplot.Filter1_ComboBox_2, "obsid")
        customplot.Filter1_QListWidget_2.item(1).setSelected(True)

        customplot.tab1_pandas_calc.rule.setText("1d")
        customplot.tab1_pandas_calc.how.setText("mean")
        customplot.tab2_pandas_calc.rule.setText("1d")
        customplot.tab2_pandas_calc.how.setText("mean")

        customplot.start_csv_dialog()
        # tempinput(data, charset='UTF-8', suffix='.csv')
        temp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
        temp.close()
        customplot.save_file_dialog.filename.setFilePath(temp.name)

        customplot.save_file_dialog.as_columns.setChecked(True)
        customplot.save_file_dialog.save_data()

        with open(temp.name) as f:
            rows = tuple([tuple(x.rstrip().split(";")) for x in f.readlines()])
        print(f"{rows=}")
        assert rows == (
            ("rowid", "index", "o1", "o2"),
            ("0", "2026-01-01", "11.0", "5.75"),
            ("1", "2026-01-02", "", "7.0"),
        )

    @mock.patch("midvatten.tools.sectionplot.common_utils.MessagebarAndLog")
    def test_save_to_csv_columns_two_filters(self, mock_messagebar):
        db_utils.sql_alter_db("""INSERT INTO obs_points (obsid) VALUES ('o1')""")
        db_utils.sql_alter_db("""INSERT INTO obs_points (obsid) VALUES ('o2')""")
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o1', '2026-01-01 00:30', 5.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o1', '2026-01-01 10:31', 10.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o1', '2026-01-01 23:50', 17.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o2', '2026-01-01 00:30', 5.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o2', '2026-01-01 01:30', 5.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o2', '2026-01-01 02:30', 6.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o2', '2026-01-01 03:30', 7.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o2', '2026-01-02 09:00', 4.0)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('o2', '2026-01-02 14:00', 10.0)"""
        )

        self.midvatten.plot_sqlite()
        customplot = self.midvatten.customplot
        gui_utils.set_combobox(customplot.table_ComboBox_1, "w_levels_logger")
        gui_utils.set_combobox(customplot.xcol_ComboBox_1, "date_time")
        gui_utils.set_combobox(customplot.ycol_ComboBox_1, "level_masl")
        gui_utils.set_combobox(customplot.Filter1_ComboBox_1, "obsid")
        customplot.Filter1_QListWidget_1.item(0).setSelected(True)

        gui_utils.set_combobox(customplot.table_ComboBox_2, "w_levels_logger")
        gui_utils.set_combobox(customplot.xcol_ComboBox_2, "date_time")
        gui_utils.set_combobox(customplot.ycol_ComboBox_2, "level_masl")
        gui_utils.set_combobox(customplot.Filter1_ComboBox_2, "obsid")
        customplot.Filter1_QListWidget_2.item(1).setSelected(True)
        gui_utils.set_combobox(customplot.Filter2_ComboBox_2, "obsid")
        customplot.Filter2_QListWidget_2.item(0).setSelected(True)

        customplot.start_csv_dialog()
        # tempinput(data, charset='UTF-8', suffix='.csv')
        temp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
        temp.close()
        customplot.save_file_dialog.filename.setFilePath(temp.name)

        customplot.save_file_dialog.as_columns.setChecked(True)
        customplot.save_file_dialog.save_data()

        with open(temp.name) as f:
            rows = tuple([tuple(x.rstrip().split(";")) for x in f.readlines()])
        print(f"{rows=}")
        assert rows == (
            ("rowid", "index", "o1", "o2, o2"),
            ("0", "2026-01-01 00:30:00", "5.0", "5.0"),
            ("1", "2026-01-01 01:30:00", "", "5.0"),
            ("2", "2026-01-01 02:30:00", "", "6.0"),
            ("3", "2026-01-01 03:30:00", "", "7.0"),
            ("4", "2026-01-01 10:31:00", "10.0", ""),
            ("5", "2026-01-01 23:50:00", "17.0", ""),
            ("6", "2026-01-02 09:00:00", "", "4.0"),
            ("7", "2026-01-02 14:00:00", "", "10.0"),
        )
