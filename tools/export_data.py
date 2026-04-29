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
    QPushButton,
    QVBoxLayout,
)

from midvatten.tools.utils import common_utils, db_utils
from midvatten.definitions import midvatten_defs as defs

_HTML_TAG_RE = re.compile(r"<[a-zA-Z][^>]*>")
_BLOCK_TAGS = frozenset(
    {"p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}
)
_SKIP_TAGS = frozenset({"style", "head", "script"})
_COM_HTML_COLUMN = "com_html"


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth: int = 0

    def handle_starttag(self, tag: str, attrs) -> None:
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

    def handle_startendtag(self, tag: str, attrs) -> None:
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
    def __init__(self, parent=None):
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

        self._buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        self._buttons.button(QDialogButtonBox.Ok).setEnabled(False)
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
            self._buttons.button(QDialogButtonBox.Ok).setEnabled(True)

    @property
    def export_folder(self) -> str:
        return self._folder

    @property
    def strip_html(self) -> bool:
        return self._strip_html_cb.isChecked()


class ExportData:
    def __init__(self, iface, ms):
        self._iface = iface
        self._ms = ms
        self.source_dbconnection = None
        self.ID_obs_points: tuple = ()
        self.ID_obs_lines: tuple = ()

    def show(self) -> None:
        common_utils.start_waiting_cursor()
        obsid_p = common_utils.get_selected_features_as_tuple("obs_points")
        obsid_l = common_utils.get_selected_features_as_tuple("obs_lines")
        common_utils.stop_waiting_cursor()

        dlg = ExportCsvDialog(None)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        common_utils.start_waiting_cursor()
        self.ID_obs_points = obsid_p
        self.ID_obs_lines = obsid_l
        self.export_2_csv(dlg.export_folder, dlg.strip_html)
        common_utils.stop_waiting_cursor()

    def export_2_csv(self, exportfolder: str, strip_html: bool = True) -> None:
        self.source_dbconnection = db_utils.DbConnectionManager()
        self.source_dbconnection.connect2db()
        db_utils.export_bytea_as_bytes(self.source_dbconnection)

        self.exportfolder = exportfolder
        self._strip_html = strip_html
        self.write_data(
            self.to_csv, None, defs.get_subset_of_tables_fr_db(category="data_domains")
        )
        self.write_data(
            self.to_csv,
            self.ID_obs_points,
            defs.get_subset_of_tables_fr_db(category="obs_points"),
        )
        self.write_data(
            self.to_csv,
            self.ID_obs_lines,
            defs.get_subset_of_tables_fr_db(category="obs_lines"),
        )
        self.write_data(
            self.to_csv,
            self.ID_obs_points,
            defs.get_subset_of_tables_fr_db(category="extra_data_tables"),
        )
        self.write_data(
            self.to_csv,
            self.ID_obs_points,
            defs.get_subset_of_tables_fr_db(category="interlab4_import_table"),
        )

        self.source_dbconnection.closedb()

    def write_data(
        self,
        to_writer: Callable,
        obsids: Optional[Union[tuple[str], tuple[()]]],
        ptabs: list[str],
        replace: bool = False,
    ):
        for tname in ptabs:
            QApplication.processEvents()
            if not db_utils.verify_table_exists(
                tname, dbconnection=self.source_dbconnection
            ):
                common_utils.MessagebarAndLog.info(
                    bar_msg=QCoreApplication.translate(
                        "ExportData", "Table %s didn't exist. Skipping it."
                    )
                    % tname
                )
                continue

            if not obsids:
                to_writer(tname, obsids, replace)
            else:
                sql = self.source_dbconnection.sql_ident(
                    "SELECT count({c}) FROM {t}", c="obsid", t=tname
                )
                clause, args = self.source_dbconnection.in_clause(obsids)
                sql += f" WHERE {self.source_dbconnection.ident('obsid')} IN {clause}"
                nr_of_rows = self.source_dbconnection.execute_and_fetchall(sql, args)[
                    0
                ][0]
                if nr_of_rows > 0:
                    to_writer(tname, obsids, replace)

    def to_csv(
        self,
        tname: str,
        obsids: Optional[Union[tuple[str], tuple[()]]] = None,
        replace: bool = False,
    ) -> None:
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
        common_utils.write_printlist_to_file(filename, printlist)
