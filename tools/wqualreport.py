"""
/***************************************************************************
 This is the part of the Midvatten plugin that returns a report with water quality data for the selected obs_point.
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

import codecs
import logging
import os
import time  # for debugging
import traceback

from qgis.PyQt.QtCore import QCoreApplication

# midvatten modules
from midvatten.tools.utils import common_utils, db_utils
from midvatten.tools.utils.common_utils import returnunicode as ru
from midvatten.tools.wqualreport_core import (
    report_path,
    write_html_preamble,
    write_html_close,
    open_report_in_browser,
)

log = logging.getLogger(__name__)


class Wqualreport:  # extracts water quality data for selected objects, selected db and given table, results shown in html report
    def __init__(self, layer, settingsdict={}):
        # show the user this may take a long time...
        common_utils.start_waiting_cursor()

        self.settingsdict = settingsdict
        provider = layer.dataProvider()  # OGR provider
        kolumnindex = provider.fieldNameIndex(
            "obsid"
        )  # To find the column named 'obsid'
        observations = layer.getSelectedFeatures()

        reportpath = report_path()
        f = codecs.open(reportpath, "wb", "utf-8")
        write_html_preamble(f)

        dbconnection = db_utils.DbConnectionManager()

        for feature in observations:
            attributes = feature.attributes()
            obsid = attributes[kolumnindex]
            log.debug(
                "about to get data for " + obsid + ", at time: " + str(time.time())
            )
            report_data = self.get_data(
                self.settingsdict["database"], obsid, dbconnection
            )  # one observation at a time
            log.debug(
                "done with getting data for " + obsid + ", at time: " + str(time.time())
            )
            if report_data:
                self.write_html_report(report_data, f)
            log.debug(
                "wrote html report for " + obsid + ", at time: " + str(time.time())
            )

        dbconnection.closedb()
        write_html_close(f)
        f.close()

        common_utils.stop_waiting_cursor()  # now this long process is done and the cursor is back as normal

        if report_data:
            open_report_in_browser(reportpath)

    def get_data(
        self, db_path="", obsid="", dbconnection=None
    ):  # get_data method that returns a table with water quality data
        # Load all water quality parameters stored in two result columns: parameter, unit
        param_col = dbconnection.ident(self.settingsdict["wqual_paramcolumn"])
        wqual_table = dbconnection.ident(self.settingsdict["wqualtable"])
        ph = dbconnection.placeholder()
        if not (
            str(self.settingsdict["wqual_unitcolumn"]) == ""
        ):  # If there is a a given column for unit
            unit_col = dbconnection.ident(self.settingsdict["wqual_unitcolumn"])
            sql = f"SELECT DISTINCT {param_col}, {unit_col} FROM {wqual_table} WHERE obsid = {ph} ORDER BY {param_col}"
        else:  # IF no specific column exist for unit
            sql = f"SELECT DISTINCT {param_col}, {param_col} FROM {wqual_table} WHERE obsid = {ph} ORDER BY {param_col}"
        connection_ok, parameters = db_utils.sql_load_fr_db(
            sql, dbconnection, execute_args=(obsid,)
        )
        if not parameters:
            common_utils.MessagebarAndLog.warning(
                bar_msg=ru(
                    QCoreApplication.translate(
                        "Wqualreport",
                        "Debug, something is wrong, no parameters are found in table w_qual_lab for %s",
                    )
                )
                % obsid
            )
            return False
        log.debug("parameters for " + obsid + " is loaded at time: " + str(time.time()))
        # Load all date_times, stored in two result columns: reportnr, date_time
        dt_len = len(self.settingsdict["wqual_date_time_format"])
        if self.settingsdict[
            "wqual_sortingcolumn"
        ]:  # If there is a a specific sorting column
            sort_col = dbconnection.ident(self.settingsdict["wqual_sortingcolumn"])
            if dt_len > 16:
                sql = f"SELECT DISTINCT {sort_col}, date_time FROM {wqual_table} WHERE obsid = {ph} ORDER BY date_time"
            else:
                sql = f"SELECT DISTINCT under16.{sort_col}, under16.date_time FROM (SELECT {sort_col}, substr(date_time,1,{dt_len}) AS date_time FROM {wqual_table} WHERE obsid = {ph}) AS under16 ORDER BY date_time"
        else:  # IF no specific column exist for sorting
            if dt_len > 16:
                sql = f"SELECT DISTINCT date_time, date_time FROM {wqual_table} WHERE obsid = {ph} ORDER BY date_time"
            else:
                sql = f"SELECT DISTINCT under16.dummy, under16.date_time FROM (SELECT substr(date_time,1,{dt_len}) AS dummy, substr(date_time,1,{dt_len}) AS date_time FROM {wqual_table} WHERE obsid = {ph}) AS under16 ORDER BY date_time"
        connection_ok, date_times = db_utils.sql_load_fr_db(
            sql, dbconnection, execute_args=(obsid,)
        )

        log.debug(
            "loaded distinct date_time for the parameters for "
            + obsid
            + " at time: "
            + str(time.time())
        )
        if not date_times:
            common_utils.MessagebarAndLog.warning(
                bar_msg=ru(
                    QCoreApplication.translate(
                        "Wqualreport",
                        "Debug, Something is wrong, no parameters are found in table w_qual_lab for %s",
                    )
                )
                % obsid
            )
            return
        else:
            if any([x[1] is None for x in date_times]):
                common_utils.MessagebarAndLog.warning(
                    bar_msg=ru(
                        QCoreApplication.translate(
                            "Wqualreport",
                            "Warning: Found rows with datetime = NULL. Column without date_time might be aggregated from multiple reports!",
                        )
                    )
                )

        if self.settingsdict["wqual_sortingcolumn"]:
            self.nr_header_rows = 3
        else:
            self.nr_header_rows = 2

        report_table = [""] * (
            len(parameters) + self.nr_header_rows
        )  # Define size of report_table

        for i in range(len(parameters) + self.nr_header_rows):  # Fill the table with ''
            report_table[i] = [""] * (len(date_times) + 1)

        # Populate First 'column' w parameters

        for parametercounter, p_u in enumerate(parameters, start=self.nr_header_rows):
            p, u = p_u
            if not (self.settingsdict["wqual_unitcolumn"] == ""):
                if u:
                    # report_table[parametercounter][0] = p.encode(utils.getcurrentlocale()[1]) + ", " +  u.encode(utils.getcurrentlocale()[1])
                    report_table[parametercounter][0] = p + ", " + u
                else:
                    # report_table[parametercounter][0] = p.encode(utils.getcurrentlocale()[1])
                    report_table[parametercounter][0] = p
            else:
                # report_table[parametercounter][0] = p.encode(utils.getcurrentlocale()[1])
                report_table[parametercounter][0] = p

        log.debug(
            "Prepare report_table for " + obsid + ", at time: " + str(time.time())
        )
        report_table[0][0] = "obsid"
        report_table[1][0] = "date_time"
        for datecounter, r_d in enumerate(
            date_times, start=1
        ):  # date_times includes both report and date_time (or possibly date_time and date_time if there is no reportnr)
            r, d = r_d
            report_table[0][datecounter] = obsid
            report_table[1][datecounter] = d  # d is date_time
            if self.settingsdict["wqual_sortingcolumn"]:
                report_table[2][0] = self.settingsdict["wqual_sortingcolumn"]
                report_table[2][datecounter] = r

        log.debug(
            "now go for each parameter value for "
            + obsid
            + ", at time: "
            + str(time.time())
        )
        for datecounter, sorting_date_time in enumerate(
            date_times, start=1
        ):  # Loop through all report
            sorting, date_time = sorting_date_time

            # Parameter rows starts after date or sorting row
            for parametercounter, p_u in enumerate(
                parameters, start=self.nr_header_rows
            ):
                p, u = p_u
                ph = dbconnection.placeholder()
                value_col = dbconnection.ident(self.settingsdict["wqual_valuecolumn"])
                wqual_table = dbconnection.ident(self.settingsdict["wqualtable"])
                sql = f"SELECT {value_col} FROM {wqual_table} WHERE obsid = {ph}"
                execute_args = [obsid]
                if date_time is None or not date_time:
                    sql += r""" AND (date_time IS NULL OR date_time = '') """
                else:
                    if len(self.settingsdict["wqual_date_time_format"]) > 16:
                        sql += f" AND date_time = {ph} "
                        execute_args.append(date_time)
                    else:
                        sql += f" AND substr(date_time,1,{len(self.settingsdict['wqual_date_time_format'])}) = {ph} "
                        execute_args.append(date_time)

                sql += f" AND parameter = {ph} "
                execute_args.append(p)

                if self.settingsdict["wqual_unitcolumn"] and u:
                    unit_col = dbconnection.ident(self.settingsdict["wqual_unitcolumn"])
                    sql += f" AND {unit_col} = {ph} "
                    execute_args.append(u)

                if self.settingsdict["wqual_sortingcolumn"]:
                    sorting_col = dbconnection.ident(
                        self.settingsdict["wqual_sortingcolumn"]
                    )
                    sql += f" AND {sorting_col} = {ph} "
                    execute_args.append(sorting)

                connection_ok, recs = db_utils.sql_load_fr_db(
                    sql, dbconnection=dbconnection, execute_args=execute_args
                )
                # each value must be in unicode or string to be written as html report
                if recs:
                    try:
                        report_table[parametercounter][datecounter] = ru(recs[0][0])
                    except Exception:
                        report_table[parametercounter][datecounter] = ""
                        common_utils.MessagebarAndLog.warning(
                            bar_msg=ru(
                                QCoreApplication.translate(
                                    "Wqualreport",
                                    "Note!, the value for %s [%s] at %s, %s was not readable. Check your data!",
                                )
                            )
                            % (p, u, sorting, date_time)
                        )
                else:
                    report_table[parametercounter][datecounter] = " "

        self.htmlcols = (
            datecounter + 1
        )  # to be able to set a relevant width to the table
        return report_table

    def write_html_report(self, report_data, f):
        tabellbredd = 180 + 75 * self.htmlcols
        rpt = '<table width="'
        rpt += str(
            tabellbredd
        )  # set table total width from no of water quality analyses
        rpt += '" border="1">\n'
        f.write(rpt)

        for counter, sublist in enumerate(report_data):
            try:
                if counter < self.nr_header_rows:
                    rpt = "  <tr><th>"
                    rpt += '    </th><th width ="75">'.join(
                        [ru(x) if x is not None else "" for x in sublist]
                    )
                    rpt += "  </th></tr>\n"
                else:
                    rpt = "  <tr><td>"
                    rpt += '    </td><td align="right">'.join(
                        [ru(x) if x is not None else "" for x in sublist]
                    )
                    rpt += "  </td></tr>\n"
            except Exception:
                log.debug("here was an error: %s" % sublist)
            f.write(rpt)
        f.write("\n</table><p></p><p></p>")
