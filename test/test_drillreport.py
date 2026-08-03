"""
/***************************************************************************
 This part of the Midvatten plugin tests the stratigraphy plot.

 This part is to a big extent based on QSpatialite plugin.
                             -------------------
        begin                : 2017-10-17
        copyright            : (C) 2016 by joskal (HenrikSpa)
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

import re

from unittest import mock
import pytest
from qgis.PyQt import QtCore

from midvatten.test import utils_for_tests
from midvatten.tools import wqualreport_core
from midvatten.tools.drillreport import Drillreport
from midvatten.tools.utils import db_utils


@pytest.fixture(autouse=True)
def _pin_report_folder(tmp_path, monkeypatch):
    """report_folder() (Task 8 hardening) now returns a fresh mkdtemp() dir
    on every call. Pin it to a single tmp_path per test so the report
    written by _run_report() and the path this test reads back agree on
    the same directory."""
    monkeypatch.setattr(wqualreport_core, "report_folder", lambda: str(tmp_path))


def _normalize_template_paths(report: str) -> str:
    """Normalize machine-specific absolute template paths to the canonical
    form used in the reference strings."""
    report = re.sub(
        r"""src="[^"]+/templates/""",
        """src="midvatten/tools/../templates/""",
        report,
    )
    return re.sub(
        r"""src='[^']+/templates/""",
        """src='midvatten/tools/../templates/""",
        report,
    )


