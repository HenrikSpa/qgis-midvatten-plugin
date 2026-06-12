"""show()-based tests for plot interaction: date-pick mode vs series selector,
picking on the markerless picker artist, and selection-button labels."""

import gc
from unittest import mock

import pytest

pytest.importorskip("qgis.PyQt")

import numpy as np
from matplotlib.backend_bases import MouseEvent
from matplotlib.dates import date2num

from midvatten.test import utils_for_tests
from midvatten.tools.loggereditor import LoggerEditor
from midvatten.tools.utils import db_utils, gui_utils


def _setup_simple_obsid():
    db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
    db_utils.sql_alter_db(
        "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl)"
        " VALUES ('rb1','2024-01-01 00:00:00',100,10.0),"
        " ('rb1','2024-01-02 00:00:00',200,20.0),"
        " ('rb1','2024-01-03 00:00:00',300,30.0)"
    )


@pytest.mark.spatialite
class TestPlotInteraction(utils_for_tests.MidvattenTestSpatialiteDbSv):
    def teardown_method(self):
        super().teardown_method()
        gc.collect()

    def _shown_editor(self):
        editor = LoggerEditor(self.iface, self.midvatten.ms)
        editor.show()
        gui_utils.set_combobox(editor.combobox_obsid, "rb1")
        editor.update_plot()
        return editor

    def test_selection_buttons_both_read_from_selection(self):
        """Both buttons take their date *from* the selection; the to-date button
        must not be labeled "To selection"."""
        editor = LoggerEditor(self.iface, self.midvatten.ms)
        assert editor.push_button_from_selection.text() == "From selection"
        assert editor.push_button_to_selection.text() == "From selection"

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_date_pick_mode_suspends_series_selector(self, mock_messagebar):
        """Arming select-date-in-plot must disable legend/series picking until
        the click lands; the click handler re-enables it."""
        _setup_simple_obsid()
        editor = self._shown_editor()
        print(f"{mock_messagebar.mock_calls=}")
        assert editor._legend_picker is not None
        assert editor._legend_picker._cid is not None  # active after plotting

        editor.set_date_from_x(editor.from_date_time)
        assert editor._legend_picker._cid is None  # suspended while armed

        event = mock.Mock(xdata=date2num(np.datetime64("2024-01-02")))
        editor.set_date_from_x_onclick(event, editor.from_date_time)
        assert editor._legend_picker._cid is not None  # restored after click
        assert editor.from_date_time.dateTime().toPyDateTime().date().isoformat() == (
            "2024-01-02"
        )

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_picker_artist_renders_nothing_but_still_picks(self, mock_messagebar):
        """The invisible picker artist must not render markers (pan/redraw cost)
        yet node picking via point proximity must keep working."""
        _setup_simple_obsid()
        editor = self._shown_editor()
        print(f"{mock_messagebar.mock_calls=}")
        artist = editor.logger_artist
        assert artist.get_marker() in ("", "None", None)
        assert artist.get_linestyle() in ("None", "none")

        x_px, y_px = editor.axes.transData.transform(
            (date2num(np.datetime64("2024-01-02")), 20.0)
        )
        click = MouseEvent("button_press_event", editor.canvas, x_px, y_px, button=1)
        contains, info = artist.contains(click)
        assert contains is True
        assert info["ind"][0] == 1  # the 2024-01-02 node

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_logger_artist_x_is_datetime64(self, mock_messagebar):
        """Plot x-data must stay datetime64 (vectorized date conversion), not
        per-row parsed strings/objects."""
        _setup_simple_obsid()
        editor = self._shown_editor()
        print(f"{mock_messagebar.mock_calls=}")
        xdata = np.asarray(editor.logger_artist.get_xdata())
        assert np.issubdtype(xdata.dtype, np.datetime64)


def _setup_many_sources_obsid(n_sources: int = 16):
    """One obsid whose rows split into n_sources line keys via source separation."""
    db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
    values = ",".join(f"('rb1','src{i:02d}')" for i in range(n_sources))
    db_utils.sql_alter_db(
        f"INSERT INTO w_logger_series (obsid, source) VALUES {values}"
    )
    rows = db_utils.sql_load_fr_db(
        "SELECT id FROM w_logger_series WHERE obsid='rb1' ORDER BY id"
    )[1]
    data = ",".join(
        f"('rb1','2024-01-{i + 1:02d} 00:00:00',{100 + i},{10.0 + i},{sid[0]})"
        for i, sid in enumerate(rows)
    )
    db_utils.sql_alter_db(
        "INSERT INTO w_levels_logger"
        f" (obsid, date_time, head_cm, level_masl, series_id) VALUES {data}"
    )


@pytest.mark.spatialite
class TestDrawSeriesCancel(utils_for_tests.MidvattenTestSpatialiteDbSv):
    def teardown_method(self):
        super().teardown_method()
        gc.collect()

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_cancel_many_lines_dialog_collapses_to_one_line(self, mock_messagebar):
        """Cancelling the 'Drawing N lines...' dialog must actually collapse
        the plot to merged lines, not re-enumerate the stale keys (which
        re-showed the dialog and, with nothing left to uncheck, recursed
        forever)."""
        _setup_many_sources_obsid(16)
        editor = LoggerEditor(self.iface, self.midvatten.ms)
        # Stub the progress dialog as "cancelled immediately".
        with mock.patch.object(
            __import__("qgis.PyQt.QtWidgets", fromlist=["QtWidgets"]),
            "QProgressDialog",
        ) as mock_dialog:
            mock_dialog.return_value.wasCanceled.return_value = True
            editor.show()
            gui_utils.set_combobox(editor.combobox_obsid, "rb1")
            editor.update_plot()
        print(f"{mock_messagebar.mock_calls=}")
        assert mock_dialog.called  # >15 keys did trigger the dialog
        # Cancel fell back to merging: source separation off, one merged line.
        assert editor.separate_source_cb.isChecked() is False
        assert len(editor.logger_plot_artists) == 1
