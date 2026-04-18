#! /usr/bin/env python
"""
/***************************************************************************
 This is where a section plot is created
 NOTE - if using this file, it has to be imported by midvatten_plugin.py
                             -------------------
        begin                : 2013-11-27
        copyright            : (C) 2011 by joskal
        email                : groundwatergis [at] gmail.com
 ***************************************************************************/
"""

import copy
import json
import logging
import os
import traceback
import types
from contextlib import contextmanager
from functools import partial

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import qgis.PyQt
from matplotlib import container, patches

from midvatten.tools.utils.mpl_compat import FigureCanvas, NavigationToolbar
from qgis.PyQt import QtWidgets
from qgis.PyQt import uic
from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtWidgets import QApplication, QDockWidget, QSizePolicy
from qgis.core import (
    QgsVectorLayer,
    QgsWkbTypes,
    Qgis,
)

from midvatten.tools.utils.file_utils import ui_path
from midvatten.tools.utils.gui_utils import set_combobox


Ui_SecPlotDock = uic.loadUiType(ui_path("secplotdockwidget.ui"))[0]

from matplotlib.widgets import Slider  # noqa: E402
from matplotlib.gridspec import GridSpec  # noqa: E402
import datetime  # noqa: E402
import matplotlib.dates as mdates  # noqa: E402
from copy import deepcopy  # noqa: E402

from midvatten.tools.utils import common_utils, db_utils  # noqa: E402
from midvatten.tools.utils.string_utils import returnunicode as ru  # noqa: E402
from midvatten.tools.utils.midvatten_utils import PlotTemplates  # noqa: E402
from midvatten.tools.utils.gui_utils import DetachFigureButton, ReverseSectionButton  # noqa: E402
import midvatten.definitions.midvatten_defs as defs  # noqa: E402
from midvatten.tools.utils import matplotlib_replacements  # noqa: E402
from midvatten.tools.sectionplot.figure import SectionPlotFigure  # noqa: E402
from midvatten.tools.sectionplot.legend import SectionPlotLegendManager  # noqa: E402
from midvatten.tools.sectionplot import painters as _painters  # noqa: E402
from midvatten.tools.sectionplot._utils import (  # noqa: E402, F401
    get_legend_items_labels,
    get_plot_label_name,
)
from midvatten.tools.sectionplot.ui_types import SecPlotUi  # noqa: E402
from midvatten.tools.sectionplot.settings import (  # noqa: E402
    apply_settings_to_ui,
    collect_ui_to_settings,
    save_settings as _save_bound_settings,
)
from midvatten.tools.sectionplot.data import (  # noqa: E402
    prepare_obsid_positions as _prepare_obsid_positions,
    get_z_data as _get_z_data,
    get_plot_data_bars as _get_plot_data_bars,
    get_screen_plot_data as _get_screen_plot_data,
    get_plot_data_layer_texts as _get_plot_data_layer_texts,
    get_drillstops as _get_drillstops,
    get_plot_data_seismic as _get_plot_data_seismic,
    get_water_levels_from_df as _get_water_levels_from_df,
    get_length_map,  # noqa: F401 — re-exported via __init__.py
    fill_empty_columns,  # noqa: F401 — re-exported via __init__.py
    slider_val_to_idx,  # noqa: F401 — re-exported via __init__.py
    SEISMIC_Y1_COLUMN,
    SEISMIC_Y2_COLUMN,
    SEISMIC_Y3_COLUMN,
)
from midvatten.tools.sectionplot._ui_fill import (  # noqa: E402
    fill_tem as _fill_tem,
    fill_images as _fill_images,
    fill_dem_list as _fill_dem_list,
)

_WLVL_EXCLUDED_TABLES = (
    "comments",
    "obs_points",
    "obs_lines",
    "obs_p_w_lvl",
    "obs_p_w_qual_field",
    "obs_p_w_qual_lab",
    "obs_p_w_strat",
    "seismic_data",
    "meteo",
    "vlf_data",
    "w_flow",
    "w_qual_field_geom",
    "zz_flowtype",
    "w_qual_lab",
    "w_qual_field",
    "stratigraphy",
    "about_db",
)

_SCREEN_MODE_TO_DISPLAY = {"none": "None", "behind": "Behind", "ontop": "On top"}
_SCREEN_MODE_FROM_DISPLAY = {v: k for k, v in _SCREEN_MODE_TO_DISPLAY.items()}

log = logging.getLogger(__name__)


