"""Tests for midvsettingsdialog.MidvattenSettingsDock helpers."""

from unittest import mock

import pytest

from midvatten.midvsettingsdialog import MidvattenSettingsDock


class ComboStub:
    """Mimics the QComboBox subset used by load_and_select_last_piper_settings."""

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
        dock = mock.Mock(spec=[])
        dock.ms = mock.Mock(spec=["settingsdict"])
        dock.ms.settingsdict = settingsdict
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
