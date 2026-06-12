"""Tests for plugin dispatcher precondition behaviour.

These tests verify that verify_msettings_loaded_and_layer_edit_mode
behaves as expected — called by the dispatcher for every action that
needs_db=True.
"""

import pytest
from unittest import mock

from midvatten.tools.utils.midvatten_utils import (
    verify_msettings_loaded_and_layer_edit_mode,
)


@pytest.fixture()
def mock_midv_settings():
    """A minimal mock of MidvSettings with a valid (non-empty) database path."""
    ms = mock.MagicMock()
    ms.settingsareloaded = True
    ms.settingsdict = {"database": "/tmp/fake_test.sqlite"}
    return ms


@pytest.mark.spatialite
class TestVerifyMsettings:
    def test_returns_zero_when_settings_loaded_and_no_layers(self, mock_midv_settings):
        """No layer tuple: only checks that settings are loaded."""
        with (
            mock.patch(
                "midvatten.tools.utils.message_utils.MessagebarAndLog"
            ) as mock_messagebar,
            mock.patch(
                "midvatten.tools.utils.midvatten_utils.db_utils.check_connection_ok",
                return_value=True,
            ),
        ):
            err_flag = verify_msettings_loaded_and_layer_edit_mode(
                mock.MagicMock(), mock_midv_settings, ()
            )
            print(mock_messagebar.mock_calls)
        assert err_flag == 0

    def test_returns_nonzero_when_settings_not_loaded(self):
        """Missing database path means err_flag != 0."""
        with mock.patch(
            "midvatten.tools.utils.message_utils.MessagebarAndLog"
        ) as mock_messagebar:
            ms = mock.MagicMock()
            ms.settingsdict = {"database": ""}
            err_flag = verify_msettings_loaded_and_layer_edit_mode(
                mock.MagicMock(), ms, ()
            )
            print(mock_messagebar.mock_calls)
        assert err_flag != 0
