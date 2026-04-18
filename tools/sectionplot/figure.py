#! /usr/bin/env python
"""
SectionPlotFigure — matplotlib Figure subclass that carries SectionPlot state.

Kept in its own module so that detached-figure callbacks can import it without
pulling in the full QDockWidget dependency tree.
"""

from __future__ import annotations

import matplotlib as mpl
from typing import TYPE_CHECKING

try:
    import pandas as pd
except Exception:
    pd = None  # type: ignore[assignment]

from midvatten.tools.utils.gui_utils import DetachFigureButton

if TYPE_CHECKING:
    from midvatten.tools.sectionplot.legend import SectionPlotLegendManager


class SectionPlotFigure(mpl.figure.Figure):
    """Matplotlib Figure subclass that carries SectionPlot application state.

    When the figure is detached from the Qt dock into a standalone window,
    SectionPlot is no longer reachable, but legend-update callbacks still need
    access to the plot handles, axes references, and QGIS layer refs stored
    here. Declaring them as proper typed attributes gives IDE support and
    makes the contract explicit.

    Instantiate with: plt.figure(FigureClass=SectionPlotFigure)
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Axes
        self.ax_main: mpl.axes.Axes | None = None
        self.ax_wlvl: mpl.axes.Axes | None = None
        self.ax_slider: mpl.axes.Axes | None = None
        self.ax_data_fit: mpl.axes.Axes | None = None
        # Plot handles list — used to rebuild the legend
        self.plot_handles: list = []
        self.waterlevel_lineplot: mpl.artist.Artist | None = None
        # Water level data for interactive slider
        self.df = None  # pd.DataFrame | None
        # QGIS refs (set to None when not running in QGIS)
        self.line_layer = None
        self.line_feature = None
        # Annotation state
        self.obsid_annotation: dict = {}
        self.obsids_x_position: dict = {}
        self.images_labels: list = []
        self.tem_cbar_label: str = ""
        self.figname: str = ""
        # Interactive widgets
        self.detach_figure_button: DetachFigureButton | None = None
        self.date_slider = None
        self.axvline: mpl.lines.Line2D | None = None
        # Legend manager — survives figure detach
        self.legend_manager: SectionPlotLegendManager | None = None
        # Event connection ID for the legend-update draw callback
        self.update_legend_cid: int | None = None
