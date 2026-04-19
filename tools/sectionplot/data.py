#! /usr/bin/env python
"""
Standalone data-preparation functions for SectionPlot.

These functions contain no ``self`` references and no figure/widget access.
They take explicit arguments and return plain data structures, making them
independently testable.
"""

import traceback
from operator import itemgetter

import numpy as np
import pandas as pd
from psycopg2.sql import SQL, Identifier
from qgis.PyQt.QtCore import QCoreApplication

from midvatten.tools.utils import common_utils, db_utils
from midvatten.tools.utils.db_utils.dialect import ident
from midvatten.tools.utils.string_utils import returnunicode as ru


def prepare_obsid_positions(
    line_feature,
    selected_obspoints,
    line_layer=None,
    dbconnection=None,
    temptable_name: str = "temporary_section_line",
):
    """Calculate x-positions (distance along section) for each obsid.

    If *line_layer* is provided the distances come from a spatial query
    against the uploaded temporary line table.  Otherwise obs_points
    coordinates are used and observations are ordered east→west or
    north→south.

    Returns a dict ``{obsid: distance_along_section}``.
    """
    obsids_x_position = {}
    if line_layer is not None:
        if len(selected_obspoints):
            obsids_x_position = get_length_along(
                selected_obspoints,
                dbconnection=dbconnection,
                temptable_name=temptable_name,
            )
            common_utils.MessagebarAndLog.info(
                log_msg=QCoreApplication.translate(
                    "SectionPlot",
                    "Hidden features, obsids and length along section:\n%s\\%s",
                )
                % (
                    ";".join(obsids_x_position.keys()),
                    ";".join([str(x) for x in obsids_x_position.values()]),
                )
            )
    else:
        res = dbconnection.execute_and_fetchall(
            f"""SELECT obsid, east, north FROM obs_points WHERE obsid IN ({dbconnection.placeholders(len(selected_obspoints))})""",
            args=tuple(selected_obspoints),
        )
        xs = [float(row[1]) for row in res]
        ys = [float(row[2]) for row in res]
        if (max(xs) - min(xs)) > (max(ys) - min(ys)):
            # Order by x
            k = 1
        else:
            # Order by y
            k = 2
            pass
        obsids_x_position = {
            row[0]: idx * 10 for idx, row in enumerate(sorted(res, key=itemgetter(k)))
        }
    return obsids_x_position


def get_length_along(
    obsidtuple,
    dbconnection=None,
    temptable_name: str = "temporary_section_line",
):
    """Query the DB for the fractional distance of each obsid along the section line.

    Returns a dict ``{obsid: distance}``.
    """
    sql = """SELECT p.obsid, ST_Length((SELECT geometry FROM {temptable_name})) * {funcname}((SELECT geometry FROM {temptable_name}), p.geometry) AS absdist FROM obs_points AS p
              WHERE p.obsid in ({placeholders})
              ORDER BY absdist"""

    funcnames = ["ST_Line_Locate_Point", "ST_LineLocatePoint"]

    if dbconnection.is_postgresql():
        try:
            _funcname = dbconnection.execute_and_fetchall(
                """SELECT proname FROM pg_proc
                                                         WHERE lower(proname) LIKE '%line%locate%point%';"""
            )
        except Exception:
            common_utils.MessagebarAndLog.info(log_msg=traceback.format_exc())
        else:
            if _funcname:
                _funcname = _funcname[0][0]
                funcnames.append(_funcname)
    cur = dbconnection.cursor
    for nr, funcname in enumerate(funcnames):
        try:
            cur.execute(
                sql.format(
                    temptable_name=temptable_name,
                    funcname=funcname,
                    placeholders=dbconnection.placeholders(len(obsidtuple)),
                ),
                tuple(obsidtuple),
            )
        except Exception:
            common_utils.MessagebarAndLog.info(log_msg=traceback.format_exc())
        else:
            res = cur.fetchall()
            break
    else:
        # Run last sql again to get an error.
        res = dbconnection.execute_and_fetchall(
            sql.format(
                temptable_name=temptable_name,
                funcname=funcname,
                placeholders=dbconnection.placeholders(len(obsidtuple)),
            ),
            args=tuple(obsidtuple),
        )

    data = {ru(row[0]): row[1] for row in res}
    return data


