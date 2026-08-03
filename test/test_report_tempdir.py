import os

from midvatten.tools import wqualreport_core


def test_report_folder_is_private_and_unique():
    a = wqualreport_core.report_folder()
    b = wqualreport_core.report_folder()
    # Each call yields a fresh private dir, not a shared fixed one:
    assert a != b
    assert os.path.isdir(a)
    # Not group/other writable:
    mode = os.stat(a).st_mode
    assert not (mode & 0o022)
