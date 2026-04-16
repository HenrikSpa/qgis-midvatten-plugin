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

import logging
import os.path
import shutil
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import qgis.PyQt.QtCore
from qgis.PyQt.QtCore import QCoreApplication, QDir, QSettings, QUrl
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMenu
from qgis.core import QgsApplication

import midvatten.midvsettingsdialog as midvsettingsdialog
from midvatten.definitions import midvatten_defs
from midvatten.tools.calculate_level import CalculateLevel
from midvatten.tools.column_values_from_selected_features import (
    ValuesFromSelectedFeaturesGui,
)
from midvatten.tools.create_db import NewDb
from midvatten.tools.custom_drillreport import DrillreportUi
from midvatten.tools.customplot import CustomPlot
from midvatten.tools.drillreport import Drillreport
from midvatten.tools.export_data import ExportData
from midvatten.tools.export_fieldlogger import ExportToFieldLogger
from midvatten.tools.export_spatialite import ExportSpatialite
from midvatten.tools.import_diveroffice import DiverofficeImport
from midvatten.tools.import_fieldlogger import FieldloggerImport
from midvatten.tools.import_general_csv_gui import GeneralCsvImportGui
from midvatten.tools.import_hobologger import HobologgerImport
from midvatten.tools.import_interlab4 import Interlab4Import
from midvatten.tools.import_levelogger import LeveloggerImport
from midvatten.tools.loadlayers import LoadLayers
from midvatten.tools.loggereditor import LoggerEditor
from midvatten.tools.midvsettings import MidvSettings
from midvatten.tools.piper import PiperPlot
from midvatten.tools.prepareforqgis2threejs import PrepareForQgis2Threejs
from midvatten.tools.sectionplot import SectionPlot
from midvatten.tools.strat_symbology import StratSymbology
from midvatten.tools.stratigraphy import Stratigraphy
from midvatten.tools.tsplot import TimeSeriesPlot
from midvatten.tools.utils import common_utils, db_utils, midvatten_utils
from midvatten.tools.utils import matplotlib_replacements
from midvatten.tools.utils.util_translate import get_translate
from midvatten.tools.w_flow_calc_aveflow import CalculateAveflow
from midvatten.tools.wqualreport import Wqualreport
from midvatten.tools.wqualreport_compact import CompactWqualReportUi
from midvatten.tools.xyplot import XYPlot

log = logging.getLogger(__name__)


@dataclass
class ActionSpec:
    id: str
    label: str
    icon: str
    menu: str  # "import" | "export" | "edit" | "plot" | "report" | "db" | "utils"
    tool_class: type | None = None
    callback: Callable[[], None] | None = None
    needs_db: bool = True
    critical_layers: tuple[str, ...] = field(default_factory=tuple)
    needs_selection: bool = False
    needs_active_layer: str | None = None
    persistent: bool = False
    toolbar: bool = False


