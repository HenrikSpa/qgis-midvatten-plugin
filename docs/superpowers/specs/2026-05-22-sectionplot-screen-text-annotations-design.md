# Sectionplot Screen Text Annotations

**Date:** 2026-05-22
**Status:** Approved

## Goal

Add text annotation support to screen bars in the sectionplot tool, letting users choose which column from the `screen` table to display as text on screen intervals. Follows the same pattern as the existing geology bar text annotations.

## Screen Table Columns Available

| Column | Type | Purpose |
|--------|------|---------|
| `screenshort` | text | Short code (abbreviation) |
| `screen` | text | Full free-text description |
| `comment` | text | Additional notes |
| `diam_inner` | double | Inner diameter |
| `diam_outer` | double | Outer diameter |

All five columns are selectable in the combobox. Empty string means no text.

## Design

### Data Layer (`tools/sectionplot/data.py`)

New function `get_screen_text_data()`:

```python
def get_screen_text_data(
    obsids_x_position: dict,
    z_data: dict,
    text_column: str,
    dbconnection=None,
) -> dict:
```

- Queries `depthtop`, `depthbot`, and the selected column from `screen` for each obsid.
- Computes vertical center of each interval: `z = bottom + (height / 2)` where `bottom = ground_z - depthbot` and `height = depthbot - depthtop`.
- Returns `{text_column: {(x, z): text_value}}` — same structure as `get_plot_data_layer_texts()`.
- Filters out None, empty, and "null" text values.
- Uses `ident()` for safe column name quoting and DB-API parameter binding for the obsid value.

### Painter Layer (`tools/sectionplot/painters.py`)

No changes. Reuses `paint_layer_text()` which already accepts any `{(x, z): text}` dict, alignment, barwidth, and template.

For screen text, the caller passes `barwidth * width_factor` so "edge" alignment positions text at the edge of the screen bar (wider than geology bars).

### UI (`ui/secplotdockwidget.ui`)

New row (row 9) in the "Bars" group box `grid_layout_2`:

- **Label** (col 0): `"Screen text:"`
- **QComboBox** `screen_textcol_combo_box` (cols 1-3): populated programmatically with `["", "screenshort", "screen", "comment", "diam_inner", "diam_outer"]`.

### Settings

- `definitions/midvatten_defs.py`: Add `"secplotscreentext": ""` to settingsdict defaults.
- `tools/sectionplot/settings.py`: Add `"secplotscreentext": _b("secplotscreentext", "screen_textcol_combo_box", str)` to `GENERAL_BINDINGS`.
- `tools/sectionplot/ui_types.py`: Add `screen_textcol_combo_box: QtWidgets.QComboBox` attribute.

### Drawing Logic (`tools/sectionplot/_sectionplot.py`)

In `fill_combo_boxes()`: populate `screen_textcol_combo_box` with the column list and restore the saved setting.

In `draw_plot()`, after screen bars are painted (inside the `screensplotmode != "none"` guard):

1. If `secplotscreentext` is non-empty:
   - Fetch screen text data via `get_screen_text_data()`.
   - Call `paint_layer_text()` with `barwidth * width_factor`, the shared `secplotlayertextalignment` setting, and the template.

### Behavioral Notes

- Screen text only appears when screens are visible (`screensplotmode != "none"`).
- Alignment (Center/Edge) is shared with geology text, but each positions relative to its own bar width.
- Text overlap between geology and screen annotations is expected; users can adjust in SVG export.
- Text style reuses the template's `layer_Axes_annotate` settings (same font/size/color as geology text).
- Interactive picking works automatically via the `original_xy` attribute set by `paint_layer_text()`.

## Files Changed

| File | Change |
|------|--------|
| `definitions/midvatten_defs.py` | Add `"secplotscreentext": ""` default |
| `tools/sectionplot/settings.py` | Add binding for `secplotscreentext` |
| `tools/sectionplot/ui_types.py` | Add `screen_textcol_combo_box` attribute |
| `ui/secplotdockwidget.ui` | Add label + combobox at row 9 |
| `tools/sectionplot/data.py` | New `get_screen_text_data()` function |
| `tools/sectionplot/_sectionplot.py` | Populate combo, fetch data, call painter |
