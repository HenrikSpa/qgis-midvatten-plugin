"""Tests for LoggerEditor duplicate-instant handling (Plan 1: safe save)."""

import gc
from unittest import mock

import pytest

pytest.importorskip("qgis.PyQt")

from midvatten.test import utils_for_tests
from midvatten.tools.loggereditor import LoggerEditor
from midvatten.tools.utils import db_utils
from midvatten.test.test_loggereditor_series import _insert_obs_point


@pytest.mark.spatialite
class TestLoggerEditorDupes(utils_for_tests.MidvattenTestSpatialiteDbSv):
    def teardown_method(self):
        super().teardown_method()
        gc.collect()

    def test_getlastcalibration_empty_returns_empty_list(self):
        """DB branch with no calibrated rows must return [] (no IndexError)."""
        _insert_obs_point("rb_empty")
        # row with NULL level_masl -> no calibration available
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm) VALUES (?, ?, ?)",
            all_args=[("rb_empty", "2024-01-01 00:00:00", 100.0)],
        )
        editor = LoggerEditor(self.iface, self.midvatten.ms)
        editor._buf = None  # force the DB branch
        result = editor.getlastcalibration("rb_empty")
        assert result == []

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_reset_settings_no_calibration_no_failure_log(self, mock_messagebar):
        """reset_settings with no calibrated rows must not log a failure message.

        Regression test for the IndexError guard added in fix commit 8e948c6:
        without ``if last_calibration and ...``, getlastcalibration returns []
        and ``[][0]`` raises IndexError, which the except handler logs as
        "Getting last calibration failed".
        """
        _insert_obs_point("rb_nocal")
        # Only a row with NULL level_masl — no calibration available
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm) VALUES (?, ?, ?)",
            all_args=[("rb_nocal", "2024-01-01 00:00:00", 100.0)],
        )
        editor = LoggerEditor(self.iface, self.midvatten.ms)
        editor._buf = None  # force the DB branch in getlastcalibration
        editor.obsid = "rb_nocal"

        with mock.patch.object(editor, "plot_or_update_selected_line"):
            editor.reset_settings()

        print(f"{mock_messagebar.mock_calls=}")
        for call in mock_messagebar.mock_calls:
            assert "Getting last calibration failed" not in str(call)
