"""
/***************************************************************************
 Cross-backend acceptance test: date_time duplicate-rule parity.

 Verifies that importing a file produces the SAME row state on SpatiaLite
 and PostGIS under the unified duplicate rule:

 - A same-instant pair ('hh:mm' vs 'hh:mm:ss') collapses to ONE row; the
   stored date_time is the RAW survivor (first seen), NOT padded.
 - A row at a distinct second is kept as a separate row.
 - A date-only value is stored VERBATIM (not padded to 'hh:mm:ss').
 - Malformed / unparseable values are stored verbatim and NOT deduped
   against each other (each escapes normalized uniqueness).
 - Re-importing the same parseable file is idempotent (row count unchanged).

 SpatiaLite tests run locally; PostGIS tests are collected but need CI.
                             -------------------
        begin                : 2026-05-29
        copyright            : (C) 2026 by HenrikSpa
        email                : groundwatergis [at] gmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

from unittest import mock

import pytest

from midvatten.test import utils_for_tests
from midvatten.tools.utils import db_utils


class DatetimeParityMixin:
    """Cross-backend acceptance tests for the unified date_time duplicate rule.

    Each concrete subclass mixes in a backend-specific test base.
    Run SpatiaLite locally; PostGIS runs in CI (requires a live server).
    """

    # ------------------------------------------------------------------
    # Test 1: same-instant pair collapses; distinct second is kept
    # ------------------------------------------------------------------

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    @mock.patch(
        "midvatten.tools.import_data_to_db.common_utils.Askuser", mock.MagicMock()
    )
    def test_same_instant_collapses_distinct_second_kept(self, mock_messagebar):
        """Same-instant pair ('hh:mm' and 'hh:mm:ss') collapses to ONE row.

        - The surviving row's date_time is the FIRST row seen in file order.
          In-file dedup uses pandas drop_duplicates(keep="first") over the
          ordered file_data list, so '2015-01-01 00:00' (row 1) is kept and
          '2015-01-01 00:00:00' (row 2) is dropped. The raw string is never
          rewritten to a padded canonical form.
        - '2015-01-01 00:00:01' is a distinct second and must be kept separately.
        """
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")

        file_data = [
            ("obsid", "date_time", "head_cm"),
            ("rb1", "2015-01-01 00:00", "1"),  # first of same-instant pair — kept
            ("rb1", "2015-01-01 00:00:00", "2"),  # same instant -> dropped in-file
            (
                "rb1",
                "2015-01-01 00:00:01",
                "3",
            ),  # distinct second -> kept (numeric string)
        ]

        self.importinstance.general_import(
            dest_table="w_levels_logger", file_data=file_data
        )

        rows = db_utils.sql_load_fr_db(
            "SELECT date_time FROM w_levels_logger WHERE obsid='rb1' ORDER BY date_time"
        )[1]
        print(f"{mock_messagebar.mock_calls=}")
        vals = [r[0] for r in rows]

        # Exactly two rows: the same-instant survivor + the distinct second
        assert len(vals) == 2, f"Expected 2 rows, got {len(vals)}: {vals}"

        # Distinct second must be present
        assert "2015-01-01 00:00:01" in vals, f"'00:00:01' row missing from {vals}"

        # First-seen row is deterministically kept (drop_duplicates keep="first")
        assert "2015-01-01 00:00" in vals, (
            f"Expected first-seen survivor '2015-01-01 00:00' in {vals}"
        )

    # ------------------------------------------------------------------
    # Test 2: date-only value is stored verbatim (not padded)
    # ------------------------------------------------------------------

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    @mock.patch(
        "midvatten.tools.import_data_to_db.common_utils.Askuser", mock.MagicMock()
    )
    def test_date_only_stored_verbatim(self, mock_messagebar):
        """A date-only value ('yyyy-mm-dd') must be stored exactly as given.

        The unique index evaluates datetime('2015-02-02') = '2015-02-02 00:00:00'
        internally for dedup purposes, but the TEXT column must hold the raw
        value — it must NOT be padded to '2015-02-02 00:00:00'.
        """
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb2')")

        file_data = [
            ("obsid", "date_time", "head_cm"),
            ("rb2", "2015-02-02", "5"),
        ]

        self.importinstance.general_import(
            dest_table="w_levels_logger", file_data=file_data
        )

        test_string = utils_for_tests.create_test_string(
            db_utils.sql_load_fr_db(
                "SELECT obsid, date_time FROM w_levels_logger WHERE obsid='rb2'"
            )
        )
        print(f"{mock_messagebar.mock_calls=}")
        # The raw '2015-02-02' must survive, NOT '2015-02-02 00:00:00'
        reference_string = "(True, [(rb2, 2015-02-02)])"
        assert test_string == reference_string

    # ------------------------------------------------------------------
    # Test 3: malformed date values are stored verbatim; not merged
    # ------------------------------------------------------------------

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    @mock.patch(
        "midvatten.tools.import_data_to_db.common_utils.Askuser", mock.MagicMock()
    )
    def test_distinct_malformed_dates_both_stored(self, mock_messagebar):
        """Malformed / unparseable date_time strings are stored verbatim.

        Observed behavior (verified via code inspection and this test):
        - The in-file dedup falls back to the raw string when instant_key()
          returns None (i.e. when the value is unparseable). Two different
          malformed strings therefore have different raw keys and are NOT merged.
        - On insert, SQLite's datetime('not a date') → NULL; the UNIQUE INDEX
          on (obsid, datetime(date_time)) allows multiple NULLs (SQL standard),
          so both rows are inserted successfully.
        - On PostGIS, midv_to_instant('not a date') → NULL (EXCEPTION handler),
          giving the same semantics: multiple NULL index values are allowed,
          so both rows survive.
        - Reimporting malformed rows is NOT idempotent: delete_existing matches
          on the normalized key (datetime(date_time) / midv_to_instant(date_time)),
          which is NULL for malformed values, and NULL = NULL is never true in SQL.
          Each reimport therefore inserts an additional copy — this is the intended
          behavior for unparseable values, but it is not idempotent.
        - Net: two distinct malformed date strings produce two distinct rows.
        """
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb3')")

        file_data = [
            ("obsid", "date_time", "head_cm"),
            ("rb3", "not a date", "10"),
            ("rb3", "also not a date", "20"),
        ]

        self.importinstance.general_import(
            dest_table="w_levels_logger", file_data=file_data
        )

        rows = db_utils.sql_load_fr_db(
            "SELECT date_time FROM w_levels_logger WHERE obsid='rb3' ORDER BY date_time"
        )[1]
        print(f"{mock_messagebar.mock_calls=}")
        vals = [r[0] for r in rows]

        # Both distinct malformed strings must be stored (not merged)
        assert len(vals) == 2, f"Expected 2 malformed rows, got {len(vals)}: {vals}"
        assert "not a date" in vals, f"'not a date' missing from {vals}"
        assert "also not a date" in vals, f"'also not a date' missing from {vals}"

    # ------------------------------------------------------------------
    # Test 4: re-importing a parseable file is idempotent
    # ------------------------------------------------------------------

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    @mock.patch(
        "midvatten.tools.import_data_to_db.common_utils.Askuser", mock.MagicMock()
    )
    def test_reimport_is_idempotent(self, mock_messagebar):
        """Importing the same parseable file twice leaves row count unchanged.

        Only well-formed dates are used here. Malformed dates are intentionally
        excluded: their delete_existing match fails (NULL=NULL is never true),
        so each reimport of a malformed row inserts an additional copy — that
        is the documented, intended behavior, but it is NOT idempotent.
        """
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb4')")

        file_data = [
            ("obsid", "date_time", "head_cm"),
            ("rb4", "2015-03-01 00:00", "1"),  # same-instant pair -> one row
            ("rb4", "2015-03-01 00:00:00", "2"),
            ("rb4", "2015-03-01 00:00:01", "3"),  # distinct second -> separate row
            ("rb4", "2015-03-02", "4"),  # date-only -> verbatim
        ]

        # First import
        self.importinstance.general_import(
            dest_table="w_levels_logger", file_data=file_data
        )

        count_after_first = db_utils.sql_load_fr_db(
            "SELECT count(*) FROM w_levels_logger WHERE obsid='rb4'"
        )[1][0][0]

        # Second import of the same file — must be a no-op
        self.importinstance.general_import(
            dest_table="w_levels_logger", file_data=file_data
        )

        count_after_second = db_utils.sql_load_fr_db(
            "SELECT count(*) FROM w_levels_logger WHERE obsid='rb4'"
        )[1][0][0]

        print(f"{mock_messagebar.mock_calls=}")
        assert count_after_first == 3, (
            f"First import should produce 3 rows (same-instant collapses), got {count_after_first}"
        )
        assert count_after_second == count_after_first, (
            f"Reimport changed row count: {count_after_first} -> {count_after_second}"
        )


# ------------------------------------------------------------------
# Concrete test classes
# ------------------------------------------------------------------


@pytest.mark.postgis
class TestDatetimeParityPostgis(
    DatetimeParityMixin,
    utils_for_tests.MidvattenTestPostgisDbSvImportInstance,
):
    pass


@pytest.mark.spatialite
class TestDatetimeParitySpatialite(
    DatetimeParityMixin,
    utils_for_tests.MidvattenTestSpatialiteDbSvImportInstance,
):
    pass
