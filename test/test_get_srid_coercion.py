"""Boundary-coercion tests for Backend.get_srid().

Both SQLite and PostgreSQL backends must coerce the raw schema value to
``int`` before returning it. This is a belt-and-braces defence against
SQL injection via the ``ST_Transform(geom, <srid>)`` pattern in
``tools/export_engine.py`` — the SRID is interpolated into SQL, so we
insist on a proven-numeric value leaving ``get_srid``.
"""

from __future__ import annotations

from unittest import mock

import pytest

from midvatten.tools.utils.db_utils.backends.sqlite import SQLiteBackend
from midvatten.tools.utils.db_utils.backends.postgresql import PostgreSQLBackend


class _FakeCursor:
    """Minimal cursor stub for PostgreSQLBackend.get_srid."""

    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql, params=None):  # noqa: D401 — test stub
        return None

    def fetchall(self):
        return self._rows


# --------------------------------------------------------------------------- #
# SQLiteBackend                                                               #
# --------------------------------------------------------------------------- #


def test_sqlite_get_srid_coerces_string_to_int():
    """A compromised schema returning '3006' must still yield int 3006."""
    backend = SQLiteBackend.__new__(SQLiteBackend)
    with mock.patch.object(backend, "execute_and_fetchall", return_value=[("3006",)]):
        result = backend.get_srid("obs_points")
    assert result == 3006
    assert isinstance(result, int)
    assert not isinstance(result, str)


def test_sqlite_get_srid_preserves_none_for_nonspatial_table():
    """Empty result (non-spatial table) must keep returning None."""
    backend = SQLiteBackend.__new__(SQLiteBackend)
    with mock.patch.object(backend, "execute_and_fetchall", return_value=[]):
        assert backend.get_srid("some_table") is None


def test_sqlite_get_srid_preserves_none_when_cell_is_null():
    """NULL srid cell must propagate as None, not crash."""
    backend = SQLiteBackend.__new__(SQLiteBackend)
    with mock.patch.object(backend, "execute_and_fetchall", return_value=[(None,)]):
        assert backend.get_srid("some_table") is None


def test_sqlite_get_srid_rejects_injection_attempt():
    """A non-numeric string must raise before reaching any SQL."""
    backend = SQLiteBackend.__new__(SQLiteBackend)
    malicious = "3006); DROP TABLE obs_points; --"
    with mock.patch.object(
        backend, "execute_and_fetchall", return_value=[(malicious,)]
    ):
        with pytest.raises(ValueError):
            backend.get_srid("obs_points")


# --------------------------------------------------------------------------- #
# PostgreSQLBackend                                                           #
# --------------------------------------------------------------------------- #


def test_postgres_get_srid_coerces_string_to_int():
    """A compromised schema returning '3006' must still yield int 3006."""
    backend = PostgreSQLBackend.__new__(PostgreSQLBackend)
    backend._cursor = _FakeCursor([("3006",)])
    backend._schema = "midv"
    result = backend.get_srid("obs_points")
    assert result == 3006
    assert isinstance(result, int)
    assert not isinstance(result, str)


def test_postgres_get_srid_preserves_none_for_nonspatial_table():
    """Empty result must keep returning None."""
    backend = PostgreSQLBackend.__new__(PostgreSQLBackend)
    backend._cursor = _FakeCursor([])
    backend._schema = "midv"
    assert backend.get_srid("some_table") is None


def test_postgres_get_srid_preserves_none_when_cell_is_null():
    backend = PostgreSQLBackend.__new__(PostgreSQLBackend)
    backend._cursor = _FakeCursor([(None,)])
    backend._schema = "midv"
    assert backend.get_srid("some_table") is None


def test_postgres_get_srid_rejects_injection_attempt():
    """A non-numeric string must raise before reaching any SQL."""
    backend = PostgreSQLBackend.__new__(PostgreSQLBackend)
    backend._cursor = _FakeCursor([("3006); DROP TABLE obs_points; --",)])
    backend._schema = "midv"
    with pytest.raises(ValueError):
        backend.get_srid("obs_points")
