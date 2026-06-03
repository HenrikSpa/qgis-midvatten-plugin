"""Tests for LoggerEditor duplicate-instant handling (Plan 1: safe save)."""

import gc
from unittest import mock

import pytest

pytest.importorskip("qgis.PyQt")

import pandas as pd

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

    def test_duplicate_instants_detects_repeated_label(self):
        _insert_obs_point("rb1")
        editor = _make_editor_with_buf(
            self.iface,
            self.midvatten.ms,
            obsid="rb1",
            dates=["2024-01-01 00:00", "2024-01-01 00:00:00", "2024-01-02 00:00:00"],
            head_values=[1.0, 1.0, 2.0],
            level_values=[10.0, 10.0, 20.0],
            series_ids=[None, None, None],
            sources=["", "", ""],
            series_buf={},
        )
        dups = editor._duplicate_instants()
        assert len(dups) == 1
        assert dups[0] == pd.Timestamp("2024-01-01 00:00:00")

    def test_duplicate_instants_empty_when_clean(self):
        _insert_obs_point("rb1")
        editor = _make_editor_with_buf(
            self.iface,
            self.midvatten.ms,
            obsid="rb1",
            dates=["2024-01-01 00:00:00", "2024-01-02 00:00:00"],
            head_values=[1.0, 2.0],
            level_values=[10.0, 20.0],
            series_ids=[None, None],
            sources=["", ""],
            series_buf={},
        )
        assert len(editor._duplicate_instants()) == 0

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_save_with_duplicate_instant_does_not_crash_or_corrupt(
        self, mock_messagebar
    ):
        _insert_obs_point("rb1")
        # Twins can only exist in legacy DBs created before the normalized-instant
        # unique index; drop it to reproduce that precondition.
        db_utils.sql_alter_db("DROP INDEX IF EXISTS uq_w_levels_logger_obsid_dt")
        # Two rows, same normalized instant, different raw text (the twin pair)
        _insert_logger_row("rb1", "2024-01-01 00:00", 100.0, 10.0)
        _insert_logger_row("rb1", "2024-01-01 00:00:00", 100.0, 11.0)
        # One clean row the user will actually edit
        _insert_logger_row("rb1", "2024-01-02 00:00:00", 200.0, 20.0)

        editor = _make_editor_with_buf(
            self.iface,
            self.midvatten.ms,
            obsid="rb1",
            dates=["2024-01-01 00:00", "2024-01-01 00:00:00", "2024-01-02 00:00:00"],
            head_values=[1.0, 1.0, 2.0],
            level_values=[10.0, 11.0, 20.0],
            series_ids=[None, None, None],
            sources=["", "", ""],
            series_buf={},
        )
        # Edit only the clean row
        editor._buf.loc[pd.Timestamp("2024-01-02 00:00:00"), "level_masl"] = 99.0

        result = editor.save_to_db()
        print(f"{mock_messagebar.mock_calls=}")
        assert result is True  # save succeeded, did not crash

        dbconn = db_utils.DbConnectionManager()
        rows = dbconn.execute_and_fetchall(
            "SELECT date_time, level_masl FROM w_levels_logger"
            " WHERE obsid='rb1' ORDER BY date_time"
        )
        dbconn.closedb()
        by_dt = {r[0]: r[1] for r in rows}
        # The clean edit persisted
        assert by_dt["2024-01-02 00:00:00"] == 99.0
        # BOTH twins are untouched (no silent overwrite of either)
        assert by_dt["2024-01-01 00:00"] == 10.0
        assert by_dt["2024-01-01 00:00:00"] == 11.0
        # A warning was emitted about the skipped duplicate
        assert mock_messagebar.warning.called

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_save_does_not_range_over_skipped_twin(self, mock_messagebar):
        """A duplicate instant between two edited clean rows must not be
        swept up by a BETWEEN range UPDATE."""
        _insert_obs_point("rb1")
        # Twins can only exist in legacy DBs created before the normalized-instant
        # unique index; drop it to reproduce that precondition.
        db_utils.sql_alter_db("DROP INDEX IF EXISTS uq_w_levels_logger_obsid_dt")
        # Clean row, then a twin pair (same instant), then another clean row.
        _insert_logger_row("rb1", "2024-01-01 00:00:00", 100.0, 10.0)
        _insert_logger_row("rb1", "2024-01-02 00:00", 200.0, 20.0)
        _insert_logger_row("rb1", "2024-01-02 00:00:00", 200.0, 21.0)
        _insert_logger_row("rb1", "2024-01-03 00:00:00", 300.0, 30.0)

        editor = _make_editor_with_buf(
            self.iface,
            self.midvatten.ms,
            obsid="rb1",
            dates=[
                "2024-01-01 00:00:00",
                "2024-01-02 00:00",
                "2024-01-02 00:00:00",
                "2024-01-03 00:00:00",
            ],
            head_values=[1.0, 2.0, 2.0, 3.0],
            level_values=[10.0, 20.0, 21.0, 30.0],
            series_ids=[None, None, None, None],
            sources=["", "", "", ""],
            series_buf={},
        )
        # Set BOTH flanking clean rows to NULL (a range pattern over the twin).
        editor._buf.loc[pd.Timestamp("2024-01-01 00:00:00"), "level_masl"] = None
        editor._buf.loc[pd.Timestamp("2024-01-03 00:00:00"), "level_masl"] = None

        result = editor.save_to_db()
        print(f"{mock_messagebar.mock_calls=}")
        assert result is True

        dbconn = db_utils.DbConnectionManager()
        rows = dbconn.execute_and_fetchall(
            "SELECT date_time, level_masl FROM w_levels_logger"
            " WHERE obsid='rb1' ORDER BY date_time"
        )
        dbconn.closedb()
        by_dt = {r[0]: r[1] for r in rows}
        # The clean edits persisted (set to NULL)
        assert by_dt["2024-01-01 00:00:00"] is None
        assert by_dt["2024-01-03 00:00:00"] is None
        # BOTH twins are untouched — not swept by a range UPDATE
        assert by_dt["2024-01-02 00:00"] == 20.0
        assert by_dt["2024-01-02 00:00:00"] == 21.0
        assert mock_messagebar.warning.called
