import datetime

import pandas as pd


_UTC_EPOCH = datetime.datetime(1970, 1, 1)


def apply_trend_correction(
    buf: pd.DataFrame,
    original_start_y: float,
    original_end_y: float,
    new_start_y: float,
    new_end_y: float,
) -> bool:
    """Apply a linearly interpolated trend correction to buf["level_masl"] in-place.

    Returns True if a correction was applied, False if skipped (zero time span).
    """
    mask = buf["level_masl"].notna()
    if mask.sum() < 2:
        return False

    start_dt = buf.index[0]
    end_dt = buf.index[-1]
    start_epoch = (start_dt - _UTC_EPOCH).total_seconds()
    end_epoch = (end_dt - _UTC_EPOCH).total_seconds()
    span = end_epoch - start_epoch

    if span == 0:
        return False

    delta_start = new_start_y - original_start_y
    delta_end = new_end_y - original_end_y

    row_epochs = buf.index.map(lambda dt: (dt - _UTC_EPOCH).total_seconds())
    f = (row_epochs - start_epoch) / span
    correction = delta_start * (1 - f) + delta_end * f
    buf.loc[mask, "level_masl"] += correction[mask]
    return True
