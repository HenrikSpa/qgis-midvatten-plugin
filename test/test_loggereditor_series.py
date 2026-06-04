"""Integration tests for LoggerEditor series editing (CRUD, undo, orphan cleanup)."""

import gc
from unittest import mock

import pandas as pd
import pytest

pytest.importorskip("qgis.PyQt")

from midvatten.test import utils_for_tests
from midvatten.tools.loggereditor import LoggerEditor
from midvatten.tools.utils import db_utils


def _insert_obs_point(obsid: str) -> None:
    db_utils.sql_alter_db(
        "INSERT INTO obs_points (obsid) VALUES (?)", all_args=[(obsid,)]
    )


def _insert_logger_row(
    obsid: str,
    date_time: str,
    head_cm: float,
    level_masl: float,
    series_id: int | None = None,
) -> None:
    if series_id is not None:
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger"
            " (obsid, date_time, head_cm, level_masl, series_id)"
            " VALUES (?, ?, ?, ?, ?)",
            all_args=[(obsid, date_time, head_cm, level_masl, series_id)],
        )
    else:
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger"
            " (obsid, date_time, head_cm, level_masl)"
            " VALUES (?, ?, ?, ?)",
            all_args=[(obsid, date_time, head_cm, level_masl)],
        )


def _insert_series(obsid: str, source: str, instrument: str | None = None) -> int:
    """Insert a w_logger_series row and return its id."""
    db_utils.sql_alter_db(
        "INSERT INTO w_logger_series (obsid, source, instrument) VALUES (?, ?, ?)",
        all_args=[(obsid, source, instrument)],
    )
    rows = db_utils.sql_load_fr_db("SELECT MAX(id) FROM w_logger_series")
    return rows[1][0][0]


def _make_editor_with_buf(
    iface,
    ms,
    obsid: str,
    dates: list[str],
    head_values: list[float],
    level_values: list[float],
    series_ids: list[int | None],
    sources: list[str],
    series_buf: dict[int, dict],
    comments: list[str] | None = None,
) -> LoggerEditor:
    """Create a LoggerEditor with a manually constructed _buf (no show() needed)."""
    editor = LoggerEditor(iface, ms)
    editor._schema_variant = "series_join"
    existing_columns = [
        "obsid",
        "date_time",
        "head_cm",
        "level_masl",
        "source",
        "series_id",
        "created_at",
    ]
    if comments is not None:
        existing_columns.append("comment")
    editor._existing_columns = existing_columns

    buf_dict: dict = {
        "head_cm_m": head_values,
        "level_masl": level_values,
        "source": sources,
        "series_id": pd.array(series_ids, dtype="Int64"),
    }
    if comments is not None:
        buf_dict["comment"] = comments
    buf_dict["dt_length"] = [len(d) for d in dates]
    buf_dict["date_time_raw"] = list(dates)

    buf_df = pd.DataFrame(
        buf_dict,
        index=pd.to_datetime(dates, format="ISO8601"),
    )
    editor._buf = buf_df
    editor._original_buf = buf_df.copy()
    editor._buf_obsid = obsid
    editor._series_buf = {k: dict(v) for k, v in series_buf.items()}
    editor._original_series_buf = {k: dict(v) for k, v in series_buf.items()}
    editor._history.clear()
    editor._history_pos = -1
    # Push initial history snapshot (mirrors load_obsid_and_init behaviour)
    editor._history.append(
        {
            "label": "Loaded",
            "timestamp": pd.Timestamp.now(),
            "level_masl": editor._buf["level_masl"].copy(),
            "present_index": editor._buf.index.copy(),
            "present_raw": editor._buf["date_time_raw"].tolist(),
            "series_id": editor._buf["series_id"].copy(),
            "series_buf": {k: dict(v) for k, v in editor._series_buf.items()},
            "source": editor._buf["source"].copy(),
        }
    )
    editor._history_pos = 0
    editor._last_saved_history_pos = 0
    editor._dirty = False
    return editor


