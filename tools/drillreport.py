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

import codecs
import os
from typing import Any, Dict, List, Optional, Tuple, Union

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import QProgressDialog

from midvatten.tools import wqualreport_core
from midvatten.tools.calculate_statistics import get_statistics_for_single_obsid
from midvatten.tools.drillreport_models import ObsPointsRow, StratigraphyRow
from midvatten.tools.utils import db_utils, layer_utils, midvatten_utils
from midvatten.tools.utils.file_utils import templates_path
from midvatten.tools.utils.html_utils import esc
from midvatten.tools.utils.string_utils import returnunicode as ru

_EMPTY_VALS = ("", "NULL")


class Drillreport:  # general observation point info for the selected object
    def __init__(self, iface, ms) -> None:
        self._iface = iface
        self._ms = ms

    def show(self) -> None:
        layer = self._iface.activeLayer()
        obsids = tuple(layer_utils.get_selected_object_names(layer))
        settingsdict = self._ms.settingsdict
        self._run_report(obsids, settingsdict)

    def _run_report(
        self,
        obsids: List[str] = None,
        settingsdict: Dict[str, Union[str, int, bool, float]] = None,
    ) -> None:
        if obsids is None:
            obsids = [""]
        if settingsdict is None:
            settingsdict = {}
        reportfolder = wqualreport_core.report_folder()
        reportpath = os.path.join(reportfolder, "drill_report.html")
        logopath = templates_path("midvatten_logga.png")
        imgpath = templates_path()

        if len(obsids) == 0:
            layer_utils.warn_no_selection()
            return None
        elif len(obsids) == 1:
            merged_question = False
        else:
            # Due to problems regarding speed when opening many tabs, only the merge mode is used.
            merged_question = True

        obsids = sorted(set(obsids))
        progress = QProgressDialog(
            QCoreApplication.translate("Drillreport", "Generating report…"),
            QCoreApplication.translate("Drillreport", "Cancel"),
            0,
            len(obsids),
        )
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        if merged_question:
            f, rpt = self.open_file(", ".join(obsids), reportpath)
            for i, obsid in enumerate(obsids):
                if progress.wasCanceled():
                    break
                progress.setValue(i)
                self.write_obsid(obsid, rpt, imgpath, logopath, f)
            progress.setValue(len(obsids))
            self.close_file(f, reportpath)
        else:
            for i, obsid in enumerate(obsids):
                if progress.wasCanceled():
                    break
                progress.setValue(i)
                f, rpt = self.open_file(obsid, reportpath)
                self.write_obsid(obsid, rpt, imgpath, logopath, f)
                url_status = self.close_file(f, reportpath)
            progress.setValue(len(obsids))

    def open_file(
        self, header: str, reportpath: str
    ) -> Tuple[codecs.StreamReaderWriter, str]:
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

    def close_file(self, f: codecs.StreamReaderWriter, reportpath: str) -> bool:
        f.write("\n</p></body></html>")
        f.close()
        # print reportpath#debug
        url_status = QDesktopServices.openUrl(QUrl.fromLocalFile(reportpath))
        return url_status

    def _locale_spec(self) -> Dict[str, Any]:
        """All locale-dependent report content in one place.

        The two locales deliberately keep their historical quirks so output
        stays byte-identical with the pre-dedup implementation: stratigraphy
        column widths differ, and the Swedish coordinate rows omit the comma
        when the CRS has no name.
        """
        if midvatten_utils.is_locale_swedish():
            return {
                "img": "for_general_report_sv.png",
                "general": "Allmän information",
                "strat": "Lagerföljd",
                "comments": "Kommentarer",
                "wlevels": "Vattennivåer",
                "upper_left": {
                    "name": "originalbenämning",
                    "type": "obstyp",
                    "length": "djup (m fr my t botten)",
                    "h_toc": "röröverkant (möh)",
                    "h_tocags": "rörövermått (m ö my)",
                    "h_gs": "markytans nivå, my (möh)",
                    "h_accur": "onoggrannhet i höjd, avser rök (m)",
                    "east": "östlig koordinat",
                    "north": "nordlig koordinat",
                    "ne_accur": "lägesonoggrannhet",
                    "material": "material",
                    "diam": "innerdiameter (mm)",
                    "drillstop": "borrningens avslut",
                    "screen": "filter/spets",
                    "drilldate": "borrningen avslutades",
                    "capacity": "kapacitet/vg på spetsnivå",
                    "place": "fastighet/plats",
                    "source": "referens",
                    "ne_source": "lägesangivelsens ursprung",
                    "h_source": "höjdangivelsens ursprung",
                },
                "crs_omit_empty_name": True,
                "strat_widths": (17, 27, 17, 5, 9, 27),
                "strat_headers": (
                    "nivå (mumy)",
                    "jordart, fullst beskrivn",
                    "huvudfraktion",
                    "vg",
                    "stänger?",
                    "kommentar",
                ),
                "unit_meas": " m u rök<br>",
                "unit_masl": " m ö h<br>",
                "stat_count": "Antal nivåmätningar: ",
                "stat_max": "Högsta uppmätta nivå: ",
                "stat_median": "Medianvärde för nivå: ",
                "stat_min": "Lägsta uppmätta nivå: ",
            }

        def tr(text: str) -> str:
            return QCoreApplication.translate("Drillreport", text)

        return {
            "img": "for_general_report.png",
            "general": tr("General information"),
            "strat": tr("Stratigraphy"),
            "comments": tr("Comments"),
            "wlevels": tr("Water levels"),
            "upper_left": {
                "name": tr("original name"),
                "type": tr("obs type"),
                "length": tr("depth (m fr gs to bottom)"),
                "h_toc": tr("top of casing, toc (masl)"),
                "h_tocags": tr("distance toc-gs, tocags (mags)"),
                "h_gs": tr("ground surface level, gs (masl)"),
                "h_accur": tr("elevation accuracy (m)"),
                "east": tr("eastern coordinate"),
                "north": tr("northern coordinate"),
                "ne_accur": tr("position accuracy"),
                "material": tr("material"),
                "diam": tr("inner diameter (mm)"),
                "drillstop": tr("drill stop"),
                "screen": tr("screen type"),
                "drilldate": tr("drill date"),
                "capacity": tr("capacity"),
                "place": tr("place"),
                "source": tr("reference"),
                "ne_source": tr("source for position"),
                "h_source": tr("source for elevation"),
            },
            "crs_omit_empty_name": False,
            "strat_widths": (15, 27, 17, 9, 13, 21),
            "strat_headers": (
                tr("level (m b gs)"),
                tr("geology, full text"),
                tr("geology, short"),
                tr("capacity"),
                tr("development"),
                tr("comment"),
            ),
            "unit_meas": tr(" m below toc") + "<br>",
            "unit_masl": tr(" m above sea level") + "<br>",
            "stat_count": tr("Number of water level measurements: "),
            "stat_max": tr("Highest measured water level: "),
            "stat_median": tr("Median water level: "),
            "stat_min": tr("Lowest measured water level: "),
        }

    @staticmethod
    def _row(label: str, value: str, width: int = 50) -> str:
        return f"<TR VALIGN=TOP><TD WIDTH=33%>{esc(label)}</TD><TD WIDTH={width}%>{esc(value)}</TD></TR>"

    def write_obsid(
        self,
        obsid: str,
        rpt: str,
        imgpath: str,
        logopath: str,
        f: codecs.StreamReaderWriter,
    ) -> None:
        spec = self._locale_spec()
        rpt += r"""<html><TABLE WIDTH=100% BORDER=0 CELLPADDING=1 CELLSPACING=1><TR VALIGN=TOP><TD WIDTH=15%><h3 style="font-family:'arial';font-size:18pt; font-weight:600">"""
        rpt += esc(obsid)
        rpt += f'</h3><img src="{os.path.join(imgpath, spec["img"])}" /><br><img src=\''
        rpt += logopath
        rpt += """' /></TD><TD WIDTH=85%><TABLE WIDTH=100% BORDER=1 CELLPADDING=4 CELLSPACING=3><TR VALIGN=TOP><TD WIDTH=50%><P><U><B>"""
        rpt += spec["general"]
        rpt += r"""</B></U></P><TABLE style="font-family:'arial'; font-size:10pt; font-weight:400; font-style:normal;" WIDTH=100% BORDER=0 CELLPADDING=0 CELLSPACING=1><COL WIDTH=43*><COL WIDTH=43*>"""
        f.write(rpt)

        # GENERAL DATA UPPER LEFT QUADRANT
        connection_ok, general_data = self.get_data(obsid, "obs_points")
        if connection_ok:
            result2 = db_utils.sql_load_fr_db(
                r"""SELECT srid FROM geometry_columns where f_table_name = 'obs_points'"""
            )[1][0][0]
            crs = ru(result2)  # 1st we need crs
            result3 = db_utils.get_srid_name(result2)
            crs_name = ru(result3)  # and crs name
            f.write(self.rpt_upper_left(general_data, crs, crs_name, spec))

            rpt = r"""</TABLE></TD><TD WIDTH=50%><P><U><B>"""
            rpt += spec["strat"]
            rpt += r"""</B></U></P><TABLE style="font-family:'arial'; font-size:10pt; font-weight:400; font-style:normal;" WIDTH=100% BORDER=0 CELLPADDING=0 CELLSPACING=1><COL WIDTH=43*><COL WIDTH=43*><COL WIDTH=43*><COL WIDTH=43*><COL WIDTH=43*><COL WIDTH=43*>"""
            f.write(rpt)

            # STRATIGRAPHY DATA UPPER RIGHT QUADRANT
            strat_data = self.get_data(obsid, "stratigraphy")[1]
            f.write(self.rpt_upper_right(strat_data, spec))

            rpt = r"""</TABLE></TD></TR><TR VALIGN=TOP><TD WIDTH=50%><P><U><B>"""
            rpt += spec["comments"]
            rpt += r"""</B></U></P>"""
            f.write(rpt)

            # COMMENTS LOWER LEFT QUADRANT
            f.write(self.rpt_lower_left(general_data))

            rpt = r"""</TD><TD WIDTH=50%><P><U><B>"""
            rpt += spec["wlevels"]
            rpt += r"""</B></U></P>"""
            f.write(rpt)

            # WATER LEVEL STATISTICS LOWER RIGHT QUADRANT
            meas_or_level_masl, statistics = get_statistics_for_single_obsid(obsid)
            f.write(self.rpt_lower_right(statistics, meas_or_level_masl, spec))

            f.write(r"""</TD></TR></TABLE></TD></TR></TABLE>""")

    def rpt_upper_left(
        self,
        general_data: List[ObsPointsRow],
        crs: str,
        crs_name: str,
        spec: Dict[str, Any],
    ) -> str:
        labels = spec["upper_left"]
        r = general_data[0]
        h_syst_suffix = " (" + ru(r.h_syst) + ")" if ru(r.h_syst) != "" else ""
        if crs_name or not spec["crs_omit_empty_name"]:
            crs_suffix = " (" + crs_name + ", EPSG:" + crs + ")"
        else:
            crs_suffix = " (EPSG:" + crs + ")"

        rpt = r"""<p style="font-family:'arial'; font-size:8pt; font-weight:400; font-style:normal;">"""
        if ru(r.name) not in _EMPTY_VALS and ru(r.name) != ru(r.obsid):
            rpt += self._row(labels["name"], ru(r.name), width=67)
        if ru(r.type) not in _EMPTY_VALS:
            rpt += self._row(labels["type"], ru(r.type))
        if ru(r.length) not in _EMPTY_VALS:
            rpt += self._row(labels["length"], ru(r.length))
        if ru(r.h_toc) not in _EMPTY_VALS:
            rpt += self._row(labels["h_toc"], ru(r.h_toc) + h_syst_suffix)
        if ru(r.h_tocags) not in _EMPTY_VALS and ru(r.h_tocags) not in ("0", "0.0"):
            rpt += self._row(labels["h_tocags"], ru(r.h_tocags))
        if ru(r.h_gs) not in _EMPTY_VALS:
            rpt += self._row(labels["h_gs"], ru(r.h_gs) + h_syst_suffix)
        if ru(r.h_accur) not in _EMPTY_VALS:
            rpt += self._row(labels["h_accur"], ru(r.h_accur))
        if ru(r.east) not in _EMPTY_VALS:
            rpt += self._row(labels["east"], ru(r.east) + crs_suffix)
        if ru(r.north) not in _EMPTY_VALS:
            rpt += self._row(labels["north"], ru(r.north) + crs_suffix)
        if ru(r.east) not in _EMPTY_VALS and ru(r.north) != "" and ru(r.ne_accur) != "":
            rpt += self._row(labels["ne_accur"], ru(r.ne_accur))
        if ru(r.material) not in _EMPTY_VALS:
            rpt += self._row(labels["material"], ru(r.material))
        if ru(r.diam) not in _EMPTY_VALS:
            rpt += self._row(labels["diam"], ru(r.diam))
        if ru(r.drillstop) not in _EMPTY_VALS:
            rpt += self._row(labels["drillstop"], ru(r.drillstop))
        if ru(r.screen) not in _EMPTY_VALS:
            rpt += self._row(labels["screen"], ru(r.screen))
        if ru(r.drilldate) not in _EMPTY_VALS:
            rpt += self._row(labels["drilldate"], ru(r.drilldate))
        if ru(r.capacity) not in _EMPTY_VALS:
            rpt += self._row(labels["capacity"], ru(r.capacity))
        if ru(r.place) not in _EMPTY_VALS:
            rpt += self._row(labels["place"], ru(r.place))
        if ru(r.source) not in _EMPTY_VALS:
            rpt += self._row(labels["source"], ru(r.source))
        rpt += r"""</p>"""
        if ru(r.ne_source) not in _EMPTY_VALS:
            rpt += self._row(labels["ne_source"], ru(r.ne_source))
        if ru(r.h_source) not in _EMPTY_VALS:
            rpt += self._row(labels["h_source"], ru(r.h_source))
        return rpt

    def rpt_upper_right(
        self,
        strat_data: List[StratigraphyRow],
        spec: Dict[str, Any],
    ) -> str:
        widths = spec["strat_widths"]
        rpt = r"""<p style="font-family:'arial'; font-size:10pt; font-weight:400; font-style:normal;">"""
        if len(strat_data) > 0:
            rpt += r"""<TR VALIGN=TOP>"""
            for width, header in zip(widths, spec["strat_headers"]):
                rpt += f"<TD WIDTH={width}%><P><u>" + header + "</P></u></TD>"
            rpt += "</TR>"
        for row in strat_data:
            cells = [
                "" if ru(value) == "NULL" else esc(value)
                for value in (
                    row.depthtop,
                    row.depthbot,
                    row.geology,
                    row.geoshort,
                    row.capacity,
                    row.development,
                    row.comment,
                )
            ]
            columns = [cells[0] + " - " + cells[1]] + cells[2:]
            rpt += r"""<TR VALIGN=TOP>"""
            for width, column in zip(widths, columns):
                rpt += f"<TD WIDTH={width}%><P>" + column + "</P></TD>"
            rpt += "</TR>"
        rpt += r"""</p>"""
        return rpt

    def rpt_lower_left(
        self,
        general_data: List[ObsPointsRow],
    ) -> str:
        r = general_data[0]
        rpt = r"""<p style="font-family:'arial'; font-size:10pt; font-weight:400; font-style:normal;">"""
        if ru(r.com_onerow) not in _EMPTY_VALS:
            rpt += esc(r.com_onerow)
        if ru(r.com_html) not in _EMPTY_VALS:
            # com_html is schema-documented as "Multiline formatted comment in
            # html format" (definitions/create_db.sql) — a rich-text editor
            # field whose content is intentionally raw HTML, not a leaf value.
            rpt += ru(r.com_html)
        rpt += r"""</p>"""
        return rpt

    def rpt_lower_right(
        self,
        statistics: List[Optional[Union[float, int]]],
        meas_or_level_masl: str,
        spec: Dict[str, Any],
    ) -> str:
        unit = spec["unit_meas"] if meas_or_level_masl == "meas" else spec["unit_masl"]
        rpt = r"""<p style="font-family:'arial'; font-size:10pt; font-weight:400; font-style:normal;">"""
        if ru(statistics[2]) != "" and ru(statistics[2]) != "0":
            rpt += spec["stat_count"] + esc(statistics[2]) + "<br>"
            if ru(statistics[0]) != "":
                rpt += spec["stat_max"] + esc(statistics[0]) + unit
            if ru(statistics[1]) != "":
                rpt += spec["stat_median"] + esc(statistics[1]) + unit
            if ru(statistics[3]) != "":
                rpt += spec["stat_min"] + esc(statistics[3]) + unit
        rpt += r"""</p>"""
        return rpt

    def get_data(
        self,
        obsid: str = "",
        tablename: str = "",
    ) -> Tuple[
        bool,
        Union[List[ObsPointsRow], List[StratigraphyRow], List[Any]],
    ]:
        """Load data from obs_points or stratigraphy. Returns (ok, rows)."""
        dbconnection = db_utils.DbConnectionManager()
        table_ident = dbconnection.ident(tablename)
        obsid_literal = db_utils.sql_literal(obsid)
        sql = f"SELECT * FROM {table_ident} WHERE obsid = {obsid_literal}"
        if tablename == "stratigraphy":
            sql += " ORDER BY stratid"
        connection_ok, raw_rows = db_utils.sql_load_fr_db(sql, dbconnection)
        if not connection_ok or not raw_rows:
            return connection_ok, []

        if tablename in ("obs_points", "stratigraphy"):
            columns = db_utils.tables_columns(
                table=tablename, dbconnection=dbconnection
            )
            col_list = columns.get(tablename, [])
            if tablename == "obs_points":
                return connection_ok, [
                    ObsPointsRow.from_row(row, col_list) for row in raw_rows
                ]
            return connection_ok, [
                StratigraphyRow.from_row(row, col_list) for row in raw_rows
            ]
        return connection_ok, raw_rows
