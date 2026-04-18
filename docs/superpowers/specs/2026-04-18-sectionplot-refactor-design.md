# SectionPlot Refactor — Design Spec

## Context

`tools/sectionplot/_sectionplot.py` is 2,952 lines with a single 57-method class
(`SectionPlot`) that handles UI init, settings load/save, data preparation, matplotlib
rendering, and window management all in one place.

Two concrete problems motivate this refactor:

1. **Settings brittleness.** Adding or changing any setting requires edits in 3–4 separate
   places: `midvatten_defs.py` (default), a `fill_*()` method (load into widget),
   `_load_ui_settings()` (read from widget), and `save_settings()` (persist to disk). Miss
   one step and you get a silent bug.

2. **The `plot_temp` bug.** Temperature settings are only loaded into GUI widgets inside
   `create_new_plot()`, which is only called when the user triggers a plot. When the dock
   panel opens in a new session, TEM widgets show defaults instead of the user's saved
   values. An early-return path in `fill_tem()` also silently skips restoring
   `secplot_tem_model_name` when no line feature is selected yet.

The goal: make the codebase navigable for targeted agent fixes, eliminate settings
brittleness, and fix the bug — while keeping the public API and test suite intact.
Path to Approach B (feature-class architecture) is left open by design.

---

## Chosen Approach: Structural Refactor (Approach A)

Split `_sectionplot.py` into focused modules by responsibility. The `SectionPlot` class
becomes a thin orchestrator. Three new modules are added to the existing package.

The package already has a good start:
- `figure.py` (57 lines) — `SectionPlotFigure` ✅ done
- `legend.py` (99 lines) — `SectionPlotLegendManager` ✅ done
- `painters.py` (356 lines) — 6 paint functions ✅ partial
- `_utils.py` (23 lines) — shared helpers ✅ done

---

## Module Layout

```
tools/sectionplot/
    _sectionplot.py      ~500 lines   orchestrator (was 2,952)
    painters.py          ~900 lines   all plot_* methods as standalone functions
    data.py              ~400 lines   all get_*/prepare_* methods as standalone functions
    settings.py          ~200 lines   declarative SettingsBinding + apply/collect/save
    ui_types.py           ~60 lines   AUTO-GENERATED typed widget stub mixin
    generate_ui_types.py  ~25 lines   generator script (dev utility, not imported)
    figure.py              57 lines   ✅ minor change only (add legend_manager attr)
    legend.py              99 lines   ✅ unchanged
    _utils.py              23 lines   ✅ unchanged
    __init__.py            46 lines   unchanged
```

`ui_types.py` is generated from `secplotdockwidget.ui` (XML) by `generate_ui_types.py`,
committed alongside the `.ui` file, and verified by a test.

---

## Section 1: Settings Binding (`settings.py`)

### Design

Replace the seven scattered methods (`fill_check_boxes`, `fill_combo_boxes`,
`fill_spinboxes`, `fill_tem`, `fill_images`, `_load_ui_settings`, `save_settings`) with a
declarative binding system and three functions.

**Key principle:** `midvatten_defs.py` remains the single source of truth for default
values. `settings.py` reads defaults from it at import time — if a key is missing from
`midvatten_defs`, the module crashes loudly at import rather than silently using a wrong
default at runtime.

```python
# settings.py
from dataclasses import dataclass
from typing import Any
from midvatten.definitions.midvatten_defs import settingsdict as _defs

_defaults = _defs()   # computed once at import time

@dataclass(frozen=True)
class Bind:
    widget: str    # attribute name on Ui_SecPlotDock / SecPlotUi
    type_: type    # str | bool | int | float
    default: Any   # sourced from midvatten_defs — never hand-typed

def _b(key: str, widget: str, type_: type) -> Bind:
    """Create a Bind, pulling the default from midvatten_defs. KeyError = missing default."""
    return Bind(widget=widget, type_=type_, default=_defaults[key])
```

Bindings declared once per feature group:

