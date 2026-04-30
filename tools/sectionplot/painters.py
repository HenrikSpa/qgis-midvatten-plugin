#! /usr/bin/env python
"""
painters.py — pure-matplotlib rendering helpers for SectionPlot.

Each function here takes a SectionPlotFigure (and the data/settings it needs)
and draws directly onto ``figure.ax_main``, appending plot handles to
``figure.plot_handles``.  None of the functions here touch ``self`` of the
SectionPlot QDockWidget.
"""

import ast
import copy
import json
import logging
import os
import traceback

import matplotlib.pyplot as plt
import matplotlib.ticker as tick
import numpy as np
import pandas as pd
from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsFeatureRequest,
    QgsGeometry,
    QgsMapLayer,
    QgsProject,
    QgsRuleBasedRenderer,
    QgsRenderContext,
    QgsVectorLayer,
)

import midvatten.definitions.midvatten_defs as defs
from midvatten.tools.utils import common_utils, db_utils
from midvatten.tools.sectionplot._utils import (
    get_legend_items_labels,
    get_plot_label_name,
)
from midvatten.tools.utils.exceptions import UsageError
from midvatten.tools.utils.sampledem import qchain, sampling
from midvatten.tools.sectionplot.data import (
    fill_empty_columns,
    get_length_map,
    get_line_feature_obsid,
)

log = logging.getLogger(__name__)


def paint_bars(
    figure,
    bars_dict: dict,
    template: dict,
    color_dict: dict,
    color_key: str = "color",
    hatch_dict: dict | None = None,
    barwidth: float = 1,
) -> None:
    """Render stratigraphy or hydrology bar plots onto *figure.ax_main*.

    Appends each BarContainer to *figure.plot_handles*.

    Parameters
    ----------
    figure:
        SectionPlotFigure instance.
    bars_dict:
        Mapping ``{typ: {"x": [...], "height": [...], "bottom": [...]}}``.
    template:
        The ``secplot_templates.loaded_template`` dict.
    color_dict:
        Mapping from bar type to a color value.
    color_key:
        Key within the per-type settings dict that holds the color override
        (``"color"`` for geology, ``"color_qt"`` for hydrology).
    hatch_dict:
        Optional mapping from bar type to a hatch pattern string.
    barwidth:
        Width of each bar in axis units.
    """
    for typ, bar_data in bars_dict.items():
        _settings = copy.deepcopy(template["geology_Axes_bar"])
        try:
            settings = _settings[typ]
        except KeyError:
            try:
                settings = _settings["DEFAULT"]
            except KeyError:
                settings = _settings

        for _typ in bars_dict.keys():
            try:
                del settings[_typ]
            except KeyError:
                pass
        try:
            del settings["DEFAULT"]
        except KeyError:
            pass

        settings["width"] = settings.get("width", barwidth)
        settings["color"] = settings.get(color_key, color_dict[typ])
        if hatch_dict is not None:
            settings["hatch"] = settings.get("hatch", hatch_dict[typ])
        settings["label"] = settings.get("label", typ)
        try:
            figure.plot_handles.append(
                figure.ax_main.bar(
                    [x - barwidth / 2 for x in bar_data["x"]],
                    bar_data["height"],
                    bottom=bar_data["bottom"],
                    align="edge",
                    **settings,
                )
            )
        except Exception:
            common_utils.MessagebarAndLog.info(
                bar_msg=QCoreApplication.translate(
                    "Sectionplot",
                    "Type %s color %s could not be plotted. Default to white!. See message log",
                )
                % (str(typ), settings["color"]),
                log_msg=traceback.format_exc(),
            )
            settings["color"] = "white"
            figure.plot_handles.append(
                figure.ax_main.bar(
                    bar_data["x"],
                    bar_data["height"],
                    bottom=bar_data["bottom"],
                    align="edge",
                    **settings,
                )
            )


def paint_screen_bars(
    figure,
    bars_dict: dict,
    style_dict: dict,
    width: float,
    zorder: int = 3,
    width_factor: float = 1.2,
) -> None:
    """Paint screen-interval bars with transparent fill, border, and hatch.

    Each bar group is keyed by ``screenshort`` (lowercased).  Style is looked
    up from *style_dict* with a ``'default'`` fallback.

    Parameters
    ----------
    figure:
        SectionPlotFigure instance.
    bars_dict:
        Mapping ``{screenshort: {"x": [...], "height": [...], "bottom": [...]}}``.
    style_dict:
        Mapping from screenshort (lowercased) to a dict with keys
        ``facecolor``, ``edgecolor``, ``hatch``, ``linewidth``.
    width:
        Base bar width in axis units (same width the stratigraphy uses).
    zorder:
        Matplotlib z-order for the bars.  Use 1 for behind stratigraphy, 3 for
        on top.
    width_factor:
        Multiplier applied to *width* when drawing screen bars so they can be
        drawn slightly wider than the stratigraphy columns.
    """
    _default_style = {
        "facecolor": "none",
        "edgecolor": "black",
        "hatch": "///",
        "linewidth": 1.0,
    }
    fallback = style_dict.get("default", _default_style)

    for screenshort, bar_data in bars_dict.items():
        raw = style_dict.get(screenshort.lower(), fallback)
        style = {
            key: raw.get(key) if raw.get(key) is not None else _default_style[key]
            for key in _default_style
        }
        xs = bar_data["x"]
        heights = bar_data["height"]
        bottoms = bar_data["bottom"]
        bar_width = width * width_factor
        try:
            figure.plot_handles.append(
                figure.ax_main.bar(
                    [x - bar_width / 2 for x in xs],
                    heights,
                    bottom=bottoms,
                    width=bar_width,
                    facecolor=style["facecolor"],
                    edgecolor=style["edgecolor"],
                    hatch=style["hatch"],
                    linewidth=style["linewidth"],
                    label=screenshort,
                    zorder=zorder,
                    align="edge",
                )
            )
        except Exception:
            common_utils.MessagebarAndLog.info(
                bar_msg=QCoreApplication.translate(
                    "Sectionplot",
                    "Screen type %s could not be plotted. See message log",
                )
                % str(screenshort),
                log_msg=traceback.format_exc(),
            )


