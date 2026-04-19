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
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import QApplication, QFileDialog

from midvatten.tools.utils import common_utils, db_utils
from midvatten.definitions import midvatten_defs as defs
from typing import Callable, Optional, Union


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

        exportfolder = QFileDialog.getExistingDirectory(
            None,
            QCoreApplication.translate(
                "Midvatten",
                "Select a folder where the csv files will be created:",
            ),
            ".",
            QFileDialog.Option.ShowDirsOnly,
        )
        if not exportfolder:
            return

        common_utils.start_waiting_cursor()
        self.ID_obs_points = obsid_p
        self.ID_obs_lines = obsid_l
        self.export_2_csv(exportfolder)
        common_utils.stop_waiting_cursor()

    def export_2_csv(self, exportfolder: str):
        self.source_dbconnection = db_utils.DbConnectionManager()
        self.source_dbconnection.connect2db()  # establish connection to the current midv db
        db_utils.export_bytea_as_bytes(self.source_dbconnection)

        self.exportfolder = exportfolder
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
                if (
                    nr_of_rows > 0
                ):  # only go on if there are any observations for this obsid
                    to_writer(tname, obsids, replace)

    def to_csv(
        self,
        tname: str,
        obsids: Optional[Union[tuple[str], tuple[()]]] = None,
        replace: bool = False,
    ):
        """
        Write to csv
        :param tname: The destination database
        :param obsids:
        :return:
        """
        sql = self.source_dbconnection.sql_ident("SELECT * FROM {t}", t=tname)
        args = None
        if obsids:
            clause, args = self.source_dbconnection.in_clause(obsids)
            sql += f" WHERE {self.source_dbconnection.ident('obsid')} IN {clause}"
        data = self.source_dbconnection.execute_and_fetchall(sql, args)
        printlist = [[col[0] for col in self.source_dbconnection.cursor.description]]
        printlist.extend(data)
        filename = os.path.join(self.exportfolder, tname + ".csv")
        common_utils.write_printlist_to_file(filename, printlist)
