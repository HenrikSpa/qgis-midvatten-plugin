"""
/***************************************************************************
 This part of the Midvatten plugin tests the module that handles calibration
 of logger data.

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

import datetime
import math
from unittest import mock

import numpy as np
import pytest

from midvatten.tools.loggereditor import LoggerEditor
from midvatten.tools.utils import db_utils, date_utils, gui_utils
from midvatten.test import utils_for_tests


class CalibrloggerMixin:
    """Test to make sure wlvllogg_import goes all the way to the end without errors"""

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_calibrlogger_last_calibration(self, mock_messagebar):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl) VALUES ('rb1', '2017-02-01 00:00', 50, 100)"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl) VALUES ('rb1', '2017-03-01 00:00', 100, NULL)"
        )
        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")

        calibrlogger.update_plot()
        test = utils_for_tests.create_test_string(
            calibrlogger.getlastcalibration(calibrlogger.selected_obsid)
        )
        ref = "[(2017-02-01 00:00, 99.5)]"
        print(f"{mock_messagebar.mock_calls=}")
        assert test == ref

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_editor_starts_without_loading_an_obsid(self, mock_messagebar):
        """Editor starts clean: obsids are available but none is selected or
        loaded until the user picks one."""
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl)"
            " VALUES ('rb1', '2017-02-01 00:00', 50, 100)"
        )
        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()

        print(f"{mock_messagebar.mock_calls=}")
        # The obsid is available to choose...
        assert calibrlogger.combobox_obsid.count() == 1
        # ...but nothing is selected or loaded on startup.
        assert calibrlogger.combobox_obsid.currentIndex() == -1
        assert calibrlogger.selected_obsid == ""
        assert calibrlogger.obsid == ""
        assert calibrlogger._buf is None

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_calibrlogger_set_log_pos(self, mock_messagebar):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels (obsid, date_time, level_masl) VALUES ('rb1', '2017-02-01 00:00', 100)"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm) VALUES ('rb1', '2017-02-01 00:00', 100)"
        )
        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")

        calibrlogger.update_plot()

        calibrlogger.from_date_time.setDateTime(
            date_utils.to_date("2000-01-01 00:00:00")
        )
        calibrlogger.logger_elevation.setText("2")
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")

        calibrlogger.set_logger_pos()

        calibrlogger.save_to_db()
        test = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger"
            )
        )
        ref = "(True, [(rb1, 2017-02-01 00:00, 100.0, None, None, 3.0, None)])"
        print(f"{mock_messagebar.mock_calls=}")
        assert test == ref

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_calibrlogger_add_to_level_masl(self, mock_messagebar):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('rb1', '2017-02-01 00:00', 100)"
        )
        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1")

        calibrlogger.update_plot()

        calibrlogger.from_date_time.setDateTime(
            date_utils.to_date("2000-01-01 00:00:00")
        )
        calibrlogger.offset.setText("50")
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")

        calibrlogger.add_to_level_masl()

        calibrlogger.save_to_db()
        test = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger"
            )
        )
        ref = "(True, [(rb1, 2017-02-01 00:00, None, None, None, 150.0, None)])"
        print(f"{mock_messagebar.mock_calls=}")
        assert test == ref

    @mock.patch("midvatten.tools.loggereditor.common_utils.pop_up_info", autospec=True)
    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_calibrlogger_calc_best_fit_add_out_of_radius(
        self, mock_messagebar, skip_popup
    ):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels (obsid, date_time, level_masl) VALUES ('rb1', '2017-02-01 00:00', 100)"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('rb1', '2017-03-01 00:00', 50)"
        )
        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()

        calibrlogger.update_plot()

        calibrlogger.loggerpos_masl_or_offset_state = 2
        calibrlogger.from_date_time.setDateTime(
            date_utils.to_date("2000-01-01 00:00:00")
        )
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")

        calibrlogger.calc_best_fit()

        test = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger"
            )
        )
        ref = "(True, [(rb1, 2017-03-01 00:00, None, None, None, 50.0, None)])"
        print(f"{mock_messagebar.mock_calls=}")
        print(test)
        assert test == ref

    @mock.patch("midvatten.tools.loggereditor.common_utils.pop_up_info", autospec=True)
    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_calibrlogger_calc_best_fit_add(self, mock_messagebar, skip_popup):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels (obsid, date_time, level_masl) VALUES ('rb1', '2017-02-01 00:00', 100)"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('rb1', '2017-02-01 01:00', 50)"
        )
        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1")

        calibrlogger.update_plot()

        calibrlogger.loggerpos_masl_or_offset_state = 2
        calibrlogger.from_date_time.setDateTime(
            date_utils.to_date("2000-01-01 00:00:00")
        )
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")
        calibrlogger.best_fit_search_radius.setText("2 hours")

        calibrlogger.calc_best_fit()

        calibrlogger.save_to_db()
        test = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger"
            )
        )
        ref = "(True, [(rb1, 2017-02-01 01:00, None, None, None, 100.0, None)])"
        print(f"{mock_messagebar.mock_calls=}")
        assert test == ref

    @mock.patch("midvatten.tools.loggereditor.common_utils.pop_up_info", autospec=True)
    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_calibrlogger_calc_best_fit_add_matches_same_from_date(
        self, mock_messagebar, skip_popup
    ):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels (obsid, date_time, level_masl) VALUES ('rb1', '2017-02-01 00:00', 100)"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('rb1', '2017-02-01 01:00', 50)"
        )
        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1")

        calibrlogger.update_plot()

        calibrlogger.loggerpos_masl_or_offset_state = 2
        calibrlogger.from_date_time.setDateTime(date_utils.to_date("2017-02-01 01:00"))
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")
        calibrlogger.best_fit_search_radius.setText("2 hours")

        calibrlogger.calc_best_fit()

        calibrlogger.save_to_db()
        test = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger"
            )
        )
        ref = "(True, [(rb1, 2017-02-01 01:00, None, None, None, 100.0, None)])"
        print(f"{mock_messagebar.mock_calls=}")
        assert test == ref

    @mock.patch("midvatten.tools.loggereditor.common_utils.pop_up_info", autospec=True)
    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_calibrlogger_calc_best_fit_add_matches_same_to_date(
        self, mock_messagebar, skip_popup
    ):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels (obsid, date_time, level_masl) VALUES ('rb1', '2017-02-01 00:00', 100)"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('rb1', '2017-02-01 01:00', 50)"
        )
        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1")

        calibrlogger.update_plot()

        calibrlogger.loggerpos_masl_or_offset_state = 2
        calibrlogger.from_date_time.setDateTime(date_utils.to_date("2010-02-01 01:00"))
        calibrlogger.to_date_time.setDateTime(date_utils.to_date("2017-02-01 01:00"))
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")
        calibrlogger.best_fit_search_radius.setText("2 hours")

        calibrlogger.calc_best_fit()

        calibrlogger.save_to_db()
        test = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time, head_cm, temp_degc, cond_mscm, level_masl, comment FROM w_levels_logger"
            )
        )
        ref = "(True, [(rb1, 2017-02-01 01:00, None, None, None, 100.0, None)])"
        print(f"{mock_messagebar.mock_calls=}")
        assert test == ref

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_calibrlogger_set_last_calibration(self, mock_messagebar):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl) VALUES ('rb1', '2017-02-01 00:00', 50, 100)"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl) VALUES ('rb1', '2017-03-01 00:00', 100, NULL)"
        )
        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")

        """(level_masl - (head_cm/100))"""

        calibrlogger.update_plot()
        res = calibrlogger.getlastcalibration(calibrlogger.selected_obsid)
        test = utils_for_tests.create_test_string(calibrlogger.info.text())
        ref = "Last pos. for logger in rb1 was 99.500 masl at 2017-02-01 00:00"

        print(f"{mock_messagebar.mock_calls=}")
        assert test == ref

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_calibrlogger_set_last_calibration_zero(self, mock_messagebar):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl) VALUES ('rb1', '2017-02-01 00:00', 100, 1)"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl) VALUES ('rb1', '2017-03-01 00:00', 100, NULL)"
        )
        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")

        """(level_masl - (head_cm/100))"""

        calibrlogger.update_plot()
        res = calibrlogger.getlastcalibration(calibrlogger.selected_obsid)
        test = utils_for_tests.create_test_string(calibrlogger.info.text())
        ref = "Last pos. for logger in rb1 was 0.000 masl at 2017-02-01 00:00"
        print(f"{mock_messagebar.mock_calls=}")
        assert test == ref

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_calibrlogger_calibrinfolast_calibration(self, mock_messagebar):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb2')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl) VALUES ('rb1', '2017-02-01 00:00', 50, 100)"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl) VALUES ('rb1', '2017-03-01 00:00', 100, NULL)"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl) VALUES ('rb1', '2017-03-01 00:00', 200, 300)"
        )
        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()
        test = utils_for_tests.create_test_string(
            calibrlogger.get_uncalibrated_obsids()
        )
        ref = "[rb1]"
        print(f"{mock_messagebar.mock_calls=}")
        print(test)
        assert test == ref

    @mock.patch("midvatten.tools.utils.common_utils.Askuser")
    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_delete_range(self, mock_messagebar, askuser):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('rb1', '2017-02-01 00:00', 100)"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('rb1', '2017-02-10 00:00', 200)"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('rb1', '2017-01-28 00:00', 200)"
        )

        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")
        calibrlogger.update_plot()
        calibrlogger.from_date_time.setDateTime(date_utils.to_date("2017-01-30 00:00"))
        calibrlogger.to_date_time.setDateTime(date_utils.to_date("2017-02-02 00:00"))
        askuser.return_value.result = True

        calibrlogger.delete_selected_range("w_levels_logger")

        calibrlogger.save_to_db()
        res = db_utils.sql_load_fr_db(
            "SELECT date_time FROM w_levels_logger ORDER BY date_time"
        )
        test = utils_for_tests.create_test_string(res)
        print(f"{mock_messagebar.mock_calls=}")
        ref = "(True, [(2017-01-28 00:00), (2017-02-10 00:00)])"
        assert test == ref

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_change_timezone_no_w_levels_tz(self, mock_messagebar):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl) VALUES ('rb1', '2017-02-01 00:00', 100, 1)"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels (obsid, date_time, meas, level_masl) VALUES ('rb1', '2017-02-01 00:00', 200, 2)"
        )
        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()
        gui_utils.set_combobox(
            calibrlogger.combobox_obsid, "rb1", add_if_not_exists=False
        )
        calibrlogger.load_obsid_and_init()
        print(f"{mock_messagebar.mock_calls=}")
        assert tuple(calibrlogger.meas_ts.tolist()) == (("2017-02-01 00:00", 2.0),)

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_change_timezone_w_levels_tz_no_conversion(self, mock_messagebar):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl) VALUES ('rb1', '2017-02-01 00:00', 100, 1)"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels (obsid, date_time, meas, level_masl) VALUES ('rb1', '2017-02-01 00:00', 200, 2)"
        )

        db_utils.sql_alter_db(
            """UPDATE about_db SET description = description || ' (UTC+1)'
                                 WHERE tablename = 'w_levels_logger';"""
        )
        db_utils.sql_alter_db(
            """UPDATE about_db SET description = description || ' (Europe/Stockholm)'
                                 WHERE tablename = 'w_levels';"""
        )

        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()
        gui_utils.set_combobox(
            calibrlogger.combobox_obsid, "rb1", add_if_not_exists=False
        )
        calibrlogger.load_obsid_and_init()
        print(f"{mock_messagebar.mock_calls=}")
        assert tuple(calibrlogger.meas_ts.tolist()) == (
            (datetime.datetime(2017, 2, 1, 0, 0), 2.0),
        )

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_change_timezone_w_levels_tz_convert(self, mock_messagebar):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl) VALUES ('rb1', '2017-02-01 00:00', 100, 1)"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels (obsid, date_time, meas, level_masl) VALUES ('rb1', '2017-05-01 00:00', 200, 2)"
        )

        db_utils.sql_alter_db(
            """UPDATE about_db SET description = description || ' (UTC+1)'
                                 WHERE tablename = 'w_levels_logger';"""
        )
        db_utils.sql_alter_db(
            """UPDATE about_db SET description = description || ' (Europe/Stockholm)'
                                 WHERE tablename = 'w_levels';"""
        )

        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()
        gui_utils.set_combobox(
            calibrlogger.combobox_obsid, "rb1", add_if_not_exists=False
        )
        calibrlogger.load_obsid_and_init()
        print(f"{mock_messagebar.mock_calls=}")
        assert tuple(calibrlogger.meas_ts.tolist()) == (
            (datetime.datetime(2017, 4, 30, 23, 0), 2.0),
        )

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_change_timezone_no_w_levels_logger_tz(self, mock_messagebar):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl) VALUES ('rb1', '2017-02-01 00:00', 100, 1)"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels (obsid, date_time, meas, level_masl) VALUES ('rb1', '2017-05-01 00:00', 200, 2)"
        )

        db_utils.sql_alter_db(
            """UPDATE about_db SET description = ''
                                 WHERE tablename = 'w_levels_logger';"""
        )
        db_utils.sql_alter_db(
            """UPDATE about_db SET description = description || ' (Europe/Stockholm)'
                                 WHERE tablename = 'w_levels';"""
        )

        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()
        gui_utils.set_combobox(
            calibrlogger.combobox_obsid, "rb1", add_if_not_exists=False
        )
        calibrlogger.load_obsid_and_init()
        print(f"{mock_messagebar.mock_calls=}")
        assert tuple(calibrlogger.meas_ts.tolist()) == (("2017-05-01 00:00", 2.0),)

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_calibrlogger_normalize_against_logger(self, mock_messagebar):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels (obsid, date_time, level_masl) VALUES ('rb1', '2017-02-01 00:00', 20)"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl) VALUES ('rb1', '2017-02-01 00:00', 50, 100)"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl) VALUES ('rb1', '2017-03-01 00:00', 100, NULL)"
        )
        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")
        calibrlogger.plot_logger_head.setChecked(True)
        calibrlogger.normalize_head.setChecked(True)

        """(level_masl - (head_cm/100))"""
        gui_utils.set_combobox(
            calibrlogger.combobox_obsid, "rb1", add_if_not_exists=False
        )
        calibrlogger.load_obsid_and_init()

        # calibrlogger.update_plot()
        print(f"{mock_messagebar.mock_calls=}")
        test = tuple(calibrlogger.head_ts_for_plot.values)

        print(test)
        ref = (99.75, 100.25)

        assert test == ref

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_calibrlogger_normalize_against_meas(self, mock_messagebar):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels (obsid, date_time, level_masl) VALUES ('rb1', '2017-02-01 00:00', 20)"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl) VALUES ('rb1', '2017-02-01 00:00', 50, NULL)"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl) VALUES ('rb1', '2017-03-01 00:00', 100, NULL)"
        )
        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")
        calibrlogger.plot_logger_head.setChecked(True)
        calibrlogger.normalize_head.setChecked(True)

        """(level_masl - (head_cm/100))"""
        gui_utils.set_combobox(
            calibrlogger.combobox_obsid, "rb1", add_if_not_exists=False
        )
        calibrlogger.load_obsid_and_init()

        # calibrlogger.update_plot()
        print(f"{mock_messagebar.mock_calls=}")
        test = tuple(calibrlogger.head_ts_for_plot.values)

        print(test)
        ref = (19.75, 20.25)

        assert test == ref

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_update_plot_calls_draw_reference_subplot(self, mock_messagebar):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl) "
            "VALUES ('rb1', '2017-02-01 00:00', 50, 100)"
        )
        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1")
        with mock.patch.object(
            calibrlogger, "_draw_reference_subplot"
        ) as mock_draw_ref:
            calibrlogger.update_plot()
        print(f"{mock_messagebar.mock_calls=}")
        mock_draw_ref.assert_called_once_with()

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_buffer_fast_path(self, mock_messagebar):
        """After update_plot, _buf is populated and _buf_obsid is set."""
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl) "
            "VALUES ('rb1', '2017-02-01 00:00', 50, 100)"
        )
        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1")

        calibrlogger.update_plot()

        print(f"{mock_messagebar.mock_calls=}")
        assert calibrlogger._buf is not None
        assert calibrlogger._buf_obsid == "rb1"
        assert calibrlogger._buf["level_masl"].tolist() == [100.0]

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_undo_reverts_buffer(self, mock_messagebar):
        """undo() restores level_masl to the pre-edit state."""
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl) "
            "VALUES ('rb1', '2017-02-01 00:00', 100, NULL)"
        )
        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")
        calibrlogger.update_plot()

        # Before edit, level_masl is NaN/None
        initial_val = calibrlogger._buf["level_masl"].iloc[0]
        assert initial_val is None or (
            isinstance(initial_val, float) and math.isnan(initial_val)
        )

        # Make an edit
        calibrlogger.from_date_time.setDateTime(
            date_utils.to_date("2000-01-01 00:00:00")
        )
        calibrlogger.logger_elevation.setText("5")
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")
        calibrlogger.set_logger_pos()

        edited_level = calibrlogger._buf["level_masl"].iloc[0]
        assert edited_level is not None and not (
            isinstance(edited_level, float) and math.isnan(edited_level)
        )
        assert calibrlogger._history_pos == 1

        # Undo reverts
        calibrlogger.undo()

        print(f"{mock_messagebar.mock_calls=}")
        reverted_val = calibrlogger._buf["level_masl"].iloc[0]
        assert reverted_val is None or (
            isinstance(reverted_val, float) and math.isnan(reverted_val)
        )
        assert calibrlogger._history_pos == 0

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_redo_after_undo(self, mock_messagebar):
        """redo() re-applies the edit after undo()."""
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl) "
            "VALUES ('rb1', '2017-02-01 00:00', 100, NULL)"
        )
        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")
        calibrlogger.update_plot()

        calibrlogger.from_date_time.setDateTime(
            date_utils.to_date("2000-01-01 00:00:00")
        )
        calibrlogger.logger_elevation.setText("5")
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")
        calibrlogger.set_logger_pos()

        edited_values = calibrlogger._buf["level_masl"].tolist()

        calibrlogger.undo()
        calibrlogger.redo()

        print(f"{mock_messagebar.mock_calls=}")
        assert calibrlogger._buf["level_masl"].tolist() == edited_values
        assert calibrlogger._history_pos == 1

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_save_to_db_writes_changes(self, mock_messagebar):
        """save_to_db() persists level_masl edits to DB and clears dirty flag."""
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl) "
            "VALUES ('rb1', '2017-02-01 00:00:00', 100, NULL)"
        )
        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")
        calibrlogger.update_plot()

        calibrlogger.from_date_time.setDateTime(
            date_utils.to_date("2000-01-01 00:00:00")
        )
        calibrlogger.logger_elevation.setText("5")
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")
        calibrlogger.set_logger_pos()

        assert calibrlogger._dirty
        expected_level = calibrlogger._buf["level_masl"].iloc[0]

        result = calibrlogger.save_to_db()

        print(f"{mock_messagebar.mock_calls=}")
        assert result is True
        assert not calibrlogger._dirty

        # Confirm DB was updated
        _ok, rows = db_utils.sql_load_fr_db(
            "SELECT level_masl FROM w_levels_logger WHERE obsid='rb1'"
        )
        assert _ok
        assert rows[0][0] == expected_level

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_close_event_dirty_cancel(self, mock_messagebar):
        """closeEvent with dirty buffer and 'cancel' response ignores the event."""
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl) "
            "VALUES ('rb1', '2017-02-01 00:00', 100, NULL)"
        )
        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")
        calibrlogger.update_plot()

        calibrlogger.from_date_time.setDateTime(
            date_utils.to_date("2000-01-01 00:00:00")
        )
        calibrlogger.logger_elevation.setText("5")
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")
        calibrlogger.set_logger_pos()

        assert calibrlogger._dirty

        with mock.patch.object(
            calibrlogger, "_ask_save_discard_cancel", return_value="cancel"
        ):
            event = mock.MagicMock()
            calibrlogger.closeEvent(event)

        print(f"{mock_messagebar.mock_calls=}")
        event.ignore.assert_called_once()
        event.accept.assert_not_called()

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_obsid_switch_dirty_cancel_reverts_combobox(self, mock_messagebar):
        """_on_obsid_changed with 'cancel' restores the previous combobox selection."""
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb2')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl) "
            "VALUES ('rb1', '2017-02-01 00:00', 100, NULL)"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl) "
            "VALUES ('rb2', '2017-02-01 00:00', 50, 20)"
        )
        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")
        calibrlogger.update_plot()

        calibrlogger.from_date_time.setDateTime(
            date_utils.to_date("2000-01-01 00:00:00")
        )
        calibrlogger.logger_elevation.setText("5")
        calibrlogger.set_logger_pos()

        assert calibrlogger._dirty
        prev_index = calibrlogger.combobox_obsid.currentIndex()

        with mock.patch.object(
            calibrlogger, "_ask_save_discard_cancel", return_value="cancel"
        ):
            calibrlogger._on_obsid_changed(0)

        print(f"{mock_messagebar.mock_calls=}")
        assert calibrlogger.combobox_obsid.currentIndex() == prev_index

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_save_to_db_multi_period_range_sql(self, mock_messagebar):
        """save_to_db uses range SQL for multiple distinct calibration periods."""
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        # Period 1: rows with head_cm (will be "set logger position")
        for dt in ("2017-01-01 00:00", "2017-01-02 00:00", "2017-01-03 00:00"):
            db_utils.sql_alter_db(
                f"INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl) "
                f"VALUES ('rb1', '{dt}', 100, NULL)"
            )
        # Period 2: rows with level_masl already set (will be "add offset")
        for dt in ("2017-02-01 00:00", "2017-02-02 00:00", "2017-02-03 00:00"):
            db_utils.sql_alter_db(
                f"INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl) "
                f"VALUES ('rb1', '{dt}', NULL, 10.0)"
            )

        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")
        calibrlogger.update_plot()

        # Calibrate period 1 via "set logger position" (elevation=2 → level = 2 + head/100 = 3.0)
        calibrlogger.from_date_time.setDateTime(date_utils.to_date("2017-01-01 00:00"))
        calibrlogger.to_date_time.setDateTime(date_utils.to_date("2017-01-03 00:00"))
        calibrlogger.logger_elevation.setText("2")
        calibrlogger.loggerpos_masl_or_offset_state = 1
        calibrlogger.set_logger_pos()

        # Calibrate period 2 via "add offset" (+5)
        calibrlogger.from_date_time.setDateTime(date_utils.to_date("2017-02-01 00:00"))
        calibrlogger.to_date_time.setDateTime(date_utils.to_date("2017-02-03 00:00"))
        calibrlogger.offset.setText("5")
        calibrlogger.loggerpos_masl_or_offset_state = 2
        calibrlogger.add_to_level_masl()

        result = calibrlogger.save_to_db()

        print(f"{mock_messagebar.mock_calls=}")
        assert result is True

        _ok, rows = db_utils.sql_load_fr_db(
            "SELECT date_time, level_masl FROM w_levels_logger WHERE obsid='rb1' ORDER BY date_time"
        )
        assert _ok
        assert len(rows) == 6
        # Period 1: level = 2 + 100/100 = 3.0
        for row in rows[:3]:
            assert row[1] == pytest.approx(3.0), (
                f"period-1 row {row[0]} wrong: {row[1]}"
            )
        # Period 2: level = 10.0 + 5 = 15.0
        for row in rows[3:]:
            assert row[1] == pytest.approx(15.0), (
                f"period-2 row {row[0]} wrong: {row[1]}"
            )


class CalibrloggerPostgisMixin(CalibrloggerMixin):
    """Postgis-specific tests for calibrlogger."""

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_calibrlogger_adjust_trend(self, mock_messagebar):
        """Interactive trend: drag start up by 5, end stays (pivot)."""
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('rb1', '2017-02-01 00:00', 100)"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('rb1', '2017-02-10 00:00', 200)"
        )

        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")
        calibrlogger.update_plot()
        calibrlogger.from_date_time.setDateTime(
            date_utils.to_date("2000-01-01 00:00:00")
        )
        calibrlogger.to_date_time.setDateTime(date_utils.to_date("2099-12-31 23:59:59"))

        from midvatten.tools.trend_math import apply_trend_correction

        apply_trend_correction(calibrlogger._buf, 100.0, 200.0, 105.0, 200.0)
        calibrlogger._history_push("Adjust trend")
        calibrlogger.save_to_db()

        res = db_utils.sql_load_fr_db(
            "SELECT obsid, date_time, level_masl FROM w_levels_logger ORDER BY date_time"
        )
        print(f"{mock_messagebar.mock_calls=}")
        test = utils_for_tests.create_test_string(res)
        ref = "(True, [(rb1, 2017-02-01 00:00, 105.0), (rb1, 2017-02-10 00:00, 200.0)])"
        assert test == ref

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_calibrlogger_plot_source_postgres(self, mock_messagebar):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels (obsid, date_time, level_masl) VALUES ('rb1', '2017-02-01 00:00', 100)"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_logger_series (obsid, source) VALUES"
            " ('rb1', 'source1'), ('rb1', 'source2'),"
            " ('rb1', ''), ('rb1', NULL),"
            " ('rb1', ''), ('rb1', NULL)"
        )
        sid_s1 = db_utils.sql_load_fr_db(
            "SELECT id FROM w_logger_series WHERE obsid='rb1' AND source='source1'"
        )[1][0][0]
        sid_s2 = db_utils.sql_load_fr_db(
            "SELECT id FROM w_logger_series WHERE obsid='rb1' AND source='source2'"
        )[1][0][0]
        sid_empty = [
            r[0]
            for r in db_utils.sql_load_fr_db(
                "SELECT id FROM w_logger_series WHERE obsid='rb1' AND source='' ORDER BY id"
            )[1]
        ]
        sid_null = [
            r[0]
            for r in db_utils.sql_load_fr_db(
                "SELECT id FROM w_logger_series WHERE obsid='rb1' AND source IS NULL ORDER BY id"
            )[1]
        ]
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, series_id)"
            f" VALUES ('rb1', '2017-02-01 00:00', 100, {sid_s1})"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, series_id)"
            f" VALUES ('rb1', '2017-02-02 00:00', 101, {sid_s2})"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, series_id)"
            f" VALUES ('rb1', '2017-02-03 00:00', 102, {sid_empty[0]})"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, series_id)"
            f" VALUES ('rb1', '2017-02-04 00:00', 103, {sid_null[0]})"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, series_id)"
            f" VALUES ('rb1', '2017-02-05 00:00', 104, {sid_empty[1]})"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, series_id)"
            f" VALUES ('rb1', '2017-02-06 00:00', 105, {sid_null[1]})"
        )
        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")

        calibrlogger.update_plot()

        calibrlogger.from_date_time.setDateTime(
            date_utils.to_date("2000-01-01 00:00:00")
        )
        calibrlogger.logger_elevation.setText("2")

        calibrlogger.set_logger_pos()

        calibrlogger.save_to_db()
        test = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT l.obsid, l.date_time, l.head_cm, l.temp_degc, l.cond_mscm,"
                " round(l.level_masl::numeric, 2), l.comment, s.source"
                " FROM w_levels_logger l"
                " LEFT JOIN w_logger_series s ON s.id = l.series_id"
            )
        )
        ref = (
            "(True, ["
            "(rb1, 2017-02-01 00:00, 100.0, None, None, 3.00, None, source1), "
            "(rb1, 2017-02-02 00:00, 101.0, None, None, 3.01, None, source2), "
            "(rb1, 2017-02-03 00:00, 102.0, None, None, 3.02, None, ), "
            "(rb1, 2017-02-04 00:00, 103.0, None, None, 3.03, None, None), "
            "(rb1, 2017-02-05 00:00, 104.0, None, None, 3.04, None, ), "
            "(rb1, 2017-02-06 00:00, 105.0, None, None, 3.05, None, None)])"
        )
        print(test)
        print(ref)
        print(f"{mock_messagebar.mock_calls=}")
        assert test == ref

        lines_data = []
        line_labels = []
        for ax in calibrlogger.calibrplotfigure.axes:
            for line in ax.lines:
                line_labels.append(line.get_label())
                xydata = tuple(
                    [
                        (x, round(y, 2) if not np.isnan(y) else None)
                        for x, y in line.get_xydata()
                    ]
                )
                lines_data.append((line.get_label(), xydata))
                # print(line.get_label())
        # print(tuple(line_labels))
        assert tuple(line_labels) == (
            "rb1 measurements",
            "rb1 logger water level for editing",
            "rb1 logger water level",
            "rb1 logger water level, source1",
            "rb1 logger water level, source2",
            "rb1 logger head",
            "rb1 logger head, source1",
            "rb1 logger head, source2",
            "Selected nodes",
        )

        # print(lines_data)
        assert tuple(lines_data) == (
            ("rb1 measurements", ((17198.0, 100.0),)),
            (
                "rb1 logger water level for editing",
                (
                    (17198.0, 3.0),
                    (17199.0, 3.01),
                    (17200.0, 3.02),
                    (17201.0, 3.03),
                    (17202.0, 3.04),
                    (17203.0, 3.05),
                ),
            ),
            (
                "rb1 logger water level",
                (
                    (17198.0, None),
                    (17199.0, None),
                    (17200.0, 3.02),
                    (17201.0, 3.03),
                    (17202.0, 3.04),
                    (17203.0, 3.05),
                ),
            ),
            (
                "rb1 logger water level, source1",
                (
                    (17198.0, 3.0),
                    (17199.0, None),
                    (17200.0, None),
                    (17201.0, None),
                    (17202.0, None),
                    (17203.0, None),
                ),
            ),
            (
                "rb1 logger water level, source2",
                (
                    (17198.0, None),
                    (17199.0, 3.01),
                    (17200.0, None),
                    (17201.0, None),
                    (17202.0, None),
                    (17203.0, None),
                ),
            ),
            (
                "rb1 logger head",
                (
                    (17198.0, None),
                    (17199.0, None),
                    (17200.0, 3.02),
                    (17201.0, 3.03),
                    (17202.0, 3.04),
                    (17203.0, 3.05),
                ),
            ),
            (
                "rb1 logger head, source1",
                (
                    (17198.0, 3.0),
                    (17199.0, None),
                    (17200.0, None),
                    (17201.0, None),
                    (17202.0, None),
                    (17203.0, None),
                ),
            ),
            (
                "rb1 logger head, source2",
                (
                    (17198.0, None),
                    (17199.0, 3.01),
                    (17200.0, None),
                    (17201.0, None),
                    (17202.0, None),
                    (17203.0, None),
                ),
            ),
            (
                "Selected nodes",
                (
                    (17198.0, 3.0),
                    (17199.0, 3.01),
                    (17200.0, 3.02),
                    (17201.0, 3.03),
                    (17202.0, 3.04),
                    (17203.0, 3.05),
                ),
            ),
        )


class CalibrloggerSpatialiteMixin(CalibrloggerMixin):
    """Spatialite-specific tests for calibrlogger."""

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_calibrlogger_adjust_trend(self, mock_messagebar):
        """Interactive trend: drag start up by 5, end stays (pivot)."""
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('rb1', '2017-02-01 00:00', 100)"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('rb1', '2017-02-10 00:00', 200)"
        )

        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")
        calibrlogger.update_plot()
        calibrlogger.from_date_time.setDateTime(
            date_utils.to_date("2000-01-01 00:00:00")
        )
        calibrlogger.to_date_time.setDateTime(date_utils.to_date("2099-12-31 23:59:59"))

        from midvatten.tools.trend_math import apply_trend_correction

        apply_trend_correction(calibrlogger._buf, 100.0, 200.0, 105.0, 200.0)
        calibrlogger._history_push("Adjust trend")
        calibrlogger.save_to_db()

        res = db_utils.sql_load_fr_db(
            "SELECT obsid, date_time, level_masl FROM w_levels_logger ORDER BY date_time"
        )
        print(f"{mock_messagebar.mock_calls=}")
        test = utils_for_tests.create_test_string(res)
        ref = "(True, [(rb1, 2017-02-01 00:00, 105.0), (rb1, 2017-02-10 00:00, 200.0)])"
        assert test == ref

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_calibrlogger_adjust_trend_undo(self, mock_messagebar):
        """Undo should restore level_masl to pre-trend values."""
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('rb1', '2017-02-01 00:00', 100)"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('rb1', '2017-02-10 00:00', 200)"
        )

        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")
        calibrlogger.update_plot()
        calibrlogger.from_date_time.setDateTime(
            date_utils.to_date("2000-01-01 00:00:00")
        )
        calibrlogger.to_date_time.setDateTime(date_utils.to_date("2099-12-31 23:59:59"))

        from midvatten.tools.trend_math import apply_trend_correction

        original_values = calibrlogger._buf["level_masl"].copy()
        apply_trend_correction(calibrlogger._buf, 100.0, 200.0, 120.0, 180.0)
        calibrlogger._history_push("Adjust trend")

        calibrlogger.undo()

        print(f"{mock_messagebar.mock_calls=}")
        assert (calibrlogger._buf["level_masl"] == original_values).all()

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_calibrlogger_adjust_trend_drag_flow(self, mock_messagebar):
        """Full event-handler flow: enter trend mode, pick, drag, release."""
        from unittest.mock import MagicMock

        from matplotlib.backend_bases import PickEvent

        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('rb1', '2017-02-01 00:00', 100)"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, level_masl) VALUES ('rb1', '2017-02-10 00:00', 200)"
        )

        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")
        calibrlogger.update_plot()
        calibrlogger.from_date_time.setDateTime(
            date_utils.to_date("2000-01-01 00:00:00")
        )
        calibrlogger.to_date_time.setDateTime(date_utils.to_date("2099-12-31 23:59:59"))

        # Enter trend mode
        calibrlogger.adjust_trend_button.button().setChecked(True)
        calibrlogger.toggle_adjust_trend(True)
        assert calibrlogger._trend_start_marker is not None
        assert calibrlogger._trend_end_marker is not None

        # Simulate pick on start marker
        pick_event = MagicMock(spec=PickEvent)
        pick_event.artist = calibrlogger._trend_start_marker
        calibrlogger._trend_pick(pick_event)
        assert calibrlogger._trend_dragging == "start"

        # Simulate drag: move start endpoint up by 5
        motion_event = MagicMock()
        motion_event.ydata = 105.0
        calibrlogger._trend_move(motion_event)

        # Simulate release
        release_event = MagicMock()
        calibrlogger._trend_release(release_event)

        # Verify correction applied
        print(f"{mock_messagebar.mock_calls=}")
        assert calibrlogger._buf["level_masl"].iloc[0] == pytest.approx(105.0)
        assert calibrlogger._buf["level_masl"].iloc[1] == pytest.approx(200.0)

        # Verify trend overlay was redrawn (not stale/crashed)
        assert calibrlogger._trend_line is not None
        assert calibrlogger._trend_start_marker is not None

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_calibrlogger_plot_source_sqlite(self, mock_messagebar):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels (obsid, date_time, level_masl) VALUES ('rb1', '2017-02-01 00:00', 100)"
        )
        # New schema: source moved from w_levels_logger to w_logger_series.
        # One series per (original) source value so loggereditor's source-based
        # grouping still has distinct groups via the LEFT JOIN.
        db_utils.sql_alter_db(
            "INSERT INTO w_logger_series (obsid, source) VALUES"
            " ('rb1', 'source1'), ('rb1', 'source2'),"
            " ('rb1', ''), ('rb1', NULL),"
            " ('rb1', ''), ('rb1', NULL)"
        )
        sid_s1 = db_utils.sql_load_fr_db(
            "SELECT id FROM w_logger_series WHERE obsid='rb1' AND source='source1'"
        )[1][0][0]
        sid_s2 = db_utils.sql_load_fr_db(
            "SELECT id FROM w_logger_series WHERE obsid='rb1' AND source='source2'"
        )[1][0][0]
        sid_empty = [
            r[0]
            for r in db_utils.sql_load_fr_db(
                "SELECT id FROM w_logger_series WHERE obsid='rb1' AND source='' ORDER BY id"
            )[1]
        ]
        sid_null = [
            r[0]
            for r in db_utils.sql_load_fr_db(
                "SELECT id FROM w_logger_series WHERE obsid='rb1' AND source IS NULL ORDER BY id"
            )[1]
        ]
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, series_id)"
            f" VALUES ('rb1', '2017-02-01 00:00', 100, {sid_s1})"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, series_id)"
            f" VALUES ('rb1', '2017-02-02 00:00', 101, {sid_s2})"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, series_id)"
            f" VALUES ('rb1', '2017-02-03 00:00', 102, {sid_empty[0]})"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, series_id)"
            f" VALUES ('rb1', '2017-02-04 00:00', 103, {sid_null[0]})"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, series_id)"
            f" VALUES ('rb1', '2017-02-05 00:00', 104, {sid_empty[1]})"
        )
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, series_id)"
            f" VALUES ('rb1', '2017-02-06 00:00', 105, {sid_null[1]})"
        )
        calibrlogger = LoggerEditor(self.iface, self.midvatten.ms)
        calibrlogger.show()
        gui_utils.set_combobox(calibrlogger.combobox_obsid, "rb1 (uncalibrated)")

        calibrlogger.update_plot()

        calibrlogger.from_date_time.setDateTime(
            date_utils.to_date("2000-01-01 00:00:00")
        )
        calibrlogger.logger_elevation.setText("2")

        calibrlogger.set_logger_pos()

        calibrlogger.save_to_db()
        test = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT l.obsid, l.date_time, l.head_cm, l.temp_degc, l.cond_mscm,"
                " round(l.level_masl, 2), l.comment, s.source"
                " FROM w_levels_logger l"
                " LEFT JOIN w_logger_series s ON s.id = l.series_id"
            )
        )
        print(f"{mock_messagebar.mock_calls=}")
        ref = (
            "(True, ["
            "(rb1, 2017-02-01 00:00, 100.0, None, None, 3.0, None, source1), "
            "(rb1, 2017-02-02 00:00, 101.0, None, None, 3.01, None, source2), "
            "(rb1, 2017-02-03 00:00, 102.0, None, None, 3.02, None, ), "
            "(rb1, 2017-02-04 00:00, 103.0, None, None, 3.03, None, None), "
            "(rb1, 2017-02-05 00:00, 104.0, None, None, 3.04, None, ), "
            "(rb1, 2017-02-06 00:00, 105.0, None, None, 3.05, None, None)])"
        )
        assert test == ref

        lines_data = []
        line_labels = []
        for ax in calibrlogger.calibrplotfigure.axes:
            for line in ax.lines:
                line_labels.append(line.get_label())
                xydata = tuple(
                    [
                        (x, round(y, 2) if not np.isnan(y) else None)
                        for x, y in line.get_xydata()
                    ]
                )
                lines_data.append((line.get_label(), xydata))
                # print(line.get_label())
        # print(tuple(line_labels))
        print(f"{mock_messagebar.mock_calls=}")
        assert tuple(line_labels) == (
            "rb1 measurements",
            "rb1 logger water level for editing",
            "rb1 logger water level",
            "rb1 logger water level, source1",
            "rb1 logger water level, source2",
            "rb1 logger head",
            "rb1 logger head, source1",
            "rb1 logger head, source2",
            "Selected nodes",
        )

        # print(lines_data)
        assert tuple(lines_data) == (
            ("rb1 measurements", ((17198.0, 100.0),)),
            (
                "rb1 logger water level for editing",
                (
                    (17198.0, 3.0),
                    (17199.0, 3.01),
                    (17200.0, 3.02),
                    (17201.0, 3.03),
                    (17202.0, 3.04),
                    (17203.0, 3.05),
                ),
            ),
            (
                "rb1 logger water level",
                (
                    (17198.0, None),
                    (17199.0, None),
                    (17200.0, 3.02),
                    (17201.0, 3.03),
                    (17202.0, 3.04),
                    (17203.0, 3.05),
                ),
            ),
            (
                "rb1 logger water level, source1",
                (
                    (17198.0, 3.0),
                    (17199.0, None),
                    (17200.0, None),
                    (17201.0, None),
                    (17202.0, None),
                    (17203.0, None),
                ),
            ),
            (
                "rb1 logger water level, source2",
                (
                    (17198.0, None),
                    (17199.0, 3.01),
                    (17200.0, None),
                    (17201.0, None),
                    (17202.0, None),
                    (17203.0, None),
                ),
            ),
            (
                "rb1 logger head",
                (
                    (17198.0, None),
                    (17199.0, None),
                    (17200.0, 3.02),
                    (17201.0, 3.03),
                    (17202.0, 3.04),
                    (17203.0, 3.05),
                ),
            ),
            (
                "rb1 logger head, source1",
                (
                    (17198.0, 3.0),
                    (17199.0, None),
                    (17200.0, None),
                    (17201.0, None),
                    (17202.0, None),
                    (17203.0, None),
                ),
            ),
            (
                "rb1 logger head, source2",
                (
                    (17198.0, None),
                    (17199.0, 3.01),
                    (17200.0, None),
                    (17201.0, None),
                    (17202.0, None),
                    (17203.0, None),
                ),
            ),
            (
                "Selected nodes",
                (
                    (17198.0, 3.0),
                    (17199.0, 3.01),
                    (17200.0, 3.02),
                    (17201.0, 3.03),
                    (17202.0, 3.04),
                    (17203.0, 3.05),
                ),
            ),
        )


@pytest.mark.postgis
class TestCalibrloggerPostgis(
    CalibrloggerPostgisMixin, utils_for_tests.MidvattenTestPostgisDbSv
):
    pass


@pytest.mark.spatialite
class TestCalibrloggerSpatialite(
    CalibrloggerSpatialiteMixin, utils_for_tests.MidvattenTestSpatialiteDbSv
):
    pass