def paint_drill_stop(
    figure,
    drillstops: list,
    template: dict,
    drillstop_label: str,
) -> None:
    """Render the drill-stop marker line onto *figure.ax_main*.

    Parameters
    ----------
    figure:
        SectionPlotFigure instance.
    drillstops:
        List of ``(x, z_bottom)`` tuples for borehole drill stops.
    template:
        The ``secplot_templates.loaded_template`` dict.
    drillstop_label:
        Label for the legend entry (e.g. ``"drillstop like %berg%"``).
    """
    settings = copy.deepcopy(template["drillstop_Axes_plot"])
    settings["label"] = settings.get("label", drillstop_label)
    settings["picker"] = 2
    (lineplot,) = figure.ax_main.plot(*list(zip(*drillstops)), **settings)
    figure.plot_handles.append(lineplot)


def paint_layer_text(
    figure,
    layer_texts: dict,
    text_key: str,
    text_alignment: str,
    barwidth: float,
    template: dict,
) -> None:
    """Annotate the stratigraphy bars with geological text.

    Parameters
    ----------
    figure:
        SectionPlotFigure instance.
    layer_texts:
        Mapping ``{column_name: {(x, z): text_value}}``.
    text_key:
        The column name to render (e.g. ``"geoshort"``).
    text_alignment:
        ``"center"`` to centre text in bar, ``"edge"`` to align to the right edge.
    barwidth:
        Width of each bar (used to compute x offset for edge alignment).
    template:
        The ``secplot_templates.loaded_template`` dict.
    """
    xy_texts = layer_texts[text_key]
    settings = template["layer_Axes_annotate"]

    for xy, text in xy_texts.items():
        if text is None or not str(text):
            continue
        if text_alignment == "center":
            x = xy[0]
        else:
            x = xy[0] + (barwidth / 2)

        a = figure.ax_main.annotate(text, (x, xy[1]), **settings)
        a.original_xy = xy


def paint_obsids(
    figure,
    z_data: dict,
    obsids_x_position: dict,
    template: dict,
    barwidth: float,
    plot_stratigraphy: bool,
    plot_hydrology: bool,
    plot_labels: bool = True,
) -> None:
    """Draw obsid label annotations and empty borehole frame bars.

    Parameters
    ----------
    figure:
        SectionPlotFigure instance.
    z_data:
        Mapping ``{obsid: {"z": z, "barheight": h, "bottom": b}}``.
    obsids_x_position:
        Mapping ``{obsid: x_position_along_section}``.
    template:
        The ``secplot_templates.loaded_template`` dict.
    barwidth:
        Width of each bar in axis units.
    plot_stratigraphy:
        Whether stratigraphy is being plotted (controls frame-bar rendering).
    plot_hydrology:
        Whether hydrology is being plotted (controls frame-bar rendering).
    plot_labels:
        Whether to annotate obsid labels above the bars.
    """
    if plot_stratigraphy or plot_hydrology:
        plotxleftbarcorner = []
        bottoms = []
        barheights = []

        for obsid, obs_z_data in z_data.items():
            if not obs_z_data["barheight"]:
                continue
            plotxleftbarcorner.append(obsids_x_position[obsid] - barwidth / 2)
            bottoms.append(obs_z_data["bottom"])
            barheights.append(obs_z_data["barheight"])

        if plotxleftbarcorner:
            obsid_axes_bar = copy.deepcopy(template["obsid_Axes_bar"])
            obsid_axes_bar["width"] = obsid_axes_bar.get("width", barwidth)
            obsid_axes_bar["bottom"] = obsid_axes_bar.get("bottom", bottoms)
            obsid_axes_bar["label"] = "frame"
            p = figure.ax_main.bar(
                plotxleftbarcorner, barheights, align="edge", **obsid_axes_bar
            )
            p.skip_legend = True
            figure.plot_handles.append(p)

    if plot_labels:
        for o, m_n in figure.obsid_annotation.items():
            m, n = m_n
            figure.ax_main.annotate(
                o,
                xy=(m, n),
                **template["obsid_Axes_annotate"],
            )


def paint_obs_lines_data(
    figure,
    obs_lines_plot_data,
    y1_column: str,
    y2_column: str,
    y3_column: str,
) -> None:
    """Render seismic / obs-lines data (bedrock, ground, gw_table) lines.

    Parameters
    ----------
    figure:
        SectionPlotFigure instance.
    obs_lines_plot_data:
        NumPy recarray with fields ``obsline_x``, ``obsline_y1``,
        ``obsline_y2``, ``obsline_y3``.
    y1_column, y2_column, y3_column:
        Legend label names for each of the three y-series (e.g.
        ``"bedrock"``, ``"ground"``, ``"gw_table"``).
    """

    def remove_nones(xdata, ydata):
        x_y = [(xdata[idx], row) for idx, row in enumerate(ydata) if not np.isnan(row)]
        x = [row[0] for row in x_y]
        y = [row[1] for row in x_y]
        return x, y

    for col_name, y_data in [
        (y1_column, obs_lines_plot_data.obsline_y1),
        (y2_column, obs_lines_plot_data.obsline_y2),
        (y3_column, obs_lines_plot_data.obsline_y3),
    ]:
        x, y = remove_nones(obs_lines_plot_data.obsline_x, y_data)
        plotlable = get_plot_label_name(
            col_name, get_legend_items_labels(figure.plot_handles)[1]
        )
        (lineplot,) = figure.ax_main.plot(
            x, y, picker=2, marker="+", linestyle="-", label=plotlable
        )
        figure.plot_handles.append(lineplot)


