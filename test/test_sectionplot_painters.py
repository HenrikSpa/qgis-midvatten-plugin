"""Unit tests for sectionplot/painters.py pure rendering functions.

painters.py functions take a SectionPlotFigure (a matplotlib Figure subclass)
and draw onto figure.ax_main, appending handles to figure.plot_handles.
No real DB or QGIS layer is needed for these tests.
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from unittest import mock

from midvatten.tools.sectionplot.figure import SectionPlotFigure
from midvatten.tools.sectionplot.painters import (
    _qgis_color_str_to_mpl,
    paint_bars,
    paint_screen_bars,
    paint_drill_stop,
    paint_layer_text,
    paint_obsids,
)

MINIMAL_TEMPLATE = {
    "geology_Axes_bar": {"DEFAULT": {"edgecolor": "black"}},
    "drillstop_Axes_plot": {
        "color": "black",
        "marker": "^",
        "markersize": 8,
        "linestyle": "",
    },
    "layer_Axes_annotate": {
        "va": "center",
        "xytext": (5, 0),
        "fontsize": 9,
        "bbox": {
            "alpha": 0.6,
            "fc": "white",
            "boxstyle": "square,pad=0.05",
            "edgecolor": "white",
        },
        "ha": "left",
        "textcoords": "offset points",
    },
    "obsid_Axes_bar": {"edgecolor": "black", "linewidth": 0.5},
    "obsid_Axes_annotate": {
        "va": "top",
        "xytext": (0, 10),
        "fontsize": 9,
        "bbox": {
            "alpha": 0.4,
            "fc": "white",
            "boxstyle": "square,pad=0.05",
            "edgecolor": "white",
        },
        "rotation": 0,
        "ha": "center",
        "textcoords": "offset points",
    },
}


def _make_figure() -> SectionPlotFigure:
    """Return a fresh SectionPlotFigure with ax_main configured."""
    fig = plt.figure(FigureClass=SectionPlotFigure)
    fig.ax_main = fig.add_subplot(111)
    fig.plot_handles = []
    fig.obsid_annotation = {}
    return fig


# ---------------------------------------------------------------------------
# _qgis_color_str_to_mpl — pure function, no DB, no mock needed
# ---------------------------------------------------------------------------


class TestQgisColorStrToMpl:
    def test_rgb_string(self):
        r, g, b = _qgis_color_str_to_mpl("255,128,0")
        assert abs(r - 1.0) < 1e-6
        assert abs(g - 128 / 255) < 1e-6
        assert abs(b - 0.0) < 1e-6

    def test_rgba_string(self):
        result = _qgis_color_str_to_mpl("255,0,0,128")
        assert len(result) == 4
        assert abs(result[3] - 128 / 255) < 1e-6

    def test_black(self):
        assert _qgis_color_str_to_mpl("0,0,0") == (0.0, 0.0, 0.0)

    def test_white(self):
        assert _qgis_color_str_to_mpl("255,255,255") == (1.0, 1.0, 1.0)


# ---------------------------------------------------------------------------
# paint_bars
# ---------------------------------------------------------------------------


@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
class TestPaintBars:
    def test_adds_one_handle_per_type(self, mock_messagebar):
        """paint_bars appends one BarContainer per bar type."""
        fig = _make_figure()
        bars_dict = {
            "sand": {"x": [2.0], "height": [2.0], "bottom": [-2.0]},
            "gravel": {"x": [8.0], "height": [3.0], "bottom": [-3.0]},
        }
        color_dict = {"sand": "yellow", "gravel": "gray"}

        paint_bars(fig, bars_dict, MINIMAL_TEMPLATE, color_dict)

        print(f"{mock_messagebar.mock_calls=}")
        assert len(fig.plot_handles) == 2

    def test_single_type(self, mock_messagebar):
        fig = _make_figure()
        bars_dict = {"clay": {"x": [1.0], "height": [5.0], "bottom": [-5.0]}}
        color_dict = {"clay": "brown"}

        paint_bars(fig, bars_dict, MINIMAL_TEMPLATE, color_dict)

        print(f"{mock_messagebar.mock_calls=}")
        assert len(fig.plot_handles) == 1

    def test_invalid_color_falls_back_to_white(self, mock_messagebar):
        """paint_bars recovers when the color string is invalid."""
        fig = _make_figure()
        bars_dict = {"rock": {"x": [1.0], "height": [1.0], "bottom": [0.0]}}
        color_dict = {"rock": "not-a-color"}

        paint_bars(fig, bars_dict, MINIMAL_TEMPLATE, color_dict)

        print(f"{mock_messagebar.mock_calls=}")
        # The fallback bar is still rendered (white), so one handle is still present.
        assert len(fig.plot_handles) == 1

    def test_bar_label_is_type_name(self, mock_messagebar):
        """The bar container's label matches the geology type name."""
        fig = _make_figure()
        bars_dict = {"limestone": {"x": [3.0], "height": [4.0], "bottom": [-4.0]}}
        color_dict = {"limestone": "beige"}

        paint_bars(fig, bars_dict, MINIMAL_TEMPLATE, color_dict)

        print(f"{mock_messagebar.mock_calls=}")
        assert fig.plot_handles[0].get_label() == "limestone"


