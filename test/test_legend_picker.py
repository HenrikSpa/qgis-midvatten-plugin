import pytest
import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt
import matplotlib.lines

from midvatten.tools.utils.legend_picker import LegendPicker


class FakeMouseEvent:
    def __init__(self, key=None):
        self.key = key


class FakePickEvent:
    def __init__(self, artist, key=None):
        self.artist = artist
        self.mouseevent = FakeMouseEvent(key)


@pytest.fixture()
def picker_setup():
    fig, ax = plt.subplots()
    line_a = ax.plot([0, 1], [0, 1], label="A")[0]
    line_b = ax.plot([0, 1], [1, 0], label="B")[0]
    handles = [line_a, line_b]
    leg = ax.legend(handles, ["A", "B"])
    picker = LegendPicker(legend=leg, fig=fig, handles=handles)
    yield picker, fig, ax, line_a, line_b, leg
    plt.close(fig)


class TestLegendPickerSingleClick:
    def test_click_selects_line(self, picker_setup):
        picker, fig, ax, line_a, line_b, leg = picker_setup
        leg_lines = leg.get_lines()
        event = FakePickEvent(leg_lines[0])
        picker.on_pick(event)
        assert leg_lines[0] in picker.selected_legend_lines
        assert line_b.get_alpha() == 0.2

    def test_click_same_line_deselects(self, picker_setup):
        picker, fig, ax, line_a, line_b, leg = picker_setup
        leg_lines = leg.get_lines()
        event = FakePickEvent(leg_lines[0])
        picker.on_pick(event)
        picker.on_pick(event)
        assert len(picker.selected_legend_lines) == 0

    def test_click_different_line_switches(self, picker_setup):
        picker, fig, ax, line_a, line_b, leg = picker_setup
        leg_lines = leg.get_lines()
        picker.on_pick(FakePickEvent(leg_lines[0]))
        picker.on_pick(FakePickEvent(leg_lines[1]))
        assert picker.selected_legend_lines == {leg_lines[1]}
        assert line_a.get_alpha() == 0.2


class TestLegendPickerCtrlClick:
    def test_ctrl_click_adds(self, picker_setup):
        picker, fig, ax, line_a, line_b, leg = picker_setup
        leg_lines = leg.get_lines()
        picker.on_pick(FakePickEvent(leg_lines[0]))
        picker.on_pick(FakePickEvent(leg_lines[1], key="control"))
        assert picker.selected_legend_lines == {leg_lines[0], leg_lines[1]}

    def test_ctrl_click_removes(self, picker_setup):
        picker, fig, ax, line_a, line_b, leg = picker_setup
        leg_lines = leg.get_lines()
        picker.on_pick(FakePickEvent(leg_lines[0]))
        picker.on_pick(FakePickEvent(leg_lines[1], key="control"))
        picker.on_pick(FakePickEvent(leg_lines[0], key="control"))
        assert picker.selected_legend_lines == {leg_lines[1]}


class TestLegendPickerCallback:
    def test_callback_fires_with_selected_ax_lines(self, picker_setup):
        picker, fig, ax, line_a, line_b, leg = picker_setup
        received = []
        picker.register_pick_callback(lambda lines: received.append(lines))
        leg_lines = leg.get_lines()
        picker.on_pick(FakePickEvent(leg_lines[0]))
        assert len(received) == 1
        assert received[0] == [line_a]

    def test_callback_fires_empty_on_deselect(self, picker_setup):
        picker, fig, ax, line_a, line_b, leg = picker_setup
        received = []
        picker.register_pick_callback(lambda lines: received.append(lines))
        leg_lines = leg.get_lines()
        picker.on_pick(FakePickEvent(leg_lines[0]))
        picker.on_pick(FakePickEvent(leg_lines[0]))
        assert received[-1] == []


class TestLegendPickerAxisPick:
    def test_click_on_axis_line_selects(self, picker_setup):
        picker, fig, ax, line_a, line_b, leg = picker_setup
        event = FakePickEvent(line_a)
        picker.on_pick(event)
        assert len(picker.selected_legend_lines) == 1


class TestLegendPickerFilteredLegendLines:
    def test_non_pickable_handle_excluded(self):
        fig, ax = plt.subplots()
        meas_line = ax.plot([0, 1], [0, 1], label="measurements")[0]
        series_line = ax.plot([0, 1], [1, 0], label="series A")[0]
        series_line._line_key = ("A",)
        handles = [meas_line, series_line]
        leg = ax.legend(handles, ["measurements", "series A"])
        legend_lines = leg.get_lines()
        paired = [
            (ll, h)
            for ll, h in zip(legend_lines, handles)
            if isinstance(h, matplotlib.lines.Line2D) and hasattr(h, "_line_key")
        ]
        pick_legend, pick_handles = zip(*paired)
        picker = LegendPicker(
            legend=leg,
            fig=fig,
            handles=list(pick_handles),
            legend_lines=list(pick_legend),
        )
        assert meas_line not in picker.leg_lines_ax_lines.values()
        assert series_line in picker.leg_lines_ax_lines.values()
        assert len(picker.leg_lines_ax_lines) == 1
        plt.close(fig)