# ---------------------------------------------------------------------------
# Newly extracted painters (Task 4)
# ---------------------------------------------------------------------------


def _nan_helper(y):
    """Helper to handle indices and logical indices of NaNs.

    from https://stackoverflow.com/questions/6518811/interpolate-nan-values-in-a-numpy-array

    Input:
        - y, 1d numpy array with possible NaNs
    Output:
        - nans, logical indices of NaNs
        - index, a function, with signature indices= index(logical_indices),
          to convert logical indices of NaNs to 'equivalent' indices
    Example:
    # linear interpolation of NaNs
    nans, x = _nan_helper(y)
    y[nans] = np.interp(x(nans), x(~nans), y[~nans])
    """
    return np.isnan(y), lambda z: z.nonzero()[0]


def _qgis_color_str_to_mpl(color_str: str) -> tuple:
    """Convert QGIS 'r,g,b[,a]' color string to matplotlib (0..1) float tuple."""
    parts = [int(x) / 255 for x in color_str.split(",")]
    return tuple(parts)


def _sample_polygon(poly_layer, sectionlinelayer, xarray, iface):
    """Sample polygon layer colors along section line.

    Parameters
    ----------
    poly_layer:
        QgsVectorLayer polygon layer.
    sectionlinelayer:
        QGIS layer containing the section line.
    xarray:
        Array of x positions along the section.
    iface:
        QGIS iface reference (needed for render context).
    """
    poly_provider = poly_layer.dataProvider()
    renderer = poly_layer.renderer()
    if not isinstance(renderer, QgsRuleBasedRenderer):
        renderer = QgsRuleBasedRenderer.convertFromRenderer(renderer)
    root_rule = renderer.rootRule()
    rules = root_rule.descendants()

    legend_symbols = root_rule.legendSymbolItems()
    legend_symbols = {item.ruleKey(): item for item in legend_symbols}

    context = QgsRenderContext.fromMapSettings(iface.mapCanvas().mapSettings())

    sampled_values = []

    x0_x1_poly = {}
    for linefeature in sectionlinelayer.getSelectedFeatures():
        linegeom = linefeature.geometry()
        polyfeatures = poly_provider.getFeatures(
            QgsFeatureRequest().setFilterRect(linegeom.boundingBox())
        )
        for polyfeature in polyfeatures:
            intersection = linegeom.intersection(polyfeature.geometry())
            if not intersection.isEmpty():
                intersection.convertToMultiType()
                multiline = intersection.asMultiPolyline()
                for line in multiline:
                    x0 = linegeom.lineLocatePoint(QgsGeometry().fromPointXY(line[0]))
                    x1 = linegeom.lineLocatePoint(QgsGeometry().fromPointXY(line[-1]))
                    k = (x0, x1)
                    if k not in x0_x1_poly:
                        x0_x1_poly[k] = polyfeature

    processed_features = {}

    x0_x1_poly = dict(sorted(x0_x1_poly.items()))
    for x in xarray:
        for (x0, x1), feat in x0_x1_poly.items():
            if x0 <= x <= x1:
                if feat.id() in processed_features:
                    sampled_values.append(processed_features[feat.id()])
                    break

                rendered_rules = [
                    r.ruleKey() for r in rules if r.willRenderFeature(feat, context)
                ]
                label_symbols = [
                    (legend_symbols[k].label(), legend_symbols[k].symbol())
                    for k in rendered_rules
                ]

                if label_symbols:
                    label, symbol = label_symbols[0]
                    symbol_layers = symbol.symbolLayers()
                    # Use the bottom layer color
                    _color = symbol_layers[0].properties()["color"]
                    try:
                        color = _qgis_color_str_to_mpl(_color)
                    except ValueError:
                        if len(_color.split(",")) > 4:
                            color = _qgis_color_str_to_mpl(
                                ",".join(_color.split(",")[:4])
                            )
                        else:
                            raise
                    sampled_values.append((label, color))
                    processed_features[feat.id()] = (label, color)
                else:
                    processed_features[feat.id()] = None
                break
        else:
            sampled_values.append(None)
    return sampled_values


