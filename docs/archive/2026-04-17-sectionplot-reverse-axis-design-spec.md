> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-04-17 · modified: 2026-04-17 · archived: 2026-07-31

# Section Plot Reverse Axis — Design Spec

**Date:** 2026-04-17
**Status:** Ready for implementation

---

## Context

The section plot displays geological data (stratigraphy, water levels, TEM, images, DEMs, etc.) along a horizontal x-axis representing cumulative distance along a selected section line. The direction of the line is determined by the geometry of the selected QGIS line feature — whichever end was digitised first is x=0.

Users frequently need to view the same plot in the opposite direction (e.g. to match a map orientation, or to align with a neighbouring section). Today there is no way to do this. The feature adds a toggle button to the matplotlib NavigationToolbar that reverses the x-axis in-place, without re-querying the database or recalculating any coordinates.

---

## Approach

Call `ax_main.invert_xaxis()` on the existing matplotlib axes object. This flips the rendered x-direction for every layer simultaneously — bars, water levels, DEMs, TEM pcolormesh, profile images, and drill stops — because they all use data coordinates that matplotlib renders relative to the axis. No data recalculation is needed.

The twin x-axis (`ax_data_fit`, created via `ax_main.twinx()` for TEM data-fit line) shares the x-axis with `ax_main` and flips automatically.

---

## Implementation

### 1. Icon — `icons/reverse_section.png`

Generate a 24×24 PNG programmatically (run once, commit result):

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(0.25, 0.25), dpi=96)
ax.annotate("", xy=(0.9, 0.65), xytext=(0.1, 0.65),
            arrowprops=dict(arrowstyle="->", color="black", lw=1.5))
ax.annotate("", xy=(0.1, 0.35), xytext=(0.9, 0.35),
            arrowprops=dict(arrowstyle="->", color="black", lw=1.5))
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.axis("off")
fig.savefig("icons/reverse_section.png", dpi=96, transparent=True,
            bbox_inches="tight", pad_inches=0)
plt.close(fig)
```

Visual result: top arrow → right, bottom arrow ← left (stacked, opposing directions).

### 2. New class — `tools/utils/gui_utils.py`

Add after `DetachFigureButton` (currently ends around line 415):

```python
class ReverseSectionButton(NavigationButton):
    def __init__(self, fig, parent=None):
        super().__init__(parent, fig)
        self._button_setup = [
            (
                "reverse section",
                self._toggle_reverse,
                QCoreApplication.translate("SectionPlot", "Reverse x-axis"),
                os.path.join(
                    os.path.dirname(__file__), "..", "..", "icons", "reverse_section.png"
                ),
            )
        ]
        self.connect_toolbar()

    def _toggle_reverse(self):
        self.fig.ax_main.invert_xaxis()
        self.fig.canvas.draw_idle()
```

### 3. Wire up — `tools/sectionplot/_sectionplot.py`

In `init_figure()`, after line 1368 (the `DetachFigureButton` line):

```python
self.figure.reverse_section_button = ReverseSectionButton(self.figure)
```

Stored on `self.figure` to match the `detach_figure_button` pattern and prevent garbage collection.

### 4. Import

Add `ReverseSectionButton` to the import of `gui_utils` in `_sectionplot.py`. The existing import line already imports `DetachFigureButton` from `gui_utils` — add `ReverseSectionButton` alongside it.

---

## Behaviour Notes

- **State resets on redraw**: each `draw_plot()` call creates a fresh figure via `init_figure()`. The button starts unchecked (normal direction) every time. The user toggles reverse after generating the plot — this is the natural workflow.
- **Attached and detached figures**: the button lives on the matplotlib `NavigationToolbar`, which is part of the figure widget. It travels with the figure when detached via `DetachFigureButton`. No special handling needed.
- **Checkable**: the button is checkable (via `add_action_to_navigation_toolbar`), so it stays visually pressed when active, giving clear feedback about the current axis direction.

---

## Files Changed

| File | Change |
|------|--------|
| `icons/reverse_section.png` | New file — generated icon |
| `tools/utils/gui_utils.py` | New `ReverseSectionButton` class |
| `tools/sectionplot/_sectionplot.py` | Import + one instantiation line in `init_figure()` |

---

## Verification

1. Generate a section plot with a known line. Note which obsid appears leftmost.
2. Click the reverse button. The leftmost obsid should now be rightmost, and all layers (bars, water levels, TEM resistivity, DEM profile) should flip together.
3. Click reverse again — plot returns to original direction.
4. Detach the figure. Click reverse on the detached figure's toolbar — same behaviour.
5. Draw a new plot. Button resets to unchecked (normal direction).
6. Run `python3 -m pytest test/ -m spatialite -x` — no regressions.