class DrillreportMixin:
    @mock.patch("midvatten.tools.drillreport.QDesktopServices.openUrl")
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    @mock.patch("midvatten.tools.utils.message_utils.pop_up_info", autospec=True)
    def test_drillreport(self, mock_skippopup, mock_messagebar, openurl, tmp_path):
        """
        :param mock_skippopup:
        :param mock_messagebar:
        :return:
        """
        # QDesktopServices.openUrl(
        db_utils.sql_alter_db(
            """INSERT INTO obs_points (obsid, h_gs, geometry) VALUES ('1', 5, ST_GeomFromText('POINT(633466 711659)', 3006))"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO obs_points (obsid, h_gs, geometry) VALUES ('2', 10, ST_GeomFromText('POINT(6720727 016568)', 3006))"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO obs_points (obsid, h_gs, geometry) VALUES ('3', 20, ST_GeomFromText('POINT(6720728 016569)', 3006))"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels (obsid, date_time, h_toc, level_masl) VALUES ('1', '2021-01-01 00:00', 20, 123)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels (obsid, date_time, h_toc, level_masl) VALUES ('2', '2021-01-01 00:00', 20, NULL)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO stratigraphy (obsid, stratid, depthtop, depthbot, geology, geoshort, capacity, development) VALUES ('1', 1, 0, 1, 'sand', 'sand', '3', 'j')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO stratigraphy (obsid, stratid, depthtop, depthbot, geology, geoshort, capacity, development) VALUES ('1', 2, 1, 4.5, 'morän', 'morän', '3', 'j')"""
        )

        # print(str(self.vlayer.isValid()))
        # print(str(db_utils.sql_load_fr_db('select * from obs_points')))
        # print(str(db_utils.sql_load_fr_db('select * from stratigraphy')))
        dlg = Drillreport(self.iface, self.midvatten.ms)
        dlg._run_report(("1", "2", "3"), self.midvatten.ms.settingsdict)

        print(f"{mock_messagebar.mock_calls=}")

        reportpath = str(tmp_path / "drill_report.html")
        assert mock.call(QtCore.QUrl.fromLocalFile(reportpath)) in openurl.mock_calls

        with open(reportpath) as f:
            report = "".join(f.readlines())
        print(str(report))

        # templates_path() returns an absolute path to <plugin>/templates/.
        report = _normalize_template_paths(report)
        print(str(report))
        ref = """<meta http-equiv="content-type" content="text/html; charset=utf-8" /><head><title>1, 2, 3 General report from Midvatten plugin for QGIS</title></head><html><TABLE WIDTH=100% BORDER=0 CELLPADDING=1 CELLSPACING=1><TR VALIGN=TOP><TD WIDTH=15%><h3 style="font-family:'arial';font-size:18pt; font-weight:600">1</h3><img src="midvatten/tools/../templates/for_general_report_sv.png" /><br><img src='midvatten/tools/../templates/midvatten_logga.png' /></TD><TD WIDTH=85%><TABLE WIDTH=100% BORDER=1 CELLPADDING=4 CELLSPACING=3><TR VALIGN=TOP><TD WIDTH=50%><P><U><B>Allmän information</B></U></P><TABLE style="font-family:'arial'; font-size:10pt; font-weight:400; font-style:normal;" WIDTH=100% BORDER=0 CELLPADDING=0 CELLSPACING=1><COL WIDTH=43*><COL WIDTH=43*><p style="font-family:'arial'; font-size:8pt; font-weight:400; font-style:normal;"><TR VALIGN=TOP><TD WIDTH=33%>markytans nivå, my (möh)</TD><TD WIDTH=50%>5.0</TD></TR><TR VALIGN=TOP><TD WIDTH=33%>östlig koordinat</TD><TD WIDTH=50%>633466.0 (SWEREF99 TM, EPSG:3006)</TD></TR><TR VALIGN=TOP><TD WIDTH=33%>nordlig koordinat</TD><TD WIDTH=50%>711659.0 (SWEREF99 TM, EPSG:3006)</TD></TR></p></TABLE></TD><TD WIDTH=50%><P><U><B>Lagerföljd</B></U></P><TABLE style="font-family:'arial'; font-size:10pt; font-weight:400; font-style:normal;" WIDTH=100% BORDER=0 CELLPADDING=0 CELLSPACING=1><COL WIDTH=43*><COL WIDTH=43*><COL WIDTH=43*><COL WIDTH=43*><COL WIDTH=43*><COL WIDTH=43*><p style="font-family:'arial'; font-size:10pt; font-weight:400; font-style:normal;"><TR VALIGN=TOP><TD WIDTH=17%><P><u>nivå (mumy)</P></u></TD><TD WIDTH=27%><P><u>jordart, fullst beskrivn</P></u></TD><TD WIDTH=17%><P><u>huvudfraktion</P></u></TD><TD WIDTH=5%><P><u>vg</P></u></TD><TD WIDTH=9%><P><u>stänger?</P></u></TD><TD WIDTH=27%><P><u>kommentar</P></u></TD></TR><TR VALIGN=TOP><TD WIDTH=17%><P>0.0 - 1.0</P></TD><TD WIDTH=27%><P>sand</P></TD><TD WIDTH=17%><P>sand</P></TD><TD WIDTH=5%><P>3</P></TD><TD WIDTH=9%><P>j</P></TD><TD WIDTH=27%><P></P></TD></TR><TR VALIGN=TOP><TD WIDTH=17%><P>1.0 - 4.5</P></TD><TD WIDTH=27%><P>morän</P></TD><TD WIDTH=17%><P>morän</P></TD><TD WIDTH=5%><P>3</P></TD><TD WIDTH=9%><P>j</P></TD><TD WIDTH=27%><P></P></TD></TR></p></TABLE></TD></TR><TR VALIGN=TOP><TD WIDTH=50%><P><U><B>Kommentarer</B></U></P><p style="font-family:'arial'; font-size:10pt; font-weight:400; font-style:normal;"></p></TD><TD WIDTH=50%><P><U><B>Vattennivåer</B></U></P><p style="font-family:'arial'; font-size:10pt; font-weight:400; font-style:normal;">Antal nivåmätningar: 1<br>Högsta uppmätta nivå: 123.0 m ö h<br>Medianvärde för nivå: 123.0 m ö h<br>Lägsta uppmätta nivå: 123.0 m ö h<br></p></TD></TR></TABLE></TD></TR></TABLE><meta http-equiv="content-type" content="text/html; charset=utf-8" /><head><title>1, 2, 3 General report from Midvatten plugin for QGIS</title></head><html><TABLE WIDTH=100% BORDER=0 CELLPADDING=1 CELLSPACING=1><TR VALIGN=TOP><TD WIDTH=15%><h3 style="font-family:'arial';font-size:18pt; font-weight:600">2</h3><img src="midvatten/tools/../templates/for_general_report_sv.png" /><br><img src='midvatten/tools/../templates/midvatten_logga.png' /></TD><TD WIDTH=85%><TABLE WIDTH=100% BORDER=1 CELLPADDING=4 CELLSPACING=3><TR VALIGN=TOP><TD WIDTH=50%><P><U><B>Allmän information</B></U></P><TABLE style="font-family:'arial'; font-size:10pt; font-weight:400; font-style:normal;" WIDTH=100% BORDER=0 CELLPADDING=0 CELLSPACING=1><COL WIDTH=43*><COL WIDTH=43*><p style="font-family:'arial'; font-size:8pt; font-weight:400; font-style:normal;"><TR VALIGN=TOP><TD WIDTH=33%>markytans nivå, my (möh)</TD><TD WIDTH=50%>10.0</TD></TR><TR VALIGN=TOP><TD WIDTH=33%>östlig koordinat</TD><TD WIDTH=50%>6720727.0 (SWEREF99 TM, EPSG:3006)</TD></TR><TR VALIGN=TOP><TD WIDTH=33%>nordlig koordinat</TD><TD WIDTH=50%>16568.0 (SWEREF99 TM, EPSG:3006)</TD></TR></p></TABLE></TD><TD WIDTH=50%><P><U><B>Lagerföljd</B></U></P><TABLE style="font-family:'arial'; font-size:10pt; font-weight:400; font-style:normal;" WIDTH=100% BORDER=0 CELLPADDING=0 CELLSPACING=1><COL WIDTH=43*><COL WIDTH=43*><COL WIDTH=43*><COL WIDTH=43*><COL WIDTH=43*><COL WIDTH=43*><p style="font-family:'arial'; font-size:10pt; font-weight:400; font-style:normal;"></p></TABLE></TD></TR><TR VALIGN=TOP><TD WIDTH=50%><P><U><B>Kommentarer</B></U></P><p style="font-family:'arial'; font-size:10pt; font-weight:400; font-style:normal;"></p></TD><TD WIDTH=50%><P><U><B>Vattennivåer</B></U></P><p style="font-family:'arial'; font-size:10pt; font-weight:400; font-style:normal;"></p></TD></TR></TABLE></TD></TR></TABLE><meta http-equiv="content-type" content="text/html; charset=utf-8" /><head><title>1, 2, 3 General report from Midvatten plugin for QGIS</title></head><html><TABLE WIDTH=100% BORDER=0 CELLPADDING=1 CELLSPACING=1><TR VALIGN=TOP><TD WIDTH=15%><h3 style="font-family:'arial';font-size:18pt; font-weight:600">3</h3><img src="midvatten/tools/../templates/for_general_report_sv.png" /><br><img src='midvatten/tools/../templates/midvatten_logga.png' /></TD><TD WIDTH=85%><TABLE WIDTH=100% BORDER=1 CELLPADDING=4 CELLSPACING=3><TR VALIGN=TOP><TD WIDTH=50%><P><U><B>Allmän information</B></U></P><TABLE style="font-family:'arial'; font-size:10pt; font-weight:400; font-style:normal;" WIDTH=100% BORDER=0 CELLPADDING=0 CELLSPACING=1><COL WIDTH=43*><COL WIDTH=43*><p style="font-family:'arial'; font-size:8pt; font-weight:400; font-style:normal;"><TR VALIGN=TOP><TD WIDTH=33%>markytans nivå, my (möh)</TD><TD WIDTH=50%>20.0</TD></TR><TR VALIGN=TOP><TD WIDTH=33%>östlig koordinat</TD><TD WIDTH=50%>6720728.0 (SWEREF99 TM, EPSG:3006)</TD></TR><TR VALIGN=TOP><TD WIDTH=33%>nordlig koordinat</TD><TD WIDTH=50%>16569.0 (SWEREF99 TM, EPSG:3006)</TD></TR></p></TABLE></TD><TD WIDTH=50%><P><U><B>Lagerföljd</B></U></P><TABLE style="font-family:'arial'; font-size:10pt; font-weight:400; font-style:normal;" WIDTH=100% BORDER=0 CELLPADDING=0 CELLSPACING=1><COL WIDTH=43*><COL WIDTH=43*><COL WIDTH=43*><COL WIDTH=43*><COL WIDTH=43*><COL WIDTH=43*><p style="font-family:'arial'; font-size:10pt; font-weight:400; font-style:normal;"></p></TABLE></TD></TR><TR VALIGN=TOP><TD WIDTH=50%><P><U><B>Kommentarer</B></U></P><p style="font-family:'arial'; font-size:10pt; font-weight:400; font-style:normal;"></p></TD><TD WIDTH=50%><P><U><B>Vattennivåer</B></U></P><p style="font-family:'arial'; font-size:10pt; font-weight:400; font-style:normal;"></p></TD></TR></TABLE></TD></TR></TABLE>
</p></body></html>"""
        assert report == ref