```python
GENERAL_BINDINGS: dict[str, Bind] = {
    "stratigraphyplotted":     _b("stratigraphyplotted",     "plot_stratigraphy",       bool),
    "secplothydrologyplotted": _b("secplothydrologyplotted", "hydrology_radio_button",  bool),
    "secplotlabelsplotted":    _b("secplotlabelsplotted",    "labels_check_box",        bool),
    "secplotlegendplotted":    _b("secplotlegendplotted",    "create_legend",           bool),
    "secplotwlvltab":          _b("secplotwlvltab",          "wlvltable",               str),
    "secplottext":             _b("secplottext",             "textcol_combo_box",       str),
    "secplotbw":               _b("secplotbw",               "barwidthdouble_spin_box", float),
    # ... all remaining general settings
}

TEM_BINDINGS: dict[str, Bind] = {
    "secplot_tem_colormap":        _b("secplot_tem_colormap",        "tem_colormap",        str),
    "secplot_tem_norm":            _b("secplot_tem_norm",            "tem_norm",            str),
    "secplot_tem_shading":         _b("secplot_tem_shading",         "tem_shading",         str),
    "secplot_tem_model_name":      _b("secplot_tem_model_name",      "tem_model_name",      str),
    "secplot_tem_vmin":            _b("secplot_tem_vmin",            "tem_vmin",            str),
    "secplot_tem_vmax":            _b("secplot_tem_vmax",            "tem_vmax",            str),
    "secplot_tem_snap":            _b("secplot_tem_snap",            "tem_snap",            bool),
    "secplot_tem_data_fit":        _b("secplot_tem_data_fit",        "tem_data_fit",        bool),
    "secplot_tem_rasterized":      _b("secplot_tem_rasterized",      "tem_rasterized",      bool),
    "secplot_tem_edgecolors":      _b("secplot_tem_edgecolors",      "tem_edgecolors",      str),
    "secplot_tem_alpha_above_doi": _b("secplot_tem_alpha_above_doi", "tem_alpha_above_doi", float),
    "secplot_tem_alpha_below_doi": _b("secplot_tem_alpha_below_doi", "tem_alpha_below_doi", float),
}

IMAGES_BINDINGS: dict[str, Bind] = { ... }   # same pattern
DEM_BINDINGS:    dict[str, Bind] = { ... }   # same pattern

ALL_BINDINGS = {**GENERAL_BINDINGS, **TEM_BINDINGS, **IMAGES_BINDINGS, **DEM_BINDINGS}
```

Three functions cover the complete round-trip:

```python
def apply_settings_to_ui(ui, ms, bindings=ALL_BINDINGS) -> None:
    """Settings → widgets. Call at dock-open time (init_ui)."""
    for key, b in bindings.items():
        set_widget(getattr(ui, b.widget), ms.settingsdict.get(key, b.default), b.type_)

def collect_ui_to_settings(ui, ms, bindings=ALL_BINDINGS) -> None:
    """Widgets → settings. Call at start of draw_plot."""
    for key, b in bindings.items():
        ms.settingsdict[key] = get_widget_value(getattr(ui, b.widget), b.type_)

def save_settings(ms, bindings=ALL_BINDINGS) -> None:
    """Persist all bound keys to QgsProject."""
    for key in bindings:
        ms.save_settings(key)
```

`set_widget` / `get_widget_value` dispatch on widget class, wrapping helpers already in
`gui_utils.py`: `set_combobox`, `setText`/`text()`, `setChecked`/`isChecked()`,
`setValue`/`value()`.

### How the plot_temp bug is fixed

`apply_settings_to_ui(self, self.ms)` is called from `init_ui()` (dock open), not only
from `create_new_plot()`. All 12 TEM settings — including `secplot_tem_model_name` — are
applied immediately from `ms.settingsdict` when the panel opens. The early-return path in
the old `fill_tem()` that silently skipped the model name no longer exists.

Dynamic combobox *choices* (model names queried from DB, DEM raster list) are populated
separately by `_populate_dynamic_widgets()` when a line feature is available. The *selected
value* is always restored by the binding on dock open.

### Adding a new setting (after refactor)

1. Add default to `midvatten_defs.settingsdict()` — one line.
2. Add `_b(key, widget, type_)` to the appropriate binding group in `settings.py` — one line.

Done. No other methods to touch.

---

## Section 2: Data Prep Module (`data.py`)

All `get_*` / `prepare_*` methods extracted as **standalone functions**: no `self`, no
figure, no widget reads. Explicit arguments in, plain data structures out.

### Functions extracted from `_sectionplot.py`