def paint_dems(
    figure,
    dem_layers: dict,
    settingsdict: dict,
    template: dict,
    barwidth: float,
    iface=None,
) -> None:
    """Plot DEM raster layers as line profiles along the section.

    Parameters
    ----------
    figure:
        SectionPlotFigure instance.
    dem_layers:
        Mapping ``{layer_name: QgsRasterLayer}`` of available DEM layers.
    settingsdict:
        ``self.ms.settingsdict`` — used for ``secplotselectedDEMs``,
        ``secplotdem_sampling_distance``, ``secplot_apply_graded_dems``, etc.
    template:
        ``secplot_templates.loaded_template`` dict.
    barwidth:
        Current bar width in axis units; used to compute default sampling distance.
    iface:
        QGIS iface reference (needed for graded-DEM polygon sampling).
    """
    try:
        if (
            settingsdict["secplotselectedDEMs"]
            and len(settingsdict["secplotselectedDEMs"]) > 0
        ):  # Adding a plot for each selected raster
            for layername in settingsdict["secplotselectedDEMs"]:
                if not settingsdict["secplotdem_sampling_distance"]:
                    distance = barwidth / 2.0
                    if not distance:
                        distance = max(
                            figure.line_feature.geometry().length() / 5000, 1
                        )
                else:
                    distance = settingsdict["secplotdem_sampling_distance"]

                temp_memorylayer, xarray = qchain(figure.line_layer, distance)
                dem_data = sampling(temp_memorylayer, dem_layers[str(layername)])
                plotlable = get_plot_label_name(
                    layername, get_legend_items_labels(figure.plot_handles)[1]
                )
                settings = template["dems_Axes_plot"].get(
                    plotlable,
                    template["dems_Axes_plot"]["DEFAULT"],
                )
                template["dems_Axes_plot"][plotlable] = copy.deepcopy(settings)
                settings = template["dems_Axes_plot"][plotlable]
                settings["label"] = settings.get("label", plotlable)
                settings["picker"] = 2
                (lineplot,) = figure.ax_main.plot(xarray, dem_data, **settings)
                figure.plot_handles.append(lineplot)

                if settingsdict["secplot_apply_graded_dems"]:
                    secplot_color_layer_name = f"{layername}_secplotcolor"
                    try:
                        common_utils.find_layer(secplot_color_layer_name)
                    except UsageError:
                        pass
                    else:
                        alpha_max = settingsdict["secplot_grading_max_opacity"]
                        alpha_min = settingsdict["secplot_grading_min_opacity"]
                        number_of_plots = settingsdict["secplot_grading_num_layers"]
                        graded_depth_m = settingsdict["secplot_grading_depth"]
                        skip_labels = []
                        paint_graded_dems(
                            figure,
                            temp_memorylayer,
                            figure.line_layer,
                            xarray,
                            dem_data,
                            secplot_color_layer_name,
                            layername,
                            alpha_max=alpha_max,
                            alpha_min=alpha_min,
                            number_of_plots=number_of_plots,
                            graded_depth_m=graded_depth_m,
                            skip_labels=skip_labels,
                            iface=iface,
                        )
    finally:
        try:
            QgsProject.instance().removeMapLayer(temp_memorylayer.id())
        except Exception:
            common_utils.MessagebarAndLog.info(log_msg=traceback.format_exc())


def paint_graded_dems(
    figure,
    temp_memorylayer,
    sectionlinelayer,
    xarray,
    dem_data,
    layername: str,
    dem_layername: str,
    alpha_max: float = 0.5,
    alpha_min: float = 0,
    number_of_plots: int = 20,
    graded_depth_m: float = 2,
    skip_labels=None,
    iface=None,
) -> None:
    """Paint graded-DEM shading below a DEM profile.

    Parameters
    ----------
    figure:
        SectionPlotFigure instance.
    temp_memorylayer:
        Temporary memory layer with sample points along the section line.
    sectionlinelayer:
        QGIS layer containing the section line (used for polygon sampling).
    xarray:
        Array of x positions along the section.
    dem_data:
        Array of elevation values corresponding to *xarray*.
    layername:
        Name of the color layer (``"{dem_layername}_secplotcolor"``).
    dem_layername:
        Name of the base DEM layer (used for legend labels).
    alpha_max:
        Maximum opacity at the DEM surface.
    alpha_min:
        Minimum opacity at *graded_depth_m* below the surface.
    number_of_plots:
        Number of gradient shading layers.
    graded_depth_m:
        Depth in metres over which the gradient fades.
    skip_labels:
        Optional list of polygon labels to skip.
    iface:
        QGIS iface reference (needed for polygon render context).
    """
    try:
        color_layer = common_utils.find_layer(layername)
    except UsageError:
        return

    points_srid = temp_memorylayer.crs().authid()
    color_layer_srid = color_layer.crs().authid()
    if points_srid != color_layer_srid:
        common_utils.MessagebarAndLog.warning(
            bar_msg=QCoreApplication.translate(
                "SectionPlot",
                "Grade dem: Layer %s had wrong srid! Had '%s' but should have '%s'.",
            )
            % (layername, str(color_layer_srid), str(points_srid))
        )
        return None

    if (
        isinstance(color_layer, QgsVectorLayer)
        or color_layer.type() == QgsMapLayer.LayerType.VectorLayer
    ):
        log.debug("Sampling as polygon")
        labels_colors = _sample_polygon(color_layer, sectionlinelayer, xarray, iface)
    else:
        log.debug("Sampling as raster")
        labels_colors_dict = {}
        colors = sampling(
            temp_memorylayer, color_layer, extract_type="value", bands=(1, 2, 3)
        )
        for color in colors:
            if color is not None:
                if color not in labels_colors_dict:
                    labels_colors_dict[color] = f"{len(labels_colors_dict) + 1}"

        labels_colors = [
            (
                (
                    labels_colors_dict[tuple(color)],
                    tuple(float(c) / 255.0 for c in color),
                )
                if color is not None
                else (None, None)
            )
            for color in colors
        ]
    plot_spec = []
    _x = []
    _y = []
    prev_label = None
    for idx, polylabel_color in enumerate(labels_colors):
        if polylabel_color is None:
            plot_spec.append([prev_label, _x, _y])
            _x = []
            _y = []
            prev_label = None
            continue

        polylabel = polylabel_color[0]
        _x.append(xarray[idx])
        _y.append(dem_data[idx])
        if prev_label is not None and prev_label != polylabel:
            plot_spec.append([prev_label, _x, _y])
            _x = [xarray[idx]]
            _y = [dem_data[idx]]
        prev_label = polylabel
    else:
        plot_spec.append([prev_label, _x, _y])

    labels_colors_dict = {
        label_color[0]: label_color[1]
        for label_color in labels_colors
        if label_color is not None
    }

    plotted_axvlines = set()
    plotted_polylabels = set()
    for label, x_vals, y_vals in plot_spec:
        _y_vals = list(y_vals)
        if (skip_labels and label in skip_labels) or label is None:
            continue

        plotlable = get_plot_label_name(
            f"{dem_layername} {label}",
            get_legend_items_labels(figure.plot_handles)[1],
        )
        if not number_of_plots:
            continue
        graded_plot_height = float(graded_depth_m) / float(number_of_plots)
        color = labels_colors_dict[label]

        gradients = np.linspace(alpha_max, alpha_min, int(number_of_plots))
        for grad_idx, grad in enumerate(gradients):
            y1 = [_y - graded_plot_height for _y in y_vals]
            theplot = figure.ax_main.fill_between(
                x_vals,
                y1,
                y_vals,
                alpha=grad,
                facecolor=color,
                linewidth=0,
                label=plotlable,
                picker=2,
            )

            figure.plot_handles.append(theplot)
            if label in plotted_polylabels:
                theplot.skip_legend = True
            else:
                theplot.skip_legend = False
                plotted_polylabels.add(label)
            y_vals = list(y1)

        for _idx in [0, -1]:
            if x_vals[_idx] not in plotted_axvlines:
                figure.ax_main.plot(
                    [x_vals[_idx], x_vals[_idx]],
                    [_y_vals[_idx] - graded_depth_m, _y_vals[_idx]],
                    color="brown",
                    linestyle="-",
                )
                plotted_axvlines.add(x_vals[_idx])