@pytest.mark.spatialite
class TestLoggerEditorSeries(utils_for_tests.MidvattenTestSpatialiteDbSv):
    def teardown_method(self):
        super().teardown_method()
        gc.collect()

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_create_series(self, mock_messagebar):
        """Create a new series from selected rows with NULL series_id."""
        _insert_obs_point("rb1")
        _insert_logger_row("rb1", "2024-01-01 00:00:00", 100.0, 10.0)
        _insert_logger_row("rb1", "2024-01-02 00:00:00", 200.0, 20.0)
        _insert_logger_row("rb1", "2024-01-03 00:00:00", 300.0, 30.0)

        editor = _make_editor_with_buf(
            self.iface,
            self.midvatten.ms,
            obsid="rb1",
            dates=["2024-01-01 00:00:00", "2024-01-02 00:00:00", "2024-01-03 00:00:00"],
            head_values=[1.0, 2.0, 3.0],
            level_values=[10.0, 20.0, 30.0],
            series_ids=[None, None, None],
            sources=["", "", ""],
            series_buf={},
        )

        # Verify initial state: all series_id are NA
        assert editor._buf["series_id"].isna().all()

        # Simulate create: assign a negative temporary ID
        temp_id = -1
        editor._series_buf[temp_id] = {
            "obsid": "rb1",
            "source": "test_source",
            "instrument": "test_instrument",
            "description": None,
            "comment": None,
        }
        editor._buf["series_id"] = temp_id
        editor._buf["source"] = "test_source"

        result = editor.save_to_db()

        print(f"{mock_messagebar.mock_calls=}")
        assert result is True

        # Verify DB state
        dbconn = db_utils.DbConnectionManager()
        series_rows = dbconn.execute_and_fetchall(
            "SELECT id, obsid, source, instrument FROM w_logger_series"
        )
        assert len(series_rows) == 1
        real_id = series_rows[0][0]
        assert series_rows[0][1] == "rb1"
        assert series_rows[0][2] == "test_source"
        assert series_rows[0][3] == "test_instrument"

        logger_rows = dbconn.execute_and_fetchall(
            "SELECT date_time, series_id FROM w_levels_logger ORDER BY date_time"
        )
        dbconn.closedb()
        assert len(logger_rows) == 3
        for row in logger_rows:
            assert row[1] == real_id

        # Verify the editor's _buf was remapped from temp_id to real_id
        assert (editor._buf["series_id"] == real_id).all()

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_assign_series(self, mock_messagebar):
        """Assign NULL rows to an existing series."""
        _insert_obs_point("rb1")
        sid = _insert_series("rb1", "existing_source")
        _insert_logger_row("rb1", "2024-01-01 00:00:00", 100.0, 10.0, series_id=sid)
        _insert_logger_row("rb1", "2024-01-02 00:00:00", 200.0, 20.0)
        _insert_logger_row("rb1", "2024-01-03 00:00:00", 300.0, 30.0)

        editor = _make_editor_with_buf(
            self.iface,
            self.midvatten.ms,
            obsid="rb1",
            dates=["2024-01-01 00:00:00", "2024-01-02 00:00:00", "2024-01-03 00:00:00"],
            head_values=[1.0, 2.0, 3.0],
            level_values=[10.0, 20.0, 30.0],
            series_ids=[sid, None, None],
            sources=["existing_source", "", ""],
            series_buf={
                sid: {
                    "obsid": "rb1",
                    "source": "existing_source",
                    "instrument": None,
                    "description": None,
                    "comment": None,
                },
            },
        )

        # Verify initial state
        assert editor._buf["series_id"].isna().sum() == 2

        # Simulate assign: set the two NULL rows to the existing series
        editor._buf.loc[editor._buf["series_id"].isna(), "series_id"] = sid
        editor._buf.loc[editor._buf["source"] == "", "source"] = "existing_source"

        result = editor.save_to_db()

        print(f"{mock_messagebar.mock_calls=}")
        assert result is True

        # Verify DB state: all rows have the same series_id
        dbconn = db_utils.DbConnectionManager()
        logger_rows = dbconn.execute_and_fetchall(
            "SELECT date_time, series_id FROM w_levels_logger ORDER BY date_time"
        )
        dbconn.closedb()
        assert len(logger_rows) == 3
        for row in logger_rows:
            assert row[1] == sid

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_edit_series_metadata(self, mock_messagebar):
        """Change series metadata (source) and verify DB update."""
        _insert_obs_point("rb1")
        sid = _insert_series("rb1", "old_source", instrument="old_instrument")
        _insert_logger_row("rb1", "2024-01-01 00:00:00", 100.0, 10.0, series_id=sid)
        _insert_logger_row("rb1", "2024-01-02 00:00:00", 200.0, 20.0, series_id=sid)

        editor = _make_editor_with_buf(
            self.iface,
            self.midvatten.ms,
            obsid="rb1",
            dates=["2024-01-01 00:00:00", "2024-01-02 00:00:00"],
            head_values=[1.0, 2.0],
            level_values=[10.0, 20.0],
            series_ids=[sid, sid],
            sources=["old_source", "old_source"],
            series_buf={
                sid: {
                    "obsid": "rb1",
                    "source": "old_source",
                    "instrument": "old_instrument",
                    "description": None,
                    "comment": None,
                },
            },
        )

        # Modify series metadata
        editor._series_buf[sid] = {
            "obsid": "rb1",
            "source": "new_source",
            "instrument": "new_instrument",
            "description": None,
            "comment": None,
        }
        # Update source column in _buf for rows with this series
        editor._buf.loc[editor._buf["series_id"] == sid, "source"] = "new_source"

        result = editor.save_to_db()

        print(f"{mock_messagebar.mock_calls=}")
        assert result is True

        # Verify DB state
        dbconn = db_utils.DbConnectionManager()
        series_rows = dbconn.execute_and_fetchall(
            "SELECT source, instrument FROM w_logger_series WHERE id = ?",
            (sid,),
        )
        dbconn.closedb()
        assert len(series_rows) == 1
        assert series_rows[0][0] == "new_source"
        assert series_rows[0][1] == "new_instrument"

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_undo_restore_series_id(self, mock_messagebar):
        """Undo restores series_id to the previous history state."""
        _insert_obs_point("rb1")
        sid = _insert_series("rb1", "src1")
        _insert_logger_row("rb1", "2024-01-01 00:00:00", 100.0, 10.0, series_id=sid)
        _insert_logger_row("rb1", "2024-01-02 00:00:00", 200.0, 20.0, series_id=sid)

        editor = _make_editor_with_buf(
            self.iface,
            self.midvatten.ms,
            obsid="rb1",
            dates=["2024-01-01 00:00:00", "2024-01-02 00:00:00"],
            head_values=[1.0, 2.0],
            level_values=[10.0, 20.0],
            series_ids=[sid, sid],
            sources=["src1", "src1"],
            series_buf={
                sid: {
                    "obsid": "rb1",
                    "source": "src1",
                    "instrument": None,
                    "description": None,
                    "comment": None,
                },
            },
        )

        original_series_ids = editor._buf["series_id"].tolist()

        # Modify series_id and push history
        new_temp_id = -1
        editor._buf["series_id"] = new_temp_id
        editor._series_buf[new_temp_id] = {
            "obsid": "rb1",
            "source": "new_src",
            "instrument": None,
            "description": None,
            "comment": None,
        }
        # Mock update_plot and _refresh_history_widget to avoid GUI calls
        with (
            mock.patch.object(editor, "update_plot"),
            mock.patch.object(editor, "_refresh_history_widget"),
            mock.patch.object(editor, "_refresh_window_title"),
        ):
            editor._history_push("Changed series")

            # Verify current state has the new series_id
            assert (editor._buf["series_id"] == new_temp_id).all()

            # Undo
            editor.undo()

        print(f"{mock_messagebar.mock_calls=}")

        # After undo, series_id should be back to original
        restored_series_ids = editor._buf["series_id"].tolist()
        assert restored_series_ids == original_series_ids

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_orphan_cleanup(self, mock_messagebar):
        """Reassigning all rows from series 2 to series 1 deletes orphaned series 2."""
        _insert_obs_point("rb1")
        sid1 = _insert_series("rb1", "source_A")
        sid2 = _insert_series("rb1", "source_B")
        _insert_logger_row("rb1", "2024-01-01 00:00:00", 100.0, 10.0, series_id=sid1)
        _insert_logger_row("rb1", "2024-01-02 00:00:00", 200.0, 20.0, series_id=sid2)
        _insert_logger_row("rb1", "2024-01-03 00:00:00", 300.0, 30.0, series_id=sid2)

        series_meta = {
            sid1: {
                "obsid": "rb1",
                "source": "source_A",
                "instrument": None,
                "description": None,
                "comment": None,
            },
            sid2: {
                "obsid": "rb1",
                "source": "source_B",
                "instrument": None,
                "description": None,
                "comment": None,
            },
        }

        editor = _make_editor_with_buf(
            self.iface,
            self.midvatten.ms,
            obsid="rb1",
            dates=["2024-01-01 00:00:00", "2024-01-02 00:00:00", "2024-01-03 00:00:00"],
            head_values=[1.0, 2.0, 3.0],
            level_values=[10.0, 20.0, 30.0],
            series_ids=[sid1, sid2, sid2],
            sources=["source_A", "source_B", "source_B"],
            series_buf=series_meta,
        )

        # Reassign all rows from series 2 to series 1
        editor._buf.loc[editor._buf["series_id"] == sid2, "series_id"] = sid1
        editor._buf.loc[editor._buf["source"] == "source_B", "source"] = "source_A"
        # Keep sid2 in _series_buf — orphan cleanup is triggered by zero remaining rows

        result = editor.save_to_db()

        print(f"{mock_messagebar.mock_calls=}")
        assert result is True

        # Verify DB: series 2 should be deleted (orphaned)
        dbconn = db_utils.DbConnectionManager()
        remaining_series = dbconn.execute_and_fetchall(
            "SELECT id, source FROM w_logger_series ORDER BY id"
        )
        logger_rows = dbconn.execute_and_fetchall(
            "SELECT series_id FROM w_levels_logger"
        )
        dbconn.closedb()

        # Only series 1 should remain
        assert len(remaining_series) == 1
        assert remaining_series[0][0] == sid1

        # All logger rows should point to series 1
        for row in logger_rows:
            assert row[0] == sid1

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_series_tab_not_shown_for_legacy_schema(self, mock_messagebar):
        """A DB without w_logger_series table should not get the Series tab."""

        def _legacy_tables_columns(table: str = "", dbconnection=None):
            """Return column info that simulates a legacy schema without series."""
            if table == "w_levels_logger":
                return {
                    "w_levels_logger": [
                        "obsid",
                        "date_time",
                        "head_cm",
                        "temp_degc",
                        "cond_mscm",
                        "level_masl",
                        "comment",
                        "source",
                    ]
                }
            if table == "w_logger_series":
                return {}
            # Fall through for any other table — return empty to avoid
            # calling the real function (which would see the real schema).
            return {}

        with mock.patch(
            "midvatten.tools.loggereditor.db_utils.tables_columns",
            side_effect=_legacy_tables_columns,
        ):
            editor = LoggerEditor(self.iface, self.midvatten.ms)
            editor.show()

        print(f"{mock_messagebar.mock_calls=}")

        # Schema variant should be "source_col" (legacy schema with source but no series)
        assert editor._schema_variant == "source_col"
        # The _series_tab attribute should not exist
        assert not hasattr(editor, "_series_tab")
