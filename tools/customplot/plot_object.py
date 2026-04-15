"""
Pure data-transformation helpers for CustomPlot.createsingleplotobject().

These functions take numpy arrays / DataFrames and return transformed arrays.
They have no knowledge of the Qt UI or the CustomPlot instance.
"""

import datetime
import logging

import matplotlib as mpl
import numpy as np
import pandas as pd
from matplotlib.dates import datestr2num
from qgis.PyQt.QtCore import QCoreApplication

from midvatten.tools.utils import common_utils
from midvatten.tools.utils.string_utils import returnunicode as ru

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Step 1 – parse raw DB records into a recarray + detect axis type
# ---------------------------------------------------------------------------


def parse_recs_to_recarray(
    recs: list,
    my_format: list,
) -> tuple:
    """Convert raw DB records into a numpy recarray and detect axis type.

    Returns
    -------
    table : np.ndarray
    table2 : np.recarray
    flag_time_xy : str  – "time" or "XY"
    numtime : array-like of floats
    my_format : list   – updated format (XY fallback changes field names)
    """
    try:
        table = np.array(recs, dtype=my_format)  # NDARRAY
        table2 = table.view(
            np.recarray
        )  # RECARRAY transform the 2 cols into callable objects
        flag_time_xy = "time"
        my_timestring = list(table2.date_time)
        numtime = datestr2num(
            my_timestring
        )  # conv list of strings to numpy.ndarray of floats
    except Exception as e:
        common_utils.MessagebarAndLog.warning(
            log_msg=QCoreApplication.translate(
                "plotsqlitewindow", "Plotting date_time failed, msg: %s"
            )
            % str(e)
        )
        common_utils.MessagebarAndLog.info(
            log_msg=QCoreApplication.translate(
                "plotsqlitewindow",
                "Customplot, transforming to recarray with date_time as x-axis failed, msg: %s",
            )
            % str(e)
        )
        my_format = [("numx", float), ("values", float)]
        table = np.array(
            recs, dtype=my_format
        )  # NDARRAY #define a format for xy-plot (to use if not datetime on x-axis)

        table2 = table.view(
            np.recarray
        )  # RECARRAY transform the 2 cols into callable objects

        flag_time_xy = "XY"
        numtime = list(table2.numx)

    return table, table2, flag_time_xy, numtime, my_format


# ---------------------------------------------------------------------------
# Step 2 – insert NaN gaps for discontinuous time steps
# ---------------------------------------------------------------------------


def apply_max_timestep_gaps(
    table: np.ndarray,
    table2: np.recarray,
    numtime,
    max_tstep: float,
    my_format: list,
) -> tuple:
    """Insert NaN sentinels between points whose time gap exceeds *max_tstep*.

    Parameters
    ----------
    max_tstep : float
        Maximum allowed timestep (in matplotlib date units, i.e. days).
        If <= 0 the function is a no-op.

    Returns
    -------
    table, table2, numtime  (possibly extended with NaN rows/values)
    """
    if max_tstep <= 0:
        return table, table2, numtime

    # from version 0.2 there is a possibility to make discontinuous plot if timestep bigger than maxtstep
    pos = np.where(np.abs(np.diff(numtime)) >= max_tstep)[0] + 1
    pos = pos.tolist()
    if pos:
        numtime = np.insert(numtime, pos, np.nan)
        try:
            table2 = np.insert(table2, pos, np.nan)
        except (ValueError, TypeError):
            for_concat = []
            nan = np.array([(np.nan, np.nan)], dtype=my_format)
            for idx, p in enumerate(pos):
                if idx == 0:
                    for_concat.append(table[0:p])
                    for_concat.append(nan.copy())
                    continue
                for_concat.append(table[pos[idx - 1] : p])
                for_concat.append(nan.copy())
            else:
                for_concat.append(table[pos[-1] :])
            table = np.concatenate(for_concat)
            table = table.astype(my_format)
            table2 = table.view(np.recarray)

    return table, table2, numtime


# ---------------------------------------------------------------------------
# Step 3 – value transformations (frequency, remove_mean, scale)
# ---------------------------------------------------------------------------


def transform_values(
    table2: np.recarray,
    flag_time_xy: str,
    plottype: str,
    label: str,
    calc_frequency_fn,
    remove_mean: bool,
    factor: float,
    offset: float,
) -> np.recarray:
    """Apply in-place value transformations: frequency, mean removal, scaling.

    Parameters
    ----------
    calc_frequency_fn : callable
        Bound method ``self.calc_frequency`` – passed in to keep this function
        free of Qt/self dependencies.
    label : str
        Human-readable series label used in the warning message for short
        frequency series.

    Returns
    -------
    table2 : np.recarray  (same object, values mutated in-place)
    """
    if flag_time_xy == "time" and plottype == "frequency":
        if len(table2) < 2:
            common_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "plotsqlitewindow",
                    "Frequency plot failed for %s. The timeseries must be longer than 1 value!",
                )
                % ru(label),
                duration=30,
            )
            table2.values[:] = [None] * len(table2)
        else:
            table2.values[:] = calc_frequency_fn(table2)[:]

    if remove_mean:
        table2.values[:] = common_utils.remove_mean_from_nparray(table2.values)[:]

    if any(
        [
            factor != 1 and factor,
            offset,
        ]
    ):
        table2.values[:] = common_utils.scale_nparray(table2.values, factor, offset)[:]

    return table2


