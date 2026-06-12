"""
Tests for midvatten.tools.utils.dialog_utils.
"""

from unittest import mock

import pytest

from midvatten.tools.utils import dialog_utils


@pytest.mark.active
class TestNotFoundQuestion:
    """Test NotFoundQuestion dialog construction and setupUi (self.dialog)."""

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    @mock.patch("midvatten.tools.utils.dialog_utils.QtWidgets.QWidget.show")
    @mock.patch(
        "midvatten.tools.utils.dialog_utils.QtWidgets.QDialog.exec", return_value=0
    )
    def test_setup_ui_sets_dialog_and_widgets(
        self, mock_exec, mock_show, mock_messagebar
    ):
        """NotFoundQuestion can be constructed; setupUi runs and dialog/widgets exist."""
        print(f"{mock_messagebar.mock_calls=}")
        d = dialog_utils.NotFoundQuestion(
            dialogtitle="Test",
            msg="Message",
            existing_list=["a", "b"],
            default_value="default",
            parent=None,
            button_names=["Ignore", "Cancel", "Ok"],
        )
        print(f"{mock_messagebar.mock_calls=}")
        assert d.dialog is d
        assert d.label is not None
        assert d.combo_box is not None
        assert d.button_box is not None
        assert d.label_2 is not None
        assert d.reuse_layout is not None
        assert d.ignore_layout is not None
        assert mock_exec.called

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    @mock.patch("midvatten.tools.utils.dialog_utils.QtWidgets.QWidget.show")
    @mock.patch(
        "midvatten.tools.utils.dialog_utils.QtWidgets.QDialog.exec", return_value=0
    )
    def test_default_value_in_combobox(self, mock_exec, mock_show, mock_messagebar):
        """Default value is added to combo box."""
        print(f"{mock_messagebar.mock_calls=}")
        d = dialog_utils.NotFoundQuestion(
            dialogtitle="Test",
            msg="Message",
            default_value="my_default",
            button_names=["ignore", "cancel", "ok"],
        )
        print(f"{mock_messagebar.mock_calls=}")
        assert d.combo_box.currentText() == "my_default"