def get_z_data(obsids_x_position: dict, dbconnection=None) -> dict:
    """Fetch ground-surface elevation and borehole length for each obsid.

    Returns a dict ``{obsid: {"z": float, "barheight": float, "bottom": float}}``.
    """
    z_data = {}
    for obs in obsids_x_position.keys():
        sql = f"SELECT h_toc, h_gs, length FROM obs_points WHERE obsid = {dbconnection.placeholder()}"
        recs = dbconnection.execute_and_fetchall(sql, (obs,))
        h_toc, h_gs, length = recs[0]
        if common_utils.isfloat(str(h_gs)) and h_gs > -999:
            z = h_gs
        elif common_utils.isfloat(str(h_toc)) and h_toc > -999:
            z = h_toc
            common_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "SectionPlot",
                    "Obsid %s: using h_gs '%s' failed, using '%s' instead.",
                )
                % (obs, str(h_gs), "h_toc")
            )
        else:
            z = 0
            common_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "SectionPlot",
                    "Obsid %s: using h_gs %s or h_toc %s failed, using 0 instead.",
                )
                % (obs, str(h_gs), str(h_toc))
            )

        if common_utils.isfloat(str(length)):
            barheight = length
        else:
            barheight = 0

        bottom = z - barheight

        z_data[obs] = {"z": z, "barheight": barheight, "bottom": bottom}

    return z_data


def get_plot_data_bars(
    obsids_x_position: dict,
    z_data: dict,
    typ_subtypes: dict,
    obsid_annotation: dict,
    dbconnection=None,
    strat_key: str = "geoshort",
) -> dict:
    """Fetch stratigraphy depth intervals and build bar-plot data.

    This is called when the class is instantiated, collecting data specific for
    the profile line layer and the obs_points.

    Also populates *obsid_annotation* with ``{obsid: (x, z)}`` entries for
    obsids not already annotated.

    Returns a dict ``{type_name: {"x": [...], "height": [...], "bottom": [...]}}``.
    """
    common_utils.start_waiting_cursor()
    bars = {}
    if not len(obsids_x_position):
        common_utils.stop_waiting_cursor()
        return bars

    for typ, _subtypes in typ_subtypes.items():
        subtypes = _subtypes
        for obs, x in obsids_x_position.items():
            if subtypes is None:
                condition = "NOT IN"
                subtypes = [st for k, v in typ_subtypes.items() for st in v if k != typ]
            else:
                condition = "IN"

            sql = """SELECT depthtop, depthbot
                     FROM stratigraphy WHERE obsid = {ph}
                     AND TRIM(LOWER({strat_key})) {condition} ({subtypes})
                     ORDER BY stratid"""
            if dbconnection.is_sqlite():
                _sql = sql.format(
                    ph=dbconnection.placeholder(),
                    strat_key=ident(strat_key),
                    condition=condition,
                    subtypes=dbconnection.placeholders(len(subtypes)),
                )
            else:
                _sql = SQL(sql).format(
                    ph=SQL(dbconnection.placeholder()),
                    strat_key=Identifier(strat_key),
                    condition=SQL(condition),
                    subtypes=SQL(dbconnection.placeholders(len(subtypes))),
                )
            params = tuple([obs] + list(subtypes))
            recs = dbconnection.execute_and_fetchall(_sql, args=params)
            if not recs:
                continue

            for row in recs:
                bars.setdefault(typ, {}).setdefault("x", []).append(x)
                bars.setdefault(typ, {}).setdefault("height", []).append(
                    float(row[1]) - float(row[0])
                )
                bars.setdefault(typ, {}).setdefault("bottom", []).append(
                    z_data[obs]["z"] - float(row[1])
                )

            if obs not in obsid_annotation:
                obsid_annotation[obs] = (x, z_data[obs]["z"])
    common_utils.stop_waiting_cursor()
    return bars