def _make_actions(plugin: "Midvatten") -> list[ActionSpec]:
    """Build the full action manifest. Called once from initGui()."""
    iface = plugin.iface
    ms = plugin.ms
    return [
        # ── Import ──────────────────────────────────────────────────
        ActionSpec(
            id="import_csv",
            label=QCoreApplication.translate(
                "Midvatten", "Import data using general csv format"
            ),
            icon="import_wqual_field.png",
            menu="import",
            tool_class=GeneralCsvImportGui,
            critical_layers=("obs_points", "obs_lines", "zz_flowtype"),
            persistent=True,
        ),
        ActionSpec(
            id="import_diveroffice",
            label=QCoreApplication.translate(
                "Midvatten",
                "Import logger data using Diver-Office csv-format",
            ),
            icon="load_wlevels_logger.png",
            menu="import",
            tool_class=DiverofficeImport,
            critical_layers=("obs_points", "w_levels_logger"),
        ),
        ActionSpec(
            id="import_levelogger",
            label=QCoreApplication.translate(
                "Midvatten",
                "Import logger data using Levelogger csv-format",
            ),
            icon="load_wlevels_logger.png",
            menu="import",
            tool_class=LeveloggerImport,
            critical_layers=("obs_points", "w_levels_logger"),
        ),
        ActionSpec(
            id="import_hobologger",
            label=QCoreApplication.translate(
                "Midvatten",
                "Import logger data using HOBO logger csv-format",
            ),
            icon="load_wlevels_logger.png",
            menu="import",
            tool_class=HobologgerImport,
            critical_layers=("obs_points", "w_levels_logger"),
        ),
        ActionSpec(
            id="import_interlab4",
            label=QCoreApplication.translate(
                "Midvatten",
                "Import w quality from lab data using interlab4 format",
            ),
            icon="import_wqual_lab.png",
            menu="import",
            tool_class=Interlab4Import,
            critical_layers=("obs_points", "w_qual_lab"),
        ),
        ActionSpec(
            id="import_fieldlogger",
            label=QCoreApplication.translate(
                "Midvatten", "Import data using FieldLogger format"
            ),
            icon="import_wqual_field.png",
            menu="import",
            tool_class=FieldloggerImport,
            critical_layers=(
                "obs_points",
                "w_qual_field",
                "w_levels",
                "w_flow",
                "comments",
            ),
        ),
        # ── Export ──────────────────────────────────────────────────
        ActionSpec(
            id="export_csv",
            label=QCoreApplication.translate(
                "Midvatten", "Export to a set of csv files"
            ),
            icon="export_csv.png",
            menu="export",
            tool_class=ExportData,
            critical_layers=("obs_points", "obs_lines"),
        ),
        ActionSpec(
            id="export_spatialite",
            label=QCoreApplication.translate(
                "Midvatten", "Export to another spatialite database"
            ),
            icon="export_spatialite.png",
            menu="export",
            tool_class=ExportSpatialite,
            critical_layers=("obs_points", "obs_lines"),
        ),
        ActionSpec(
            id="export_fieldlogger",
            label=QCoreApplication.translate(
                "Midvatten", "Export to FieldLogger or FieldForm format"
            ),
            icon="export_csv.png",
            menu="export",
            tool_class=ExportToFieldLogger,
            needs_db=False,
            persistent=True,
        ),
        # ── Edit ────────────────────────────────────────────────────
        ActionSpec(
            id="wlvlcalculate",
            label=QCoreApplication.translate(
                "Midvatten", "Calculate w level from manual measurements"
            ),
            icon="calc_level_masl.png",
            menu="edit",
            tool_class=CalculateLevel,
            critical_layers=("obs_points", "w_levels"),
            needs_active_layer="obs_points",
            toolbar=True,
        ),
        ActionSpec(
            id="wlvlloggcalibrate",
            label=QCoreApplication.translate(
                "Midvatten", "Edit water level logger data"
            ),
            icon="calibr_level_logger_masl.png",
            menu="edit",
            tool_class=LoggerEditor,
            critical_layers=("w_levels_logger", "w_levels"),
            persistent=True,
        ),
        ActionSpec(
            id="calculate_aveflow",
            label=QCoreApplication.translate(
                "Midvatten", "Calculate Aveflow from Accvol"
            ),
            icon="import_wflow.png",
            menu="edit",
            tool_class=CalculateAveflow,
            critical_layers=("obs_points", "w_flow"),
            needs_selection=True,
        ),
        # ── Plot ────────────────────────────────────────────────────
        ActionSpec(
            id="plot_timeseries",
            label=QCoreApplication.translate("Midvatten", "Time series plot"),
            icon="PlotTS.png",
            menu="plot",
            tool_class=TimeSeriesPlot,
            needs_selection=True,
            toolbar=True,
        ),
        ActionSpec(
            id="plot_xy",
            label=QCoreApplication.translate("Midvatten", "Scatter plot"),
            icon="PlotXY.png",
            menu="plot",
            tool_class=XYPlot,
            needs_selection=True,
            toolbar=True,
        ),
        ActionSpec(
            id="plot_stratigraphy",
            label=QCoreApplication.translate("Midvatten", "Stratigraphy plot"),
            icon="PlotStratigraphy.png",
            menu="plot",
            tool_class=Stratigraphy,
            needs_selection=True,
            toolbar=True,
        ),
        ActionSpec(
            id="plot_section",
            label=QCoreApplication.translate("Midvatten", "Section plot"),
            icon="PlotSection.png",
            menu="plot",
            tool_class=SectionPlot,
            persistent=True,
            toolbar=True,
        ),
        ActionSpec(
            id="plot_sqlite",
            label=QCoreApplication.translate("Midvatten", "Custom plots"),
            icon="plotsqliteicon.png",
            menu="plot",
            tool_class=CustomPlot,
            persistent=True,
            toolbar=True,
        ),
        ActionSpec(
            id="plot_piper",
            label=QCoreApplication.translate("Midvatten", "Piper diagram"),
            icon="Piper.png",
            menu="plot",
            tool_class=PiperPlot,
            critical_layers=("w_qual_lab", "w_qual_field"),
            needs_selection=True,
            persistent=True,
            toolbar=True,
        ),
        # ── Report ──────────────────────────────────────────────────
        ActionSpec(
            id="drillreport",
            label=QCoreApplication.translate("Midvatten", "General drill report"),
            icon="drill_report.png",
            menu="report",
            tool_class=Drillreport,
            critical_layers=("obs_points", "w_levels", "w_qual_lab"),
            needs_selection=True,
            toolbar=True,
        ),
        ActionSpec(
            id="custom_drillreport",
            label=QCoreApplication.translate("Midvatten", "Custom drill report"),
            icon="drill_report.png",
            menu="report",
            tool_class=DrillreportUi,
            critical_layers=("obs_points", "w_levels", "w_qual_lab"),
        ),
        ActionSpec(
            id="waterqualityreport",
            label=QCoreApplication.translate("Midvatten", "Water quality table"),
            icon="wqualreport.png",
            menu="report",
            tool_class=Wqualreport,
            needs_selection=True,
            toolbar=True,
        ),
        ActionSpec(
            id="waterqualityreportcompact",
            label=QCoreApplication.translate(
                "Midvatten", "Compact water quality reports"
            ),
            icon="wqualreport.png",
            menu="report",
            tool_class=CompactWqualReportUi,
        ),
        # ── DB management ───────────────────────────────────────────
        ActionSpec(
            id="new_db",
            label=QCoreApplication.translate(
                "Midvatten",
                "Create a new Midvatten project database",
            ),
            icon="create_new.xpm",
            menu="db",
            callback=lambda: plugin.new_db(),
            needs_db=False,
        ),
        ActionSpec(
            id="new_postgis_db",
            label=QCoreApplication.translate(
                "Midvatten",
                "Make selected PostgreSQL database into a Midvatten project database",
            ),
            icon="create_new.xpm",
            menu="db",
            callback=lambda: plugin.new_postgis_db(),
            needs_db=False,
        ),
        ActionSpec(
            id="vacuum_db",
            label=QCoreApplication.translate("Midvatten", "Vacuum the database"),
            icon="vacuum.png",
            menu="db",
            callback=lambda: db_utils.vacuum_db(),
        ),
        ActionSpec(
            id="zip_db",
            label=QCoreApplication.translate("Midvatten", "Backup the database"),
            icon="zip.png",
            menu="db",
            callback=lambda: db_utils.backup_db(),
        ),
        ActionSpec(
            id="add_non_essential_tables",
            label=QCoreApplication.translate(
                "Midvatten", "Add non-essential data tables"
            ),
            icon="create_new.xmp",
            menu="db",
            callback=lambda: midvatten_utils.add_non_essential_tables(),
        ),
        # ── Utils ───────────────────────────────────────────────────
        ActionSpec(
            id="load_data_domains",
            label=QCoreApplication.translate(
                "Midvatten", "Load data domain tables to qgis"
            ),
            icon="loaddatadomains.png",
            menu="utils",
            callback=lambda: LoadLayers(
                iface, ms.settingsdict, "Midvatten_data_domains"
            ),
        ),
        ActionSpec(
            id="load_data_tables",
            label=QCoreApplication.translate("Midvatten", "Load data tables to qgis"),
            icon="loaddatadomains.png",
            menu="utils",
            callback=lambda: LoadLayers(
                iface, ms.settingsdict, "Midvatten_data_tables"
            ),
        ),
        ActionSpec(
            id="load_strat_symbology",
            label=QCoreApplication.translate(
                "Midvatten", "Load stratigraphy symbology to qgis"
            ),
            icon="stratsymbology.png",
            menu="utils",
            tool_class=StratSymbology,
            toolbar=True,
        ),
        ActionSpec(
            id="prepare_layers_for_qgis2threejs",
            label=QCoreApplication.translate(
                "Midvatten", "Prepare 3D-data for Qgis2threejs plugin"
            ),
            icon="qgis2threejs.png",
            menu="utils",
            tool_class=PrepareForQgis2Threejs,
            critical_layers=("obs_points", "stratigraphy"),
        ),
        ActionSpec(
            id="calculate_db_table_rows",
            label=QCoreApplication.translate(
                "Midvatten", "Calculate database table row"
            ),
            icon="calc_statistics.png",
            menu="utils",
            callback=lambda: db_utils.calculate_db_table_rows(),
        ),
        ActionSpec(
            id="list_of_values_from_selected_features",
            label=QCoreApplication.translate(
                "Midvatten", "List of values from selected features"
            ),
            icon="listofvalues.png",
            menu="utils",
            tool_class=ValuesFromSelectedFeaturesGui,
            needs_db=False,
            toolbar=True,
        ),
        ActionSpec(
            id="add_view_obs_points_lines",
            label=QCoreApplication.translate(
                "Midvatten", "Add obs_points/obs_lines view"
            ),
            icon="create_new.xmp",
            menu="utils",
            callback=lambda: midvatten_utils.add_view_obs_points_obs_lines(),
        ),
        ActionSpec(
            id="add_midvatten_layers",
            label=QCoreApplication.translate(
                "Midvatten", "Load default db-layers to qgis"
            ),
            icon="loaddefaultlayers.png",
            menu="db",
            callback=lambda: LoadLayers(iface, ms.settingsdict),
        ),
    ]


