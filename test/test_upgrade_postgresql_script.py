"""
/***************************************************************************
 The PostgreSQL upgrade script must not delete data. When same-instant
 duplicates exist it stops before changing anything, reports every group
 in the psql output and in a per-table view the admin can query, and
 leaves the decision to the admin. A separate opt-in script performs the
 old keep-earliest deletion for admins who have reviewed the report.
                             -------------------
        begin                : 2026-09-07
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

import os
import shutil
import subprocess

import pytest

from midvatten.test import utils_for_tests
from midvatten.tools.utils import db_utils

DEFINITIONS = os.path.join(os.path.dirname(__file__), "..", "definitions")
UPGRADE_SCRIPT = os.path.join(DEFINITIONS, "upgrade_postgresql_to_2_0_0.sql")
DEDUP_SCRIPT = os.path.join(
    DEFINITIONS, "upgrade_postgresql_to_2_0_0_dedup_keep_earliest.sql"
)
DUPLICATES_VIEW = "midv_upgrade_duplicates_w_levels"


def _run_psql(script: str) -> subprocess.CompletedProcess:
    settings = utils_for_tests.MidvattenTestPostgisNotCreated.ALL_POSTGIS_SETTINGS[
        "nosetests"
    ]
    return subprocess.run(
        [
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-h",
            settings["host"],
            "-p",
            settings["port"],
            "-d",
            settings["database"],
            "-f",
            script,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def _w_levels_rows() -> list:
    return db_utils.sql_load_fr_db(
        "SELECT obsid, date_time FROM w_levels ORDER BY obsid, date_time"
    )[1]


@pytest.mark.postgis
@pytest.mark.skipif(shutil.which("psql") is None, reason="psql not installed")
class TestUpgradeScriptDuplicateGate(utils_for_tests.MidvattenTestPostgisDbSv):
    def setup_method(self):
        super().setup_method()
        db_utils.sql_alter_db("DROP INDEX IF EXISTS uq_w_levels_obsid_dt")
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('o1'), ('o2')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels (obsid, date_time, meas, level_masl) VALUES "
            # identical data, only the date_time spelling differs
            "('o1', '2020-01-01 12:00', 1.0, 5.0), "
            "('o1', '2020-01-01 12:00:00', 1.0, 5.0), "
            # conflicting data at the same instant
            "('o2', '2020-02-01 08:00', 1.5, NULL), "
            "('o2', '2020-02-01 08:00:00', 2.5, NULL)"
        )

    def test_upgrade_stops_and_reports_before_changing_anything(self):
        result = _run_psql(UPGRADE_SCRIPT)
        print(result.stdout)
        print(result.stderr)

        assert result.returncode != 0
        assert "w_levels" in result.stderr
        assert DUPLICATES_VIEW in result.stderr
        assert len(_w_levels_rows()) == 4
        # Section 12 (drop old indexes) must not have run.
        assert db_utils.sql_load_fr_db(
            "SELECT 1 FROM pg_indexes WHERE indexname = 'uq_comments_obsid_dt'"
        )[1]

        groups = db_utils.sql_load_fr_db(
            "SELECT obsid, row_count, data_identical, date_time, meas, level_masl "
            f"FROM {DUPLICATES_VIEW} ORDER BY obsid"
        )[1]
        assert groups == [
            ("o1", 2, True, "2020-01-01 12:00, 2020-01-01 12:00:00", "1, 1", "5, 5"),
            (
                "o2",
                2,
                False,
                "2020-02-01 08:00, 2020-02-01 08:00:00",
                "1.5, 2.5",
                "NULL, NULL",
            ),
        ]

    def test_dedup_script_then_upgrade_succeeds(self):
        result = _run_psql(DEDUP_SCRIPT)
        print(result.stdout)
        print(result.stderr)
        assert result.returncode == 0
        assert _w_levels_rows() == [
            ("o1", "2020-01-01 12:00"),
            ("o2", "2020-02-01 08:00"),
        ]

        result = _run_psql(UPGRADE_SCRIPT)
        print(result.stdout)
        print(result.stderr)
        assert result.returncode == 0
        assert not db_utils.verify_table_exists(DUPLICATES_VIEW)
        assert db_utils.sql_load_fr_db(
            "SELECT 1 FROM pg_indexes WHERE indexname = 'uq_w_levels_obsid_dt'"
        )[1]
