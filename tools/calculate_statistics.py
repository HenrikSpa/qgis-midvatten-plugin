"""
/***************************************************************************
 This is the part of the Midvatten plugin that calculates some general statistics
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
from typing import Any, Dict, List, Optional, Tuple, Union, TYPE_CHECKING

import qgis.PyQt
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import QMainWindow

from midvatten.tools.utils import common_utils, gui_utils, db_utils
from midvatten.tools.utils.common_utils import returnunicode as ru

calculate_statistics_dialog = qgis.PyQt.uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "..", "ui", "calculate_statistics_ui.ui")
)[0]

if TYPE_CHECKING:
    from midvatten.tools.midvsettings import MidvSettings


class CalculateStatisticsGui(
    qgis.PyQt.QtWidgets.QMainWindow, calculate_statistics_dialog
):
    def __init__(self, parent: QMainWindow, midv_settings: "MidvSettings"):
        self.iface = parent

        self.ms = midv_settings
        qgis.PyQt.QtWidgets.QDialog.__init__(self, parent)
        self.setAttribute(qgis.PyQt.QtCore.Qt.WA_DeleteOnClose)
        self.setupUi(self)  # Required by Qt

        tables_columns = db_utils.tables_columns()
        self.db_browser = DbBrowser(tables_columns)

        self.grid_layout.addWidget(self.db_browser.widget, 0, 0)

        self.push_button_ok.clicked.connect(lambda x: self.calculate())

        self.push_button_cancel.clicked.connect(lambda: self.close())

        self.show()

    @common_utils.waiting_cursor
    @common_utils.general_exception_handler
    def calculate(self):
        table = self.db_browser.table_list
        column = self.db_browser.column_list
        obsids = common_utils.get_selected_features_as_tuple()

        if not all([table, column, obsids]):
            common_utils.MessagebarAndLog.critical(
                bar_msg=ru(
                    QCoreApplication.translate(
                        "CalculateStatisticsGui",
                        """Calculation failed, make sure you've selected a table, a column and features with a column obsid.""",
                    )
                )
            )
            return None

        sql_function_order = ["min", "max", "avg", "count"]
        stats = get_statistics(
            obsids, table, column, sql_function_order=sql_function_order, median=True
        )
        printlist = []
        printlist.append(
            ru(
                QCoreApplication.translate(
                    "Midvatten", "Obsid;Min;Median;Average;Max;Nr of values"
                )
            )
        )
        printlist.extend(
            [
                ";".join([ru(x) for x in (obsid, v[0], v[4], v[2], v[1], v[3])])
                for obsid, v in sorted(stats.items())
            ]
        )
        common_utils.MessagebarAndLog.info(
            bar_msg=ru(
                QCoreApplication.translate(
                    "Midvatten",
                    "Statistics for table %s column %s done, see log for results.",
                )
            )
            % (table, column),
            log_msg="\n".join(printlist),
            duration=15,
            button=True,
        )


class DbBrowser(gui_utils.DistinctValuesBrowser):

    def __init__(self, tables_columns: Dict[str, List[str]]):
        super().__init__(tables_columns)

        self.distinct_value_label.setVisible(False)
        self._distinct_value.setVisible(False)
        self.browser_label.setVisible(False)

    @staticmethod
    def get_distinct_values(tablename: str, columnname: str) -> List[Any]:
        return []


def get_statistics(
    obsids: List[str],
    table: str,
    column: str,
    sql_function_order: Optional[List[str]] = None,
    median: bool = True,
    dbconnection: None = None,
) -> Dict[str, List[Union[float, int]]]:
    if not isinstance(dbconnection, db_utils.DbConnectionManager):
        dbconnection = db_utils.DbConnectionManager()

    if sql_function_order is None:
        sql_function_order = ["min", "max", "avg", "count"]
    if not isinstance(obsids, (list, tuple)):
        obsids = [obsids]

    clause, args = dbconnection.in_clause(obsids)
    col_ident = dbconnection.ident(column)
    table_ident = dbconnection.ident(table)
    agg_cols = ", ".join([f"{func}({col_ident})" for func in sql_function_order])
    sql = f"select obsid, {agg_cols} from {table_ident} where obsid in {clause} group by obsid"
    _res = db_utils.get_sql_result_as_dict(
        sql, dbconnection=dbconnection, execute_args=args
    )[1]
    res = dict([(obsid, list(v[0])) for obsid, v in _res.items()])
    if median:
        [
            v.append(
                db_utils.calculate_median_value(table, column, obsid, dbconnection)
            )
            for obsid, v in res.items()
        ]
    return res


def get_statistics_for_single_obsid(
    obsid: str = "", table: str = "w_levels", data_columns: None = None
) -> Union[Tuple[str, List[Union[float, int]]], Tuple[str, List[Optional[int]]]]:
    statistics_list = [0] * 4

    if data_columns is None:
        data_columns = ["meas", "level_masl"]
    data_column = data_columns[0]  # default value

    # number of values, also decide wehter to use meas or level_masl in report
    dbconnection = db_utils.DbConnectionManager()
    ph = dbconnection.placeholder_sign()
    table_ident = dbconnection.ident(table)
    for column in data_columns:
        col_ident = dbconnection.ident(column)
        sql = f"select Count({col_ident}) from {table_ident} where obsid = {ph}"
        connection_ok, number_of_values = db_utils.sql_load_fr_db(
            sql, dbconnection=dbconnection, execute_args=(obsid,)
        )
        if (
            number_of_values and number_of_values[0][0] > statistics_list[2]
        ):  # this will select meas if meas >= level_masl
            data_column = column
            statistics_list[2] = number_of_values[0][0]

    # min value
    col_ident = dbconnection.ident(data_column)
    sql = f"select min({col_ident}) from {table_ident} where obsid = {ph}"
    connection_ok, min_value = db_utils.sql_load_fr_db(
        sql, dbconnection=dbconnection, execute_args=(obsid,)
    )
    if min_value:
        statistics_list[0] = min_value[0][0]

    # median value
    median_value = db_utils.calculate_median_value(table, data_column, obsid)
    if median_value:
        statistics_list[1] = median_value

    # max value
    sql = f"select max({col_ident}) from {table_ident} where obsid = {ph}"
    connection_ok, max_value = db_utils.sql_load_fr_db(
        sql, dbconnection=dbconnection, execute_args=(obsid,)
    )
    if max_value:
        statistics_list[3] = max_value[0][0]

    try:
        dbconnection.closedb()
    except Exception:
        pass

    return data_column, statistics_list
