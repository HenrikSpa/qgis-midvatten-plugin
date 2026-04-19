# Research: Matplotlib Transforms vs. Piper Plot Manual Math

## Context

The piper diagram (`tools/piper.py`) draws all geometry — data points, grid lines, tick labels, axes labels, inner zone labels, crossing lines — by manually computing `(x, y)` pixel-equivalent coordinates using trigonometry. The question is whether matplotlib's transform system would make this substantially simpler.

---

## What Matplotlib Transforms Are

Matplotlib uses a layered transform pipeline:

```
data coords → transData → axes coords → transAxes → figure coords → display (pixels)
```

Every artist you place on axes goes through `ax.transData`. You can *replace* or *compose* transforms to intercept this pipeline.

### Key primitives

| Class | What it does |
|-------|-------------|
| `Affine2D` | Linear map: scale, rotate, translate, **shear** — all composable with `+` |
| `Transform` ABC | Subclass to define arbitrary non-linear mappings |
| `CompositeGenericTransform` | Chain two transforms together |
| `BboxTransform` | Map one bounding box to another |
| `blended_transform_factory(tx, ty)` | Mix x-transform from one source, y from another |

Key insight: any **affine** map (linear + translate, including shear) can be expressed as a single `Affine2D` object and composed into `ax.transData` by doing:

```python
ax.set_transform(my_affine + ax.transData)
```

Or you can pass `transform=` to any artist (`ax.text(…, transform=my_transform)`).

### Custom projection axes

Matplotlib's `mpl_toolkits.axisartist` and `projections.register_projection()` let you register a whole new axes class with a custom `transData`. QGIS's embedded matplotlib is modern enough to support this. The `skewed_axes` example in the official matplotlib docs is exactly this pattern — it uses `Affine2D().skew_deg(rot, 0) + ax.transData` to shear an axes.

---

## What the Piper Plot Does Today

### Three coordinate systems in one axes

All drawing happens on a single `ax` with `xlim/ylim` set to `[0, 100]`. The three sub-regions are:

| Region | Class | Input data | Geometry |
|--------|-------|-----------|----------|
| Cation triangle (left) | `TriangleGraph` | `(x%, y%)` | Equilateral triangle, base at bottom |
| Anion triangle (right) | `TriangleGraph` | `(x%, y%)` | Mirror image |
| Rhomboid diamond (center-top) | `RhomboidGraph` | `(cation%, anion%)` | Diamond formed by combining both |

### The transforms done by hand

**TriangleGraph._transform** (lines ~1055–1069):
```python
transformed_y = ymin + equilateral_height(side_length * (y / 100))
transformed_x = xmin + side_length * ((x + y/2) / 100)   # ← shear term y/2
```
This is a **pure affine (shear + scale + translate)**. It is exactly an `Affine2D` matrix.

**RhomboidGraph._transform** (lines ~1084–1112):
```python
transformed_y = ymin + equilateral_height(side_length) + equilateral_height(side_length*y/100) - equilateral_height(side_length*x/100)
transformed_x = xmin + side_length*(x/200 + y/200)
```
Also affine — shear in the opposite direction applied to two independent inputs (x from cation side, y from anion side).

### Everything else is manually placed

- **Tick labels**: `ax.text()` at manually computed `(x, y)` positions, with rotation angles calculated via `math.atan()` from the axes aspect ratio at draw time.
- **Grid lines**: `ax.plot()` with a list of pre-computed line endpoints.
- **Axes edges**: same.
- **Inner zone labels** ("Ca type", "Na type", etc.): `ax.text()` at fixed data coordinates.
- **Crossing lines** (interactive): `Line2D` objects with slopes computed from `math.tan(30°)`.

### The aspect-ratio problem

The most painful hack is in `get_rotation()` (line ~1120). Because tick labels need to be perpendicular to triangle sides, and the display angle of a side depends on the figure's physical aspect ratio, the code recomputes text rotation every time the figure is resized. If the transform were baked into the axes, matplotlib would handle text rotation automatically via its own `dpi_cor` mechanism.

---

## Would Transforms Simplify This?

### What they **would** eliminate

1. **`TriangleGraph._transform` and `RhomboidGraph._transform`** — both are affine and map directly to `Affine2D`. Data points would just be plotted in ternary `%` coordinates and the transform does the skew automatically.

