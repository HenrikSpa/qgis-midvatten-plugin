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
    _insert_series,
    _make_editor_with_buf,
)


def _drop_dt_index() -> None:
    """Drop the normalized-instant unique index so same-instant twins can be
    inserted (reproduces the legacy-DB precondition that predates the index)."""
    db_utils.sql_alter_db("DROP INDEX IF EXISTS uq_w_levels_logger_obsid_dt")


def _fetch_col(obsid: str, col: str) -> dict:
    """Return {date_time: <col>} for an obsid, ordered by date_time.

    ``col`` is a test-internal, trusted column name (the SQL-safety rule on
    interpolation applies to production queries, not test fixtures)."""
    dbconn = db_utils.DbConnectionManager()
    rows = dbconn.execute_and_fetchall(
        f"SELECT date_time, {col} FROM w_levels_logger"
        " WHERE obsid = ? ORDER BY date_time",
        (obsid,),
    )
    dbconn.closedb()
    return {r[0]: r[1] for r in rows}


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
        _drop_dt_index()
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

        by_dt = _fetch_col("rb1", "level_masl")
        # The clean edit persisted
        assert by_dt["2024-01-02 00:00:00"] == 99.0
        # BOTH twins are untouched (no silent overwrite of either)
        assert by_dt["2024-01-01 00:00"] == 10.0
        assert by_dt["2024-01-01 00:00:00"] == 11.0
        # A warning was emitted about the skipped duplicate
        assert mock_messagebar.warning.called

    def test_buffer_carries_raw_date_time_text(self):
        """The buffer keeps the original DB date_time text per row, distinct for twins."""
        _insert_obs_point("rb1")
        editor = _make_editor_with_buf(
            self.iface,
            self.midvatten.ms,
            obsid="rb1",
            dates=["2024-01-05 00:00", "2024-01-05 00:00:00", "2024-01-06 00:00:00"],
            head_values=[1.0, 1.0, 2.0],
            level_values=[10.0, 11.0, 20.0],
            series_ids=[None, None, None],
            sources=["", "", ""],
            series_buf={},
        )
        assert "date_time_raw" in editor._buf.columns
        assert editor._buf["date_time_raw"].tolist() == [
            "2024-01-05 00:00",
            "2024-01-05 00:00:00",
            "2024-01-06 00:00:00",
        ]

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_save_does_not_range_over_skipped_twin(self, mock_messagebar):
        """A duplicate instant between two edited clean rows must not be
        swept up by a BETWEEN range UPDATE."""
        _insert_obs_point("rb1")
        _drop_dt_index()
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

        by_dt = _fetch_col("rb1", "level_masl")
        # The clean edits persisted (set to NULL)
        assert by_dt["2024-01-01 00:00:00"] is None
        assert by_dt["2024-01-03 00:00:00"] is None
        # BOTH twins are untouched — not swept by a range UPDATE
        assert by_dt["2024-01-02 00:00"] == 20.0
        assert by_dt["2024-01-02 00:00:00"] == 21.0
        assert mock_messagebar.warning.called

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_save_series_id_change_with_twin_present(self, mock_messagebar):
        """Assigning a series_id to a clean row while twins exist must persist
        the assignment (series_join path) and leave both twin rows untouched."""
        _insert_obs_point("rb1")
        _drop_dt_index()
        sid = _insert_series("rb1", "src_a")
        # Twin pair: same normalized instant, different raw text, no series_id
        _insert_logger_row("rb1", "2024-01-05 00:00", 100.0, 10.0)
        _insert_logger_row("rb1", "2024-01-05 00:00:00", 100.0, 11.0)
        # Clean row to assign to the existing series
        _insert_logger_row("rb1", "2024-01-06 00:00:00", 200.0, 20.0)

        editor = _make_editor_with_buf(
            self.iface,
            self.midvatten.ms,
            obsid="rb1",
            dates=["2024-01-05 00:00", "2024-01-05 00:00:00", "2024-01-06 00:00:00"],
            head_values=[1.0, 1.0, 2.0],
            level_values=[10.0, 11.0, 20.0],
            series_ids=[None, None, None],
            sources=["", "", ""],
            series_buf={
                sid: {
                    "obsid": "rb1",
                    "source": "src_a",
                    "instrument": None,
                    "description": None,
                    "comment": None,
                }
            },
        )

        # Simulate the user assigning the clean row to the existing series
        editor._buf.loc[pd.Timestamp("2024-01-06 00:00:00"), "series_id"] = sid
        editor._buf.loc[pd.Timestamp("2024-01-06 00:00:00"), "source"] = "src_a"

        result = editor.save_to_db()
        print(f"{mock_messagebar.mock_calls=}")
        assert result is True

        by_sid = _fetch_col("rb1", "series_id")
        by_lvl = _fetch_col("rb1", "level_masl")
        # Clean row's series_id was written to the DB
        assert by_sid["2024-01-06 00:00:00"] == sid
        # Both twin rows are untouched: series_id still NULL, levels unchanged
        assert by_sid["2024-01-05 00:00"] is None
        assert by_sid["2024-01-05 00:00:00"] is None
        assert by_lvl["2024-01-05 00:00"] == 10.0
        assert by_lvl["2024-01-05 00:00:00"] == 11.0
        # A warning was emitted about the skipped duplicate instants
        assert mock_messagebar.warning.called

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_save_persists_removed_twin(self, mock_messagebar):
        """Dropping one twin row from the buffer deletes exactly that DB row on save."""
        _insert_obs_point("rb1")
        _drop_dt_index()
        _insert_logger_row("rb1", "2024-01-05 00:00", 100.0, 10.0)
        _insert_logger_row("rb1", "2024-01-05 00:00:00", 100.0, 11.0)
        _insert_logger_row("rb1", "2024-01-06 00:00:00", 200.0, 20.0)

        editor = _make_editor_with_buf(
            self.iface,
            self.midvatten.ms,
            obsid="rb1",
            dates=["2024-01-05 00:00", "2024-01-05 00:00:00", "2024-01-06 00:00:00"],
            head_values=[1.0, 1.0, 2.0],
            level_values=[10.0, 11.0, 20.0],
            series_ids=[None, None, None],
            sources=["", "", ""],
            series_buf={},
        )
        # Resolve: drop the coarse twin (raw text "2024-01-05 00:00"), keep the precise one.
        editor._buf = editor._buf[editor._buf["date_time_raw"] != "2024-01-05 00:00"]

        result = editor.save_to_db()
        print(f"{mock_messagebar.mock_calls=}")
        assert result is True

        by_dt = _fetch_col("rb1", "level_masl")
        assert "2024-01-05 00:00" not in by_dt
        assert by_dt["2024-01-05 00:00:00"] == 11.0
        assert by_dt["2024-01-06 00:00:00"] == 20.0

    def test_undo_redo_with_twins_present(self):
        """Editing then undo/redo must not corrupt a buffer that contains twins."""
        _insert_obs_point("rb1")
        editor = _make_editor_with_buf(
            self.iface,
            self.midvatten.ms,
            obsid="rb1",
            dates=["2024-01-05 00:00", "2024-01-05 00:00:00", "2024-01-06 00:00:00"],
            head_values=[1.0, 1.0, 2.0],
            level_values=[10.0, 11.0, 20.0],
            series_ids=[None, None, None],
            sources=["", "", ""],
            series_buf={},
        )
        editor._buf.loc[pd.Timestamp("2024-01-06 00:00:00"), "level_masl"] = 99.0
        editor._history_push("edit")
        assert len(editor._buf) == 3  # no row explosion from the twin label

        editor.undo()
        assert len(editor._buf) == 3
        assert editor._buf["date_time_raw"].tolist() == [
            "2024-01-05 00:00",
            "2024-01-05 00:00:00",
            "2024-01-06 00:00:00",
        ]
        assert (
            editor._buf.loc[pd.Timestamp("2024-01-06 00:00:00"), "level_masl"] == 20.0
        )

        editor.redo()
        assert len(editor._buf) == 3
        assert (
            editor._buf.loc[pd.Timestamp("2024-01-06 00:00:00"), "level_masl"] == 99.0
        )

    def test_undo_restores_removed_twin(self):
        """Undo after removing a twin brings the removed row back."""
        _insert_obs_point("rb1")
        editor = _make_editor_with_buf(
            self.iface,
            self.midvatten.ms,
            obsid="rb1",
            dates=["2024-01-05 00:00", "2024-01-05 00:00:00", "2024-01-06 00:00:00"],
            head_values=[1.0, 1.0, 2.0],
            level_values=[10.0, 11.0, 20.0],
            series_ids=[None, None, None],
            sources=["", "", ""],
            series_buf={},
        )
        editor._buf = editor._buf[editor._buf["date_time_raw"] != "2024-01-05 00:00"]
        editor._history_push("remove twin")
        assert len(editor._buf) == 2

        editor.undo()
        assert len(editor._buf) == 3
        assert "2024-01-05 00:00" in editor._buf["date_time_raw"].tolist()