class Midvatten:
    def __init__(self, iface):
        matplotlib_replacements.perform_all_replacements()
        self.iface = iface
        # initialize plugin directory
        self.plugin_dir = Path(os.path.dirname(__file__))

        self.ms = MidvSettings()
        self.translator = get_translate("midvatten")
        self.actions = []
        self._open_tools: dict = {}

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
        icon_path: str,
        text: str,
        callback: Callable,
        enabled_flag: bool = True,
        add_to_menu: bool = False,
        add_to_toolbar: bool = False,
        status_tip: Optional[str] = None,
        whats_this: Optional[str] = None,
        parent=None,
    ) -> QAction:
        """Create a QAction and register it in self.actions."""
        if parent is None:
            parent = self.iface.mainWindow()

        icon_full_path = self.plugin_dir / "icons" / icon_path
        icon = QIcon(str(icon_full_path))
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)
        if whats_this is not None:
            action.setWhatsThis(whats_this)
        if add_to_toolbar:
            self.iface.addToolBarIcon(action)
        if add_to_menu:
            self.iface.addPluginToMenu(self.menu, action)

        self.actions.append(action)
        return action

    @common_utils.general_exception_handler
    def _dispatch(self, spec: ActionSpec) -> None:
        if spec.needs_db:
            err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
                self.iface, self.ms, spec.critical_layers
            )
            if err_flag:
                return
        if spec.needs_selection:
            err_flag = common_utils.verify_layer_selection(0, 0)
            if err_flag:
                return
        if spec.needs_active_layer:
            err_flag = common_utils.verify_this_layer_selected_and_not_in_edit_mode(
                0, spec.needs_active_layer
            )
            if err_flag:
                return

        if spec.persistent:
            existing = self._open_tools.get(spec.id)
            if existing is not None and existing.isVisible():
                existing.raise_()
                existing.activateWindow()
                return

        if spec.callback is not None:
            spec.callback()
            return
        tool = spec.tool_class(self.iface, self.ms)
        tool.show()
        if spec.persistent:
            self._open_tools[spec.id] = tool

    def initGui(self) -> None:
        """Create the menu entries and toolbar icons inside the QGIS GUI."""
        self._open_tools = {}
        self._setup_menu()
        self._connect_signals()

        self._actions_manifest: list[ActionSpec] = _make_actions(self)
        self._qactions: dict[str, QAction] = {}

        # Build submenus
        import_menu = self.add_menu(self.tr("&Import data to database"), self.menu)
        export_menu = self.add_menu(self.tr("&Export data from database"), self.menu)
        edit_menu = self.add_menu(self.tr("&Edit data in database"), self.menu)
        plot_menu = self.add_menu(self.tr("&Plots"), self.menu)
        report_menu = self.add_menu(self.tr("&Reports"), self.menu)
        db_menu = self.add_menu(self.tr("&Database management"), self.menu)
        utils_menu = self.add_menu(self.tr("&Utilities"), self.menu)

        menu_map = {
            "import": import_menu,
            "export": export_menu,
            "edit": edit_menu,
            "plot": plot_menu,
            "report": report_menu,
            "db": db_menu,
            "utils": utils_menu,
        }
        self._submenus = menu_map

        # Build toolbar
        self.tool_bar = self.iface.addToolBar("Midvatten")
        self.tool_bar.setObjectName("Midvatten")

        # Settings action (special — not in manifest)
        self.action_midvatten_settings = self.add_action(
            "MidvSettings.png",
            text=self.tr("Midvatten Settings"),
            callback=lambda x: self.setup(),
            whats_this=self.tr("Configuration for Midvatten toolset"),
        )
        self.iface.registerMainWindowAction(self.action_midvatten_settings, "F6")
        self.tool_bar.addAction(self.action_midvatten_settings)

        # Build all manifest actions
        for spec in self._actions_manifest:
            action = self.add_action(
                spec.icon,
                text=spec.label,
                callback=lambda x, s=spec: self._dispatch(s),
            )
            self._qactions[spec.id] = action
            menu_map[spec.menu].addAction(action)
            if spec.toolbar:
                self.tool_bar.addAction(action)

        # Reset settings action (goes in utils submenu, not in manifest)
        action_reset = self.add_action(
            "ResetSettings.png",
            text=self.tr("Reset settings"),
            callback=lambda x: self.reset_settings(),
        )
        utils_menu.addAction(action_reset)

        # Special actions on main menu (not in submenus)
        self.action_load_layers = self._qactions["add_midvatten_layers"]

        self.action_about = self.add_action(
            "about.png",
            text=self.tr("About"),
            callback=lambda x: self.about(),
        )

        self.menu.addSeparator()
        self.menu.addAction(self.action_load_layers)
        self.menu.addAction(self.action_midvatten_settings)
        self.menu.addAction(self.action_about)

    def _setup_menu(self) -> None:
        """Find an existing Midvatten menu or create a new one."""
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

    def _connect_signals(self) -> None:
        """Connect QGIS iface signals to plugin slots."""
        # QGIS iface connections
        self.iface.projectRead.connect(self.project_opened)
        self.iface.newProjectCreated.connect(self.project_created)

        # Connect message log to logfile.
        # Log file name must be set as env. variable QGIS_LOG_FILE in
        # settings > options > system > environment.
        QgsApplication.messageLog().messageReceived.connect(
            common_utils.write_qgs_log_to_file
        )

    def add_menu(self, name: str, parent: QMenu) -> QMenu:
        menu = QMenu(name)
        parent.addMenu(menu)
        return menu

    def unload(self):
        try:
            self.menu.removeAction(self.action_load_layers)
            self.menu.removeAction(self.action_midvatten_settings)
            self.menu.removeAction(self.action_about)
        except Exception:
            pass

        for submenu in getattr(self, "_submenus", {}).values():
            try:
                self.menu.removeAction(submenu.menuAction())
                submenu.deleteLater()
            except Exception:
                pass

        if self.owns_midv_menu:
            self.menu.parentWidget().removeAction(self.menu.menuAction())
            self.menu.deleteLater()

        for action in self.actions:
            try:
                self.iface.removeToolBarIcon(action)
            except Exception:
                pass

        del self.tool_bar
        self.iface.unregisterMainWindowAction(self.action_midvatten_settings)

    def about(self):
        get_translate("midvatten")
        filename = self.plugin_dir / "metadata.txt"
        metadata = QSettings(str(filename), QSettings.Format.IniFormat)
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

        with open(str(template_file), encoding="cp1252") as infile:
            rows = [
                row.replace("VERSIONCHANGETHIS", verno)
                .replace("AUTHORCHANGETHIS", author)
                .replace("EMAILCHANGETHIS", email)
                .replace("HOMEPAGECHANGETHIS", homepage)
                for row in infile
            ]
        with open(str(outname), "w", encoding="cp1252") as outfile:
            outfile.write("\n".join(rows))
        dlg = common_utils.HtmlDialog(
            "About Midvatten plugin for QGIS", QUrl.fromLocalFile(str(outname))
        )
        dlg.exec()

    def project_created(self):
        self.reset_settings()

    def project_opened(self):
        self.ms.reset_settings()
        self.ms.load_settings()
        try:  # if midvsettingsdock is shown, then it must be reloaded
            self.midvsettingsdialog.activateWindow()
            self.midvsettingsdialog.clear_everything()
            self.midvsettingsdialog.select_last_settings()
        except Exception:
            pass
        midvatten_utils.warn_about_old_database()

    def reset_settings(self):
        self.ms.reset_settings()
        self.ms.save_settings()
        try:  # if midvsettingsdock is shown, then it must be reset
            self.midvsettingsdialog.activateWindow()
            self.midvsettingsdialog.clear_everything()
        except Exception:
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
        except Exception:
            common_utils.MessagebarAndLog.info(log_msg=traceback.format_exc())

    @common_utils.general_exception_handler
    def export_csv(self):
        allcritical_layers = ("obs_points", "obs_lines")
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            self.iface, self.ms, allcritical_layers
        )
        if err_flag == 0:
            ExportData(self.iface, self.ms).show()

    @common_utils.general_exception_handler
    def load_strat_symbology(self):
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            self.iface, self.ms
        )
        if not err_flag:
            self.strat_symbology = StratSymbology(self.iface, self.ms)

    @common_utils.general_exception_handler
    def plot_sqlite(self):
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            self.iface, self.ms
        )
        if not (err_flag == 0):
            return
        existing = self._open_tools.get("plot_sqlite")
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return
        tool = CustomPlot(self.iface, self.ms)
        tool.show()
        self._open_tools["plot_sqlite"] = tool
        self.customplot = tool  # kept for test-call-site compatibility

    @common_utils.general_exception_handler
    def plot_section(self):
        existing = self._open_tools.get("plot_section")
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return
        tool = SectionPlot(self.iface, self.ms)
        tool.show()
        self._open_tools["plot_section"] = tool
        self.sectionplot = tool  # kept for test-call-site compatibility

    @common_utils.general_exception_handler
    def prepare_layers_for_qgis2threejs(self):
        allcritical_layers = ("obs_points", "stratigraphy")
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            self.iface, self.ms, allcritical_layers
        )
        if err_flag == 0:
            common_utils.start_waiting_cursor()
            PrepareForQgis2Threejs(self.iface, self.ms).show()
            common_utils.stop_waiting_cursor()

    @common_utils.general_exception_handler
    def new_db(self, *args):
        sanity = common_utils.Askuser(
            "YesNo",
            QCoreApplication.translate(
                "Midvatten",
                """This will create a new empty\nMidvatten DB with predefined design.\n\nContinue?""",
            ),
            QCoreApplication.translate("Midvatten", "Are you sure?"),
        )
        if sanity.result == 1:
            filenamepath = os.path.join(os.path.dirname(__file__), "metadata.txt")
            ini_text = QSettings(filenamepath, QSettings.Format.IniFormat)
            _verno = ini_text.value("version")
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

    @db_utils.if_connection_ok
    @common_utils.general_exception_handler
    def new_postgis_db(self):
        sanity = common_utils.Askuser(
            "YesNo",
            QCoreApplication.translate(
                "Midvatten",
                """This will update the selected postgis database to a \nMidvatten Postgis DB with predefined design.\n\nContinue?""",
            ),
            QCoreApplication.translate("Midvatten", "Are you sure?"),
        )
        if sanity.result == 1:
            filenamepath = os.path.join(os.path.dirname(__file__), "metadata.txt")
            ini_text = QSettings(filenamepath, QSettings.Format.IniFormat)
            verno = str(ini_text.value("version"))
            newdbinstance = NewDb()
            newdbinstance.populate_postgis_db(verno)
            if newdbinstance.db_settings:
                self.ms.settingsdict["database"] = newdbinstance.db_settings
                self.ms.save_settings("database")
                try:
                    self.midvsettingsdialog.select_last_settings()
                except AttributeError:
                    pass
