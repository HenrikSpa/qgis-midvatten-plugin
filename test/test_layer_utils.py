from unittest import mock

from midvatten.tools.utils import layer_utils


@mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
def test_warn_no_selection_uses_warning_bar(mock_messagebar):
    layer_utils.warn_no_selection()
    print(mock_messagebar.mock_calls)
    assert mock_messagebar.warning.called
    assert not mock_messagebar.critical.called


@mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
def test_warn_no_layer_names_the_field(mock_messagebar):
    layer_utils.warn_no_layer("obsid")
    print(mock_messagebar.mock_calls)
    (_, _, kwargs) = mock_messagebar.warning.mock_calls[0]
    assert "obsid" in kwargs["bar_msg"]
