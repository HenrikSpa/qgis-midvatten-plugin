"""
Dialog utilities for the Midvatten plugin.
"""

import qgis.PyQt
from qgis.PyQt import QtCore, QtWidgets, uic

try:
    from qgis.PyQt.QtWebKitWidgets import QWebView
except ImportError:
    from qgis.PyQt.QtWebEngineWidgets import QWebEngineView as QWebView

from midvatten.tools.utils.exceptions import UserInterruptError
from midvatten.tools.utils.file_utils import ui_path
from midvatten.tools.utils import message_utils
from midvatten.tools.utils.string_utils import returnunicode, tr

not_found_dialog = uic.loadUiType(ui_path("not_found_gui.ui"))[0]


class Askuser(QtWidgets.QDialog):
    def __init__(
        self,
        question: str = "YesNo",
        msg: str = "",
        dialogtitle: str = tr("askuser", "User input needed"),
        parent: None = None,
        include_cancel_button: bool = False,
    ):
        self.result = ""
        if question == "YesNo":  #  Yes/No dialog
            if include_cancel_button:
                buttons = (
                    QtWidgets.QMessageBox.StandardButton.Yes
                    | QtWidgets.QMessageBox.StandardButton.No
                    | QtWidgets.QMessageBox.StandardButton.Cancel
                )
            else:
                buttons = (
                    QtWidgets.QMessageBox.StandardButton.Yes
                    | QtWidgets.QMessageBox.StandardButton.No
                )
            reply = QtWidgets.QMessageBox.question(
                parent,
                dialogtitle,
                msg,
                buttons,
                QtWidgets.QMessageBox.StandardButton.Yes,
            )
            if reply == QtWidgets.QMessageBox.StandardButton.Cancel:
                raise UserInterruptError()
            elif reply == QtWidgets.QMessageBox.StandardButton.Yes:
                self.result = 1  # 1 = "yes"
            else:
                self.result = 0  # 0="no"
        elif question == "AllSelected":  # All or Selected Dialog
            btn_all = QtWidgets.QPushButton(tr("askuser", "All"))  # = "0"
            btn_selected = QtWidgets.QPushButton(tr("askuser", "Selected"))  # = "1"
            msg_box = QtWidgets.QMessageBox(parent)
            msg_box.setText(msg)
            msg_box.setWindowTitle(dialogtitle)
            msg_box.addButton(btn_all, QtWidgets.QMessageBox.ButtonRole.ActionRole)
            msg_box.addButton(btn_selected, QtWidgets.QMessageBox.ButtonRole.ActionRole)
            msg_box.addButton(QtWidgets.QMessageBox.StandardButton.Cancel)
            reply = msg_box.exec()
            self.result = reply  # ALL=0, SELECTED=1
        elif question == "DateShift":
            supported_units = [
                "microseconds",
                "milliseconds",
                "seconds",
                "minutes",
                "hours",
                "days",
                "weeks",
            ]
            while True:
                answer = str(
                    qgis.PyQt.QtWidgets.QInputDialog.getText(
                        None,
                        tr("askuser", "User input needed"),
                        returnunicode(
                            tr(
                                "askuser",
                                "Give needed adjustment of date/time for the data.\nSupported format: +- X <resolution>\nEx: 1 hours, -1 hours, -1 days\nSupported units:\n%s",
                            )
                        )
                        % ", ".join(supported_units),
                        qgis.PyQt.QtWidgets.QLineEdit.EchoMode.Normal,
                        "0 hours",
                    )[0]
                )
                if not answer:
                    self.result = "cancel"
                    break
                else:
                    adjustment_unit = answer.split()
                    if len(adjustment_unit) == 2:
                        if adjustment_unit[1] in supported_units:
                            self.result = adjustment_unit
                            break
                        else:
                            message_utils.pop_up_info(
                                returnunicode(
                                    tr(
                                        "askuser",
                                        "Failure:\nOnly support resolutions\n%s",
                                    )
                                )
                                % ", ".join(supported_units)
                            )
                    else:
                        message_utils.pop_up_info(
                            tr(
                                "askuser",
                                "Failure:\nMust write time resolution also.\n",
                            )
                        )


