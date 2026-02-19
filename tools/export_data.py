# -*- coding: utf-8 -*-
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

import os, os.path
from qgis.PyQt.QtCore import QCoreApplication

from midvatten.tools.utils import common_utils, db_utils
from midvatten.tools.utils.common_utils import returnunicode as ru
from midvatten.definitions import midvatten_defs as defs, db_defs

from midvatten.tools.import_data_to_db import midv_data_importer
from midvatten.tools.utils.db_utils import DbConnectionManager
from typing import Any, Callable, List, Optional, Tuple, Union


class ExportData(object):

    def __init__(self, OBSID_P: Union[Tuple[str], Tuple[()]], OBSID_L: Union[Tuple[str], Tuple[()]]):
        self.ID_obs_points = OBSID_P
        self.ID_obs_lines = OBSID_L
        self.dest_dbconnection = None
        self.source_dbconnection = None

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

        self.midv_data_importer = midv_data_importer()

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

        db_utils.delete_srids(self.dest_dbconnection.cursor, dest_srid)
        self.dest_dbconnection.commit()

        # Statistics
        statistics = self.get_table_rows_with_differences()

        self.dest_dbconnection.cursor.execute("vacuum")

        common_utils.MessagebarAndLog.info(
            bar_msg=ru(
                QCoreApplication.translate(
                    "ExportData", "Export done, see differences in log message panel"
                )
            ),
            log_msg=ru(
                QCoreApplication.translate(
                    "ExportData", "Tables with different number of rows:\n%s"
                )
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

    def write_data(self, to_writer: Callable, obsids: Optional[Union[Tuple[str], Tuple[()]]], ptabs: List[str], replace: bool=False):
        for tname in ptabs:
            if not db_utils.verify_table_exists(
                tname, dbconnection=self.source_dbconnection
            ):
                common_utils.MessagebarAndLog.info(
                    bar_msg=ru(
                        QCoreApplication.translate(
                            "ExportData", "Table %s didn't exist. Skipping it."
                        )
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
                                bar_msg=ru(
                                    QCoreApplication.translate(
                                        "ExportData",
                                        "Programming error, file path not existing: %s. Skipping table %s",
                                    )
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
                            bar_msg=ru(
                                QCoreApplication.translate(
                                    "ExportData",
                                    "Programming error, table missing in new database: %s.",
                                )
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

    def to_csv(self, tname: str, obsids: Optional[Union[Tuple[str], Tuple[()]]]=None, replace: bool=False):
        """
        Write to csv
        :param tname: The destination database
        :param obsids:
        :return:
        """
        sql = self.source_dbconnection.sql_ident('SELECT * FROM {t}', t=tname)
        args = None
        if obsids:
            clause, args = self.source_dbconnection.in_clause(obsids)
            sql += f" WHERE obsid IN {clause}"
        data = self.source_dbconnection.execute_and_fetchall(sql, args)
        printlist = [[col[0] for col in self.source_dbconnection.cursor.description]]
        printlist.extend(data)
        filename = os.path.join(self.exportfolder, tname + ".csv")
        common_utils.write_printlist_to_file(filename, printlist)

    def to_sql(self, tname: str, obsids: Optional[Union[Tuple[str], Tuple[()]]]=None, replace: bool=False):
        """
        Write to new sql database
        :param tname: The destination database
        :param tname_with_prefix: The source database
        :param obsids:
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
        except:
            common_utils.MessagebarAndLog.info(
                bar_msg=ru(
                    QCoreApplication.translate(
                        "ExportData",
                        "Error! Export of table %s failed, see log message panel",
                    )
                )
                % tname,
                log_msg=ru(traceback.format_exc()),
            )
            return

        if replace:
            self.dest_dbconnection.execute("""PRAGMA foreign_keys = OFF;""")
            dest_data = self.get_table_data(
                tname, obsids, self.dest_dbconnection, file_data_srid
            )
            if dest_data:
                self.dest_dbconnection.execute_safe(
                    self.dest_dbconnection.sql_ident("DELETE FROM {t}", t=tname)
                )

        if tname == "obs_points":
            geom_column = list(
                db_utils.get_geometry_types(self.source_dbconnection, tname).keys()
            )[0]
            source_data = [
                (
                    set_east_north_to_null(row, source_data[0], geom_column)
                    if rownr > 0
                    else row
                )
                for rownr, row in enumerate(source_data)
            ]

        self.midv_data_importer.general_import(
            tname,
            source_data,
            _dbconnection=self.dest_dbconnection,
            source_srid=file_data_srid,
            skip_confirmation=True,
            binary_geometry=True,
        )

        if replace and dest_data is not None:
            self.midv_data_importer.general_import(
                tname,
                dest_data,
                _dbconnection=self.dest_dbconnection,
                source_srid=file_data_srid,
                skip_confirmation=True,
            )
            self.dest_dbconnection.execute("""PRAGMA foreign_keys = ON;""")

    def get_table_data(self, tname: str, obsids: Optional[Union[Tuple[str], Tuple[()]]], dbconnection: DbConnectionManager, file_data_srid: Optional[int]) -> List[Any]:
        dbconnection.execute_safe(dbconnection.sql_ident("SELECT * FROM {t} LIMIT 1", t=tname))
        columns = [x[0] for x in dbconnection.cursor.description]

        if file_data_srid:
            astext = "ST_AsBinary(ST_Transform({}, %s))" % str(file_data_srid)
        else:
            astext = "ST_AsBinary({})"

        geom_columns = list(db_utils.get_geometry_types(dbconnection, tname).keys())
        # Transform to 4326 just to be sure that both the source and dest database has support for the srid.
        select_columns = [
            (
                astext.format(col)
                if (col.lower() in geom_columns and dbconnection.get_srid(tname, col))
                else col
            )
            for col in columns
        ]

        sql = "SELECT {} FROM {}".format(
            ", ".join(select_columns),
            dbconnection.ident(tname),
        )
        args = None
        if obsids:
            clause, args = dbconnection.in_clause(obsids)
            sql += f" WHERE obsid IN {clause}"
        dbconnection.execute_safe(sql, args)

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
                except:
                    common_utils.MessagebarAndLog.warning(
                        log_msg=ru(
                            QCoreApplication.translate(
                                "ExportData",
                                "Sql failed while getting table row differences: %s",
                            )
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
                "{0:40}{1:15}{2:15}".format(result_row[0], result_row[1], result_row[2])
                for result_row in printable_results
            ]
        )
        return printable_msg


def set_east_north_to_null(row: Tuple[str, None, None, None, None, None, None, None, None, None, None, None, None, float, float, None, None, None, None, None, None, None, None, None, None, None, bytes], header: List[str], geometry: str) -> List[Optional[Union[str, bytes]]]:
    res = list(row)
    if res[header.index(geometry)]:
        res[header.index("east")] = None
        res[header.index("north")] = None
    return res
