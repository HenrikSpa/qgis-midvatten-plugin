"""Tests for LoggerEditor duplicate-instant handling (Plan 1: safe save)."""

import gc
from unittest import mock

import pandas as pd
import pytest

pytest.importorskip("qgis.PyQt")

from midvatten.test import utils_for_tests
from midvatten.tools.loggereditor import LoggerEditor
from midvatten.tools.utils import db_utils
from midvatten.test.test_loggereditor_series import (
    _insert_obs_point,
    _insert_logger_row,
    _make_editor_with_buf,
)


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
