# -*- coding: utf-8 -*-
"""
/***************************************************************************
 midvsettingsdialog
 A part of the QGIS plugin Midvatten
 
 This part of the plugin handles the user interaction with midvsettingsdock and
 propagates any changes to midvattensettings
 
                             -------------------
        begin                : 2011-10-18
        copyright            : (C) 2011 by joskal
        email                : groundwatergis [at] gmail.com
 ***************************************************************************/"""
import ast
import os.path

from functools import partial  # only to get combobox signals to work
from typing import Any, List, Optional

import qgis.PyQt
from qgis.PyQt import uic, QtCore
from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtWidgets import QDockWidget, QFileDialog
from qgis.PyQt.QtWidgets import QGridLayout, QMainWindow

from midvatten.tools.midvsettings import MidvSettings
from midvatten.tools.utils import common_utils, gui_utils, db_utils
from midvatten.tools.utils.common_utils import returnunicode as ru
from midvatten.tools.utils.midvatten_utils import warn_about_old_database

midvsettingsdock_ui_class = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "ui", "midvsettingsdock.ui")
)[0]


class MidvattenSettingsDock(QDockWidget, midvsettingsdock_ui_class):
    """
    Class for the Midvatten settings dockwidget.
    """

    def __init__(self, parent: QMainWindow, iface, msettings: MidvSettings):
        self.parent = parent
        self.iface = iface
        self.ms = msettings
        self.ms.load_settings()
        QDockWidget.__init__(self, self.parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setupUi(self)
        self.init_ui()

    def init_ui(self):
        """The settings dialog is cleared, filled with relevant information and
        the last selected settings are preset
        """
        self.database_settings = DatabaseSettings(self, self.grid_layout_db)
        self.clear_everything()

        self.marker_combo_box.addItems(
            ["obsid", "type", "date_time", "obsid but no legend", "simple marker"]
        )

        if len(self.ms.settingsdict["database"]) > 0:
            self.select_last_settings()

        # Load general settings
        # self.load_and_select_general_settings() # TODO: remove in version 1.4

        # SIGNALS
        # move dockwidget
        self.dockLocationChanged.connect(self.set_location)

        # tab TS
        self.list_of_tables.currentIndexChanged.connect(partial(self.ts_table_updated))
        self.list_of_columns.currentIndexChanged.connect(
            partial(self.changed_list_of_columns)
        )
        self.check_box_data_points.stateChanged.connect(self.changed_check_box_data_points)
        self.check_box_step_plot.stateChanged.connect(self.changed_check_box_step_plot)
        # tab XY
        self.list_of_tables_2.currentIndexChanged.connect(partial(self.xy_table_updated))
        self.list_of_columns_2.currentIndexChanged.connect(
            partial(self.changed_list_of_columns2)
        )
        self.list_of_columns_3.currentIndexChanged.connect(
            partial(self.changed_list_of_columns3)
        )
        self.list_of_columns_4.currentIndexChanged.connect(
            partial(self.changed_list_of_columns4)
        )
        self.list_of_columns_5.currentIndexChanged.connect(
            partial(self.changed_list_of_columns5)
        )
        self.check_box_data_points_2.stateChanged.connect(self.changed_check_box_data_points2)
        # tab wqualreport
        self.list_of_tables_wqual.currentIndexChanged.connect(
            partial(self.wqual_table_updated)
        )
        self.list_of_columns_wqualparam.currentIndexChanged.connect(
            partial(self.changed_list_of_columns_w_qual_param)
        )
        self.list_of_columns_wqualvalue.currentIndexChanged.connect(
            partial(self.changed_list_of_columns_w_qual_value)
        )
        self.list_ofdate_time_format.currentIndexChanged.connect(
            partial(self.changed_list_ofdate_time_format)
        )
        self.list_of_columns_wqualunit.currentIndexChanged.connect(
            partial(self.changed_list_of_columns_w_qual_unit)
        )
        self.list_of_columns_wqualsorting.currentIndexChanged.connect(
            partial(self.changed_list_of_columns_w_qual_sorting)
        )

        # tab piper
        self.param_cl.currentIndexChanged.connect(partial(self.changed_param_cl))
        self.param_hco3.currentIndexChanged.connect(partial(self.changed_param_hco3))
        self.param_so4.currentIndexChanged.connect(partial(self.changed_param_so4))
        self.param_na.currentIndexChanged.connect(partial(self.changed_param_na))
        self.param_k.currentIndexChanged.connect(partial(self.changed_param_k))
        self.param_ca.currentIndexChanged.connect(partial(self.changed_param_ca))
        self.param_mg.currentIndexChanged.connect(partial(self.changed_param_mg))
        self.marker_combo_box.currentIndexChanged.connect(
            partial(self.changed_piper_marker_combo_box)
        )

        # Draw the widget
        self.iface.addDockWidget(max(self.ms.settingsdict["settingslocation"], 1), self)
        self.iface.mapCanvas().setRenderFlag(True)

    def changed_check_box_data_points(self):
        self.ms.settingsdict["tsdotmarkers"] = self.check_box_data_points.checkState()
        self.ms.save_settings("tsdotmarkers")

    def changed_check_box_data_points2(self):
        self.ms.settingsdict["xydotmarkers"] = self.check_box_data_points_2.checkState()
        self.ms.save_settings("xydotmarkers")

    def changed_check_box_step_plot(self):
        self.ms.settingsdict["tsstepplot"] = self.check_box_step_plot.checkState()
        self.ms.save_settings("tsstepplot")

    def changed_list_of_columns(self):
        self.ms.settingsdict["tscolumn"] = self.list_of_columns.currentText()
        self.ms.save_settings("tscolumn")

    def changed_list_of_columns2(self):
        self.ms.settingsdict["xy_xcolumn"] = self.list_of_columns_2.currentText()
        self.ms.save_settings("xy_xcolumn")

    def changed_list_of_columns3(self):
        self.ms.settingsdict["xy_y1column"] = self.list_of_columns_3.currentText()
        self.ms.save_settings("xy_y1column")

    def changed_list_of_columns4(self):
        self.ms.settingsdict["xy_y2column"] = self.list_of_columns_4.currentText()
        self.ms.save_settings("xy_y2column")

    def changed_list_of_columns5(self):
        self.ms.settingsdict["xy_y3column"] = self.list_of_columns_5.currentText()
        self.ms.save_settings("xy_y3column")

    def changed_list_of_columns_w_qual_param(self):
        self.ms.settingsdict["wqual_paramcolumn"] = (
            self.list_of_columns_wqualparam.currentText()
        )
        self.ms.save_settings("wqual_paramcolumn")

    def changed_list_of_columns_w_qual_value(self):
        self.ms.settingsdict["wqual_valuecolumn"] = (
            self.list_of_columns_wqualvalue.currentText()
        )
        self.ms.save_settings("wqual_valuecolumn")

    def changed_list_of_columns_w_qual_unit(self):
        self.ms.settingsdict["wqual_unitcolumn"] = (
            self.list_of_columns_wqualunit.currentText()
        )
        self.ms.save_settings("wqual_unitcolumn")

    def changed_list_of_columns_w_qual_sorting(self):
        self.ms.settingsdict["wqual_sortingcolumn"] = (
            self.list_of_columns_wqualsorting.currentText()
        )
        self.ms.save_settings("wqual_sortingcolumn")

    def changed_list_ofdate_time_format(self):
        self.ms.settingsdict["wqual_date_time_format"] = (
            self.list_ofdate_time_format.currentText()
        )
        self.ms.save_settings("wqual_date_time_format")

    def changed_param_cl(self):
        self.ms.settingsdict["piper_cl"] = self.param_cl.currentText()
        self.ms.save_settings("piper_cl")

    def changed_param_hco3(self):
        self.ms.settingsdict["piper_hco3"] = self.param_hco3.currentText()
        self.ms.save_settings("piper_hco3")

    def changed_param_so4(self):
        self.ms.settingsdict["piper_so4"] = self.param_so4.currentText()
        self.ms.save_settings("piper_so4")

    def changed_param_na(self):
        self.ms.settingsdict["piper_na"] = self.param_na.currentText()
        self.ms.save_settings("piper_na")

    def changed_param_k(self):
        self.ms.settingsdict["piper_k"] = self.param_k.currentText()
        self.ms.save_settings("piper_k")

    def changed_param_ca(self):
        self.ms.settingsdict["piper_ca"] = self.param_ca.currentText()
        self.ms.save_settings("piper_ca")

    def changed_param_mg(self):
        self.ms.settingsdict["piper_mg"] = self.param_mg.currentText()
        self.ms.save_settings("piper_mg")

    def changed_piper_marker_combo_box(self):
        self.ms.settingsdict["piper_markers"] = self.marker_combo_box.currentText()
        self.ms.save_settings("piper_markers")

    def changed_combobox(self, combobox, settings_string):
        """All "ChangedX" that are comboboxed should be replaced to this one
        Usage:
        self.param_hco3, SIGNAL("activated(int)"), partial(self.changed_combobox, self.param_hco3, 'piper_hco3'))
        """
        self.ms.settingsdict[settings_string] = combobox.currentText()
        self.ms.save_settings(settings_string)

    def clear_column_lists(self):
        self.list_of_columns.clear()
        self.list_of_columns_2.clear()
        self.list_of_columns_3.clear()
        self.list_of_columns_4.clear()
        self.list_of_columns_5.clear()
        self.list_of_columns_wqualparam.clear()
        self.list_of_columns_wqualvalue.clear()
        self.list_of_columns_wqualunit.clear()
        self.list_of_columns_wqualsorting.clear()

    def clear_everything(self):
        self.database_settings.clear()
        self.clear_table_lists()
        self.clear_column_lists()
        self.clear_piper_params()

    def clear_table_lists(self):
        self.list_of_tables.clear()
        self.list_of_tables_2.clear()
        self.list_of_tables_wqual.clear()

    def clear_piper_params(self):
        self.param_cl.clear()
        self.param_hco3.clear()
        self.param_so4.clear()
        self.param_na.clear()
        self.param_k.clear()
        self.param_ca.clear()
        self.param_mg.clear()

    def columns_to_combo_box(self, comboboxname: str = "", table: Optional[str] = None):
        getattr(self, comboboxname).clear()
        """This method fills comboboxes with columns for selected tool and table"""
        columns = self.load_columns_from_table(
            table
        )  # Load all columns into a list 'columns'
        if len(columns) > 0:  # Transfer information from list 'columns' to the combobox
            getattr(self, comboboxname).addItem("")
            for column_name in columns:
                getattr(self, comboboxname).addItem(
                    column_name
                )  # getattr is to combine a function and a string to a combined function

    @db_utils.if_connection_ok
    def select_last_settings(self):
        # self.ms.save_settings('database')
        self.database_settings.update_settings(self.ms.settingsdict["database"])
        self.load_plot_settings()

    @common_utils.general_exception_handler
    def load_plot_settings(self):
        self.load_tables_from_db()  # All ListOfTables are filled with relevant information
        self.load_distinct_piper_params()

        # TS plot settings
        self.load_and_select_last_ts_plot_settings()

        # XY plot settings
        self.load_and_select_last_xyplot_settings()

        # Water Quality Reports settings
        self.load_and_select_last_wqual_settings()

        # piper diagram settings
        self.load_and_select_last_piper_settings()

        # finally, set dockwidget to last choosen tab
        self.tab_widget.setCurrentIndex(int(self.ms.settingsdict["tabwidget"]))

    def load_and_select_last_piper_settings(self):
        searchindex = self.param_cl.findText(self.ms.settingsdict["piper_cl"])
        if searchindex >= 0:
            self.param_cl.setCurrentIndex(searchindex)
        searchindex = self.param_hco3.findText(self.ms.settingsdict["piper_hco3"])
        if searchindex >= 0:
            self.param_hco3.setCurrentIndex(searchindex)
        searchindex = self.param_so4.findText(self.ms.settingsdict["piper_so4"])
        if searchindex >= 0:
            self.param_so4.setCurrentIndex(searchindex)
        searchindex = self.param_na.findText(self.ms.settingsdict["piper_na"])
        if searchindex >= 0:
            self.param_na.setCurrentIndex(searchindex)
        searchindex = self.param_k.findText(self.ms.settingsdict["piper_k"])
        if searchindex >= 0:
            self.param_k.setCurrentIndex(searchindex)
        searchindex = self.param_ca.findText(self.ms.settingsdict["piper_ca"])
        if searchindex >= 0:
            self.param_ca.setCurrentIndex(searchindex)
        searchindex = self.param_mg.findText(self.ms.settingsdict["piper_mg"])
        if searchindex >= 0:
            self.param_mg.setCurrentIndex(searchindex)
        searchindex = self.marker_combo_box.findText(
            self.ms.settingsdict["piper_markers"]
        )
        if searchindex >= 0:
            self.marker_combo_box.setCurrentIndex(searchindex)

    def load_and_select_last_ts_plot_settings(self):
        if len(
            str(self.ms.settingsdict["tstable"])
        ):  # If there is a last selected tstable. #MacOSX fix1
            notfound = 0
            i = 0
            while notfound == 0:  # Loop until the last selected tstable is found
                self.list_of_tables.setCurrentIndex(i)
                if str(self.list_of_tables.currentText()) == str(
                    self.ms.settingsdict["tstable"]
                ):  # The index count stops when last selected table is found #MacOSX fix1
                    notfound = 1
                    self.ts_table_updated()  # Fill the given combobox with columns from the given table and also perform a sanity check of table
                    searchindex = self.list_of_columns.findText(
                        self.ms.settingsdict["tscolumn"]
                    )
                    if searchindex >= 0:
                        self.list_of_columns.setCurrentIndex(searchindex)
                elif i > len(self.list_of_tables):
                    notfound = 1
                i = i + 1

        if (
            self.ms.settingsdict["tsdotmarkers"] == 2
        ):  # If the TSPlot dot markers checkbox was checked last time it will be so now #MacOSX fix1
            self.check_box_data_points.setChecked(True)
        else:
            self.check_box_data_points.setChecked(False)
        if (
            self.ms.settingsdict["tsstepplot"] == 2
        ):  # If the TSPlot stepplot checkbox was checked last time it will be so now #MacOSX fix1
            self.check_box_step_plot.setChecked(True)
        else:
            self.check_box_step_plot.setChecked(False)

    def load_and_select_last_wqual_settings(self):
        searchindexouter = self.list_of_tables_wqual.findText(
            self.ms.settingsdict["wqualtable"]
        )
        if searchindexouter >= 0:
            self.list_of_tables_wqual.setCurrentIndex(searchindexouter)
            self.wqual_table_updated()
            # and then check all possible last selected columns for parameters, values etc.
            searchindex = self.list_of_columns_wqualparam.findText(
                self.ms.settingsdict["wqual_paramcolumn"]
            )
            if searchindex >= 0:
                self.list_of_columns_wqualparam.setCurrentIndex(searchindex)
            searchindex = self.list_of_columns_wqualvalue.findText(
                self.ms.settingsdict["wqual_valuecolumn"]
            )
            if searchindex >= 0:
                self.list_of_columns_wqualvalue.setCurrentIndex(searchindex)
            searchindex = self.list_ofdate_time_format.findText(
                self.ms.settingsdict["wqual_date_time_format"]
            )
            if searchindex == -1:
                searchindex = 1
            self.list_ofdate_time_format.setCurrentIndex(searchindex)
            searchindex = self.list_of_columns_wqualunit.findText(
                self.ms.settingsdict["wqual_unitcolumn"]
            )
            if searchindex >= 0:
                self.list_of_columns_wqualunit.setCurrentIndex(searchindex)
            searchindex = self.list_of_columns_wqualsorting.findText(
                self.ms.settingsdict["wqual_sortingcolumn"]
            )
            if searchindex >= 0:
                self.list_of_columns_wqualsorting.setCurrentIndex(searchindex)

    def load_and_select_last_xyplot_settings(self):
        if len(
            self.ms.settingsdict["xytable"]
        ):  # If there is a last selected xytable #MacOSX fix1
            notfound = 0
            i = 0
            while (
                notfound == 0
            ):  # looping through ListOfTables_2 looking for last selected xytable
                self.list_of_tables_2.setCurrentIndex(i)
                if str(self.list_of_tables_2.currentText()) == str(
                    self.ms.settingsdict["xytable"]
                ):  # when last selected xytable found, it is selected in list and a lot of columns is searced for #MacOSX fix1
                    notfound = 1
                    self.xy_table_updated()  # Fill the given combobox with columns from the given table and performs a test
                    searchindex = self.list_of_columns_2.findText(
                        self.ms.settingsdict["xy_xcolumn"]
                    )
                    if searchindex >= 0:
                        self.list_of_columns_2.setCurrentIndex(searchindex)
                    searchindex = self.list_of_columns_3.findText(
                        self.ms.settingsdict["xy_y1column"]
                    )
                    if searchindex >= 0:
                        self.list_of_columns_3.setCurrentIndex(searchindex)
                    searchindex = self.list_of_columns_4.findText(
                        self.ms.settingsdict["xy_y2column"]
                    )
                    if searchindex >= 0:
                        self.list_of_columns_4.setCurrentIndex(searchindex)
                    searchindex = self.list_of_columns_5.findText(
                        self.ms.settingsdict["xy_y3column"]
                    )
                    if searchindex >= 0:
                        self.list_of_columns_5.setCurrentIndex(searchindex)
                elif i > len(self.list_of_tables_2):
                    notfound = 1
                i = i + 1

        if (
            self.ms.settingsdict["xydotmarkers"] == 2
        ):  # If the XYPlot dot markers checkbox was checked last time it will be so now #MacOSX fix1
            self.check_box_data_points_2.setChecked(True)
        else:
            self.check_box_data_points_2.setChecked(False)

    def load_columns_from_table(self, table: str = "") -> List[Any]:
        return db_utils.tables_columns().get(table, [])

    def load_tables_from_db(
        self,
    ):  # This method populates all table-comboboxes with the tables inside the database
        # Execute a query in SQLite to return all available tables (sql syntax excludes some of the predefined tables)
        # start with cleaning comboboxes before filling with new entries
        tables = list(db_utils.tables_columns().keys())

        self.list_of_tables.addItem("")
        self.list_of_tables_2.addItem("")
        self.list_of_tables_wqual.addItem("")

        for table in sorted(tables):
            self.list_of_tables.addItem(table)
            self.list_of_tables_2.addItem(table)
            self.list_of_tables_wqual.addItem(table)

    def load_distinct_piper_params(self):
        self.clear_piper_params()

        # Dict not implemented yet.
        lab_parameters = {}
        if lab_parameters:
            for param_list in [
                self.param_cl,
                self.param_hco3,
                self.param_so4,
                self.param_na,
                self.param_k,
                self.param_ca,
                self.param_mg,
            ]:
                new_list = [""]
                new_list.extend(sorted(lab_parameters.keys()))
                param_list.addItems(new_list)
        else:
            connection_ok, result = db_utils.sql_load_fr_db(
                r"""SELECT DISTINCT parameter FROM w_qual_lab ORDER BY parameter"""
            )
            if connection_ok:
                self.param_cl.addItem("")
                self.param_hco3.addItem("")
                self.param_so4.addItem("")
                self.param_na.addItem("")
                self.param_k.addItem("")
                self.param_ca.addItem("")
                self.param_mg.addItem("")
                for row in result:
                    self.param_cl.addItem(row[0])
                    self.param_hco3.addItem(row[0])
                    self.param_so4.addItem(row[0])
                    self.param_na.addItem(row[0])
                    self.param_k.addItem(row[0])
                    self.param_ca.addItem(row[0])
                    self.param_mg.addItem(row[0])

    def piper_cl_updated(self):
        self.ms.settingsdict["piper_cl"] = str(self.param_cl.currentText())
        self.ms.save_settings("piper_cl")  # save this specific setting

    def piper_hco3_updated(self):
        self.ms.settingsdict["piper_hco3"] = str(self.param_hco3.currentText())
        self.ms.save_settings("piper_hco3")  # save this specific setting

    def piper_so4_updated(self):
        self.ms.settingsdict["piper_so4"] = str(self.param_so4.currentText())
        self.ms.save_settings("piper_so4")  # save this specific setting

    def piper_na_updated(self):
        self.ms.settingsdict["piper_na"] = str(self.param_na.currentText())
        self.ms.save_settings("piper_na")  # save this specific setting

    def piper_k_updated(self):
        self.ms.settingsdict["piper_k"] = str(self.param_k.currentText())
        self.ms.save_settings("piper_k")  # save this specific setting

    def piper_ca_updated(self):
        self.ms.settingsdict["piper_ca"] = str(self.param_ca.currentText())
        self.ms.save_settings("piper_ca")  # save this specific setting

    def piper_mg_updated(self):
        self.ms.settingsdict["piper_mg"] = str(self.param_mg.currentText())
        self.ms.save_settings("piper_mg")  # save this specific setting

    def set_location(self):
        dockarea = self.parent.dockWidgetArea(self)
        self.ms.settingsdict["settingslocation"] = dockarea
        self.ms.save_settings("settingslocation")

    def ts_table_updated(self):
        """This method is called whenever time series table is changed"""
        # First, update combobox with columns
        self.columns_to_combo_box(
            "list_of_columns", self.list_of_tables.currentText()
        )  # For some reason it is not possible to send currentText with the SIGNAL-trigger
        # Second, Make sure that columns obsid and date_time exists
        columns = self.load_columns_from_table(
            self.list_of_tables.currentText()
        )  # For some reason it is not possible to send currentText with the SIGNAL-trigger
        if ("obsid" in columns) and ("date_time" in columns):
            text = "<font color=green>%s</font>" % ru(
                QCoreApplication.translate(
                    "midvsettingsdialogdock",
                    "Correct table, both obsid and date_time columns have been found.",
                )
            )
        else:
            text = "<font color=red>%s</font>" % ru(
                QCoreApplication.translate(
                    "midvsettingsdialogdock",
                    "Wrong table! obsid and/or date_time is missing.",
                )
            )
        self.info_txt_ts_plot.setText(text)
        # finally, save to qgis project settings
        self.ms.settingsdict["tstable"] = self.list_of_tables.currentText()
        self.ms.save_settings("tstable")  # save this specific setting

    def wqual_table_updated(self):
        """This method is called whenever water quality table is changed and fils comboboxes with columns for wqual report"""
        self.list_of_columns_wqualparam.clear()
        self.list_of_columns_wqualvalue.clear()
        self.list_ofdate_time_format.clear()
        self.list_of_columns_wqualunit.clear()
        self.list_of_columns_wqualsorting.clear()
        columns = self.load_columns_from_table(
            self.list_of_tables_wqual.currentText()
        )  # Load all columns into a list (dict?) 'columns'
        if len(columns):  # Transfer information from list 'columns' to the combobox
            self.list_of_columns_wqualparam.addItem("")
            self.list_of_columns_wqualvalue.addItem("")
            self.list_ofdate_time_format.addItem("YYYY")
            self.list_of_columns_wqualunit.addItem("")
            self.list_of_columns_wqualsorting.addItem("")
            for column_name in columns:
                self.list_of_columns_wqualparam.addItem(column_name)
                self.list_of_columns_wqualvalue.addItem(column_name)
                self.list_of_columns_wqualunit.addItem(column_name)
                self.list_of_columns_wqualsorting.addItem(column_name)
        self.list_ofdate_time_format.addItem("YYYY-MM")
        self.list_ofdate_time_format.addItem("YYYY-MM-DD")
        self.list_ofdate_time_format.addItem("YYYY-MM-DD hh")
        self.list_ofdate_time_format.addItem("YYYY-MM-DD hh:mm")
        self.list_ofdate_time_format.addItem("YYYY-MM-DD hh:mm:ss")
        # self.ChangedListOfColumnsWQualParam()
        # self.ChangedListOfColumnsWQualValue()
        # self.ChangedListOfdate_time_format()
        # self.ChangedListOfColumnsWQualUnit()
        # self.ChangedListOfColumnsWQualSorting()
        self.ms.settingsdict["wqualtable"] = self.list_of_tables_wqual.currentText()
        self.ms.save_settings("wqualtable")  # save this specific setting

    def xy_columns_to_combo_box(self, table: Optional[str] = None):
        """This method fills comboboxes with columns for xyplot"""
        self.list_of_columns_2.clear()
        self.list_of_columns_3.clear()
        self.list_of_columns_4.clear()
        self.list_of_columns_5.clear()
        columns = self.load_columns_from_table(
            table
        )  # Load all columns into a list (dict?) 'columns'
        if len(columns):  # Transfer information from list 'columns' to the combobox
            self.list_of_columns_2.addItem("")
            self.list_of_columns_3.addItem("")
            self.list_of_columns_4.addItem("")
            self.list_of_columns_5.addItem("")
            for column_name in columns:
                self.list_of_columns_2.addItem(column_name)
                self.list_of_columns_3.addItem(column_name)
                self.list_of_columns_4.addItem(column_name)
                self.list_of_columns_5.addItem(column_name)

    def xy_table_updated(self):
        """This method is called whenever xy table is changed"""
        # First, update comboboxes with columns
        self.xy_columns_to_combo_box(
            self.list_of_tables_2.currentText()
        )  # For some reason it is not possible to send currentText with the SIGNAL-trigger
        # Second, Make sure that column obsid exists
        columns = self.load_columns_from_table(
            self.list_of_tables_2.currentText()
        )  # For some reason it is not possible to send currentText with the SIGNAL-trigger
        if "obsid" in columns:
            text = "<font color=green>%s</font>" % ru(
                QCoreApplication.translate(
                    "midvsettingsdialogdock", "Correct table! obsid column is found."
                )
            )
        else:
            text = "<font color=red>%s</font>" % ru(
                QCoreApplication.translate(
                    "midvsettingsdialogdock", "Wrong table! obsid is missing."
                )
            )
        self.info_txt_xy_plot.setText(text)
        self.ms.settingsdict["xytable"] = self.list_of_tables_2.currentText()
        self.ms.save_settings("xytable")  # save this specific setting


class DatabaseSettings(object):
    def __init__(
        self, midvsettingsdialogdock: MidvattenSettingsDock, gridLayout_db: QGridLayout
    ):
        self.midvsettingsdialogdock = midvsettingsdialogdock
        self.layout = gridLayout_db
        self.layout.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
        self.db_settings_obj = None
        self.label_width = self.maximum_label_width()

        self._label = qgis.PyQt.QtWidgets.QLabel(
            ru(QCoreApplication.translate("DatabaseSettings", "Database type"))
        )
        self._label.setFixedWidth(self.label_width)
        self._dbtype_combobox = qgis.PyQt.QtWidgets.QComboBox()
        self._dbtype_combobox.addItems(["", "spatialite", "postgis"])

        self.grid = gui_utils.RowEntryGrid()
        self.grid.layout.addWidget(self._label, 0, 0)
        self.grid.layout.addWidget(self._dbtype_combobox, 0, 1)
        self.layout.addWidget(self.grid.widget)

        self.child_widgets = []

        self._dbtype_combobox.currentIndexChanged.connect(self.choose_dbtype)

        # self.layout.setRowStretch(self.layout.rowCount(), 1)

    @property
    def dbtype_combobox(self):
        return common_utils.returnunicode(self._dbtype_combobox.currentText())

    @dbtype_combobox.setter
    def dbtype_combobox(self, value):
        index = self._dbtype_combobox.findText(common_utils.returnunicode(value))
        if index != -1:
            self._dbtype_combobox.setCurrentIndex(index)

    def choose_dbtype(self):
        # Remove stretch
        # self.layout.setRowStretch(self.layout.rowCount(), 0)
        for widget in self.child_widgets:
            try:
                widget.clear_widgets()
            except:
                pass
            try:
                self.layout.removeWidget(widget)
            except:
                pass
            try:
                widget.deleteLater()
            except:
                pass
            try:
                widget.close()
            except:
                pass
        self.child_widgets = []

        dbclasses = {"spatialite": SpatialiteSettings, "postgis": PostgisSettings}

        dbclass = dbclasses.get(self.dbtype_combobox, None)

        if dbclass is None:
            self.db_settings_obj = None
            return

        self.db_settings_obj = dbclass(self.midvsettingsdialogdock, self.label_width)
        self.layout.addWidget(self.db_settings_obj.widget, self.layout.rowCount(), 0)
        self.child_widgets.append(self.db_settings_obj.widget)

        # self.layout.setRowStretch(self.layout.rowCount(), 1)

    def update_settings(self, _db_settings: str):
        db_settings = None
        if not _db_settings or _db_settings is None:
            return

        try:
            db_settings = ast.literal_eval(_db_settings)
        except:
            common_utils.MessagebarAndLog.warning(
                log_msg=ru(
                    QCoreApplication.translate(
                        "DatabaseSettings", "Reading db_settings failed using string %s"
                    )
                )
                % _db_settings
            )
        else:
            pass

        for setting in [db_settings, _db_settings]:
            if isinstance(setting, str):
                # Assume that the db_settings is an old spatialite database
                if os.path.isfile(setting) and setting.endswith(".sqlite"):
                    db_settings = {"spatialite": {"dbpath": setting}}
                    break

        if isinstance(db_settings, dict):
            for dbtype, settings in db_settings.items():
                self.dbtype_combobox = dbtype
                self.choose_dbtype()

                for setting_name, value in settings.items():
                    try:
                        if hasattr(self.db_settings_obj, str(setting_name)):
                            setattr(self.db_settings_obj, str(setting_name), value)
                        else:
                            common_utils.MessagebarAndLog.warning(
                                log_msg=ru(
                                    QCoreApplication.translate(
                                        "DatabaseSettings",
                                        "Databasetype %s didn' t have setting %s",
                                    )
                                )
                                % (dbtype, setting_name)
                            )
                    except:
                        print(str(setting_name))
                        raise
        else:
            common_utils.MessagebarAndLog.warning(
                bar_msg=ru(
                    QCoreApplication.translate(
                        "DatabaseSettings",
                        "Could not load database settings. Select database again!",
                    )
                ),
                log_msg=ru(
                    QCoreApplication.translate(
                        "DatabaseSettings", "Tried to load db_settings string %s"
                    )
                )
                % _db_settings,
            )

    def clear(self):
        self.dbtype_combobox = ""
        self.choose_dbtype()

    def maximum_label_width(self) -> int:
        maximumwidth = 0
        for label_name in [
            ru(QCoreApplication.translate("DatabaseSettings", "Database type")),
            ru(QCoreApplication.translate("DatabaseSettings", "Select db")),
            ru(QCoreApplication.translate("DatabaseSettings", "Connections")),
        ]:
            testlabel = qgis.PyQt.QtWidgets.QLabel(label_name)
            maximumwidth = max(maximumwidth, testlabel.sizeHint().width())
        testlabel = None
        return maximumwidth


class SpatialiteSettings(gui_utils.RowEntryGrid):
    def __init__(self, midvsettingsdialogdock: MidvattenSettingsDock, label_width: int):
        super(SpatialiteSettings, self).__init__()
        self.midvsettingsdialogdock = midvsettingsdialogdock
        self.btn_set_db = qgis.PyQt.QtWidgets.QPushButton(
            ru(QCoreApplication.translate("SpatialiteSettings", "Select db"))
        )
        self.btn_set_db.setFixedWidth(label_width)
        self.layout.addWidget(self.btn_set_db, 0, 0)
        self._dbpath = qgis.PyQt.QtWidgets.QLineEdit("")
        self._dbpath.textChanged.connect(lambda: self.database_chosen())
        self._dbpath.editingFinished.connect(self.database_chosen)
        self.layout.addWidget(self._dbpath, 0, 1)

        # select file
        self.btn_set_db.clicked.connect(lambda x: self.select_file())

    @property
    def dbpath(self):
        return common_utils.returnunicode(self._dbpath.text())

    @dbpath.setter
    def dbpath(self, value):
        self._dbpath.setText(common_utils.returnunicode(value))

    def select_file(self):
        """Open a dialog to locate the sqlite file and some more..."""
        dbpath, __ = QFileDialog.getOpenFileName(
            None, str("Select database:"), "*.sqlite"
        )
        if dbpath:  # Only get new db name if not cancelling the FileDialog
            self.dbpath = dbpath

        else:  # debug
            common_utils.MessagebarAndLog.info(
                log_msg=ru(
                    QCoreApplication.translate(
                        "SpatialiteSettings",
                        "DB selection cancelled and still using database path %s",
                    )
                )
                % common_utils.returnunicode(
                    self.midvsettingsdialogdock.ms.settingsdict["database"]
                )
            )

    def database_chosen(self):
        if self._dbpath.hasFocus():
            return

        dbpath = self.dbpath
        self.midvsettingsdialogdock.ms.settingsdict["database"] = (
            common_utils.anything_to_string_representation(
                {"spatialite": {"dbpath": dbpath}}
            )
        )
        self.midvsettingsdialogdock.ms.save_settings("database")
        self.midvsettingsdialogdock.load_plot_settings()
        warn_about_old_database()


class PostgisSettings(gui_utils.RowEntryGrid):
    """Using a guide from http://gis.stackexchange.com/questions/180427/retrieve-available-postgis-connections-in-pyqgis"""

    def __init__(self, midvsettingsdialogdock: MidvattenSettingsDock, label_width: int):
        super(PostgisSettings, self).__init__()
        self.midvsettingsdialogdock = midvsettingsdialogdock

        postgis_connections = db_utils.get_postgis_connections()

        self.label = qgis.PyQt.QtWidgets.QLabel(
            ru(QCoreApplication.translate("PostgisSettings", "Connections"))
        )
        if label_width is not None:
            self.label.setFixedWidth(label_width)
        self._connection = qgis.PyQt.QtWidgets.QComboBox()
        self._connection.addItem("")
        connection_names = [
            "/".join(
                [
                    k,
                    ":".join(
                        [v.get("service", ""), v.get("host", ""), v.get("port", "")]
                    ),
                    v.get("database", ""),
                ]
            )
            for k, v in postgis_connections.items()
        ]
        self._connection.addItems(sorted(connection_names))

        self._connection.currentIndexChanged.connect(self.set_db)

        self.layout.addWidget(self.label, 0, 0)
        self.layout.addWidget(self._connection, 0, 1)

    @property
    def connection(self):
        return common_utils.returnunicode(self._connection.currentText())

    @connection.setter
    def connection(self, value):
        index = self._connection.findText(common_utils.returnunicode(value))
        if index != -1:
            self._connection.setCurrentIndex(index)

    def set_db(self):
        if self.connection:
            self.midvsettingsdialogdock.ms.settingsdict["database"] = (
                common_utils.anything_to_string_representation(
                    {"postgis": {"connection": self.connection}}
                )
            )
            self.midvsettingsdialogdock.ms.save_settings("database")
            self.midvsettingsdialogdock.load_plot_settings()
            warn_about_old_database()
