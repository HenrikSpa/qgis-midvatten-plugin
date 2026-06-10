"""Tests for validate_resample_how — the allowlist for the pandas resample
"how" widget input used by sectionplot and customplot.

The raw widget text must never be passed to getattr() on a pandas object:
only known aggregation method names are allowed through.
"""

import pandas as pd
import pytest

from midvatten.definitions import midvatten_defs as defs
from midvatten.tools.utils.exceptions import UsageError


class TestValidateResampleHow:
    def test_known_method_is_returned(self):
        assert defs.validate_resample_how("mean") == "mean"
        assert defs.validate_resample_how("sum") == "sum"
        assert defs.validate_resample_how("median") == "median"
        assert defs.validate_resample_how("first") == "first"
        assert defs.validate_resample_how("last") == "last"

    def test_whitespace_and_case_are_normalized(self):
        assert defs.validate_resample_how(" Mean ") == "mean"
        assert defs.validate_resample_how("SUM") == "sum"

    def test_empty_input_defaults_to_mean(self):
        assert defs.validate_resample_how("") == "mean"
        assert defs.validate_resample_how("   ") == "mean"
        assert defs.validate_resample_how(None) == "mean"

    def test_dunder_attribute_is_rejected(self):
        with pytest.raises(UsageError):
            defs.validate_resample_how("__class__")

    def test_non_aggregation_pandas_method_is_rejected(self):
        with pytest.raises(UsageError):
            defs.validate_resample_how("to_csv")

    def test_typo_is_rejected_with_allowed_methods_in_message(self):
        with pytest.raises(UsageError, match="mean"):
            defs.validate_resample_how("maen")


class TestSectionplotResampleHelper:
    """The shared resample() helper must reject unvalidated 'how' values
    itself, not rely on every caller validating first."""

    @staticmethod
    def _df():
        idx = pd.to_datetime(["2026-01-01 00:00", "2026-01-01 12:00"])
        return pd.DataFrame({"level_masl": [1.0, 3.0]}, index=idx)

    def test_valid_how_aggregates(self):
        from midvatten.tools.sectionplot._sectionplot import resample

        df = resample(self._df(), "level_masl", "1d", {"how": "mean"})
        assert float(df.iloc[0]) == 2.0

    def test_invalid_how_raises_usage_error(self):
        from midvatten.tools.sectionplot._sectionplot import resample

        with pytest.raises(UsageError):
            resample(self._df(), "level_masl", "1d", {"how": "to_csv"})