# ---------------------------------------------------------------------------
# paint_screen_bars
# ---------------------------------------------------------------------------


@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
class TestPaintScreenBars:
    def test_adds_handle_per_screenshort(self, mock_messagebar):
        fig = _make_figure()
        bars_dict = {
            "open": {"x": [2.0], "height": [1.0], "bottom": [-3.0]},
        }

        paint_screen_bars(fig, bars_dict, style_dict={}, width=1.0)

        print(f"{mock_messagebar.mock_calls=}")
        assert len(fig.plot_handles) == 1

    def test_two_screen_types(self, mock_messagebar):
        fig = _make_figure()
        bars_dict = {
            "open": {"x": [2.0], "height": [1.0], "bottom": [-3.0]},
            "cased": {"x": [5.0], "height": [2.0], "bottom": [-5.0]},
        }

        paint_screen_bars(fig, bars_dict, style_dict={}, width=1.0)

        print(f"{mock_messagebar.mock_calls=}")
        assert len(fig.plot_handles) == 2

    def test_custom_style_applied(self, mock_messagebar):
        """Style from style_dict is used when screenshort key matches."""
        fig = _make_figure()
        bars_dict = {"cased": {"x": [3.0], "height": [2.0], "bottom": [-5.0]}}
        style_dict = {
            "cased": {
                "facecolor": "blue",
                "edgecolor": "red",
                "hatch": "xx",
                "linewidth": 2.0,
            }
        }

        paint_screen_bars(fig, bars_dict, style_dict=style_dict, width=1.0)

        print(f"{mock_messagebar.mock_calls=}")
        assert len(fig.plot_handles) == 1


# ---------------------------------------------------------------------------
# paint_drill_stop
# ---------------------------------------------------------------------------


@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
class TestPaintDrillStop:
    def test_adds_one_line_handle(self, mock_messagebar):
        fig = _make_figure()
        drillstops = [(2.0, -5.0), (8.0, -8.0)]

        paint_drill_stop(fig, drillstops, MINIMAL_TEMPLATE, drillstop_label="drillstop")

        print(f"{mock_messagebar.mock_calls=}")
        assert len(fig.plot_handles) == 1

    def test_label_used_in_legend(self, mock_messagebar):
        """The drillstop_label appears as the artist's label."""
        fig = _make_figure()
        drillstops = [(1.0, -3.0)]

        paint_drill_stop(
            fig, drillstops, MINIMAL_TEMPLATE, drillstop_label="bedrock hit"
        )

        print(f"{mock_messagebar.mock_calls=}")
        assert fig.plot_handles[0].get_label() == "bedrock hit"


# ---------------------------------------------------------------------------
# paint_layer_text
# ---------------------------------------------------------------------------


