"""
Dialog classes for creating new Midvatten databases.
Replaces the sequential dialog pattern with unified single dialogs.
"""

import locale as locale_module

from qgis.PyQt.QtCore import QCoreApplication, QLocale
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from midvatten.tools.utils.common_utils import format_timezone_string
from midvatten.tools.utils.date_utils import get_pytz_timezones


def _locale_options() -> list:
    locales = [
        QLocale(QLocale.Swedish, QLocale.Sweden),
        QLocale(QLocale.English, QLocale.UnitedStates),
    ]
    names = [loc.name() for loc in locales]
    sys_locale = locale_module.getlocale()[0]
    if sys_locale:
        names.append(sys_locale)
    return sorted(set(names))


def _logger_tz_options() -> list:
    return [""] + [format_timezone_string(h) for h in range(-12, 15)]


def _levels_tz_options() -> list:
    return [""] + list(get_pytz_timezones())


class NewSpatialiteDbDialog(QDialog):
    """Single dialog collecting all settings for a new SpatiaLite database."""

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setWindowTitle(
            QCoreApplication.translate(
                "NewDb", "Create new Midvatten SpatiaLite database"
            )
        )
        self._build_ui()
        self._connect_signals()
        sys_locale = locale_module.getlocale()[0] or ""
        initial = "sv_SE" if sys_locale.lower().startswith("sv") else "en_US"
        idx = self._locale_combo.findText(initial)
        if idx >= 0:
            self._locale_combo.setCurrentIndex(idx)
        self._on_locale_changed(self._locale_combo.currentText())

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._locale_combo = QComboBox()
        self._locale_combo.addItems(_locale_options())
        form.addRow(QCoreApplication.translate("NewDb", "Locale:"), self._locale_combo)

        self._epsg_spin = QSpinBox()
        self._epsg_spin.setRange(1, 999999)
        self._epsg_spin.setValue(4326)
        form.addRow(QCoreApplication.translate("NewDb", "EPSG code:"), self._epsg_spin)

        self._logger_tz_combo = QComboBox()
        self._logger_tz_combo.addItems(_logger_tz_options())
        form.addRow(
            QCoreApplication.translate("NewDb", "Logger timezone (w_levels_logger):"),
            self._logger_tz_combo,
        )

        self._levels_tz_combo = QComboBox()
        self._levels_tz_combo.addItems(_levels_tz_options())
        form.addRow(
            QCoreApplication.translate("NewDb", "Levels timezone (w_levels):"),
            self._levels_tz_combo,
        )

        path_row = QHBoxLayout()
        self._path_edit = QLineEdit("midv_obsdb.sqlite")
        self._browse_btn = QPushButton(
            QCoreApplication.translate("NewDb", "Browse\u2026")
        )
        path_row.addWidget(self._path_edit)
        path_row.addWidget(self._browse_btn)
        path_widget = QWidget()
        path_widget.setLayout(path_row)
        form.addRow(QCoreApplication.translate("NewDb", "Database path:"), path_widget)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _connect_signals(self) -> None:
        self._locale_combo.currentTextChanged.connect(self._on_locale_changed)
        self._browse_btn.clicked.connect(self._browse_path)

    def _on_locale_changed(self, locale_str: str) -> None:
        if locale_str.lower() == "sv_se":
            self._epsg_spin.setValue(3006)
            idx = self._logger_tz_combo.findText("UTC+1")
            if idx >= 0:
                self._logger_tz_combo.setCurrentIndex(idx)
            idx = self._levels_tz_combo.findText("Europe/Stockholm")
            if idx >= 0:
                self._levels_tz_combo.setCurrentIndex(idx)
        else:
            self._epsg_spin.setValue(4326)
            self._logger_tz_combo.setCurrentIndex(0)
            self._levels_tz_combo.setCurrentIndex(0)

    def _browse_path(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            QCoreApplication.translate("NewDb", "New DB"),
            self._path_edit.text() or "midv_obsdb.sqlite",
            "Spatialite (*.sqlite)",
        )
        if path:
            self._path_edit.setText(path)

    @property
    def locale(self) -> str:
        return self._locale_combo.currentText()

    @property
    def epsg_code(self) -> int:
        return self._epsg_spin.value()

    @property
    def w_levels_logger_timezone(self) -> str:
        return self._logger_tz_combo.currentText()

    @property
    def w_levels_timezone(self) -> str:
        return self._levels_tz_combo.currentText()

    @property
    def dbpath(self) -> str:
        return self._path_edit.text()


class NewPostgisDbDialog(QDialog):
    """Single dialog collecting all settings for a new PostGIS database."""

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setWindowTitle(
            QCoreApplication.translate("NewDb", "Create new Midvatten PostGIS database")
        )
        self._build_ui()
        self._connect_signals()
        sys_locale = locale_module.getlocale()[0] or ""
        initial = "sv_SE" if sys_locale.lower().startswith("sv") else "en_US"
        idx = self._locale_combo.findText(initial)
        if idx >= 0:
            self._locale_combo.setCurrentIndex(idx)
        self._on_locale_changed(self._locale_combo.currentText())

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._locale_combo = QComboBox()
        self._locale_combo.addItems(_locale_options())
        form.addRow(QCoreApplication.translate("NewDb", "Locale:"), self._locale_combo)

        self._epsg_spin = QSpinBox()
        self._epsg_spin.setRange(1, 999999)
        self._epsg_spin.setValue(4326)
        form.addRow(QCoreApplication.translate("NewDb", "EPSG code:"), self._epsg_spin)

        self._logger_tz_combo = QComboBox()
        self._logger_tz_combo.addItems(_logger_tz_options())
        form.addRow(
            QCoreApplication.translate("NewDb", "Logger timezone (w_levels_logger):"),
            self._logger_tz_combo,
        )

        self._levels_tz_combo = QComboBox()
        self._levels_tz_combo.addItems(_levels_tz_options())
        form.addRow(
            QCoreApplication.translate("NewDb", "Levels timezone (w_levels):"),
            self._levels_tz_combo,
        )

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _connect_signals(self) -> None:
        self._locale_combo.currentTextChanged.connect(self._on_locale_changed)

    def _on_locale_changed(self, locale_str: str) -> None:
        if locale_str.lower() == "sv_se":
            self._epsg_spin.setValue(3006)
            idx = self._logger_tz_combo.findText("UTC+1")
            if idx >= 0:
                self._logger_tz_combo.setCurrentIndex(idx)
            idx = self._levels_tz_combo.findText("Europe/Stockholm")
            if idx >= 0:
                self._levels_tz_combo.setCurrentIndex(idx)
        else:
            self._epsg_spin.setValue(4326)
            self._logger_tz_combo.setCurrentIndex(0)
            self._levels_tz_combo.setCurrentIndex(0)

    @property
    def locale(self) -> str:
        return self._locale_combo.currentText()

    @property
    def epsg_code(self) -> int:
        return self._epsg_spin.value()

    @property
    def w_levels_logger_timezone(self) -> str:
        return self._logger_tz_combo.currentText()

    @property
    def w_levels_timezone(self) -> str:
        return self._levels_tz_combo.currentText()