def paint_tem(
    figure,
    dbconnection,
    settingsdict: dict,
    template: dict,
) -> None:
    """Plot TEM (Time-domain Electromagnetic) inversion results.

    Parameters
    ----------
    figure:
        SectionPlotFigure instance.
    dbconnection:
        Active ``DbConnectionManager`` (used for SQL queries and pandas read).
    settingsdict:
        ``self.ms.settingsdict`` — used for TEM display settings.
    template:
        ``secplot_templates.loaded_template`` dict.
    """
    if not settingsdict["secplot_tem_model_name"]:
        return

    tables = db_utils.get_tables()
    if "tem_data" not in tables:
        return

    line_obsid = get_line_feature_obsid(figure.line_feature)
    if line_obsid is None:
        return

    df = pd.read_sql(
        f"""SELECT length, thickness, resistivity, elevation, doi, data_fit FROM tem_data WHERE inversion_name = {dbconnection.placeholder()} AND obsid = {dbconnection.placeholder()} ORDER BY length;""",
        dbconnection.conn,
        params=(
            settingsdict["secplot_tem_model_name"],
            line_obsid,
        ),
    )

    vmin = None
    vmax = None

    number_of_layers = 0
    for col in ["thickness", "resistivity"]:
        df[col] = df[col].apply(eval)
        _max_layers = df[col].apply(len).max()
        number_of_layers = max(_max_layers, number_of_layers)

    def create_array(shape):
        a = np.empty(shape=shape)
        a[:] = np.nan
        return a

    shading = settingsdict["secplot_tem_shading"]

    if shading == "nearest":
        new_idx_map, min_column_width = get_length_map(df["length"])
    else:
        new_idx_map = {idx: idx for idx in range(len(df["length"]))}

    shape = (number_of_layers, max(list(new_idx_map.values())) + 1)
    x_arr = create_array(shape)
    y_arr = create_array(shape)
    z_arr = create_array(shape)
    z_below_doi = create_array(shape)

    for idx, (
        length,
        thickness,
        resistivity,
        elevation,
        doi,
        data_fit,
    ) in enumerate(df.itertuples(index=False)):
        resistivity = np.array(resistivity)
        if len(thickness) < len(resistivity):
            thickness.append(thickness[-1])
        thickness = np.array(thickness)

        layers_top = [0]
        layers_top.extend(thickness[:-1])
        layers_top = np.array(layers_top).cumsum()
        layers_top = elevation - layers_top
        layers_middle = layers_top - thickness / 2

        # Split the plot into above and below doi (depth of investigation)
        resistivity_below_doi = resistivity.copy()
        if doi is None:
            vmin = min(resistivity) if vmin is None else min(vmin, min(resistivity))
            vmax = max(resistivity) if vmax is None else max(vmax, max(resistivity))
        else:
            mask_above_doi = layers_top >= (
                elevation - doi
            )  # (layers + thickness/2) >= (elevation - doi)
            if any(mask_above_doi):
                resistivity_above_doi = resistivity[mask_above_doi]
                vmin = (
                    min(resistivity_above_doi)
                    if vmin is None
                    else min(vmin, min(resistivity_above_doi))
                )
                vmax = (
                    max(resistivity_above_doi)
                    if vmax is None
                    else max(vmax, max(resistivity_above_doi))
                )

            resistivity[~mask_above_doi] = np.nan
            resistivity_below_doi[mask_above_doi] = np.nan

        adjusted_idx = new_idx_map[idx]
        x_arr[:, adjusted_idx] = length
        y_arr[: len(resistivity), adjusted_idx] = layers_middle
        z_arr[: len(resistivity), adjusted_idx] = resistivity
        z_below_doi[: len(resistivity_below_doi), adjusted_idx] = resistivity_below_doi

    if shading == "nearest":
        fill_empty_columns(new_idx_map, min_column_width, x_arr, y_arr)

    maximum_depth = max(y_arr[-1, :])
    y_arr[-1, :] = np.where(np.isnan(y_arr[-1, :]), maximum_depth, y_arr[-1, :])
    nans, x = _nan_helper(y_arr)
    y_arr[nans] = np.interp(x(nans), x(~nans), y_arr[~nans])

    if settingsdict["secplot_tem_vmin"].strip():
        try:
            vmin = float(settingsdict["secplot_tem_vmin"].strip().replace(",", "."))
        except Exception:
            common_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "SectionPlot",
                    "Error: Supplied vmin could not be interpreted as a number",
                )
            )
    if settingsdict["secplot_tem_vmax"].strip():
        try:
            vmax = float(settingsdict["secplot_tem_vmax"].strip().replace(",", "."))
        except Exception:
            common_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "SectionPlot",
                    "Error: Supplied vmax could not be interpreted as a number",
                )
            )

    snap = settingsdict["secplot_tem_snap"]
    rasterized = settingsdict["secplot_tem_rasterized"]
    edgecolors = (
        settingsdict["secplot_tem_edgecolors"].strip()
        if settingsdict["secplot_tem_edgecolors"].strip()
        else "none"
    )
    shading = settingsdict["secplot_tem_shading"]
    cmap = settingsdict["secplot_tem_colormap"]
    norm = settingsdict["secplot_tem_norm"]

    z_masked = np.ma.masked_invalid(z_arr)

    above_doi = figure.ax_main.pcolormesh(
        x_arr,
        y_arr,
        z_masked,
        cmap=cmap,
        norm=norm,
        vmin=vmin,
        vmax=round(vmax, 0) if vmax is not None else vmax,
        zorder=1,
        snap=snap,
        edgecolors=edgecolors,
        alpha=settingsdict["secplot_tem_alpha_above_doi"],
        shading=shading,
        rasterized=rasterized,
    )

    figure.plot_handles.append(above_doi)
    if not df["doi"].dropna().empty:
        m_z_below_doi = np.ma.masked_invalid(z_below_doi)
        below_doi = figure.ax_main.pcolormesh(
            x_arr,
            y_arr,
            m_z_below_doi,
            cmap=cmap,
            norm=norm,
            vmin=vmin,
            vmax=round(vmax, 0) if vmax is not None else vmax,
            zorder=1,
            snap=snap,
            edgecolors=edgecolors,
            alpha=settingsdict["secplot_tem_alpha_below_doi"],
            shading=shading,
            rasterized=rasterized,
        )

        a = figure.ax_main.plot(
            df["length"],
            df["elevation"] - df["doi"],
            color="k",
            label="TEM DOI",
            linestyle=":",
        )[0]
        figure.plot_handles.append(a)

    if settingsdict["secplot_tem_norm"] == "log":
        ticks = []
        for pow in range(6):
            ticks.extend(np.linspace(10**pow, 10 ** (pow + 1), 10))
    else:
        ticks = None

    label = (
        QCoreApplication.translate("SectionPlot", "Resistivity")
        + " "
        + settingsdict["secplot_tem_model_name"]
    )
    cbar = figure.colorbar(above_doi, label=label, ticks=ticks)
    figure.tem_cbar_label = label

    if ticks is not None:
        cbar.ax.set_yticklabels(
            [f"{v:.0f}" for v in cbar.ax.get_yticks()],
            **template["ticklabels_Text_set_fontsize"],
        )

    data_fit = settingsdict["secplot_tem_data_fit"]
    if data_fit:
        if getattr(figure, "ax_data_fit", None) is None:
            figure.ax_data_fit = figure.ax_main.twinx()
            figure.ax_data_fit.midv_axes_name = "data_fit"
            figure.ax_data_fit.set_ylabel("TEM data fit")
        a = figure.ax_data_fit.plot(
            df["length"],
            df["data_fit"],
            color="k",
            label="TEM data fit",
            linestyle=":",
            alpha=0.5,
        )[0]
        figure.plot_handles.append(a)


