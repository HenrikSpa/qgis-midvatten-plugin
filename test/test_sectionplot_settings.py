"""
Pure Qt unit tests for tools/sectionplot/settings.py.

No QGIS project, no DB — only real Qt widget instances and unittest.mock.
The QgsApplication is initialised by test/__init__.py, which also ensures that
qgis.PyQt.QtWidgets widgets can be constructed.
"""

from unittest.mock import MagicMock

import pytest
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QLineEdit,
    QSpinBox,
)

from midvatten.tools.sectionplot.settings import (
    ALL_BINDINGS,
    DEM_BINDINGS,
    GENERAL_BINDINGS,
    IMAGES_BINDINGS,
    TEM_BINDINGS,
    _defaults,
    apply_settings_to_ui,
    collect_ui_to_settings,
    save_settings,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeUI:
    """Simple namespace to hold widget attributes."""


def make_ms(settingsdict):
    ms = MagicMock()
    ms.settingsdict = settingsdict
    return ms


# ---------------------------------------------------------------------------
# Widget dispatch tests — _set_widget (via apply_settings_to_ui)
# ---------------------------------------------------------------------------


def test_apply_settings_checkbox():
    """QCheckBox receives True correctly."""
    ui = FakeUI()
    ui.include_views_check_box = QCheckBox()
    ms = make_ms({"secplotincludeviews": True})
    apply_settings_to_ui(
        ui, ms, {"secplotincludeviews": ALL_BINDINGS["secplotincludeviews"]}
    )
    assert ui.include_views_check_box.isChecked()


def test_apply_settings_checkbox_false():
    """QCheckBox receives False correctly."""
    ui = FakeUI()
    ui.include_views_check_box = QCheckBox()
    ms = make_ms({"secplotincludeviews": False})
    apply_settings_to_ui(
        ui, ms, {"secplotincludeviews": ALL_BINDINGS["secplotincludeviews"]}
    )
    assert not ui.include_views_check_box.isChecked()


def test_apply_settings_double_spinbox():
    """QDoubleSpinBox receives a float value correctly."""
    ui = FakeUI()
    spin = QDoubleSpinBox()
    spin.setRange(0.0, 100.0)
    ui.barwidthdouble_spin_box = spin
    ms = make_ms({"secplotbw": 3.5})
    apply_settings_to_ui(ui, ms, {"secplotbw": ALL_BINDINGS["secplotbw"]})
    assert spin.value() == pytest.approx(3.5)


def test_apply_settings_int_spinbox():
    """QSpinBox receives an integer value correctly."""
    ui = FakeUI()
    spin = QSpinBox()
    spin.setRange(0, 100)
    ui.secplot_grading_num_layers = spin
    ms = make_ms({"secplot_grading_num_layers": 5})
    apply_settings_to_ui(
        ui,
        ms,
        {"secplot_grading_num_layers": ALL_BINDINGS["secplot_grading_num_layers"]},
    )
    assert spin.value() == 5


def test_apply_settings_line_edit():
    """QLineEdit receives a string value correctly."""
    ui = FakeUI()
    le = QLineEdit()
    ui.drillstop = le
    ms = make_ms({"secplotdrillstop": "%berg%"})
    apply_settings_to_ui(ui, ms, {"secplotdrillstop": ALL_BINDINGS["secplotdrillstop"]})
    assert le.text() == "%berg%"


def test_apply_settings_checkable_groupbox():
    """A checkable QGroupBox receives True correctly."""
    ui = FakeUI()
    gb = QGroupBox()
    gb.setCheckable(True)
    ui.secplot_apply_graded_dems = gb
    ms = make_ms({"secplot_apply_graded_dems": True})
    apply_settings_to_ui(
        ui, ms, {"secplot_apply_graded_dems": ALL_BINDINGS["secplot_apply_graded_dems"]}
    )
    assert gb.isChecked()


def test_apply_settings_non_checkable_groupbox_no_crash():
    """A non-checkable QGroupBox does not raise when apply is called."""
    ui = FakeUI()
    gb = QGroupBox()
    gb.setCheckable(False)
    ui.secplot_apply_graded_dems = gb
    ms = make_ms({"secplot_apply_graded_dems": True})
    apply_settings_to_ui(
        ui, ms, {"secplot_apply_graded_dems": ALL_BINDINGS["secplot_apply_graded_dems"]}
    )


def test_apply_settings_combobox_existing_value():
    """QComboBox selects an existing item correctly."""
    ui = FakeUI()
    cb = QComboBox()
    cb.addItems(["viridis", "plasma"])
    ui.tem_colormap = cb
    ms = make_ms({"secplot_tem_colormap": "plasma"})
    apply_settings_to_ui(
        ui, ms, {"secplot_tem_colormap": ALL_BINDINGS["secplot_tem_colormap"]}
    )
    assert cb.currentText() == "plasma"


def test_apply_settings_combobox_missing_value_no_crash():
    """QComboBox with a missing value does not crash and keeps its item count."""
    ui = FakeUI()
    cb = QComboBox()
    cb.addItems(["viridis"])
    ui.tem_colormap = cb
    ms = make_ms({"secplot_tem_colormap": "nonexistent"})
    apply_settings_to_ui(
        ui, ms, {"secplot_tem_colormap": ALL_BINDINGS["secplot_tem_colormap"]}
    )
    assert cb.count() == 1


# ---------------------------------------------------------------------------
# Widget dispatch tests — _get_widget_value (via collect_ui_to_settings)
# ---------------------------------------------------------------------------


def test_collect_checkbox():
    """QCheckBox.isChecked() → bool in settingsdict."""
    ui = FakeUI()
    cb = QCheckBox()
    cb.setChecked(True)
    ui.labels_check_box = cb
    ms = make_ms({})
    collect_ui_to_settings(
        ui, ms, {"secplotlabelsplotted": ALL_BINDINGS["secplotlabelsplotted"]}
    )
    assert ms.settingsdict["secplotlabelsplotted"]


def test_collect_double_spinbox():
    """QDoubleSpinBox.value() → float in settingsdict."""
    ui = FakeUI()
    spin = QDoubleSpinBox()
    spin.setRange(0.0, 100.0)
    spin.setValue(2.5)
    ui.screen_width_factor_spin = spin
    ms = make_ms({})
    collect_ui_to_settings(
        ui, ms, {"screenwidthfactor": ALL_BINDINGS["screenwidthfactor"]}
    )
    assert ms.settingsdict["screenwidthfactor"] == pytest.approx(2.5)


def test_collect_int_spinbox():
    """QSpinBox.value() → int in settingsdict with correct type."""
    ui = FakeUI()
    spin = QSpinBox()
    spin.setRange(0, 100)
    spin.setValue(7)
    ui.secplot_grading_num_layers = spin
    ms = make_ms({})
    collect_ui_to_settings(
        ui,
        ms,
        {"secplot_grading_num_layers": ALL_BINDINGS["secplot_grading_num_layers"]},
    )
    assert ms.settingsdict["secplot_grading_num_layers"] == 7
    assert isinstance(ms.settingsdict["secplot_grading_num_layers"], int)


def test_collect_line_edit():
    """QLineEdit.text() → str in settingsdict with correct type."""
    ui = FakeUI()
    le = QLineEdit()
    le.setText("0.8")
    ui.images_alpha = le
    ms = make_ms({})
    collect_ui_to_settings(
        ui, ms, {"secplot_images_alpha": ALL_BINDINGS["secplot_images_alpha"]}
    )
    assert ms.settingsdict["secplot_images_alpha"] == "0.8"
    assert isinstance(ms.settingsdict["secplot_images_alpha"], str)


def test_collect_checkable_groupbox():
    """Checkable QGroupBox.isChecked() → bool in settingsdict."""
    ui = FakeUI()
    gb = QGroupBox()
    gb.setCheckable(True)
    gb.setChecked(True)
    ui.secplot_apply_graded_dems = gb
    ms = make_ms({})
    collect_ui_to_settings(
        ui, ms, {"secplot_apply_graded_dems": ALL_BINDINGS["secplot_apply_graded_dems"]}
    )
    assert ms.settingsdict["secplot_apply_graded_dems"]


def test_collect_non_checkable_groupbox_fallback():
    """Non-checkable QGroupBox returns type_ zero-value (False for bool)."""
    ui = FakeUI()
    gb = QGroupBox()
    gb.setCheckable(False)
    ui.secplot_apply_graded_dems = gb
    ms = make_ms({})
    collect_ui_to_settings(
        ui, ms, {"secplot_apply_graded_dems": ALL_BINDINGS["secplot_apply_graded_dems"]}
    )
    assert not ms.settingsdict["secplot_apply_graded_dems"]


# ---------------------------------------------------------------------------
# Default value tests
# ---------------------------------------------------------------------------


def test_apply_uses_default_when_key_missing():
    """When key is absent from settingsdict, the widget gets the default from _defaults."""
    ui = FakeUI()
    cb = QCheckBox()
    ui.include_views_check_box = cb
    ms = make_ms({})  # empty — key missing
    apply_settings_to_ui(
        ui, ms, {"secplotincludeviews": ALL_BINDINGS["secplotincludeviews"]}
    )
    expected_default = _defaults["secplotincludeviews"]
    assert cb.isChecked() is bool(expected_default)


def test_apply_uses_provided_value_over_default():
    """When key is present with a non-default value, the widget gets that value."""
    default_val = _defaults["secplotincludeviews"]
    non_default_val = not bool(default_val)

    ui = FakeUI()
    cb = QCheckBox()
    ui.include_views_check_box = cb
    ms = make_ms({"secplotincludeviews": non_default_val})
    apply_settings_to_ui(
        ui, ms, {"secplotincludeviews": ALL_BINDINGS["secplotincludeviews"]}
    )
    assert cb.isChecked() is non_default_val


# ---------------------------------------------------------------------------
# save_settings test
# ---------------------------------------------------------------------------


def test_save_settings_calls_ms_for_all_keys():
    """save_settings calls ms.save_settings exactly once per bound key."""
    ms = MagicMock()
    save_settings(ms)
    assert ms.save_settings.call_count == len(ALL_BINDINGS)
    called_keys = {call.args[0] for call in ms.save_settings.call_args_list}
    assert called_keys == set(ALL_BINDINGS.keys())


# ---------------------------------------------------------------------------
# Group round-trip tests
# ---------------------------------------------------------------------------


def test_general_bindings_roundtrip():
    """Non-combo GENERAL_BINDINGS keys survive apply → collect with correct values."""
    test_values = {
        "secplotbw": 4.0,
        "secplotdrillstop": "%lera%",
        "secplotincludeviews": True,
        "secplotlabelsplotted": False,
        "secplotlegendplotted": True,
        "screenwidthfactor": 1.5,
    }

    ui = FakeUI()

    spin_bw = QDoubleSpinBox()
    spin_bw.setRange(0.0, 100.0)
    ui.barwidthdouble_spin_box = spin_bw

    le_drillstop = QLineEdit()
    ui.drillstop = le_drillstop

    cb_includeviews = QCheckBox()
    ui.include_views_check_box = cb_includeviews

    cb_labels = QCheckBox()
    ui.labels_check_box = cb_labels

    cb_legend = QCheckBox()
    ui.create_legend = cb_legend

    spin_width = QDoubleSpinBox()
    spin_width.setRange(0.0, 100.0)
    ui.screen_width_factor_spin = spin_width

    # Use only the non-combo subset of GENERAL_BINDINGS.
    test_bindings = {k: GENERAL_BINDINGS[k] for k in test_values}

    ms = make_ms(dict(test_values))
    apply_settings_to_ui(ui, ms, test_bindings)

    ms_out = make_ms({})
    collect_ui_to_settings(ui, ms_out, test_bindings)

    assert ms_out.settingsdict["secplotbw"] == pytest.approx(4.0)
    assert ms_out.settingsdict["secplotdrillstop"] == "%lera%"
    assert ms_out.settingsdict["secplotincludeviews"]
    assert not ms_out.settingsdict["secplotlabelsplotted"]
    assert ms_out.settingsdict["secplotlegendplotted"]
    assert ms_out.settingsdict["screenwidthfactor"] == pytest.approx(1.5)


def test_tem_bindings_non_combo_roundtrip():
    """Non-combo TEM keys survive apply → collect with correct values."""
    test_values = {
        "secplot_tem_data_fit": True,
        "secplot_tem_snap": True,
        "secplot_tem_rasterized": False,
        "secplot_tem_vmin": "0.01",
        "secplot_tem_vmax": "100",
        "secplot_tem_edgecolors": "none",
        "secplot_tem_alpha_above_doi": 0.3,
        "secplot_tem_alpha_below_doi": 0.7,
    }

    ui = FakeUI()

    cb_data_fit = QCheckBox()
    ui.tem_data_fit = cb_data_fit

    cb_snap = QCheckBox()
    ui.tem_snap = cb_snap

    cb_rasterized = QCheckBox()
    ui.tem_rasterized = cb_rasterized

    le_vmin = QLineEdit()
    ui.tem_vmin = le_vmin

    le_vmax = QLineEdit()
    ui.tem_vmax = le_vmax

    le_edgecolors = QLineEdit()
    ui.tem_edgecolors = le_edgecolors

    spin_alpha_above = QDoubleSpinBox()
    spin_alpha_above.setRange(0.0, 1.0)
    spin_alpha_above.setDecimals(2)
    ui.tem_alpha_above_doi = spin_alpha_above

    spin_alpha_below = QDoubleSpinBox()
    spin_alpha_below.setRange(0.0, 1.0)
    spin_alpha_below.setDecimals(2)
    ui.tem_alpha_below_doi = spin_alpha_below

    test_bindings = {k: TEM_BINDINGS[k] for k in test_values}

    ms = make_ms(dict(test_values))
    apply_settings_to_ui(ui, ms, test_bindings)

    ms_out = make_ms({})
    collect_ui_to_settings(ui, ms_out, test_bindings)

    assert ms_out.settingsdict["secplot_tem_data_fit"]
    assert ms_out.settingsdict["secplot_tem_snap"]
    assert not ms_out.settingsdict["secplot_tem_rasterized"]
    assert ms_out.settingsdict["secplot_tem_vmin"] == "0.01"
    assert ms_out.settingsdict["secplot_tem_vmax"] == "100"
    assert ms_out.settingsdict["secplot_tem_edgecolors"] == "none"
    assert ms_out.settingsdict["secplot_tem_alpha_above_doi"] == pytest.approx(0.3)
    assert ms_out.settingsdict["secplot_tem_alpha_below_doi"] == pytest.approx(0.7)


def test_dem_bindings_roundtrip():
    """All DEM keys survive apply → collect with correct values."""
    test_values = {
        "secplotdem_sampling_distance": 3.0,
        "secplot_apply_graded_dems": True,
        "secplot_grading_depth": 12.0,
        "secplot_grading_num_layers": 7,
        "secplot_grading_max_opacity": 0.9,
        "secplot_grading_min_opacity": 0.1,
    }

    ui = FakeUI()

    spin_sampling = QDoubleSpinBox()
    spin_sampling.setRange(0.0, 1000.0)
    ui.dem_sampling_distance = spin_sampling

    gb_apply = QGroupBox()
    gb_apply.setCheckable(True)
    ui.secplot_apply_graded_dems = gb_apply

    spin_depth = QDoubleSpinBox()
    spin_depth.setRange(0.0, 100.0)
    ui.secplot_grading_depth = spin_depth

    spin_layers = QSpinBox()
    spin_layers.setRange(1, 50)
    ui.secplot_grading_num_layers = spin_layers

    spin_max_opacity = QDoubleSpinBox()
    spin_max_opacity.setRange(0.0, 1.0)
    spin_max_opacity.setDecimals(2)
    ui.secplot_grading_max_opacity = spin_max_opacity

    spin_min_opacity = QDoubleSpinBox()
    spin_min_opacity.setRange(0.0, 1.0)
    spin_min_opacity.setDecimals(2)
    ui.secplot_grading_min_opacity = spin_min_opacity

    ms = make_ms(dict(test_values))
    apply_settings_to_ui(ui, ms, DEM_BINDINGS)

    ms_out = make_ms({})
    collect_ui_to_settings(ui, ms_out, DEM_BINDINGS)

    assert ms_out.settingsdict["secplotdem_sampling_distance"] == pytest.approx(3.0)
    assert ms_out.settingsdict["secplot_apply_graded_dems"]
    assert ms_out.settingsdict["secplot_grading_depth"] == pytest.approx(12.0)
    assert ms_out.settingsdict["secplot_grading_num_layers"] == 7
    assert isinstance(ms_out.settingsdict["secplot_grading_num_layers"], int)
    assert ms_out.settingsdict["secplot_grading_max_opacity"] == pytest.approx(0.9)
    assert ms_out.settingsdict["secplot_grading_min_opacity"] == pytest.approx(0.1)


def test_images_bindings_roundtrip():
    """All IMAGES keys survive apply → collect with correct values."""
    test_values = {
        "secplot_images_alpha": "0.5",
        "secplot_images_zorder": "3",
        "secplot_images_clip": False,
    }

    ui = FakeUI()

    le_alpha = QLineEdit()
    ui.images_alpha = le_alpha

    le_zorder = QLineEdit()
    ui.images_zorder = le_zorder

    cb_clip = QCheckBox()
    ui.images_clip = cb_clip

    ms = make_ms(dict(test_values))
    apply_settings_to_ui(ui, ms, IMAGES_BINDINGS)

    ms_out = make_ms({})
    collect_ui_to_settings(ui, ms_out, IMAGES_BINDINGS)

    assert ms_out.settingsdict["secplot_images_alpha"] == "0.5"
    assert ms_out.settingsdict["secplot_images_zorder"] == "3"
    assert not ms_out.settingsdict["secplot_images_clip"]


# ---------------------------------------------------------------------------
# Type enforcement test
# ---------------------------------------------------------------------------


def test_collect_returns_correct_types():
    """After collect, each value has the correct Python type."""
    ui = FakeUI()

    spin_bw = QDoubleSpinBox()
    spin_bw.setRange(0.0, 100.0)
    spin_bw.setValue(2.0)
    ui.barwidthdouble_spin_box = spin_bw

    cb_include = QCheckBox()
    cb_include.setChecked(True)
    ui.include_views_check_box = cb_include

    spin_layers = QSpinBox()
    spin_layers.setRange(1, 50)
    spin_layers.setValue(3)
    ui.secplot_grading_num_layers = spin_layers

    le_alpha = QLineEdit()
    le_alpha.setText("0.5")
    ui.images_alpha = le_alpha

    test_bindings = {
        "secplotbw": GENERAL_BINDINGS["secplotbw"],
        "secplotincludeviews": GENERAL_BINDINGS["secplotincludeviews"],
        "secplot_grading_num_layers": DEM_BINDINGS["secplot_grading_num_layers"],
        "secplot_images_alpha": IMAGES_BINDINGS["secplot_images_alpha"],
    }

    ms = make_ms({})
    collect_ui_to_settings(ui, ms, test_bindings)

    assert isinstance(ms.settingsdict["secplotbw"], float)
    assert isinstance(ms.settingsdict["secplotincludeviews"], bool)
    assert isinstance(ms.settingsdict["secplot_grading_num_layers"], int)
    assert isinstance(ms.settingsdict["secplot_images_alpha"], str)
