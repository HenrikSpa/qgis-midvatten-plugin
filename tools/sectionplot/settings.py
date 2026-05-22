"""
Declarative settings-binding system for the SectionPlot dock.

Each :class:`Bind` entry maps one settings key to a single Qt widget attribute
on the UI object and describes the Python type that should be stored.

``apply_settings_to_ui``, ``collect_ui_to_settings``, and ``save_settings``
are the three round-trip functions callers should use.  All other symbols
(``_b``, ``_set_widget``, ``_get_widget_value``) are implementation details.

Keys deliberately **omitted** from the declarative bindings (require custom
handling in the orchestrator):
  - ``secplotdates``              — list stored via QTextEdit multiline text
  - ``secplotlocation``           — dock location integer, no widget
  - ``secplot_loaded_template``   — template system, complex serialisation
  - ``secplot_templates``         — template system
  - ``secplotselectedDEMs``       — QListWidget multi-selection
  - ``secplothydrologyplotted``   — 3-way radio button group (not saved in save_settings either)
  - ``secplotwidthofplot``        — radio button pair (width_of_plot / width_of_profile)
  - ``secplotlayertextalignment`` — radio button pair encoded as "center"/"edge"
  - ``screensplotmode``           — combo with display-mapped values (_SCREEN_MODE_TO_DISPLAY)
  - ``secplot_images_images``     — QListWidget multi-selection, JSON-serialised
  - ``secplot_tem_model_name``    — combo populated dynamically from DB
  - ``stratigraphyplotted``       — radio button (plot_stratigraphy), not a simple checkbox
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QLineEdit,
    QSpinBox,
)

from midvatten.definitions.midvatten_defs import settingsdict as _defs
from midvatten.tools.utils.gui_utils import set_combobox

_defaults = _defs()


@dataclass(frozen=True)
class Bind:
    """Declarative binding between a settings key and a Qt widget attribute."""

    widget: str  # attribute name on the Qt UI object
    type_: type  # str | bool | int | float
    default: Any  # sourced from midvatten_defs at import time


def _b(key: str, widget: str, type_: type) -> Bind:
    """Build a Bind, failing loudly if ``key`` is missing from settingsdict."""
    return Bind(widget=widget, type_=type_, default=_defaults[key])


# ---------------------------------------------------------------------------
# Binding groups
# ---------------------------------------------------------------------------

# General settings — checkboxes, spinboxes, combos not specific to TEM/images/DEM
GENERAL_BINDINGS: dict[str, Bind] = {
    "secplotwlvltab": _b("secplotwlvltab", "wlvltable", str),
    "secplottext": _b("secplottext", "textcol_combo_box", str),
    # default is int 2 in defs; QDoubleSpinBox.value() always returns float
    "secplotbw": _b("secplotbw", "barwidthdouble_spin_box", float),
    "secplotdrillstop": _b("secplotdrillstop", "drillstop", str),
    "secplotincludeviews": _b("secplotincludeviews", "include_views_check_box", bool),
    "secplotlabelsplotted": _b("secplotlabelsplotted", "labels_check_box", bool),
    "secplotlegendplotted": _b("secplotlegendplotted", "create_legend", bool),
    "screenwidthfactor": _b("screenwidthfactor", "screen_width_factor_spin", float),
    "secplotscreentext": _b("secplotscreentext", "screen_textcol_combo_box", str),
}

# DEM-specific settings
DEM_BINDINGS: dict[str, Bind] = {
    "secplotdem_sampling_distance": _b(
        "secplotdem_sampling_distance", "dem_sampling_distance", float
    ),
    "secplot_apply_graded_dems": _b(
        "secplot_apply_graded_dems", "secplot_apply_graded_dems", bool
    ),
    "secplot_grading_depth": _b(
        "secplot_grading_depth", "secplot_grading_depth", float
    ),
    "secplot_grading_num_layers": _b(
        "secplot_grading_num_layers", "secplot_grading_num_layers", int
    ),
    "secplot_grading_max_opacity": _b(
        "secplot_grading_max_opacity", "secplot_grading_max_opacity", float
    ),
    "secplot_grading_min_opacity": _b(
        "secplot_grading_min_opacity", "secplot_grading_min_opacity", float
    ),
}

# TEM (transient electromagnetic) settings
TEM_BINDINGS: dict[str, Bind] = {
    "secplot_tem_colormap": _b("secplot_tem_colormap", "tem_colormap", str),
    "secplot_tem_data_fit": _b("secplot_tem_data_fit", "tem_data_fit", bool),
    "secplot_tem_norm": _b("secplot_tem_norm", "tem_norm", str),
    "secplot_tem_shading": _b("secplot_tem_shading", "tem_shading", str),
    "secplot_tem_vmin": _b("secplot_tem_vmin", "tem_vmin", str),
    "secplot_tem_vmax": _b("secplot_tem_vmax", "tem_vmax", str),
    "secplot_tem_snap": _b("secplot_tem_snap", "tem_snap", bool),
    "secplot_tem_edgecolors": _b("secplot_tem_edgecolors", "tem_edgecolors", str),
    "secplot_tem_alpha_above_doi": _b(
        "secplot_tem_alpha_above_doi", "tem_alpha_above_doi", float
    ),
    "secplot_tem_alpha_below_doi": _b(
        "secplot_tem_alpha_below_doi", "tem_alpha_below_doi", float
    ),
    "secplot_tem_rasterized": _b("secplot_tem_rasterized", "tem_rasterized", bool),
}

# Images settings
IMAGES_BINDINGS: dict[str, Bind] = {
    "secplot_images_alpha": _b("secplot_images_alpha", "images_alpha", str),
    "secplot_images_zorder": _b("secplot_images_zorder", "images_zorder", str),
    "secplot_images_clip": _b("secplot_images_clip", "images_clip", bool),
}

# Merged dict of all declaratively-bound settings
ALL_BINDINGS: dict[str, Bind] = {
    **GENERAL_BINDINGS,
    **DEM_BINDINGS,
    **TEM_BINDINGS,
    **IMAGES_BINDINGS,
}

# ---------------------------------------------------------------------------
# Low-level widget dispatch
# ---------------------------------------------------------------------------


def _set_widget(widget: Any, value: Any, type_: type) -> None:  # noqa: ARG001 — type_ unused here; coercion done directly on value
    """Push *value* into *widget*, dispatching on widget type.

    Unknown widget types are silently skipped (no crash).
    """
    if isinstance(widget, QComboBox):
        set_combobox(widget, str(value), add_if_not_exists=False)
    elif isinstance(widget, QCheckBox):
        widget.setChecked(bool(value))
    elif isinstance(widget, QGroupBox):
        # QGroupBox can be made checkable; treat like a checkbox
        if widget.isCheckable():
            widget.setChecked(bool(value))
    elif isinstance(widget, QLineEdit):
        widget.setText(str(value))
    elif isinstance(widget, QDoubleSpinBox):
        widget.setValue(float(value))
    elif isinstance(widget, QSpinBox):
        widget.setValue(int(value))
    # Unknown widget type: silently skip


def _get_widget_value(widget: Any, type_: type) -> Any:
    """Read the current value from *widget*, returning *type_*'s zero-value as fallback."""
    if isinstance(widget, QComboBox):
        return widget.currentText()
    elif isinstance(widget, QCheckBox):
        return widget.isChecked()
    elif isinstance(widget, QGroupBox):
        if widget.isCheckable():
            return widget.isChecked()
        return type_()
    elif isinstance(widget, QLineEdit):
        return widget.text()
    elif isinstance(widget, QDoubleSpinBox):
        return widget.value()
    elif isinstance(widget, QSpinBox):
        return widget.value()
    return type_()  # fallback to zero-value


# ---------------------------------------------------------------------------
# Public round-trip functions
# ---------------------------------------------------------------------------


def apply_settings_to_ui(
    ui: Any, ms: Any, bindings: dict[str, Bind] = ALL_BINDINGS
) -> None:
    """Settings → widgets.  Call at dock-open time to restore saved values."""
    for key, b in bindings.items():
        _set_widget(getattr(ui, b.widget), ms.settingsdict.get(key, b.default), b.type_)


def collect_ui_to_settings(
    ui: Any, ms: Any, bindings: dict[str, Bind] = ALL_BINDINGS
) -> None:
    """Widgets → settings. Replaces _load_ui_settings() in Task 5 slimdown."""
    for key, b in bindings.items():
        ms.settingsdict[key] = _get_widget_value(getattr(ui, b.widget), b.type_)


def save_settings(ms: Any, bindings: dict[str, Bind] = ALL_BINDINGS) -> None:
    """Persist all declaratively-bound keys to QgsProject."""
    for key in bindings:
        ms.save_settings(key)
