# -*- coding: utf-8 -*-
"""
/***************************************************************************
 Midvatten
                                 A QGIS plugin
A toolset that makes QGIS an interface for editing/viewing hydrogeological
observational data (drillings, water levels, seismic data etc) stored in a
SQLite or PostgreSQL database.
                             -------------------
        begin                : 2011-10-18
        copyright            : (C) 2026 by Midvatten
        email                : midvattenplugin@midvatten.se
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/

"""
import io
import os.path
import shutil
import traceback
from pathlib import Path

import qgis.utils
from qgis.PyQt.QtCore import QCoreApplication, QDir, QSettings, QUrl, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QApplication, QFileDialog, QMenu
from qgis.core import QgsApplication, QgsWkbTypes, QgsVectorLayer

import midvatten.midvsettingsdialog as midvsettingsdialog

from midvatten.definitions import midvatten_defs
from midvatten.tools.calculate_statistics import CalculateStatisticsGui
from midvatten.tools.column_values_from_selected_features import (
    ValuesFromSelectedFeaturesGui,
)
from midvatten.tools.create_db import NewDb
from midvatten.tools.custom_drillreport import DrillreportUi
from midvatten.tools.customplot import plotsqlitewindow
from midvatten.tools.drillreport import Drillreport
from midvatten.tools.export_data import ExportData
from midvatten.tools.export_fieldlogger import ExportToFieldLogger
from midvatten.tools.import_diveroffice import DiverofficeImport
from midvatten.tools.import_fieldlogger import FieldloggerImport
from midvatten.tools.import_general_csv_gui import GeneralCsvImportGui
from midvatten.tools.import_hobologger import HobologgerImport
from midvatten.tools.import_interlab4 import Interlab4Import
from midvatten.tools.import_levelogger import LeveloggerImport
from midvatten.tools.loaddefaultlayers import LoadLayers
from midvatten.tools.midvsettings import midvsettings
from midvatten.tools.piper import PiperPlot
from midvatten.tools.prepareforqgis2threejs import PrepareForQgis2Threejs
from midvatten.tools.sectionplot import SectionPlot
from midvatten.tools.strat_symbology import StratSymbology
from midvatten.tools.stratigraphy import Stratigraphy
from midvatten.tools.tsplot import TimeSeriesPlot
from midvatten.tools.utils import common_utils, db_utils, midvatten_utils
from midvatten.tools.utils import matplotlib_replacements
from midvatten.tools.utils.common_utils import returnunicode as ru
from midvatten.tools.utils.util_translate import getTranslate
from midvatten.tools.w_flow_calc_aveflow import CalculateAveflow
from midvatten.tools.calculate_level import CalculateLevel
from midvatten.tools.loggereditor import LoggerEditor
from midvatten.tools.wqualreport import Wqualreport
from midvatten.tools.wqualreport_compact import CompactWqualReportUi
from midvatten.tools.xyplot import XYPlot


