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


def _setup_two_period_obsid():
    db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
    _drop_dt_index()
    db_utils.sql_alter_db(
        "INSERT INTO w_logger_series (obsid, source) VALUES ('rb1','a'),('rb1','b')"
    )
    rows = db_utils.sql_load_fr_db(
        "SELECT id, source FROM w_logger_series WHERE obsid='rb1' ORDER BY id"
    )[1]
    sid = {src: i for i, src in rows}
    db_utils.sql_alter_db(
        "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl, series_id)"
        f" VALUES ('rb1','2024-01-10 00:00',1,10.0,{sid['a']}),"
        f" ('rb1','2024-01-10 00:00:00',1,11.0,{sid['b']}),"
        f" ('rb1','2024-06-10 00:00',2,20.0,{sid['a']}),"
        f" ('rb1','2024-06-10 00:00:00',2,21.0,{sid['b']})"
    )


@pytest.mark.spatialite
class TestResolveUiSpatialite(utils_for_tests.MidvattenTestSpatialiteDbSv):
    def teardown_method(self):
        super().teardown_method()
        gc.collect()

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
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

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
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

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_duplicate_marker_drawn_and_shrinks(self, mock_messagebar):
        _setup_twin_obsid()  # rb1: one duplicated instant at 2024-01-01 + a clean row
        editor = LoggerEditor(self.iface, self.midvatten.ms)
        editor.show()
        gui_utils.set_combobox(editor.combobox_obsid, "rb1")
        editor.update_plot()
        print(f"{mock_messagebar.mock_calls=}")
        assert len(editor._dupe_marker_artists) == 1  # one run

        # remove the duplicate, redraw -> marker gone
        editor._buf = editor._buf[editor._buf["date_time_raw"] != "2024-01-01 00:00"]
        editor.update_plot()
        assert editor._dupe_marker_artists == []

    def _open_dialog(self, editor):
        from qgis.PyQt.QtWidgets import QPushButton  # noqa: F401

        # full range so the dialog sees all duplicates initially
        fr, to = editor._full_buffer_range()
        editor.from_date_time.setDateTime(fr)
        editor.to_date_time.setDateTime(to)
        editor._resolve_dupes_btn.click()
        return editor._resolve_dialog

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_banner_button_opens_nonmodal_tool_dialog(self, mock_messagebar):
        from qgis.PyQt.QtCore import Qt

        _setup_twin_obsid()
        editor = LoggerEditor(self.iface, self.midvatten.ms)
        editor.show()
        gui_utils.set_combobox(editor.combobox_obsid, "rb1")
        editor.update_plot()
        editor._resolve_dupes_btn.click()
        dlg = editor._resolve_dialog
        # The editor opens the dialog via show() (the test harness patches
        # QWidget.show to a no-op, so isVisible() can't be asserted here); verify
        # it was created as a Qt.Tool window parented to the editor instead.
        assert dlg is not None
        assert (dlg.windowFlags() & Qt.Tool) == Qt.Tool
        assert dlg.parent() is editor
        # clicking again reuses the same instance
        editor._resolve_dupes_btn.click()
        assert editor._resolve_dialog is dlg

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_dialog_stay_open_resolves_two_periods(self, mock_messagebar):
        from qgis.PyQt.QtWidgets import QPushButton

        _setup_two_period_obsid()
        editor = LoggerEditor(self.iface, self.midvatten.ms)
        editor.show()
        gui_utils.set_combobox(editor.combobox_obsid, "rb1")
        editor.update_plot()
        dlg = self._open_dialog(editor)

        def keep_button(src):
            for b in dlg.findChildren(QPushButton):
                if b.text() == f"Keep '{src}'":
                    return b
            return None

        # Period A (Jan): keep 'a'
        editor.from_date_time.setDateTime(pd.Timestamp("2024-01-01"))
        editor.to_date_time.setDateTime(pd.Timestamp("2024-02-01"))
        keep_button("a").click()  # dialog still open, scoped to Jan
        # Period B (Jun): keep 'b' — SAME dialog instance
        assert editor._resolve_dialog is dlg
        editor.from_date_time.setDateTime(pd.Timestamp("2024-06-01"))
        editor.to_date_time.setDateTime(pd.Timestamp("2024-07-01"))
        keep_button("b").click()

        print(f"{mock_messagebar.mock_calls=}")
        jan = editor._buf[editor._buf.index == pd.Timestamp("2024-01-10 00:00:00")]
        jun = editor._buf[editor._buf.index == pd.Timestamp("2024-06-10 00:00:00")]
        assert jan["source"].tolist() == ["a"]
        assert jun["source"].tolist() == ["b"]

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_whole_dataset_button_widens_scope(self, mock_messagebar):
        from qgis.PyQt.QtWidgets import QPushButton

        _setup_two_period_obsid()
        editor = LoggerEditor(self.iface, self.midvatten.ms)
        editor.show()
        gui_utils.set_combobox(editor.combobox_obsid, "rb1")
        editor.update_plot()
        # open scoped to Jan only
        editor.from_date_time.setDateTime(pd.Timestamp("2024-01-01"))
        editor.to_date_time.setDateTime(pd.Timestamp("2024-02-01"))
        editor._resolve_dupes_btn.click()
        dlg = editor._resolve_dialog
        assert len(dlg._groups()) == 1  # only Jan in scope
        for b in dlg.findChildren(QPushButton):
            if b.text() == "Whole dataset":
                b.click()
                break
        assert len(dlg._groups()) == 2  # both periods now in scope

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_changing_obsid_closes_dialog(self, mock_messagebar):
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
        editor._resolve_dupes_btn.click()
        assert editor._resolve_dialog is not None
        gui_utils.set_combobox(editor.combobox_obsid, "clean1")
        assert editor._resolve_dialog is None