# ---------------------------------------------------------------------------
# Step 4 – pandas resampling / rolling
# ---------------------------------------------------------------------------


def apply_pandas_calculations(
    table2: np.recarray,
    numtime,
    flag_time_xy: str,
    pandas_calc,
    my_format: list,
) -> tuple:
    """Apply optional pandas resample / rolling-mean calculations.

    If *pandas_calc* is None or ``use_pandas()`` returns False, the inputs are
    returned unchanged.

    Returns
    -------
    table2 : np.recarray
    numtime : array-like of floats
    """
    if pandas_calc and flag_time_xy == "time":
        if pandas_calc.use_pandas():
            df = pd.DataFrame.from_records(
                table2, columns=["values"], exclude=["date_time"]
            )
            df.set_index(
                pd.DatetimeIndex(table2.date_time, name="date_time"), inplace=True
            )
            df.columns = ["values"]

            df = pandas_calc.calculate(df)
            if df is not None:
                try:
                    table = np.array(list(zip(df.index, df["values"])), dtype=my_format)
                except TypeError:
                    common_utils.MessagebarAndLog.info(log_msg=str(df))
                    raise
                table2 = table.view(
                    np.recarray
                )  # RECARRAY transform the 2 cols into callable objects
                numtime = table2.date_time
            else:
                common_utils.MessagebarAndLog.info(
                    bar_msg=QCoreApplication.translate(
                        "plotsqlitewindow", "Pandas calculate failed."
                    )
                )

    return table2, numtime


# ---------------------------------------------------------------------------
# Step 5 – render one series onto the axes
# ---------------------------------------------------------------------------


def render_series(
    p_list: list,
    i: int,
    plabels: list,
    axes,
    flag_time_xy: str,
    numtime,
    table2: np.recarray,
    plottype: str,
    line_cycler,
    marker_cycler,
    line_and_marker_cycler,
) -> None:
    """Call ``axes.plot()`` with the appropriate style for *plottype*.

    Mutates *p_list[i]* and *plabels[i]* in-place (the frequency branch
    prepends "frequency " to the label).

    Parameters
    ----------
    p_list, plabels : lists managed by CustomPlot
    axes : matplotlib Axes object
    flag_time_xy : "time" or "XY"
    """
    if flag_time_xy == "time":
        plotfunc = axes.plot
    elif flag_time_xy == "XY":
        plotfunc = axes.plot
    else:
        raise Exception("Programming error. Must be time or XY!")

    # Matplotlib rcParams often uses lines.markeredgewidth: 0.0 which makes the marker invisible.
    markeredgewidth = (
        1.0
        if not mpl.rcParams["lines.markeredgewidth"]
        else mpl.rcParams["lines.markeredgewidth"]
    )

    if plottype == "step-pre":
        (p_list[i],) = plotfunc(
            numtime,
            table2.values,
            picker=2,
            drawstyle="steps-pre",
            marker="None",
            label=plabels[i],
            **next(line_cycler),
        )  # 'steps-pre' best for precipitation and flowmeters, optional types are 'steps', 'steps-mid', 'steps-post'
    elif plottype == "step-post":
        (p_list[i],) = plotfunc(
            numtime,
            table2.values,
            picker=2,
            drawstyle="steps-post",
            marker="None",
            label=plabels[i],
            **next(line_cycler),
        )
    elif plottype == "line and cross":
        (p_list[i],) = plotfunc(
            numtime,
            table2.values,
            picker=2,
            marker="x",
            label=plabels[i],
            markeredgewidth=markeredgewidth,
            **next(line_cycler),
        )
    elif plottype == "marker":
        (p_list[i],) = plotfunc(
            numtime,
            table2.values,
            picker=2,
            linestyle="None",
            label=plabels[i],
            markeredgewidth=markeredgewidth,
            **next(marker_cycler),
        )
    elif plottype == "line":
        (p_list[i],) = plotfunc(
            numtime,
            table2.values,
            picker=2,
            marker="None",
            label=plabels[i],
            **next(line_cycler),
        )
    elif plottype == "frequency" and flag_time_xy == "time":
        try:
            (p_list[i],) = plotfunc(
                numtime,
                table2.values,
                picker=2,
                marker="None",
                label="frequency " + str(plabels[i]),
                **next(line_cycler),
            )
            plabels[i] = "frequency " + str(plabels[i])
        except Exception:
            (p_list[i],) = plotfunc(
                np.array([]),
                np.array([]),
                picker=2,
                marker="None",
                label="frequency " + str(plabels[i]),
                **next(line_cycler),
            )
            plabels[i] = "frequency " + str(plabels[i])
    else:
        # line and marker
        (p_list[i],) = plotfunc(
            numtime,
            table2.values,
            picker=2,
            label=plabels[i],
            markeredgewidth=markeredgewidth,
            **next(line_and_marker_cycler),
        )
