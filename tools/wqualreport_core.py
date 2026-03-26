"""
Shared logic for water quality reports (wqualreport.py and wqualreport_compact.py).
"""

import os
from typing import Optional, TextIO

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtCore import QDir
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices

from midvatten.tools.utils.common_utils import returnunicode as ru


REPORT_FILENAME = "w_qual_report.html"


def report_folder() -> str:
    """Ensure midvatten_reports folder exists in temp and return its path."""
    reportfolder = os.path.join(QDir.tempPath(), "midvatten_reports")
    if not os.path.exists(reportfolder):
        os.makedirs(reportfolder)
    return reportfolder


def report_path() -> str:
    """Return the path to the default water quality report HTML file."""
    return os.path.join(report_folder(), REPORT_FILENAME)


def default_report_title() -> str:
    """Return the default title for the water quality report."""
    return QCoreApplication.translate(
        "Wqualreport",
        "water quality report from Midvatten plugin for QGIS",
    )


def write_html_preamble(
    f: TextIO,
    title: Optional[str] = None,
) -> None:
    """Write HTML head, meta and open body tag to the report file."""
    if title is None:
        title = default_report_title()
    rpt = f"<head><title>{ru(title)}</title></head>"
    rpt += r""" <meta http-equiv="content-type" content="text/html; charset=utf-8" />"""
    rpt += "<html><body>"
    f.write(rpt)


def write_html_close(f: TextIO) -> None:
    """Write closing body and html tags."""
    f.write("\n</body></html>")


def open_report_in_browser(path: str) -> None:
    """Open the report file in the default browser."""
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))
