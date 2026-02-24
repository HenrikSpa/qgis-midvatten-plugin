"""
Dialog utilities for the Midvatten plugin.
"""

import os

import qgis.PyQt
from qgis.PyQt import QtCore, QtWidgets, uic
from qgis.PyQt.QtWebKitWidgets import QWebView

from midvatten.tools.utils.exceptions import UserInterruptError
from midvatten.tools.utils.message_utils import pop_up_info
from midvatten.tools.utils.string_utils import returnunicode, tr

not_found_dialog = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "../..", "ui", "not_found_gui.ui")
)[0]


class Askuser(QtWidgets.QDialog):
    def __init__(
        self,
        question="YesNo",
        msg="",
        dialogtitle=tr("askuser", "User input needed"),
        parent=None,
        include_cancel_button=False,
    ):
        self.result = ""
        if question == "YesNo":  #  Yes/No dialog
            if include_cancel_button:
                buttons = (
                    QtWidgets.QMessageBox.Yes
                    | QtWidgets.QMessageBox.No
                    | QtWidgets.QMessageBox.Cancel
                )
            else:
                buttons = QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
            reply = QtWidgets.QMessageBox.information(
                parent, dialogtitle, msg, buttons, QtWidgets.QMessageBox.Yes
            )
            if reply == QtWidgets.QMessageBox.Cancel:
                raise UserInterruptError()
            elif reply == QtWidgets.QMessageBox.Yes:
                self.result = 1  # 1 = "yes"
            else:
                self.result = 0  # 0="no"
        elif question == "AllSelected":  # All or Selected Dialog
            btn_all = QtWidgets.QPushButton(tr("askuser", "All"))  # = "0"
            btn_selected = QtWidgets.QPushButton(tr("askuser", "Selected"))  # = "1"
            msg_box = QtWidgets.QMessageBox(parent)
            msg_box.setText(msg)
            msg_box.setWindowTitle(dialogtitle)
            msg_box.addButton(btn_all, QtWidgets.QMessageBox.ActionRole)
            msg_box.addButton(btn_selected, QtWidgets.QMessageBox.ActionRole)
            msg_box.addButton(QtWidgets.QMessageBox.Cancel)
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
                        qgis.PyQt.QtWidgets.QLineEdit.Normal,
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
                            pop_up_info(
                                returnunicode(
                                    tr(
                                        "askuser",
                                        "Failure:\nOnly support resolutions\n%s",
                                    )
                                )
                                % ", ".join(supported_units)
                            )
                    else:
                        pop_up_info(
                            tr(
                                "askuser",
                                "Failure:\nMust write time resolution also.\n",
                            )
                        )


class NotFoundQuestion(QtWidgets.QDialog, not_found_dialog):
    window_position = qgis.PyQt.QtCore.QPoint(500, 150)

    def __init__(
        self,
        dialogtitle="Warning",
        msg="",
        existing_list=None,
        default_value="",
        parent=None,
        button_names=["Ignore", "Cancel", "Ok"],
        combobox_label="Similar values found in db (choose or edit):",
        reuse_header_list=None,
        reuse_column="",
        ignore_checkbox=False,
    ):
        QtWidgets.QDialog.__init__(self, parent)
        self.answer = None
        self.setupUi(self)
        self.setWindowTitle(dialogtitle)
        self.label.setText(msg)
        self.label.setTextInteractionFlags(qgis.PyQt.QtCore.Qt.TextSelectableByMouse)
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
        for idx, button_name in enumerate(button_names):
            button = QtWidgets.QPushButton(button_name)
            button.setObjectName(button_name.lower())
            self.button_box.addButton(button, QtWidgets.QDialogButtonBox.ActionRole)
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
        self.vertical_layout.setMargin(0)
        self.vertical_layout.addWidget(self.web_view)
        self.close_button = QtWidgets.QPushButton()
        self.close_button.setText(tr("HtmlDialog", "Close"))
        self.close_button.setMaximumWidth(150)
        self.horizontal_layout = QtWidgets.QHBoxLayout()
        self.horizontal_layout.setSpacing(2)
        self.horizontal_layout.setMargin(0)
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
            QtWidgets.QLineEdit.Normal,
            str(default_crs),
        )[0]
    )