def paint_images(
    figure,
    dbconnection,
    settingsdict: dict,
) -> None:
    """Plot images registered in the ``profile_images`` table.

    Parameters
    ----------
    figure:
        SectionPlotFigure instance.
    dbconnection:
        Active ``DbConnectionManager`` (used for SQL queries).
    settingsdict:
        ``self.ms.settingsdict`` — used for image selection and display options.
    """
    if not figure.line_layer:
        return

    tables = db_utils.get_tables()
    if "profile_images" not in tables:
        return

    if not settingsdict["secplot_images_images"]:
        return

    line_obsid = get_line_feature_obsid(figure.line_feature)
    if line_obsid is None:
        return

    labels = []

    res = dbconnection.execute_and_fetchall(
        f"SELECT alias, path, clip_left_right_top_bottom, extent_left_right_top_bottom FROM profile_images WHERE obsid = {dbconnection.placeholder()}",
        args=(line_obsid,),
    )

    alphas = [
        float(x.strip().replace(",", "."))
        for x in settingsdict.get("secplot_images_alpha", "").strip().split(";")
        if x.strip()
    ]
    if not alphas:
        alphas = [1.0]

    zorders = [
        int(x.strip().replace(",", "."))
        for x in settingsdict.get("secplot_images_zorder", "").strip().split(";")
        if x.strip()
    ]
    if not zorders:
        zorders = [0]

    selected_images = settingsdict.get("secplot_images_images", "[]")
    if selected_images.strip():
        try:
            selected_images = json.loads(selected_images.strip())
        except (json.JSONDecodeError, ValueError):
            selected_images = ast.literal_eval(selected_images.strip())
    else:
        return

    for idx, selected_alias in enumerate(selected_images):
        for (
            alias,
            _path,
            clip_left_right_top_bottom,
            extent_left_right_top_bottom,
        ) in res:
            if not alias == selected_alias:
                continue

            path = None
            if os.path.isfile(_path):
                path = _path
            else:
                if dbconnection.is_sqlite():
                    new_path = os.path.join(os.path.dirname(dbconnection.dbpath), _path)
                    if os.path.isfile(new_path):
                        path = new_path

            if path is None:
                common_utils.MessagebarAndLog.warning(
                    bar_msg=QCoreApplication.translate(
                        "SectionPlot",
                        "Error: The image path '%s' could not be found!",
                    )
                    % _path
                )
                continue

            alpha = (
                alphas[0]
                if len(alphas) <= 1
                else alphas[idx]
                if idx < len(alphas)
                else alphas[-1]
            )
            zorder = (
                zorders[0]
                if len(zorders) <= 1
                else zorders[idx]
                if idx < len(zorders)
                else zorders[-1]
            )

            left, right, top, bottom = ast.literal_eval(extent_left_right_top_bottom)

            im = plt.imread(path)

            clip = settingsdict.get("secplot_images_clip", True)
            if clip_left_right_top_bottom:
                clip_left_right_top_bottom = ast.literal_eval(
                    clip_left_right_top_bottom
                )
                clip_left, clip_right, clip_top, clip_bottom = (
                    clip_left_right_top_bottom
                )
                if clip:
                    im = im[clip_top:clip_bottom, clip_left:clip_right]
                else:
                    # Calculate the full extent of the image
                    numrows, numcols, _ = im.shape
                    if clip_right != clip_left:
                        dx = (right - left) / (clip_right - clip_left)
                        left = -clip_left * dx + left
                        right = (numcols - clip_right) * dx + right
                    if clip_bottom != clip_top:
                        dy = (bottom - top) / (clip_bottom - clip_top)
                        top = -clip_top * dy + top
                        bottom = (numrows - clip_bottom) * dy + bottom

            figure.ax_main.imshow(
                im,
                extent=[left, right, bottom, top],
                zorder=zorder,
                alpha=alpha,
                clip_on=True,
                aspect="auto",
                label=alias,
            )
            labels.append(alias)
    figure.images_labels = list(sorted(set(labels)))


