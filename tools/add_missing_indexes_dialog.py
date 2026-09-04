"""Database-management dialog: add missing normalized-timestamp indexes.

Older (pre-2.0.0) databases can lack the normalized-timestamp index on the
time-series tables, which makes imports to those tables slow. This dialog adds
the non-unique speed-up index to every affected table in one pass, using a long
busy timeout, and recommends taking a backup first (the operation only adds
indexes and never touches rows, but a backup is cheap insurance).
"""

import traceback

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from midvatten.tools import import_data_to_db
from midvatten.tools.utils import common_utils, db_utils, message_utils


def _tr(text: str) -> str:
    return QCoreApplication.translate("AddMissingIndexesDialog", text)


class AddMissingIndexesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_tr("Add missing timestamp indexes"))
        self.backup_done = False

        layout = QVBoxLayout(self)
        info = QLabel(
            _tr(
                "This adds speed-up indexes for imports on the time-series tables "
                "(w_levels, w_flow, comments, meteo, ...). It only adds indexes "
                "and never changes or deletes data.\n\n"
                "It can take a while on a large database, and needs exclusive "
                "access: close any other program or QGIS panel using this "
                "database first. Taking a backup first is recommended."
            )
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.backup_button = QPushButton(_tr("Back up the database now"))
        self.backup_button.clicked.connect(self.run_backup)
        layout.addWidget(self.backup_button)

        buttons = QDialogButtonBox()
        self.add_button = buttons.addButton(
            _tr("Add missing indexes"), QDialogButtonBox.ButtonRole.AcceptRole
        )
        buttons.addButton(QDialogButtonBox.StandardButton.Close)
        self.add_button.clicked.connect(self.run_add_indexes)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def run_backup(self) -> None:
        """Run the standard backup; on success, disable the backup button."""
        try:
            db_utils.backup_db()
        except Exception:
            message_utils.MessagebarAndLog.critical(
                bar_msg=_tr("Backup failed, see log message panel."),
                log_msg=traceback.format_exc(),
            )
            return
        self.backup_done = True
        self.backup_button.setEnabled(False)
        self.backup_button.setText(_tr("Backup created"))
        message_utils.MessagebarAndLog.info(bar_msg=_tr("Database backup created."))

    def run_add_indexes(self) -> None:
        """Build the missing indexes and report the per-table outcome."""
        common_utils.start_waiting_cursor()
        try:
            results = import_data_to_db.add_missing_normalized_datetime_indexes()
        finally:
            common_utils.stop_waiting_cursor()

        created = sorted(t for t, s in results.items() if s == "created")
        exists = sorted(t for t, s in results.items() if s == "exists")
        missing = sorted(t for t, s in results.items() if s == "missing")
        failed = sorted(t for t, s in results.items() if s == "failed")

        log_lines = [
            _tr("Added index: %s") % ", ".join(created) if created else "",
            _tr("Already present: %s") % ", ".join(exists) if exists else "",
            _tr("Not in this database: %s") % ", ".join(missing) if missing else "",
            _tr("Could not be created: %s") % ", ".join(failed) if failed else "",
        ]
        log_msg = "\n".join(line for line in log_lines if line)

        if failed:
            message_utils.MessagebarAndLog.warning(
                bar_msg=_tr(
                    "Some indexes could not be created (the database may still "
                    "be in use). See the log message panel."
                ),
                log_msg=log_msg,
            )
        else:
            message_utils.MessagebarAndLog.info(
                bar_msg=_tr("%s index(es) added, %s already present.")
                % (len(created), len(exists)),
                log_msg=log_msg,
            )
        self.accept()
