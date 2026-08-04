"""
/***************************************************************************
 This is the part of the Midvatten plugin that enables quick export of data from the database
                              -------------------
        begin                : 2015-08-30
        copyright            : (C) 2011 by joskal
        email                : groundwatergis [at] gmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import os
import os.path
import re
from html.parser import HTMLParser
from typing import Callable, Optional, Union

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from midvatten.tools.utils import (
    common_utils,
    db_utils,
    file_utils,
    layer_utils,
    message_utils,
)
from midvatten.definitions import midvatten_defs as defs

_HTML_TAG_RE = re.compile(r"<[a-zA-Z][^>]*>")
_BLOCK_TAGS = frozenset(
    {"p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}
)
_SKIP_TAGS = frozenset({"style", "head", "script"})
_COM_HTML_COLUMN = "com_html"


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth: int = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        t = tag.lower()
        if t in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if t in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if t in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, Optional[str]]]
    ) -> None:
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._parts.append(data)

    def get_text(self) -> str:
        text = "".join(self._parts)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def html_to_plaintext(value: str) -> str:
    if not isinstance(value, str) or not _HTML_TAG_RE.search(value):
        return value
    extractor = _TextExtractor()
    extractor.feed(value)
    return extractor.get_text()


class ExportCsvDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(QCoreApplication.translate("ExportData", "Export to CSV"))
        self._folder = ""
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        folder_row = QHBoxLayout()
        self._folder_edit = QLineEdit()
        self._folder_edit.setReadOnly(True)
        self._folder_edit.setPlaceholderText(
            QCoreApplication.translate("ExportData", "Select export folder…")
        )
        self._browse_btn = QPushButton(
            QCoreApplication.translate("ExportData", "Browse…")
        )
        self._browse_btn.clicked.connect(self._browse_folder)
        folder_row.addWidget(self._folder_edit)
        folder_row.addWidget(self._browse_btn)
        form.addRow(
            QCoreApplication.translate("ExportData", "Export folder:"), folder_row
        )

        self._strip_html_cb = QCheckBox(
            QCoreApplication.translate(
                "ExportData", "Convert rich-text (HTML) fields to plain text"
            )
        )
        self._strip_html_cb.setChecked(True)
        form.addRow("", self._strip_html_cb)

        layout.addLayout(form)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        layout.addWidget(self._buttons)

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            QCoreApplication.translate("ExportData", "Select export folder"),
            self._folder_edit.text() or ".",
            QFileDialog.Option.ShowDirsOnly,
        )
        if folder:
            self._folder = folder
            self._folder_edit.setText(folder)
            self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)

    @property
    def export_folder(self) -> str:
        return self._folder

    @property
    def strip_html(self) -> bool:
        return self._strip_html_cb.isChecked()


class ExportData:
    def __init__(self, iface, ms) -> None:
        self._iface = iface
        self._ms = ms
        self.source_dbconnection = None
        self.ID_obs_points: tuple = ()
        self.ID_obs_lines: tuple = ()

    @common_utils.waiting_cursor
    def show(self) -> None:
        obsid_p = layer_utils.get_selected_features_as_tuple("obs_points")
        obsid_l = layer_utils.get_selected_features_as_tuple("obs_lines")

        with common_utils.suspended_waiting_cursor():
            dlg = ExportCsvDialog(None)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return

        self.ID_obs_points = obsid_p
        self.ID_obs_lines = obsid_l
        self.export_2_csv(dlg.export_folder, dlg.strip_html)

    def export_2_csv(self, exportfolder: str, strip_html: bool = True) -> None:
        self.source_dbconnection = db_utils.DbConnectionManager()
        try:
            self.source_dbconnection.connect2db()
            db_utils.export_bytea_as_bytes(self.source_dbconnection)

            self._strip_html = strip_html
            planned_tables = self._planned_tables()
            selected_folder = exportfolder
            replace = False

            while True:
                planned_exports = [
                    (
                        tname,
                        obsids,
                        os.path.join(selected_folder, tname + ".csv"),
                    )
                    for tname, obsids in planned_tables
                ]
                conflicts = [
                    filename
                    for _, _, filename in planned_exports
                    if os.path.exists(filename)
                ]
                if not conflicts:
                    break

                action = self._ask_csv_collision_action(conflicts)
                if action == "replace":
                    replace = True
                    break
                if action == "choose":
                    selected_folder = self._choose_another_folder(selected_folder)
                    if not selected_folder:
                        return
                    continue
                return

            self.exportfolder = selected_folder
            for tname, obsids, _filename in planned_exports:
                QApplication.processEvents()
                self.to_csv(tname, obsids, replace)

            message_utils.MessagebarAndLog.info(
                bar_msg=QCoreApplication.translate(
                    "ExportData", "Exported %s CSV files to %s"
                )
                % (len(planned_exports), selected_folder)
            )
        finally:
            if self.source_dbconnection is not None:
                self.source_dbconnection.closedb()

    def _table_groups(self):
        return [
            (
                None,
                defs.get_subset_of_tables_fr_db(category="data_domains"),
            ),
            (
                self.ID_obs_points,
                defs.get_subset_of_tables_fr_db(category="obs_points"),
            ),
            (
                self.ID_obs_lines,
                defs.get_subset_of_tables_fr_db(category="obs_lines"),
            ),
            (
                self.ID_obs_points,
                defs.get_subset_of_tables_fr_db(category="extra_data_tables"),
            ),
            (
                self.ID_obs_points,
                defs.get_subset_of_tables_fr_db(category="interlab4_import_table"),
            ),
        ]

    def _tables_to_export(self, obsids, ptabs):
        tables = []
        for tname in ptabs:
            QApplication.processEvents()
            if not db_utils.verify_table_exists(
                tname, dbconnection=self.source_dbconnection
            ):
                message_utils.MessagebarAndLog.info(
                    bar_msg=QCoreApplication.translate(
                        "ExportData", "Table %s didn't exist. Skipping it."
                    )
                    % tname
                )
                continue

            if not obsids:
                tables.append((tname, obsids))
                continue

            sql = self.source_dbconnection.sql_ident(
                "SELECT count({c}) FROM {t}", c="obsid", t=tname
            )
            clause, args = self.source_dbconnection.in_clause(obsids)
            sql += f" WHERE {self.source_dbconnection.ident('obsid')} IN {clause}"
            nr_of_rows = self.source_dbconnection.execute_and_fetchall(sql, args)[0][0]
            if nr_of_rows > 0:
                tables.append((tname, obsids))
        return tables

    def _planned_tables(self):
        planned_tables = []
        for obsids, ptabs in self._table_groups():
            planned_tables.extend(self._tables_to_export(obsids, ptabs))
        return planned_tables

    def _dialog_parent(self):
        if self._iface is None:
            return None
        return self._iface.mainWindow()

    def _ask_csv_collision_action(self, conflicts: list[str]) -> str:
        box = QMessageBox(self._dialog_parent())
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(
            QCoreApplication.translate("ExportData", "CSV files already exist")
        )
        conflict_list = "\n".join(os.path.basename(path) for path in conflicts)
        box.setText(
            QCoreApplication.translate(
                "ExportData",
                "The following CSV files already exist:\n%s\n\nHow would you like to continue?",
            )
            % conflict_list
        )
        replace_button = box.addButton(
            QCoreApplication.translate("ExportData", "Replace existing files"),
            QMessageBox.AcceptRole,
        )
        choose_button = box.addButton(
            QCoreApplication.translate("ExportData", "Choose another folder"),
            QMessageBox.ActionRole,
        )
        cancel_button = box.addButton(
            QCoreApplication.translate("ExportData", "Cancel"),
            QMessageBox.RejectRole,
        )
        box.setDefaultButton(cancel_button)
        box.setEscapeButton(cancel_button)
        box.exec()

        clicked = box.clickedButton()
        if clicked is replace_button:
            return "replace"
        if clicked is choose_button:
            return "choose"
        return "cancel"

    def _choose_another_folder(self, current_folder: str) -> str:
        return QFileDialog.getExistingDirectory(
            self._dialog_parent(),
            QCoreApplication.translate("ExportData", "Select export folder"),
            current_folder,
            QFileDialog.Option.ShowDirsOnly,
        )

    def write_data(
        self,
        to_writer: Callable,
        obsids: Optional[Union[tuple[str], tuple[()]]],
        ptabs: list[str],
        replace: bool = False,
    ) -> None:
        for tname, table_obsids in self._tables_to_export(obsids, ptabs):
            to_writer(tname, table_obsids, replace)

    def to_csv(
        self,
        tname: str,
        obsids: Optional[Union[tuple[str], tuple[()]]] = None,
        replace: bool = False,
    ) -> None:
        geom_cols = set(
            db_utils.get_geometry_types(
                tname, dbconnection=self.source_dbconnection
            ).keys()
        )
        if geom_cols:
            table_info = (
                db_utils.get_table_info(tname, dbconnection=self.source_dbconnection)
                or []
            )
            q = self.source_dbconnection.ident
            col_exprs = [
                f"ST_AsText({q(row[1])}) AS {q(row[1])}"
                if row[1] in geom_cols
                else q(row[1])
                for row in table_info
            ]
            sql = f"SELECT {', '.join(col_exprs)} FROM {q(tname)}"
        else:
            sql = self.source_dbconnection.sql_ident("SELECT * FROM {t}", t=tname)
        args = None
        if obsids:
            clause, args = self.source_dbconnection.in_clause(obsids)
            sql += f" WHERE {self.source_dbconnection.ident('obsid')} IN {clause}"
        data = self.source_dbconnection.execute_and_fetchall(sql, args)
        headers = [col[0] for col in self.source_dbconnection.cursor.description]

        if self._strip_html:
            html_col_indices = {
                i for i, h in enumerate(headers) if h == _COM_HTML_COLUMN
            }
            if html_col_indices:
                data = [
                    tuple(
                        html_to_plaintext(cell) if i in html_col_indices else cell
                        for i, cell in enumerate(row)
                    )
                    for row in data
                ]

        printlist = [headers, *data]
        filename = os.path.join(self.exportfolder, tname + ".csv")
        file_utils.write_printlist_to_file(
            filename,
            printlist,
            notify=False,
            overwrite=replace,
        )
