#! /usr/bin/env python
"""
painters.py — pure-matplotlib rendering helpers for SectionPlot.

Each function here takes a SectionPlotFigure (and the data/settings it needs)
and draws directly onto ``figure.ax_main``, appending plot handles to
``figure.plot_handles``.  None of the functions here touch ``self`` of the
SectionPlot QDockWidget.
"""

import copy
import traceback

from qgis.PyQt.QtCore import QCoreApplication

from midvatten.tools.utils import common_utils
from midvatten.tools.sectionplot._utils import (
    get_legend_items_labels,
    get_plot_label_name,
)


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
    import numpy as np

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
