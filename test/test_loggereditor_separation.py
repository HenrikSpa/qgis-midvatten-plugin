import pytest
import pandas as pd
import numpy as np

pytest.importorskip("qgis.PyQt")

from midvatten.tools.loggereditor import LoggerEditor


class TestLineKeyComputation:
    def test_source_only(self):
        buf = pd.DataFrame(
            {
                "head_cm_m": [1.0, 2.0, 3.0],
                "level_masl": [10.0, 20.0, 30.0],
                "source": ["A", "B", "A"],
            },
            index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
        )
        result = LoggerEditor._compute_line_keys(
            buf,
            separate_source=True,
            separate_created_at=False,
            separate_dt_precision=False,
            created_at_grouping=None,
        )
        assert list(result) == [("A",), ("B",), ("A",)]

    def test_source_and_created_at(self):
        buf = pd.DataFrame(
            {
                "head_cm_m": [1.0, 2.0],
                "level_masl": [10.0, 20.0],
                "source": ["A", "A"],
                "created_at": ["2024-01-01 10:00:00", "2024-01-02 14:00:00"],
            },
            index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
        )
        result = LoggerEditor._compute_line_keys(
            buf,
            separate_source=True,
            separate_created_at=True,
            separate_dt_precision=False,
            created_at_grouping=None,
        )
        assert list(result) == [
            ("A", "2024-01-01 10:00:00"),
            ("A", "2024-01-02 14:00:00"),
        ]

    def test_series_id_column_does_not_split_or_shift_keys(self):
        """A series_id column must NOT add a grouping dimension: rows that share
        source (incl. empty/null) group together regardless of series_id, and
        the created_at dimension stays correctly positioned in the key."""
        buf = pd.DataFrame(
            {
                "head_cm_m": [1.0, 2.0, 3.0],
                "level_masl": [10.0, 20.0, 30.0],
                "source": ["A", "", ""],
                "series_id": pd.array([1, 2, 3], dtype="Int64"),
                "created_at": [
                    "2024-01-01 10:00:00",
                    "2024-01-02 14:00:00",
                    "2024-01-02 14:00:00",
                ],
            },
            index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
        )
        result = LoggerEditor._compute_line_keys(
            buf,
            separate_source=True,
            separate_created_at=True,
            separate_dt_precision=False,
            created_at_grouping=None,
        )
        # series_id 2 and 3 share source "" and created_at -> same key (no split);
        # the second key element is created_at, not series_id.
        assert list(result) == [
            ("A", "2024-01-01 10:00:00"),
            ("", "2024-01-02 14:00:00"),
            ("", "2024-01-02 14:00:00"),
        ]

    def test_created_at_grouped_by_day(self):
        buf = pd.DataFrame(
            {
                "head_cm_m": [1.0, 2.0],
                "level_masl": [10.0, 20.0],
                "source": ["A", "A"],
                "created_at": ["2024-01-01 10:00:00", "2024-01-01 14:00:00"],
            },
            index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
        )
        result = LoggerEditor._compute_line_keys(
            buf,
            separate_source=True,
            separate_created_at=True,
            separate_dt_precision=False,
            created_at_grouping="day",
        )
        assert result[0] == result[1]

    def test_dt_precision_separation(self):
        buf = pd.DataFrame(
            {
                "head_cm_m": [1.0, 2.0],
                "level_masl": [10.0, 20.0],
                "source": ["A", "A"],
                "dt_length": [16, 19],
            },
            index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
        )
        result = LoggerEditor._compute_line_keys(
            buf,
            separate_source=True,
            separate_created_at=False,
            separate_dt_precision=True,
            created_at_grouping=None,
        )
        assert result[0] != result[1]

    def test_no_separation_single_key(self):
        buf = pd.DataFrame(
            {
                "head_cm_m": [1.0, 2.0],
                "level_masl": [10.0, 20.0],
                "source": ["A", "B"],
            },
            index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
        )
        result = LoggerEditor._compute_line_keys(
            buf,
            separate_source=False,
            separate_created_at=False,
            separate_dt_precision=False,
            created_at_grouping=None,
        )
        assert result[0] == result[1]


class TestCreatedAtGrouping:
    def test_group_by_hour_truncates(self):
        buf = pd.DataFrame(
            {
                "head_cm_m": [1.0, 2.0],
                "level_masl": [10.0, 20.0],
                "source": ["A", "A"],
                "created_at": ["2024-01-01 10:05:00", "2024-01-01 10:22:00"],
            },
            index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
        )
        result = LoggerEditor._compute_line_keys(
            buf,
            separate_source=False,
            separate_created_at=True,
            separate_dt_precision=False,
            created_at_grouping="hour",
        )
        assert result[0] == result[1]

    def test_group_by_hour_different_hours(self):
        buf = pd.DataFrame(
            {
                "head_cm_m": [1.0, 2.0],
                "level_masl": [10.0, 20.0],
                "source": ["A", "A"],
                "created_at": ["2024-01-01 10:05:00", "2024-01-01 14:22:00"],
            },
            index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
        )
        result = LoggerEditor._compute_line_keys(
            buf,
            separate_source=False,
            separate_created_at=True,
            separate_dt_precision=False,
            created_at_grouping="hour",
        )
        assert result[0] != result[1]