2. **Grid lines** — once the transform is set, a grid line at `x=20` in data space automatically appears at the right screen angle. No endpoint math.

3. **Axes edges** — same; the boundary is always `[0,100]×[0,100]` in data space.

4. **Manual rotation of tick labels** — `mpl_toolkits.axisartist` has `AxisArtist` objects that track the physical angle of an axis and rotate tick labels perpendicular to it automatically.

5. **`get_rotation()` / `get_aspect()` hacks** — gone entirely.

### What they **would NOT** simplify

1. **Three coordinate systems in one axes.** This is the fundamental structural problem. Matplotlib's transform applies uniformly to all artists on an axes. The cation triangle, anion triangle, and rhomboid live in *different* data spaces (left vs. right triangle; combined diamond). You cannot express all three with a single transform.

   The clean solution would be **three separate axes** (one per region), each with its own `Affine2D` transform, overlaid with `fig.add_axes([left, bottom, width, height])`. This is architecturally sound but requires redesigning how data is dispatched and how the legend is shared.

2. **Interactive crossing lines.** These span all three regions and compute their slope from the data values in the rhomboid. They would still need explicit geometry, though the math would be simpler if each axes had its own transform.

3. **Inner zone labels.** These are placed at "meaningful" interior data coordinates that still require knowing the diagram geometry. Transforms help positioning but not the *choice* of coordinates.

### Net verdict

**Yes, transforms would simplify this enormously — but the simplification requires splitting into three axes.**

The current design puts everything on one axes and manually converts every coordinate. With three axes + custom `Affine2D` transforms:

- The ternary shear math disappears from application code
- Tick/label rotation is automatic
- Grid lines are trivial
- Data plotting is just `ax.plot(x_pct, y_pct)` in each axes

The crossing-line code would shrink significantly but not disappear — it still needs to compute where a line from the cation triangle intersects the anion triangle and rhomboid in screen space.

---

## Rough Implementation Sketch

```python
# Build the affine transform for the left (cation) triangle
H = math.sin(math.radians(60))  # ≈ 0.866

# Shear matrix for equilateral ternary: x' = x + y/2, y' = y*H
cation_tf = (
    Affine2D()
    .scale(1, H)                       # y-axis: compress to triangle height
    .skew_deg(-30, 0)                  # apply 30-degree shear on x
    + ax_cation.transData
)

# Register on axes so all artists see it by default
ax_cation.set_aspect('equal')
for artist in ax_cation.get_children():
    artist.set_transform(cation_tf)
```

Or more cleanly, register a custom projection:

```python
from matplotlib.projections import register_projection
from matplotlib.axes import Axes
from matplotlib.transforms import Affine2D

class TernaryAxes(Axes):
    name = 'ternary'

    def _set_lim_and_transforms(self):
        super()._set_lim_and_transforms()
        H = math.sin(math.radians(60))
        ternary_shear = Affine2D().scale(1, H).skew_deg(-30, 0)
        self.transData = ternary_shear + self.transData

register_projection(TernaryAxes)
```

Note: there are also well-maintained third-party libraries (`mpltern`, `python-ternary`) that already implement ternary axes as matplotlib projections — worth comparing before writing from scratch.

---

## Critical Files

- `tools/piper.py` — entire implementation; `TriangleGraph` (~1045), `RhomboidGraph` (~1072), `equilateral_height` (~1115), `get_rotation` (~1120), `get_aspect` (~1127)
- `tools/customplot.py` — reference for how other plots use matplotlib here (no custom transforms currently)

---

## Recommendation

This is a **significant refactor**, not a quick win. The payoff is high (removes ~200 lines of manual math, fixes the aspect-ratio rotation bug permanently), but the structural change (one axes → three axes) touches the data-dispatch path, the crossing-line logic, and the legend.

A good incremental path:
1. Prototype one ternary triangle as a custom `Affine2D` transform on a fresh axes — verify the math matches the current output visually.
2. Replace the three plotting regions with three overlaid axes.
3. Remove `TriangleGraph`, `RhomboidGraph`, and the rotation hacks.
4. Port the crossing-line code to work with `ax.transData` screen-space math instead of manual trigonometry.