class NotFoundQuestion(QtWidgets.QDialog, not_found_dialog):
    window_position = qgis.PyQt.QtCore.QPoint(500, 150)

    def __init__(
        self,
        dialogtitle=tr("NotFoundQuestion", "Warning"),
        msg="",
        existing_list=None,
        default_value="",
        parent=None,
        button_names=None,
        combobox_label=tr(
            "NotFoundQuestion", "Similar values found in db (choose or edit):"
        ),
        reuse_header_list=None,
        reuse_column="",
        ignore_checkbox=False,
    ):
        QtWidgets.QDialog.__init__(self, parent)
        if button_names is None:
            button_names = ["Ignore", "Cancel", "Ok"]
        self.answer = None
        # Root widget in not_found_gui.ui is named "dialog". PyQt uic generates
        # connection code like dialog.dialog.accept (receiver name as attribute of
        # the setupUi argument), so the object passed to setupUi must have .dialog.
        self.dialog = self
        self.setupUi(self)
        self.setWindowTitle(dialogtitle)
        self.label.setText(msg)
        self.label.setTextInteractionFlags(
            qgis.PyQt.QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.combo_box.addItem(default_value)
        self.label_2.setText(combobox_label)
        if existing_list is not None:
            for existing in existing_list:
                self.combo_box.addItem(existing)

        if ignore_checkbox:
            self.ignore_checkbox = qgis.PyQt.QtWidgets.QCheckBox(
                tr("NotFoundQuestion", "Ignore database missmatch"),
                self,
            )
            self.ignore_checkbox.setToolTip(
                tr(
                    "NotFoundQuestion",
                    "Ignore database missmatch and try to import anyway",
                )
            )
            self.ignore_layout.addWidget(self.ignore_checkbox)
        # objectName stays the stable English key (button_clicked/set_answer_and_value
        # compare on it); only the visible label is translated, and only for the
        # known default names -- caller-supplied button_names are shown as-is.
        button_display_names = {
            "Ignore": tr("NotFoundQuestion", "Ignore"),
            "Cancel": tr("NotFoundQuestion", "Cancel"),
            "Ok": tr("NotFoundQuestion", "Ok"),
        }
        for idx, button_name in enumerate(button_names):
            button = QtWidgets.QPushButton(
                button_display_names.get(button_name, button_name)
            )
            button.setObjectName(button_name.lower())
            self.button_box.addButton(
                button, QtWidgets.QDialogButtonBox.ButtonRole.ActionRole
            )
            button.clicked.connect(lambda x: self.button_clicked())

        self.reuse_label = qgis.PyQt.QtWidgets.QLabel(
            tr("NotFoundQuestion", "Reuse answer for all identical")
        )
        self._reuse_column = qgis.PyQt.QtWidgets.QComboBox()
        self._reuse_column.addItem("")
        if isinstance(reuse_header_list, (list, tuple)):
            self.reuse_layout.addWidget(self.reuse_label)
            self.reuse_layout.addWidget(self._reuse_column)
            self.reuse_layout.addStretch()
            self._reuse_column.addItems(reuse_header_list)
            self.reuse_column_temp = reuse_column

        _label = QtWidgets.QLabel(msg)
        if 140 < _label.height() <= 300:
            self.setGeometry(
                NotFoundQuestion.window_position.x(),
                NotFoundQuestion.window_position.y(),
                self.width(),
                415,
            )
        elif _label.height() > 300:
            self.setGeometry(
                NotFoundQuestion.window_position.x(),
                NotFoundQuestion.window_position.y(),
                self.width(),
                600,
            )

        self.exec()

    @property
    def reuse_column_temp(self, value):
        index = self._reuse_column.findText(returnunicode(value))
        if index != -1:
            self._reuse_column.setCurrentIndex(index)

    @reuse_column_temp.setter
    def reuse_column_temp(self, value):
        index = self._reuse_column.findText(returnunicode(value))
        if index != -1:
            self._reuse_column.setCurrentIndex(index)

    def button_clicked(self):
        button = self.sender()
        button_object_name = button.objectName()
        self.set_answer_and_value(button_object_name)
        self.close()

    def set_answer_and_value(self, answer):
        self.answer = answer
        self.value = returnunicode(self.combo_box.currentText())
        self.reuse_column = self._reuse_column.currentText()

    def closeEvent(self, event):
        if self.answer is None:
            self.set_answer_and_value("cancel")
        NotFoundQuestion.window_position = self.geometry().topLeft()
        super().closeEvent(event)


class HtmlDialog(QtWidgets.QDialog):
    def __init__(self, title="", filepath=""):
        QtWidgets.QDialog.__init__(self)
        self.setModal(True)
        self.setupUi(title, filepath)

    def setupUi(self, title, filepath):
        self.resize(600, 500)
        self.web_view = QWebView()
        self.setWindowTitle(title)
        self.vertical_layout = QtWidgets.QVBoxLayout()
        self.vertical_layout.setSpacing(2)
        self.vertical_layout.setContentsMargins(0, 0, 0, 0)
        self.vertical_layout.addWidget(self.web_view)
        self.close_button = QtWidgets.QPushButton()
        self.close_button.setText(tr("HtmlDialog", "Close"))
        self.close_button.setMaximumWidth(150)
        self.horizontal_layout = QtWidgets.QHBoxLayout()
        self.horizontal_layout.setSpacing(2)
        self.horizontal_layout.setContentsMargins(0, 0, 0, 0)
        self.horizontal_layout.addStretch(1000)
        self.horizontal_layout.addWidget(self.close_button)
        self.close_button.clicked.connect(lambda x: self.closeWindow())
        self.vertical_layout.addLayout(self.horizontal_layout)
        self.setLayout(self.vertical_layout)
        url = QtCore.QUrl(filepath)
        self.web_view.load(url)

    def closeWindow(self):
        self.close()


def ask_user_about_stopping(question):
    """
    Asks the user a question and returns 'failed' or 'continue' as yes or no
    :param question: A string to write at the dialog box.
    :return: The string 'failed' or 'continue' as yes/no
    """
    answer = Askuser("YesNo", question)
    if answer.result:
        return "cancel"
    else:
        return "ignore"


def ask_for_export_crs(default_crs: int = "") -> str:
    return str(
        QtWidgets.QInputDialog.getText(
            None,
            tr("ask_for_export_crs", "Set export crs"),
            tr("ask_for_export_crs", "Give the crs for the exported database.\n"),
            QtWidgets.QLineEdit.EchoMode.Normal,
            str(default_crs),
        )[0]
    )