| Current method | New signature |
|---|---|
| `prepare_line_and_obsid_positions()` | `prepare_obsid_positions(line_feature, obspoints, conn) -> dict` |
| `get_length_along()` | `get_length_along(obsidtuple, line_feature, ...) -> Series` |
| `get_z_data()` | `get_z_data(obsids_x_position, conn) -> dict` |
| `get_plot_data_bars()` | `get_plot_data_bars(obsids_x_position, z_data, conn, ...) -> dict` |
| `get_screen_plot_data()` | `get_screen_plot_data(obsids_x_position, conn) -> dict` |
| `get_plot_data_layer_texts()` | `get_plot_data_layer_texts(obsids_x_position, z_data, ...) -> list` |
| `get_drillstops()` | `get_drillstops(obsids_x_position, z_data) -> dict` |
| `get_plot_data_seismic()` | `get_plot_data_seismic(line_layer, line_feature, conn) -> list` |
| `get_water_levels_from_df()` | `get_water_levels_from_df(df, idx, obsids_x_position, fig)` |
| `get_length_map()` (module-level) | moved as-is |
| `fill_empty_columns()` (module-level) | moved as-is |
| `get_slider_idx()` (module-level) | moved as-is |

**Stays in orchestrator:** `get_dem_selection()` — reads the `dem_list` widget selection.

---

## Section 3: Painters Module (extending `painters.py`)

Six functions already extracted. Remaining `plot_*` methods become standalone functions
following the established convention: `paint_*(figure, data, settingsdict) -> None`.

**Contract:** painters receive `figure` (a `SectionPlotFigure`) and append artists to
`figure.plot_handles` for legend management. They draw onto `figure.ax_main` and may set
state on `figure` (e.g. `figure.tem_cbar_label`). They never write to `ms.settingsdict`.
`SectionPlotFigure` already carries all persistent artist state — this is the existing
pattern.

Conditional feature guards (`if settingsdict["stratigraphyplotted"]`) move inside each
painter, keeping `draw_plot()` in the orchestrator unconditional and readable.

### Functions extracted from `_sectionplot.py`

| Current method | New function | Notes |
|---|---|---|
| `plot_dems()` | `paint_dems(figure, dem_data, settingsdict)` | |
| `plot_graded_dems()` | `paint_graded_dems(figure, dem_data, settingsdict)` | |
| `plot_tem()` | `paint_tem(figure, tem_data, settingsdict)` | 228 lines, body unchanged |
| `plot_images()` | `paint_images(figure, image_data, settingsdict)` | |
| `plot_specific_water_level()` | `paint_specific_water_level(figure, wl_data, settingsdict)` | |
| `plot_water_level_interactive()` | `paint_water_level_interactive(figure, wl_data, settingsdict)` | drawing only |
| `plot_water_level()` | `paint_water_level(figure, wl_data, settingsdict)` | thin dispatcher |
| `finish_plot()` | `finish_plot(figure, settingsdict)` | |
| `_configure_axes()` | `configure_axes(figure, settingsdict)` | |

**Special case — interactive water level:** Qt slider signal wiring references `self` (the
dock widget) and stays in the orchestrator as `_setup_interactive_slider()`. Only the
matplotlib drawing portion moves to `painters.py`.

**`figure.legend_manager`:** `SectionPlotLegendManager` currently stored as
`self.secplot_legend_manager` moves to `figure.legend_manager` so it is accessible after
figure detach. Add attribute declaration to `figure.py`.

---

## Section 4: Type Stubs (`ui_types.py`) — auto-generated

`secplotdockwidget.ui` is XML. `generate_ui_types.py` parses it to produce `ui_types.py`:

```python
# generate_ui_types.py
import xml.etree.ElementTree as ET
import pathlib

def generate(ui_path: str) -> str:
    tree = ET.parse(ui_path)
    lines = [
        "# AUTO-GENERATED from secplotdockwidget.ui — do not edit manually.",
        "# Regenerate: python tools/sectionplot/generate_ui_types.py",
        "from qgis.PyQt import QtWidgets, QtCore",
        "",
        "class SecPlotUi:",
    ]
    seen: set[str] = set()
    for elem in tree.iter("widget"):
        name, cls = elem.get("name"), elem.get("class")
        if name and cls and name not in seen and name != "SecPlotDock":
            lines.append(f"    {name}: QtWidgets.{cls}")
            seen.add(name)
    return "\n".join(lines) + "\n"

if __name__ == "__main__":
    here = pathlib.Path(__file__).parent
    ui_file = here.parent.parent / "ui" / "secplotdockwidget.ui"  # adjust path
    (here / "ui_types.py").write_text(generate(str(ui_file)))
```

The generated file is committed. A test verifies it stays in sync:

```python
def test_ui_types_up_to_date():
    from midvatten.tools.sectionplot.generate_ui_types import generate
    current = (Path(...) / "ui_types.py").read_text()
    assert current == generate("path/to/secplotdockwidget.ui"), (
        "ui_types.py is stale — run generate_ui_types.py"
    )
```