def get_screen_plot_data(
    obsids_x_position: dict,
    z_data: dict,
    dbconnection=None,
) -> dict:
    """Fetch screen intervals grouped by screenshort for plotting.

    Returns a dict ``{screenshort: {"x": [...], "height": [...], "bottom": [...]}}``
    matching the shape produced by ``get_plot_data_bars()``.  Returns an empty
    dict if the ``screen`` table doesn't exist (older DBs) or no rows match.
    """
    if not db_utils.verify_table_exists("screen", dbconnection=dbconnection):
        return {}

    bars: dict = {}
    if not obsids_x_position:
        return bars

    ph = dbconnection.placeholder()
    sql = f"SELECT depthtop, depthbot, screenshort FROM screen WHERE obsid = {ph} ORDER BY screenid"

    for obs, x in obsids_x_position.items():
        if obs not in z_data:
            continue
        recs = dbconnection.execute_and_fetchall(sql, args=(obs,))
        if not recs:
            continue
        z = z_data[obs]["z"]
        for row in recs:
            depthtop, depthbot, screenshort = row[0], row[1], row[2]
            if depthtop is None or depthbot is None:
                continue
            key = str(screenshort).lower() if screenshort is not None else "default"
            height = float(depthbot) - float(depthtop)
            bottom = z - float(depthbot)
            bars.setdefault(key, {}).setdefault("x", []).append(x)
            bars.setdefault(key, {}).setdefault("height", []).append(height)
            bars.setdefault(key, {}).setdefault("bottom", []).append(bottom)

    return bars


def get_plot_data_layer_texts(
    obsids_x_position: dict,
    z_data: dict,
    hydro_colors: dict,
    dbconnection=None,
) -> dict:
    """Fetch stratigraphy text labels for each bar segment.

    Returns a dict ``{column_name: {(x, z): text}}``.
    """
    bar_texts = {}
    common_utils.start_waiting_cursor()

    for obs, x in obsids_x_position.items():
        sql = f"""SELECT depthtop, depthbot, geology, geoshort, capacity, development,
                comment
                FROM stratigraphy WHERE obsid = {dbconnection.placeholder()}
                ORDER BY stratid"""
        recs = dbconnection.execute_and_fetchall(sql, args=(obs,))
        if not recs:
            continue

        for row in recs:
            height = float(row[1]) - float(row[0])
            bottom = z_data[obs]["z"] - float(row[1])
            z = bottom + (height / 2)
            bar_texts.setdefault("geology", {})[(x, z)] = row[2]
            bar_texts.setdefault("geoshort", {})[(x, z)] = row[3]
            capacity = row[4]
            bar_texts.setdefault("capacity", {})[(x, z)] = capacity
            bar_texts.setdefault("development", {})[(x, z)] = row[5]
            bar_texts.setdefault("comment", {})[(x, z)] = row[6]

            if capacity:
                bar_texts.setdefault("hydroexplanation", {})[(x, z)] = hydro_colors.get(
                    capacity, [" "]
                )[0]

    # Remove bad texts.
    bar_texts = {
        k: {
            xz: t
            for xz, t in v.items()
            if all([t is not None, str(t).strip(), str(t).lower().strip() != "null"])
        }
        for k, v in bar_texts.items()
    }

    common_utils.stop_waiting_cursor()
    return bar_texts


def get_drillstops(
    obsids_x_position: dict,
    z_data: dict,
    settingsdict: dict = None,
    dbconnection=None,
) -> list:
    """Return a list of ``(x, bottom)`` tuples for boreholes that hit bedrock.

    An empty string *secplotdrillstop* in *settingsdict* means no filter is
    applied and the result is an empty list.
    """
    obs_p_w_drill_stops = []
    if settingsdict["secplotdrillstop"] != "":
        sql = f"""SELECT obsid FROM obs_points WHERE lower(drillstop) LIKE {dbconnection.placeholder()}"""
        res = dbconnection.execute_and_fetchall(
            sql, (ru(settingsdict["secplotdrillstop"]),)
        )
        if res:
            obs_p_w_drill_stops = [row[0] for row in res]

    drillstops = [
        (float(obsids_x_position[obs]), z_data[obs]["bottom"])
        for obs, x in obsids_x_position.items()
        if obs in obs_p_w_drill_stops
    ]
    return drillstops


SEISMIC_Y1_COLUMN = "bedrock"
SEISMIC_Y2_COLUMN = "ground"
SEISMIC_Y3_COLUMN = "gw_table"