def paint_specific_water_level(
    figure,
    dbconnection,
    settingsdict: dict,
    obsids_x_position: dict,
    waterlevel_lineplot_fn,
) -> None:
    """Plot water level markers for each date listed in settingsdict["secplotdates"].

    Parameters
    ----------
    figure:
        SectionPlotFigure instance.
    dbconnection:
        Active ``DbConnectionManager`` (used for SQL queries).
    settingsdict:
        ``self.ms.settingsdict`` — read for ``secplotdates``, ``secplotwlvltab``,
        ``stratigraphyplotted``, ``secplothydrologyplotted``.
    obsids_x_position:
        Mapping ``{obsid: x_position}`` for all observation points.
    waterlevel_lineplot_fn:
        Callable ``(x_wl, wl, date_str)`` that renders the water level line
        and appends a handle to ``figure.plot_handles``.
    """
    for secplotdates in settingsdict["secplotdates"]:
        if secplotdates.startswith("#"):
            continue
        date_obsids = secplotdates.split(";")
        _date = date_obsids[0]
        wl = []
        x_wl = []
        for obs, x in obsids_x_position.items():
            if len(date_obsids) > 1:
                if obs not in date_obsids[1:]:
                    continue

            # TODO: There should probably be a setting for using avg(level_masl)
            tab = settingsdict["secplotwlvltab"]
            ph_obs = dbconnection.placeholder()
            _d = _date.replace("-", "").replace(" ", "").strip()
            for _int in range(10):
                _d = _d.replace(str(_int), "")
            if _d:
                # Treat _date as a value (parameterized), not as raw SQL.
                ph_date = dbconnection.placeholder()
                sql = dbconnection.sql_ident(
                    f"SELECT level_masl FROM {{t}} WHERE obsid = {ph_obs} AND date_time = {ph_date} AND level_masl IS NOT NULL",
                    t=tab,
                )
                res = dbconnection.execute_and_fetchall(sql, (obs, _date))
            else:
                ph_like = dbconnection.placeholder()
                sql = dbconnection.sql_ident(
                    f"SELECT level_masl FROM {{t}} WHERE obsid = {ph_obs} AND date_time LIKE {ph_like} ORDER BY date_time ASC",
                    t=tab,
                )
                res = dbconnection.execute_and_fetchall(sql, (obs, f"{_date}%"))
            # query = """SELECT avg(level_masl) FROM {} WHERE obsid = '{}' AND date_time like '{}%'""".format(settingsdict['secplotwlvltab'], obs, _date)

            try:
                val = res[0][0]
            except IndexError:
                continue

            if val is None:
                continue

            wl.append(val)
            x_wl.append(x)
            if obs not in figure.obsid_annotation or not any(
                [
                    settingsdict["stratigraphyplotted"],
                    settingsdict["secplothydrologyplotted"],
                ]
            ):
                figure.obsid_annotation[obs] = (x_wl[-1], wl[-1])
        waterlevel_lineplot_fn(x_wl, wl, _date)


def paint_water_level(
    figure,
    dbconnection,
    settingsdict: dict,
    obsids_x_position: dict,
    waterlevel_lineplot_fn,
    plot_specific_dates: bool,
) -> None:
    """Plot water level lines (specific-date variant only).

    The interactive water level (slider) is NOT rendered here — it stays in
    the orchestrator (``SectionPlot.plot_water_level_interactive``).

    Parameters
    ----------
    figure:
        SectionPlotFigure instance.
    dbconnection:
        Active ``DbConnectionManager``.
    settingsdict:
        ``self.ms.settingsdict``.
    obsids_x_position:
        Mapping ``{obsid: x_position}`` for all observation points.
    waterlevel_lineplot_fn:
        Callable ``(x_wl, wl, date_str)`` that renders the water level line.
    plot_specific_dates:
        Whether the specific-dates groupbox is checked (``self.specific_dates_groupbox.isChecked()``).
    """
    if not settingsdict["secplotwlvltab"]:
        return
    if plot_specific_dates:
        if (
            settingsdict["secplotdates"] and len(settingsdict["secplotdates"]) > 0
        ):  # PLOT Water Levels
            paint_specific_water_level(
                figure,
                dbconnection,
                settingsdict,
                obsids_x_position,
                waterlevel_lineplot_fn,
            )


