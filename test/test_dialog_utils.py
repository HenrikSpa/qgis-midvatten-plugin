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

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    @mock.patch("midvatten.tools.utils.dialog_utils.QtWidgets.QWidget.show")
    @mock.patch(
        "midvatten.tools.utils.dialog_utils.QtWidgets.QDialog.exec", return_value=0
    )
    @mock.patch("midvatten.tools.utils.dialog_utils.tr")
    def test_default_button_objectnames_stay_english_under_translation(
        self, mock_tr, mock_exec, mock_show, mock_messagebar
    ):
        """button_clicked/set_answer_and_value compare on objectName, so the
        default Ignore/Cancel/Ok buttons must keep the stable English
        objectName no matter what a translation returns for the label."""
        mock_tr.side_effect = lambda context, msg: f"TRANSLATED-{msg}"
        print(f"{mock_messagebar.mock_calls=}")
        d = dialog_utils.NotFoundQuestion(
            dialogtitle="Test",
            msg="Message",
            default_value="default",
            parent=None,
            # button_names left as None -> exercises the translated defaults.
        )
        buttons = d.button_box.buttons()
        by_object_name = {b.objectName(): b for b in buttons}
        assert set(by_object_name) == {"ignore", "cancel", "ok"}
        # Display text is translated (proves translation actually ran)...
        assert by_object_name["ignore"].text() == "TRANSLATED-Ignore"
        assert by_object_name["cancel"].text() == "TRANSLATED-Cancel"
        assert by_object_name["ok"].text() == "TRANSLATED-Ok"
        # ...but objectName -- the key button_clicked/set_answer_and_value
        # actually compare on -- stays the untranslated English key.
        d.set_answer_and_value(by_object_name["ok"].objectName())
        assert d.answer == "ok"

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    @mock.patch("midvatten.tools.utils.dialog_utils.QtWidgets.QWidget.show")
    @mock.patch(
        "midvatten.tools.utils.dialog_utils.QtWidgets.QDialog.exec", return_value=0
    )
    def test_ok_button_is_rightmost_even_with_extra_buttons(
        self, mock_exec, mock_show, mock_messagebar
    ):
        """The primary Ok button must be the last (rightmost) button regardless
        of extra action buttons like Skip, so chained dialogs (obsid then
        instrument) never place Ok where the next dialog shows Cancel."""
        d = dialog_utils.NotFoundQuestion(
            dialogtitle="Test",
            msg="Message",
            default_value="default",
            parent=None,
            button_names=["Cancel", "Ok", "Skip"],
        )
        object_names = [b.objectName() for b in d.button_box.buttons()]
        print(f"{object_names=}")
        assert object_names[-1] == "ok"


def test_ordered_button_names_ok_last_moves_ok_to_the_end():
    order = dialog_utils._ordered_button_names_ok_last
    # Ok is pushed to the end, other buttons keep their relative order.
    assert order(["Cancel", "Ok", "Skip"]) == ["Cancel", "Skip", "Ok"]
    # Already last -> unchanged.
    assert order(["Ignore", "Cancel", "Ok"]) == ["Ignore", "Cancel", "Ok"]
    # No Ok -> unchanged.
    assert order(["Cancel", "Skip"]) == ["Cancel", "Skip"]
