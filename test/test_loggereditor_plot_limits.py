"""Regression test for the MultiCursor dataLim pollution fixed in
MultiCursorButton.__init__: xlim must frame the plotted data, not ~1970."""

import gc
from unittest import mock

import pytest

pytest.importorskip("qgis.PyQt")

from matplotlib.dates import num2date

from midvatten.test import utils_for_tests
from midvatten.test.test_loggereditor_series import (
    _insert_logger_row,
    _insert_obs_point,
)
from midvatten.tools.loggereditor import LoggerEditor
from midvatten.tools.utils import db_utils, gui_utils


@pytest.mark.spatialite
class TestPlotLimits(utils_for_tests.MidvattenTestSpatialiteDbSv):
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_xlim_frames_plotted_data_not_1970(self, mock_messagebar):
        _insert_obs_point("rb1")
        _insert_logger_row("rb1", "2020-05-01 00:00:00", 100.0, 10.0)
        _insert_logger_row("rb1", "2020-05-02 00:00:00", 110.0, 10.1)
        _insert_logger_row("rb1", "2020-05-03 00:00:00", 120.0, 10.2)
        db_utils.sql_alter_db(
            "INSERT INTO w_levels (obsid, date_time, level_masl) VALUES (?, ?, ?)",
            all_args=[("rb1", "2020-05-02 12:00:00", 10.15)],
        )

        editor = LoggerEditor(self.iface, self.midvatten.ms)
        editor.show()
        gui_utils.set_combobox(editor.combobox_obsid, "rb1")
        editor.update_plot()

        print(f"{mock_messagebar.mock_calls=}")

        xmin, xmax = (num2date(x) for x in editor.axes.get_xlim())
        assert xmin.year == 2020, f"xlim min stretched to {xmin.isoformat()}"
        assert xmax.year == 2020, f"xlim max stretched to {xmax.isoformat()}"

        editor.close()
        gc.collect()
