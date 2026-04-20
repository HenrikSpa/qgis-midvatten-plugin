"""Pinned-behavior tests for cast_date_time_as_epoch.

These lock down today's UTC interpretation of the naive date string
`2024-06-15 12:00:00`. Both backends interpret it as UTC, so the epoch
value is 1718452800.

Written before the F1 refactor (see docs/superpowers/specs/
2026-04-19-stabilisation-followups.md). The tests must keep passing
after the refactor — that's the whole point.
"""

from unittest import mock

import pytest

from midvatten.test import utils_for_tests
from midvatten.tools.utils import db_utils

# 2024-06-15 12:00:00 UTC
EXPECTED_EPOCH = 1718452800
FIXED_INPUT = "2024-06-15 12:00:00"


class CastDateTimeAsEpochMixin:
    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_literal_path_utc_interpretation(self, mock_messagebar):
        """Calling cast_date_time_as_epoch with a fixed datetime literal
        must produce 1718452800 (UTC interpretation)."""
        conn = db_utils.DbConnectionManager(self._class_db_settings)
        conn.connect2db()
        try:
            fragment = conn.cast_date_time_as_epoch(date_time=FIXED_INPUT)
            sql, args = _split(fragment)
            rows = conn.execute_and_fetchall(f"SELECT {sql}", args)
            print(f"{mock_messagebar.mock_calls=}")
            assert int(rows[0][0]) == EXPECTED_EPOCH
        finally:
            conn.closedb()

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_column_path_utc_interpretation(self, mock_messagebar):
        """Calling cast_date_time_as_epoch() with no arg (column mode) on
        a row where date_time='2024-06-15 12:00:00' must produce
        1718452800."""
        conn = db_utils.DbConnectionManager(self._class_db_settings)
        conn.connect2db()
        try:
            # Seed one obs_points row (FK) and one w_levels_logger row.
            ph = conn.placeholder()
            db_utils.sql_alter_db(
                f"INSERT INTO obs_points (obsid) VALUES ({ph})",
                dbconnection=conn,
                all_args=[("P_epoch",)],
            )
            db_utils.sql_alter_db(
                f"INSERT INTO w_levels_logger (obsid, date_time) VALUES ({ph}, {ph})",
                dbconnection=conn,
                all_args=[("P_epoch", FIXED_INPUT)],
            )

            fragment = conn.cast_date_time_as_epoch()
            sql, args = _split(fragment)
            rows = conn.execute_and_fetchall(
                f"SELECT {sql} FROM w_levels_logger WHERE obsid = {ph}",
                (*args, "P_epoch"),
            )
            print(f"{mock_messagebar.mock_calls=}")
            assert int(rows[0][0]) == EXPECTED_EPOCH
        finally:
            conn.closedb()


def _split(fragment):
    """Accept either `str` (pre-refactor) or `(sql, args)` (post-refactor).

    The pinned behavior test must pass under both shapes so the single
    refactor commit that changes the signature is easy to verify.
    """
    if isinstance(fragment, tuple):
        sql, args = fragment
        return sql, tuple(args)
    return fragment, ()


@pytest.mark.spatialite
class TestCastDateTimeAsEpochSpatialite(
    CastDateTimeAsEpochMixin, utils_for_tests.MidvattenTestSpatialiteDbSv
):
    pass


@pytest.mark.postgis
class TestCastDateTimeAsEpochPostgis(
    CastDateTimeAsEpochMixin, utils_for_tests.MidvattenTestPostgisDbSv
):
    pass
