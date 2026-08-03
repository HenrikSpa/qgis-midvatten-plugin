import os

from midvatten.tools import wqualreport_core
from midvatten.tools.utils import file_utils


def test_report_folder_is_private_and_unique():
    a = wqualreport_core.report_folder()
    b = wqualreport_core.report_folder()
    # Each call yields a fresh private dir, not a shared fixed one:
    assert a != b
    assert os.path.isdir(a)
    # Not group/other writable:
    mode = os.stat(a).st_mode
    assert not (mode & 0o022)


def test_session_tempdir_cleanup_removes_report_dir():
    """report_folder() dirs (created via the shared session_tempdir helper)
    must not accumulate unbounded across a session: the atexit-registered
    sweep must actually remove a tracked dir when invoked."""
    d = wqualreport_core.report_folder()
    assert os.path.isdir(d)

    file_utils._cleanup_session_tempdirs()

    assert not os.path.isdir(d)


def test_session_tempdir_cleanup_removes_csv_dir():
    """The CSV-dump temp dirs (Backend.dump_table_2_csv) go through the same
    session_tempdir helper, so the one shared sweep removes them too."""
    d = file_utils.session_tempdir(prefix="midvatten_csv_")
    assert os.path.isdir(d)

    file_utils._cleanup_session_tempdirs()

    assert not os.path.isdir(d)
