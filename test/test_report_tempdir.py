import os
import tempfile

from midvatten.tools import wqualreport_core
from midvatten.tools.utils.db_utils.backends import base


def test_report_folder_is_private_and_unique():
    a = wqualreport_core.report_folder()
    b = wqualreport_core.report_folder()
    # Each call yields a fresh private dir, not a shared fixed one:
    assert a != b
    assert os.path.isdir(a)
    # Not group/other writable:
    mode = os.stat(a).st_mode
    assert not (mode & 0o022)


def test_cleanup_report_dirs_removes_tracked_dir():
    """report_folder() dirs must not accumulate unbounded across a session:
    the atexit-registered sweep must actually remove a tracked dir when
    invoked."""
    d = wqualreport_core.report_folder()
    assert os.path.isdir(d)

    wqualreport_core._cleanup_report_dirs()

    assert not os.path.isdir(d)


def test_cleanup_csv_dirs_removes_tracked_dir():
    """Same accumulation guard for the CSV-dump temp dirs created by
    Backend.dump_table_2_csv() (base.py): the atexit-registered sweep must
    remove a tracked dir when invoked."""
    d = tempfile.mkdtemp(prefix="midvatten_csv_")
    base._created_tmp_dirs.append(d)
    assert os.path.isdir(d)

    base._cleanup_csv_dirs()

    assert not os.path.isdir(d)