class SectionPlot(qgis.PyQt.QtWidgets.QDockWidget, SecPlotUi, Ui_SecPlotDock):
    def __init__(self, iface, ms):
        qgis.PyQt.QtWidgets.QDockWidget.__init__(self, iface.mainWindow())

        self.figures = {}
        self.figure = None

        self.geo_bars = {}
        self.hydro_bars = {}
        self.screen_bars = {}
        self.layer_texts = {}
        self.hydro_colors = defs.hydrocolors()

        self.parent = iface.mainWindow()
        self.iface = iface
        self._ms = ms

        if not self.isWindow():
            self.dockLocationChanged.connect(
                self.set_location
            )  # not really implemented yet

        self.setupUi(self)
        self.init_ui()
        self.template_plot_label.setText(
            '<a href="https://github.com/jkall/qgis-midvatten-plugin/wiki/5.-Plots-and-reports#create-section-plot">Templates manual</a>'
        )
        self.template_plot_label.setOpenExternalLinks(True)

    def init_ui(self):
        # connect signal
        self.push_button.clicked.connect(lambda x: self.draw_plot())
        self.topLevelChanged.connect(lambda x: self.add_titlebar(self))
        self.settingsdock_widget.topLevelChanged.connect(
            lambda x: self.float_settings()
        )
        self.include_views_check_box.clicked.connect(
            lambda x: self.fill_wlvltable(self.include_views_check_box.isChecked())
        )
        self.tab_widget.currentChanged.connect(
            lambda: tabwidget_resize(self.tab_widget)
        )
        tabwidget_resize(self.tab_widget)
        self.wlvl_groupbox.collapsedStateChanged.connect(
            lambda: self.resize_widget(self.settingsdock_widget)
        )
        self.dem_groupbox.collapsedStateChanged.connect(
            lambda: self.resize_widget(self.settingsdock_widget)
        )
        self.bar_groupbox.collapsedStateChanged.connect(
            lambda: self.resize_widget(self.settingsdock_widget)
        )
        self.plots_groupbox.collapsedStateChanged.connect(
            lambda: self.resize_widget(self.settingsdock_widget)
        )
        self.tem_groupbox.collapsedStateChanged.connect(
            lambda: self.resize_widget(self.settingsdock_widget)
        )
        self.images_groupbox.collapsedStateChanged.connect(
            lambda: self.resize_widget(self.settingsdock_widget)
        )
        self.tab_widget.setTabBarAutoHide(True)
        self.settingsdock_widget.closeEvent = types.MethodType(
            self.dock_settings, self.settingsdock_widget
        )
        self.resize_widget(self.settingsdock_widget)
        self.resample_rule.setText("1D")
        self.resample_rule.setToolTip(defs.pandas_rule_tooltip())
        self.resample_offset.setText("0" if pd.__version__ < "1.1.0" else "")
        self.resample_offset.setToolTip(defs.pandas_base_tooltip())
        self.resample_how.setText("mean")
        self.resample_how.setToolTip(defs.pandas_how_tooltip())

        # Restore saved settings to widgets immediately so values are visible
        # when the dock opens before the first plot is drawn (bug fix: previously
        # fill_*() methods were only called from create_new_plot()).
        # Restores saved values to widgets on dock open. TEM combo-box *choices* are
        # not yet populated (that happens in fill_tem), so combo values are re-applied
        # there. All other widget types (checkboxes, spinboxes, line edits) are set here.
        apply_settings_to_ui(self, self._ms)

    def show(self) -> None:
        """Validate layers and trigger section plot.

        Logic moved from midvatten_plugin.plot_section().
        """
        selected_layer = self.iface.mapCanvas().currentLayer()  # MUST BE LINE VECTOR LAYER WITH SAME EPSG as MIDV_OBSDB AND THERE MUST BE ONLY ONE SELECTED FEATURE
        if not selected_layer:
            common_utils.MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "Midvatten",
                    "You must select at least one layer and one feature!",
                ),
                duration=10,
            )
            raise common_utils.UsageError()

        nrofselected = selected_layer.selectedFeatureCount()
        if not isinstance(selected_layer, QgsVectorLayer):
            common_utils.MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "Midvatten",
                    "You must activate the vector line layer that defines the section.",
                ),
                log_msg=QCoreApplication.translate(
                    "Midvatten",
                    'The layer must be of type QgsVectorLayer, but was  "%s".',
                )
                % str(type(selected_layer)),
            )
            raise common_utils.UsageError()
        selected_obspoints = None
        for feat in selected_layer.getSelectedFeatures():
            geom = feat.geometry()
            if geom.wkbType() in (
                QgsWkbTypes.Type.LineString,
                2,
                QgsWkbTypes.Type.MultiLineString,
                5,
                QgsWkbTypes.Type.LineStringZ,
                1002,
                QgsWkbTypes.Type.MultiLineStringZ,
                1005,
                QgsWkbTypes.Type.LineStringM,
                2002,
                QgsWkbTypes.Type.MultiLineStringM,
                2005,
                QgsWkbTypes.Type.LineStringZM,
                3002,
                QgsWkbTypes.Type.MultiLineStringZM,
                3005,
            ):
                if nrofselected != 1:
                    common_utils.MessagebarAndLog.critical(
                        bar_msg=QCoreApplication.translate(
                            "Midvatten",
                            "You must select only one line feature that defines the section",
                        )
                    )
                    raise common_utils.UsageError()
                else:
                    try:
                        obs_points_layer = common_utils.find_layer("obs_points")
                    except common_utils.UsageError as e:
                        common_utils.MessagebarAndLog.critical(
                            bar_msg=QCoreApplication.translate(
                                "Midvatten",
                                "%s. Plotting without observations!",
                            )
                            % str(e)
                        )
                        break
                    else:
                        if obs_points_layer.isEditable():
                            common_utils.MessagebarAndLog.warning(
                                bar_msg=QCoreApplication.translate(
                                    "Midvatten",
                                    "Layer obs_points is in editing mode! Plotting without observations!",
                                )
                            )
                            break
                        else:
                            selected_obspoints = common_utils.get_selected_object_names(
                                obs_points_layer
                            )
            else:
                selected_layer = None
                selected_obspoints = (
                    common_utils.get_selected_object_names()
                )  # Finding obsid from currently selected layer
                if not selected_obspoints:
                    common_utils.MessagebarAndLog.warning(
                        bar_msg=QCoreApplication.translate(
                            "Midvatten",
                            "The current layer had no selected obsids. Trying to plot from layer obs_points!",
                        )
                    )
                    try:
                        obs_points_layer = common_utils.find_layer("obs_points")
                    except common_utils.UsageError:
                        common_utils.MessagebarAndLog.warning(
                            bar_msg=QCoreApplication.translate(
                                "Midvatten",
                                "Layer obs_points is not found. Plotting without observations!",
                            )
                        )
                        break
                    else:
                        if obs_points_layer.isEditable():
                            common_utils.MessagebarAndLog.warning(
                                bar_msg=QCoreApplication.translate(
                                    "Midvatten",
                                    "Layer obs_points is in editing mode! Plotting without observations!",
                                )
                            )
                            break
                        else:
                            selected_obspoints = common_utils.get_selected_object_names(
                                obs_points_layer
                            )

        if not selected_layer and not selected_obspoints:
            common_utils.MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "Midvatten", "You must select at least one feature!"
                ),
                duration=10,
            )
            raise common_utils.UsageError()
        elif not selected_layer:
            common_utils.MessagebarAndLog.info(
                bar_msg=QCoreApplication.translate(
                    "Midvatten",
                    "No line layer was selected. The stratigraphy bars will be lined up from south-north or west-east and no DEMS will be plotted.",
                ),
                duration=10,
            )

        if selected_obspoints is not None and len(selected_obspoints) > 0:
            selected_obspoints = ru(selected_obspoints, keep_containers=True)
        else:
            selected_obspoints = []

        self.create_new_plot(self._ms, selected_obspoints, selected_layer)
        super().show()
        self.activateWindow()

    def create_new_plot(self, msettings, selected_obspoints, line_layer):
        self.line_layer = None
        self.line_feature = None
        self.obs_lines_plot_data = None
        if line_layer:
            selected_features = [f for f in line_layer.getSelectedFeatures()]
            if len(selected_features) != 1:
                common_utils.MessagebarAndLog.critical(
                    bar_msg=QCoreApplication.translate(
                        "SectionPlot",
                        "Must select only one feature in qgis layer: %s)",
                    )
                    % line_layer.name()
                )
            else:
                self.line_layer = line_layer
                self.line_feature = selected_features[0]
        self.obsid_annotation = {}
        self.water_level_labels_duplicate_check = []

        # show the user this may take a long time...
        common_utils.start_waiting_cursor()
        # settings must be recieved here since plot windows may stay open (hence sectionplot instance activated) while a new qgis project is opened or midv settings are changed.
        self.ms = msettings

        template_folder = os.path.join(
            os.path.split(os.path.split(os.path.dirname(__file__))[0])[0],
            "definitions",
            "secplot_templates",
        )
        self.secplot_templates = PlotTemplates(
            self,
            self.template_list,
            self.edit_button,
            self.load_button,
            self.save_as_button,
            self.import_button,
            self.remove_button,
            template_folder,
            "secplot_templates",
            "secplot_loaded_template",
            defs.secplot_default_template(),
            self.ms,
        )

        self.iface.addDockWidget(max(self.ms.settingsdict["secplotlocation"], 1), self)
        self.iface.mapCanvas().setRenderFlag(True)

        self.temptable_name = "temporary_section_line"

        self.dbconnection = db_utils.DbConnectionManager()

        self.fill_combo_boxes()
        self.fill_tem(self.line_feature)
        self.fill_images(self.line_feature)
        self.fill_dem_list(self.line_layer)

        # Re-apply all bound settings (including checkboxes, spinboxes).
        apply_settings_to_ui(self, self.ms)
        # Special-case: unbound settings not covered by the declarative bindings.
        self.plot_stratigraphy.setChecked(
            bool(self.ms.settingsdict["stratigraphyplotted"])
        )
        self.hydrology_radio_button.setChecked(
            bool(self.ms.settingsdict["secplothydrologyplotted"])
        )
        if self.ms.settingsdict["secplotwidthofplot"]:
            self.width_of_plot.setChecked(True)
        else:
            self.width_of_profile.setChecked(True)
        if self.ms.settingsdict["secplotlayertextalignment"] == "center":
            self.text_align_center.setChecked(True)
        else:
            self.text_align_edge.setChecked(True)
        self.screens_mode_combo.setCurrentText(
            _SCREEN_MODE_TO_DISPLAY.get(self.ms.settingsdict["screensplotmode"], "None")
        )

        super().show()

        # Upload line feature to DB temp table and compute obsid x-positions.
        if self.line_layer is not None:
            self.upload_qgis_vector_layer(self.line_layer, self.line_feature)
        self.obsids_x_position = _prepare_obsid_positions(
            line_feature=self.line_feature,
            selected_obspoints=selected_obspoints,
            line_layer=self.line_layer,
            dbconnection=self.dbconnection,
            temptable_name=self.temptable_name,
        )

        # Fetch all data needed for plotting.
        self.z_data = _get_z_data(
            self.obsids_x_position,
            dbconnection=self.dbconnection,
        )
        self.geo_bars = _get_plot_data_bars(
            obsids_x_position=self.obsids_x_position,
            z_data=self.z_data,
            typ_subtypes=defs.plot_types_dict(),
            obsid_annotation=self.obsid_annotation,
            dbconnection=self.dbconnection,
            strat_key="geoshort",
        )
        hydro_subtypes = {k: f"IN ('{k}')" for k in self.hydro_colors.keys()}
        self.hydro_bars = _get_plot_data_bars(
            obsids_x_position=self.obsids_x_position,
            z_data=self.z_data,
            typ_subtypes=hydro_subtypes,
            obsid_annotation=self.obsid_annotation,
            dbconnection=self.dbconnection,
            strat_key="capacity",
        )
        self.layer_texts = _get_plot_data_layer_texts(
            obsids_x_position=self.obsids_x_position,
            z_data=self.z_data,
            hydro_colors=self.hydro_colors,
            dbconnection=self.dbconnection,
        )
        if self.ms.settingsdict["screensplotmode"] != "none":
            self.screen_bars = _get_screen_plot_data(
                obsids_x_position=self.obsids_x_position,
                z_data=self.z_data,
                dbconnection=self.dbconnection,
            )
        else:
            self.screen_bars = {}
        if self.line_feature is not None:
            self.obs_lines_plot_data = _get_plot_data_seismic(
                line_layer=self.line_layer,
                line_feature=self.line_feature,
                dbconnection=self.dbconnection,
            )
            # Store the seismic column names for paint_obs_lines_data.
            self.y1_column = SEISMIC_Y1_COLUMN
            self.y2_column = SEISMIC_Y2_COLUMN
            self.y3_column = SEISMIC_Y3_COLUMN

        # Add annotation entries for obsids without stratigraphy.
        for obs, x in self.obsids_x_position.items():
            if obs not in self.obsid_annotation and (
                self.ms.settingsdict["stratigraphyplotted"]
                or self.ms.settingsdict["secplothydrologyplotted"]
            ):
                self.obsid_annotation[obs] = (
                    x,
                    self.z_data[obs]["bottom"] + self.z_data[obs]["barheight"],
                )

        self.drillstops = _get_drillstops(
            obsids_x_position=self.obsids_x_position,
            z_data=self.z_data,
            settingsdict=self.ms.settingsdict,
            dbconnection=self.dbconnection,
        )

        self.draw_plot()
        common_utils.stop_waiting_cursor()

    def fill_combo_boxes(self):
        self.textcol_combo_box.clear()
        self.datetime.clear()
        self.drillstop.clear()

        self.fill_wlvltable(self.include_views_check_box.isChecked())

        textitems = [
            "",
            "geology",
            "geoshort",
            "capacity",
            "hydroexplanation",
            "development",
            "comment",
        ]
        for item in textitems:
            self.textcol_combo_box.addItem(item)

        for datum in self.ms.settingsdict["secplotdates"]:
            self.datetime.append(datum)

        if len(str(self.ms.settingsdict["secplotwlvltab"])):
            set_combobox(
                self.wlvltable,
                str(self.ms.settingsdict["secplotwlvltab"]),
                add_if_not_exists=False,
            )

        if len(str(self.ms.settingsdict["secplottext"])):
            set_combobox(
                self.textcol_combo_box,
                str(self.ms.settingsdict["secplottext"]),
                add_if_not_exists=False,
            )

        if self.ms.settingsdict["secplotbw"] != 0:
            self.barwidthdouble_spin_box.setValue(self.ms.settingsdict["secplotbw"])
        else:
            self.barwidthdouble_spin_box.setValue(2)

        drillstop = (
            self.ms.settingsdict["secplotdrillstop"]
            if self.ms.settingsdict["secplotdrillstop"]
            else f"%{defs.bedrock_geoshort()}%"
        )
        self.drillstop.setText(drillstop)
        if self.ms.settingsdict["secplotincludeviews"]:
            self.include_views_check_box.setChecked(True)

    def fill_dem_list(self, line_layer=None):
        self.dem_layers, self.rasterselection = _fill_dem_list(
            self, self.ms, line_layer
        )

    def fill_wlvltable(self, include_views):
        self.ms.settingsdict["secplotincludeviews"] = include_views
        current_text = self.wlvltable.currentText()
        self.wlvltable.clear()
        skip_views = True if not include_views else False
        tabeller = [
            x
            for x in db_utils.get_tables(
                dbconnection=self.dbconnection, skip_views=skip_views
            )
            if not x.startswith("zz_") and x not in _WLVL_EXCLUDED_TABLES
        ]
        self.wlvltable.addItem("")
        for tabell in tabeller:
            self.wlvltable.addItem(tabell)
        set_combobox(self.wlvltable, str(current_text), add_if_not_exists=False)

    def fill_tem(self, line_feature=None):
        _fill_tem(self, self.ms, self.dbconnection, line_feature)

    def fill_images(self, line_feature):
        _fill_images(self, self.ms, self.dbconnection, line_feature)

    def draw_plot(self):
        self.water_level_labels_duplicate_check = []

        rcparams = self.secplot_templates.loaded_template.get("rcParams", {})
        for k, v in rcparams.items():
            try:
                mpl.rcParams[k] = v
            except KeyError:
                common_utils.MessagebarAndLog.info(
                    log_msg=QCoreApplication.translate(
                        "SectionPlot", "rcParams key %s didn't exist"
                    )
                    % ru(k)
                )

        try:
            common_utils.MessagebarAndLog.info(
                log_msg=QCoreApplication.translate(
                    "SectionPlot", "Plotting using settings:\n%s"
                )
                % self.secplot_templates.readable_output()
            )
        except Exception:
            common_utils.MessagebarAndLog.warning(log_msg=traceback.format_exc())
        if not isinstance(self.dbconnection, db_utils.DbConnectionManager):
            self.dbconnection = db_utils.DbConnectionManager()

        self.init_figure()

        try:
            common_utils.start_waiting_cursor()  # show the user this may take a long time...

            # Collect declaratively-bound widget values into settingsdict.
            collect_ui_to_settings(self, self.ms)
            # Special-case: settings not covered by the declarative bindings.
            temporarystring = ru(self.datetime.toPlainText())
            try:
                self.ms.settingsdict["secplotdates"] = [
                    x
                    for x in temporarystring.replace("\r", "").split("\n")
                    if x.strip()
                ]
            except TypeError:
                self.ms.settingsdict["secplotdates"] = ""
            self.ms.settingsdict["stratigraphyplotted"] = (
                self.plot_stratigraphy.isChecked()
            )
            self.ms.settingsdict["secplothydrologyplotted"] = (
                self.hydrology_radio_button.isChecked()
            )
            self.ms.settingsdict["screensplotmode"] = _SCREEN_MODE_FROM_DISPLAY.get(
                self.screens_mode_combo.currentText(), "none"
            )
            # Collect selected DEM raster layers.
            self.rasterselection = [
                item.text() for item in self.dem_list.selectedItems()
            ]
            self.ms.settingsdict["secplotselectedDEMs"] = self.rasterselection
            self.ms.settingsdict["secplot_tem_model_name"] = (
                self.tem_model_name.currentText()
            )
            self.ms.settingsdict["secplot_images_images"] = json.dumps(
                [item.text() for item in self.images_images.selectedItems()]
            )
            if self.text_align_center.isChecked():
                self.ms.settingsdict["secplotlayertextalignment"] = "center"
            else:
                self.ms.settingsdict["secplotlayertextalignment"] = "edge"

            _painters.paint_tem(
                self.figure,
                self.dbconnection,
                self.ms.settingsdict,
                self.secplot_templates.loaded_template,
            )
            _painters.paint_images(
                self.figure,
                self.dbconnection,
                self.ms.settingsdict,
            )

            if self.obsids_x_position:
                xmax, xmin = (
                    float(max(self.obsids_x_position.values())),
                    float(min(self.obsids_x_position.values())),
                )
                self.barwidth = (self.ms.settingsdict["secplotbw"] / 100.0) * (
                    xmax - xmin
                )

                _screens_mode = self.ms.settingsdict["screensplotmode"]
                if _screens_mode != "none" and self.screen_bars:
                    _painters.paint_screen_bars(
                        self.figure,
                        self.screen_bars,
                        defs.screen_style_dict(),
                        width=self.barwidth,
                        zorder=1 if _screens_mode == "behind" else 3,
                        width_factor=float(self.ms.settingsdict["screenwidthfactor"]),
                    )

                if self.ms.settingsdict["stratigraphyplotted"]:
                    _painters.paint_bars(
                        self.figure,
                        self.geo_bars,
                        self.secplot_templates.loaded_template,
                        color_dict=defs.plot_colors_dict(),
                        color_key="color",
                        hatch_dict=defs.plot_hatch_dict(),
                        barwidth=self.barwidth,
                    )
                    if len(self.ms.settingsdict["secplottext"]) > 0:
                        _painters.paint_layer_text(
                            self.figure,
                            self.layer_texts,
                            self.ms.settingsdict["secplottext"],
                            self.ms.settingsdict["secplotlayertextalignment"],
                            self.barwidth,
                            self.secplot_templates.loaded_template,
                        )

                if self.ms.settingsdict["secplothydrologyplotted"]:
                    hydro_color_dict = {k: v[1] for k, v in self.hydro_colors.items()}
                    _painters.paint_bars(
                        self.figure,
                        self.hydro_bars,
                        self.secplot_templates.loaded_template,
                        color_dict=hydro_color_dict,
                        color_key="color_qt",
                        hatch_dict=None,
                        barwidth=self.barwidth,
                    )
                    if len(self.ms.settingsdict["secplottext"]) > 0:
                        _painters.paint_layer_text(
                            self.figure,
                            self.layer_texts,
                            self.ms.settingsdict["secplottext"],
                            self.ms.settingsdict["secplotlayertextalignment"],
                            self.barwidth,
                            self.secplot_templates.loaded_template,
                        )

                _painters.paint_water_level(
                    self.figure,
                    self.dbconnection,
                    self.ms.settingsdict,
                    self.obsids_x_position,
                    self.waterlevel_lineplot,
                    plot_specific_dates=self.specific_dates_groupbox.isChecked(),
                )
                if self.interactive_groupbox.isChecked():
                    self.plot_water_level_interactive()

                if self.ms.settingsdict["secplotdrillstop"] != "" and self.drillstops:
                    drillstop_label = (
                        self.secplot_templates.loaded_template[
                            "drillstop_Axes_plot"
                        ].get("label")
                        or "drillstop like " + self.ms.settingsdict["secplotdrillstop"]
                    )
                    _painters.paint_drill_stop(
                        self.figure,
                        self.drillstops,
                        self.secplot_templates.loaded_template,
                        drillstop_label,
                    )

                # write obsid at top of each stratigraphy floating bar plot, also plot empty bars to show drillings without stratigraphy data
                if (
                    self.ms.settingsdict["stratigraphyplotted"]
                    or self.ms.settingsdict["secplothydrologyplotted"]
                    or (
                        self.ms.settingsdict["secplotdates"]
                        and len(self.ms.settingsdict["secplotdates"]) > 0
                    )
                ):
                    _painters.paint_obsids(
                        self.figure,
                        self.z_data,
                        self.obsids_x_position,
                        self.secplot_templates.loaded_template,
                        self.barwidth,
                        plot_stratigraphy=self.ms.settingsdict["stratigraphyplotted"],
                        plot_hydrology=self.ms.settingsdict["secplothydrologyplotted"],
                        plot_labels=self.ms.settingsdict["secplotlabelsplotted"],
                    )

            else:
                self.barwidth = 0.0

            # if the line layer obs_lines is selected, then try to plot seismic data if there are any
            if self.figure.line_layer and self.figure.line_layer.name() == "obs_lines":
                if len(self.obs_lines_plot_data) > 0:
                    _painters.paint_obs_lines_data(
                        self.figure,
                        self.obs_lines_plot_data,
                        self.y1_column,
                        self.y2_column,
                        self.y3_column,
                    )

            # if there are any DEMs selected, try to plot them
            if len(self.ms.settingsdict["secplotselectedDEMs"]) > 0:
                _painters.paint_dems(
                    self.figure,
                    self.dem_layers,
                    self.ms.settingsdict,
                    self.secplot_templates.loaded_template,
                    self.barwidth,
                    iface=self.iface,
                )

            _painters.configure_axes(
                self.figure,
                self.secplot_templates.loaded_template,
                self.barwidth,
            )

            # Build legend manager and assign to figure so detached callbacks can use it.
            legend_manager = SectionPlotLegendManager.from_template(
                self.secplot_templates.loaded_template
            )
            self.figure.legend_manager = legend_manager

            _painters.finish_plot(
                self.figure,
                self.secplot_templates.loaded_template,
                self.ms.settingsdict,
                legend_manager,
            )

            if self.width_of_plot.isChecked():
                self.ms.settingsdict["secplotwidthofplot"] = True
                self.update_barwidths_from_plot(self.figure.ax_main)
            else:
                self.ms.settingsdict["secplotwidthofplot"] = False

            self.update_plot_size()
            self.attach_signals(self.figure)
            self.figure.canvas.draw_idle()
            self.tab_widget.setCurrentIndex(0)
            plt.close(self.figure)

            # Persist all settings.
            _save_bound_settings(self.ms)
            self.ms.save_settings("secplotdates")
            self.ms.save_settings("secplotlocation")
            self.ms.save_settings("secplotselectedDEMs")
            self.ms.save_settings("stratigraphyplotted")
            self.ms.save_settings("screensplotmode")
            self.ms.save_settings("secplotwidthofplot")
            self.ms.save_settings("secplotlayertextalignment")
            self.ms.save_settings("secplot_tem_model_name")
            self.ms.save_settings("secplot_images_images")
            loaded_template = copy.deepcopy(self.secplot_templates.loaded_template)
            common_utils.save_stored_settings(
                self.ms, loaded_template, "secplot_loaded_template"
            )
            self.ms.save_settings("secplot_templates")

            self.dbconnection.closedb()
            self.dbconnection = None
        except KeyError:
            common_utils.MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "SectionPlot",
                    'Section plot optional settings error, press "Restore defaults"',
                ),
                log_msg=QCoreApplication.translate("SectionPlot", "Error msg: %s")
                % str(traceback.format_exc()),
            )
            common_utils.stop_waiting_cursor()
            self.dbconnection.closedb()
            self.dbconnection = None

        except Exception:
            common_utils.MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "SectionPlot", "An error occured, see log message panel!"
                ),
                log_msg=QCoreApplication.translate("SectionPlot", "Error msg:\n %s")
                % str(traceback.format_exc()),
            )

            common_utils.stop_waiting_cursor()
            self.dbconnection.closedb()
            self.dbconnection = None
            raise
        else:
            common_utils.stop_waiting_cursor()  # now this long process is done and the cursor is back as normal

    def remove_previous_figure(self):
        if self.figure is None:
            return

        previous_canvas = self.figure.canvas
        previous_toolbar = previous_canvas.toolbar
        self.layoutplot.removeWidget(previous_toolbar)
        previous_toolbar.close()

        self.layoutplot.removeWidget(previous_canvas)
        previous_canvas.close()

        fignum = self.figure.number
        if fignum in self.figures:
            del self.figures[fignum]
        plt.close(fignum)
        self.figure = None

    def init_figure(self):
        self.remove_previous_figure()

        if self.dynamic_plot_size.isChecked():
            self.figure = plt.figure(
                FigureClass=SectionPlotFigure, layout="constrained"
            )
        else:
            self.figure = plt.figure(FigureClass=SectionPlotFigure)

        self.figure.obsids_x_position = deepcopy(
            self.obsids_x_position
        )  # Needed for interactive waterlevel.
        self.figure.waterlevel_lineplot = None  # Needed for interactive waterlevel.
        self.figure.df = None  # Needed for interactive waterlevel.
        self.figure.plot_handles = []  # Needed for updating of legend.
        self.figure.line_layer = (
            self.line_layer
        )  # Needed for flash_section_line_position.
        self.figure.line_feature = (
            self.line_feature
        )  # Needed for flash_section_line_position.
        self.figure.obsid_annotation = deepcopy(
            self.obsid_annotation
        )  # Needed for interactive waterlevel.

        # Storing figures for detached figures to not be garbage collected.
        self.figures[self.figure.number] = self.figure

        if self.interactive_groupbox.isChecked():
            self.gridspec = GridSpec(nrows=2, ncols=2, height_ratios=[20, 1])
        else:
            self.gridspec = GridSpec(nrows=1, ncols=1)

        self.figure.ax_main = self.figure.add_subplot(self.gridspec[0:2, 0:1])
        canvas = FigureCanvas(self.figure)

        mpltoolbar = NavigationToolbar(canvas, self.widget_plot)

        try:
            matplotlib_replacements.replace_matplotlib_backends_backend_qt5agg_NavigationToolbar2QT_set_message_xylimits(
                mpltoolbar
            )
        except Exception as e:
            common_utils.MessagebarAndLog.info(
                log_msg=QCoreApplication.translate(
                    "SectionPlot", "Could not alter NavigationToolbar, msg: %s"
                )
                % str(e)
            )

        self.layoutplot.addWidget(canvas)
        self.layoutplot.addWidget(mpltoolbar)

        common_utils.PickAnnotator(self.figure)
        self.figure.detach_figure_button = DetachFigureButton(
            self.figure, callback=self.detach_figure
        )
        self.figure.reverse_section_button = ReverseSectionButton(self.figure)

    # ----- Methods used by the gui -----
    def detach_figure(self, button):
        log.debug("Detach pressed")
        self.layoutplot.removeWidget(self.figure.canvas.toolbar)
        self.layoutplot.removeWidget(self.figure.canvas)

        self.figure.canvas.toolbar.close()
        self.figure.canvas.close()
        fig = self.figure

        button._detach_button()
        self.attach_signals(self.figure)
        self.figure = None

        window_title = []
        window_title.extend(
            [
                getattr(fig, attr, None)
                for attr in ["figname", "tem_cbar_label"]
                if getattr(fig, attr, None)
            ]
        )
        window_title.extend(getattr(fig, "images_labels", []))

        if window_title:
            window_title = ", ".join(window_title)
            try:
                fig.canvas.manager.set_window_title(window_title)
            except AttributeError:
                e = traceback.format_exc()
                try:
                    fig.canvas.set_window_title(window_title)
                except AttributeError:
                    try:
                        fig.canvas.setWindowTitle(window_title)
                    except Exception:
                        log.debug(f"Error, {e}, followup:\n{traceback.format_exc()}")

    def resize_widget(self, parent):
        """
        :param parent:
        :param widget:
        :return:
        """
        parent.updateGeometry()
        parent.layout().setSizeConstraint(QtWidgets.QLayout.SetFixedSize)
        parent.adjustSize()

    def update_plot_size(self):
        if self.dynamic_plot_size.isChecked():
            self.widget_plot.setMinimumWidth(10)
            self.widget_plot.setMaximumWidth(16777215)
            self.widget_plot.setMinimumHeight(10)
            self.widget_plot.setMaximumHeight(16777215)
        else:
            width_inches, height_inches = self.figure.get_size_inches()
            screen_dpi = QApplication.screens()[0].logicalDotsPerInch()
            width_pixels = width_inches * screen_dpi
            height_pixels = height_inches * screen_dpi
            self.figure.canvas.setFixedSize(int(width_pixels), int(height_pixels))
            self.widget_plot.setFixedWidth(
                int(
                    max(
                        self.figure.canvas.size().width(),
                        self.figure.canvas.toolbar.size().width(),
                    )
                )
            )
            self.widget_plot.setFixedHeight(
                int(
                    self.figure.canvas.size().height()
                    + self.figure.canvas.toolbar.size().height() * 3
                )
            )

    def add_titlebar(self, widget):
        if widget.isWindow():
            widget.setWindowFlags(
                Qt.WindowType.Window
                | Qt.WindowType.WindowMinimizeButtonHint
                | Qt.WindowType.WindowMaximizeButtonHint
                | Qt.WindowType.WindowCloseButtonHint
            )
            widget.show()

    def float_settings(self):
        dockwidget = getattr(self, "settingsdock_widget")
        if dockwidget.isWindow():
            self.add_titlebar(dockwidget)
            dockwidget.setWindowTitle(
                QCoreApplication.translate("SectionPlot", "Sectionplot settings")
            )

            if self.tab_widget.count() > 1:
                self.tab_widget.removeTab(1)
        dockwidget.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)

    def dock_settings(self, _self, event):
        self.tab_widget.addTab(self.settings_tab, "Settings")
        self.old_settingsdock_widget = self.settingsdock_widget
        self.settingsdock_widget = QDockWidget()
        self.settingsdock_widget.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
        )
        self.settingsdock_widget.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum
        )
        self.settingsdock_widget.topLevelChanged.connect(
            lambda x: self.float_settings()
        )
        self.settingsdock_widget.closeEvent = types.MethodType(
            self.dock_settings, self.settingsdock_widget
        )
        self.settingsdock_widget.setWidget(self.dock_widget_contents_2)

        # Remove the old widget widgetitem from the old settingsdock_widget
        self.vertical_layout_4.takeAt(0)

        spacing = self.vertical_layout_4.takeAt(0)

        self.vertical_layout_4.addWidget(self.settingsdock_widget)
        self.vertical_layout_4.insertSpacerItem(-1, spacing)

        self.resize_widget(self.settingsdock_widget)
        tabwidget_resize(self.tab_widget)
        self.tab_widget.adjustSize()
        event.accept()

    def set_location(self):  # not ready
        self.ms.settingsdict["secplotlocation"] = self.parent.dockWidgetArea(self)

    # ----- Methods used by each figure instance as long as the figure is live -----
    def flash_section_line_position(self, event):
        if event.button.name.lower() != "right":
            return

        ax = event.inaxes
        if ax is None:
            return
        fig = ax.get_figure()

        if not all(
            [
                getattr(fig, "line_feature", None) is not None,
                event.button.name.lower() == "right",
            ]
        ):
            return

        axs = [
            getattr(fig, name, None)
            for name in ["ax_main", "ax_data_fit"]
            if getattr(fig, name, None) is not None
        ]
        if ax not in axs:
            return

        point = fig.line_feature.geometry().interpolate(event.xdata)
        self.iface.mapCanvas().flashGeometries([point], crs=fig.line_layer.crs())

    def update_animation(self, fig, datevalue):
        if fig.waterlevel_lineplot is not None and fig.df is not None:
            current_idx = slider_val_to_idx(fig.date_slider.val)
            x_wl, wl = self.get_water_levels_from_df(
                fig.df, current_idx, fig.obsids_x_position, fig
            )

            fig.waterlevel_lineplot.set_ydata(wl)
            try:
                fig.axvline.set_xdata(df_idx_as_datetime(fig.df, current_idx))
            except RuntimeError:
                # Change in Matplotlib to only accept a sequence for Line2D.set_xdata.
                fig.axvline.set_xdata([df_idx_as_datetime(fig.df, current_idx)])
            fig.waterlevel_lineplot.set_label(
                longdateformat(df_idx_as_datetime(fig.df, current_idx))
            )
            fig.canvas.draw_idle()

    def update_slider(self, event):
        fig = event.canvas.figure

        wlvl_axes = fig.ax_wlvl
        xmin, xmax = wlvl_axes.get_xlim()
        # For some reason, matplotlib gives me days from 1970 instead of from 1900.
        _1970 = mdates.date2num(datetime.date(1970, 1, 1))
        xmin_1970 = _1970 + int(round(xmin, 0))
        xmax_1970 = _1970 + int(round(xmax, 0))

        min_date = mdates.num2date(xmin_1970).replace(tzinfo=None)
        max_date = mdates.num2date(xmax_1970).replace(tzinfo=None)
        min_idx = fig.df.index.get_indexer([min_date], method="backfill")
        max_idx = fig.df.index.get_indexer([max_date], method="pad")

        date_slider = fig.date_slider
        prev_val = date_slider.val
        date_slider.valmin = min_idx
        date_slider.valmax = max_idx
        if prev_val > max_idx:
            newval = max_idx
        elif prev_val < min_idx:
            newval = min_idx
        else:
            newval = prev_val
        date_slider.valinit = newval
        date_slider.reset()
        fig.ax_slider.set_xlim(left=min_idx, right=max_idx)

    def update_legend(self, from_navbar=True, fig=None):
        if self.ms.settingsdict["secplotlegendplotted"]:  # Include legend in plot
            if fig is None:
                fig = self.figure
            if getattr(fig, "ax_data_fit", None) is not None:
                leg_ax = fig.ax_data_fit
            else:
                leg_ax = fig.ax_main
            legend_manager = SectionPlotLegendManager.from_template(
                self.secplot_templates.loaded_template
            )
            legend_manager.rebuild(leg_ax, fig.plot_handles)

    def update_barwidths_from_plot(self, event):
        if not self.width_of_plot.isChecked():
            return

        try:
            ax = event.canvas.figure.ax_main
        except AttributeError:
            ax = event
        used_xmin, used_xmax = ax.get_xlim()
        total_width = float(used_xmax) - float(used_xmin)
        barwidth = total_width * float(self.ms.settingsdict["secplotbw"]) * 0.01
        for p in ax.containers:
            if isinstance(p, container.BarContainer):
                children = p.get_children()
                for child in children:
                    if isinstance(child, patches.Rectangle):
                        prev_middle = child.get_x() + child.get_width() / 2
                        child.set_width(barwidth)
                        child.set_x(prev_middle - child.get_width() / 2)

        for a in ax.findobj(
            lambda artist: (
                isinstance(artist, mpl.text.Text) and hasattr(artist, "original_xy")
            )
        ):
            if self.ms.settingsdict["secplotlayertextalignment"] == "center":
                x = a.original_xy[0]
            else:
                x = a.original_xy[0] + (barwidth / 2)
            a.xy = (x, a.original_xy[1])

    def get_water_levels_from_df(self, df, idx, obsids_x_position, fig):
        x_wl, wl, new_annotations = _get_water_levels_from_df(
            df=df,
            idx=idx,
            obsids_x_position=obsids_x_position,
            obsid_annotation=fig.obsid_annotation,
            settingsdict=self.ms.settingsdict,
        )
        fig.obsid_annotation.update(new_annotations)
        return x_wl, wl

    # ----- Tools used during creation of a new figure -----
    def waterlevel_lineplot(self, x_wl, wl, level_date, interactive_line=False):
        plotlable = get_plot_label_name(
            level_date, self.water_level_labels_duplicate_check
        )
        self.water_level_labels_duplicate_check.append(plotlable)
        settings = self.secplot_templates.loaded_template["wlevels_Axes_plot"].get(
            plotlable,
            self.secplot_templates.loaded_template["wlevels_Axes_plot"]["DEFAULT"],
        )
        self.secplot_templates.loaded_template["wlevels_Axes_plot"][plotlable] = (
            copy.deepcopy(settings)
        )
        settings = self.secplot_templates.loaded_template["wlevels_Axes_plot"][
            plotlable
        ]
        settings["label"] = settings.get("label", plotlable)
        settings["picker"] = 2
        lineplot = self.figure.ax_main.plot(x_wl, wl, **settings)[0]
        if interactive_line:
            self.figure.waterlevel_lineplot = lineplot
        self.figure.plot_handles.append(lineplot)

    def upload_qgis_vector_layer(self, line_layer, line_feature):
        """Upload a selected line feature into a temporary DB table."""
        srid = line_layer.crs().postgisSrid()
        self.temptable_name = self.dbconnection.create_temporary_table_for_import(
            self.temptable_name, ["dummyfield TEXT"], ["geometry", "LINESTRING", srid]
        )

        geom = line_feature.geometry()
        try:
            geom_linestring = geom.convertToType(1)
        except TypeError:
            # Adjustment for QGIS > 3.30
            geom_linestring = geom.convertToType(Qgis.GeometryType.Line)
        ph = self.dbconnection.placeholder()
        sql = self.dbconnection.sql_ident(
            f"INSERT INTO {{t}} (dummyfield, geometry) VALUES ('0', ST_GeomFromText({ph}, {ph}))",
            t=self.temptable_name,
        )
        self.dbconnection.execute(sql, all_args=[(geom_linestring.asWkt(), srid)])

    def plot_water_level_interactive(self):
        placeholders = self.dbconnection.placeholders(len(self.obsids_x_position))
        sql = self.dbconnection.sql_ident(
            f"SELECT date_time, level_masl, obsid FROM {{t}} WHERE obsid IN ({placeholders})",
            t=self.ms.settingsdict["secplotwlvltab"],
        )
        df = pd.read_sql(
            sql,
            self.dbconnection.conn,
            index_col="date_time",
            coerce_float=True,
            params=tuple(self.obsids_x_position.keys()),
            parse_dates={"date_time": {"format": "mixed"}},
            columns=None,
            chunksize=None,
        )
        if df.empty:
            common_utils.MessagebarAndLog.info(
                log_msg=QCoreApplication.translate(
                    "SectionPlot",
                    "Interactive plot: No waterlevels found for chosen obsids in %s.",
                )
                % self.ms.settingsdict["secplotwlvltab"]
            )
            return
        if isinstance(df, pd.Series):
            df = df.to_frame()

        resample_kwargs = {"how": self.resample_how.text()}
        if self.resample_offset.text():
            if pd.__version__ < "1.1.0":
                resample_kwargs["base"] = int(self.resample_offset.text())
            else:
                resample_kwargs["offset"] = self.resample_offset.text()

        # First resample each obsid to overcome duplicate date_times
        df = resample(
            df.groupby(by=["obsid"]),
            "level_masl",
            self.resample_rule.text(),
            resample_kwargs,
        )
        df = df.apply(lambda x: x)

        # Then pivot and resample to get a complete date_time index without missing datetimes.
        df = df.reset_index()
        df = df.pivot(index="date_time", columns="obsid", values="level_masl")
        df = resample(df, None, self.resample_rule.text(), resample_kwargs)

        if self.skip_nan.isChecked():
            df = df.dropna()
        self.figure.df = df

        # The slider should update after user pan.
        valuemin = 0
        valuemax = len(df) - 1
        valinit = valuemin
        self.figure.ax_wlvl = self.figure.add_subplot(self.gridspec[0:1, 1:2])
        self.figure.ax_wlvl.midv_axes_name = "wlvl_axes"
        color_styles = set()
        linestyles = ["-", "--", "-.", ":"]
        df.plot(ax=self.figure.ax_wlvl, picker=2)
        for line in self.figure.ax_wlvl.lines:
            k = (line.get_color(), line.get_linestyle())

            for ls in linestyles:
                if k in color_styles:
                    k = (line.get_color(), ls)
                else:
                    line.set_color(k[0])
                    line.set_linestyle(k[1])
                    color_styles.add(k)
                    break
        self.figure.ax_wlvl.legend()

        self.figure.ax_wlvl.set_xlabel("")
        self.figure.ax_wlvl.set_ylabel("")

        for label in self.figure.ax_wlvl.yaxis.get_ticklabels():
            label.set_fontsize(
                **self.secplot_templates.loaded_template["ticklabels_Text_set_fontsize"]
            )

        for label in self.figure.ax_wlvl.xaxis.get_ticklabels():
            label.set_fontsize(
                **self.secplot_templates.loaded_template["ticklabels_Text_set_fontsize"]
            )

        self.figure.ax_slider = self.figure.add_subplot(self.gridspec[1:2, 1:2])
        self.figure.ax_slider.midv_axes_name = "sliderax"
        self.figure.date_slider = Slider(
            self.figure.ax_slider,
            "Date",
            valuemin,
            valuemax,
            valinit=valinit,
            valfmt="%1.0f",
        )

        self.figure.axvline = self.figure.ax_wlvl.axvline(
            df_idx_as_datetime(df, valinit), color="black", linewidth=2, linestyle="--"
        )

        current_idx = slider_val_to_idx(self.figure.date_slider.val)
        x_wl, wl = self.get_water_levels_from_df(
            df, current_idx, self.obsids_x_position, self.figure
        )
        self.waterlevel_lineplot(
            x_wl,
            wl,
            longdateformat(df_idx_as_datetime(df, current_idx)),
            interactive_line=True,
        )

    def attach_signals(self, fig):
        fig.canvas.mpl_connect("button_release_event", self.update_barwidths_from_plot)
        fig.canvas.mpl_connect("resize_event", self.update_barwidths_from_plot)
        fig.canvas.mpl_connect("button_release_event", self.flash_section_line_position)

        if getattr(fig, "date_slider", None) is not None:
            fig.canvas.mpl_connect("draw_event", self.update_slider)
            fig.date_slider.on_changed(partial(self.update_animation, fig))

        fig.update_legend_cid = fig.canvas.mpl_connect(
            "draw_event", lambda x: self.update_legend(True, fig)
        )

    @contextmanager
    def temporary_deactivate_update_legend(self, fig):
        """Currently the legend is updated after each draw, but it doesn't trigger draw itself.

        draw_idle probably doesn't work with the context manager as it exits the manager before draw is triggered
        reusling in a very slow gui as legend is redone over and over again."""
        fig.canvas.mpl_disconnect(fig.update_legend_cid)
        fig.update_legend_cid = None
        yield
        fig.update_legend_cid = fig.canvas.mpl_connect(
            "draw_event", lambda x: self.update_legend(True, fig)
        )


