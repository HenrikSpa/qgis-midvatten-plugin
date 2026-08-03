import os
import subprocess
import sys
import textwrap

import pytest

import midvatten.tools.utils.db_utils.connection as conn
from midvatten.tools.utils.exceptions import UsageError


def test_core_modules_import_without_psycopg2():
    """The plugin must load SpatiaLite-only when psycopg2 is unavailable."""
    code = textwrap.dedent(
        """
        import sys
        # Make any import of psycopg2 raise ImportError (this is a fresh
        # subprocess, so psycopg2 was never imported yet; this just blocks it):
        sys.modules["psycopg2"] = None
        import importlib
        importlib.import_module("midvatten.tools.utils.db_utils.connection")
        importlib.import_module("midvatten.tools.import_data_to_db")
        importlib.import_module("midvatten.tools.prepareforqgis2threejs")
        importlib.import_module("midvatten.tools.strat_symbology")
        importlib.import_module("midvatten.tools.sectionplot")
        print("OK")
        """
    )
    # Prepend this worktree's _pkgroot (relative symlink midvatten -> "..") to
    # PYTHONPATH so the subprocess resolves "midvatten" to *this* worktree's
    # code, not the shared QGIS plugins symlink (which points at a different
    # checkout entirely — see conftest.py for why _pkgroot exists).
    pkgroot = os.path.abspath(
        os.path.join(os.path.dirname(__file__), os.pardir, "_pkgroot")
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [pkgroot, env.get("PYTHONPATH")]))
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert "OK" in result.stdout, result.stderr


def test_create_backend_postgis_without_psycopg2_raises_usage_error(monkeypatch):
    """Attempting a PostGIS connection without psycopg2 must raise a
    translated, actionable UsageError - not an ImportError/traceback."""
    monkeypatch.setattr(conn, "PostgreSQLBackend", None)
    with pytest.raises(UsageError, match="psycopg2"):
        conn.create_backend({"postgis": {}})


def test_duplicate_table_errors_constant_present_with_psycopg2():
    """When psycopg2 IS importable (the normal test environment here),
    _DUPLICATE_TABLE_ERRORS must still be the real 1-tuple so that
    DuplicateTable is caught on PostgreSQL exactly as before."""
    import psycopg2.errors

    from midvatten.tools import prepareforqgis2threejs as q3js

    assert q3js._DUPLICATE_TABLE_ERRORS == (psycopg2.errors.DuplicateTable,)

    caught = False
    try:
        raise psycopg2.errors.DuplicateTable("boom")
    except q3js._DUPLICATE_TABLE_ERRORS:
        caught = True
    assert caught


def test_duplicate_table_errors_empty_without_psycopg2():
    """When psycopg2 is unavailable, _DUPLICATE_TABLE_ERRORS must be an empty
    tuple (so `except _DUPLICATE_TABLE_ERRORS:` never matches - it neither
    swallows an unrelated error nor raises AttributeError while evaluating
    `None.errors.DuplicateTable`), and an unrelated error raised inside the
    guarded try block must propagate untouched."""
    code = textwrap.dedent(
        """
        import sys
        sys.modules["psycopg2"] = None
        import importlib
        q3js = importlib.import_module("midvatten.tools.prepareforqgis2threejs")

        assert q3js._DUPLICATE_TABLE_ERRORS == (), q3js._DUPLICATE_TABLE_ERRORS

        try:
            try:
                raise RuntimeError("some other db error")
            except q3js._DUPLICATE_TABLE_ERRORS:
                raise AssertionError("empty tuple must never match")
        except RuntimeError:
            pass  # expected: the real error propagates instead of being masked

        print("OK")
        """
    )
    pkgroot = os.path.abspath(
        os.path.join(os.path.dirname(__file__), os.pardir, "_pkgroot")
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [pkgroot, env.get("PYTHONPATH")]))
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert "OK" in result.stdout, result.stderr
