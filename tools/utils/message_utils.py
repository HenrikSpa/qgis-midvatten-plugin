"""
Message bar and logging utilities for the Midvatten plugin.
"""

import traceback
from typing import Optional

import qgis.utils
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import QCoreApplication, QObject, QThread, pyqtSignal, pyqtSlot
from qgis.core import Qgis, QgsApplication

from midvatten.tools.utils.string_utils import returnunicode, tr


def show_message_log(pop_error=False):
    """
    Source: qgis code
    """
    if pop_error:
        qgis.utils.iface.messageBar().popWidget()

    qgis.utils.iface.openMessageLog()


class _MessageDispatcher(QObject):
    """Marshal message-bar work from background workers to the GUI thread."""

    requested = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.requested.connect(self._deliver)

    @pyqtSlot(object)
    def _deliver(self, payload) -> None:
        MessagebarAndLog._log_on_main_thread(*payload)


_message_dispatcher = _MessageDispatcher()


class MessagebarAndLog:
    """Class that sends logmessages to messageBar and or to QgsMessageLog

    Usage: MessagebarAndLog.info(bar_msg='a', log_msg='b', duration=10,
    messagebar_level=Qgis.Info, log_level=Qgis.Info,
    button=True)

    :param bar_msg: A short msg displayed in messagebar and log.
    :param log_msg: A long msg displayed only in log.
    :param messagebar_level: The message level of the messageBar.
    :param log_level: The message level of the QgsMessageLog  { Info = 0, Warning = 1, Critical = 2 }.
    :param duration: The duration of the messageBar.
    :param button: (True/False, default True) If False, the button to the
                   QgsMessageLog does not appear at the messageBar.

    :return:

    The message bar_msg is written to both messageBar and QgsMessageLog
    The log_msg is only written to QgsMessageLog

    * If the user only supplies bar_msg, a messageBar popup appears without button to message log.
    * If the user supplies only log_msg, the message is only written to message log.
    * If the user supplies both, a messageBar with bar_msg appears with a button to open message log.
      In the message log, the bar_msg and log_msg is written.

      Activate writing of log messages to file by settings :
      qgis Settings > Options > System > Environment > mark Use custom variables > Click Add >
      enter "QGIS_LOG_FILE" in the field Variable and a filename as Value.
    """

    def __init__(self):
        pass

    @staticmethod
    def log(
        bar_msg: Optional[str] = None,
        log_msg: Optional[str] = None,
        duration: int = 10,
        messagebar_level: Qgis.MessageLevel = Qgis.Info,
        log_level: Qgis.MessageLevel = Qgis.Info,
        button: bool = True,
    ):
        app = QCoreApplication.instance()
        if app is not None and QThread.currentThread() is not app.thread():
            _message_dispatcher.requested.emit(
                (
                    bar_msg,
                    log_msg,
                    duration,
                    messagebar_level,
                    log_level,
                    button,
                )
            )
            return None
        return MessagebarAndLog._log_on_main_thread(
            bar_msg,
            log_msg,
            duration,
            messagebar_level,
            log_level,
            button,
        )

    @staticmethod
    def _log_on_main_thread(
        bar_msg: Optional[str] = None,
        log_msg: Optional[str] = None,
        duration: int = 10,
        messagebar_level: Qgis.MessageLevel = Qgis.Info,
        log_level: Qgis.MessageLevel = Qgis.Info,
        button: bool = True,
    ):
        if qgis.utils.iface is None:
            return None
        if bar_msg is not None:
            widget = qgis.utils.iface.messageBar().createMessage(returnunicode(bar_msg))
            log_button = QtWidgets.QPushButton(
                tr("MessagebarAndLog", "View message log"),
                pressed=show_message_log,
            )
            if log_msg is not None and button:
                widget.layout().addWidget(log_button)
            qgis.utils.iface.messageBar().pushWidget(
                widget, level=messagebar_level, duration=duration
            )
            # This part can be used to push message to an additional messagebar, but dialogs closes after the timer
            if hasattr(qgis.utils.iface, "optional_bar"):
                try:
                    qgis.utils.iface.optional_bar.pushWidget(
                        widget, level=messagebar_level, duration=duration
                    )
                except Exception:
                    QgsApplication.messageLog().logMessage(
                        traceback.format_exc(), "Midvatten", level=Qgis.Info
                    )
        QgsApplication.messageLog().logMessage(
            returnunicode(bar_msg), "Midvatten", level=log_level
        )
        if log_msg is not None:
            QgsApplication.messageLog().logMessage(
                returnunicode(log_msg), "Midvatten", level=log_level
            )

    @staticmethod
    def info(
        bar_msg: Optional[str] = None,
        log_msg: Optional[str] = None,
        duration: int = 10,
        button: bool = True,
    ):
        MessagebarAndLog.log(bar_msg, log_msg, duration, Qgis.Info, Qgis.Info, button)

    @staticmethod
    def warning(
        bar_msg: Optional[str] = None,
        log_msg: Optional[str] = None,
        duration: int = 10,
        button: bool = True,
    ):
        MessagebarAndLog.log(
            bar_msg, log_msg, duration, Qgis.Warning, Qgis.Warning, button
        )

    @staticmethod
    def critical(
        bar_msg: Optional[str] = None,
        log_msg: Optional[str] = None,
        duration: int = 10,
        button: bool = True,
    ):
        MessagebarAndLog.log(
            bar_msg, log_msg, duration, Qgis.Critical, Qgis.Critical, button
        )


def pop_up_info(msg="", title=tr("pop_up_info", "Information"), parent=None):
    """Display an info message via Qt box"""
    QtWidgets.QMessageBox.information(parent, title, "%s" % (msg))


def sql_failed_msg() -> str:
    return tr("sql_failed_msg", "Sql failed, see log message panel.")