def resample(df, valuecol, rule, resample_kwargs):
    resample_kwargs = dict(resample_kwargs)
    how = resample_kwargs.get("how", "mean")
    del resample_kwargs["how"]
    df = df if valuecol is None else df[valuecol]
    df = getattr(df.resample(rule, **resample_kwargs), how)()
    return df


def groupby(df, indexcol, filters):
    df = df.reset_index()
    df = df.set_index(indexcol)
    if filters is not None:
        df = df.groupby(by=filters)
    return df


def longdateformat(adate):
    return adate.strftime("%Y-%m-%d %H:%M:%S")


def df_idx_as_datetime64(df, idx):
    return df.iloc[[idx]].index.values[0]


def df_idx_as_datetime(df, idx):
    return pd.to_datetime(str(df_idx_as_datetime64(df, idx)))


def nan_helper(y):
    """Helper to handle indices and logical indices of NaNs.

    from https://stackoverflow.com/questions/6518811/interpolate-nan-values-in-a-numpy-array

    Input:
        - y, 1d numpy array with possible NaNs
    Output:
        - nans, logical indices of NaNs
        - index, a function, with signature indices= index(logical_indices),
          to convert logical indices of NaNs to 'equivalent' indices
    Example:
    # linear interpolation of NaNs
    nans, x= nan_helper(y)
    y[nans]= np.interp(x(nans), x(~nans), y[~nans])
    """
    return np.isnan(y), lambda z: z.nonzero()[0]


def tabwidget_resize(tabwidget):
    current_index = tabwidget.currentIndex()
    for tabnr in range(tabwidget.count()):
        if tabnr != current_index:
            tabwidget.widget(tabnr).setSizePolicy(
                QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored
            )
    tab = tabwidget.currentWidget()
    tab.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
    tab.adjustSize()