def get_plot_data_seismic(line_layer, line_feature, dbconnection=None):
    """Load seismic data for an obs_lines layer feature.

    Returns a numpy recarray with columns ``obsline_x``, ``obsline_y1``,
    ``obsline_y2``, ``obsline_y3``, or ``None`` if the layer is not
    ``obs_lines``.
    """
    my_format = [
        ("obsline_x", float),
        ("obsline_y1", float),
        ("obsline_y2", float),
        ("obsline_y3", float),
    ]
    x = "length"
    y1_column = SEISMIC_Y1_COLUMN
    y2_column = SEISMIC_Y2_COLUMN
    y3_column = SEISMIC_Y3_COLUMN
    table = "seismic_data"
    if line_layer and line_layer.name() == "obs_lines":
        sql = (
            r"""select %s as x, %s as y1, %s as y2, %s as y3 from %s where obsid=%s"""  # noqa: UP031
            % (
                x,
                y1_column,
                y2_column,
                y3_column,
                table,
                dbconnection.placeholder(),
            )
        )
        recs = dbconnection.execute_and_fetchall(
            sql, args=(line_feature.attribute("obsid"),)
        )
        table = np.array(recs, dtype=my_format)
        obs_lines_plot_data = table.view(np.recarray)
        return obs_lines_plot_data


def get_water_levels_from_df(
    df,
    idx: int,
    obsids_x_position: dict,
    obsid_annotation: dict,
    settingsdict: dict = None,
) -> tuple:
    """Extract water-level values for the given DataFrame row index.

    Returns ``(x_wl, wl, new_annotations)`` where *x_wl* and *wl* are
    parallel lists of x-positions and water-level values, and
    *new_annotations* is a ``{obsid: (x, val)}`` dict of annotation entries
    for obsids not yet annotated (to be merged into the caller's
    ``obsid_annotation`` dict).
    """
    wl = []
    x_wl = []
    new_annotations: dict = {}
    for obs, x in obsids_x_position.items():
        try:
            val = df.iloc[[idx]][obs]
        except KeyError:
            continue
        except TypeError:
            try:
                _obs = obs.encode("utf8").decode("utf8")
            except Exception:
                common_utils.MessagebarAndLog.info(
                    log_msg=QCoreApplication.translate(
                        "SectionPlot", "Encoding string failed for %s"
                    )
                    % ru(obs)
                )
                continue
            else:
                try:
                    val = df.iloc[[idx]][_obs]
                except KeyError:
                    continue

        wl.append(val)
        x_wl.append(x)
        if obs not in obsid_annotation or not any(
            [
                settingsdict["stratigraphyplotted"],
                settingsdict["secplothydrologyplotted"],
            ]
        ):
            new_annotations[obs] = (x, val)
    return x_wl, wl, new_annotations


def get_length_map(length_series: pd.Series):
    """
    Fix to add two empty columns (TEM measurement column) if the length along section
    diff of two locations are greater than 1,5 times the column width.
    """

    df = length_series.sort_values().to_frame()
    df["diff"] = df["length"].diff()
    min_column_width = df["diff"].dropna().min()
    new_idx_map = {}
    new_idx = 0
    allowed_interpolation_diff_factor = 1.5
    for idx, (length, diff) in enumerate(df.itertuples(index=False)):
        if not pd.isna(diff):
            if diff > (min_column_width * allowed_interpolation_diff_factor):
                # Fix that adds two columns, but no mapping for the real column.
                new_idx += 2
                new_idx_map[idx] = new_idx
                new_idx += 1
                continue

        new_idx_map[idx] = new_idx
        new_idx += 1
    return new_idx_map, min_column_width


def fill_empty_columns(new_idx_map, min_column_width, X, Y):  # noqa: N803
    """
    Fills the two new empty columns with the values of the previous non-empty
    column and the next non-empty column. Uses the same layer config
    as the two surrounding columns.
    """
    prev_idx = 0
    for current_idx in sorted(new_idx_map.values()):
        if current_idx > prev_idx + 1:
            X[:, prev_idx + 1] = X[:, prev_idx] + min_column_width
            X[:, current_idx - 1] = X[:, current_idx] - min_column_width
            Y[:, prev_idx + 1] = Y[:, prev_idx]
            Y[:, current_idx - 1] = Y[:, current_idx]
        prev_idx = current_idx


def slider_val_to_idx(val: float) -> int:
    return int(round(val, 0))