`SectionPlot` inherits the mixin:

```python
class SectionPlot(QDockWidget, SecPlotUi, Ui_SecPlotDock):
    ...
```

`Bind("tem_colormap", ...)` strings in `settings.py` now correspond to visible, typed
attributes rather than magic strings into an opaque generated class.

---

## Section 5: Orchestrator Slimdown (`_sectionplot.py`, target ~500 lines)

**What stays:**
- `__init__` / `init_ui` — dock setup; calls `apply_settings_to_ui(self, self.ms)` on open
- `_populate_dynamic_widgets()` — DB-sourced combobox/list choices (model names, DEM list)
- `show()` — layer validation guard
- `create_new_plot()` — entry point: populate dynamic widgets → `draw_plot()`
- `draw_plot()` — clean data-then-paint pipeline
- `_setup_interactive_slider()` — Qt signal wiring for date slider
- `detach_figure`, `dock_settings`, `float_settings` — window management
- `update_legend`, `add_titlebar` — thin delegation to `figure.legend_manager`

**`draw_plot()` after refactor:**

```python
def draw_plot(self):
    collect_ui_to_settings(self, self.ms)

    conn = ...
    positions = prepare_obsid_positions(self.figure.line_feature, ..., conn)
    z_data    = get_z_data(positions, conn)
    bars      = get_plot_data_bars(positions, z_data, conn, self.ms.settingsdict)
    screens   = get_screen_plot_data(positions, conn)
    texts     = get_plot_data_layer_texts(positions, z_data, ...)
    seismic   = get_plot_data_seismic(...)

    configure_axes(self.figure, self.ms.settingsdict)
    paint_dems(self.figure, ...)
    paint_bars(self.figure, bars, ...)
    paint_tem(self.figure, ...)
    paint_images(self.figure, ...)
    paint_water_level(self.figure, ...)
    finish_plot(self.figure, self.ms.settingsdict)

    save_settings(self.ms)
```

---

## Critical Files

| File | Action |
|---|---|
| `tools/sectionplot/_sectionplot.py` | Refactor — shrinks to ~500-line orchestrator |
| `tools/sectionplot/settings.py` | **New** — declarative binding system |
| `tools/sectionplot/data.py` | **New** — standalone data prep functions |
| `tools/sectionplot/painters.py` | Extend — add remaining paint functions |
| `tools/sectionplot/ui_types.py` | **New (generated)** — typed widget mixin |
| `tools/sectionplot/generate_ui_types.py` | **New** — generator script |
| `tools/sectionplot/figure.py` | Minor — add `legend_manager: SectionPlotLegendManager` attr |
| `definitions/midvatten_defs.py` | Read-only — source of setting defaults, no changes |
| `test/test_sectionplot.py` | Update imports; add settings-binding unit tests |

---

## Implementation Order

1. **`generate_ui_types.py` + `ui_types.py`** — write generator, run it, commit output,
   add sync test.
2. **`settings.py`** — `Bind`, `_b()`, all binding dicts, three round-trip functions. Call
   `apply_settings_to_ui` from `init_ui` to fix the plot_temp bug.
3. **`data.py`** — move `get_*` / `prepare_*` as-is; update imports in orchestrator.
4. **`painters.py`** — move remaining `plot_*` methods as standalone functions; move
   `legend_manager` to `figure`.
5. **Slim `_sectionplot.py`** — remove extracted methods, wire everything together.
6. **Ruff + full test suite.**

---

## Verification

```bash
# Run after each step:
python3 -m pytest test/test_sectionplot.py -x
python3 -m pytest test/test_sectionplot_templates.py -x
python3 -m pytest test/test_sectionplot_spatialite.py -x
python3 -m pytest test/test_sectionplot_screens.py -x

# After step 2 — manually verify bug fix:
# Open SectionPlot dock in QGIS with a saved project.
# TEM widgets should show saved values before clicking Plot.

# Full suite at end:
python3 -m pytest test/ -x -m spatialite
ruff check .
```

---

## Path to Approach B (feature-class architecture)

After this refactor, migrating to feature classes is mechanical — no abstractions change:
- Group per-feature functions from `data.py` + `painters.py` into `features/tem.py` etc.
- Move per-feature binding groups from `settings.py` into each feature class as `SETTINGS`.
- Same `Bind` dataclass, same function signatures — just regrouped by feature.
