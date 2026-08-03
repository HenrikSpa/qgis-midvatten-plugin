"""
Tests for StoredSettingsMixin (Task 16): the shared stored-settings
load/save/edit-as-string logic extracted from tools/custom_drillreport.py
and tools/wqualreport_compact.py (previously ~150 lines duplicated
verbatim between the two).
"""

from unittest import mock

import pytest
from qgis.PyQt.QtWidgets import QCheckBox, QLineEdit

from midvatten.tools.utils.stored_settings import StoredSettingsMixin


class _FakeMs:
    """Minimal stand-in for MidvattenSettings: just enough for
    common_utils.save_stored_settings()/get_stored_settings() to work
    without a real QGIS plugin instance."""

    def __init__(self):
        self.settingsdict = {}

    def save_settings(self, key):
        pass


class _DummyDialog(StoredSettingsMixin):
    """Tiny host class mixing in StoredSettingsMixin, with real Qt widgets."""

    def __init__(self, ms):
        self.ms = ms
        self.stored_settings_key = "dummy_stored_settings_key"
        self.save_attrnames = ["name_field", "enabled_checkbox"]

        self.name_field = QLineEdit()
        self.enabled_checkbox = QCheckBox()

        self.stored_settings = {}


@pytest.fixture
def dummy():
    return _DummyDialog(_FakeMs())


@pytest.mark.active
@mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
def test_save_and_update_round_trip_lineedit_and_checkbox(mock_messagebar, dummy):
    dummy.name_field.setText("Borehole 1")
    dummy.enabled_checkbox.setChecked(True)

    dummy.save_stored_settings(dummy.save_attrnames)

    print(mock_messagebar.mock_calls)
    assert dummy.stored_settings == {
        "name_field": "Borehole 1",
        "enabled_checkbox": True,
    }

    # Reset the widgets, then restore them from the persisted dict.
    dummy.name_field.setText("")
    dummy.enabled_checkbox.setChecked(False)

    dummy.update_from_stored_settings(dummy.stored_settings)

    assert dummy.name_field.text() == "Borehole 1"
    assert dummy.enabled_checkbox.isChecked() is True


@pytest.mark.active
@mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
def test_update_from_stored_settings_is_noop_for_empty_or_missing(
    mock_messagebar, dummy
):
    # Falsy/non-dict input must be a no-op, matching the original behavior:
    # widgets are left as-is when there is nothing stored yet.
    dummy.update_from_stored_settings({})
    dummy.update_from_stored_settings(None)
    print(mock_messagebar.mock_calls)
    assert dummy.name_field.text() == ""
    assert dummy.enabled_checkbox.isChecked() is False


@pytest.mark.active
@mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
@mock.patch("midvatten.tools.utils.stored_settings.QCoreApplication.translate")
def test_save_stored_settings_translate_context_is_neutral(
    mock_translate, mock_messagebar, dummy
):
    """A missing attribute name is a "programmer error" message path. It must
    be filed under the mixin's own neutral context, not "DrillreportUi" --
    the bug this extraction fixes for wqualreport_compact's error messages."""
    mock_translate.side_effect = lambda context, text, *a, **kw: text

    dummy.save_stored_settings(["does_not_exist"])

    print(mock_messagebar.mock_calls)
    contexts = {call.args[0] for call in mock_translate.mock_calls}
    assert "StoredSettings" in contexts
    assert "DrillreportUi" not in contexts


@pytest.mark.active
@mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
@mock.patch("midvatten.tools.utils.stored_settings.QCoreApplication.translate")
@mock.patch("qgis.PyQt.QtWidgets.QInputDialog.getText")
def test_ask_for_stored_settings_translate_context_is_neutral(
    mock_gettext, mock_translate, mock_messagebar, dummy
):
    """ask_for_stored_settings() is where wqualreport_compact's original copy
    had a literal context mismatch: the dialog title was translated under
    "DrillreportUi" even though the rest of the method used
    "CompactWqualReportUi". The mixin must use one neutral context
    throughout."""
    mock_translate.side_effect = lambda context, text, *a, **kw: text
    mock_gettext.return_value = ('{"name_field": "x"}', True)

    result = dummy.ask_for_stored_settings({"name_field": "old"})

    print(mock_messagebar.mock_calls)
    assert result == {"name_field": "x"}
    contexts = {call.args[0] for call in mock_translate.mock_calls}
    assert contexts == {"StoredSettings"}
