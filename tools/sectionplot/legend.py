#! /usr/bin/env python
"""
SectionPlotLegendManager — rebuilds the section plot legend with preserved
custom formatting.

Matplotlib's built-in legend editor discards custom font sizes and other
formatting when "update legend" is clicked. This class holds a formatting
config and rebuilds the legend with the saved settings whenever the legend
needs to be updated — e.g. after new artists are added to the figure.
"""

from midvatten.tools.utils.common_utils import LEGEND_NCOL_KEY
from midvatten.tools.sectionplot._utils import get_legend_items_labels

_LEGACY_NCOL_KEY = "ncol"  # Matplotlib < 3.6 used "ncol"; >= 3.6 uses "ncols"


class SectionPlotLegendManager:
    """Rebuilds the section plot legend with preserved custom formatting.

    Matplotlib's built-in legend editor discards custom font sizes and
    other formatting when "update legend" is clicked. This class holds
    a formatting config and rebuilds the legend with the saved settings
    whenever the legend needs to be updated — e.g. after new artists
    are added to the figure.
    """

    def __init__(self, legend_config: dict):
        """
        legend_config: dict of kwargs forwarded to ax.legend(), plus
        additional display settings under the keys:
          - 'frame_facecolor': forwarded to leg.get_frame().set_facecolor()
          - 'frame_fill':      forwarded to leg.get_frame().set_fill()
          - 'text_fontsize':   forwarded to t.set_fontsize() for each legend text
        """
        self.legend_config = legend_config

    @classmethod
    def from_template(cls, loaded_template: dict) -> "SectionPlotLegendManager":
        """Build a SectionPlotLegendManager from a secplot loaded_template dict.

        Extracts and normalises the legend display settings so the caller
        does not need to know the internal template key names.
        """
        legend_kwargs = dict(loaded_template["legend_Axes_legend"])
        # Normalise ncol vs ncols key (matplotlib changed the kwarg name).
        if LEGEND_NCOL_KEY not in legend_kwargs:
            if _LEGACY_NCOL_KEY in legend_kwargs:
                legend_kwargs[LEGEND_NCOL_KEY] = legend_kwargs.pop(_LEGACY_NCOL_KEY)

        config = dict(legend_kwargs)
        config["frame_facecolor"] = loaded_template["legend_Frame_set_facecolor"]
        config["frame_fill"] = loaded_template["legend_Frame_set_fill"]
        config["text_fontsize"] = loaded_template["legend_Text_set_fontsize"]
        return cls(config)

    def rebuild(self, ax, plot_handles: list) -> None:
        """Rebuild the legend on *ax* using *plot_handles* and stored config.

        plot_handles: list of matplotlib artist objects (Line2D, BarContainer,
        PolyCollection, …) — items with ``skip_legend=True`` are excluded.
        """
        items, labels = get_legend_items_labels(plot_handles)
        if not items:
            # Nothing to show — don't create an empty legend frame
            return

        # Separate display-only keys from kwargs forwarded to ax.legend().
        frame_facecolor = self.legend_config.pop("frame_facecolor", None)
        frame_fill = self.legend_config.pop("frame_fill", None)
        text_fontsize = self.legend_config.pop("text_fontsize", None)

        try:
            leg = ax.legend(items, labels, **self.legend_config)
        finally:
            # Restore the display-only keys so the config remains reusable.
            if frame_facecolor is not None:
                self.legend_config["frame_facecolor"] = frame_facecolor
            if frame_fill is not None:
                self.legend_config["frame_fill"] = frame_fill
            if text_fontsize is not None:
                self.legend_config["text_fontsize"] = text_fontsize

        try:
            leg.set_draggable(state=True)
        except AttributeError:
            # For older versions of matplotlib.
            leg.draggable(state=True)
        leg.set_zorder(999)

        frame = leg.get_frame()
        if frame_facecolor is not None:
            frame.set_facecolor(frame_facecolor)
        if frame_fill is not None:
            frame.set_fill(frame_fill)

        if text_fontsize is not None:
            for t in leg.get_texts():
                t.set_fontsize(text_fontsize)
