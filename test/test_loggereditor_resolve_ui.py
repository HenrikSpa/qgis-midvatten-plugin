"""show()-based UI tests for duplicate-resolution (banner, plot-focus, dialog)."""

import gc
from unittest import mock

import pytest

pytest.importorskip("qgis.PyQt")

import pandas as pd

from midvatten.test import utils_for_tests
from midvatten.tools.loggereditor import LoggerEditor
from midvatten.tools.utils import db_utils, gui_utils
from midvatten.test.test_loggereditor_dupes import _drop_dt_index


def _setup_twin_obsid():
    db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
    _drop_dt_index()
    db_utils.sql_alter_db(
        "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl)"
        " VALUES ('rb1','2024-01-01 00:00',100,10.0),"
        " ('rb1','2024-01-01 00:00:00',100,10.0),"
        " ('rb1','2024-01-02 00:00:00',200,20.0)"
    )


@pytest.mark.spatialite
class TestResolveUiSpatialite(utils_for_tests.MidvattenTestSpatialiteDbSv):
    def teardown_method(self):
        super().teardown_method()
        gc.collect()

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_focus_plot_on_instants_sets_range_and_separation(self, mock_messagebar):
        _setup_twin_obsid()
        editor = LoggerEditor(self.iface, self.midvatten.ms)
        editor.show()
        gui_utils.set_combobox(editor.combobox_obsid, "rb1")
        editor.update_plot()

        editor._focus_plot_on_instants([pd.Timestamp("2024-01-01 00:00:00")])

        print(f"{mock_messagebar.mock_calls=}")
        assert editor.separate_dt_precision_cb.isChecked() is True
        assert editor.from_date_time.dateTime().toPyDateTime() <= pd.Timestamp(
            "2024-01-01 00:00:00"
        )
        assert editor.to_date_time.dateTime().toPyDateTime() >= pd.Timestamp(
            "2024-01-01 00:00:00"
        )

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_dupe_banner_visible_only_when_duplicates(self, mock_messagebar):
        _setup_twin_obsid()
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('clean1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl)"
            " VALUES ('clean1','2024-03-01 00:00:00',1,1.0)"
        )
        editor = LoggerEditor(self.iface, self.midvatten.ms)
        editor.show()

        gui_utils.set_combobox(editor.combobox_obsid, "rb1")
        editor.update_plot()
        print(f"{mock_messagebar.mock_calls=}")
        assert editor._dupe_banner.isVisibleTo(editor) is True
        assert "1" in editor._dupe_warning_label.text()  # 1 duplicated instant

        gui_utils.set_combobox(editor.combobox_obsid, "clean1")
        editor.update_plot()
        assert editor._dupe_banner.isVisibleTo(editor) is False
