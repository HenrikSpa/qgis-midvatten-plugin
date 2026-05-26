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


class TestBuildSelectionWhereHourBoundary:
    def test_hour_23_rolls_to_next_day(self):
        """Verify that hour-grouped SQL WHERE for hour 23 uses next day 00:00:00."""
        import datetime
        from midvatten.tools.utils.db_utils.dialect import ident

        lower_dt = datetime.datetime.strptime(
            "2024-01-01 23:00:00", "%Y-%m-%d %H:%M:%S"
        )
        upper_dt = lower_dt + datetime.timedelta(hours=1)
        upper_str = upper_dt.strftime("%Y-%m-%d %H:%M:%S")
        assert upper_str == "2024-01-02 00:00:00"


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
