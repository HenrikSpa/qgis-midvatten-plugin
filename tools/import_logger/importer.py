"""
LoggerImport Qt dialog for unified DiverOffice, Levelogger, and HOBO imports.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime as _datetime

import qgis.core
import qgis.PyQt
import qgis.PyQt.QtWidgets as QtWidgets
from qgis.PyQt.QtCore import QCoreApplication, QEventLoop, Qt, QThread

from midvatten.tools import import_data_to_db
from midvatten.tools.base_importer import BaseImporter
from midvatten.tools.utils import (
    common_utils,
    db_utils,
    dialog_utils,
    file_utils,
    message_utils,
    midvatten_utils,
)
from midvatten.tools.utils.common_utils import format_timezone_string
from midvatten.tools.utils.exceptions import UserInterruptError
from midvatten.tools.utils.file_utils import ui_path
from midvatten.tools.utils.gui_utils import (
    DateTimeFilter,
    RowEntry,
    VRowEntry,
    get_line,
    set_combobox,
)
from midvatten.tools.utils.string_utils import returnunicode as ru

from .parsers import (
    _BARO_METEO_PARAMS,
    TzConverter,
    _pivot_baro_to_meteo,
    filter_dates_from_filedata,
)
from .workers import (
    LoggerDbImportRequest,
    LoggerDbImportResult,
    LoggerFileFailure,
    LoggerParseBatchResult,
    LoggerDbImportWorker,
    LoggerParseRequest,
    LoggerParseWorker,
    LoggerSeriesSpec,
    LoggerWorker,
)

import_ui_dialog = qgis.PyQt.uic.loadUiType(ui_path("import_fieldlogger.ui"))[0]


@dataclass
class LoggerImportSummary:
    imported: list[str] = field(default_factory=list)
    no_new_rows: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    parse_failures: list[LoggerFileFailure] = field(default_factory=list)
    database_failures: list[LoggerFileFailure] = field(default_factory=list)


class CheckboxAndExplanation(VRowEntry):
    """A checkbox widget with an optional explanatory label below it."""

    def __init__(self, checkbox_label, explanation=None):
        super().__init__()
        self.checkbox = QtWidgets.QCheckBox(checkbox_label)
        self.layout().addWidget(self.checkbox)
        self.label = QtWidgets.QLabel()

        if explanation:
            self.label.setText(explanation)
            self.layout().addWidget(self.label)

    @property
    def checked(self):
        return self.checkbox.isChecked()

    @checked.setter
    def checked(self, check=True):
        self.checkbox.setChecked(check)


# ── Dialog class ──────────────────────────────────────────────────────────────


class LoggerImport(BaseImporter, import_ui_dialog):
    """Unified logger data importer for DiverOffice, Levelogger, and HOBO formats.

    Replaces DiverofficeImport, LeveloggerImport, and HobologgerImport with a
    single dialog that includes a format selector and shows format-specific help
    text inline (instead of the pre-import wall-of-text Askuser dialogs).
    """

    FORMAT_DIVEROFFICE = "DiverOffice"
    FORMAT_DIVEROFFICE_BARO = "DiverOffice Baro"
    FORMAT_LEVELOGGER = "Levelogger"
    FORMAT_HOBO = "Hobo"

    _FORMAT_EXTENSIONS = {
        FORMAT_DIVEROFFICE: frozenset((".csv", ".mon")),
        FORMAT_DIVEROFFICE_BARO: frozenset((".csv", ".mon")),
        FORMAT_LEVELOGGER: frozenset((".csv",)),
        FORMAT_HOBO: frozenset((".csv",)),
    }

    def __init__(self, iface, ms):
        self.files = []
        # BaseImporter.__init__(iface, ms) calls QMainWindow.__init__(self, iface.mainWindow())
        # internally and sets self.iface = iface, self.ms = ms, self.status = True.
        super().__init__(iface, ms)
        self.setWindowTitle(QCoreApplication.translate("LoggerImport", "Logger import"))
        # Do NOT call load_gui() here — widgets are built lazily in show().
        # Tests call load_gui() directly to avoid opening a real window.

    def show(self) -> None:
        """Entry point called by the plugin dispatcher — builds widgets then shows."""
        self.load_gui()
        super().show()
        self.activateWindow()

    # ── GUI construction ─────────────────────────────────────────────────────

    def load_gui(self) -> None:
        # Format selector — in left panel for a top-to-bottom workflow
        format_label = QtWidgets.QLabel(
            QCoreApplication.translate("LoggerImport", "Logger format:")
        )
        self.format_combo = QtWidgets.QComboBox()
        self.format_combo.addItems(
            [
                self.FORMAT_DIVEROFFICE,
                self.FORMAT_DIVEROFFICE_BARO,
                self.FORMAT_LEVELOGGER,
                self.FORMAT_HOBO,
            ]
        )
        self.grid_layout_buttons.addWidget(format_label, 0, 0)
        self.grid_layout_buttons.addWidget(self.format_combo, 1, 0)
        self.grid_layout_buttons.addWidget(get_line(), 2, 0)

        # Format description — stays in right panel as reference text
        self._format_description_label = QtWidgets.QLabel()
        self._format_description_label.setWordWrap(True)
        self.add_row(self._format_description_label)

        self.add_row(get_line())

        # Date/time filter (all formats)
        self.date_time_filter = DateTimeFilter(calendar=True)
        self.add_row(self.date_time_filter)

        # Format-specific sections (each builds a container widget shown/hidden by _on_format_changed)
        _db_tz = db_utils.get_timezone_from_db("w_levels_logger")
        self._build_diveroffice_section(_db_tz)
        self._build_diveroffice_baro_section(_db_tz)
        self._build_levelogger_section()
        self._build_hobo_section()

        self.add_row(get_line())

        # skip_rows + its separator line, grouped so both can be shown/hidden together
        self._skip_rows_container = QtWidgets.QWidget()
        _vl = QtWidgets.QVBoxLayout(self._skip_rows_container)
        _vl.setContentsMargins(0, 0, 0, 0)
        self.skip_rows = CheckboxAndExplanation(
            QCoreApplication.translate("LoggerImport", "Skip rows without water level"),
            QCoreApplication.translate(
                "LoggerImport",
                "Checked = Rows without a value for columns Water head[cm] or Level[cm] will be skipped.",
            ),
        )
        self.skip_rows.checked = True
        _vl.addWidget(self.skip_rows)
        _vl.addWidget(get_line())
        self.add_row(self._skip_rows_container)

        # confirm_names
        self.confirm_names = CheckboxAndExplanation(
            QCoreApplication.translate(
                "LoggerImport", "Confirm each logger obsid before import"
            ),
            QCoreApplication.translate(
                "LoggerImport",
                "Checked = The obsid will be requested of the user for every file.\n\n"
                "Unchecked = the location attribute, both as is and capitalized, in the\n"
                "file will be matched against obsids in the database.\n\n"
                "In both cases, obsid will be requested of the user if no match in the "
                "database is found.",
            ),
        )
        self.confirm_names.checked = True
        self.add_row(self.confirm_names)
        self.add_row(get_line())

        # import_all_data
        self.import_all_data = CheckboxAndExplanation(
            QCoreApplication.translate("LoggerImport", "Import all data"),
            QCoreApplication.translate(
                "LoggerImport",
                "Checked = any data not matching an exact datetime in the database\n"
                "for the corresponding obsid will be imported.\n\n"
                "Unchecked = only new data after the latest date in the database,\n"
                "for each observation point, will be imported.",
            ),
        )
        self.import_all_data.checked = False
        self.add_row(self.import_all_data)

        # Optional source comment
        existing_columns = db_utils.tables_columns(table="w_levels_logger")[
            "w_levels_logger"
        ]
        series_table = db_utils.tables_columns(table="w_logger_series").get(
            "w_logger_series"
        )
        # Show source edit for:
        #   - Old/current schema: column w_levels_logger.source
        #   - New schema: w_logger_series table exists; source lives on the series row
        if "source" in existing_columns or series_table:
            self.add_row(get_line())
            self.source_row = RowEntry()
            self.source_label = QtWidgets.QLabel(
                QCoreApplication.translate(
                    "LoggerImport", "Add source comment (optional)"
                )
            )
            self.source_edit = QtWidgets.QLineEdit()
            self.source_row.layout().addWidget(self.source_label)
            self.source_row.layout().addWidget(self.source_edit)
            self.add_row(self.source_row)
        else:
            self.source_edit = None

        # Buttons
        self.select_files_button = QtWidgets.QPushButton(
            QCoreApplication.translate("LoggerImport", "Select files")
        )
        self.grid_layout_buttons.addWidget(self.select_files_button, 3, 0)
        self.select_files_button.clicked.connect(lambda: self.select_files())

        self._files_label = QtWidgets.QLabel(
            QCoreApplication.translate("LoggerImport", "No files selected")
        )
        self.grid_layout_buttons.addWidget(self._files_label, 4, 0)

        self.close_after_import = QtWidgets.QCheckBox(
            QCoreApplication.translate("LoggerImport", "Close dialog after import")
        )
        self.close_after_import.setChecked(True)
        self.grid_layout_buttons.addWidget(self.close_after_import, 5, 0)

        self.start_import_button = QtWidgets.QPushButton(
            QCoreApplication.translate("LoggerImport", "Start import")
        )
        self.grid_layout_buttons.addWidget(self.start_import_button, 6, 0)
        self.start_import_button.clicked.connect(
            lambda: self.start_import(
                files=self.files,
                skip_rows_without_water_level=self.skip_rows.checked,
                confirm_names=self.confirm_names.checked,
                import_all_data=self.import_all_data.checked,
                from_date=self.date_time_filter.from_date,
                to_date=self.date_time_filter.to_date,
                export_csv=False,
                import_to_db=True,
            )
        )
        self.start_import_button.setEnabled(False)

        self.export_csv_button = QtWidgets.QPushButton(
            QCoreApplication.translate("LoggerImport", "Export csv")
        )
        self.grid_layout_buttons.addWidget(self.export_csv_button, 7, 0)
        self.export_csv_button.clicked.connect(
            lambda: self.start_import(
                files=self.files,
                skip_rows_without_water_level=self.skip_rows.checked,
                confirm_names=self.confirm_names.checked,
                import_all_data=self.import_all_data.checked,
                from_date=self.date_time_filter.from_date,
                to_date=self.date_time_filter.to_date,
                export_csv=True,
                import_to_db=False,
            )
        )
        self.export_csv_button.setEnabled(False)

        self.grid_layout_buttons.setRowStretch(8, 1)
        self.main_vertical_layout.addStretch()
        self.setGeometry(500, 150, 1200, 700)

        # Build static per-format lookup tables once (QCoreApplication.translate needs
        # a running Qt app, so these can't be class-level constants).
        self._format_descriptions = {
            self.FORMAT_DIVEROFFICE: QCoreApplication.translate(
                "LoggerImport",
                "DiverOffice format: semicolon or comma separated.\n"
                "Data header must contain 'Date/time' and at least one of:\n"
                "Water head[cm], Temperature[°C], Level[cm], Conductivity[mS/cm].\n"
                "Column names matter; column order does not.",
            ),
            self.FORMAT_DIVEROFFICE_BARO: QCoreApplication.translate(
                "LoggerImport",
                "DiverOffice Baro format: same file format as DiverOffice.\n"
                "Imports Pressure[cmH2O] and Temperature[°C] into the meteo table.\n"
                "The instrument serial number is used as instrumentid.\n"
                "Column names matter; column order does not.",
            ),
            self.FORMAT_LEVELOGGER: QCoreApplication.translate(
                "LoggerImport",
                "Levelogger format: CSV exported from the Levelogger data wizard.\n"
                "Header must contain 'Date', 'Time', and at least one of:\n"
                "LEVEL, TEMPERATURE, spec. conductivity.\n"
                "LEVEL unit (cm or m) is read from the row after 'LEVEL'.",
            ),
            self.FORMAT_HOBO: QCoreApplication.translate(
                "LoggerImport",
                "Hobo format: UTF-8 CSV from HOBO logger.\n"
                'First row: "Plot Title: <name>"\n'
                'Second row: "#","Date Time, GMT+HH:MM","Temp, °C (...LBL: obsid)"\n'
                "obsid is read from the LBL tag in the temperature column header.",
            ),
        }
        self._format_titles = {
            self.FORMAT_DIVEROFFICE: QCoreApplication.translate(
                "LoggerImport", "Logger import — DiverOffice"
            ),
            self.FORMAT_DIVEROFFICE_BARO: QCoreApplication.translate(
                "LoggerImport", "Logger import — DiverOffice Baro"
            ),
            self.FORMAT_LEVELOGGER: QCoreApplication.translate(
                "LoggerImport", "Logger import — Levelogger"
            ),
            self.FORMAT_HOBO: QCoreApplication.translate(
                "LoggerImport", "Logger import — Hobo"
            ),
        }

        # Wire format change AFTER all widgets are built
        self.format_combo.currentTextChanged.connect(self._on_format_changed)
        self._on_format_changed(self.format_combo.currentText())

    def _build_diveroffice_section(self, database_timezone: str | None = None) -> None:
        """Build DiverOffice-specific section (UTC offset control). Hidden for other formats."""
        self._diveroffice_section = QtWidgets.QWidget()
        _vl = QtWidgets.QVBoxLayout(self._diveroffice_section)
        _vl.setContentsMargins(0, 0, 0, 0)

        self.utcoffset_label = QtWidgets.QLabel(
            QCoreApplication.translate(
                "LoggerImport", "Identify and change UTC offset:"
            )
        )
        self.utc_offset = QtWidgets.QComboBox()
        self.utc_offset.setToolTip(
            QCoreApplication.translate(
                "LoggerImport",
                "Identifies UTC-offset in file and changes to the selected one.",
            )
        )
        self.utc_offset.addItem("")
        self.utc_offset.addItems(
            [format_timezone_string(hour) for hour in range(-12, 15)]
        )
        if database_timezone is not None:
            set_combobox(self.utc_offset, database_timezone, add_if_not_exists=False)
        self.utcoffset_row = RowEntry()
        self.utcoffset_row.layout().addWidget(self.utcoffset_label)
        self.utcoffset_row.layout().addWidget(self.utc_offset)
        _vl.addWidget(self.utcoffset_row)

        self.add_row(self._diveroffice_section)

    def _build_diveroffice_baro_section(
        self, database_timezone: str | None = None
    ) -> None:
        """Build DiverOffice Baro section (UTC offset control). Imports to meteo table."""
        self._diveroffice_baro_section = QtWidgets.QWidget()
        _vl = QtWidgets.QVBoxLayout(self._diveroffice_baro_section)
        _vl.setContentsMargins(0, 0, 0, 0)

        baro_utcoffset_label = QtWidgets.QLabel(
            QCoreApplication.translate(
                "LoggerImport", "Identify and change UTC offset:"
            )
        )
        self.baro_utc_offset = QtWidgets.QComboBox()
        self.baro_utc_offset.setToolTip(
            QCoreApplication.translate(
                "LoggerImport",
                "Identifies UTC-offset in file and changes to the selected one.",
            )
        )
        self.baro_utc_offset.addItem("")
        self.baro_utc_offset.addItems(
            [format_timezone_string(hour) for hour in range(-12, 15)]
        )
        if database_timezone is not None:
            set_combobox(
                self.baro_utc_offset, database_timezone, add_if_not_exists=False
            )
        baro_utcoffset_row = RowEntry()
        baro_utcoffset_row.layout().addWidget(baro_utcoffset_label)
        baro_utcoffset_row.layout().addWidget(self.baro_utc_offset)
        _vl.addWidget(baro_utcoffset_row)

        self.add_row(self._diveroffice_baro_section)

    def _build_levelogger_section(self) -> None:
        """Build Levelogger-specific section (no extra controls needed)."""
        self._levelogger_section = QtWidgets.QWidget()
        self.add_row(self._levelogger_section)

    def _build_hobo_section(self) -> None:
        """Build Hobo-specific section (TzConverter control). Hidden for other formats."""
        self._hobo_section = QtWidgets.QWidget()
        _vl = QtWidgets.QVBoxLayout(self._hobo_section)
        _vl.setContentsMargins(0, 0, 0, 0)

        self.tz_converter = TzConverter()
        _vl.addWidget(self.tz_converter)
        self.add_row(self._hobo_section)

    def _on_format_changed(self, format_name: str) -> None:
        """Show/hide format-specific widgets and update window title."""
        is_diveroffice = format_name == self.FORMAT_DIVEROFFICE
        is_baro = format_name == self.FORMAT_DIVEROFFICE_BARO
        is_hobo = format_name == self.FORMAT_HOBO

        self._diveroffice_section.setVisible(is_diveroffice)
        self._diveroffice_baro_section.setVisible(is_baro)
        self._levelogger_section.setVisible(format_name == self.FORMAT_LEVELOGGER)
        self._hobo_section.setVisible(is_hobo)

        # skip_rows only applies to water-level formats, not baro or hobo
        show_skip_rows = format_name in (
            self.FORMAT_DIVEROFFICE,
            self.FORMAT_LEVELOGGER,
        )
        self._skip_rows_container.setVisible(show_skip_rows)
        self.skip_rows.checked = show_skip_rows

        self._format_description_label.setText(
            self._format_descriptions.get(format_name, "")
        )
        self.setWindowTitle(self._format_titles.get(format_name, "Logger import"))

        accepted = self._FORMAT_EXTENSIONS.get(format_name, frozenset())
        files_compatible = self.files and all(
            os.path.splitext(f)[1].lower() in accepted for f in self.files
        )
        if not files_compatible:
            self.files = []
            self._files_label.setText(
                QCoreApplication.translate("LoggerImport", "No files selected")
            )
            self.start_import_button.setEnabled(False)
            self.export_csv_button.setEnabled(False)

    # ── File selection ───────────────────────────────────────────────────────

    @common_utils.general_exception_handler
    def select_files(self) -> None:
        """Open file picker. Encoding is handled automatically in start_import()."""
        format_name = self.format_combo.currentText()
        exts = sorted(self._FORMAT_EXTENSIONS.get(format_name, frozenset((".csv",))))
        if len(exts) > 1:
            combined = " ".join(f"*{e}" for e in exts)
            parts = [f"All supported ({combined})"]
            parts.extend(f"{e.lstrip('.')} (*{e})" for e in exts)
            extension = ";;".join(parts)
        else:
            extension = f"{exts[0].lstrip('.')} (*{exts[0]})"
        files = midvatten_utils.select_files(only_one_file=False, extension=extension)
        if not files:
            raise UserInterruptError()

        self.files = files
        self._files_label.setText(
            QCoreApplication.translate("LoggerImport", "%d file(s) selected")
            % len(files)
        )
        self.start_import_button.setEnabled(True)
        self.export_csv_button.setEnabled(True)

    # ── Import logic ─────────────────────────────────────────────────────────

    def _run_worker(self, worker: LoggerWorker, progress: QtWidgets.QProgressDialog):
        """Run a logger worker while a nested event loop keeps QGIS responsive."""
        thread = QThread(self)
        loop = QEventLoop(self)
        outcome = {"result": None, "error": None, "cancelled": False}

        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        def on_finished(result) -> None:
            outcome["result"] = result
            loop.quit()

        def on_error(error: str) -> None:
            outcome["error"] = error
            loop.quit()

        def on_cancelled() -> None:
            outcome["cancelled"] = True
            loop.quit()

        def cancel_worker() -> None:
            progress.setLabelText(
                QCoreApplication.translate("LoggerImport", "Cancelling...")
            )
            worker.cancel()

        worker.progress.connect(progress.setLabelText)
        worker.finished.connect(on_finished)
        worker.error.connect(on_error)
        worker.cancelled.connect(on_cancelled)
        for terminal_signal in (
            worker.finished,
            worker.error,
            worker.cancelled,
        ):
            terminal_signal.connect(worker.deleteLater)
            terminal_signal.connect(thread.quit, Qt.DirectConnection)
        progress.canceled.connect(cancel_worker)

        try:
            thread.start()
            loop.exec_()
            thread.wait()
            thread.deleteLater()
        finally:
            try:
                progress.canceled.disconnect(cancel_worker)
            except TypeError:
                pass

        if outcome["error"] is not None:
            raise RuntimeError(outcome["error"])
        if outcome["cancelled"]:
            raise UserInterruptError()
        return outcome["result"]

    def _run_parse_worker(
        self, request: LoggerParseRequest, progress: QtWidgets.QProgressDialog
    ) -> LoggerParseBatchResult:
        return self._run_worker(
            LoggerParseWorker(request), progress
        ) or LoggerParseBatchResult([], [])

    def _run_db_worker(
        self,
        request: LoggerDbImportRequest,
        progress: QtWidgets.QProgressDialog,
    ) -> LoggerDbImportResult:
        db_settings = self.ms.settingsdict.get("database")
        if not db_settings:
            db_settings = qgis.core.QgsProject.instance().readEntry(
                "Midvatten", "database"
            )[0]
        worker = LoggerDbImportWorker(db_settings, request)
        return self._run_worker(worker, progress)

    def _report_import_summary(self, summary: LoggerImportSummary) -> None:
        failed_count = (
            len(summary.no_new_rows)
            + len(summary.skipped)
            + len(summary.parse_failures)
            + len(summary.database_failures)
        )
        bar_message = QCoreApplication.translate(
            "LoggerImport",
            "Logger import complete: %s imported, %s skipped or failed.",
        ) % (len(summary.imported), failed_count)
        detail_lines = [f"Imported: {name}" for name in summary.imported]
        detail_lines.extend(f"No new rows: {name}" for name in summary.no_new_rows)
        detail_lines.extend(f"Skipped: {name}" for name in summary.skipped)
        detail_lines.extend(
            f"Parse failure: {failure.filename}: {failure.reason}"
            for failure in summary.parse_failures
        )
        detail_lines.extend(
            f"Database failure: {failure.filename}: {failure.reason}"
            for failure in summary.database_failures
        )
        reporter = (
            message_utils.MessagebarAndLog.info
            if summary.imported
            else message_utils.MessagebarAndLog.warning
        )
        reporter(bar_msg=bar_message, log_msg="\n".join(detail_lines))

    @common_utils.general_exception_handler
    @import_data_to_db.import_exception_handler
    def start_import(
        self,
        files,
        skip_rows_without_water_level,
        confirm_names,
        import_all_data,
        from_date=None,
        to_date=None,
        export_csv=False,
        import_to_db=True,
    ):
        common_utils.start_waiting_cursor()

        progress = QtWidgets.QProgressDialog(
            QCoreApplication.translate("LoggerImport", "Importing logger data..."),
            QCoreApplication.translate("LoggerImport", "Cancel"),
            0,
            0,
            self,
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        format_name = self.format_combo.currentText()
        utc_widget = (
            self.baro_utc_offset
            if format_name == self.FORMAT_DIVEROFFICE_BARO
            else self.utc_offset
        )
        parse_request = LoggerParseRequest(
            files=tuple(files),
            format_name=format_name,
            skip_rows_without_water_level=skip_rows_without_water_level,
            from_date=from_date,
            to_date=to_date,
            requested_utc_offset=utc_widget.currentText(),
            hobo_target_timezone=self.tz_converter.target_tz,
        )
        parsed_files = []

        try:
            parse_batch = self._run_parse_worker(parse_request, progress)
            summary = LoggerImportSummary(parse_failures=list(parse_batch.failures))
            for failure in summary.parse_failures:
                message_utils.MessagebarAndLog.warning(
                    log_msg=QCoreApplication.translate(
                        "LoggerImport", "%s failed during %s: %s"
                    )
                    % (failure.filename, failure.stage, failure.reason)
                )
            for parsed in parse_batch.parsed_files:
                if parsed.timezone_error:
                    msg = QCoreApplication.translate(
                        "LoggerImport",
                        "Reading timezone in file %s failed,\n"
                        " no conversion done:\n%s\n\nSkip file?",
                    ) % (ru(parsed.filename), parsed.timezone_error)
                    common_utils.stop_waiting_cursor()
                    question = dialog_utils.Askuser(
                        question="YesNo",
                        msg=msg,
                        dialogtitle=QCoreApplication.translate(
                            "askuser", "File timezone error!"
                        ),
                        include_cancel_button=True,
                    )
                    common_utils.start_waiting_cursor()
                    if question.result:
                        summary.skipped.append(parsed.filename)
                        continue
                parsed_files.append(
                    (
                        parsed.file_data,
                        parsed.filename,
                        parsed.location,
                        parsed.serial_number,
                    )
                )

            if len(parsed_files) == 0:
                self._report_import_summary(summary)
                message_utils.MessagebarAndLog.critical(
                    bar_msg=QCoreApplication.translate(
                        "LoggerImport", "Import Failure: No files imported"
                    )
                )
                common_utils.stop_waiting_cursor()
                return

            # Add obsid to all parsed filedatas by asking the user for it.
            filename_location_obsid = [["filename", "location", "obsid"]]
            filename_location_obsid.extend(
                [
                    [parsed_file[1], parsed_file[2], parsed_file[2]]
                    for parsed_file in parsed_files
                ]
            )

            try_capitalize = not confirm_names

            existing_obsids = db_utils.get_all_obsids()
            common_utils.stop_waiting_cursor()
            filename_location_obsid = common_utils.filter_nonexisting_values_and_ask(
                file_data=filename_location_obsid,
                header_value="obsid",
                existing_values=existing_obsids,
                try_capitalize=try_capitalize,
                always_ask_user=confirm_names,
            )
            common_utils.start_waiting_cursor()

            if len(filename_location_obsid) < 2:
                summary.skipped.extend(parsed_file[1] for parsed_file in parsed_files)
                self._report_import_summary(summary)
                message_utils.MessagebarAndLog.warning(
                    bar_msg=QCoreApplication.translate(
                        "LoggerImport",
                        "Warning. All files were skipped, nothing imported!",
                    )
                )
                common_utils.stop_waiting_cursor()
                return False

            filenames_obsid = {x[0]: x[2] for x in filename_location_obsid[1:]}

            parsed_files_with_obsid = []
            for file_data, filename, location, serial_number in parsed_files:
                if not file_data:
                    summary.skipped.append(filename)
                    message_utils.MessagebarAndLog.warning(
                        bar_msg=QCoreApplication.translate(
                            "LoggerImport",
                            "Diveroffice import warning. See log message panel",
                        ),
                        log_msg=QCoreApplication.translate(
                            "LoggerImport",
                            "No data parsed from file %s. Remove rows without the correct number of columns.",
                        )
                        % filename,
                    )
                    continue

                if filename in filenames_obsid:
                    file_data = list(file_data)
                    obsid = filenames_obsid[filename]
                    file_data[0].append("obsid")
                    for row in file_data[1:]:
                        row.append(obsid)
                    parsed_files_with_obsid.append(
                        [file_data, filename, location, serial_number]
                    )

            if not parsed_files_with_obsid:
                self._report_import_summary(summary)
                message_utils.MessagebarAndLog.warning(
                    bar_msg=QCoreApplication.translate(
                        "LoggerImport",
                        "Warning. All files were skipped, nothing imported!",
                    )
                )
                common_utils.stop_waiting_cursor()
                return False

            # ── DiverOffice Baro path: pivot to meteo long format and import ────────
            if format_name == self.FORMAT_DIVEROFFICE_BARO:
                if import_to_db:
                    dbconn = db_utils.DbConnectionManager()
                    try:
                        ph = dbconn.placeholder()
                        with dbconn.transaction():
                            for param, explanation in _BARO_METEO_PARAMS:
                                existing = dbconn.execute_and_fetchall(
                                    f"SELECT parameter FROM zz_meteoparam WHERE parameter = {ph}",
                                    (param,),
                                )
                                if not existing:
                                    dbconn.execute(
                                        f"INSERT INTO zz_meteoparam(parameter, explanation)"
                                        f" VALUES ({ph}, {ph})",
                                        (param, explanation),
                                    )
                    finally:
                        dbconn.closedb()

                exported_rows: list[list] = []
                for (
                    file_data,
                    filename,
                    _location,
                    serial_number,
                ) in parsed_files_with_obsid:
                    meteo_rows = _pivot_baro_to_meteo(
                        file_data, serial_number, filename
                    )
                    if len(meteo_rows) < 2:
                        summary.no_new_rows.append(filename)
                        continue
                    if not exported_rows:
                        exported_rows = [list(row) for row in meteo_rows]
                    else:
                        exported_rows.extend([list(row) for row in meteo_rows[1:]])

                    if import_to_db:
                        result = self._run_db_worker(
                            LoggerDbImportRequest(
                                filename=filename,
                                dest_table="meteo",
                                file_data=meteo_rows,
                            ),
                            progress,
                        )
                        if result.imported:
                            summary.imported.append(filename)
                        else:
                            summary.database_failures.append(
                                LoggerFileFailure(
                                    filename,
                                    "database",
                                    result.reason or "import failed",
                                )
                            )
                    elif export_csv:
                        summary.imported.append(filename)

                if export_csv:
                    path = QtWidgets.QFileDialog.getSaveFileName(
                        self, "Save File", "", "CSV(*.csv)"
                    )
                    if path:
                        path = ru(path[0])
                        file_utils.write_printlist_to_file(path, exported_rows)

                self._report_import_summary(summary)
                common_utils.stop_waiting_cursor()
                if self.close_after_import.isChecked():
                    self.close()
                return True

            # ── Water-level path (w_levels_logger) ──────────────────────────────────────────
            # Schema variant detection. In the new schema, source has moved to a
            # w_logger_series row that groups all rows from one imported file.
            # In older schemas, source is still a column on w_levels_logger. We
            # keep supporting both so users don't have to migrate to keep using
            # this importer.
            wlogger_cols = db_utils.tables_columns(table="w_levels_logger").get(
                "w_levels_logger", []
            )
            has_series_id = "series_id" in wlogger_cols
            has_created_at = "created_at" in wlogger_cols
            has_source_column = "source" in wlogger_cols

            source_text = (
                self.source_edit.text().strip() if self.source_edit is not None else ""
            )

            if not import_all_data:
                # This snapshot belongs to the whole selected batch. Never
                # recalculate it after an earlier file has committed.
                last_dates = db_utils.get_last_logger_dates()
                filtered_files = []
                for parsed_file in parsed_files_with_obsid:
                    parsed_file[0] = filter_dates_from_filedata(
                        parsed_file[0], last_dates
                    )
                    if len(parsed_file[0]) > 1:
                        filtered_files.append(parsed_file)
                    else:
                        summary.no_new_rows.append(parsed_file[1])
                parsed_files_with_obsid = filtered_files

            if not parsed_files_with_obsid:
                self._report_import_summary(summary)
                message_utils.MessagebarAndLog.info(
                    bar_msg=QCoreApplication.translate(
                        "LoggerImport",
                        "No new data existed in the files. Nothing imported.",
                    )
                )
                self.status = True
                common_utils.stop_waiting_cursor()
                return True

            batch_created_at = _datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            exported_data: list[list] = []
            for (
                file_data,
                filename,
                _location,
                serial_number,
            ) in parsed_files_with_obsid:
                file_data = [list(row) for row in file_data]

                # Old schemas store source directly on each reading.
                if source_text and has_source_column and not has_series_id:
                    file_data[0].append("source")
                    for row in file_data[1:]:
                        row.append(source_text)

                if not exported_data:
                    exported_data = [list(row) for row in file_data]
                else:
                    exported_data.extend([list(row) for row in file_data[1:]])

                series = None
                if has_series_id:
                    series = LoggerSeriesSpec(
                        obsid=filenames_obsid[filename],
                        source=source_text or None,
                        description=os.path.basename(filename) if filename else None,
                        instrument=serial_number,
                        created_at=batch_created_at if has_created_at else None,
                    )

                if import_to_db:
                    result = self._run_db_worker(
                        LoggerDbImportRequest(
                            filename=filename,
                            dest_table="w_levels_logger",
                            file_data=file_data,
                            series=series,
                        ),
                        progress,
                    )
                    if result.imported:
                        summary.imported.append(filename)
                    elif result.reason == "no non-duplicate rows":
                        summary.no_new_rows.append(filename)
                    else:
                        summary.database_failures.append(
                            LoggerFileFailure(
                                filename,
                                "database",
                                result.reason or "import failed",
                            )
                        )
                elif export_csv:
                    summary.imported.append(filename)

            if export_csv:
                path = QtWidgets.QFileDialog.getSaveFileName(
                    self, "Save File", "", "CSV(*.csv)"
                )
                if path:
                    path = ru(path[0])
                    file_utils.write_printlist_to_file(path, exported_data)

            self._report_import_summary(summary)
            common_utils.stop_waiting_cursor()

            if self.close_after_import.isChecked():
                self.close()
        finally:
            progress.close()
