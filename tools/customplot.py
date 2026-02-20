# -*- coding: utf-8 -*-
"""
/***************************************************************************
 This part of the Midvatten plugin originates from the PlotSQLite application which plots . 
        Name                 : PlotSQLite
        Description          : Plots charts from data stored in a SQLite database
        Date                 : 2012-12-03 
        Author               : Josef Källgården
        copyright            : (C) 2011 by Josef Källgården
        email                : groundwatergis [at] gmail.com

The PlotSQLite application version 0.2.6 was merged into Midvatten plugin at 2014-05-06
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


import os
from functools import partial  # only to get combobox signals to work

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import qgis.PyQt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.dates import datestr2num
from qgis.PyQt import QtGui, QtCore, uic, QtWidgets  # , QtSql
from qgis.PyQt.QtCore import QCoreApplication

try:  # assume matplotlib >=1.5.1
    from matplotlib.backends.backend_qt5agg import (
        NavigationToolbar2QT as NavigationToolbar,
    )
    from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT
except:
    from matplotlib.backends.backend_qt5agg import (
        NavigationToolbar2QTAgg as NavigationToolbar,
    )
    from matplotlib.backends.backend_qt5agg import NavigationToolbar2QTAgg
import datetime
import matplotlib.ticker as tick

from qgis.PyQt.QtWidgets import QApplication

from midvatten.tools.utils import common_utils, midvatten_utils, db_utils
from midvatten.tools.utils.common_utils import returnunicode as ru, LEGEND_NCOL_KEY
from midvatten.definitions import midvatten_defs as defs
from midvatten.tools.utils.gui_utils import set_groupbox_children_visibility

try:
    import pandas as pd
except:
    pandas_on = False
else:
    pandas_on = True

common_utils.MessagebarAndLog.info(log_msg="Python pandas: " + str(pandas_on))
customplot_ui_class = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "..", "ui", "customplotdialog.ui")
)[0]


class CustomPlot(QtWidgets.QMainWindow, customplot_ui_class):
    def __init__(self, parent, msettings):
        self.ms = msettings
        self.ms.load_settings()
        QtWidgets.QDialog.__init__(self, parent)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.setupUi(self)  # due to initialisation of Ui_MainWindow instance
        self.init_ui()
        self.tables_columns = db_utils.tables_columns()
        self.load_tables_from_db(self.tables_columns)
        self.last_selections()  # fill comboboxes etc with last selected values
        # on close:
        # del self.axes.collections[:]#this should delete all plot objects related to axes and hence not intefere with following tsplots
        self.drawn = False
        self.used_format = None
        self.matplotlib_style_sheet_reference.setText(
            """<a href="https://matplotlib.org/stable/gallery/style_sheets/style_sheets_reference.html">Matplotlib style sheet reference</a>"""
        )
        self.matplotlib_style_sheet_reference.setOpenExternalLinks(True)

    def init_ui(self):
        self.tab1_table.clear()
        self.tab2_table.clear()
        self.tab3_table.clear()
        for i in range(1, 3):
            self.clearthings(i)
        # function partial due to problems with currentindexChanged and Combobox
        # self.tab1_table, QtCore.SIGNAL("currentIndexChanged(int)"), partial(self.table1_changed))#currentIndexChanged caused unnecessary signals when scrolling in combobox
        self.tab1_table.currentIndexChanged.connect(partial(self.table1_changed))
        self.tab1_filtercol1.currentIndexChanged.connect(
            partial(self.tab1_filter1_changed)
        )
        # self.tab1_filtercol1.currentIndexChanged.connect( partial(self.FilterChanged(1,1)))
        self.tab1_filtercol2.currentIndexChanged.connect(
            partial(self.tab1_filter2_changed)
        )
        self.tab2_table.currentIndexChanged.connect(partial(self.table2_changed))
        self.tab2_filtercol1.currentIndexChanged.connect(
            partial(self.tab2_filter1_changed)
        )
        self.tab2_filtercol2.currentIndexChanged.connect(
            partial(self.tab2_filter2_changed)
        )
        self.tab3_table.currentIndexChanged.connect(partial(self.table3_changed))
        self.tab3_filtercol1.currentIndexChanged.connect(
            partial(self.tab3_filter1_changed)
        )
        self.tab3_filtercol2.currentIndexChanged.connect(
            partial(self.tab3_filter2_changed)
        )
        self.tab1_plotsettings.clicked.connect(
            partial(set_groupbox_children_visibility, self.tab1_plotsettings)
        )
        self.tab2_plotsettings.clicked.connect(
            partial(set_groupbox_children_visibility, self.tab2_plotsettings)
        )
        self.tab3_plotsettings.clicked.connect(
            partial(set_groupbox_children_visibility, self.tab3_plotsettings)
        )
        self.chart_settings.clicked.connect(
            partial(set_groupbox_children_visibility, self.chart_settings)
        )
        self.styles_settings.clicked.connect(
            partial(set_groupbox_children_visibility, self.styles_settings)
        )
        self.plot_tabwidget.currentChanged.connect(self.uncheck_settings)
        self.plot_tabwidget.currentChanged.connect(
            lambda: self.tabwidget_resize(self.plot_tabwidget)
        )
        self.tab_widget.currentChanged.connect(
            lambda: self.tabwidget_resize(self.tab_widget)
        )

        self.select_button_t1f1.clicked.connect(
            partial(
                self.select_in_filterlist_from_selection,
                self.tab1_filter1,
                self.tab1_filtercol1,
            )
        )
        self.select_button_t1f2.clicked.connect(
            partial(
                self.select_in_filterlist_from_selection,
                self.tab1_filter2,
                self.tab1_filtercol2,
            )
        )
        self.select_button_t2f1.clicked.connect(
            partial(
                self.select_in_filterlist_from_selection,
                self.tab2_filter1,
                self.tab2_filtercol1,
            )
        )
        self.select_button_t2f2.clicked.connect(
            partial(
                self.select_in_filterlist_from_selection,
                self.tab2_filter2,
                self.tab2_filtercol2,
            )
        )
        self.select_button_t3f1.clicked.connect(
            partial(
                self.select_in_filterlist_from_selection,
                self.tab3_filter1,
                self.tab3_filtercol1,
            )
        )
        self.select_button_t3f2.clicked.connect(
            partial(
                self.select_in_filterlist_from_selection,
                self.tab3_filter2,
                self.tab3_filtercol2,
            )
        )

        self.tab1_listfilter1.editingFinished.connect(
            partial(self.filter_filterlist, self.tab1_filter1, self.tab1_listfilter1)
        )
        self.tab1_listfilter2.editingFinished.connect(
            partial(self.filter_filterlist, self.tab1_filter2, self.tab1_listfilter2)
        )
        self.tab2_listfilter1.editingFinished.connect(
            partial(self.filter_filterlist, self.tab2_filter1, self.tab2_listfilter1)
        )
        self.tab2_listfilter2.editingFinished.connect(
            partial(self.filter_filterlist, self.tab2_filter2, self.tab2_listfilter2)
        )
        self.tab3_listfilter1.editingFinished.connect(
            partial(self.filter_filterlist, self.tab3_filter1, self.tab3_listfilter1)
        )
        self.tab3_listfilter2.editingFinished.connect(
            partial(self.filter_filterlist, self.tab3_filter2, self.tab3_listfilter2)
        )
        self.filtersettings1.clicked.connect(
            partial(set_groupbox_children_visibility, self.filtersettings1)
        )
        self.filtersettings2.clicked.connect(
            partial(set_groupbox_children_visibility, self.filtersettings2)
        )
        self.filtersettings3.clicked.connect(
            partial(set_groupbox_children_visibility, self.filtersettings3)
        )

        self.plot_chart_q_push_button.clicked.connect(
            lambda x: self.draw_plot_with_styles()
        )
        self.save_as_csv_button.clicked.connect(lambda: self.start_csv_dialog())
        self.redraw_push_button.clicked.connect(lambda x: self.redraw())

        self.custplot_last_used_style_settingskey = "custplot_last_used_template"
        self.styles = midvatten_utils.MatplotlibStyles(
            self,
            self.template_list,
            self.import_button,
            self.open_folder_button,
            self.available_settings_button,
            self.save_as_button,
            self.custplot_last_used_style_settingskey,
            defs.custplot_default_style(),
            msettings=self.ms,
        )
        self.styles.select_style_in_list(defs.custplot_default_style()[1])

        # Validator for QlineEdit that should contain only floats, any number of
        # decimals with either point(.) or comma(,) as a decimal separater
        regexp = QtCore.QRegExp("[+-]?\\d*[\\.,]?\\d+")
        validator = QtGui.QRegExpValidator(regexp)
        self.tab1_factor.setValidator(validator)
        self.tab2_factor.setValidator(validator)
        self.tab3_factor.setValidator(validator)
        self.tab1_offset.setValidator(validator)
        self.tab2_offset.setValidator(validator)
        self.tab3_offset.setValidator(validator)

        self.tab1_pandas_calc = None
        self.tab2_pandas_calc = None
        self.tab3_pandas_calc = None
        if pandas_on:
            self.tab1_pandas_calc = PandasCalculations(self.grid_layout_16)
            self.tab2_pandas_calc = PandasCalculations(self.grid_layout_14)
            self.tab3_pandas_calc = PandasCalculations(self.grid_layout_19)

        self.plot_tabwidget.setCurrentIndex(0)
        for group_box in [
            self.tab1_plotsettings,
            self.tab2_plotsettings,
            self.tab3_plotsettings,
            self.filtersettings1,
            self.filtersettings2,
            self.filtersettings3,
            self.chart_settings,
            self.styles_settings,
        ]:
            group_box.setChecked(False)
            set_groupbox_children_visibility(group_box)
        self.uncheck_settings(0)

        self.title = None
        self.xaxis_label = None
        self.yaxis_label = None

        self.init_figure()
        self.tabwidget_resize(self.tab_widget)
        self.tabwidget_resize(self.plot_tabwidget)
        self.show()

    def init_figure(self):
        try:
            self.title = self.axes.get_title()
            self.xaxis_label = self.axes.get_xlabel()
            self.yaxis_label = self.axes.get_ylabel()
        except:
            pass

        if hasattr(self, "mpltoolbar"):
            self.layoutplot.removeWidget(self.mpltoolbar)
            self.mpltoolbar.close()
        if hasattr(self, "canvas"):
            self.layoutplot.removeWidget(self.canvas)
            self.canvas.close()
        if hasattr(self, "custplotfigure"):
            fignum = self.custplotfigure.number
            plt.close(fignum)

        self.custplotfigure = plt.figure()
        self.axes = self.custplotfigure.add_subplot(111)
        self.canvas = FigureCanvas(self.custplotfigure)

        self.mpltoolbar = NavigationToolbar(self.canvas, self.widget_plot)
        common_utils.PickAnnotator(self.custplotfigure, canvas=self.canvas)
        self.layoutplot.addWidget(self.canvas)
        self.layoutplot.addWidget(self.mpltoolbar)

    def calc_frequency(self, table2):
        freqs = np.zeros(len(table2.values), dtype=float)
        for j, row in enumerate(table2):
            if j > 0:  # we can not calculate frequency for first row
                try:
                    diff = table2.values[j] - table2.values[j - 1]
                    """ Get help from function datestr2num to get date and time into float"""
                    delta_time = (
                        24
                        * 3600
                        * (
                            datestr2num(table2.date_time[j])
                            - datestr2num(table2.date_time[j - 1])
                        )
                    )  # convert to seconds since numtime is days
                except:
                    pass  # just skip inaccurate data values and use previous frequency
                freqs[j] = diff / delta_time
        freqs[0] = freqs[1]  # assuming start frequency to get a nicer plot

        return freqs

    def draw_plot_with_styles(self):
        self.styles.load(self.draw_plot_all, (self, "mpltoolbar"))

    @common_utils.general_exception_handler
    def draw_plot_all(self, only_get_data=False):
        self.data = []
        common_utils.start_waiting_cursor()  # show the user this may take a long time...
        if not only_get_data:
            continous_color = True
            if continous_color:
                self.used_style_color_combo = set()
                color_cycler = mpl.rcParams["axes.prop_cycle"]
                color_cycle_len = len(color_cycler)
                color_cycle = color_cycler()
                self.line_cycler = common_utils.ContinuousColorCycle(
                    color_cycle,
                    color_cycle_len,
                    mpl.rcParams["axes.midv_line_cycle"],
                    self.used_style_color_combo,
                )
                self.marker_cycler = common_utils.ContinuousColorCycle(
                    color_cycle,
                    color_cycle_len,
                    mpl.rcParams["axes.midv_marker_cycle"],
                    self.used_style_color_combo,
                )
                self.line_and_marker_cycler = common_utils.ContinuousColorCycle(
                    color_cycle,
                    color_cycle_len,
                    mpl.rcParams["axes.midv_marker_cycle"]
                    * mpl.rcParams["axes.midv_line_cycle"],
                    self.used_style_color_combo,
                )
            else:
                ccycler = mpl.rcParams["axes.prop_cycle"]
                self.line_cycler = (mpl.rcParams["axes.midv_line_cycle"] * ccycler)()
                self.marker_cycler = (
                    mpl.rcParams["axes.midv_marker_cycle"] * ccycler
                )()
                self.line_and_marker_cycler = (
                    mpl.rcParams["axes.midv_marker_cycle"]
                    * mpl.rcParams["axes.midv_line_cycle"]
                    * ccycler
                )()

            self.init_figure()

            self.used_format = None

            if self.title:
                self.axes.set_title(self.title)
            if self.xaxis_label:
                self.axes.set_xlabel(self.xaxis_label)
            if self.yaxis_label:
                self.axes.set_ylabel(self.yaxis_label)

            self.axes.legend_ = None
        my_format = [
            ("date_time", datetime.datetime),
            ("values", float),
        ]

        dbconnection = db_utils.DbConnectionManager()

        i = 0
        nop = 0  # nop=number of plots
        self.p = []
        self.plabels = []

        nop, i = self.draw_plot(
            dbconnection,
            nop,
            i,
            my_format,
            self.tab1_table,
            self.tab1_xcol,
            self.tab1_ycol,
            self.tab1_filtercol1,
            self.tab1_filter1,
            self.tab1_filtercol2,
            self.tab1_filter2,
            self.tab1_plot_type,
            self.tab1_pandas_calc,
            self.tab1_remove_mean,
            self.tab1_factor,
            self.tab1_offset,
            only_get_data=only_get_data,
        )
        nop, i = self.draw_plot(
            dbconnection,
            nop,
            i,
            my_format,
            self.tab2_table,
            self.tab2_xcol,
            self.tab2_ycol,
            self.tab2_filtercol1,
            self.tab2_filter1,
            self.tab2_filtercol2,
            self.tab2_filter2,
            self.tab2_plot_type,
            self.tab2_pandas_calc,
            self.tab2_remove_mean,
            self.tab2_factor,
            self.tab2_offset,
            only_get_data=only_get_data,
        )
        nop, i = self.draw_plot(
            dbconnection,
            nop,
            i,
            my_format,
            self.tab3_table,
            self.tab3_xcol,
            self.tab3_ycol,
            self.tab3_filtercol1,
            self.tab3_filter1,
            self.tab3_filtercol2,
            self.tab3_filter2,
            self.tab3_plot_type,
            self.tab3_pandas_calc,
            self.tab3_remove_mean,
            self.tab3_factor,
            self.tab3_offset,
            only_get_data=only_get_data,
        )
        if only_get_data:
            data = self.data
            self.data = None
            common_utils.stop_waiting_cursor()
            return data
        else:
            if not self.p:
                common_utils.MessagebarAndLog.warning(
                    bar_msg=ru(
                        QCoreApplication.translate("CustomPlot", "Plot not updated.")
                    )
                )
                return None
            self.xaxis_formatters = (
                self.axes.xaxis.get_major_formatter(),
                self.axes.xaxis.get_major_locator(),
            )

            try:
                self.xaxis_formatters[1].__dict__["intervald"][3] = [
                    1,
                    2,
                    4,
                    8,
                    16,
                ]  # Fix to not have the date ticks overlap at month end/start
            except Exception as e:
                common_utils.MessagebarAndLog.warning(
                    log_msg=ru(
                        QCoreApplication.translate(
                            "Customplot", "Setting intervald failed! msg:\n%s "
                        )
                    )
                    % str(e)
                )

            self.drawn = True

            self.refreshPlot()
            common_utils.stop_waiting_cursor()

    def draw_plot(
        self,
        dbconnection,
        nop,
        i,
        my_format,
        table,
        xcol,
        ycol,
        filter1_col,
        filter1,
        filter2_col,
        filter2,
        plot_type,
        pandas_calc,
        remove_mean,
        factor,
        offset,
        only_get_data=False,
    ):

        if (
            not (table.currentText() == "" or table.currentText() == " ")
            and not (xcol.currentText() == "" or xcol.currentText() == " ")
            and not (ycol.currentText() == "" or ycol.currentText() == " ")
        ):  # if anything is to be plotted from tab 1
            self.ms.settingsdict["custplot_maxtstep"] = (
                self.spn_max_tstep.value()
            )  # if user selected a time step bigger than zero than thre may be discontinuous plots
            filter1_col = str(filter1_col.currentText())
            filter1list = filter1.selectedItems()
            filter2_col = str(filter2_col.currentText())
            filter2list = filter2.selectedItems()
            nop = max(len(filter1list), 1) * max(len(filter2list), 1)
            # self.p= [None]*nop#list for plot objects
            self.p.extend([None] * nop)  # list for plot objects
            self.plabels.extend([None] * nop)  # List for plot labels
            try:
                factor = float(factor.text().replace(",", "."))
            except ValueError:
                factor = 1.0
            try:
                offset = float(offset.text().replace(",", "."))
            except ValueError:
                offset = 0.0

            remove_mean = remove_mean.isChecked()

            _sql = r"""SELECT %s, %s FROM %s """ % (
                str(xcol.currentText()),
                str(ycol.currentText()),
                str(table.currentText()),
            )
            _sql += r"""WHERE %s """ % db_utils.test_not_null_and_not_empty_string(
                str(table.currentText()),
                str(xcol.currentText()),
                dbconnection,
            )
            _sql += r"""AND %s """ % db_utils.test_not_null_and_not_empty_string(
                str(table.currentText()),
                str(ycol.currentText()),
                dbconnection,
            )

            while i < len(self.p):
                # Both filters empty
                if (not filter1_col.strip() or not filter1list) and (
                    not filter2_col.strip() or not filter2list
                ):
                    sql = _sql + r""" ORDER BY %s""" % str(xcol.currentText())
                    recs = dbconnection.execute_and_fetchall(sql)
                    label = (
                        str(ycol.currentText()) + """, """ + str(table.currentText())
                    )
                    if not recs:
                        i += 1
                        continue
                    self.plabels[i] = label
                    self.createsingleplotobject(
                        recs,
                        i,
                        my_format,
                        plot_type.currentText(),
                        factor,
                        offset,
                        remove_mean,
                        pandas_calc,
                        only_get_data=only_get_data,
                    )
                    i += 1
                # Both filters in use
                elif all(
                    (filter1_col.strip(), filter1list, filter2_col.strip(), filter2list)
                ):
                    for item1 in filter1list:
                        for item2 in filter2list:
                            sql = (
                                _sql
                                + r""" AND %s = '%s' AND %s = '%s' ORDER BY %s"""
                                % (
                                    filter1_col,
                                    str(item1.text()),
                                    filter2_col,
                                    str(item2.text()),
                                    str(xcol.currentText()),
                                )
                            )
                            recs = dbconnection.execute_and_fetchall(sql)
                            label = str(item1.text()) + """, """ + str(item2.text())
                            if not recs:
                                common_utils.MessagebarAndLog.info(
                                    log_msg=ru(
                                        QCoreApplication.translate(
                                            "CustomPlot", "No plottable data for %s."
                                        )
                                    )
                                    % label
                                )
                                i += 1
                                continue
                            self.plabels[i] = label
                            self.createsingleplotobject(
                                recs,
                                i,
                                my_format,
                                plot_type.currentText(),
                                factor,
                                offset,
                                remove_mean,
                                pandas_calc,
                                only_get_data=only_get_data,
                            )
                            i += 1
                # One filter in use
                else:
                    for filter, filterlist in [
                        (filter1_col, filter1list),
                        (filter2_col, filter2list),
                    ]:
                        if not filter.strip() or not filterlist:
                            continue
                        else:
                            for item in filterlist:
                                sql = _sql + r""" AND %s = '%s' ORDER BY %s""" % (
                                    filter,
                                    str(item.text()),
                                    str(xcol.currentText()),
                                )
                                recs = dbconnection.execute_and_fetchall(sql)
                                label = str(item.text())
                                if not recs:
                                    common_utils.MessagebarAndLog.warning(
                                        log_msg=ru(
                                            QCoreApplication.translate(
                                                "CustomPlot",
                                                "No plottable data for %s.",
                                            )
                                        )
                                        % label
                                    )
                                    i += 1
                                    continue
                                self.plabels[i] = label
                                self.createsingleplotobject(
                                    recs,
                                    i,
                                    my_format,
                                    plot_type.currentText(),
                                    factor,
                                    offset,
                                    remove_mean,
                                    pandas_calc,
                                    only_get_data=only_get_data,
                                )
                                i += 1

        return nop, i

    def createsingleplotobject(
        self,
        recs,
        i,
        my_format,
        plottype="line",
        factor=1.0,
        offset=0.0,
        remove_mean=False,
        pandas_calc=None,
        only_get_data=False,
    ):
        # Transform data to a numpy.recarray
        try:
            table = np.array(recs, dtype=my_format)  # NDARRAY
            table2 = table.view(
                np.recarray
            )  # RECARRAY transform the 2 cols into callable objects
            flag_time_xy = "time"
            my_timestring = list(table2.date_time)
            numtime = datestr2num(
                my_timestring
            )  # conv list of strings to numpy.ndarray of floats
        except Exception as e:
            common_utils.MessagebarAndLog.warning(
                log_msg=ru(
                    QCoreApplication.translate(
                        "plotsqlitewindow", "Plotting date_time failed, msg: %s"
                    )
                )
                % str(e)
            )
            common_utils.MessagebarAndLog.info(
                log_msg=ru(
                    QCoreApplication.translate(
                        "plotsqlitewindow",
                        "Customplot, transforming to recarray with date_time as x-axis failed, msg: %s",
                    )
                )
                % ru(str(e))
            )
            my_format = [("numx", float), ("values", float)]
            table = np.array(
                recs, dtype=my_format
            )  # NDARRAY #define a format for xy-plot (to use if not datetime on x-axis)

            table2 = table.view(
                np.recarray
            )  # RECARRAY transform the 2 cols into callable objects

            flag_time_xy = "XY"
            numtime = list(table2.numx)

        if self.used_format is None:
            self.used_format = flag_time_xy
        else:
            if self.used_format != flag_time_xy:
                raise common_utils.UsageError(
                    ru(
                        QCoreApplication.translate(
                            "CustomPlot",
                            "Plotting both xy and time plot at the same time doesn't work! Check the x-y axix settings in all tabs!",
                        )
                    )
                )

        # from version 0.2 there is a possibility to make discontinuous plot if timestep bigger than maxtstep
        if (
            self.spn_max_tstep.value() > 0
        ):  # if user selected a time step bigger than zero than thre may be discontinuous plots
            pos = (
                np.where(np.abs(np.diff(numtime)) >= self.spn_max_tstep.value())[0] + 1
            )
            pos = pos.tolist()
            if pos:
                numtime = np.insert(numtime, pos, np.nan)
                try:
                    table2 = np.insert(table2, pos, np.nan)
                except (ValueError, TypeError):
                    for_concat = []
                    nan = np.array([(np.nan, np.nan)], dtype=my_format)
                    for idx, p in enumerate(pos):
                        if idx == 0:
                            for_concat.append(table[0:p])
                            for_concat.append(nan.copy())
                            continue
                        for_concat.append(table[pos[idx - 1] : p])
                        for_concat.append(nan.copy())
                    else:
                        for_concat.append(table[pos[-1] :])
                    table = np.concatenate(for_concat)
                    table = table.astype(my_format)
                    table2 = table.view(np.recarray)

        if flag_time_xy == "time" and plottype == "frequency":
            if len(table2) < 2:
                common_utils.MessagebarAndLog.warning(
                    bar_msg=ru(
                        QCoreApplication.translate(
                            "plotsqlitewindow",
                            "Frequency plot failed for %s. The timeseries must be longer than 1 value!",
                        )
                    )
                    % ru(self.plabels[i]),
                    duration=30,
                )
                table2.values[:] = [None] * len(table2)
            else:
                table2.values[:] = self.calc_frequency(table2)[:]

        if remove_mean:
            table2.values[:] = common_utils.remove_mean_from_nparray(table2.values)[:]

        if any(
            [
                factor != 1 and factor,
                offset,
            ]
        ):
            table2.values[:] = common_utils.scale_nparray(
                table2.values, factor, offset
            )[:]

        if pandas_calc and flag_time_xy == "time":
            if pandas_calc.use_pandas():
                df = pd.DataFrame.from_records(
                    table2, columns=["values"], exclude=["date_time"]
                )
                df.set_index(
                    pd.DatetimeIndex(table2.date_time, name="date_time"), inplace=True
                )
                df.columns = ["values"]

                df = pandas_calc.calculate(df)
                if df is not None:
                    try:
                        table = np.array(
                            list(zip(df.index, df["values"])), dtype=my_format
                        )
                    except TypeError:
                        common_utils.MessagebarAndLog.info(log_msg=str(df))
                        raise
                    table2 = table.view(
                        np.recarray
                    )  # RECARRAY transform the 2 cols into callable objects
                    numtime = table2.date_time
                else:
                    common_utils.MessagebarAndLog.info(
                        bar_msg=ru(
                            QCoreApplication.translate(
                                "plotsqlitewindow", "Pandas calculate failed."
                            )
                        )
                    )

        if flag_time_xy == "time":
            plotfunc = self.axes.plot_date
        elif flag_time_xy == "XY":
            plotfunc = self.axes.plot
        else:
            raise Exception("Programming error. Must be time or XY!")

        # Matplotlib rcParams often uses lines.markeredgewidth: 0.0 which makes the marker invisible.
        markeredgewidth = (
            1.0
            if not mpl.rcParams["lines.markeredgewidth"]
            else mpl.rcParams["lines.markeredgewidth"]
        )

        if only_get_data:
            self.data.append((table2, self.plabels[i]))
            return
        if plottype == "step-pre":
            (self.p[i],) = plotfunc(
                numtime,
                table2.values,
                "",
                picker=2,
                drawstyle="steps-pre",
                marker="None",
                label=self.plabels[i],
                **next(self.line_cycler),
            )  # 'steps-pre' best for precipitation and flowmeters, optional types are 'steps', 'steps-mid', 'steps-post'
        elif plottype == "step-post":
            (self.p[i],) = plotfunc(
                numtime,
                table2.values,
                "",
                picker=2,
                drawstyle="steps-post",
                marker="None",
                label=self.plabels[i],
                **next(self.line_cycler),
            )
        elif plottype == "line and cross":
            (self.p[i],) = plotfunc(
                numtime,
                table2.values,
                "",
                picker=2,
                marker="x",
                label=self.plabels[i],
                markeredgewidth=markeredgewidth,
                **next(self.line_cycler),
            )
        elif plottype == "marker":
            (self.p[i],) = plotfunc(
                numtime,
                table2.values,
                "",
                picker=2,
                linestyle="None",
                label=self.plabels[i],
                markeredgewidth=markeredgewidth,
                **next(self.marker_cycler),
            )
        elif plottype == "line":
            (self.p[i],) = plotfunc(
                numtime,
                table2.values,
                "",
                picker=2,
                marker="None",
                label=self.plabels[i],
                **next(self.line_cycler),
            )
        elif plottype == "frequency" and flag_time_xy == "time":
            try:
                (self.p[i],) = plotfunc(
                    numtime,
                    table2.values,
                    "",
                    picker=2,
                    marker="None",
                    label="frequency " + str(self.plabels[i]),
                    **next(self.line_cycler),
                )
                self.plabels[i] = "frequency " + str(self.plabels[i])
            except:
                (self.p[i],) = plotfunc(
                    np.array([]),
                    np.array([]),
                    "",
                    picker=2,
                    marker="None",
                    label="frequency " + str(self.plabels[i]),
                    **next(self.line_cycler),
                )
                self.plabels[i] = "frequency " + str(self.plabels[i])
        else:
            # line and marker
            (self.p[i],) = plotfunc(
                numtime,
                table2.values,
                "",
                picker=2,
                label=self.plabels[i],
                markeredgewidth=markeredgewidth,
                **next(self.line_and_marker_cycler),
            )

    def last_selections(self):  # set same selections as last plot

        last_selection_arg_tuples = [
            (
                self.tab1_table,
                self.tab1_xcol,
                self.tab1_ycol,
                "custplot_table1",
                "custplot_xcol1",
                "custplot_ycol1",
                self.table1_changed,
            ),
            (
                self.tab2_table,
                self.tab2_xcol,
                self.tab2_ycol,
                "custplot_table2",
                "custplot_xcol2",
                "custplot_ycol2",
                self.table2_changed,
            ),
            (
                self.tab3_table,
                self.tab3_xcol,
                self.tab3_ycol,
                "custplot_table3",
                "custplot_xcol3",
                "custplot_ycol3",
                self.table3_changed,
            ),
        ]

        for (
            table_combobox,
            xcol_combobox,
            ycol_combobox,
            custplot_table,
            custplot_xcol,
            custplot_ycol,
            table_changed,
        ) in last_selection_arg_tuples:
            self.set_last_selection(
                table_combobox,
                xcol_combobox,
                ycol_combobox,
                custplot_table,
                custplot_xcol,
                custplot_ycol,
                table_changed,
            )

        # table2
        self.tab_widget.setCurrentIndex(int(self.ms.settingsdict["custplot_tabwidget"]))

        filter_tuples = [
            (self.tab1_filtercol1, "custplot_filter1_1", 1, 1),
            (self.tab1_filtercol2, "custplot_filter2_1", 2, 1),
            (self.tab2_filtercol1, "custplot_filter1_2", 1, 2),
            (self.tab2_filtercol2, "custplot_filter2_2", 2, 2),
            (self.tab3_filtercol1, "custplot_filter1_3", 1, 3),
            (self.tab3_filtercol2, "custplot_filter2_3", 2, 3),
        ]

        for filter_combobox, custplot_filter, filterno1, filterno2 in filter_tuples:
            self.set_filters(filter_combobox, custplot_filter, filterno1, filterno2)

        filter_selection_tuples = [
            (self.tab1_filter1, "custplot_filter1_1_selection"),
            (self.tab1_filter2, "custplot_filter2_1_selection"),
            (self.tab2_filter1, "custplot_filter1_2_selection"),
            (self.tab2_filter2, "custplot_filter2_2_selection"),
            (self.tab3_filter1, "custplot_filter1_3_selection"),
            (self.tab3_filter2, "custplot_filter2_3_selection"),
        ]

        for filter_qlistwidget, custplot_filter_selection in filter_selection_tuples:
            self.filter_selections(filter_qlistwidget, custplot_filter_selection)

        # plottype1
        searchindex = self.tab1_plot_type.findText(
            self.ms.settingsdict["custplot_plottype1"]
        )
        if searchindex >= 0:
            self.tab1_plot_type.setCurrentIndex(searchindex)
        # plottype2
        searchindex = self.tab2_plot_type.findText(
            self.ms.settingsdict["custplot_plottype2"]
        )
        if searchindex >= 0:
            self.tab2_plot_type.setCurrentIndex(searchindex)
        # plottype3
        searchindex = self.tab3_plot_type.findText(
            self.ms.settingsdict["custplot_plottype3"]
        )
        if searchindex >= 0:
            self.tab3_plot_type.setCurrentIndex(searchindex)
        # max time step, titles, grid, legend
        self.spn_max_tstep.setValue(self.ms.settingsdict["custplot_maxtstep"])

        self.create_legend.setChecked(self.ms.settingsdict["custplot_legend"])
        self.regular_xaxis_interval.setChecked(
            self.ms.settingsdict["custplot_regular_xaxis_interval"]
        )
        self.grid.setChecked(self.ms.settingsdict["custplot_grid"])

    def set_last_selection(
        self,
        table_combobox,
        xcol_combobox,
        ycol_combobox,
        custplot_table,
        custplot_xcol,
        custplot_ycol,
        table_changed,
    ):
        searchindex = table_combobox.findText(self.ms.settingsdict[custplot_table])
        if searchindex >= 0:
            table_combobox.setCurrentIndex(searchindex)
            table_changed()
            searchindex = xcol_combobox.findText(self.ms.settingsdict[custplot_xcol])
            if searchindex >= 0:
                xcol_combobox.setCurrentIndex(searchindex)
            searchindex = ycol_combobox.findText(self.ms.settingsdict[custplot_ycol])
            if searchindex >= 0:
                ycol_combobox.setCurrentIndex(searchindex)

    def set_filters(self, filter_combobox, custplot_filter, filterno1, filterno2):
        # filtre1_1
        searchindex = filter_combobox.findText(self.ms.settingsdict[custplot_filter])
        if searchindex >= 0:
            filter_combobox.setCurrentIndex(searchindex)
            self.FilterChanged(filterno1, filterno2)

    def filter_selections(self, filter_qlistwidget, custplot_filter_selection):
        # filtre1_1_selection
        for index in range(filter_qlistwidget.count()):
            for item in self.ms.settingsdict[custplot_filter_selection]:
                if (
                    filter_qlistwidget.item(index).text() == item
                ):  # earlier str(item) but that caused probs for non-ascii
                    filter_qlistwidget.item(index).setSelected(True)

    def filter_filterlist(self, filterlist, lineedit):
        words = lineedit.text().split(";")

        listcount = filterlist.count()
        if words:
            [
                (
                    filterlist.item(idx).setHidden(False)
                    if any(
                        [
                            word.lower() in filterlist.item(idx).text().lower()
                            for word in words
                        ]
                    )
                    else filterlist.item(idx).setHidden(True)
                )
                for idx in range(listcount)
            ]
        else:
            [filterlist.item(idx).setHidden(False) for idx in range(listcount)]

    def load_tables_from_db(
        self, tables_columns
    ):  # Open the SpatiaLite file to extract info about tables
        tables = sorted(
            [
                table
                for table in list(tables_columns.keys())
                if table not in db_utils.nonplot_tables(as_tuple=True)
                and not table.startswith("zz_")
            ]
        )
        for i, table_combobox in enumerate(
            [self.tab1_table, self.tab2_table, self.tab3_table], 1
        ):
            table_combobox.clear()
            self.clearthings(i)
            table_combobox.addItem("")
            try:
                table_combobox.addItems(tables)
            except:
                for table in tables:
                    table_combobox.addItem(table)

    def clearthings(self, tabno=1):  # clear xcol,ycol,filter1,filter2
        xcolcombobox = f"tab{tabno}_xcol"
        ycolcombobox = f"tab{tabno}_ycol"
        filter1combobox = f"tab{tabno}_filtercol1"
        filter2combobox = f"tab{tabno}_filtercol2"
        filter1qlistwidget = f"tab{tabno}_filter1"
        filter2qlistwidget = f"tab{tabno}_filter2"
        getattr(self, xcolcombobox).clear()
        getattr(self, ycolcombobox).clear()
        getattr(self, filter1combobox).clear()
        getattr(self, filter2combobox).clear()
        getattr(self, filter1qlistwidget).clear()
        getattr(self, filter2qlistwidget).clear()

    def table1_changed(self):  # This method is called whenever table1 is changed
        # First, update combobox with columns
        self.clearthings(1)
        # self.ms.settingsdict['custplot_table1'] = self.tab1_table.currentText()
        self.populate_combo_box(
            "tab1_xcol", self.tab1_table.currentText()
        )  # GeneralNote: For some reason it is not possible to send currentText with the SIGNAL-trigger
        self.populate_combo_box(
            "tab1_ycol", self.tab1_table.currentText()
        )  # See GeneralNote
        self.populate_combo_box(
            "tab1_filtercol1", self.tab1_table.currentText()
        )  # See GeneralNote
        self.populate_combo_box(
            "tab1_filtercol2", self.tab1_table.currentText()
        )  # See GeneralNote

    def table2_changed(self):  # This method is called whenever table2 is changed
        # First, update combobox with columns
        self.clearthings(2)
        # self.ms.settingsdict['custplot_table2'] = self.tab2_table.currentText()
        self.populate_combo_box(
            "tab2_xcol", self.tab2_table.currentText()
        )  # GeneralNote: For some reason it is not possible to send currentText with the SIGNAL-trigger
        self.populate_combo_box(
            "tab2_ycol", self.tab2_table.currentText()
        )  # See GeneralNote
        self.populate_combo_box(
            "tab2_filtercol1", self.tab2_table.currentText()
        )  # See GeneralNote
        self.populate_combo_box(
            "tab2_filtercol2", self.tab2_table.currentText()
        )  # See GeneralNote

    def table3_changed(self):  # This method is called whenever table3 is changed
        # First, update combobox with columns
        self.clearthings(3)
        # self.ms.settingsdict['custplot_table2'] = self.tab3_table.currentText()
        self.populate_combo_box(
            "tab3_xcol", self.tab3_table.currentText()
        )  # GeneralNote: For some reason it is not possible to send currentText with the SIGNAL-trigger
        self.populate_combo_box(
            "tab3_ycol", self.tab3_table.currentText()
        )  # See GeneralNote
        self.populate_combo_box(
            "tab3_filtercol1", self.tab3_table.currentText()
        )  # See GeneralNote
        self.populate_combo_box(
            "tab3_filtercol2", self.tab3_table.currentText()
        )  # See GeneralNote

    def populate_combo_box(self, comboboxname="", table=None):
        """This method fills comboboxes with columns for selected tool and table"""
        columns = self.tables_columns.get(
            table, []
        )  # Load all columns into a list 'columnsä
        if len(columns) > 0:  # Transfer information from list 'columns' to the combobox
            getattr(self, comboboxname).addItem("")
            try:
                getattr(self, comboboxname).addItems(columns)
            except:
                for column in columns:
                    getattr(self, comboboxname).addItem(column)

    def filter_changed(self, filterno, tabno):
        table_combobox = f"tab{tabno}_table"
        filter_combobox = f"tab{tabno}_filtercol{filterno}"
        filter_q_list_widget = f"tab{tabno}_filter{filterno}"

        other_filterno = {2: 1, 1: 2}[filterno]
        other_filter_combobox = f"tab{tabno}_filtercol{other_filterno}"
        other_filter_q_list_widget = f"tab{tabno}_filter{other_filterno}"

        dependent_filtering_box = getattr(
            self, "dependent_filtering" + str(tabno), None
        )

        getattr(self, filter_q_list_widget).clear()
        if not getattr(self, filter_combobox).currentText() == "":
            self.populate_filter_list(
                getattr(self, table_combobox).currentText(),
                filter_q_list_widget,
                getattr(self, filter_combobox).currentText(),
                other_filter_q_list_widget,
                getattr(self, other_filter_combobox).currentText(),
                dependent_filtering_box,
            )

    def tab1_filter1_changed(self):
        self.filter_changed(1, 1)

    def tab1_filter2_changed(self):
        self.filter_changed(2, 1)

    def tab2_filter1_changed(self):
        self.filter_changed(1, 2)

    def tab2_filter2_changed(self):
        self.filter_changed(2, 2)

    def tab3_filter1_changed(self):
        self.filter_changed(1, 3)

    def tab3_filter2_changed(self):
        self.filter_changed(2, 3)

    def populate_filter_list(
        self,
        table,
        q_list_widget_name="",
        filtercolumn=None,
        other_q_list_widget=None,
        other_filtercolumn=None,
        dependent_filtering_box=None,
    ):

        dbconnection = db_utils.DbConnectionManager()
        sql = dbconnection.sql_ident(
            "SELECT DISTINCT {c} FROM {t} ORDER BY {c}", c=str(filtercolumn), t=table
        )
        args = None

        if dependent_filtering_box is not None:
            dependent_filtering = dependent_filtering_box.isChecked()
        else:
            dependent_filtering = False

        if other_q_list_widget is not None and other_filtercolumn and dependent_filtering:
            other_q_list_widget_wid = getattr(self, other_q_list_widget)
            selected = ru(
                [
                    item.text()
                    for item in other_q_list_widget_wid.selectedItems()
                    if item.text()
                ],
                keep_containers=True,
            )
            if selected:
                clause, args = dbconnection.in_clause(selected)
                sql = dbconnection.sql_ident(
                    "SELECT DISTINCT {c} FROM {t} WHERE {oc} IN "
                    + clause
                    + " ORDER BY {c}",
                    c=str(filtercolumn),
                    t=table,
                    oc=other_filtercolumn,
                )

        try:
            list_data = dbconnection.execute_and_fetchall(sql, args)
            connection_ok = True
        except Exception:
            connection_ok, list_data = False, []
        finally:
            try:
                dbconnection.closedb()
            except Exception:
                pass

        for post in list_data:
            item = QtWidgets.QListWidgetItem(str(post[0]))
            getattr(self, q_list_widget_name).addItem(item)

    @common_utils.general_exception_handler
    def redraw(self):
        self.styles.load(self.refreshPlot, (self, "mpltoolbar"))

    @common_utils.general_exception_handler
    def refreshPlot(self):
        # If the user has not pressed "draw" before, do nothing
        common_utils.MessagebarAndLog.info(
            log_msg=ru(QCoreApplication.translate("Customplot", "Loaded style:\n%s "))
            % (self.styles.rcparams())
        )

        if not self.drawn:
            return None

        self.storesettings()  # all custom plot related settings are stored when plotting data (or pressing "redraw")

        if self.used_format == "time":
            datemin = self.spn_min_x.dateTime().toPyDateTime()
            datemax = self.spn_max_x.dateTime().toPyDateTime()
            if datemin == datemax:  # xaxis-limits
                pass
            else:
                self.axes.set_xlim(min(datemin, datemax), max(datemin, datemax))
            if self.spn_min_y.value() == self.spn_max_y.value():  # yaxis-limits
                pass
            else:
                self.axes.set_ylim(
                    min(self.spn_max_y.value(), self.spn_min_y.value()),
                    max(self.spn_max_y.value(), self.spn_min_y.value()),
                )
            self.axes.yaxis.set_major_formatter(
                tick.ScalarFormatter(useOffset=False, useMathText=False)
            )  # yaxis-format
            self.axes.xaxis.set_major_formatter(self.xaxis_formatters[0])
            self.axes.xaxis.set_major_locator(self.xaxis_formatters[1])

            try:
                if self.regular_xaxis_interval.isChecked():
                    self.xaxis_formatters[1].__dict__["interval_multiples"] = False
                else:
                    self.xaxis_formatters[1].__dict__["interval_multiples"] = True
            except Exception as e:
                common_utils.MessagebarAndLog.warning(
                    log_msg=ru(
                        QCoreApplication.translate(
                            "Customplot",
                            "Setting regular xaxis interval failed! msg:\n%s ",
                        )
                    )
                    % str(e)
                )

        self.axes.grid(self.grid.isChecked())  # grid

        for label in self.axes.xaxis.get_ticklabels():
            label.set_rotation(20)

        # The legend
        if self.create_legend.isChecked():
            ncols = mpl.rcParams["legend.midv_ncol"]
            if self.axes.legend_ is None:
                if (self.spn_leg_x.value() == 0) and (self.spn_leg_y.value() == 0):
                    leg = self.axes.legend(
                        self.p, self.plabels, **{LEGEND_NCOL_KEY: ncols}
                    )
                else:
                    leg = self.axes.legend(
                        self.p,
                        self.plabels,
                        bbox_to_anchor=(self.spn_leg_x.value(), self.spn_leg_y.value()),
                        loc=10,
                        **{LEGEND_NCOL_KEY: ncols},
                    )
            else:
                if (self.spn_leg_x.value() == 0) and (self.spn_leg_y.value() == 0):
                    leg = self.axes.legend(**{LEGEND_NCOL_KEY: ncols})
                else:
                    leg = self.axes.legend(
                        bbox_to_anchor=(self.spn_leg_x.value(), self.spn_leg_y.value()),
                        loc=10,
                        **{LEGEND_NCOL_KEY: ncols},
                    )

            leg.set_zorder(999)
            try:
                leg.set_draggable(state=True)
            except AttributeError:
                # For older version of matplotlib
                leg.draggable(state=True)
        else:
            self.axes.legend_ = None

        self.update_plot_size()

        self.canvas.draw()

        self.plot_tabwidget.setCurrentIndex(0)
        # plt.close(self.custplotfigure)#this closes reference to self.custplotfigure

    def update_plot_size(self):
        if self.dynamic_plot_size.isChecked():
            self.widget_plot.setMinimumWidth(10)
            self.widget_plot.setMaximumWidth(16777215)
            self.widget_plot.setMinimumHeight(10)
            self.widget_plot.setMaximumHeight(16777215)
            # self.widget_plot.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        else:
            width_inches, height_inches = mpl.rcParams["figure.figsize"]
            screen_dpi = QApplication.screens()[0].logicalDotsPerInch()
            width_pixels = width_inches * screen_dpi
            height_pixels = height_inches * screen_dpi
            self.canvas.setFixedSize(int(width_pixels), int(height_pixels))
            self.widget_plot.setFixedWidth(
                int(max(self.canvas.size().width(), self.mpltoolbar.size().width()))
            )
            self.widget_plot.setFixedHeight(
                int(self.canvas.size().height() + self.mpltoolbar.size().height() * 3)
            )

    def storesettings(self):
        self.ms.settingsdict["custplot_table1"] = str(self.tab1_table.currentText())
        self.ms.settingsdict["custplot_xcol1"] = str(self.tab1_xcol.currentText())
        self.ms.settingsdict["custplot_ycol1"] = str(self.tab1_ycol.currentText())
        self.ms.settingsdict["custplot_table2"] = str(self.tab2_table.currentText())
        self.ms.settingsdict["custplot_xcol2"] = str(self.tab2_xcol.currentText())
        self.ms.settingsdict["custplot_ycol2"] = str(self.tab2_ycol.currentText())
        self.ms.settingsdict["custplot_table3"] = str(self.tab3_table.currentText())
        self.ms.settingsdict["custplot_xcol3"] = str(self.tab3_xcol.currentText())
        self.ms.settingsdict["custplot_ycol3"] = str(self.tab3_ycol.currentText())
        self.ms.settingsdict["custplot_filter1_1"] = str(
            self.tab1_filtercol1.currentText()
        )
        self.ms.settingsdict["custplot_filter2_1"] = str(
            self.tab1_filtercol2.currentText()
        )
        self.ms.settingsdict["custplot_filter1_2"] = str(
            self.tab2_filtercol1.currentText()
        )
        self.ms.settingsdict["custplot_filter2_2"] = str(
            self.tab2_filtercol2.currentText()
        )
        self.ms.settingsdict["custplot_filter1_3"] = str(
            self.tab3_filtercol1.currentText()
        )
        self.ms.settingsdict["custplot_filter2_3"] = str(
            self.tab3_filtercol2.currentText()
        )
        self.ms.settingsdict["custplot_filter1_1_selection"] = []
        self.ms.settingsdict["custplot_filter2_1_selection"] = []
        self.ms.settingsdict["custplot_filter1_2_selection"] = []
        self.ms.settingsdict["custplot_filter2_2_selection"] = []
        self.ms.settingsdict["custplot_filter1_3_selection"] = []
        self.ms.settingsdict["custplot_filter2_3_selection"] = []
        for item in self.tab1_filter1.selectedItems():
            self.ms.settingsdict["custplot_filter1_1_selection"].append(
                str(item.text())
            )
        for item in self.tab1_filter2.selectedItems():
            self.ms.settingsdict["custplot_filter2_1_selection"].append(
                str(item.text())
            )
        for item in self.tab2_filter1.selectedItems():
            self.ms.settingsdict["custplot_filter1_2_selection"].append(
                str(item.text())
            )
        for item in self.tab2_filter2.selectedItems():
            self.ms.settingsdict["custplot_filter2_2_selection"].append(
                str(item.text())
            )
        for item in self.tab3_filter1.selectedItems():
            self.ms.settingsdict["custplot_filter1_3_selection"].append(
                str(item.text())
            )
        for item in self.tab3_filter2.selectedItems():
            self.ms.settingsdict["custplot_filter2_3_selection"].append(
                str(item.text())
            )
        self.ms.settingsdict["custplot_plottype1"] = str(
            self.tab1_plot_type.currentText()
        )
        self.ms.settingsdict["custplot_plottype2"] = str(
            self.tab2_plot_type.currentText()
        )
        self.ms.settingsdict["custplot_plottype3"] = str(
            self.tab3_plot_type.currentText()
        )
        self.ms.settingsdict["custplot_maxtstep"] = self.spn_max_tstep.value()
        self.ms.settingsdict["custplot_legend"] = self.create_legend.isChecked()
        self.ms.settingsdict["custplot_grid"] = self.grid.isChecked()
        # self.ms.settingsdict['custplot_title'] = unicode(self.axes.get_title())
        # self.ms.settingsdict['custplot_xtitle'] = unicode(self.axes.get_xlabel())
        # self.ms.settingsdict['custplot_ytitle'] = unicode(self.axes.get_ylabel())
        self.ms.settingsdict["custplot_tabwidget"] = self.tab_widget.currentIndex()
        self.ms.settingsdict["custplot_regular_xaxis_interval"] = (
            self.regular_xaxis_interval.isChecked()
        )
        self.ms.save_settings()

        self.ms.save_settings(self.custplot_last_used_style_settingskey)

    def select_in_filterlist_from_selection(self, filter_listwidget, filter_combobox):
        current_column = ru(filter_combobox.currentText())
        if not current_column:
            return
        selected_values = common_utils.getselectedobjectnames(
            column_name=current_column
        )
        [
            filter_listwidget.item(nr).setSelected(True)
            for nr in range(filter_listwidget.count())
            if ru(filter_listwidget.item(nr).text()) in selected_values
        ]

    def uncheck_settings(self, current_index):
        if current_index == 0:
            self.chart_settings.setChecked(False)
            self.styles_settings.setChecked(False)
            pass
        elif current_index == 1:
            self.chart_settings.setChecked(True)
            self.styles_settings.setChecked(True)

        set_groupbox_children_visibility(self.styles_settings)
        set_groupbox_children_visibility(self.chart_settings)

    def tabwidget_resize(self, tabwidget):
        current_index = tabwidget.currentIndex()
        for tabnr in range(tabwidget.count()):
            if tabnr != current_index:
                tabwidget.widget(tabnr).setSizePolicy(
                    QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored
                )
        tab = tabwidget.currentWidget()
        tab.setSizePolicy(
            QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred
        )
        tab.adjustSize()

    @common_utils.general_exception_handler
    def start_csv_dialog(self):
        data = self.draw_plot_all(only_get_data=True)
        self.save_file_dialog = SaveToCsvDialog(self, data)


class PandasCalculations(object):
    def __init__(self, gridlayout):

        self.widget = qgis.PyQt.QtWidgets.QWidget()

        # General settings
        self.rule_label = qgis.PyQt.QtWidgets.QLabel("Resample rule")
        self.rule = qgis.PyQt.QtWidgets.QLineEdit()
        for wid in [self.rule_label, self.rule]:
            wid.setToolTip(defs.pandas_rule_tooltip())

        _label = "Resample base" if pd.__version__ < "1.1.0" else "Resample offset"
        self.offset_label = qgis.PyQt.QtWidgets.QLabel(_label)
        self.offset = qgis.PyQt.QtWidgets.QLineEdit()
        for wid in [self.offset_label, self.offset]:
            wid.setToolTip(defs.pandas_base_tooltip())

        self.how_label = qgis.PyQt.QtWidgets.QLabel("Resample how")
        self.how = qgis.PyQt.QtWidgets.QLineEdit()
        for wid in [self.how_label, self.how]:
            wid.setToolTip(defs.pandas_how_tooltip())

        # Moving average:
        self.window_label = qgis.PyQt.QtWidgets.QLabel("Rolling mean window")
        self.window = qgis.PyQt.QtWidgets.QLineEdit("")
        self.center_label = qgis.PyQt.QtWidgets.QLabel("Rolling mean center")
        self.center = qgis.PyQt.QtWidgets.QCheckBox()
        self.center.setChecked(True)
        for wid in [self.window_label, self.window]:
            wid.setToolTip(
                ru(
                    QCoreApplication.translate(
                        "PandasCalculations",
                        "The number of timesteps in each moving average (rolling mean) mean\n"
                        "The result is stored at the center timestep of each mean.\n"
                        "See Pandas pandas.DataFrame.rolling documentation for more info.\n"
                        "No rolling mean if field is empty.",
                    )
                )
            )

        for wid in [self.center_label, self.center]:
            wid.setToolTip(
                ru(
                    QCoreApplication.translate(
                        "PandasCalculations",
                        "Check (default) to store the rolling mean at the center timestep.\n"
                        "Uncheck to store the rolling mean at the last timestep.\n"
                        "See Pandas pandas.rolling_mean documentation for more info.",
                    )
                )
            )

        for lineedit in [self.rule, self.offset, self.how, self.window, self.center]:
            # lineedit.sizeHint()setFixedWidth(122)
            lineedit.sizePolicy().setHorizontalPolicy(
                qgis.PyQt.QtWidgets.QSizePolicy.Preferred
            )

        maximumwidth = 0
        for label in [
            self.rule_label,
            self.offset_label,
            self.how_label,
            self.window_label,
            self.center_label,
        ]:
            testlabel = qgis.PyQt.QtWidgets.QLabel()
            testlabel.setText(label.text())
            maximumwidth = max(maximumwidth, testlabel.sizeHint().width())
        testlabel = None
        for label in [
            self.rule_label,
            self.offset_label,
            self.how_label,
            self.window_label,
            self.center_label,
        ]:
            label.setFixedWidth(maximumwidth)
            # label.setMinimumWidth(maximumwidth)
            label.sizePolicy().setHorizontalPolicy(
                qgis.PyQt.QtWidgets.QSizePolicy.Fixed
            )

        hline = horizontal_line()
        hline.sizePolicy().setHorizontalPolicy(qgis.PyQt.QtWidgets.QSizePolicy.Fixed)
        gridlayout.addWidget(hline)
        for col1, col2 in [
            (self.rule_label, self.rule),
            (self.offset_label, self.offset),
            (self.how_label, self.how),
            (self.window_label, self.window),
            (self.center_label, self.center),
        ]:
            current_row = gridlayout.rowCount()

            try:
                col1.setMaximumHeight(27)
                col2.setMaximumHeight(27)
            except:
                pass

            gridlayout.addWidget(col1, current_row, 0)
            gridlayout.addWidget(col2, current_row, 1)

    def use_pandas(self):
        if self.rule.text() or self.window.text():
            return True
        else:
            return False

    def calculate(self, df):
        # Resample
        rule = self.rule.text()
        offset = self.offset.text() if self.offset.text() else None

        if pd.__version__ < "1.1.0":
            base = 0 if offset is None else offset
            try:
                base = int(base)
            except ValueError:
                common_utils.MessagebarAndLog.critical(
                    bar_msg=ru(
                        QCoreApplication.translate(
                            "PandasCalculations", "Resample base must be an integer"
                        )
                    )
                )
                # Rule is set to None to skip resampling
                rule = None
            else:
                resample_kwargs = {"base": base}
        else:
            resample_kwargs = {"offset": offset}

        if rule:
            how = self.how.text() if self.how.text() else "mean"
            if pd.__version__ > "0.18.0":
                # new api for pandas >=0.18
                df = getattr(df.resample(rule, **resample_kwargs), how)()
            else:
                # old pandas
                df = df.resample(rule, how=how, base=base)

        # Rolling mean
        window = self.window.text()
        if window:
            try:
                window = int(window)
            except ValueError:
                common_utils.MessagebarAndLog.critical(
                    bar_msg=ru(
                        QCoreApplication.translate(
                            "PandasCalculations",
                            "Rolling mean window must be an integer",
                        )
                    )
                )
            else:
                try:
                    # Pandas version >= '0.18.0'
                    df = df.rolling(window, center=self.center.isChecked()).mean()
                except AttributeError:
                    df = pd.rolling_mean(
                        df, window=window, center=self.center.isChecked()
                    )

        return df


def horizontal_line():
    line = qgis.PyQt.QtWidgets.QFrame()
    line.setGeometry(qgis.PyQt.QtCore.QRect(320, 150, 118, 3))
    line.setFrameShape(qgis.PyQt.QtWidgets.QFrame.HLine)
    line.setFrameShadow(qgis.PyQt.QtWidgets.QFrame.Sunken)
    return line


class SaveToCsvDialog(QtWidgets.QDialog):
    def __init__(self, parent, data):
        super().__init__(parent)
        self.setAttribute(qgis.PyQt.QtCore.Qt.WA_DeleteOnClose)
        self.setWindowTitle(
            QCoreApplication.translate("SaveToCsvDialog", "Save as csv")
        )

        self.setLayout(QtWidgets.QVBoxLayout())
        row = QtWidgets.QWidget()
        row.setLayout(qgis.PyQt.QtWidgets.QHBoxLayout())
        row.layout().setContentsMargins(0, 0, 0, 0)
        self.layout().addWidget(row)

        row.layout().addWidget(
            QtWidgets.QLabel(QCoreApplication.translate("SaveToCsvDialog", "Filename"))
        )
        self.filename = qgis.gui.QgsFileWidget()
        self.filename.setStorageMode(qgis.gui.QgsFileWidget.SaveFile)
        self.filename.setDialogTitle(
            QCoreApplication.translate("SaveToCsvDialog", "Filename")
        )
        row.layout().addWidget(self.filename)
        self.filename.setFilter("csv (*.csv)")

        self.as_columns = QtWidgets.QRadioButton("Series as columns")
        self.as_rows = QtWidgets.QRadioButton("Series as rows")
        self.as_columns.setChecked(True)
        self.layout().addWidget(self.as_rows)
        self.layout().addWidget(self.as_columns)

        self.data = data

        self.save_button = QtWidgets.QPushButton("Save")
        self.layout().addWidget(self.save_button)
        self.save_button.clicked.connect(self.save_data)
        self.show()

    @common_utils.general_exception_handler
    def save_data(self, *args):
        filename = self.filename.filePath()
        if not filename:
            MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "SaveToCsvDialog", "Must give filename"
                )
            )
            return
        common_utils.start_waiting_cursor()
        if self.as_rows.isChecked():
            dfs = []
            for series in self.data:
                df = pd.DataFrame()
                df["index"] = self.parse_index(series[0])
                df["values"] = series[0].values
                df["label"] = series[1]
                df = df.sort_values(by=["index"])
                dfs.append(df)
            df = pd.concat(dfs, axis=0)
            df.to_csv(filename, sep=";", encoding="utf-8", index_label="rowid")
        else:
            dfs = []
            for series in self.data:
                df = pd.DataFrame(
                    series[0].values,
                    index=self.parse_index(series[0]),
                    columns=[series[1]],
                )
                if not len(df) == len(df.loc[~df.index.duplicated(keep="first")]):
                    MessagebarAndLog.critical(
                        bar_msg=QCoreApplication.translate(
                            "SaveToCsvDialog",
                            "Unable to export as columns (the x-axis contained duplicates)",
                        )
                    )
                    common_utils.stop_waiting_cursor()
                    return
                dfs.append(df)
            df = pd.concat(dfs, axis=1)  # .sort_index()
            df.index.name = "index"
            df = df.reset_index()
            df.to_csv(filename, sep=";", encoding="utf-8", index_label="rowid")
        common_utils.stop_waiting_cursor()
        self.close()

    def parse_index(self, array):
        if hasattr(array, "date_time"):
            try:
                index = pd.to_datetime(array.date_time, format="mixed")
            except ValueError:
                index = array.date_time
        else:
            index = array.numx
        return index