def configure_axes(
    figure,
    template: dict,
    barwidth: float,
) -> None:
    """Set xlim and ylim on *figure.ax_main* from template or auto-calculated values.

    If there is no stratigraphy data and no borehole length for first or last
    observations, autoscaling will fail silently since it does not consider
    axes.annotate (which is used for printing obsid). This special treatment
    checks if xlim are less than expected from lengthalong.

    Parameters
    ----------
    figure:
        SectionPlotFigure instance — ``figure.obsids_x_position`` and
        ``figure.ax_main`` are read directly.
    template:
        ``secplot_templates.loaded_template`` dict.
    barwidth:
        Current bar width in axis units.
    """
    xmin_xmax = template["Axes_set_xlim"]
    if xmin_xmax is not None:
        xmin, xmax = xmin_xmax
    else:
        if figure.obsids_x_position:
            _xmin, _xmax = figure.ax_main.get_xlim()
            xmin = min(
                float(min(figure.obsids_x_position.values())) - barwidth,
                _xmin,
            )
            xmax = max(
                float(max(figure.obsids_x_position.values())) + barwidth,
                _xmax,
            )
        else:
            xticks = figure.ax_main.get_xticks()
            # shift half a step left and right
            xmin = (3 * xticks[0] - xticks[1]) / 2.0
            xmax = (3 * xticks[-1] - xticks[-2]) / 2.0
    figure.ax_main.set_xlim(xmin, xmax)

    ymin_ymax = template["Axes_set_ylim"]
    if ymin_ymax is not None:
        ymin, ymax = ymin_ymax
    else:
        yticks = figure.ax_main.get_yticks()
        # shift half a step up and down
        ymin = (3 * yticks[0] - yticks[1]) / 2.0
        ymax = (3 * yticks[-1] - yticks[-2]) / 2.0
    figure.ax_main.set_ylim(ymin, ymax)


def finish_plot(
    figure,
    template: dict,
    legend_manager,
) -> None:
    """Apply final matplotlib formatting (grid, labels, ticks, legend) to *figure*.

    Qt-widget operations (update_plot_size, attach_signals, canvas.draw_idle,
    tab_widget.setCurrentIndex, plt.close) are intentionally NOT done here —
    they remain in the orchestrator's ``finish_plot`` method.

    Parameters
    ----------
    figure:
        SectionPlotFigure instance.
    template:
        ``secplot_templates.loaded_template`` dict.
    legend_manager:
        ``SectionPlotLegendManager`` instance (or ``None`` to skip legend).
    """
    figure.ax_main.grid(**template["grid_Axes_grid"])
    if not figure.line_layer:  # Test produces simple stratigraphy plot
        figure.ax_main.set_xticks(
            list(figure.obsids_x_position.values())
        )  # Places ticks where plots are
        for label in figure.ax_main.set_xticklabels(
            list(figure.obsids_x_position.keys())
        ):  # Sets tick labels as obsids
            label.set_fontsize(**template["ticklabels_Text_set_fontsize"])
        axes_set_xlabel = dict(
            [
                (k, v)
                for k, v in template.get("Axes_set_xlabel", {}).items()
                if k != "xlabel"
            ]
        )
        xlabel = template.get("Axes_set_xlabel_stratplot", {}).get(
            "xlabel",
            defs.secplot_default_template()["Axes_set_xlabel_stratplot"]["xlabel"],
        )

    else:
        figure.ax_main.xaxis.set_major_formatter(
            tick.ScalarFormatter(useOffset=False, useMathText=False)
        )
        for label in figure.ax_main.xaxis.get_ticklabels():
            label.set_fontsize(**template["ticklabels_Text_set_fontsize"])
        axes_set_xlabel = dict(
            [
                (k, v)
                for k, v in template.get("Axes_set_xlabel", {}).items()
                if k != "xlabel"
            ]
        )
        xlabel = template.get("Axes_set_xlabel", {}).get(
            "xlabel", defs.secplot_default_template()["Axes_set_xlabel"]["xlabel"]
        )
    if figure.line_layer:
        line_obsid = get_line_feature_obsid(figure.line_feature)
        if line_obsid is not None:
            xlabel += f" {line_obsid}"
            figure.figname = line_obsid
    figure.ax_main.set_xlabel(
        xlabel, **axes_set_xlabel
    )  # Allows international characters ('åäö') as xlabel
    figure.ax_main.yaxis.set_major_formatter(
        tick.ScalarFormatter(useOffset=False, useMathText=False)
    )

    axes_set_ylabel = dict(
        [
            (k, v)
            for k, v in template.get("Axes_set_ylabel", {}).items()
            if k != "ylabel"
        ]
    )
    ylabel = template.get("Axes_set_ylabel", {}).get(
        "ylabel", defs.secplot_default_template()["Axes_set_ylabel"]["ylabel"]
    )
    figure.ax_main.set_ylabel(
        ylabel, **axes_set_ylabel
    )  # Allows international characters ('åäö') as ylabel

    for label in figure.ax_main.yaxis.get_ticklabels():
        label.set_fontsize(**template["ticklabels_Text_set_fontsize"])
    if getattr(figure, "ax_data_fit", None) is not None:
        for label in figure.ax_data_fit.yaxis.get_ticklabels():
            label.set_fontsize(**template["ticklabels_Text_set_fontsize"])

    if template["Figure_subplots_adjust"]:
        figure.subplots_adjust(**template["Figure_subplots_adjust"])

    if legend_manager is not None:
        if getattr(figure, "ax_data_fit", None) is not None:
            leg_ax = figure.ax_data_fit
        else:
            leg_ax = figure.ax_main
        legend_manager.rebuild(leg_ax, figure.plot_handles)