class Midvatten:
    def __init__(self, iface):
        matplotlib_replacements.perform_all_replacements()
        self.iface = iface
        # initialize plugin directory
        self.plugin_dir = Path(os.path.dirname(__file__))

        self.ms = midvsettings()
        self.translator = getTranslate("midvatten")
        self.actions = []

        # Check if plugin was started the first time in current QGIS session
        # Must be set in initGui() to survive plugin reloads
        self.first_start = None

    def tr(self, message: str) -> str:
        """Get the translation for a string using Qt translation API.

        We implement this ourselves since we do not inherit QObject.

        :param message: String for translation.
        :type message: str, QString

        :returns: Translated version of message.
        :rtype: QString
        """
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate("Midvatten", message)

    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=False,
        add_to_toolbar=False,
        status_tip=None,
        whats_this=None,
        parent=None,
    ):
        """Add a toolbar icon to the toolbar.

        :param icon_path: Path to the icon for this action. Can be a resource
            path (e.g. ':/plugins/foo/bar.png') or a normal file system path.
        :type icon_path: str

        :param text: Text that should be shown in menu items for this action.
        :type text: str

        :param callback: Function to be called when the action is triggered.
        :type callback: function

        :param enabled_flag: A flag indicating if the action should be enabled
            by default. Defaults to True.
        :type enabled_flag: bool

        :param add_to_menu: Flag indicating whether the action should also
            be added to the menu. Defaults to True.
        :type add_to_menu: bool

        :param add_to_toolbar: Flag indicating whether the action should also
            be added to the toolbar. Defaults to True.
        :type add_to_toolbar: bool

        :param status_tip: Optional text to show in a popup when mouse pointer
            hovers over the action.
        :type status_tip: str

        :param parent: Parent widget for the new action. Defaults None.
        :type parent: QWidget

        :param whats_this: Optional text to show in the status bar when the
            mouse pointer hovers over the action.

        :returns: The action that was created. Note that the action is also
            added to self.actions list.
        :rtype: QAction
        """
        icon_path = Path(os.path.dirname(__file__)) / "icons" / icon_path

        icon = QIcon(str(icon_path))
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if parent is None:
            parent = self.iface.mainWindow()

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            # Adds plugin icon to Plugins toolbar
            self.iface.addToolBarIcon(action)

        if add_to_menu:
            self.iface.addPluginToMenu(self.menu, action)

        self.actions.append(action)

        return action

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""

        # Check if the menu exists and get it
        for child in self.iface.mainWindow().menuBar().children():
            if isinstance(child, QMenu):
                if child.title() == "Midvatten":
                    self.menu = child
                    self.owns_midv_menu = False
                    break
        else:
            self.menu = QMenu("Midvatten", self.iface.mainWindow().menuBar())
            self.iface.mainWindow().menuBar().addMenu(self.menu)
            # Indicator that this plugin must not clean up the midvatten menu
            self.owns_midv_menu = True

        self.action_new_db = self.add_action(
            "create_new.xpm",
            text=self.tr("Create a new Midvatten project database"),
            callback=lambda x: self.new_db(),
        )

        self.action_new_pgdb = self.add_action(
            "create_new.xpm",
            text=self.tr(
                "Make selected PostgreSQL database into a Midvatten " "project database"
            ),
            callback=lambda x: self.new_postgis_db(),
        )

        self.action_load_layers = self.add_action(
            "loaddefaultlayers.png",
            text=self.tr("Load default db-layers to qgis"),
            callback=lambda x: self.add_midvatten_layers(),
            whats_this=self.tr("Load default layers from the selected database"),
        )

        self.action_midvatten_settings = self.add_action(
            "MidvSettings.png",
            text=self.tr("Midvatten Settings"),
            callback=lambda x: self.setup(),
            whats_this=self.tr("Configuration for Midvatten toolset"),
        )
        self.iface.registerMainWindowAction(self.action_midvatten_settings, "F6")

        self.action_reset_settings = self.add_action(
            "ResetSettings.png",
            text=self.tr("Reset settings"),
            callback=lambda x: self.reset_settings(),
        )

        self.action_about = self.add_action(
            "about.png",
            text=self.tr("About"),
            callback=lambda x: self.about(),
        )

        self.action_wlvlcalculate = self.add_action(
            "calc_level_masl.png",
            text=self.tr("Calculate w level from manual measurements"),
            callback=lambda x: self.wlvlcalculate(),
        )

        self.action_aveflowcalculate = self.add_action(
            "import_wflow.png",
            text=self.tr("Calculate Aveflow from Accvol"),
            callback=lambda x: self.calculate_aveflow(),
        )

        self.action_import_diverofficedata = self.add_action(
            "load_wlevels_logger.png",
            text=self.tr("Import logger data using Diver-Office csv-format"),
            callback=lambda x: self.import_diverofficedata(),
        )

        self.action_import_leveloggerdata = self.add_action(
            "load_wlevels_logger.png",
            text=self.tr("Import logger data using Levelogger csv-format"),
            callback=lambda x: self.import_leveloggerdata(),
        )

        self.action_import_hobologgerdata = self.add_action(
            "load_wlevels_logger.png",
            text=self.tr("Import logger data using HOBO logger csv-format"),
            callback=lambda x: self.import_hobologgerdata(),
        )

        self.action_wlvlloggcalibrate = self.add_action(
            "calibr_level_logger_masl.png",
            text=self.tr("Edit water level logger data"),
            callback=lambda x: self.wlvlloggcalibrate(),
        )

        self.actionimport_wqual_lab_from_interlab4 = self.add_action(
            "import_wqual_lab.png",
            text=self.tr("Import w quality from lab data using interlab4 format"),
            callback=lambda x: self.import_wqual_lab_from_interlab4(),
        )

        self.actionimport_fieldlogger = self.add_action(
            "import_wqual_field.png",
            text=self.tr("Import data using FieldLogger format"),
            callback=lambda x: self.import_fieldlogger(),
        )

        self.actiongeneral_import_csv = self.add_action(
            "import_wqual_field.png",
            text=self.tr("Import data using general csv format"),
            callback=lambda x: self.import_csv(),
        )

        self.action_tsplot = self.add_action(
            "PlotTS.png",
            text=self.tr("Time series plot"),
            callback=lambda x: self.plot_timeseries(),
        )

        self.action_xyplot = self.add_action(
            "PlotXY.png",
            text=self.tr("Scatter plot"),
            callback=lambda x: self.plot_xy(),
            whats_this=self.tr(
                "Plot XY scatter data (e.g. seismic profile) for selected objects",
            ),
        )

        self.action_piper2 = self.add_action(
            "Piper.png",
            text=self.tr("Piper diagram"),
            callback=lambda x: self.plot_piper2(),
            whats_this=self.tr("Plot a Piper diagram for selected objects"),
        )

        self.action_customplot = self.add_action(
            "plotsqliteicon.png",
            text=self.tr("Custom plots"),
            callback=lambda x: self.plot_sqlite(),
            whats_this=self.tr("Create custom plots for reports"),
        )

        self.action_stratigraphyplot = self.add_action(
            "PlotStratigraphy.png",
            text=self.tr("Stratigraphy plot"),
            callback=lambda x: self.plot_stratigraphy(),
            whats_this=self.tr("Show stratigraphy for selected objects"),
        )

        self.action_drillreport = self.add_action(
            "drill_report.png",
            text=self.tr("General drill report"),
            callback=lambda x: self.drillreport(),
            whats_this=self.tr("Show a general drill report for selected objects"),
        )

        self.action_custom_drillreport = self.add_action(
            "drill_report.png",
            text=self.tr("Custom drill report"),
            callback=lambda x: self.custom_drillreport(),
            whats_this=self.tr("Create drill report tables for reports"),
        )

        self.action_wqualreport = self.add_action(
            "wqualreport.png",
            text=self.tr("Water quality table"),
            callback=lambda x: self.waterqualityreport(),
            whats_this=self.tr("Show water quality for selected objects"),
        )

        self.action_compactwqualreport = self.add_action(
            "wqualreport.png",
            text=self.tr("Compact water quality reports"),
            callback=lambda x: self.waterqualityreportcompact(),
            whats_this=self.tr("Create water quality tables for reports"),
        )

        self.action_sectionplot = self.add_action(
            "PlotSection.png",
            text=self.tr("Section plot"),
            callback=lambda x: self.plot_section(),
            whats_this=self.tr("Plot a section with stratigraphy and water levels"),
        )

        self.action_load_qgis2threejs_layers = self.add_action(
            "qgis2threejs.png",
            text=self.tr("Prepare 3D-data for Qgis2threejs plugin"),
            callback=lambda x: self.prepare_layers_for_qgis2threejs(),
            whats_this=self.tr(
                "Add spatialite views to be used by Qgis2threejs plugin to create a 3D plot"
            ),
        )

        self.action_load_data_domains = self.add_action(
            "loaddatadomains.png",
            text=self.tr("Load data domain tables to qgis"),
            callback=lambda x: self.load_data_domains(),
            whats_this=self.tr("Load the data domain (zz-) tables from the database"),
        )

        self.action_load_data_tables = self.add_action(
            "loaddatadomains.png",
            text=self.tr("Load data tables to qgis"),
            callback=lambda x: self.load_data_tables(),
            whats_this=self.tr("Load the remaining data tables from the database"),
        )

        self.action_stratsymbology = self.add_action(
            "stratsymbology.png",
            text=self.tr("Load stratigraphy symbology to qgis"),
            callback=lambda x: self.load_strat_symbology(),
            whats_this=self.tr("Load stratigraphy symbology to QGIS"),
        )

        self.action_vacuum_db = self.add_action(
            "vacuum.png",
            text=self.tr("Vacuum the database"),
            callback=lambda x: self.vacuum_db(),
            whats_this=self.tr("Perform database vacuuming"),
        )

        self.action_backup_db = self.add_action(
            "zip.png",
            text=self.tr("Backup the database"),
            callback=lambda x: self.zip_db(),
            whats_this=self.tr(
                "A compressed copy of the (SQLite) database will be "
                "placed in same directory as the db"
            ),
        )

        self.action_export_csv = self.add_action(
            "export_csv.png",
            text=self.tr("Export to a set of csv files"),
            callback=lambda x: self.export_csv,
            whats_this=self.tr(
                "All data for the selected objects (obs_points and obs_lines) will be "
                "exported to a set of csv files"
            ),
        )

        self.action_export_spatialite = self.add_action(
            "export_spatialite.png",
            text=self.tr("Export to another spatialite database"),
            callback=lambda x: self.export_spatialite(),
            whats_this=self.tr(
                "All data for the selected objects (obs_points and "
                "obs_lines) will be exported to another spatialite db"
            ),
        )

        self.action_export_fieldlogger = self.add_action(
            "export_csv.png",
            text=self.tr("Export to FieldLogger or FieldForm format"),
            callback=lambda x: self.export_fieldlogger(),
        )

        self.action_calculate_db_table_rows = self.add_action(
            "calc_statistics.png",
            text=self.tr("Calculate database table row"),
            callback=lambda x: self.calculate_db_table_rows(),
            whats_this=self.tr(
                "Counts the number of rows for all tables in the " "database"
            ),
        )

        self.action_list_selected_features = self.add_action(
            "listofvalues.png",
            text=self.tr("List of values from selected features"),
            callback=lambda x: self.list_of_values_from_selected_features(),
            whats_this=self.tr(
                "Writes a concatted list of values from selected "
                "column from selected features to log and clipboard. "
                "The list could be used in other layer filters or "
                "selections."
            ),
        )

        self.action_non_essential_tables = self.add_action(
            "create_new.png",
            text=self.tr("Add non-essential data tables"),
            callback=lambda x: self.add_non_essential_tables(),
            whats_this=self.tr(
                "Add extra tables to the database:"
                "\nw_qual_logger to store water quality logger data,"
                "\ns_qual_lab to store soil quality data,"
                "\nspatial_history to store history of obs_points "
                "altitude and spatial (h_*-columns, east and north) "
                "values."
            ),
        )

        # Add toolbar with buttons
        self.toolBar = self.iface.addToolBar("Midvatten")
        self.toolBar.setObjectName("Midvatten")
        self.toolBar.addAction(self.action_midvatten_settings)
        self.toolBar.addAction(self.action_tsplot)
        self.toolBar.addAction(self.action_xyplot)
        self.toolBar.addAction(self.action_stratigraphyplot)
        self.toolBar.addAction(self.action_sectionplot)
        self.toolBar.addAction(self.action_customplot)
        self.toolBar.addAction(self.action_piper2)
        self.toolBar.addAction(self.action_drillreport)
        self.toolBar.addAction(self.action_wqualreport)
        self.toolBar.addAction(self.action_stratsymbology)
        self.toolBar.addAction(self.action_list_selected_features)

        self.menu.import_data_menu = self.add_menu(
            self.tr("&Import data to database"), self.menu
        )

        self.menu.import_data_menu.addAction(self.actiongeneral_import_csv)
        self.menu.import_data_menu.addAction(self.action_import_diverofficedata)
        self.menu.import_data_menu.addAction(self.action_import_leveloggerdata)
        self.menu.import_data_menu.addAction(self.action_import_hobologgerdata)
        self.menu.import_data_menu.addAction(self.actionimport_wqual_lab_from_interlab4)
        self.menu.import_data_menu.addAction(self.actionimport_fieldlogger)

        self.menu.export_data_menu = self.add_menu(
            self.tr("&Export data from database"), self.menu
        )
        self.menu.export_data_menu.addAction(self.action_export_csv)
        self.menu.export_data_menu.addAction(self.action_export_spatialite)
        self.menu.export_data_menu.addAction(self.action_export_fieldlogger)

        self.menu.edit_data_menu = self.add_menu(
            self.tr("&Edit data in database"), self.menu
        )
        self.menu.edit_data_menu.addAction(self.action_wlvlcalculate)
        self.menu.edit_data_menu.addAction(self.action_wlvlloggcalibrate)
        # self.menu.add_data_menu.addAction(self.actionupdatecoord)
        # self.menu.add_data_menu.addAction(self.actionupdateposition)
        self.menu.edit_data_menu.addAction(self.action_aveflowcalculate)

        self.menu.plot_data_menu = self.add_menu(self.tr("&Plots"), self.menu)
        self.menu.plot_data_menu.addAction(self.action_tsplot)
        self.menu.plot_data_menu.addAction(self.action_xyplot)
        self.menu.plot_data_menu.addAction(self.action_stratigraphyplot)
        self.menu.plot_data_menu.addAction(self.action_sectionplot)
        self.menu.plot_data_menu.addAction(self.action_customplot)
        self.menu.plot_data_menu.addAction(self.action_piper2)

        self.menu.report_menu = self.add_menu(self.tr("&Reports"), self.menu)
        self.menu.report_menu.addAction(self.action_drillreport)
        self.menu.report_menu.addAction(self.action_custom_drillreport)
        self.menu.report_menu.addAction(self.action_wqualreport)
        self.menu.report_menu.addAction(self.action_compactwqualreport)

        self.menu.db_manage_menu = self.add_menu(
            self.tr("&Database management"), self.menu
        )
        self.menu.db_manage_menu.addAction(self.action_new_db)
        self.menu.db_manage_menu.addAction(self.action_new_pgdb)
        self.menu.db_manage_menu.addAction(self.action_vacuum_db)
        self.menu.db_manage_menu.addAction(self.action_backup_db)
        self.menu.db_manage_menu.addAction(self.action_non_essential_tables)

        self.menu.utils = self.add_menu(self.tr("&Utilities"), self.menu)
        self.menu.utils.addAction(self.action_load_data_domains)
        self.menu.utils.addAction(self.action_load_data_tables)
        self.menu.utils.addAction(self.action_stratsymbology)
        self.menu.utils.addAction(self.action_load_qgis2threejs_layers)
        self.menu.utils.addAction(self.action_reset_settings)
        self.menu.utils.addAction(self.action_calculate_db_table_rows)
        self.menu.utils.addAction(self.action_list_selected_features)

        self.menu.addSeparator()

        self.menu.addAction(self.action_load_layers)
        self.menu.addAction(self.action_midvatten_settings)
        self.menu.addAction(self.action_about)

        # QGIS iface connections
        self.iface.projectRead.connect(self.project_opened)
        self.iface.newProjectCreated.connect(self.project_created)

        # Connect message log to logfile.
        # Log file name must be set as env. variable QGIS_LOG_FILE in
        # settings > options > system > environment.
        QgsApplication.messageLog().messageReceived.connect(
            common_utils.write_qgs_log_to_file
        )

    def add_menu(self, name, parent):
        menu = QMenu(name)
        parent.addMenu(menu)
        return menu

    def unload(self):
        try:
            self.menu.removeAction(self.action_load_layers)
            self.menu.removeAction(self.action_midvatten_settings)
            self.menu.removeAction(self.action_about)
        except:
            pass

        if self.owns_midv_menu:
            self.menu.parentWidget().removeAction(self.menu.menuAction())
            self.menu.deleteLater()

        for action in self.actions:
            try:
                self.iface.removeToolBarIcon(action)
            except:
                pass

        del self.toolBar

        # Also remove F key triggers
        self.iface.unregisterMainWindowAction(self.action_midvatten_settings)

    def about(self):
        getTranslate("midvatten")
        filename = self.plugin_dir / "metadata.txt"
        metadata = QSettings(str(filename), QSettings.IniFormat)
        verno = metadata.value("version")
        author = ", ".join(metadata.value("author"))
        email = metadata.value("email")
        homepage = metadata.value("homepage")

        template_file = self.plugin_dir / "templates" / "about_template.htm"
        out_folder = Path(QDir.tempPath()) / "midvatten_about"
        os.makedirs(out_folder, exist_ok=True)

        outname = out_folder / "about.htm"
        shutil.copy2(
            self.plugin_dir / "templates" / "midvatten_logga.png",
            out_folder / "midvatten_logga.png",
        )

        with io.open(str(template_file), "rt", encoding="cp1252") as infile:
            rows = [
                row.replace("VERSIONCHANGETHIS", verno)
                .replace("AUTHORCHANGETHIS", author)
                .replace("EMAILCHANGETHIS", email)
                .replace("HOMEPAGECHANGETHIS", homepage)
                for row in infile
            ]
        with io.open(str(outname), "w", encoding="cp1252") as outfile:
            outfile.write("\n".join(rows))
        dlg = common_utils.HtmlDialog(
            "About Midvatten plugin for QGIS", QUrl.fromLocalFile(str(outname))
        )
        dlg.exec_()

    @common_utils.general_exception_handler
    def calculate_aveflow(self):
        """
        Calculates Aveflow from Accvol
        """

        # First verify that required layers are not in edit mode and that there are
        # features selected
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            self.iface,
            self.ms,
            (
                "obs_points",
                "w_flow",
            ),
        )
        err_flag = common_utils.verify_layer_selection(err_flag, 0)
        if err_flag == 0:
            dlg = CalculateAveflow(self.iface.mainWindow())
            dlg.exec_()

    @common_utils.general_exception_handler
    def drillreport(self):
        allcritical_layers = (
            "obs_points",
            "w_levels",
            "w_qual_lab",
        )  # none of these layers must be in editing mode
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            self.iface, self.ms, allcritical_layers
        )  # verify midv settings are loaded and the critical layers are not in editing mode
        err_flag = common_utils.verify_layer_selection(
            err_flag, 0
        )  # verify the selected layer has attribute "obsid" and that exactly one feature is selected
        if err_flag == 0:
            obsids = common_utils.getselectedobjectnames(
                qgis.utils.iface.activeLayer()
            )  # selected obs_point is now found in obsid[0]
            Drillreport(obsids, self.ms.settingsdict)

    @common_utils.general_exception_handler
    def custom_drillreport(self):
        allcritical_layers = (
            "obs_points",
            "w_levels",
            "w_qual_lab",
        )  # none of these layers must be in editing mode
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            self.iface, self.ms, allcritical_layers
        )  # verify midv settings are loaded and the critical layers are not in editing mode
        if err_flag == 0:
            DrillreportUi(self.iface.mainWindow(), self.ms)

    @common_utils.general_exception_handler
    def export_csv(self):
        # None of these layers must be in editing mode
        allcritical_layers = tuple(
            midvatten_defs.get_subset_of_tables_fr_db("obs_points")
            + midvatten_defs.get_subset_of_tables_fr_db("obs_lines")
            + midvatten_defs.get_subset_of_tables_fr_db("data_domains")
            + midvatten_defs.get_subset_of_tables_fr_db("default_layers")
            + midvatten_defs.get_subset_of_tables_fr_db("default_nonspatlayers")
            + midvatten_defs.get_subset_of_tables_fr_db("interlab4_import_table")
            + midvatten_defs.get_subset_of_tables_fr_db("extra_data_tables")
        )

        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            self.iface, self.ms, allcritical_layers
        )  # verify midv settings are loaded and the critical layers are not in editing mode

        if err_flag == 0:
            common_utils.start_waiting_cursor()  # show the user this may take a long time...

            # Get two lists (OBSID_P and OBSID_L) with selected obs_points and obs_lines
            OBSID_P = common_utils.get_selected_features_as_tuple("obs_points")
            OBSID_L = common_utils.get_selected_features_as_tuple("obs_lines")

            # sanity = midvatten_utils.Askuser("YesNo", ru(QCoreApplication.translate("Midvatten", """You are about to export data for the selected obs_points and obs_lines into a set of csv files. \n\nContinue?""")), ru(QCoreApplication.translate("Midvatten", 'Are you sure?')))
            # exportfolder =    QtWidgets.QFileDialog.getExistingDirectory(None, 'Select a folder:', 'C:\\', QtWidgets.QFileDialog.ShowDirsOnly)
            common_utils.stop_waiting_cursor()
            exportfolder = QFileDialog.getExistingDirectory(
                None,
                ru(
                    QCoreApplication.translate(
                        "Midvatten",
                        "Select a folder where the csv files will be created:",
                    )
                ),
                ".",
                QFileDialog.ShowDirsOnly,
            )
            common_utils.start_waiting_cursor()
            if len(exportfolder) > 0:
                exportinstance = ExportData(OBSID_P, OBSID_L)
                exportinstance.export_2_csv(exportfolder)

            common_utils.stop_waiting_cursor()

    @common_utils.general_exception_handler
    def export_spatialite(self):
        # , *args, **kwargs
        # print("export args: '{}' kwargs: '{}' ".format(str(args), str(kwargs)))

        allcritical_layers = tuple(
            midvatten_defs.get_subset_of_tables_fr_db("obs_points")
            + midvatten_defs.get_subset_of_tables_fr_db("obs_lines")
            + midvatten_defs.get_subset_of_tables_fr_db("data_domains")
            + midvatten_defs.get_subset_of_tables_fr_db("default_layers")
            + midvatten_defs.get_subset_of_tables_fr_db("default_nonspatlayers")
        )  # none of these layers must be in editing mode
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            self.iface, self.ms, allcritical_layers
        )  # verify midv settings are loaded and the critical layers are not in editing mode

        if err_flag == 0:
            common_utils.start_waiting_cursor()  # show the user this may take a long time..

            # Get two lists (OBSID_P and OBSID_L) with selected obs_points and obs_lines
            OBSID_P = common_utils.get_selected_features_as_tuple("obs_points")
            OBSID_L = common_utils.get_selected_features_as_tuple("obs_lines")
            try:
                print(str(OBSID_P))
                print(str(OBSID_L))
            except:
                pass
            common_utils.stop_waiting_cursor()

            selected_all = (
                ru(QCoreApplication.translate("Midvatten", "selected"))
                if any([OBSID_P, OBSID_L])
                else ru(QCoreApplication.translate("Midvatten", "all"))
            )

            sanity = common_utils.Askuser(
                "YesNo",
                ru(
                    QCoreApplication.translate(
                        "Midvatten",
                        """This will create a new empty Midvatten DB with predefined design\nand fill the database with data from %s obs_points and obs_lines.\n\nContinue?""",
                    )
                )
                % (selected_all),
                ru(QCoreApplication.translate("Midvatten", "Are you sure?")),
            )
            if sanity.result == 1:
                common_utils.start_waiting_cursor()  # show the user this may take a long time...
                source_srid = db_utils.sql_load_fr_db(
                    """SELECT srid FROM geometry_columns WHERE f_table_name = 'obs_points';"""
                )[1][0][0]
                w_levels_logger_timezone = db_utils.get_timezone_from_db(
                    "w_levels_logger"
                )
                w_levels_timezone = db_utils.get_timezone_from_db("w_levels")
                # Let the user chose an EPSG-code for the exported database
                common_utils.stop_waiting_cursor()
                user_chosen_EPSG_code = common_utils.ask_for_export_crs(source_srid)
                common_utils.start_waiting_cursor()

                if not user_chosen_EPSG_code:
                    common_utils.stop_waiting_cursor()
                    return None

                filenamepath = os.path.join(os.path.dirname(__file__), "metadata.txt")
                iniText = QSettings(filenamepath, QSettings.IniFormat)
                verno = str(iniText.value("version"))

                newdbinstance = NewDb()
                newdbinstance.create_new_spatialite_db(
                    verno,
                    user_select_CRS="n",
                    EPSG_code=user_chosen_EPSG_code,
                    delete_srids=False,
                    w_levels_logger_timezone=w_levels_logger_timezone,
                    w_levels_timezone=w_levels_timezone,
                )
                common_utils.start_waiting_cursor()
                if newdbinstance.db_settings:
                    new_dbpath = db_utils.get_spatialite_db_path_from_dbsettings_string(
                        newdbinstance.db_settings
                    )
                    if not new_dbpath:
                        common_utils.MessagebarAndLog.critical(
                            bar_msg=ru(
                                QCoreApplication.translate(
                                    "export_spatialite",
                                    "Export to spatialite failed, see log message panel",
                                )
                            ),
                            button=True,
                        )
                        common_utils.stop_waiting_cursor()
                        return
                    exportinstance = ExportData(OBSID_P, OBSID_L)
                    exportinstance.export_2_splite(new_dbpath, user_chosen_EPSG_code)

                common_utils.stop_waiting_cursor()

    @common_utils.general_exception_handler
    def export_fieldlogger(self):
        """
        Exports data to FieldLogger android app format
        :return: None
        """
        if hasattr(self, "export_to_field_logger"):
            try:
                self.export_to_field_logger.activateWindow()
            except:
                self.export_to_field_logger = ExportToFieldLogger(
                    self.iface.mainWindow(), self.ms
                )
        else:
            self.export_to_field_logger = ExportToFieldLogger(
                self.iface.mainWindow(), self.ms
            )

    @common_utils.general_exception_handler
    def import_fieldlogger(self):
        """
        Imports data from FieldLogger android app format.
        :return: Writes to db.
        """
        allcritical_layers = (
            "obs_points",
            "w_qual_field",
            "w_levels",
            "w_flow",
            "comments",
        )  # none of these layers must be in editing mode
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            self.iface, self.ms, allcritical_layers
        )  # verify midv settings are loaded and the critical layers are not in editing mode
        if err_flag == 0:
            if not (self.ms.settingsdict["database"] == ""):
                longmessage = ru(
                    QCoreApplication.translate(
                        "Midvatten",
                        "You are about to import water head data, water flow or water quality from FieldLogger format.",
                    )
                )
                sanity = common_utils.Askuser(
                    "YesNo",
                    ru(longmessage),
                    ru(QCoreApplication.translate("Midvatten", "Are you sure?")),
                )
                if sanity.result == 1:
                    importinstance = FieldloggerImport(self.iface.mainWindow(), self.ms)
                    importinstance.parse_observations_and_populate_gui()
                    if (
                        not importinstance.status == "True"
                        and not importinstance.status
                    ):
                        common_utils.MessagebarAndLog.warning(
                            bar_msg=QCoreApplication.translate(
                                "Midvatten", "Something failed during import"
                            )
                        )
                    else:
                        try:
                            self.midvsettingsdialog.clear_everything()
                            self.midvsettingsdialog.select_last_settings()
                        except:
                            pass
            else:
                common_utils.MessagebarAndLog.critical(
                    bar_msg=QCoreApplication.translate(
                        "Midvatten", "You have to select database first!"
                    )
                )
        common_utils.stop_waiting_cursor()

    @common_utils.general_exception_handler
    def import_csv(self):
        """
        Imports data from a csv file
        :return: Writes to db.
        """
        # Foreign key layers that should not be in edit mode
        allcritical_layers = (
            "obs_points",
            "obs_lines",
            "zz_flowtype",
        )
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            self.iface, self.ms, allcritical_layers
        )
        if err_flag == 0:
            if not (self.ms.settingsdict["database"] == ""):
                self.importinstance = GeneralCsvImportGui(
                    self.iface.mainWindow(), self.ms
                )
                self.importinstance.load_gui()
                self.importinstance.destroyed.connect(
                    lambda: self._del_dialog("importinstance")
                )
            else:
                common_utils.MessagebarAndLog.critical(
                    bar_msg=QCoreApplication.translate(
                        "Midvatten", "You have to select database first!"
                    )
                )
        common_utils.stop_waiting_cursor()

    @common_utils.general_exception_handler
    def import_wqual_lab_from_interlab4(self):
        allcritical_layers = (
            "obs_points",
            "w_qual_lab",
        )  # none of these layers must be in editing mode
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            self.iface, self.ms, allcritical_layers
        )  # verify midv settings are loaded and the critical layers are not in editing mode
        if err_flag == 0:  # unless none of the critical layers are in editing mode
            sanity = common_utils.Askuser(
                "YesNo",
                ru(
                    QCoreApplication.translate(
                        "Midvatten",
                        """You are about to import water quality data from laboratory analysis, from a textfile using interlab4 format.\nSpecifications http://www.svensktvatten.se/globalassets/dricksvatten/riskanalys-och-provtagning/interlab-4-0.pdf\n\nContinue?""",
                    )
                ),
                ru(QCoreApplication.translate("Midvatten", "Are you sure?")),
            )
            if sanity.result == 1:
                importinstance = Interlab4Import(self.iface.mainWindow(), self.ms)
                importinstance.init_gui()
                if importinstance.status == "True":  #
                    common_utils.MessagebarAndLog.info(
                        bar_msg=ru(
                            QCoreApplication.translate(
                                "Midvatten",
                                "%s water quality parameters were imported to the database",
                            )
                        )
                        % str(importinstance.recsafter - importinstance.recsbefore)
                    )
                    try:
                        self.midvsettingsdialog.clear_everything()
                        self.midvsettingsdialog.select_last_settings()
                    except:
                        pass

    @common_utils.general_exception_handler
    def import_diverofficedata(self):
        allcritical_layers = (
            "obs_points",
            "w_levels_logger",
        )  # none of these layers must be in editing mode
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            self.iface, self.ms, allcritical_layers
        )  # verify midv settings are loaded and the critical layers are not in editing mode
        if err_flag == 0:
            if not (self.ms.settingsdict["database"] == ""):
                longmessage = ru(
                    QCoreApplication.translate(
                        "Midvatten",
                        """You are about to import water head data, recorded with a Level Logger (e.g. Diver).\n"""
                        """Data is supposed to be imported from a diveroffice file and obsid will be read from the attribute 'Location'.\n"""
                        """The data is supposed to be semicolon or comma separated.\n"""
                        """The header for the data should have column Date/time and at least one of the columns:\n"""
                        """Water head[cm], Temperature[°C], Level[cm], Conductivity[mS/cm], 1:Conductivity[mS/cm], 2:Spec.cond.[mS/cm].\n\n"""
                        """The column order is unimportant but the column names are.\n"""
                        """The data columns must be real numbers with point (.) or comma (,) as decimal separator and no separator for thousands.\n"""
                        """The charset is usually cp1252!\n\n"""
                        """Continue?""",
                    )
                )
                sanity = common_utils.Askuser(
                    "YesNo",
                    ru(longmessage),
                    ru(QCoreApplication.translate("Midvatten", "Are you sure?")),
                )
                if sanity.result == 1:
                    importinstance = DiverofficeImport(self.iface.mainWindow(), self.ms)
            else:
                common_utils.MessagebarAndLog.critical(
                    bar_msg=QCoreApplication.translate(
                        "Midvatten", "You have to select database first!"
                    )
                )
        common_utils.stop_waiting_cursor()

    @common_utils.general_exception_handler
    def import_leveloggerdata(self):
        allcritical_layers = (
            "obs_points",
            "w_levels_logger",
        )  # none of these layers must be in editing mode
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            self.iface, self.ms, allcritical_layers
        )  # verify midv settings are loaded and the critical layers are not in editing mode
        if err_flag == 0:
            if not (self.ms.settingsdict["database"] == ""):
                longmessage = ru(
                    QCoreApplication.translate(
                        "Midvatten",
                        """You are about to import water head data, recorded with a Levelogger.\n"""
                        """Data is supposed to be imported from a csv file exported from the levelogger data wizard and obsid will be read from the attribute 'Location'.\n"""
                        """The data is supposed to be semicolon or comma separated.\n"""
                        """The header for the data should have column Date, Time and at least one of the columns:\n"""
                        """LEVEL, TEMPERATURE, spec. conductivity (uS/cm), spec. conductivity (mS/cm).\n\n"""
                        """The unit for LEVEL must be cm or m and the unit must be given as the "UNIT: " argument one row after "LEVEL" argument.\n"""
                        """The unit for spec. conductivity is read from the spec. conductivity column head and must be mS/cm or uS/cm.\n"""
                        """The column order is unimportant but the column names are.\n"""
                        """The data columns must be real numbers with point (.) or comma (,) as decimal separator and no separator for thousands.\n"""
                        """The charset is usually cp1252!\n\n"""
                        """Continue?""",
                    )
                )
                sanity = common_utils.Askuser(
                    "YesNo",
                    ru(longmessage),
                    ru(QCoreApplication.translate("Midvatten", "Are you sure?")),
                )
                if sanity.result == 1:
                    importinstance = LeveloggerImport(self.iface.mainWindow(), self.ms)

                    if not importinstance.status:
                        common_utils.MessagebarAndLog.warning(
                            bar_msg=QCoreApplication.translate(
                                "Midvatten", "Something failed during import"
                            )
                        )
                    else:
                        try:
                            self.midvsettingsdialog.clear_everything()
                            self.midvsettingsdialog.select_last_settings()
                        except:
                            pass
            else:
                common_utils.MessagebarAndLog.critical(
                    bar_msg=QCoreApplication.translate(
                        "Midvatten", "You have to select database first!"
                    )
                )
        common_utils.stop_waiting_cursor()

    @common_utils.general_exception_handler
    def import_hobologgerdata(self):
        allcritical_layers = (
            "obs_points",
            "w_levels_logger",
        )  # none of these layers must be in editing mode
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            self.iface, self.ms, allcritical_layers
        )  # verify midv settings are loaded and the critical layers are not in editing mode
        if err_flag == 0:
            if not (self.ms.settingsdict["database"] == ""):
                longmessage = ru(
                    QCoreApplication.translate(
                        "Midvatten",
                        """You are about to import water head data, recorded with a HOBO temperature logger.\n"""
                        """Data is supposed to be in utf-8 and using this format:\n"""
                        """"Plot Title: temp_aname"\n"""
                        """"#","Date Time, GMT+02:00","Temp, °C (LGR S/N: 1234, SEN S/N: 1234, LBL: obsid)",...\n"""
                        """1,07/19/18 11:00:00 fm,7.654,...\n"""
                        """The data columns must be real numbers with point (.) or comma (,) as decimal separator and no separator for thousands.\n"""
                        """The charset is usually utf8!\n\n"""
                        """Continue?""",
                    )
                )
                sanity = common_utils.Askuser(
                    "YesNo",
                    ru(longmessage),
                    ru(QCoreApplication.translate("Midvatten", "Are you sure?")),
                )
                if sanity.result == 1:
                    importinstance = HobologgerImport(self.iface.mainWindow(), self.ms)
                    importinstance.select_files_and_load_gui()

                    if not importinstance.status:
                        common_utils.MessagebarAndLog.warning(
                            bar_msg=QCoreApplication.translate(
                                "Midvatten", "Something failed during import"
                            )
                        )
                    else:
                        try:
                            self.midvsettingsdialog.clear_everything()
                            self.midvsettingsdialog.select_last_settings()
                        except:
                            pass
            else:
                common_utils.MessagebarAndLog.critical(
                    bar_msg=QCoreApplication.translate(
                        "Midvatten", "You have to select database first!"
                    )
                )
        common_utils.stop_waiting_cursor()

    @common_utils.general_exception_handler
    def load_data_domains(self):
        # utils.pop_up_info(msg='This feature is not yet implemented',title='Hold on...')
        # return
        common_utils.start_waiting_cursor()
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            qgis.utils.iface, self.ms
        )  # verify midv settings are loaded
        common_utils.MessagebarAndLog.info(
            log_msg=ru(
                QCoreApplication.translate(
                    "Midvatten", "load_data_domains err_flag: %s"
                )
            )
            % str(err_flag)
        )
        if err_flag == 0:
            LoadLayers(qgis.utils.iface, self.ms.settingsdict, "Midvatten_data_domains")
        common_utils.stop_waiting_cursor()

    @common_utils.general_exception_handler
    def load_data_tables(self):
        common_utils.start_waiting_cursor()
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            qgis.utils.iface, self.ms
        )  # verify midv settings are loaded
        common_utils.MessagebarAndLog.info(
            log_msg=ru(
                QCoreApplication.translate("Midvatten", "load_data_tables err_flag: %s")
            )
            % str(err_flag)
        )
        if err_flag == 0:
            LoadLayers(qgis.utils.iface, self.ms.settingsdict, "Midvatten_data_tables")
        common_utils.stop_waiting_cursor()

    @common_utils.general_exception_handler
    def load_strat_symbology(self):
        common_utils.start_waiting_cursor()
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            qgis.utils.iface, self.ms
        )  # verify midv settings are loaded
        if err_flag:
            common_utils.MessagebarAndLog.info(
                log_msg=ru(
                    QCoreApplication.translate(
                        "Midvatten", "load_strat_symbology err_flag: %s"
                    )
                )
                % str(err_flag)
            )
        else:
            self.strat_symbology = StratSymbology(
                qgis.utils.iface, self.iface.mainWindow()
            )
        common_utils.stop_waiting_cursor()

    @common_utils.general_exception_handler
    def add_midvatten_layers(self):
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            self.iface, self.ms
        )  # verify midv settings are loaded
        if err_flag == 0:
            sanity = common_utils.Askuser(
                "YesNo",
                ru(
                    QCoreApplication.translate(
                        "Midvatten",
                        """This operation will load default layers ( with predefined layout, edit forms etc.) from your selected database to your qgis project.\n\nIf any default Midvatten DB layers already are loaded into your qgis project, then those layers first will be removed from your qgis project.\n\nProceed?""",
                    )
                ),
                ru(QCoreApplication.translate("Midvatten", "Warning!")),
            )
            if sanity.result == 1:
                # show the user this may take a long time...
                common_utils.start_waiting_cursor()
                LoadLayers(qgis.utils.iface, self.ms.settingsdict)
                common_utils.stop_waiting_cursor()

    @common_utils.general_exception_handler
    def new_db(self, *args):
        sanity = common_utils.Askuser(
            "YesNo",
            ru(
                QCoreApplication.translate(
                    "Midvatten",
                    """This will create a new empty\nMidvatten DB with predefined design.\n\nContinue?""",
                )
            ),
            ru(QCoreApplication.translate("Midvatten", "Are you sure?")),
        )
        if sanity.result == 1:
            filenamepath = os.path.join(os.path.dirname(__file__), "metadata.txt")
            iniText = QSettings(filenamepath, QSettings.IniFormat)
            _verno = iniText.value("version")
            if isinstance(_verno, qgis.PyQt.QtCore.QVariant):
                verno = _verno.toString()
            else:
                verno = str(_verno)
            newdbinstance = NewDb()
            newdbinstance.create_new_spatialite_db(verno)

            if newdbinstance.db_settings:
                self.ms.settingsdict["database"] = newdbinstance.db_settings
                self.ms.save_settings("database")
                try:
                    self.midvsettingsdialog.select_last_settings()
                except AttributeError:
                    pass

            # about_db = db_utils.sql_load_fr_db('select * from about_db')

            # The markdown table is for gitlab. Run the rows below when there is a change in create_db
            # markdowntable = midvatten_utils.create_markdown_table_from_table('about_db', transposed=False, only_description=True)
            # print(markdowntable)

    @db_utils.if_connection_ok
    @common_utils.general_exception_handler
    def new_postgis_db(self):
        sanity = common_utils.Askuser(
            "YesNo",
            ru(
                QCoreApplication.translate(
                    "Midvatten",
                    """This will update the selected postgis database to a \nMidvatten Postgis DB with predefined design.\n\nContinue?""",
                )
            ),
            ru(QCoreApplication.translate("Midvatten", "Are you sure?")),
        )
        if sanity.result == 1:
            filenamepath = os.path.join(os.path.dirname(__file__), "metadata.txt")
            iniText = QSettings(filenamepath, QSettings.IniFormat)
            verno = str(iniText.value("version"))
            newdbinstance = NewDb()
            newdbinstance.populate_postgis_db(verno)
            if newdbinstance.db_settings:
                self.ms.settingsdict["database"] = newdbinstance.db_settings
                self.ms.save_settings("database")
                try:
                    self.midvsettingsdialog.select_last_settings()
                except AttributeError:
                    pass

            # The markdown table is for gitlab. Run the rows below when there is a change in create_db
            # markdowntable = midvatten_utils.create_markdown_table_from_table('about_db', transposed=False, only_description=True)
            # print(markdowntable)

    @common_utils.general_exception_handler
    def plot_piper(self):
        allcritical_layers = (
            "w_qual_lab",
            "w_qual_field",
        )  # none of these layers must be in editing mode
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            self.iface, self.ms, allcritical_layers
        )  # verify midv settings are loaded and the critical layers are not in editing mode
        err_flag = common_utils.verify_layer_selection(
            err_flag, 0
        )  # verify the selected layer has attribute "obsid" and that some features are selected
        if err_flag == 0:
            self.piperplot = PiperPlot(self.ms, qgis.utils.iface.activeLayer())
            self.piperplot.get_data_and_make_plot()

    @common_utils.general_exception_handler
    def plot_piper2(self):
        allcritical_layers = (
            "w_qual_lab",
            "w_qual_field",
        )  # none of these layers must be in editing mode
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            self.iface, self.ms, allcritical_layers
        )  # verify midv settings are loaded and the critical layers are not in editing mode
        err_flag = common_utils.verify_layer_selection(
            err_flag, 0
        )  # verify the selected layer has attribute "obsid" and that some features are selected
        if err_flag == 0:
            self.piperplot = PiperPlot(
                self.ms, qgis.utils.iface.activeLayer(), version=2
            )
            self.piperplot.get_data_and_make_plot()

    @common_utils.general_exception_handler
    def plot_timeseries(self):
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            self.iface, self.ms
        )  # verify midv settings are loaded
        err_flag = common_utils.verify_layer_selection(
            err_flag, 0
        )  # verify the selected layer has attribute "obsid" and that some features are selected
        if (
            self.ms.settingsdict["tstable"] == ""
            or self.ms.settingsdict["tscolumn"] == ""
        ):
            err_flag += 1
            common_utils.MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "Midvatten",
                    "Please set time series table and column in Midvatten settings.",
                ),
                duration=15,
            )
        if err_flag == 0:
            dlg = TimeSeriesPlot(qgis.utils.iface.activeLayer(), self.ms.settingsdict)

    @common_utils.general_exception_handler
    def plot_stratigraphy(self):
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            self.iface, self.ms
        )
        err_flag = common_utils.verify_layer_selection(err_flag, 0)
        if (
            err_flag == 0
            and common_utils.strat_selection_check(qgis.utils.iface.activeLayer())
            == "ok"
        ):
            dlg = Stratigraphy(
                self.iface, qgis.utils.iface.activeLayer(), self.ms.settingsdict
            )
            dlg.showSurvey()
            self.dlg = dlg  # only to prevent the Qdialog from closing.

    @common_utils.general_exception_handler
    def plot_section(self):
        selected_layer = (
            qgis.utils.iface.mapCanvas().currentLayer()
        )  # MUST BE LINE VECTOR LAYER WITH SAME EPSG as MIDV_OBSDB AND THERE MUST BE ONLY ONE SELECTED FEATURE
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
                log_msg=ru(
                    QCoreApplication.translate(
                        "Midvatten",
                        'The layer must be of type QgsVectorLayer, but was  "%s".',
                    )
                )
                % str(type(selected_layer)),
            )
            raise common_utils.UsageError()
        selected_obspoints = None
        for feat in selected_layer.getSelectedFeatures():
            geom = feat.geometry()
            if geom.wkbType() in (
                QgsWkbTypes.LineString,
                2,
                QgsWkbTypes.MultiLineString,
                5,
                QgsWkbTypes.LineStringZ,
                1002,
                QgsWkbTypes.MultiLineStringZ,
                1005,
                QgsWkbTypes.LineStringM,
                2002,
                QgsWkbTypes.MultiLineStringM,
                2005,
                QgsWkbTypes.LineStringZM,
                3002,
                QgsWkbTypes.MultiLineStringZM,
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
                            bar_msg=ru(
                                QCoreApplication.translate(
                                    "Midvatten",
                                    "%s. Plotting without observations!",
                                )
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
                            selected_obspoints = common_utils.getselectedobjectnames(
                                obs_points_layer
                            )
            else:
                selected_layer = None
                # utils.MessagebarAndLog.warning(bar_msg=QCoreApplication.translate("Midvatten", 'Reverting to simple stratigraphy plot. For section plot, you must activate the vector line layer and select exactly one feature that defines the section'))
                # Then verify that at least two feature is selected in obs_points layer,
                # and get a list (selected_obspoints) of selected obs_points
                selected_obspoints = (
                    common_utils.getselectedobjectnames()
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
                            selected_obspoints = common_utils.getselectedobjectnames(
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
        # Then verify that at least two feature is selected in obs_points layer, and get a list (selected_obspoints) of selected obs_points
        # if len(selected_obspoints)>1:
        #    # We cannot send unicode as string to sql because it would include the '
        #    # Made into tuple because module sectionplot depends on obsid being a tuple
        #    selected_obspoints = ru(selected_obspoints, keep_containers=True)
        # else:
        #    midvatten_utils.MessagebarAndLog.critical(bar_msg=ru(QCoreApplication.translate("Midvatten", 'You must select at least two objects in the obs_points layer')))
        #    raise midvatten_utils.UsageError()
        try:
            self.sectionplot.create_new_plot(
                self.ms, selected_obspoints, selected_layer
            )
        except AttributeError:
            # traceback.print_exc()
            self.sectionplot = SectionPlot(self.iface.mainWindow(), self.iface)
            self.sectionplot.create_new_plot(
                self.ms, selected_obspoints, selected_layer
            )

    @common_utils.general_exception_handler
    def plot_xy(self):
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            self.iface, self.ms
        )  # verify midv settings are loaded
        err_flag = common_utils.verify_layer_selection(
            err_flag, 0
        )  # verify the selected layer has attribute "obsid" and that some features are selected
        if (
            self.ms.settingsdict["xytable"] == ""
            or self.ms.settingsdict["xy_xcolumn"] == ""
            or (
                self.ms.settingsdict["xy_y1column"] == ""
                and self.ms.settingsdict["xy_y2column"] == ""
                and self.ms.settingsdict["xy_y3column"] == ""
            )
        ):
            err_flag += 1
            common_utils.MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "Midvatten",
                    "Please set xy series table and columns in Midvatten settings.",
                ),
                duration=15,
            )
        if err_flag == 0:
            dlg = XYPlot(qgis.utils.iface.activeLayer(), self.ms.settingsdict)

    @common_utils.general_exception_handler
    def plot_sqlite(self):
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            self.iface, self.ms
        )  # verify midv settings are loaded
        if not (err_flag == 0):
            return
        try:
            self.customplot.activateWindow()
        except:
            self.customplot = plotsqlitewindow(
                self.iface.mainWindow(), self.ms
            )  # self.iface as arg?

    @common_utils.general_exception_handler
    def prepare_layers_for_qgis2threejs(self):
        allcritical_layers = ("obs_points", "stratigraphy")
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            self.iface, self.ms, allcritical_layers
        )  # verify midv settings are loaded
        if err_flag == 0:
            dbconnection = db_utils.DbConnectionManager()
            dbtype = dbconnection.dbtype
            dbconnection.closedb()
            """if dbtype != 'spatialite':
                common_utils.MessagebarAndLog.critical(bar_msg=ru(QCoreApplication.translate('prepare_layers_for_qgis2threejs', 'Only supported for spatialite.')))
                return"""

            common_utils.start_waiting_cursor()  # show the user this may take a long time...
            PrepareForQgis2Threejs(qgis.utils.iface, self.ms.settingsdict)
            common_utils.stop_waiting_cursor()

    def project_created(self):
        self.reset_settings()

    def project_opened(self):
        self.ms.reset_settings()
        self.ms.loadSettings()
        try:  # if midvsettingsdock is shown, then it must be reloaded
            self.midvsettingsdialog.activateWindow()
            self.midvsettingsdialog.clear_everything()
            self.midvsettingsdialog.select_last_settings()
        except:
            pass
        midvatten_utils.warn_about_old_database()

    def reset_settings(self):
        self.ms.reset_settings()
        self.ms.save_settings()
        try:  # if midvsettingsdock is shown, then it must be reset
            self.midvsettingsdialog.activateWindow()
            self.midvsettingsdialog.clear_everything()
        except:
            pass

    def setup(self):
        try:
            self.midvsettingsdialog.activateWindow()
        except AttributeError:
            # utils.MessagebarAndLog.info(log_msg=traceback.format_exc())
            self.midvsettingsdialog = midvsettingsdialog.MidvattenSettingsDock(
                self.iface.mainWindow(), self.iface, self.ms
            )  # self.iface as arg?
            self.midvsettingsdialog.destroyed.connect(
                lambda: self._del_dialog("midvsettingsdialog")
            )
            # self.midvsettingsdialog.closed.connect(lambda: self.del_dialog())

    def _del_dialog(self, var):
        try:
            delattr(self, var)
        except:
            common_utils.MessagebarAndLog.info(log_msg=traceback.format_exc())

    def vacuum_db(self):
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            self.iface, self.ms
        )  # verify midv settings are loaded
        if err_flag == 0:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            with monkeytype.trace():
                db_utils.sql_alter_db("vacuum")
            common_utils.stop_waiting_cursor()

    @common_utils.general_exception_handler
    def waterqualityreport(self):
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            self.iface, self.ms
        )  # verify midv settings are loaded
        err_flag = common_utils.verify_layer_selection(
            err_flag
        )  # verify the selected layer has attribute "obsid" and that some feature(s) is selected
        if (
            self.ms.settingsdict["database"] == ""
            or self.ms.settingsdict["wqualtable"] == ""
            or self.ms.settingsdict["wqual_paramcolumn"] == ""
            or self.ms.settingsdict["wqual_valuecolumn"] == ""
        ):
            err_flag += 1
            common_utils.MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "Midvatten",
                    "Check Midvatten settings! \nSomething is probably wrong in the 'W quality report' tab!",
                ),
                duration=15,
            )
        if err_flag == 0:
            fail = 0
            for k in common_utils.getselectedobjectnames(
                qgis.utils.iface.activeLayer()
            ):  # all selected objects
                if not db_utils.sql_load_fr_db(
                    "select obsid from %s where obsid = '%s'"
                    % (self.ms.settingsdict["wqualtable"], str(k))
                )[
                    1
                ]:  # if there is a selected object without water quality data
                    common_utils.MessagebarAndLog.critical(
                        bar_msg=ru(
                            QCoreApplication.translate(
                                "Midvatten", "No water quality data for %s"
                            )
                        )
                        % str(k)
                    )
                    fail = 1
            if not fail == 1:  # only if all objects has data
                Wqualreport(
                    qgis.utils.iface.activeLayer(), self.ms.settingsdict
                )  # TEMPORARY FOR GVAB

    @common_utils.general_exception_handler
    def waterqualityreportcompact(self):
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            self.iface, self.ms
        )  # verify midv settings are loaded
        if err_flag == 0:
            CompactWqualReportUi(self.iface.mainWindow(), self.ms)

    @common_utils.general_exception_handler
    def wlvlcalculate(self):
        allcritical_layers = (
            "obs_points",
            "w_levels",
        )  # Check that none of these layers are in editing mode
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            self.iface, self.ms, allcritical_layers
        )  # verify midv settings are loaded
        layername = "obs_points"
        err_flag = common_utils.verify_this_layer_selected_and_not_in_edit_mode(
            err_flag, layername
        )  # verify selected layername and not in edit mode
        if err_flag == 0:
            dlg = CalculateLevel(
                self.iface.mainWindow(), qgis.utils.iface.activeLayer()
            )  # dock is an instance of calibrlogger
            dlg.exec_()

    @common_utils.general_exception_handler
    def wlvlloggcalibrate(self):
        allcritical_layers = ("w_levels_logger", "w_levels")
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            self.iface, self.ms, allcritical_layers
        )  # verify midv settings are loaded
        if err_flag == 0:
            try:
                self.calibrplot.activateWindow()
            except:
                self.calibrplot = LoggerEditor(
                    self.iface.mainWindow(), self.ms.settingsdict
                )  # ,obsid)

    @common_utils.waiting_cursor
    def zip_db(self):
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            self.iface, self.ms
        )  # verify midv settings are loaded
        if err_flag == 0:
            dbconnection = db_utils.DbConnectionManager()
            connection_ok = dbconnection.connect2db()
            if connection_ok:
                db_utils.backup_db(dbconnection)
                dbconnection.closedb()

    @common_utils.general_exception_handler
    def calculate_db_table_rows(self):
        """Counts the number of rows for all tables in the database"""
        QApplication.setOverrideCursor(Qt.WaitCursor)
        midvatten_utils.calculate_db_table_rows()
        common_utils.stop_waiting_cursor()

    @common_utils.general_exception_handler
    def list_of_values_from_selected_features(self):
        """Writes a concatted list of values from selected column from selected features
        The list could be used in other layer filters or selections.
        """

        ValuesFromSelectedFeaturesGui(self.iface.mainWindow())

    @common_utils.general_exception_handler
    def add_view_obs_points_lines(self):
        midvatten_utils.add_view_obs_points_obs_lines()

    @common_utils.general_exception_handler
    def add_non_essential_tables(self):
        midvatten_utils.add_non_essential_tables()
