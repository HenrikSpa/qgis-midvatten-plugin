"""
/***************************************************************************
 This is the part of the Midvatten plugin that returns a report with general observation point info,
 "drill report"for the selected obs_point.
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

import ast
import codecs
import json
import os

from collections import OrderedDict

import qgis
import qgis.PyQt
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtCore import QUrl, QDir
from qgis.PyQt.QtGui import QDesktopServices

from midvatten.tools.utils import (
    common_utils,
    db_utils,
    exceptions,
    layer_utils,
    message_utils,
    string_utils,
)
from midvatten.tools.utils.file_utils import templates_path, ui_path
from midvatten.tools.utils.gui_utils import WA_DeleteOnClose
from midvatten.tools.utils.html_utils import esc
from midvatten.tools.utils.string_utils import returnunicode as ru

_EMPTY_VALS = ("", "NULL")

custom_drillreport_dialog = qgis.PyQt.uic.loadUiType(ui_path("custom_drillreport.ui"))[
    0
]


class DrillreportUi(qgis.PyQt.QtWidgets.QMainWindow, custom_drillreport_dialog):
    def __init__(self, iface, ms):
        self.iface = iface

        self.ms = ms
        qgis.PyQt.QtWidgets.QMainWindow.__init__(self, iface.mainWindow())
        self.setAttribute(WA_DeleteOnClose)
        self.setupUi(self)  # Required by Qt

        self.stored_settings_key = "customdrillreportstoredsettings"
        self.stored_settings = common_utils.get_stored_settings(
            self.ms, self.stored_settings_key, {}
        )
        self.update_from_stored_settings(self.stored_settings)

        self.push_button_ok.clicked.connect(lambda x: self.drillreport())

        self.push_button_cancel.clicked.connect(lambda x: self.close())

        self.push_button_update_from_string.clicked.connect(
            lambda x: self.ask_and_update_stored_settings()
        )

    def show(self) -> None:
        super().show()
        self.activateWindow()

    @common_utils.general_exception_handler
    def drillreport(self):
        general_metadata = [
            x for x in self.general_metadata.toPlainText().split("\n") if x
        ]
        geo_metadata = [x for x in self.geo_metadata.toPlainText().split("\n") if x]
        strat_columns = [x for x in self.strat_columns.toPlainText().split("\n") if x]
        header_in_table = self.header_in_table.isChecked()
        skip_empty = self.skip_empty.isChecked()
        include_comments = self.include_comments.isChecked()
        obsids = sorted(
            layer_utils.get_selected_object_names(qgis.utils.iface.activeLayer())
        )  # selected obs_point is now found in obsid[0]
        general_metadata_header = self.general_metadata_header.text()
        geo_metadata_header = self.geo_metadata_header.text()
        strat_columns_header = self.strat_columns_header.text()
        comment_header = self.comment_header.text()
        empty_row_between_obsids = self.empty_row_between_obsids.isChecked()
        topleft_topright_colwidths = self.topleft_topright_colwidths.text().split(";")
        general_colwidth = self.general_colwidth.text().split(";")
        geo_colwidth = self.geo_colwidth.text().split(";")
        decimal_separator = self.decimal_separator.text()
        if not obsids:
            message_utils.MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "DrillreportUi",
                    "Must select at least 1 obsid in selected layer",
                )
            )
            raise exceptions.UsageError()
        self.save_stored_settings()
        drillrep = Drillreport(
            obsids,
            self.ms,
            general_metadata,
            geo_metadata,
            strat_columns,
            header_in_table,
            skip_empty,
            include_comments,
            general_metadata_header,
            geo_metadata_header,
            strat_columns_header,
            comment_header,
            empty_row_between_obsids,
            topleft_topright_colwidths,
            general_colwidth,
            geo_colwidth,
            decimal_separator,
        )

    @common_utils.general_exception_handler
    def ask_and_update_stored_settings(self):
        self.stored_settings = self.ask_for_stored_settings(self.stored_settings)
        self.update_from_stored_settings(self.stored_settings)
        self.save_stored_settings()

    def update_from_stored_settings(self, stored_settings):
        if isinstance(stored_settings, dict) and stored_settings:
            for attr, val in stored_settings.items():
                try:
                    selfattr = getattr(self, attr)
                except AttributeError:
                    pass
                else:
                    if isinstance(selfattr, qgis.PyQt.QtWidgets.QPlainTextEdit):
                        if isinstance(val, (list, tuple)):
                            val = "\n".join(val)
                        selfattr.setPlainText(val)
                    elif isinstance(selfattr, qgis.PyQt.QtWidgets.QCheckBox):
                        selfattr.setChecked(val)
                    elif isinstance(selfattr, qgis.PyQt.QtWidgets.QLineEdit):
                        selfattr.setText(val)
        else:
            # Settings:
            # --------------
            # The order and content of the geographical and general tables will follow general_metadata and geo_metadata list.
            # All obs_points columns could appear here except geometry.
            # The XY-reference system is added a bit down in the script to the list geo_data. The append has to be commented away
            # if it's not wanted.
            self.general_metadata.setPlainText(
                "\n".join(
                    [
                        "type",
                        "h_tocags",
                        "material",
                        "diam",
                        "drillstop",
                        "screen",
                        "drilldate",
                    ]
                )
            )

            self.geo_metadata.setPlainText(
                "\n".join(
                    [
                        "east",
                        "north",
                        "ne_accur",
                        "ne_source",
                        "h_source",
                        "h_toc",
                        "h_accur",
                    ]
                )
            )

            self.strat_columns.setPlainText(
                "\n".join(
                    [
                        "depth",
                        "geology",
                        "geoshort",
                        "capacity",
                        "development",
                        "comment",
                    ]
                )
            )

            self.general_metadata_header.setText(
                QCoreApplication.translate("Drillreport2", "General information")
            )
            self.geo_metadata_header.setText(
                QCoreApplication.translate("Drillreport2", "Geographical information")
            )
            self.strat_columns_header.setText(
                QCoreApplication.translate("Drillreport2", "Stratigraphy")
            )
            self.comment_header.setText(
                QCoreApplication.translate("Drillreport2", "Comment")
            )
            ##If False, the header will be written outside the table
            # header_in_table = True
            ##If True, headers/values in general_metadata and geo_metadata will be skipped if the value is empty, else they
            ##will be printed anyway
            # skip_empty = False
            # include_comments = True
            ###############

    def save_stored_settings(self):
        stored_settings = {}
        for attrname in [
            "general_metadata",
            "geo_metadata",
            "strat_columns",
            "header_in_table",
            "skip_empty",
            "include_comments",
            "general_metadata_header",
            "geo_metadata_header",
            "strat_columns_header",
            "comment_header",
            "empty_row_between_obsids",
            "topleft_topright_colwidths",
            "general_colwidth",
            "geo_colwidth",
            "decimal_separator",
        ]:
            try:
                attr = getattr(self, attrname)
            except Exception:
                message_utils.MessagebarAndLog.info(
                    log_msg=QCoreApplication.translate(
                        "DrillreportUi",
                        "Programming error. Attribute name %s didn't exist in self.",
                    )
                    % attrname
                )
            else:
                if isinstance(attr, qgis.PyQt.QtWidgets.QPlainTextEdit):
                    val = [x for x in attr.toPlainText().split("\n") if x]
                elif isinstance(attr, qgis.PyQt.QtWidgets.QCheckBox):
                    val = attr.isChecked()
                elif isinstance(attr, qgis.PyQt.QtWidgets.QLineEdit):
                    val = attr.text()
                else:
                    message_utils.MessagebarAndLog.info(
                        log_msg=QCoreApplication.translate(
                            "DrillreportUi",
                            "Programming error. The Qt-type %s is unhandled.",
                        )
                        % str(type(attr))
                    )
                    continue
                stored_settings[attrname] = val

        self.stored_settings = stored_settings

        common_utils.save_stored_settings(
            self.ms, self.stored_settings, self.stored_settings_key
        )

    def ask_for_stored_settings(self, stored_settings):
        old_string = string_utils.anything_to_string_representation(
            stored_settings,
            itemjoiner=",\n",
            pad="    ",
            dictformatter="{\n%s}",
            listformatter="[\n%s]",
            tupleformatter="(\n%s, )",
        )

        msg = QCoreApplication.translate(
            "DrillreportUi",
            "Replace the settings string with a new settings string.",
        )

        new_string = qgis.PyQt.QtWidgets.QInputDialog.getText(
            None,
            QCoreApplication.translate("DrillreportUi", "Edit settings string"),
            msg,
            qgis.PyQt.QtWidgets.QLineEdit.Normal,
            old_string,
        )
        if not new_string[1]:
            raise exceptions.UserInterruptError()

        new_string_text = ru(new_string[0])
        if not new_string_text:
            return {}

        try:
            try:
                as_dict = json.loads(new_string_text)
            except (json.JSONDecodeError, ValueError):
                as_dict = ast.literal_eval(new_string_text)
        except Exception as e:
            message_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "DrillreportUi",
                    "Translating string to dict failed, see log message panel",
                ),
                log_msg=str(e),
            )
            raise exceptions.UsageError()
        else:
            return as_dict


class Drillreport:  # general observation point info for the selected object
    def __init__(
        self,
        obsids,
        settingsdict,
        general_metadata,
        geo_metadata,
        strat_columns,
        header_in_table,
        skip_empty,
        include_comments,
        general_metadata_header,
        geo_metadata_header,
        strat_columns_header,
        comment_header,
        empty_row_between_obsids,
        topleft_topright_colwidths,
        general_colwidth,
        geo_colwidth,
        decimal_separator,
    ):

        reportfolder = os.path.join(QDir.tempPath(), "midvatten_reports")
        if not os.path.exists(reportfolder):
            os.makedirs(reportfolder)
        reportpath = os.path.join(reportfolder, "drill_report.html")
        logopath = templates_path("midvatten_logga.png")
        imgpath = templates_path()

        if len(obsids) == 0:
            message_utils.pop_up_info(
                QCoreApplication.translate(
                    "Drillreport", "Must select one or more obsids!"
                )
            )
            return None

        obsids = sorted(set(obsids))

        obs_points_translations = {
            "obsid": QCoreApplication.translate("Drillreport2", "obsid"),
            "name": QCoreApplication.translate("Drillreport2", "name"),
            "place": QCoreApplication.translate("Drillreport2", "place"),
            "type": QCoreApplication.translate("Drillreport2", "type"),
            "length": QCoreApplication.translate("Drillreport2", "length"),
            "drillstop": QCoreApplication.translate("Drillreport2", "drillstop"),
            "diam": QCoreApplication.translate("Drillreport2", "diam"),
            "material": QCoreApplication.translate("Drillreport2", "material"),
            "screen": QCoreApplication.translate("Drillreport2", "screen"),
            "capacity": QCoreApplication.translate("Drillreport2", "capacity"),
            "drilldate": QCoreApplication.translate("Drillreport2", "drilldate"),
            "wmeas_yn": QCoreApplication.translate("Drillreport2", "wmeas_yn"),
            "wlogg_yn": QCoreApplication.translate("Drillreport2", "wlogg_yn"),
            "east": QCoreApplication.translate("Drillreport2", "east"),
            "north": QCoreApplication.translate("Drillreport2", "north"),
            "ne_accur": QCoreApplication.translate("Drillreport2", "ne_accur"),
            "ne_source": QCoreApplication.translate("Drillreport2", "ne_source"),
            "h_toc": QCoreApplication.translate("Drillreport2", "h_toc"),
            "h_tocags": QCoreApplication.translate("Drillreport2", "h_tocags"),
            "h_gs": QCoreApplication.translate("Drillreport2", "h_gs"),
            "h_accur": QCoreApplication.translate("Drillreport2", "h_accur"),
            "h_syst": QCoreApplication.translate("Drillreport2", "h_syst"),
            "h_source": QCoreApplication.translate("Drillreport2", "h_source"),
            "source": QCoreApplication.translate("Drillreport2", "source"),
            "com_onerow": QCoreApplication.translate("Drillreport2", "com_onerow"),
            "com_html": QCoreApplication.translate("Drillreport2", "com_html"),
        }

        """
        thelist = [ "obsid", "stratid", "depthtop", "depthbot", "geology", "geoshort", "capacity", "development", "comment"]
        >>> y = '\n'.join(["'%s'"%x + ': ' + "QCoreApplication.translate('Drillreport2', '%s'),"%x for x in thelist])
        >>> print(y)
        """

        dbconnection = db_utils.DbConnectionManager()

        obs_points_cols = [
            "obsid",
            "name",
            "place",
            "type",
            "length",
            "drillstop",
            "diam",
            "material",
            "screen",
            "capacity",
            "drilldate",
            "wmeas_yn",
            "wlogg_yn",
            "east",
            "north",
            "ne_accur",
            "ne_source",
            "h_toc",
            "h_tocags",
            "h_gs",
            "h_accur",
            "h_syst",
            "h_source",
            "source",
            "com_onerow",
            "com_html",
        ]
        clause, args = dbconnection.in_clause(obsids)
        cols_sql = ", ".join([dbconnection.ident(c) for c in obs_points_cols])
        sql = f"SELECT {cols_sql} FROM {dbconnection.ident('obs_points')} WHERE obsid IN {clause} ORDER BY obsid"
        all_obs_points_data = ru(
            db_utils.get_sql_result_as_dict(
                sql, dbconnection=dbconnection, execute_args=args
            )[1],
            keep_containers=True,
        )

        if strat_columns:
            strat_sql_columns_list = [x.split(";")[0] for x in strat_columns]
            if "depth" in strat_sql_columns_list:
                strat_sql_columns_list.extend(["depthtop", "depthbot"])
                strat_sql_columns_list.remove("depth")
                strat_sql_columns_list = [
                    x for x in strat_sql_columns_list if x not in ("obsid")
                ]

            cols_sql = ", ".join(
                [dbconnection.ident(c) for c in strat_sql_columns_list]
            )
            strat_sql = f"SELECT obsid, {cols_sql} FROM stratigraphy WHERE obsid IN {clause} ORDER BY obsid, stratid"
            all_stratigrapy_data = ru(
                db_utils.get_sql_result_as_dict(
                    strat_sql,
                    dbconnection=dbconnection,
                    execute_args=args,
                )[1],
                keep_containers=True,
            )
        else:
            all_stratigrapy_data = {}
            strat_sql_columns_list = []

        crs = ru(
            db_utils.sql_load_fr_db(
                """SELECT srid FROM geometry_columns where f_table_name = 'obs_points'""",
                dbconnection=dbconnection,
            )[1][0][0]
        )
        crsname = ru(db_utils.get_srid_name(crs, dbconnection=dbconnection))

        dbconnection.closedb()

        f, rpt = self.open_file(", ".join(obsids), reportpath)
        rpt += r"""<html>"""
        for obsid in obsids:
            obs_points_data = all_obs_points_data[obsid][0]
            general_data_no_rounding = [x.split(";")[0] for x in general_metadata]
            general_rounding = [
                x.split(";")[1] if len(x.split(";")) == 2 else None
                for x in general_metadata
            ]
            general_data = [
                (
                    obs_points_translations.get(header, header),
                    obs_points_data[obs_points_cols.index(header) - 1],
                )
                for header in general_data_no_rounding
            ]
            if geo_metadata:
                geo_metadata_no_rounding = [x.split(";")[0] for x in geo_metadata]
                geo_rounding = [
                    x.split(";")[1] if len(x.split(";")) == 2 else None
                    for x in geo_metadata
                ]
                geo_data = [
                    (
                        obs_points_translations.get(header, header),
                        obs_points_data[obs_points_cols.index(header) - 1],
                    )
                    for header in geo_metadata_no_rounding
                ]
                if (
                    "east" in geo_metadata_no_rounding
                    or "north" in geo_metadata_no_rounding
                ):
                    geo_data.append(
                        (
                            QCoreApplication.translate(
                                "Drillreport2", "XY Reference system"
                            ),
                            "%s" % ("%s, " % crsname if crsname else "")
                            + "EPSG:"
                            + crs,
                        )
                    )
            else:
                geo_data = []
                geo_rounding = []

            strat_data = all_stratigrapy_data.get(obsid, None)

            if include_comments:
                comment_data = [
                    (header, obs_points_data[obs_points_cols.index(header) - 1])
                    for header in ("com_onerow", "com_html")
                    if all(
                        [
                            obs_points_data[obs_points_cols.index(header) - 1]
                            is not None,
                            obs_points_data[obs_points_cols.index(header) - 1].replace(
                                "NULL", ""
                            ),
                            obs_points_data[obs_points_cols.index(header) - 1].strip(),
                            'text-indent:0px;"><br /></p>'
                            not in obs_points_data[obs_points_cols.index(header) - 1],
                            'text-indent:0px;"></p>'
                            not in obs_points_data[obs_points_cols.index(header) - 1],
                            'text-indent:0px;">NULL</p>'
                            not in obs_points_data[
                                obs_points_cols.index(header) - 1
                            ].strip(),
                        ]
                    )
                ]
            else:
                comment_data = []

            rpt += self.write_obsid(
                obsid,
                general_data,
                geo_data,
                strat_data,
                comment_data,
                strat_columns,
                header_in_table=header_in_table,
                skip_empty=skip_empty,
                general_metadata_header=general_metadata_header,
                geo_metadata_header=geo_metadata_header,
                strat_columns_header=strat_columns_header,
                comment_header=comment_header,
                general_rounding=general_rounding,
                geo_rounding=geo_rounding,
                strat_sql_columns_list=strat_sql_columns_list,
                topleft_topright_colwidths=topleft_topright_colwidths,
                general_colwidth=general_colwidth,
                geo_colwidth=geo_colwidth,
                decimal_separator=decimal_separator,
            )
            rpt += r"""<p>    </p>"""
            if empty_row_between_obsids:
                rpt += r"""<p>empty_row_between_obsids</p>"""

        rpt += r"""</html>"""
        f.write(rpt)
        self.close_file(f, reportpath)

    def open_file(self, header, reportpath):
        # open connection to report file
        f = codecs.open(reportpath, "wb", "utf-8")
        # write some initiating html, header and also
        rpt = (
            r"""<meta http-equiv="content-type" content="text/html; charset=utf-8" />"""
        )
        rpt += r"""<head><title>%s %s</title></head>""" % (
            esc(header),
            QCoreApplication.translate(
                "Drillreport", "General report from Midvatten plugin for QGIS"
            ),
        )

        return f, rpt

    def close_file(self, f, reportpath):
        f.write("\n</p></body></html>")
        f.close()
        # print reportpath#debug
        url_status = QDesktopServices.openUrl(QUrl.fromLocalFile(reportpath))
        return url_status

    def obsid_header(self, obsid):
        return (
            r"""<h3 style="font-family:'Ubuntu';font-size:12pt; font-weight:600"><font size=4>%s</font></h3>"""
            % esc(obsid)
        )

    def write_obsid(
        self,
        obsid,
        general_data,
        geo_data,
        strat_data,
        comment_data,
        strat_columns,
        header_in_table=True,
        skip_empty=False,
        general_metadata_header="",
        geo_metadata_header="",
        strat_columns_header="",
        comment_header="",
        general_rounding=None,
        geo_rounding=None,
        strat_sql_columns_list=None,
        topleft_topright_colwidths=None,
        general_colwidth=None,
        geo_colwidth=None,
        decimal_separator=".",
    ):
        """This part only handles writing the information. It does not do any db data collection."""
        if general_rounding is None:
            general_rounding = []
        if geo_rounding is None:
            geo_rounding = []
        if strat_sql_columns_list is None:
            strat_sql_columns_list = []
        if topleft_topright_colwidths is None:
            topleft_topright_colwidths = []
        if general_colwidth is None:
            general_colwidth = []
        if geo_colwidth is None:
            geo_colwidth = []

        rpt = ""

        if not header_in_table:
            rpt += self.obsid_header(obsid)

        rpt += r"""<TABLE WIDTH=100% BORDER=1 CELLPADDING=1 class="no-spacing" CELLSPACING=0>"""

        if header_in_table:
            # Row 1, obsid header
            rpt += r"""<TR VALIGN=TOP>"""
            rpt += r"""<TD WIDTH=100% COLSPAN=2>"""
            rpt += self.obsid_header(obsid)
            rpt += r"""</TD>"""
            rpt += r"""</TR>"""

        # Row 2, general and geographical information
        rpt += r"""<TR VALIGN=TOP>"""
        if geo_data:
            if len(topleft_topright_colwidths) == 2:
                rpt += r"""<TD WIDTH=%s>""" % (topleft_topright_colwidths[0])
            else:
                rpt += r"""<TD WIDTH=60%>"""
        else:
            rpt += r"""<TD WIDTH=100% COLSPAN=2>"""

        rpt += self.write_two_col_table(
            general_data,
            general_metadata_header,
            skip_empty,
            general_rounding,
            general_colwidth,
            decimal_separator,
        )
        rpt += r"""</TD>"""

        if geo_data:
            if len(topleft_topright_colwidths) == 2:
                rpt += r"""<TD WIDTH=%s>""" % (topleft_topright_colwidths[1])
            else:
                rpt += r"""<TD WIDTH=40%>"""

            rpt += self.write_two_col_table(
                geo_data,
                geo_metadata_header,
                skip_empty,
                geo_rounding,
                geo_colwidth,
                decimal_separator,
            )
            rpt += r"""</TD>"""
        rpt += r"""</TR>"""

        # Row 3, stratigraphy and comments

        if strat_data or comment_data:
            rpt += r"""<TR VALIGN=TOP>"""
            rpt += r"""<TD WIDTH=100% COLSPAN=2>"""

            if strat_data:
                rpt += self.write_strat_data(
                    strat_data,
                    strat_columns,
                    strat_columns_header,
                    strat_sql_columns_list,
                    decimal_separator,
                )

            if comment_data:
                rpt += self.write_comment_data(comment_data, comment_header)

            rpt += r"""</TD>"""
            rpt += r"""</TR>"""
        rpt += r"""</TABLE>"""

        return rpt

    def write_two_col_table(
        self,
        data,
        table_header,
        skip_empty=False,
        column_rounding=None,
        col_widths=None,
        decimal_separator=".",
    ):
        if column_rounding is None:
            column_rounding = []

        if table_header:
            rpt = r"""<P><U><B><font size=3>%s</font></B></U></P>""" % table_header
        else:
            rpt = r""

        if not col_widths or len(col_widths) != 2:
            message_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "Drillreport2",
                    "Column width not entered correctly, must be like x;y. Was %s"
                    % str(col_widths),
                )
            )
            col_widths = ["2*", "3*"]

        rpt += rf"""<TABLE style="font-family:'Ubuntu'; font-size:8pt; font-weight:400; font-style:normal;" WIDTH=100% BORDER=0 CELLPADDING=0 class="no-spacing" CELLSPACING=0><COL WIDTH={col_widths[0]}><COL WIDTH={col_widths[1]}>"""

        rpt += r"""<p style="font-family:'Ubuntu'; font-size:8pt; font-weight:400; font-style:normal;">"""
        for idx, header_value in enumerate(data):
            header, value = header_value
            header = ru(header)
            value = ru(value) if ru(value) is not None and ru(value) != "NULL" else ""
            if skip_empty:
                if value and value != "NULL" and value != header:
                    try:
                        _test = float(value)
                    except ValueError:
                        pass
                    else:
                        pass
                        # if _test == 0.0:
                        #    continue
                else:
                    continue
            try:
                round = column_rounding[idx]
            except IndexError:
                pass
            else:
                if round is not None:
                    try:
                        _test = float(value)
                    except ValueError:
                        pass
                    else:
                        # Round the numbers to the maximum given rounding.
                        int_and_dec = value.split(".")
                        if len(int_and_dec) == 2:
                            len_dec = len(int_and_dec[1])
                            prec = min(len_dec, int(round))
                        else:
                            prec = int(round)

                        value = "{:.{prec}f}".format(float(value), prec=prec)

            if decimal_separator != ".":
                value = value.replace(".", decimal_separator)

            try:
                rpt += rf"""<TR VALIGN=TOP><TD WIDTH=33%><P><font size=1>{esc(header)}</font></P></TD><TD WIDTH=50%><P><font size=1>{esc(value)}</font></P></TD></TR>"""
            except UnicodeEncodeError:
                message_utils.MessagebarAndLog.critical(
                    bar_msg=QCoreApplication.translate(
                        "custom_drillreport",
                        "Writing drillreport failed, see log message panel",
                    ),
                    log_msg=QCoreApplication.translate(
                        "custom_drillreport",
                        "Writing header %s and value %s failed",
                    )
                    % (header, value),
                )
                raise
        rpt += r"""</p>"""
        rpt += r"""</TABLE>"""
        return rpt

    def write_strat_data(
        self,
        strat_data,
        _strat_columns,
        table_header,
        strat_sql_columns_list,
        decimal_separator,
    ):
        if table_header:
            rpt = r"""<P><U><B><font size=3>%s</font></B></U></P>""" % table_header
        else:
            rpt = r""
        strat_columns = [x.split(";")[0] for x in _strat_columns]

        col_widths = [
            x.split(";")[1] if len(x.split(";")) == 2 else "1*" for x in _strat_columns
        ]

        rpt += r"""<TABLE style="font-family:'Ubuntu'; font-size:8pt; font-weight:400; font-style:normal;" WIDTH=100% BORDER=0 CELLPADDING=0 class="no-spacing" CELLSPACING=0>"""
        for col_width in col_widths:
            rpt += rf"""<COL WIDTH={col_width}>"""
        rpt += r"""<p style="font-family:'Ubuntu'; font-size:8pt; font-weight:400; font-style:normal;">"""

        headers_txt = OrderedDict(
            [
                (
                    "stratid",
                    QCoreApplication.translate("Drillreport2_strat", "Layer number"),
                ),
                (
                    "depth",
                    QCoreApplication.translate("Drillreport2_strat", "level (m b gs)"),
                ),
                (
                    "depthtop",
                    QCoreApplication.translate(
                        "Drillreport2_strat", "top of layer (m b gs)"
                    ),
                ),
                (
                    "depthbot",
                    QCoreApplication.translate(
                        "Drillreport2_strat", "bottom of layer (m b gs)"
                    ),
                ),
                (
                    "geology",
                    QCoreApplication.translate(
                        "Drillreport2_strat", "geology, full text"
                    ),
                ),
                (
                    "geoshort",
                    QCoreApplication.translate("Drillreport2_strat", "geology, short"),
                ),
                (
                    "capacity",
                    QCoreApplication.translate("Drillreport2_strat", "capacity"),
                ),
                (
                    "development",
                    QCoreApplication.translate("Drillreport2_strat", "development"),
                ),
                (
                    "comment",
                    QCoreApplication.translate("Drillreport2_strat", "comment"),
                ),
            ]
        )

        if len(strat_data) > 0:
            rpt += r"""<TR VALIGN=TOP>"""
            for header in strat_columns:
                rpt += rf"""<TD><P><font size=2><u>{headers_txt[header]}</font></P></u></TD>"""
            rpt += r"""</TR>"""

            for rownr, row in enumerate(strat_data):
                rpt += r"""<TR VALIGN=TOP>"""
                for col in strat_columns:
                    if col == "depth":
                        try:
                            depthtop_idx = strat_sql_columns_list.index("depthtop")
                            depthbot_idx = strat_sql_columns_list.index("depthbot")
                        except ValueError:
                            message_utils.MessagebarAndLog.critical(
                                bar_msg=QCoreApplication.translate(
                                    "Drillreport2",
                                    "Programming error, depthtop and depthbot columns was supposed to exist",
                                )
                            )
                            rpt += r"""<TD><P><font size=1> </font></P></TD>"""
                        else:
                            depthtop = (
                                ""
                                if row[depthtop_idx] == "NULL"
                                else row[depthtop_idx].replace(".", decimal_separator)
                            )
                            depthbot = (
                                ""
                                if row[depthbot_idx] == "NULL"
                                else row[depthbot_idx].replace(".", decimal_separator)
                            )
                            rpt += r"""<TD><P><font size=1>{}</font></P></TD>""".format(
                                esc(" - ".join([depthtop, depthbot]))
                            )
                    else:
                        value_idx = strat_sql_columns_list.index(col)
                        value = "" if row[value_idx] == "NULL" else row[value_idx]
                        if col in ("depthtop", "depthbot") and decimal_separator != ".":
                            value = value.replace(".", decimal_separator)
                        rpt += rf"""<TD><P><font size=1>{esc(value)}</font></P></TD>"""

                rpt += r"""</TR>"""
        rpt += r"""</p>"""
        rpt += r"""</TABLE>"""

        return rpt

    def write_comment_data(self, comment_data, header):
        if comment_data:
            if header:
                rpt = rf"""<P><U><B><font size=3>{header}</font></B></U></P>"""
            else:
                rpt = r""

            rpt += r"""<p style="font-family:'Ubuntu'; font-size:8pt; font-weight:400; font-style:normal;"><font size=1>"""
            # com_html is schema-documented as "Multiline formatted comment in
            # html format" (definitions/create_db.sql) — a rich-text editor
            # field whose content is intentionally raw HTML, not a leaf value.
            # com_onerow is plain free text and must be escaped.
            rpt += r". ".join(
                [
                    ru(value) if col == "com_html" else esc(value)
                    for col, value in comment_data
                    if ru(value) not in _EMPTY_VALS
                ]
            )
            rpt += r"""</font></p>"""
        else:
            rpt = ""

        return rpt
