"""Tests for midvsettingsdialog.MidvattenSettingsDock helpers."""

import types

import pytest

from midvatten.midvsettingsdialog import MidvattenSettingsDock


class ComboStub:
    """Mimics the QComboBox subset that gui_utils.set_combobox calls."""

    def __init__(self, items):
        self.items = items
        self.current_index = -99  # sentinel: untouched

    def findText(self, text):
        try:
            return self.items.index(text)
        except ValueError:
            return -1

    def setCurrentIndex(self, index):
        self.current_index = index


@pytest.mark.active
class TestLoadAndSelectLastPiperSettings:
    def _make_stub_dock(self, settingsdict):
        dock = types.SimpleNamespace()
        dock.ms = types.SimpleNamespace(settingsdict=settingsdict)
        dock.param_cl = ComboStub(["", "cl_col"])
        dock.param_hco3 = ComboStub(["", "hco3_col"])
        dock.param_so4 = ComboStub(["", "so4_col"])
        dock.param_na = ComboStub(["", "na_col"])
        dock.param_k = ComboStub(["", "k_col"])
        dock.param_ca = ComboStub(["", "ca_col"])
        dock.param_mg = ComboStub(["", "mg_col"])
        dock.marker_combo_box = ComboStub(["", "obsid"])
        return dock

    def test_found_settings_are_selected(self):
        dock = self._make_stub_dock(
            {
                "piper_cl": "cl_col",
                "piper_hco3": "hco3_col",
                "piper_so4": "so4_col",
                "piper_na": "na_col",
                "piper_k": "k_col",
                "piper_ca": "ca_col",
                "piper_mg": "mg_col",
                "piper_markers": "obsid",
            }
        )
        MidvattenSettingsDock.load_and_select_last_piper_settings(dock)
        assert dock.param_cl.current_index == 1
        assert dock.param_hco3.current_index == 1
        assert dock.param_so4.current_index == 1
        assert dock.param_na.current_index == 1
        assert dock.param_k.current_index == 1
        assert dock.param_ca.current_index == 1
        assert dock.param_mg.current_index == 1
        assert dock.marker_combo_box.current_index == 1

    def test_missing_settings_leave_comboboxes_untouched(self):
        dock = self._make_stub_dock(
            {
                "piper_cl": "not_in_combobox",
                "piper_hco3": "hco3_col",
                "piper_so4": "nope",
                "piper_na": "nope",
                "piper_k": "nope",
                "piper_ca": "nope",
                "piper_mg": "nope",
                "piper_markers": "nope",
            }
        )
        MidvattenSettingsDock.load_and_select_last_piper_settings(dock)
        assert dock.param_cl.current_index == -99  # untouched
        assert dock.param_hco3.current_index == 1  # found and set
        assert dock.marker_combo_box.current_index == -99


@pytest.mark.active
class TestLoadAndSelectLastWqualSettings:
    def _make_stub_dock(self, settingsdict):
        dock = types.SimpleNamespace()
        dock.ms = types.SimpleNamespace(settingsdict=settingsdict)
        dock.list_of_tables_wqual = ComboStub(["", "w_qual_lab"])
        dock.list_of_columns_wqualparam = ComboStub(["", "parameter"])
        dock.list_of_columns_wqualvalue = ComboStub(["", "reading_txt"])
        dock.list_ofdate_time_format = ComboStub(["%Y-%m-%d", "%Y-%m-%d %H:%M:%S"])
        dock.list_of_columns_wqualunit = ComboStub(["", "unit"])
        dock.list_of_columns_wqualsorting = ComboStub(["", "obsid"])
        dock.table_updated_calls = []
        dock.wqual_table_updated = lambda: dock.table_updated_calls.append(True)
        return dock

    def test_found_table_selects_columns_and_updates(self):
        dock = self._make_stub_dock(
            {
                "wqualtable": "w_qual_lab",
                "wqual_paramcolumn": "parameter",
                "wqual_valuecolumn": "reading_txt",
                "wqual_date_time_format": "%Y-%m-%d %H:%M:%S",
                "wqual_unitcolumn": "unit",
                "wqual_sortingcolumn": "obsid",
            }
        )
        MidvattenSettingsDock.load_and_select_last_wqual_settings(dock)
        assert dock.list_of_tables_wqual.current_index == 1
        assert dock.table_updated_calls == [True]
        assert dock.list_of_columns_wqualparam.current_index == 1
        assert dock.list_of_columns_wqualvalue.current_index == 1
        assert dock.list_ofdate_time_format.current_index == 1
        assert dock.list_of_columns_wqualunit.current_index == 1
        assert dock.list_of_columns_wqualsorting.current_index == 1

    def test_missing_date_time_format_falls_back_to_index_1(self):
        dock = self._make_stub_dock(
            {
                "wqualtable": "w_qual_lab",
                "wqual_paramcolumn": "parameter",
                "wqual_valuecolumn": "reading_txt",
                "wqual_date_time_format": "not_in_list",
                "wqual_unitcolumn": "unit",
                "wqual_sortingcolumn": "obsid",
            }
        )
        MidvattenSettingsDock.load_and_select_last_wqual_settings(dock)
        assert dock.list_ofdate_time_format.current_index == 1  # fallback

    def test_missing_table_touches_nothing(self):
        dock = self._make_stub_dock(
            {
                "wqualtable": "gone_table",
                "wqual_paramcolumn": "parameter",
                "wqual_valuecolumn": "reading_txt",
                "wqual_date_time_format": "%Y-%m-%d",
                "wqual_unitcolumn": "unit",
                "wqual_sortingcolumn": "obsid",
            }
        )
        MidvattenSettingsDock.load_and_select_last_wqual_settings(dock)
        assert dock.list_of_tables_wqual.current_index == -99
        assert dock.table_updated_calls == []
        assert dock.list_of_columns_wqualparam.current_index == -99