@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
class TestPaintLayerText:
    def test_annotates_non_none_texts(self, mock_messagebar):
        fig = _make_figure()
        layer_texts = {"geoshort": {(2.0, -1.0): "sand", (8.0, -1.5): "gravel"}}

        paint_layer_text(
            fig,
            layer_texts,
            "geoshort",
            text_alignment="center",
            barwidth=1.0,
            template=MINIMAL_TEMPLATE,
        )

        print(f"{mock_messagebar.mock_calls=}")
        texts = [t.get_text() for t in fig.ax_main.texts]
        assert "sand" in texts
        assert "gravel" in texts

    def test_none_text_skipped(self, mock_messagebar):
        """None text values produce no annotation."""
        fig = _make_figure()
        layer_texts = {"geoshort": {(2.0, -1.0): None, (8.0, -1.5): "clay"}}

        paint_layer_text(
            fig,
            layer_texts,
            "geoshort",
            text_alignment="center",
            barwidth=1.0,
            template=MINIMAL_TEMPLATE,
        )

        print(f"{mock_messagebar.mock_calls=}")
        texts = [t.get_text() for t in fig.ax_main.texts]
        assert len(texts) == 1
        assert "clay" in texts

    def test_edge_alignment_shifts_x(self, mock_messagebar):
        """Edge alignment produces a different x than center alignment."""
        fig_center = _make_figure()
        fig_edge = _make_figure()
        layer_texts = {"geoshort": {(2.0, -1.0): "sand"}}

        paint_layer_text(
            fig_center,
            layer_texts,
            "geoshort",
            text_alignment="center",
            barwidth=1.0,
            template=MINIMAL_TEMPLATE,
        )
        paint_layer_text(
            fig_edge,
            layer_texts,
            "geoshort",
            text_alignment="edge",
            barwidth=1.0,
            template=MINIMAL_TEMPLATE,
        )

        print(f"{mock_messagebar.mock_calls=}")
        x_center = fig_center.ax_main.texts[0].xy[0]
        x_edge = fig_edge.ax_main.texts[0].xy[0]
        assert x_edge != x_center


# ---------------------------------------------------------------------------
# paint_obsids
# ---------------------------------------------------------------------------


@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
class TestPaintObsids:
    def test_frame_bar_added_when_stratigraphy_enabled(self, mock_messagebar):
        fig = _make_figure()
        z_data = {"P1": {"z": 10.0, "barheight": 5.0, "bottom": -5.0}}
        obsids_x_position = {"P1": 2.0}

        paint_obsids(
            fig,
            z_data,
            obsids_x_position,
            MINIMAL_TEMPLATE,
            barwidth=1.0,
            plot_stratigraphy=True,
            plot_hydrology=False,
            plot_labels=False,
        )

        print(f"{mock_messagebar.mock_calls=}")
        assert len(fig.plot_handles) == 1

    def test_frame_bar_added_when_hydrology_enabled(self, mock_messagebar):
        fig = _make_figure()
        z_data = {"P1": {"z": 10.0, "barheight": 5.0, "bottom": -5.0}}
        obsids_x_position = {"P1": 2.0}

        paint_obsids(
            fig,
            z_data,
            obsids_x_position,
            MINIMAL_TEMPLATE,
            barwidth=1.0,
            plot_stratigraphy=False,
            plot_hydrology=True,
            plot_labels=False,
        )

        print(f"{mock_messagebar.mock_calls=}")
        assert len(fig.plot_handles) == 1

    def test_no_frame_bar_when_neither_enabled(self, mock_messagebar):
        fig = _make_figure()
        z_data = {"P1": {"z": 10.0, "barheight": 5.0, "bottom": -5.0}}
        obsids_x_position = {"P1": 2.0}

        paint_obsids(
            fig,
            z_data,
            obsids_x_position,
            MINIMAL_TEMPLATE,
            barwidth=1.0,
            plot_stratigraphy=False,
            plot_hydrology=False,
            plot_labels=False,
        )

        print(f"{mock_messagebar.mock_calls=}")
        assert len(fig.plot_handles) == 0

    def test_label_annotations_added_when_plot_labels_true(self, mock_messagebar):
        fig = _make_figure()
        fig.obsid_annotation = {"P1": (2.0, 10.5)}
        z_data = {"P1": {"z": 10.0, "barheight": 5.0, "bottom": -5.0}}
        obsids_x_position = {"P1": 2.0}

        paint_obsids(
            fig,
            z_data,
            obsids_x_position,
            MINIMAL_TEMPLATE,
            barwidth=1.0,
            plot_stratigraphy=False,
            plot_hydrology=False,
            plot_labels=True,
        )

        print(f"{mock_messagebar.mock_calls=}")
        texts = [t.get_text() for t in fig.ax_main.texts]
        assert "P1" in texts

    def test_zero_barheight_skipped(self, mock_messagebar):
        """An obsid with barheight=0 produces no frame bar."""
        fig = _make_figure()
        z_data = {"P1": {"z": 10.0, "barheight": 0, "bottom": 0}}
        obsids_x_position = {"P1": 2.0}

        paint_obsids(
            fig,
            z_data,
            obsids_x_position,
            MINIMAL_TEMPLATE,
            barwidth=1.0,
            plot_stratigraphy=True,
            plot_hydrology=False,
            plot_labels=False,
        )

        print(f"{mock_messagebar.mock_calls=}")
        assert len(fig.plot_handles) == 0
