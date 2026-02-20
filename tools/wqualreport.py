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
import os
import time  # for debugging

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtCore import QUrl, QDir
from qgis.PyQt.QtGui import QDesktopServices

# midvatten modules
from midvatten.tools.utils import common_utils, db_utils
from midvatten.tools.utils.common_utils import returnunicode as ru


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

        reportfolder = os.path.join(QDir.tempPath(), "midvatten_reports")
        if not os.path.exists(reportfolder):
            os.makedirs(reportfolder)
        reportpath = os.path.join(reportfolder, "w_qual_report.html")
        # f = open(reportpath, "wb" )
        f = codecs.open(reportpath, "wb", "utf-8")

        # write some initiating html
        rpt = r"""<head><title>%s</title></head>""" % ru(
            QCoreApplication.translate(
                "Wqualreport", "water quality report from Midvatten plugin for QGIS"
            )
        )
        rpt += r""" <meta http-equiv="content-type" content="text/html; charset=utf-8" />"""  # NOTE, all report data must be in 'utf-8'
        rpt += "<html><body>"
        # rpt += "<table width=\"100%\" border=\"1\">\n"
        # rpt2 = rpt.encode("utf-8")
        f.write(rpt)

        dbconnection = db_utils.DbConnectionManager()

        for feature in observations:
            attributes = feature.attributes()
            obsid = attributes[kolumnindex]
            try:
                print(
                    "about to get data for " + obsid + ", at time: " + str(time.time())
                )  # debug
            except Exception:
                pass
            report_data = self.get_data(
                self.settingsdict["database"], obsid, dbconnection
            )  # one observation at a time
            try:
                print(
                    "done with getting data for "
                    + obsid
                    + ", at time: "
                    + str(time.time())
                )  # debug
            except Exception:
                pass
            if report_data:
                self.write_html_report(report_data, f)
            try:
                print(
                    "wrote html report for " + obsid + ", at time: " + str(time.time())
                )  # debug
            except Exception:
                pass

        dbconnection.closedb()
        # write some finishing html and close the file
        f.write("\n</body></html>")
        f.close()

        common_utils.stop_waiting_cursor()  # now this long process is done and the cursor is back as normal

        if report_data:
            QDesktopServices.openUrl(QUrl.fromLocalFile(reportpath))

    def get_data(
        self, db_path="", obsid="", dbconnection=None
    ):  # get_data method that returns a table with water quality data
        # Load all water quality parameters stored in two result columns: parameter, unit
        if not (
            str(self.settingsdict["wqual_unitcolumn"]) == ""
        ):  # If there is a a given column for unit
            sql = (
                r"""select distinct """
                + self.settingsdict["wqual_paramcolumn"]
                + """, """
            )
            sql += self.settingsdict["wqual_unitcolumn"]
            sql += r""" from """
        else:  # IF no specific column exist for unit
            sql = (
                r"""select distinct """
                + self.settingsdict["wqual_paramcolumn"]
                + """, """
                + self.settingsdict["wqual_paramcolumn"]
                + """ from """
            )  # The twice selection of parameter is a dummy to keep same structure (2 cols) of sql-answer as if a unit column exists
        sql += self.settingsdict["wqualtable"]
        sql += r""" where obsid = '"""
        sql += obsid
        sql += r"""' ORDER BY """ + self.settingsdict["wqual_paramcolumn"]
        connection_ok, parameters = db_utils.sql_load_fr_db(sql, dbconnection)
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
        try:
            print(
                "parameters for " + obsid + " is loaded at time: " + str(time.time())
            )  # debug
        except Exception:
            pass
        # Load all date_times, stored in two result columns: reportnr, date_time
        if self.settingsdict[
            "wqual_sortingcolumn"
        ]:  # If there is a a specific sorting column
            if len(self.settingsdict["wqual_date_time_format"]) > 16:
                sql = r"""select distinct """
                sql += self.settingsdict["wqual_sortingcolumn"]
                sql += r""", date_time from """  # including parameters
            else:
                sql = (
                    r"""select distinct under16.%s, under16.date_time from (select %s, substr(date_time,1,%s) as date_time from """
                    % (
                        self.settingsdict["wqual_sortingcolumn"],
                        self.settingsdict["wqual_sortingcolumn"],
                        len(self.settingsdict["wqual_date_time_format"]),
                    )
                )
        else:  # IF no specific column exist for sorting
            if len(self.settingsdict["wqual_date_time_format"]) > 16:
                sql = r"""select distinct date_time, date_time from """  # The twice selection of date_time is a dummy to keep same structure (2 cols) of sql-answer as if reportnr exists
            else:
                sql = (
                    r"""select distinct under16.dummy, under16.date_time from (select substr(date_time,1,%s) as dummy, substr(date_time,1,%s) as date_time from """
                    % (
                        len(self.settingsdict["wqual_date_time_format"]),
                        len(self.settingsdict["wqual_date_time_format"]),
                    )
                )  # The twice selection of date_time is a dummy to keep same structure (2 cols) of sql-answer as if reportnr exists
        sql += self.settingsdict["wqualtable"]
        sql += """ where obsid = '"""
        sql += obsid
        if len(self.settingsdict["wqual_date_time_format"]) > 16:
            sql += """' ORDER BY date_time"""
        else:
            sql += """') AS under16 ORDER BY date_time"""
        # sql2 = unicode(sql) #To get back to unicode-string
        connection_ok, date_times = db_utils.sql_load_fr_db(
            sql, dbconnection
        )  # Send SQL-syntax to cursor,

        try:
            print(
                "loaded distinct date_time for the parameters for "
                + obsid
                + " at time: "
                + str(time.time())
            )  # debug
        except Exception:
            pass
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

        try:
            print(
                "Prepare report_table for " + obsid + ", at time: " + str(time.time())
            )  # debug
        except Exception:
            pass
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

        try:
            print(
                "now go for each parameter value for "
                + obsid
                + ", at time: "
                + str(time.time())
            )  # debug
        except Exception:
            pass
        for datecounter, sorting_date_time in enumerate(
            date_times, start=1
        ):  # Loop through all report
            sorting, date_time = sorting_date_time

            # Parameter rows starts after date or sorting row
            for parametercounter, p_u in enumerate(
                parameters, start=self.nr_header_rows
            ):
                p, u = p_u
                ph = dbconnection.placeholder_sign()
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
                    sorting_col = dbconnection.ident(self.settingsdict["wqual_sortingcolumn"])
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
                try:
                    print("here was an error: %s" % sublist)
                except Exception:
                    pass
            f.write(rpt)
        f.write("\n</table><p></p><p></p>")
