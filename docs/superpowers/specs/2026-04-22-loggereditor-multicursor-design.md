# Logger Editor — Multicursor Button

## Goal

Add a toggleable crosshair/multicursor button to the logger editor's matplotlib toolbar, spanning both subplots (main axes and reference axes) when both are visible.

## Reference

Pattern copied from `dynplot/utils/matplotlib_crosshair_addon.py`, which wraps `matplotlib.widgets.MultiCursor` in the `NavigationButton` base class.

## Changes

### 1. New class `MultiCursorButton` in `tools/loggereditor.py`

Add at the bottom of the file, alongside `SelectNodesButton` and `MoveNodesButton`:

```python
class MultiCursorButton(NavigationButton):
    def __init__(self, parent, fig):
        super().__init__(parent, fig)
        self._button_setup = [
            (
                "show crosshair",
                self.clicked,
                "Show crosshair",
                os.path.join(os.path.dirname(__file__), "..", "icons", "crosshair.png"),
            )
        ]
        self.connect_toolbar()
        self.mc = MultiCursor(
            fig.canvas, fig.axes, horizOn=True, vertOn=True, color="k", lw=0.8, ls="--"
        )
        self.mc.visible = False

    def button(self):
        return list(self.actions.values())[0]

    def clicked(self):
        self.mc.visible = self.button().isChecked()
        if not self.mc.visible:
            self.fig.canvas.draw_idle()
```

`fig.axes` at construction time is `[self.axes, self.ref_axes]`. When `ref_axes` is hidden, matplotlib draws nothing on it — no special handling needed.

### 2. Wire up in `LoggerEditor.show()`

After the existing button instantiations:

```python
self.select_nodes_button = SelectNodesButton(self, self.calibrplotfigure)
self.move_nodes_button = MoveNodesButton(self, self.calibrplotfigure)
self.multi_cursor_button = MultiCursorButton(self, self.calibrplotfigure)
```

### 3. Add import

```python
from matplotlib.widgets import RectangleSelector, MultiCursor
```

### 4. Copy icon

Copy `crosshair.png` from `dynplot/dynplot/icons/crosshair.png` to `midvatten/icons/crosshair.png`.

## Behaviour

- Button is checkable; off by default.
- When checked: `MultiCursor` becomes visible, drawing a full `+` crosshair that tracks mouse position across all visible subplots.
- When unchecked: crosshair hidden, `canvas.draw_idle()` clears residual lines.
- Independent of select-nodes and move-nodes buttons — all three can be toggled independently.
