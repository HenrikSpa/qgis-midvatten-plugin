# -*- coding: utf-8 -*-
"""
/***************************************************************************
 This part of the Midvatten plugin handles calculation of average water flow
 based on readings of accumulated volume. Data is read from, and written to, table w_flow. 
                              -------------------
        begin                : 2014-01-23
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

import pandas as pd
import qgis.PyQt
import qgis.utils
from qgis.PyQt import uic
from qgis.PyQt.QtCore import QCoreApplication

from midvatten.tools import import_data_to_db
from midvatten.tools.utils import common_utils, db_utils
from midvatten.tools.utils.common_utils import returnunicode as ru

Calc_Ui_Dialog = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "..", "ui", "calc_aveflow_dialog.ui")
)[0]


class CalculateAveflow(qgis.PyQt.QtWidgets.QDialog, Calc_Ui_Dialog):
    def __init__(self, parent):
        qgis.PyQt.QtWidgets.QDialog.__init__(self)
        self.setupUi(self)  # Required by Qt
        self.setWindowTitle(
            ru(QCoreApplication.translate("Calcave", "Calculate average flow"))
        )
        self.pushButton_All.clicked.connect(lambda x: self.calcall())
        self.pushButton_Selected.clicked.connect(lambda x: self.calcselected())
        self.pushButton_Cancel.clicked.connect(lambda x: self.close())

    def calcall(self):
        ok, obsar = db_utils.sql_load_fr_db(
            """SELECT DISTINCT obsid FROM w_flow WHERE flowtype = 'Accvol' """
        )
        if not obsar:
            common_utils.MessagebarAndLog.critical(
                bar_msg=ru(
                    QCoreApplication.translate(
                        "Calcave",
                        "No observations with Accvol found, nothing calculated!",
                    )
                )
            )
            return
        observations = [obs[0] for obs in obsar]
        self.calc_aveflow(observations)

    def calcselected(self):
        observations = common_utils.getselectedobjectnames(
            qgis.utils.iface.activeLayer()
        )
        self.calc_aveflow(observations)

    def calc_aveflow(self, observations):
        common_utils.start_waiting_cursor()
        date_from = self.FromDateTime.dateTime().toPyDateTime()
        date_to = self.ToDateTime.dateTime().toPyDateTime()

        dbconnection = db_utils.DbConnectionManager()
        ph = dbconnection.placeholder_sign()
        in_clause, in_args = dbconnection.in_clause(observations)
        sql = (
            "SELECT date_time, reading, obsid, instrumentid, comment "
            "FROM w_flow "
            f"WHERE flowtype = 'Accvol' AND date_time >= {ph} AND date_time <= {ph} "
            f"AND obsid IN {in_clause} "
            "ORDER BY obsid, instrumentid, date_time"
        )
        params = [date_from, date_to] + in_args
        df = pd.read_sql(
            sql,
            dbconnection.conn,
            index_col=["date_time"],
            coerce_float=True,
            params=params,
            parse_dates={"date_time": {"format": "mixed"}},
            columns=None,
            chunksize=None,
        )
        dbconnection.closedb()

        df["dt"] = df.index.astype("int64") // 1e9
        df = df.sort_values(by=["obsid", "instrumentid", "date_time"]).reset_index()
        grouped = df.groupby(by=["obsid", "instrumentid"])
        df["aveflow"] = (grouped["reading"].diff() / grouped["dt"].diff()) * 1000

        if (df["aveflow"] < 0).any():
            common_utils.MessagebarAndLog.info(
                bar_msg=ru(
                    QCoreApplication.translate(
                        "Calcave", "Please notice that negative flow was encountered."
                    )
                )
            )

        columns = ["obsid", "instrumentid", "date_time", "aveflow", "comment"]
        df["date_time"] = df["date_time"].astype(str)
        df = df.loc[df["aveflow"].notna(), columns]  #'[[columns].copy()
        df.columns = ["obsid", "instrumentid", "date_time", "reading", "comment"]
        df["flowtype"] = "Aveflow"
        df["unit"] = "l/s"

        file_data = df.values.tolist()
        file_data.reverse()
        file_data.append(list(df.columns))
        file_data.reverse()

        # print('\n'.join([', '.join([str(x) for x in row]) for row in file_data]))

        importer = import_data_to_db.midv_data_importer()
        importer.general_import(dest_table="w_flow", file_data=file_data)

        common_utils.stop_waiting_cursor()
        self.close()
