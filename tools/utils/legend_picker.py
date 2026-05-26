import matplotlib as mpl
import matplotlib.lines


class LegendPicker:
    def __init__(
        self,
        legend: mpl.legend.Legend,
        fig: mpl.figure.Figure,
        handles: list,
        legend_lines: list | None = None,
        picked_alpha: float = 1.0,
        other_alpha: float = 0.2,
        pickradius: int = 4,
    ):
        self.legend = legend
        self.fig = fig
        self.picked_alpha = picked_alpha
        self.other_alpha = other_alpha
        self.leg_lines_ax_lines: dict = {}
        self.original_alphas: dict = {}
        self.selected_legend_lines: set = set()
        self._pick_callback = None

        ax_lines = [a for a in handles if isinstance(a, mpl.lines.Line2D)]
        leg_lines = legend_lines if legend_lines is not None else legend.get_lines()
        self.leg_lines_ax_lines = self._prepare_for_pick(
            leg_lines, ax_lines, pickradius
        )
        self.ax_to_legend = {v: k for k, v in self.leg_lines_ax_lines.items()}
        fig.canvas.mpl_connect("pick_event", self.on_pick)

    def _prepare_for_pick(
        self,
        legend_lines: list,
        ax_lines: list,
        pickradius: int,
    ) -> dict:
        mapping: dict = {}
        for legend_line, ax_line in zip(legend_lines, ax_lines):
            legend_line.set_picker(pickradius)
            ax_line.set_picker(pickradius)
            mapping[legend_line] = ax_line
            self.original_alphas[legend_line] = legend_line.get_alpha()
            self.original_alphas[ax_line] = ax_line.get_alpha()
        return mapping

    def register_pick_callback(self, callback):
        self._pick_callback = callback

    def on_pick(self, event):
        artist = event.artist
        if artist in self.ax_to_legend:
            legend_line = self.ax_to_legend[artist]
        elif artist in self.leg_lines_ax_lines:
            legend_line = artist
        else:
            return

        ctrl_held = getattr(event.mouseevent, "key", None) == "control"

        if ctrl_held:
            if legend_line in self.selected_legend_lines:
                self.selected_legend_lines.discard(legend_line)
            else:
                self.selected_legend_lines.add(legend_line)
            if not self.selected_legend_lines:
                self.revert_alpha()
            else:
                self._apply_alpha()
        else:
            if self.selected_legend_lines == {legend_line}:
                self.revert_alpha()
            else:
                self.selected_legend_lines = {legend_line}
                self._apply_alpha()

    def _apply_alpha(self):
        for legend_line, ax_line in self.leg_lines_ax_lines.items():
            alpha = (
                self.picked_alpha
                if legend_line in self.selected_legend_lines
                else self.other_alpha
            )
            legend_line.set_alpha(alpha)
            ax_line.set_alpha(alpha)
        self.fig.canvas.draw_idle()
        self._fire_callback()

    def _fire_callback(self):
        if self._pick_callback:
            ax_lines = [
                self.leg_lines_ax_lines[ll] for ll in self.selected_legend_lines
            ]
            self._pick_callback(ax_lines)

    def revert_alpha(self):
        for line, alpha in self.original_alphas.items():
            line.set_alpha(alpha)
        self.selected_legend_lines = set()
        self.fig.canvas.draw_idle()
        self._fire_callback()

    def get_selected_ax_lines(self) -> list:
        return [self.leg_lines_ax_lines[ll] for ll in self.selected_legend_lines]
