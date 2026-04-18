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

import traceback

import os
import os.path
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import QApplication, QFileDialog

from midvatten.tools.utils import common_utils, db_utils
from midvatten.tools.utils.string_utils import returnunicode as ru
from midvatten.definitions import midvatten_defs as defs, db_defs

from midvatten.tools.import_data_to_db import MidvDataImporter
from midvatten.tools.utils.db_utils import DbConnectionManager
from typing import Any, Callable, List, Optional, Tuple, Union


class ExportData:
    def __init__(self, iface, ms):
        self._iface = iface
        self._ms = ms
        self.dest_dbconnection = None
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

    def export_2_splite(self, target_db: str, dest_srid: str):
        """
        Exports a datagbase to a new spatialite database file
        :param target_db: The name of the new database file
        :param dest_srid:
        :return:

        """
        self.source_dbconnection = db_utils.DbConnectionManager()
        self.source_dbconnection.connect2db()  # establish connection to the current midv db
        db_utils.export_bytea_as_bytes(self.source_dbconnection)

        self.dest_dbconnection = db_utils.DbConnectionManager(target_db)
        self.dest_dbconnection.connect2db()

        self.midv_data_importer = MidvDataImporter()

        self.write_data(
            self.to_sql,
            None,
            defs.get_subset_of_tables_fr_db(category="data_domains"),
            replace=True,
        )
        self.dest_dbconnection.commit()
        self.write_data(
            self.to_sql,
            self.ID_obs_points,
            defs.get_subset_of_tables_fr_db(category="obs_points"),
        )
        self.dest_dbconnection.commit()
        self.write_data(
            self.to_sql,
            self.ID_obs_lines,
            defs.get_subset_of_tables_fr_db(category="obs_lines"),
        )
        self.dest_dbconnection.commit()
        self.write_data(
            self.to_sql,
            self.ID_obs_points,
            defs.get_subset_of_tables_fr_db(category="extra_data_tables"),
        )
        self.dest_dbconnection.commit()
        self.write_data(
            self.to_sql,
            self.ID_obs_points,
            defs.get_subset_of_tables_fr_db(category="interlab4_import_table"),
        )
        self.dest_dbconnection.commit()

        db_utils.delete_srids(self.dest_dbconnection, dest_srid)
        self.dest_dbconnection.commit()

        # Statistics
        statistics = self.get_table_rows_with_differences()

        self.dest_dbconnection.vacuum()

        common_utils.MessagebarAndLog.info(
            bar_msg=QCoreApplication.translate(
                "ExportData", "Export done, see differences in log message panel"
            ),
            log_msg=QCoreApplication.translate(
                "ExportData", "Tables with different number of rows:\n%s"
            )
            % statistics,
        )

        self.dest_dbconnection.commit_and_closedb()
        self.source_dbconnection.closedb()

    def get_number_of_rows(self, obsids: Tuple[str], tname: str) -> int:
        sql = self.source_dbconnection.sql_ident(
            "SELECT count(obsid) FROM {t}", t=tname
        )
        args = None
        if obsids:
            clause, args = self.source_dbconnection.in_clause(obsids)
            sql += f" WHERE obsid IN {clause}"
        nr_of_rows = self.source_dbconnection.execute_and_fetchall(sql, args)[0][0]
        return nr_of_rows

    def write_data(
        self,
        to_writer: Callable,
        obsids: Optional[Union[Tuple[str], Tuple[()]]],
        ptabs: List[str],
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
            if self.dest_dbconnection is not None:
                if not db_utils.verify_table_exists(
                    tname, dbconnection=self.dest_dbconnection
                ):
                    if tname in defs.get_subset_of_tables_fr_db("extra_data_tables"):
                        sqlfile = db_defs.extra_datatables_sqlfile()
                        if not os.path.isfile(sqlfile):
                            common_utils.MessagebarAndLog.info(
                                bar_msg=QCoreApplication.translate(
                                    "ExportData",
                                    "Programming error, file path not existing: %s. Skipping table %s",
                                )
                                % (sqlfile, tname)
                            )
                            continue
                        else:
                            db_utils.execute_sqlfile(
                                sqlfile, self.dest_dbconnection, merge_newlines=True
                            )
                            self.dest_dbconnection.commit()
                    else:
                        common_utils.MessagebarAndLog.info(
                            bar_msg=QCoreApplication.translate(
                                "ExportData",
                                "Programming error, table missing in new database: %s.",
                            )
                            % tname
                        )

            if not obsids:
                to_writer(tname, obsids, replace)
            else:
                nr_of_rows = self.get_number_of_rows(obsids, tname)
                if (
                    nr_of_rows > 0
                ):  # only go on if there are any observations for this obsid
                    to_writer(tname, obsids, replace)

    def to_csv(
        self,
        tname: str,
        obsids: Optional[Union[Tuple[str], Tuple[()]]] = None,
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
            sql += f" WHERE obsid IN {clause}"
        data = self.source_dbconnection.execute_and_fetchall(sql, args)
        printlist = [[col[0] for col in self.source_dbconnection.cursor.description]]
        printlist.extend(data)
        filename = os.path.join(self.exportfolder, tname + ".csv")
        common_utils.write_printlist_to_file(filename, printlist)

    def to_sql(
        self,
        tname: str,
        obsids: Optional[Union[Tuple[str], Tuple[()]]] = None,
        replace: bool = False,
    ):
        """
        Write to new sql database


        :param tname: The destination table
        :param obsids: Only collect data for the given obsids.
        :param replace: Primary keys (or unique constraints) in the source table will have priority over the destination table.
                        Primary keys (or unique constraints) in the destination table that does not exist in the source table will be kept.
        :return:
        """

        dest_data = None

        source_srid = self.source_dbconnection.get_srid(tname)
        dest_srid = self.dest_dbconnection.get_srid(tname)

        if source_srid is dest_srid or source_srid == dest_srid:
            file_data_srid = dest_srid
        else:
            file_data_srid = 4326

        try:
            source_data = self.get_table_data(
                tname, obsids, self.source_dbconnection, file_data_srid
            )
        except Exception:
            common_utils.MessagebarAndLog.info(
                bar_msg=QCoreApplication.translate(
                    "ExportData",
                    "Error! Export of table %s failed, see log message panel",
                )
                % tname,
                log_msg=ru(traceback.format_exc()),
            )
            return

        dest_data = None

        # replace: Making sure that source data has priority
        # 1. Read and cache rows from destination table.
        # 2. Delete all rows in destination table.
        # 3. Import data from source table to destination table.
        # 4. Import the cached destination rows using "insert or ignore"-logic. Only rows that didn't exist
        # in the source table will be inserted to destination table.
        if replace:
            self.dest_dbconnection.execute("""PRAGMA foreign_keys = OFF;""")
            dest_data = self.get_table_data(
                tname, obsids, self.dest_dbconnection, file_data_srid
            )
            if dest_data:
                self.dest_dbconnection.execute_safe(
                    self.dest_dbconnection.sql_ident("DELETE FROM {t}", t=tname)
                )
                self.dest_dbconnection.commit()

        if tname == "obs_points":
            geom_column = list(
                db_utils.get_geometry_types(
                    tname, dbconnection=self.source_dbconnection
                ).keys()
            )[0]
            source_data = [
                (
                    set_east_north_to_null(row, source_data[0], geom_column)
                    if rownr > 0
                    else row
                )
                for rownr, row in enumerate(source_data)
            ]

        if tname == "w_levels_logger":
            source_data = self._migrate_logger_source_to_series(source_data)

        self.midv_data_importer.general_import(
            tname,
            source_data,
            _dbconnection=self.dest_dbconnection,
            source_srid=file_data_srid,
            skip_confirmation=True,
            binary_geometry=True,
        )
        self.dest_dbconnection.commit()

        if replace and dest_data is not None:
            self.midv_data_importer.general_import(
                tname,
                dest_data,
                _dbconnection=self.dest_dbconnection,
                source_srid=file_data_srid,
                skip_confirmation=True,
                binary_geometry=True,
            )
            self.dest_dbconnection.commit()

        if replace:
            self.dest_dbconnection.execute("""PRAGMA foreign_keys = ON;""")

    def _migrate_logger_source_to_series(self, source_data: List[Any]) -> List[Any]:
        """Bridge Midv 1.x w_levels_logger.source -> new w_logger_series.

        When the source DB still has the old ``w_levels_logger.source``
        column and the destination has the new schema (``series_id`` on
        ``w_levels_logger`` plus ``w_logger_series``), create one
        series row per distinct ``(obsid, source)`` pair on the
        destination and replace the ``source`` column in ``source_data``
        with a ``series_id`` column pointing at those new series rows.

        No-op when both DBs are on the same schema (source with no
        ``source`` column, or dest without ``w_logger_series``).
        """
        if not source_data or len(source_data) < 2:
            return source_data

        header = list(source_data[0])
        if "source" not in header:
            return source_data
        src_idx = header.index("source")
        obsid_idx = header.index("obsid") if "obsid" in header else -1
        if obsid_idx < 0:
            return source_data

        dest_tables = db_utils.tables_columns(dbconnection=self.dest_dbconnection)
        if "w_logger_series" not in dest_tables:
            return source_data
        if "series_id" not in dest_tables.get("w_levels_logger", []):
            return source_data

        ph = self.dest_dbconnection.placeholder()
        key_to_sid: Dict[Tuple[str, Optional[str]], int] = {}
        for row in source_data[1:]:
            obsid = row[obsid_idx]
            source_val = row[src_idx]
            key = (obsid, source_val)
            if key in key_to_sid:
                continue
            self.dest_dbconnection.execute(
                f"INSERT INTO w_logger_series "
                f"(obsid, source, description) VALUES ({ph}, {ph}, {ph})",
                (obsid, source_val, "Upgraded from Midv 1.x"),
            )
            key_to_sid[key] = db_utils.get_last_insert_id(self.dest_dbconnection)
        self.dest_dbconnection.commit()

        new_header = list(header)
        new_header[src_idx] = "series_id"
        migrated = [new_header]
        for row in source_data[1:]:
            new_row = list(row)
            new_row[src_idx] = key_to_sid[(new_row[obsid_idx], new_row[src_idx])]
            migrated.append(new_row)
        return migrated

    def get_table_data(
        self,
        tname: str,
        obsids: Optional[Union[Tuple[str], Tuple[()]]],
        dbconnection: DbConnectionManager,
        file_data_srid: Optional[int],
    ) -> List[Any]:
        dbconnection.execute_safe(
            dbconnection.sql_ident("SELECT * FROM {t} LIMIT 1", t=tname)
        )
        columns = [x[0] for x in dbconnection.cursor.description]

        geom_columns = list(
            db_utils.get_geometry_types(tname, dbconnection=dbconnection).keys()
        )
        # Transform to 4326 just to be sure that both the source and dest database has support for the srid.
        # All column identifiers are quoted; geometry columns are wrapped in ST_AsBinary.
        select_columns = []
        for col in columns:
            if col.lower() in geom_columns and dbconnection.get_srid(tname, col):
                quoted_col = dbconnection.ident(col)
                if file_data_srid:
                    select_columns.append(
                        f"ST_AsBinary(ST_Transform({quoted_col}, {file_data_srid}))"
                    )
                else:
                    select_columns.append(f"ST_AsBinary({quoted_col})")
            else:
                select_columns.append(dbconnection.ident(col))

        sql = f"SELECT {', '.join(select_columns)} FROM {dbconnection.ident(tname)}"
        args = None
        if obsids:
            clause, args = dbconnection.in_clause(obsids)
            sql += f" WHERE obsid IN {clause}"
        table_data = [[x.lower() for x in columns]]
        table_data.extend([row for row in dbconnection.execute_and_fetchall(sql, args)])

        if len(table_data) < 2:
            return None
        else:
            return table_data

    def get_table_rows_with_differences(self) -> str:
        """
        Counts rows for all tables in new and old database and returns those that differ.
        self.cursor is required where the new database is the regular one and the old database is the attached one
        :param db_aliases_and_prefixes: A list of tuples like ('new', '')
        :return:  a printable list of nr of rows for all tables
        """
        results = {}
        db_aliases_and_connections = [
            ("exported_db", self.dest_dbconnection),
            ("source_db", self.source_dbconnection),
        ]
        for alias, dbconnection in db_aliases_and_connections:
            tablenames = db_utils.get_tables(dbconnection, skip_views=True)
            for tablename in tablenames:
                sql = dbconnection.sql_ident("SELECT count(*) FROM {t}", t=tablename)
                try:
                    nr_of_rows = dbconnection.execute_and_fetchall(sql)[0][0]
                except Exception:
                    common_utils.MessagebarAndLog.warning(
                        log_msg=QCoreApplication.translate(
                            "ExportData",
                            "Sql failed while getting table row differences: %s",
                        )
                        % sql
                    )
                else:
                    results.setdefault(tablename, {})[alias] = str(nr_of_rows)

        printable_results = []

        # Create header
        header = ["tablename"]
        db_aliases = sorted([_x[0] for _x in db_aliases_and_connections])
        header.extend(db_aliases)
        printable_results.append(header)

        # Create table result rows
        for tablename, dbdict in sorted(results.items()):
            vals = [tablename]
            vals.extend(
                [
                    str(dbdict.get(alias, "table_missing"))
                    for alias in sorted(db_aliases)
                ]
            )
            if vals[1] != vals[2]:
                printable_results.append(vals)

        printable_msg = "\n".join(
            [
                f"{result_row[0]:40}{result_row[1]:15}{result_row[2]:15}"
                for result_row in printable_results
            ]
        )
        return printable_msg


def set_east_north_to_null(
    row: Tuple[
        str,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        float,
        float,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        bytes,
    ],
    header: List[str],
    geometry: str,
) -> List[Optional[Union[str, bytes]]]:
    res = list(row)
    if res[header.index(geometry)]:
        res[header.index("east")] = None
        res[header.index("north")] = None
    return res
