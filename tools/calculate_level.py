# -*- coding: utf-8 -*-
"""
/***************************************************************************
 This part of the Midvatten plugin handles importing of water level measurements
 to the database. Also some calculations and calibrations. 

 This part is to a big extent based on QSpatialite plugin.
                             -------------------
        begin                : 2011-10-18
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
from typing import List

import matplotlib as mpl
from qgis.PyQt.QtWidgets import QWidget

mpl.use("Qt5Agg")

import qgis.PyQt

from qgis.PyQt import uic
from qgis.PyQt.QtCore import QCoreApplication

try:  # assume matplotlib >=1.5.1
    from matplotlib.backends.backend_qt5agg import (
        NavigationToolbar2QT as NavigationToolbar,
    )
except:
    from matplotlib.backends.backend_qt5agg import (
        NavigationToolbar2QTAgg as NavigationToolbar,
    )

from midvatten.tools.utils import common_utils, db_utils
from midvatten.tools.utils.common_utils import returnunicode as ru, fn_timer

Calc_Ui_Dialog = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "..", "ui", "calc_lvl_dialog.ui")
)[0]


class CalculateLevel(
    qgis.PyQt.QtWidgets.QDialog, Calc_Ui_Dialog
):  # An instance of the class Calc_Ui_Dialog is created same time as instance of calclvl is created

    @fn_timer
    def __init__(self, parent: QWidget, layerin: int):
        qgis.PyQt.QtWidgets.QDialog.__init__(self)
        self.setupUi(self)  # Required by Qt
        # self.obsid = midvatten_utils.getselectedobjectnames()
        self.setWindowTitle(
            ru(QCoreApplication.translate("Calclvl", "Calculate levels"))
        )
        self.pushButton_All.clicked.connect(lambda x: self.calcall())
        self.pushButton_Selected.clicked.connect(lambda x: self.calcselected())
        self.pushButton_Cancel.clicked.connect(lambda x: self.close())
        self.layer = layerin

    def calc(self, obsids: List[str]):
        fr_d_t = self.FromDateTime.dateTime().toPyDateTime()
        to_d_t = self.ToDateTime.dateTime().toPyDateTime()
        dbconnection = db_utils.DbConnectionManager()
        try:
            in_clause, in_args = dbconnection.in_clause(obsids)
            sql = (
                f"SELECT obsid FROM obs_points WHERE obsid IN {in_clause} AND h_toc IS NULL"
            )
            obsid_with_h_toc_null = db_utils.sql_load_fr_db(
                sql, dbconnection=dbconnection, execute_args=in_args
            )[1]
            if obsid_with_h_toc_null:
                obsid_with_h_toc_null = [x[0] for x in obsid_with_h_toc_null]
                if self.checkBox_stop_if_null.isChecked():
                    any_nulls = [
                        obsid for obsid in obsids if obsid in obsid_with_h_toc_null
                    ]
                    if any_nulls:
                        common_utils.pop_up_info(
                            ru(
                                QCoreApplication.translate(
                                    "Calclvl",
                                    "Adjustment aborted! There seems to be NULL values in your table obs_points, column h_toc.",
                                )
                            ),
                            ru(QCoreApplication.translate("Calclvl", "Error")),
                        )
                        return None

                else:
                    obsids = [
                        obsid
                        for obsid in obsids
                        if obsid not in obsid_with_h_toc_null
                    ]

                if not obsids:
                    common_utils.pop_up_info(
                        ru(
                            QCoreApplication.translate(
                                "Calclvl", "Adjustment aborted! All h_tocs were NULL."
                            )
                        ),
                        ru(QCoreApplication.translate("Calclvl", "Error")),
                    )
                    return None

            in_clause, in_args = dbconnection.in_clause(obsids)
            ph = dbconnection.placeholder_sign()
            where_sql = (
                f"meas IS NOT NULL AND date_time >= {ph} AND date_time <= {ph} AND obsid IN {in_clause}"
            )
            where_sql_args = [fr_d_t, to_d_t] + in_args
            if not self.checkBox_overwrite_prev.isChecked():
                where_sql += """ AND level_masl IS NULL """

            sql1 = (
                "UPDATE w_levels "
                "SET h_toc = (SELECT obs_points.h_toc FROM obs_points WHERE w_levels.obsid = obs_points.obsid) "
                f"WHERE {where_sql}"
            )
            self.updated_h_tocs = self.log_msg(where_sql, where_sql_args)
            db_utils.sql_alter_db(sql1, all_args=[where_sql_args])

            where_sql += """ AND h_toc IS NOT NULL"""
            sql2 = f"UPDATE w_levels SET level_masl = h_toc - meas WHERE h_toc IS NOT NULL AND {where_sql}"
            self.updated_level_masl = self.log_msg(where_sql, where_sql_args)
            db_utils.sql_alter_db(sql2, all_args=[where_sql_args])

            common_utils.MessagebarAndLog.info(
                bar_msg=ru(
                    QCoreApplication.translate(
                        "Calclvl", "Calculation done, see log message panel"
                    )
                ),
                log_msg=ru(
                    QCoreApplication.translate(
                        "Calclvl",
                        "H_toc added and level_masl calculated for\nobsid;min date;max date;calculated number of measurements: \n%s",
                    )
                )
                % (self.updated_level_masl),
            )
            self.close()
        finally:
            try:
                dbconnection.closedb()
            except Exception:
                pass

    @fn_timer
    def calcall(self):
        obsids = db_utils.sql_load_fr_db("""SELECT DISTINCT obsid FROM w_levels""")[1]
        if obsids:
            obsids = [x[0] for x in obsids]
            self.calc(obsids)
        else:
            common_utils.pop_up_info(
                ru(
                    QCoreApplication.translate(
                        "Calclvl", "Adjustment aborted! No obsids in w_levels."
                    )
                ),
                ru(QCoreApplication.translate("Calclvl", "Error")),
            )

    @fn_timer
    def calcselected(self):
        obsids = ru(
            common_utils.getselectedobjectnames(self.layer), keep_containers=True
        )
        if not obsids:
            common_utils.pop_up_info(
                ru(
                    QCoreApplication.translate(
                        "Calclvl", "Adjustment aborted! No obsids selected."
                    )
                ),
                ru(QCoreApplication.translate("Calclvl", "Error")),
            )
        else:
            self.calc(obsids)

    def log_msg(self, where_sql: str, where_sql_args: List) -> str:
        res_sql = """SELECT DISTINCT obsid, min(date_time), max(date_time), count(obsid) FROM w_levels WHERE {} GROUP BY obsid"""
        log_msg = "\n".join(
            [
                ";".join(ru(row, keep_containers=True))
                for row in db_utils.sql_load_fr_db(
                    res_sql.format(where_sql), execute_args=where_sql_args
                )[1]
            ]
        )
        return log_msg
