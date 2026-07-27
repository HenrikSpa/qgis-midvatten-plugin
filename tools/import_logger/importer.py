"""
LoggerImport Qt dialog for unified DiverOffice, Levelogger, and HOBO imports.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from datetime import datetime as _datetime

import qgis.core
import qgis.PyQt
import qgis.PyQt.QtWidgets as QtWidgets
import pandas as pd
from qgis.PyQt.QtCore import QCoreApplication, QEventLoop, Qt, QThread

from midvatten.tools import import_data_to_db
from midvatten.tools.base_importer import BaseImporter
from midvatten.tools.utils import (
    common_utils,
    date_utils,
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

from .models import (
    BARO_METEO_PARAMS,
    NO_NEW_ROWS_REASON,
    LoggerDataKind,
    LoggerDbImportRequest,
    LoggerDbImportResult,
    LoggerFileFailure,
    LoggerImportOptions,
    LoggerParseBatchResult,
    LoggerParseRequest,
    LoggerSchemaCapabilities,
    LoggerSeriesSpec,
    ParsedLoggerFile,
    PreparedLoggerFile,
)
from .parsers import TzConverter
from .pipeline import (
    InvalidLatestDateError,
    parse_latest_dates,
    run_post_resolution_pipeline,
    write_logger_csv,
)
from .workers import (
    LoggerDbImportWorker,
    LoggerParseWorker,
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


def logger_schema_capabilities(columns: list[str]) -> LoggerSchemaCapabilities:
    """Describe supported logger-table metadata without coupling to a DB version."""
    return LoggerSchemaCapabilities(
        has_series_id="series_id" in columns,
        has_created_at="created_at" in columns,
        has_source_column="source" in columns,
    )


def _parse_gui_date_bound(value, name: str) -> pd.Timestamp | None:
    """Parse one date-filter widget value into a Timestamp.

    This is the GUI's parse boundary. ``pipeline._typed_bound`` is the
    downstream *assertion* boundary and deliberately rejects text.
    """
    if value in (None, ""):
        return None
    if isinstance(value, (pd.Timestamp, _datetime)):
        return pd.Timestamp(value)
    parsed = date_utils.to_date(value)
    if parsed is None:
        raise ValueError(f"Invalid {name}: {value!r}")
    return pd.Timestamp(parsed)


_DESTINATION_TABLES = {
    LoggerDataKind.WATER_LEVEL: "w_levels_logger",
    LoggerDataKind.BAROMETRIC: "meteo",
}


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
        # Section build order determines layout order — DiverOffice first.
        (
            self._diveroffice_section,
            self.utc_offset,
            self.utcoffset_label,
            self.utcoffset_row,
        ) = self._build_utc_offset_section(_db_tz)
        (
            self._diveroffice_baro_section,
            self.baro_utc_offset,
            _baro_label,
            _baro_row,
        ) = self._build_utc_offset_section(_db_tz)
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
            lambda: self._start_import_from_gui(export_csv=False, import_to_db=True)
        )
        self.start_import_button.setEnabled(False)

        self.export_csv_button = QtWidgets.QPushButton(
            QCoreApplication.translate("LoggerImport", "Export csv")
        )
        self.grid_layout_buttons.addWidget(self.export_csv_button, 7, 0)
        self.export_csv_button.clicked.connect(
            lambda: self._start_import_from_gui(export_csv=True, import_to_db=False)
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

    def _build_utc_offset_section(
        self, database_timezone: str | None = None
    ) -> tuple[QtWidgets.QWidget, QtWidgets.QComboBox, QtWidgets.QLabel, RowEntry]:
        """Build one format section holding a UTC-offset combobox.

        DiverOffice and DiverOffice Baro need the identical control; they only
        differ in which section is visible for the selected format.
        """
        section = QtWidgets.QWidget()
        section_layout = QtWidgets.QVBoxLayout(section)
        section_layout.setContentsMargins(0, 0, 0, 0)

        label = QtWidgets.QLabel(
            QCoreApplication.translate(
                "LoggerImport", "Identify and change UTC offset:"
            )
        )
        combobox = QtWidgets.QComboBox()
        combobox.setToolTip(
            QCoreApplication.translate(
                "LoggerImport",
                "Identifies UTC-offset in file and changes to the selected one.",
            )
        )
        combobox.addItem("")
        combobox.addItems([format_timezone_string(hour) for hour in range(-12, 15)])
        if database_timezone is not None:
            set_combobox(combobox, database_timezone, add_if_not_exists=False)

        row = RowEntry()
        row.layout().addWidget(label)
        row.layout().addWidget(combobox)
        section_layout.addWidget(row)

        self.add_row(section)
        return section, combobox, label, row

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

    def _start_import_from_gui(self, *, export_csv: bool, import_to_db: bool):
        """Read the current widget state and run one import or CSV export."""
        return self.start_import(
            files=self.files,
            skip_rows_without_water_level=self.skip_rows.checked,
            confirm_names=self.confirm_names.checked,
            import_all_data=self.import_all_data.checked,
            from_date=self.date_time_filter.from_date,
            to_date=self.date_time_filter.to_date,
            export_csv=export_csv,
            import_to_db=import_to_db,
        )

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

    def _report_parse_failures(self, summary: LoggerImportSummary) -> None:
        """Log one warning per file that failed before obsid resolution."""
        for failure in summary.parse_failures:
            message_utils.MessagebarAndLog.warning(
                log_msg=QCoreApplication.translate(
                    "LoggerImport", "%s failed during %s: %s"
                )
                % (failure.filename, failure.stage, failure.reason)
            )

    def _accept_parsed_files(
        self,
        parse_batch: LoggerParseBatchResult,
        summary: LoggerImportSummary,
    ) -> list[ParsedLoggerFile]:
        """Surface notices, resolve timezone errors, and drop unusable files."""
        parsed_files = []
        for parsed in parse_batch.parsed_files:
            for notice in parsed.notices:
                message_utils.MessagebarAndLog.info(log_msg=notice.message)
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
                    summary.skipped.append(parsed.source_path)
                    continue
            if parsed.data.empty:
                summary.skipped.append(parsed.source_path)
                continue
            parsed_files.append(parsed)
        return parsed_files

    def _resolve_obsids(
        self,
        parsed_files: list[ParsedLoggerFile],
        confirm_names: bool,
        summary: LoggerImportSummary,
    ) -> list[tuple[ParsedLoggerFile, str]]:
        """Match each file to an obsid, asking the user where needed."""
        filename_location_obsid = [["filename", "location", "obsid"]]
        filename_location_obsid.extend(
            [parsed.source_path, parsed.location, parsed.location]
            for parsed in parsed_files
        )
        existing_obsids = db_utils.get_all_obsids()
        common_utils.stop_waiting_cursor()
        resolved_metadata = common_utils.filter_nonexisting_values_and_ask(
            file_data=filename_location_obsid,
            header_value="obsid",
            existing_values=existing_obsids,
            try_capitalize=not confirm_names,
            always_ask_user=confirm_names,
        )
        common_utils.start_waiting_cursor()
        paths_obsid = {row[0]: row[2] for row in resolved_metadata[1:]}
        # One pass: the two predicates were exact complements, so a change to
        # the resolution rule had to be made identically in both places or
        # files would be dropped from the summary or counted twice.
        resolved_files = []
        for parsed in parsed_files:
            obsid = paths_obsid.get(parsed.source_path)
            if obsid is None:
                summary.skipped.append(parsed.source_path)
            else:
                resolved_files.append((parsed, obsid))
        return resolved_files

    def _import_one_prepared_file(
        self,
        prepared: PreparedLoggerFile,
        series: LoggerSeriesSpec | None,
        progress: QtWidgets.QProgressDialog,
        summary: LoggerImportSummary,
    ) -> None:
        """Run one file's database import and record its outcome."""
        result = self._run_db_worker(
            LoggerDbImportRequest(
                filename=prepared.source_path,
                dest_table=_DESTINATION_TABLES[prepared.kind],
                frame=prepared.data,
                series=series,
            ),
            progress,
        )
        if result.imported:
            summary.imported.append(prepared.source_path)
        elif result.reason == NO_NEW_ROWS_REASON:
            summary.no_new_rows.append(prepared.source_path)
        else:
            summary.database_failures.append(
                LoggerFileFailure(
                    prepared.source_path,
                    "database",
                    result.reason or "import failed",
                )
            )

    def _ensure_baro_meteo_parameters(self) -> None:
        """Insert any zz_meteoparam rows a barometric import depends on.

        zz_meteoparam is keyed on `parameter`, so the backend's own
        insert-or-ignore expresses "seed what is missing" in one statement per
        row — no read-then-write, and no second idempotency scheme to keep
        working across both backends.
        """
        with db_utils.use_or_create_connection(None) as connection:
            placeholder = connection.placeholder()
            sql = db_utils.add_insert_or_ignore_to_sql(
                "INSERT INTO zz_meteoparam(parameter, explanation) "
                f"VALUES ({placeholder}, {placeholder})",
                connection,
            )
            with connection.transaction():
                for parameter, explanation in BARO_METEO_PARAMS:
                    connection.execute(sql, (parameter, explanation))

    @common_utils.waiting_cursor
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
        target_timezone = {
            self.FORMAT_DIVEROFFICE: self.utc_offset.currentText() or None,
            self.FORMAT_DIVEROFFICE_BARO: (self.baro_utc_offset.currentText() or None),
            self.FORMAT_HOBO: self.tz_converter.target_tz,
        }.get(format_name)

        parse_request = LoggerParseRequest(
            files=tuple(files),
            format_name=format_name,
            skip_missing_water_head=skip_rows_without_water_level,
            from_date=_parse_gui_date_bound(from_date, "from_date"),
            to_date=_parse_gui_date_bound(to_date, "to_date"),
            target_timezone=target_timezone,
        )

        try:
            parse_batch = self._run_parse_worker(parse_request, progress)
            summary = LoggerImportSummary(parse_failures=list(parse_batch.failures))
            self._report_parse_failures(summary)

            parsed_files = self._accept_parsed_files(parse_batch, summary)

            if not parsed_files:
                self._report_import_summary(summary)
                message_utils.MessagebarAndLog.critical(
                    bar_msg=QCoreApplication.translate(
                        "LoggerImport", "Import Failure: No files imported"
                    )
                )
                return

            resolved_files = self._resolve_obsids(parsed_files, confirm_names, summary)
            if not resolved_files:
                self._report_import_summary(summary)
                message_utils.MessagebarAndLog.warning(
                    bar_msg=QCoreApplication.translate(
                        "LoggerImport",
                        "Warning. All files were skipped, nothing imported!",
                    )
                )
                return False

            logger_columns = db_utils.tables_columns(table="w_levels_logger").get(
                "w_levels_logger", []
            )
            capabilities = logger_schema_capabilities(logger_columns)
            source_text = (
                self.source_edit.text().strip() if self.source_edit is not None else ""
            )
            latest_dates = {}
            if not import_all_data and any(
                parsed.kind is LoggerDataKind.WATER_LEVEL
                for parsed, _obsid in resolved_files
            ):
                try:
                    latest_dates = parse_latest_dates(db_utils.get_last_logger_dates())
                except InvalidLatestDateError as error:
                    message_utils.MessagebarAndLog.warning(log_msg=str(error))

            options = LoggerImportOptions(import_all_data=import_all_data)
            prepared_files: list[PreparedLoggerFile] = []
            batch_created_at = _datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for parsed, obsid in resolved_files:
                prepared = run_post_resolution_pipeline(
                    parsed,
                    obsid,
                    latest_dates,
                    options,
                )
                if prepared.data.empty:
                    summary.no_new_rows.append(prepared.source_path)
                    continue
                if (
                    prepared.kind is LoggerDataKind.WATER_LEVEL
                    and source_text
                    and capabilities.has_source_column
                    and not capabilities.has_series_id
                ):
                    prepared = replace(
                        prepared,
                        data=prepared.data.assign(source=source_text),
                    )
                prepared_files.append(prepared)

            if not prepared_files:
                self._report_import_summary(summary)
                message_utils.MessagebarAndLog.info(
                    bar_msg=QCoreApplication.translate(
                        "LoggerImport",
                        "No new data existed in the files. Nothing imported.",
                    )
                )
                self.status = True
                return True

            if import_to_db and any(
                prepared.kind is LoggerDataKind.BAROMETRIC
                for prepared in prepared_files
            ):
                self._ensure_baro_meteo_parameters()

            for prepared in prepared_files:
                series = None
                if (
                    prepared.kind is LoggerDataKind.WATER_LEVEL
                    and capabilities.has_series_id
                ):
                    series = LoggerSeriesSpec(
                        obsid=prepared.obsid,
                        source=source_text or None,
                        description=os.path.basename(prepared.filename),
                        instrument=prepared.serial_number,
                        created_at=(
                            batch_created_at if capabilities.has_created_at else None
                        ),
                    )
                if import_to_db:
                    self._import_one_prepared_file(prepared, series, progress, summary)
                elif export_csv:
                    summary.imported.append(prepared.source_path)

            if export_csv:
                selected_path = QtWidgets.QFileDialog.getSaveFileName(
                    self, "Save File", "", "CSV(*.csv)"
                )[0]
                if selected_path:
                    write_logger_csv(ru(selected_path), prepared_files)
                    message_utils.MessagebarAndLog.info(
                        bar_msg=QCoreApplication.translate(
                            "LoggerImport", "Data written to file %s."
                        )
                        % ru(selected_path)
                    )

            self._report_import_summary(summary)
            if self.close_after_import.isChecked():
                self.close()
            return True
        finally:
            progress.close()
