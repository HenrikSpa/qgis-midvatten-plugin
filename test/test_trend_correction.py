import datetime

import numpy as np
import pandas as pd
import pytest


def test_drag_end_up():
    """Drag end endpoint up by 10; start stays fixed (pivot).

    Correction should be 0 at start, +10 at end, linear in between.
    """
    from midvatten.tools.trend_math import apply_trend_correction

    index = pd.to_datetime(["2017-02-01", "2017-02-05", "2017-02-10"]).to_pydatetime()
    buf = pd.DataFrame({"level_masl": [100.0, 150.0, 200.0]}, index=index)

    original_start_y = 100.0
    original_end_y = 200.0
    new_start_y = 100.0  # pivot — unchanged
    new_end_y = 210.0  # dragged up by 10

    apply_trend_correction(
        buf, original_start_y, original_end_y, new_start_y, new_end_y
    )

    # Feb-05 is 4/9 of the span (Feb-01 → Feb-10 = 9 days), so correction = +10 * 4/9
    expected = [100.0, 150.0 + 10.0 * 4 / 9, 210.0]
    np.testing.assert_allclose(buf["level_masl"].values, expected, atol=1e-10)


def test_drag_start_down():
    """Drag start endpoint down by 6; end stays fixed (pivot).

    Correction should be -6 at start, 0 at end, linear in between.
    """
    from midvatten.tools.trend_math import apply_trend_correction

    index = pd.to_datetime(["2017-02-01", "2017-02-05", "2017-02-10"]).to_pydatetime()
    buf = pd.DataFrame({"level_masl": [100.0, 150.0, 200.0]}, index=index)

    apply_trend_correction(buf, 100.0, 200.0, 94.0, 200.0)

    # f values: 0/9=0.0, 4/9≈0.4444, 9/9=1.0
    # corrections: -6*(1-0)+0*0=-6, -6*(1-4/9)+0=-10/3, -6*0+0*1=0
    expected = [94.0, 150.0 - 6.0 * 5 / 9, 200.0]
    np.testing.assert_allclose(buf["level_masl"].values, expected, atol=1e-10)


def test_drag_both_endpoints():
    """Both endpoints moved — start up by 2, end down by 3."""
    from midvatten.tools.trend_math import apply_trend_correction

    index = pd.to_datetime(["2017-02-01", "2017-02-10"]).to_pydatetime()
    buf = pd.DataFrame({"level_masl": [100.0, 200.0]}, index=index)

    apply_trend_correction(buf, 100.0, 200.0, 102.0, 197.0)

    expected = [102.0, 197.0]  # +2 at start, -3 at end
    np.testing.assert_allclose(buf["level_masl"].values, expected, atol=1e-10)


def test_null_level_masl_skipped():
    """Rows with NaN level_masl should not be modified."""
    from midvatten.tools.trend_math import apply_trend_correction

    index = pd.to_datetime(["2017-02-01", "2017-02-05", "2017-02-10"]).to_pydatetime()
    buf = pd.DataFrame({"level_masl": [100.0, np.nan, 200.0]}, index=index)

    apply_trend_correction(buf, 100.0, 200.0, 100.0, 210.0)

    assert buf["level_masl"].values[0] == pytest.approx(100.0)
    assert pd.isna(buf["level_masl"].values[1])
    assert buf["level_masl"].values[2] == pytest.approx(210.0)


def test_zero_time_span_no_change():
    """If start and end have the same timestamp, correction is skipped (no division by zero)."""
    from midvatten.tools.trend_math import apply_trend_correction

    index = pd.to_datetime(["2017-02-01", "2017-02-01"]).to_pydatetime()
    buf = pd.DataFrame({"level_masl": [100.0, 200.0]}, index=index)

    apply_trend_correction(buf, 100.0, 200.0, 110.0, 210.0)

    np.testing.assert_allclose(buf["level_masl"].values, [100.0, 200.0], atol=1e-10)


def test_single_point_no_crash():
    """Single-point selection: no crash, no change (start==end timestamp)."""
    from midvatten.tools.trend_math import apply_trend_correction

    index = pd.to_datetime(["2017-02-01"]).to_pydatetime()
    buf = pd.DataFrame({"level_masl": [100.0]}, index=index)

    apply_trend_correction(buf, 100.0, 100.0, 110.0, 110.0)

    np.testing.assert_allclose(buf["level_masl"].values, [100.0], atol=1e-10)
