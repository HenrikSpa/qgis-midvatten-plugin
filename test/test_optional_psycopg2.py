import os
import subprocess
import sys
import textwrap


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
    pkgroot = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, "_pkgroot"))
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
