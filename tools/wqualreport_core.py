"""
Shared logic for water quality reports (wqualreport.py and wqualreport_compact.py).
"""

import atexit
import os
import shutil
import tempfile
from typing import Optional, TextIO

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices

from midvatten.tools.utils.html_utils import esc


REPORT_FILENAME = "w_qual_report.html"

# Every report_folder() call creates a brand-new mkdtemp() dir (kept alive
# for the session so the report stays viewable in the browser). Track them
# here and sweep on process exit so a long QGIS session doesn't accumulate
# one orphaned dir per report view.
_created_tmp_dirs: list[str] = []


def _cleanup_report_dirs() -> None:
    """Remove every report temp dir created this session. Registered with
    atexit; also callable directly (e.g. from tests)."""
    for d in _created_tmp_dirs:
        shutil.rmtree(d, ignore_errors=True)


atexit.register(_cleanup_report_dirs)


def report_folder() -> str:
    """Create and return a fresh, private temp directory for a report.

    Each call returns a brand-new directory (tempfile.mkdtemp, mode 0700),
    rather than a shared fixed path, to avoid symlink/pre-creation attacks
    on multi-user hosts (bandit B108). The directory is swept at process
    exit via `_cleanup_report_dirs` so these don't accumulate unbounded.
    """
    reportfolder = tempfile.mkdtemp(prefix="midvatten_report_")
    _created_tmp_dirs.append(reportfolder)
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
    rpt = f"<head><title>{esc(title)}</title></head>"
    rpt += r""" <meta http-equiv="content-type" content="text/html; charset=utf-8" />"""
    rpt += "<html><body>"
    f.write(rpt)


def write_html_close(f: TextIO) -> None:
    """Write closing body and html tags."""
    f.write("\n</body></html>")


def open_report_in_browser(path: str) -> None:
    """Open the report file in the default browser."""
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))