@pytest.mark.postgis
class TestDrillreportPostgis(
    DrillreportMixin, utils_for_tests.MidvattenTestPostgisDbSv
):
    pass


@pytest.mark.spatialite
class TestDrillreportSpatialite(
    DrillreportMixin, utils_for_tests.MidvattenTestSpatialiteDbSv
):
    pass


class DrillreportEnglishMixin:
    """Same scenario as DrillreportMixin but with the English (non-Swedish)
    report path. Reference captured from the pre-dedup implementation; the
    sv/en quadrant builders must stay byte-identical through refactors."""

    @mock.patch(
        "midvatten.tools.drillreport.QCoreApplication.translate",
        side_effect=lambda context, text, *args: text,
    )
    @mock.patch("midvatten.tools.utils.midvatten_utils.is_locale_swedish")
    @mock.patch("midvatten.tools.drillreport.QDesktopServices.openUrl")
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    @mock.patch("midvatten.tools.utils.message_utils.pop_up_info", autospec=True)
    def test_drillreport_english(
        self,
        mock_skippopup,
        mock_messagebar,
        openurl,
        mock_swedish,
        mock_translate,
        tmp_path,
    ):
        """The translate patch returns source text so the reference does not
        depend on which translator the host machine happens to load."""
        mock_swedish.return_value = False
        db_utils.sql_alter_db(
            """INSERT INTO obs_points (obsid, h_gs, geometry) VALUES ('1', 5, ST_GeomFromText('POINT(633466 711659)', 3006))"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO w_levels (obsid, date_time, h_toc, level_masl) VALUES ('1', '2021-01-01 00:00', 20, 123)"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO stratigraphy (obsid, stratid, depthtop, depthbot, geology, geoshort, capacity, development) VALUES ('1', 1, 0, 1, 'sand', 'sand', '3', 'j')"""
        )

        dlg = Drillreport(self.iface, self.midvatten.ms)
        dlg._run_report(("1",), self.midvatten.ms.settingsdict)

        print(f"{mock_messagebar.mock_calls=}")
        with open(tmp_path / "drill_report.html") as f:
            report = "".join(f.readlines())
        report = _normalize_template_paths(report)
        ref = """<meta http-equiv="content-type" content="text/html; charset=utf-8" /><head><title>1 General report from Midvatten plugin for QGIS</title></head><html><TABLE WIDTH=100% BORDER=0 CELLPADDING=1 CELLSPACING=1><TR VALIGN=TOP><TD WIDTH=15%><h3 style="font-family:'arial';font-size:18pt; font-weight:600">1</h3><img src="midvatten/tools/../templates/for_general_report.png" /><br><img src='midvatten/tools/../templates/midvatten_logga.png' /></TD><TD WIDTH=85%><TABLE WIDTH=100% BORDER=1 CELLPADDING=4 CELLSPACING=3><TR VALIGN=TOP><TD WIDTH=50%><P><U><B>General information</B></U></P><TABLE style="font-family:'arial'; font-size:10pt; font-weight:400; font-style:normal;" WIDTH=100% BORDER=0 CELLPADDING=0 CELLSPACING=1><COL WIDTH=43*><COL WIDTH=43*><p style="font-family:'arial'; font-size:8pt; font-weight:400; font-style:normal;"><TR VALIGN=TOP><TD WIDTH=33%>ground surface level, gs (masl)</TD><TD WIDTH=50%>5.0</TD></TR><TR VALIGN=TOP><TD WIDTH=33%>eastern coordinate</TD><TD WIDTH=50%>633466.0 (SWEREF99 TM, EPSG:3006)</TD></TR><TR VALIGN=TOP><TD WIDTH=33%>northern coordinate</TD><TD WIDTH=50%>711659.0 (SWEREF99 TM, EPSG:3006)</TD></TR></p></TABLE></TD><TD WIDTH=50%><P><U><B>Stratigraphy</B></U></P><TABLE style="font-family:'arial'; font-size:10pt; font-weight:400; font-style:normal;" WIDTH=100% BORDER=0 CELLPADDING=0 CELLSPACING=1><COL WIDTH=43*><COL WIDTH=43*><COL WIDTH=43*><COL WIDTH=43*><COL WIDTH=43*><COL WIDTH=43*><p style="font-family:'arial'; font-size:10pt; font-weight:400; font-style:normal;"><TR VALIGN=TOP><TD WIDTH=15%><P><u>level (m b gs)</P></u></TD><TD WIDTH=27%><P><u>geology, full text</P></u></TD><TD WIDTH=17%><P><u>geology, short</P></u></TD><TD WIDTH=9%><P><u>capacity</P></u></TD><TD WIDTH=13%><P><u>development</P></u></TD><TD WIDTH=21%><P><u>comment</P></u></TD></TR><TR VALIGN=TOP><TD WIDTH=15%><P>0.0 - 1.0</P></TD><TD WIDTH=27%><P>sand</P></TD><TD WIDTH=17%><P>sand</P></TD><TD WIDTH=9%><P>3</P></TD><TD WIDTH=13%><P>j</P></TD><TD WIDTH=21%><P></P></TD></TR></p></TABLE></TD></TR><TR VALIGN=TOP><TD WIDTH=50%><P><U><B>Comments</B></U></P><p style="font-family:'arial'; font-size:10pt; font-weight:400; font-style:normal;"></p></TD><TD WIDTH=50%><P><U><B>Water levels</B></U></P><p style="font-family:'arial'; font-size:10pt; font-weight:400; font-style:normal;">Number of water level measurements: 1<br>Highest measured water level: 123.0 m above sea level<br>Median water level: 123.0 m above sea level<br>Lowest measured water level: 123.0 m above sea level<br></p></TD></TR></TABLE></TD></TR></TABLE>
</p></body></html>"""
        assert report == ref


@pytest.mark.spatialite
class TestDrillreportEnglishSpatialite(
    DrillreportEnglishMixin, utils_for_tests.MidvattenTestSpatialiteDbSv
):
    pass
