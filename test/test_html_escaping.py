from unittest import mock

import pytest

from midvatten.test import utils_for_tests
from midvatten.tools import wqualreport_core
from midvatten.tools.custom_drillreport import Drillreport as CustomDrillreport
from midvatten.tools.drillreport import Drillreport
from midvatten.tools.utils import db_utils
from midvatten.tools.utils.html_utils import esc


def test_esc_neutralizes_script():
    assert esc("<script>alert(1)</script>") == ("&lt;script&gt;alert(1)&lt;/script&gt;")


def test_esc_escapes_quotes_and_amp():
    assert esc('a & "b" <c>') == "a &amp; &quot;b&quot; &lt;c&gt;"


def test_esc_handles_none():
    assert esc(None) == ""


# ---------------------------------------------------------------------------
# End-to-end regression: a <script> payload stored in free-text DB columns
# must never reach the written report HTML unescaped. Reference-data tests
# can't catch this class of regression because their fixtures contain no
# special characters, so this guard fails loudly (raw <script> found in the
# file) if an esc() call is ever removed from either report builder.
# ---------------------------------------------------------------------------

_SCRIPT_PAYLOAD = "<script>alert(1)</script>"
_ESCAPED_PAYLOAD = "&lt;script&gt;alert(1)&lt;/script&gt;"


@pytest.mark.spatialite
class TestReportsNeutralizeScriptPayload(utils_for_tests.MidvattenTestSpatialiteDbSv):
    @mock.patch("midvatten.tools.drillreport.QDesktopServices.openUrl")
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    @mock.patch("midvatten.tools.utils.message_utils.pop_up_info", autospec=True)
    def test_drillreport_escapes_script_payload(
        self, mock_skippopup, mock_messagebar, mock_openurl, tmp_path, monkeypatch
    ):
        # report_folder() now returns a fresh mkdtemp() dir per call (Task 8
        # hardening); pin it to a known pytest tmp_path so the test can find
        # the written report.
        monkeypatch.setattr(wqualreport_core, "report_folder", lambda: str(tmp_path))

        db_utils.sql_alter_db(
            f"""INSERT INTO obs_points (obsid, material, geometry) VALUES
            ('{_SCRIPT_PAYLOAD}', '{_SCRIPT_PAYLOAD}',
             ST_GeomFromText('POINT(0 0)', 3006))"""
        )
        db_utils.sql_alter_db(
            f"""INSERT INTO stratigraphy
                    (obsid, stratid, depthtop, depthbot, geology)
                VALUES ('{_SCRIPT_PAYLOAD}', 1, 0, 1, '{_SCRIPT_PAYLOAD}')"""
        )

        dlg = Drillreport(self.iface, self.midvatten.ms)
        dlg._run_report((_SCRIPT_PAYLOAD,), self.midvatten.ms.settingsdict)

        with open(tmp_path / "drill_report.html") as f:
            report = f.read()

        print(f"{mock_messagebar.mock_calls=}")
        assert _SCRIPT_PAYLOAD not in report
        assert _ESCAPED_PAYLOAD in report

    @mock.patch("midvatten.tools.custom_drillreport.QDesktopServices.openUrl")
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    @mock.patch("midvatten.tools.utils.message_utils.pop_up_info", autospec=True)
    def test_custom_drillreport_escapes_script_payload(
        self, mock_skippopup, mock_messagebar, mock_openurl, tmp_path, monkeypatch
    ):
        # report_folder() now returns a fresh mkdtemp() dir per call (Task 8
        # hardening); pin it to a known pytest tmp_path so the test can find
        # the written report.
        monkeypatch.setattr(wqualreport_core, "report_folder", lambda: str(tmp_path))

        db_utils.sql_alter_db(
            f"""INSERT INTO obs_points (obsid, material, com_onerow, geometry) VALUES
            ('{_SCRIPT_PAYLOAD}', '{_SCRIPT_PAYLOAD}', '{_SCRIPT_PAYLOAD}',
             ST_GeomFromText('POINT(0 0)', 3006))"""
        )
        db_utils.sql_alter_db(
            f"""INSERT INTO stratigraphy
                    (obsid, stratid, depthtop, depthbot, geology)
                VALUES ('{_SCRIPT_PAYLOAD}', 1, 0, 1, '{_SCRIPT_PAYLOAD}')"""
        )

        CustomDrillreport(
            [_SCRIPT_PAYLOAD],
            self.midvatten.ms,
            ["material"],
            [],
            ["geology"],
            True,
            False,
            True,
            "General",
            "Geo",
            "Stratigraphy",
            "Comment",
            False,
            [],
            ["2*", "3*"],
            [],
            ".",
        )

        with open(tmp_path / "drill_report.html") as f:
            report = f.read()

        print(f"{mock_messagebar.mock_calls=}")
        assert _SCRIPT_PAYLOAD not in report
        assert _ESCAPED_PAYLOAD in report
