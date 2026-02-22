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
from unittest import mock

import numpy as np
from nose.plugins.attrib import attr

from midvatten.test import utils_for_tests
from midvatten.tools.utils import db_utils, gui_utils


def _insert_w_levels_logger_data():
    """Insert standard obs_points and w_levels_logger data for customplot tests."""
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


def _configure_customplot_tab1_tab2(customplot, tab2=False):
    """Set table, xcol, ycol, filtercol and filter selection for tab1 and optionally tab2."""
    gui_utils.set_combobox(customplot.tab1_table, "w_levels_logger")
    gui_utils.set_combobox(customplot.tab1_xcol, "date_time")
    gui_utils.set_combobox(customplot.tab1_ycol, "level_masl")
    gui_utils.set_combobox(customplot.tab1_filtercol1, "obsid")
    customplot.tab1_filter1.item(0).setSelected(True)
    if tab2:
        gui_utils.set_combobox(customplot.tab2_table, "w_levels_logger")
        gui_utils.set_combobox(customplot.tab2_xcol, "date_time")
        gui_utils.set_combobox(customplot.tab2_ycol, "level_masl")
        gui_utils.set_combobox(customplot.tab2_filtercol1, "obsid")
        customplot.tab2_filter1.item(1).setSelected(True)


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
        gui_utils.set_combobox(customplot.tab1_table, "w_levels_logger")
        gui_utils.set_combobox(customplot.tab1_xcol, "date_time")
        gui_utils.set_combobox(customplot.tab1_ycol, "level_masl")
        gui_utils.set_combobox(customplot.tab1_filtercol1, "obsid")
        customplot.tab1_filter1.item(0).setSelected(True)

        gui_utils.set_combobox(customplot.tab2_table, "w_levels_logger")
        gui_utils.set_combobox(customplot.tab2_xcol, "date_time")
        gui_utils.set_combobox(customplot.tab2_ycol, "level_masl")
        gui_utils.set_combobox(customplot.tab2_filtercol1, "obsid")
        customplot.tab2_filter1.item(1).setSelected(True)

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
        print(f"{mock_messagebar.mock_calls=}")
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
        gui_utils.set_combobox(customplot.tab1_table, "w_levels_logger")
        gui_utils.set_combobox(customplot.tab1_xcol, "date_time")
        gui_utils.set_combobox(customplot.tab1_ycol, "level_masl")
        gui_utils.set_combobox(customplot.tab1_filtercol1, "obsid")
        customplot.tab1_filter1.item(0).setSelected(True)

        gui_utils.set_combobox(customplot.tab2_table, "w_levels_logger")
        gui_utils.set_combobox(customplot.tab2_xcol, "date_time")
        gui_utils.set_combobox(customplot.tab2_ycol, "level_masl")
        gui_utils.set_combobox(customplot.tab2_filtercol1, "obsid")
        customplot.tab2_filter1.item(1).setSelected(True)

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
        print(f"{mock_messagebar.mock_calls=}")
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
        gui_utils.set_combobox(customplot.tab1_table, "w_levels_logger")
        gui_utils.set_combobox(customplot.tab1_xcol, "date_time")
        gui_utils.set_combobox(customplot.tab1_ycol, "level_masl")
        gui_utils.set_combobox(customplot.tab1_filtercol1, "obsid")
        customplot.tab1_filter1.item(0).setSelected(True)

        gui_utils.set_combobox(customplot.tab2_table, "w_levels_logger")
        gui_utils.set_combobox(customplot.tab2_xcol, "date_time")
        gui_utils.set_combobox(customplot.tab2_ycol, "level_masl")
        gui_utils.set_combobox(customplot.tab2_filtercol1, "obsid")
        customplot.tab2_filter1.item(1).setSelected(True)

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
        print(f"{mock_messagebar.mock_calls=}")
        assert rows == (
            ("rowid", "index", "o1", "o2"),
            ("0", "2026-01-01", "11.0", "5.75"),
            ("1", "2026-01-02", "", "7.0"),
        )

    @mock.patch("midvatten.tools.sectionplot.common_utils.MessagebarAndLog")
    def test_save_to_csv_columns_tab1_two_filters(self, mock_messagebar):
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
        gui_utils.set_combobox(customplot.tab1_table, "w_levels_logger")
        gui_utils.set_combobox(customplot.tab1_xcol, "date_time")
        gui_utils.set_combobox(customplot.tab1_ycol, "level_masl")
        gui_utils.set_combobox(customplot.tab1_filtercol1, "obsid")
        customplot.tab1_filter1.item(0).setSelected(True)
        gui_utils.set_combobox(customplot.tab1_filtercol2, "obsid")
        customplot.tab1_filter2.item(0).setSelected(True)

        gui_utils.set_combobox(customplot.tab2_table, "w_levels_logger")
        gui_utils.set_combobox(customplot.tab2_xcol, "date_time")
        gui_utils.set_combobox(customplot.tab2_ycol, "level_masl")
        gui_utils.set_combobox(customplot.tab2_filtercol1, "obsid")
        customplot.tab2_filter1.item(1).setSelected(True)

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
        print(f"{mock_messagebar.mock_calls=}")
        assert rows == (
            ("rowid", "index", "o1, o1", "o2"),
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
    def test_save_to_csv_columns_tab2_two_filters(self, mock_messagebar):
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
        gui_utils.set_combobox(customplot.tab1_table, "w_levels_logger")
        gui_utils.set_combobox(customplot.tab1_xcol, "date_time")
        gui_utils.set_combobox(customplot.tab1_ycol, "level_masl")
        gui_utils.set_combobox(customplot.tab1_filtercol1, "obsid")
        customplot.tab1_filter1.item(0).setSelected(True)

        gui_utils.set_combobox(customplot.tab2_table, "w_levels_logger")
        gui_utils.set_combobox(customplot.tab2_xcol, "date_time")
        gui_utils.set_combobox(customplot.tab2_ycol, "level_masl")
        gui_utils.set_combobox(customplot.tab2_filtercol1, "obsid")
        customplot.tab2_filter1.item(1).setSelected(True)
        gui_utils.set_combobox(customplot.tab2_filtercol2, "obsid")
        customplot.tab2_filter2.item(0).setSelected(True)

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
        print(f"{mock_messagebar.mock_calls=}")
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

    @mock.patch("midvatten.tools.sectionplot.common_utils.MessagebarAndLog")
    def test_save_to_csv_columns_tab3_two_filters(self, mock_messagebar):
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
        gui_utils.set_combobox(customplot.tab1_table, "w_levels_logger")
        gui_utils.set_combobox(customplot.tab1_xcol, "date_time")
        gui_utils.set_combobox(customplot.tab1_ycol, "level_masl")
        gui_utils.set_combobox(customplot.tab1_filtercol1, "obsid")
        customplot.tab1_filter1.item(0).setSelected(True)

        gui_utils.set_combobox(customplot.tab3_table, "w_levels_logger")
        gui_utils.set_combobox(customplot.tab3_xcol, "date_time")
        gui_utils.set_combobox(customplot.tab3_ycol, "level_masl")
        gui_utils.set_combobox(customplot.tab3_filtercol1, "obsid")
        customplot.tab3_filter1.item(1).setSelected(True)
        gui_utils.set_combobox(customplot.tab3_filtercol2, "obsid")
        customplot.tab3_filter2.item(0).setSelected(True)

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
        print(f"{mock_messagebar.mock_calls=}")
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

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_plot_button_draws_lines(self, mock_messagebar):
        _insert_w_levels_logger_data()
        self.midvatten.plot_sqlite()
        customplot = self.midvatten.customplot
        _configure_customplot_tab1_tab2(customplot, tab2=False)
        customplot.draw_plot_all()
        lines = customplot.axes.get_lines()
        print(f"{mock_messagebar.mock_calls=}")
        assert len(lines) >= 1
        xdata, ydata = lines[0].get_data()
        assert len(xdata) > 0 and len(ydata) > 0

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_plot_type_line(self, mock_messagebar):
        _insert_w_levels_logger_data()
        self.midvatten.plot_sqlite()
        customplot = self.midvatten.customplot
        _configure_customplot_tab1_tab2(customplot, tab2=False)
        gui_utils.set_combobox(customplot.tab1_plot_type, "line")
        customplot.draw_plot_all()
        lines = customplot.axes.get_lines()
        print(f"{mock_messagebar.mock_calls=}")
        assert len(lines) >= 1
        marker = lines[0].get_marker()
        linestyle = lines[0].get_linestyle()
        assert marker in (None, "None", "none")
        assert linestyle not in (None, "None", "none", "")

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_plot_type_marker(self, mock_messagebar):
        _insert_w_levels_logger_data()
        self.midvatten.plot_sqlite()
        customplot = self.midvatten.customplot
        _configure_customplot_tab1_tab2(customplot, tab2=False)
        gui_utils.set_combobox(customplot.tab1_plot_type, "marker")
        customplot.draw_plot_all()
        lines = customplot.axes.get_lines()
        print(f"{mock_messagebar.mock_calls=}")
        assert len(lines) >= 1
        linestyle = lines[0].get_linestyle()
        marker = lines[0].get_marker()
        assert linestyle in (None, "None", "none", "")
        assert marker not in (None, "None", "none")

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_plot_type_line_and_cross(self, mock_messagebar):
        _insert_w_levels_logger_data()
        self.midvatten.plot_sqlite()
        customplot = self.midvatten.customplot
        _configure_customplot_tab1_tab2(customplot, tab2=False)
        gui_utils.set_combobox(customplot.tab1_plot_type, "line and cross")
        customplot.draw_plot_all()
        lines = customplot.axes.get_lines()
        print(f"{mock_messagebar.mock_calls=}")
        assert len(lines) >= 1
        assert lines[0].get_marker() == "x"

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_plot_type_step_pre(self, mock_messagebar):
        _insert_w_levels_logger_data()
        self.midvatten.plot_sqlite()
        customplot = self.midvatten.customplot
        _configure_customplot_tab1_tab2(customplot, tab2=False)
        gui_utils.set_combobox(customplot.tab1_plot_type, "step-pre")
        customplot.draw_plot_all()
        lines = customplot.axes.get_lines()
        print(f"{mock_messagebar.mock_calls=}")
        assert len(lines) >= 1
        assert lines[0].get_drawstyle() == "steps-pre"
        assert lines[0].get_marker() in (None, "None", "none")

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_remove_mean_checkbox(self, mock_messagebar):
        _insert_w_levels_logger_data()
        self.midvatten.plot_sqlite()
        customplot = self.midvatten.customplot
        _configure_customplot_tab1_tab2(customplot, tab2=False)
        customplot.draw_plot_all()
        _, ydata_before = customplot.axes.get_lines()[0].get_data()
        customplot.tab1_remove_mean.setChecked(True)
        customplot.draw_plot_all()
        _, ydata_after = customplot.axes.get_lines()[0].get_data()
        print(f"{mock_messagebar.mock_calls=}")
        assert abs(float(np.mean(ydata_after))) < 1e-10
        assert abs(float(np.mean(ydata_before))) > 0.1

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_grid_checkbox(self, mock_messagebar):
        _insert_w_levels_logger_data()
        self.midvatten.plot_sqlite()
        customplot = self.midvatten.customplot
        _configure_customplot_tab1_tab2(customplot, tab2=False)
        customplot.draw_plot_all()
        customplot.grid.setChecked(True)
        customplot.refreshPlot()
        gridlines = customplot.axes.xaxis.get_gridlines()
        print(f"{mock_messagebar.mock_calls=}")
        assert len(gridlines) > 0
        assert gridlines[0].get_visible()
        customplot.grid.setChecked(False)
        customplot.refreshPlot()
        assert not customplot.axes.xaxis.get_gridlines()[0].get_visible()

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_legend_checkbox(self, mock_messagebar):
        _insert_w_levels_logger_data()
        self.midvatten.plot_sqlite()
        customplot = self.midvatten.customplot
        _configure_customplot_tab1_tab2(customplot, tab2=True)
        customplot.create_legend.setChecked(True)
        customplot.draw_plot_all()
        print(f"{mock_messagebar.mock_calls=}")
        assert customplot.axes.legend_ is not None
        customplot.create_legend.setChecked(False)
        customplot.refreshPlot()
        assert customplot.axes.legend_ is None

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_redraw_after_draw(self, mock_messagebar):
        _insert_w_levels_logger_data()
        self.midvatten.plot_sqlite()
        customplot = self.midvatten.customplot
        _configure_customplot_tab1_tab2(customplot, tab2=False)
        customplot.draw_plot_all()
        assert customplot.drawn
        customplot.grid.setChecked(True)
        customplot.refreshPlot()
        gridlines = customplot.axes.xaxis.get_gridlines()
        print(f"{mock_messagebar.mock_calls=}")
        assert len(gridlines) > 0 and gridlines[0].get_visible()

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_plot_type_combobox_tab2(self, mock_messagebar):
        _insert_w_levels_logger_data()
        self.midvatten.plot_sqlite()
        customplot = self.midvatten.customplot
        _configure_customplot_tab1_tab2(customplot, tab2=True)
        gui_utils.set_combobox(customplot.tab2_plot_type, "marker")
        customplot.draw_plot_all()
        lines = customplot.axes.get_lines()
        print(f"{mock_messagebar.mock_calls=}")
        assert len(lines) >= 2
        assert lines[1].get_linestyle() in (None, "None", "none", "")
        assert lines[1].get_marker() not in (None, "None", "none")

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_pandas_resample_rule_how_changes_line_data(self, mock_messagebar):
        _insert_w_levels_logger_data()
        self.midvatten.plot_sqlite()
        customplot = self.midvatten.customplot
        _configure_customplot_tab1_tab2(customplot, tab2=False)
        customplot.tab1_pandas_calc.rule.setText("1d")
        customplot.tab1_pandas_calc.how.setText("mean")
        customplot.draw_plot_all()
        lines = customplot.axes.get_lines()
        print(f"{mock_messagebar.mock_calls=}")
        assert len(lines) >= 1
        xdata, ydata = lines[0].get_data()
        assert len(xdata) == 1 and len(ydata) == 1
        # o1: 5.0, 10.0, 17.0 on 2026-01-01 -> daily mean = 32/3
        assert np.isclose(float(ydata[0]), 32.0 / 3.0)

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_pandas_resample_how_default_mean(self, mock_messagebar):
        _insert_w_levels_logger_data()
        self.midvatten.plot_sqlite()
        customplot = self.midvatten.customplot
        _configure_customplot_tab1_tab2(customplot, tab2=False)
        customplot.tab1_pandas_calc.rule.setText("1d")
        customplot.tab1_pandas_calc.how.setText("")
        customplot.draw_plot_all()
        lines = customplot.axes.get_lines()
        print(f"{mock_messagebar.mock_calls=}")
        assert len(lines) >= 1
        xdata, ydata = lines[0].get_data()
        assert len(xdata) == 1 and len(ydata) == 1
        # default how is mean; o1 daily mean = 32/3
        assert np.isclose(float(ydata[0]), 32.0 / 3.0)

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_pandas_resample_how_sum_different_from_mean(self, mock_messagebar):
        _insert_w_levels_logger_data()
        self.midvatten.plot_sqlite()
        customplot = self.midvatten.customplot
        _configure_customplot_tab1_tab2(customplot, tab2=False)
        customplot.tab1_pandas_calc.rule.setText("1d")
        customplot.tab1_pandas_calc.how.setText("mean")
        customplot.draw_plot_all()
        _, ydata_mean = customplot.axes.get_lines()[0].get_data()
        customplot.tab1_pandas_calc.how.setText("sum")
        customplot.draw_plot_all()
        _, ydata_sum = customplot.axes.get_lines()[0].get_data()
        print(f"{mock_messagebar.mock_calls=}")
        assert not np.isclose(float(ydata_mean[0]), float(ydata_sum[0]))

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_pandas_rolling_window_smooths_line_data(self, mock_messagebar):
        _insert_w_levels_logger_data()
        self.midvatten.plot_sqlite()
        customplot = self.midvatten.customplot
        _configure_customplot_tab1_tab2(customplot, tab2=False)
        customplot.tab1_pandas_calc.rule.setText("")
        customplot.tab1_pandas_calc.window.setText("2")
        customplot.draw_plot_all()
        lines = customplot.axes.get_lines()
        print(f"{mock_messagebar.mock_calls=}")
        assert len(lines) >= 1
        xdata, ydata = lines[0].get_data()
        assert len(xdata) == 3 and len(ydata) == 3
        raw = np.array([5.0, 10.0, 17.0])
        assert not np.allclose(ydata, raw)

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_pandas_rolling_center_checkbox(self, mock_messagebar):
        _insert_w_levels_logger_data()
        self.midvatten.plot_sqlite()
        customplot = self.midvatten.customplot
        _configure_customplot_tab1_tab2(customplot, tab2=False)
        customplot.tab1_pandas_calc.window.setText("2")
        customplot.tab1_pandas_calc.center.setChecked(True)
        customplot.draw_plot_all()
        _, ydata_center = customplot.axes.get_lines()[0].get_data()
        customplot.tab1_pandas_calc.center.setChecked(False)
        customplot.draw_plot_all()
        _, ydata_no_center = customplot.axes.get_lines()[0].get_data()
        print(f"{mock_messagebar.mock_calls=}")
        assert not np.allclose(ydata_center, ydata_no_center)

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_pandas_no_rule_no_window_uses_raw_data(self, mock_messagebar):
        _insert_w_levels_logger_data()
        self.midvatten.plot_sqlite()
        customplot = self.midvatten.customplot
        _configure_customplot_tab1_tab2(customplot, tab2=False)
        customplot.tab1_pandas_calc.rule.setText("")
        customplot.tab1_pandas_calc.window.setText("")
        customplot.draw_plot_all()
        lines = customplot.axes.get_lines()
        print(f"{mock_messagebar.mock_calls=}")
        assert len(lines) >= 1
        xdata, ydata = lines[0].get_data()
        assert len(xdata) == 3 and len(ydata) == 3

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_pandas_resample_plus_rolling(self, mock_messagebar):
        _insert_w_levels_logger_data()
        self.midvatten.plot_sqlite()
        customplot = self.midvatten.customplot
        _configure_customplot_tab1_tab2(customplot, tab2=False)
        customplot.tab1_pandas_calc.rule.setText("1d")
        customplot.tab1_pandas_calc.how.setText("mean")
        customplot.tab1_pandas_calc.window.setText("1")
        customplot.draw_plot_all()
        lines = customplot.axes.get_lines()
        print(f"{mock_messagebar.mock_calls=}")
        assert len(lines) >= 1
        xdata, ydata = lines[0].get_data()
        assert len(xdata) == 1 and len(ydata) == 1

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_pandas_invalid_window_critical_message(self, mock_messagebar):
        _insert_w_levels_logger_data()
        self.midvatten.plot_sqlite()
        customplot = self.midvatten.customplot
        _configure_customplot_tab1_tab2(customplot, tab2=False)
        customplot.tab1_pandas_calc.rule.setText("")
        customplot.tab1_pandas_calc.window.setText("x")
        customplot.draw_plot_all()
        lines = customplot.axes.get_lines()
        print(f"{mock_messagebar.mock_calls=}")
        critical_calls = [c for c in mock_messagebar.mock_calls if c[0] == "critical"]
        assert len(critical_calls) >= 1
        assert len(lines) >= 1
        _, ydata = lines[0].get_data()
        assert len(ydata) == 3

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_pandas_tab2_widgets_affect_second_line(self, mock_messagebar):
        _insert_w_levels_logger_data()
        self.midvatten.plot_sqlite()
        customplot = self.midvatten.customplot
        _configure_customplot_tab1_tab2(customplot, tab2=True)
        customplot.tab1_pandas_calc.rule.setText("1d")
        customplot.tab1_pandas_calc.how.setText("mean")
        customplot.tab2_pandas_calc.rule.setText("1d")
        customplot.tab2_pandas_calc.how.setText("mean")
        customplot.draw_plot_all()
        lines = customplot.axes.get_lines()
        print(f"{mock_messagebar.mock_calls=}")
        assert len(lines) >= 2
        x1, y1 = lines[0].get_data()
        x2, y2 = lines[1].get_data()
        assert len(x1) == 1 and len(y1) == 1
        assert len(x2) == 2 and len(y2) == 2
        assert np.isclose(float(y1[0]), 32.0 / 3.0)
        assert np.isclose(float(y2[0]), 5.75)
        assert np.isclose(float(y2[1]), 7.0)
