# -*- coding: utf-8 -*-
"""
/***************************************************************************
 This part of the Midvatten plugin is more or less just a small tweak of
 the ARPAT plugin developed by Martin Dobias for Faunalia:

# Copyright 2006-2007 by ARPAT-SIRA (www.arpat.toscana.it http://sira.arpat.toscana.it/sira/)
# Licenced under GNU GPL (General Public License) v2
# Developed by Martin Dobias for Faunalia (www.faunalia.it)
# For details send a mail to PFR_SIRA@arpat.toscana.it
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation (www.fsf.org); version 2 of the License, or any later version.
#
#
# Copyright 2006-2007 di ARPAT-SIRA (www.arpat.toscana.it http://sira.arpat.toscana.it/sira/)
# Rilasciato sotto licenza GNU GPL (General Public License) v2
# Sviluppato da Martin Dobias per Faunalia (www.faunalia.it)
# Per ulteriori informazioni inviare una mail a PFR_SIRA@arpat.toscana.it
#
# Questo programma rientra nel software libero; possibile redistribuirlo e/o modificarlo
# sotto i termini della licenza GNU General Public License come pubblicato da
# Free Software Foundation (www.fsf.org); versione 2 o superiore della licenza.
 
 ---------- THE ARPAT PLUGIN IS INCLUDED IN MIDVATTEN PLUGIN AND MODIFIED FOR SQLITE DATA BY:
        begin                : 2012-03-06
        copyright            : (C) 2011 by joskal
        email                : groundwatergis [at] gmail.com
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


import unicodedata
from functools import partial  # only to get combobox signals to work

from qgis.PyQt import QtPrintSupport, QtWidgets, QtCore, QtGui
from qgis.PyQt.QtCore import QCoreApplication

from midvatten.definitions import midvatten_defs as defs
from midvatten.tools.utils import common_utils, db_utils
from midvatten.tools.utils.common_utils import returnunicode as ru


class Stratigraphy(object):

    def __init__(self, iface, layer=None, settingsdict={}):
        self.iface = iface
        self.stratitable = (
            defs.stratigraphy_table()
        )  # no longer an option to select other tables than 'stratigraphy'
        self.layer = layer
        self.store = None
        # self.showSurvey()
        self.w = None

    def initStore(self):
        try:  # return from SurveyStore is stored in self.store only if no object belonging to DataError class is created
            self.store = SurveyStore(self.stratitable)
        except (
            DataError
        ) as e:  # if an object 'e' belonging to DataError is created, then do following
            try:
                # fix_print_with_import
                print("Load failed due: " + e.problem)
            except:
                pass
            self.store = None

    def showSurvey(self):
        # lyr = self.iface.activeLayer() # THIS IS TSPLOT-method, GETS THE SELECTED LAYER
        lyr = self.layer
        ids = lyr.selectedFeatureIds()
        if len(ids) == 0:
            common_utils.pop_up_info(
                ru(QCoreApplication.translate(" Stratigraphy", "No selection")),
                ru(
                    QCoreApplication.translate(
                        " Stratigraphy", "No features are selected"
                    )
                ),
            )
            return
        # initiate the datastore if not yet done
        self.initStore()
        common_utils.start_waiting_cursor()  # Sets the mouse cursor to wait symbol
        try:  # return from store.getData is stored in data only if no object belonging to DataSanityError class is created
            self.data = self.store.getData(ids, lyr)  # added lyr as an argument!!!
        except (
            DataSanityError
        ) as e:  # if an object 'e' belonging to DataSanityError is created, then do following
            print("DataSanityError %s" % str(e))
            common_utils.stop_waiting_cursor()
            common_utils.pop_up_info(
                ru(
                    QCoreApplication.translate(
                        " Stratigraphy", "Data sanity problem, obsid: %s\n%s"
                    )
                )
                % (e.sond_id, e.message)
            )
            return
        except (
            Exception
        ) as e:  # if an object 'e' belonging to DataSanityError is created, then do following
            print("exception : %s" % str(e))
            common_utils.stop_waiting_cursor()
            common_utils.MessagebarAndLog.critical(
                bar_msg=ru(
                    QCoreApplication.translate(
                        " Stratigraphy",
                        "The stratigraphy plot failed, check Midvatten plugin settings and your data!",
                    )
                )
            )
            return
        common_utils.stop_waiting_cursor()  # Restores the mouse cursor to normal symbol
        # show widget
        w = SurveyDialog()
        # w.widget.setData2_nosorting(data)  #THIS IS IF DATA IS NOT TO BE SORTED!!
        w.widget.setData(self.data)  # THIS IS ONLY TO SORT DATA!!
        w.show()
        self.w = w  # save reference so it doesn't get deleted immediately        This has to be done both here and also in midvatten instance


class SurveyInfo(object):  # This class is to define the data structure...

    def __init__(
        self, obsid="", top_lvl=0, coord=None, strata=None, length=None
    ):  # _CHANGE_ added obsid
        self.obsid = obsid  # _CHANGE_
        self.top_lvl = top_lvl
        self.coord = coord
        self.length = length
        if strata == None:
            strata = []
        self.strata = strata

    def __repr__(
        self,
    ):  # _INFO_ : A class can control what this function returns for its instances by defining a __repr__() method.
        return "SURVEY('%s', %f, '%s')" % (
            str(self.obsid),
            self.top_lvl,
            self.coord,
        )  # _CHANGE_


class StrataInfo(object):
    def __init__(
        self,
        stratid=0,
        depth_top=0,
        depth_bot=0,
        geology="",
        geo_short="",
        hydro="",
        Comment="",
        development="",
    ):
        self.stratid = stratid  # This is id no for the geological information (1 = uppermost stratigraphy layer)
        self.geology = geology  # This is full text description of stratigraphy (the geologic descripition, e.g. "sandy till")
        self.depth_top = depth_top  # This is depth to top of the stratigraphy layer
        self.depth_bot = depth_bot  # This is depth to bottom for the stratigraphy layer
        self.geo_short = geo_short  # This is short name for the geology of the stratigraphy layer, also used for symbology and color
        self.comment = Comment  # Comment for the stratigraphy layer
        self.hydro = hydro  # Water loss or similar measurement of layer permeability, given as 1, 2, 3, etc, see below
        self.development = development

    def __repr__(self):
        return "strata(%d, '%s', '%s', '%s', %f-%f)" % (
            self.stratid,
            self.hydro,
            self.geology,
            self.geo_short,
            self.depth_top,
            self.depth_bot,
        )


class SurveyStore(object):
    def __init__(self, stratitable):
        self.stratitable = stratitable
        self.warning_popup = True

    def getData(
        self, featureIds, vectorlayer
    ):  # THIS FUNCTION IS ONLY CALLED FROM ARPATPLUGIN/SHOWSURVEY
        """get data from databases for array of features specified by their IDs"""
        surveys = self._getDataStep1(featureIds, vectorlayer)
        if not surveys:
            raise DataSanityError(
                "feature ids {}".format(", ".join([str(x) for x in featureIds])),
                "Could not get data from layer!",
            )
        try:
            data_loading_status, surveys = self._getDataStep2(surveys)
        except:
            data_loading_status = False
        if data_loading_status == True:
            surveys = self.sanityCheck(surveys)
            return surveys
        else:
            raise DataSanityError("Unknown obsid", "Dataloading failed!")

    def _getDataStep1(self, featureIds, vlayer):
        """STEP 1: get data from selected layer"""  # _CHANGE_ Completely revised to TSPLot method
        provider = (
            vlayer.dataProvider()
        )  # _CHANGE_  THIS IS TSPLOT-method, we do not use the db loadeds by ARPAT _init_ surveystore
        obsid_col_no = provider.fieldNameIndex(
            "obsid"
        )  # _CHANGE_  THIS IS TSPLOT-method To find the column named 'obsid'
        if obsid_col_no == -1:
            obsid_col_no = provider.fieldNameIndex("OBSID")  # backwards compatibility
        h_gs_col_no = provider.fieldNameIndex(
            "h_gs"
        )  # _CHANGE_  THIS IS TSPLOT-method To find the column named 'h_gs'
        h_toc_col_no = provider.fieldNameIndex(
            "h_toc"
        )  # _CHANGE_  THIS IS TSPLOT-method To find the column named 'h_toc'
        if h_gs_col_no == -1 and h_toc_col_no == -1:
            h_gs_col_no = provider.fieldNameIndex("SURF_LVL")  # backwards compatibility
        length_col_no = provider.fieldNameIndex("length")
        surveys = {}
        strata = {}
        if vlayer:
            n_f = vlayer.selectedFeatureCount()
            if n_f > 0:
                # Load all selected observation points
                ob = vlayer.getSelectedFeatures()
                obsid_list = [None] * n_f  # List for obsid
                toplvl_list = [None] * n_f  # List for top_lvl
                coord_list = [None] * n_f  # List for coordinates
                for i, feature in enumerate(
                    ob
                ):  # Loop through all selected objects, a plot is added for each one of the observation points (i.e. selected objects)
                    attributes = feature.attributes()
                    obsid = ru(attributes[obsid_col_no])
                    obsid_list[i] = (
                        obsid  # Copy value in column obsid in the attribute list
                    )
                    h_gs = ru(attributes[h_gs_col_no])
                    level_val = None
                    error_msg = False
                    if h_gs:
                        try:
                            level_val = float(h_gs)
                        except ValueError:
                            error_msg = ru(
                                QCoreApplication.translate(
                                    "Stratigraphy", "Converting to float failed."
                                )
                            )
                        except Exception as e:
                            error_msg = e
                    if level_val is None:
                        h_toc = ru(attributes[h_toc_col_no])
                        try:
                            level_val = float(h_toc)
                        except:
                            using = "-1"
                            level_val = -1
                        else:
                            using = "h_toc"

                        common_utils.MessagebarAndLog.warning(
                            bar_msg=ru(
                                QCoreApplication.translate(
                                    "Stratigraphy",
                                    "Obsid %s: using h_gs '%s' failed, using '%s' instead.",
                                )
                            )
                            % (obsid, h_gs, using),
                            log_msg=ru(QCoreApplication.translate("Stratigraphy", "%s"))
                            % error_msg,
                            duration=90,
                        )

                        if self.warning_popup:
                            common_utils.pop_up_info(
                                ru(
                                    QCoreApplication.translate(
                                        "Stratigraphy",
                                        "Warning, h_gs is missing. See messagebar.",
                                    )
                                )
                            )
                            self.warning_popup = False
                    toplvl_list[i] = level_val
                    coord_list[i] = feature.geometry().asPoint()

                    if length_col_no == -1:
                        length = None
                    else:
                        try:
                            length = float(ru(attributes[length_col_no]))
                        except:
                            length = None

                    # add to array
                    surveys[obsid_list[i]] = SurveyInfo(
                        obsid_list[i], toplvl_list[i], coord_list[i], length=length
                    )
        else:
            common_utils.pop_up_info(
                ru(QCoreApplication.translate("Stratigraphy", "getDataStep1 failed"))
            )  # _CHANGE_ for debugging
        return surveys

    def _getDataStep2(self, surveys):
        """STEP 2: get strata information for every point"""
        dbconnection = db_utils.DbConnectionManager()
        for obsid, survey in surveys.items():
            sql = r"""SELECT stratid, depthtop, depthbot, geology, trim(lower(geoshort)), trim(capacity), comment, development FROM """
            sql += self.stratitable  # MacOSX fix1
            sql += r""" WHERE obsid = '"""
            sql += str(
                obsid
            )  # THIS IS WHERE THE KEY IS GIVEN TO LOAD STRATIGRAPHY FOR CHOOSEN obsid
            sql += """' ORDER BY stratid"""
            recs = dbconnection.execute_and_fetchall(sql)
            if not recs:
                if survey.length is not None:
                    recs.append([1, 0.0, survey.length, "", "", "", "", ""])
            # parse attributes
            prev_depthbot = 0
            for record in recs:
                if (
                    common_utils.isinteger(record[0])
                    and common_utils.isfloat(record[1])
                    and common_utils.isfloat(record[2])
                ):
                    stratigaphy_id = record[0]  # Stratigraphy layer no
                    depthtotop = record[1]  # depth to top of stratrigraphy layer
                    depthtobot = record[2]  # depth to bottom of stratrigraphy layer
                else:
                    raise DataSanityError(
                        str(obsid),
                        ru(
                            QCoreApplication.translate(
                                "SurveyStore",
                                "Something bad with stratid, depthtop or depthbot!",
                            )
                        ),
                    )
                    stratigaphy_id = (
                        1  # when something went wrong, put it into first layer
                    )
                    depthtotop = 0
                    depthtobot = 999  # default value when something went wrong
                if record[
                    3
                ]:  # Must check since it is not possible to print null values as text in qt widget
                    geology = record[3]  # Geology full text
                else:
                    geology = " "
                geo_short_txt = record[
                    4
                ]  # geo_short might contain national special characters
                if geo_short_txt:  # Must not try to encode an empty field
                    geo_short = (
                        unicodedata.normalize("NFKD", geo_short_txt)
                        .encode("ascii", "ignore")
                        .decode("ascii")
                    )  # geo_short normalized for symbols and color
                else:  # If the field is empty, then store an empty string
                    geo_short = ""
                hydro = record[5]  # waterloss (hydrogeo parameter) for color
                if record[
                    6
                ]:  # Must check since it is not possible to print null values as text in qt widget
                    comment = record[6]  #
                else:
                    comment = " "
                if record[
                    7
                ]:  # Must check since it is not possible to print null values as text in qt widget
                    development = record[7]  #
                else:
                    development = " "

                # Add layer if there is a gap
                if depthtotop != prev_depthbot:
                    stratid = len(survey.strata) + 1
                    st = StrataInfo(stratid, prev_depthbot, depthtotop)
                    survey.strata.append(st)

                stratid = len(survey.strata) + 1
                st = StrataInfo(
                    stratid,
                    depthtotop,
                    depthtobot,
                    geology,
                    geo_short,
                    hydro,
                    comment,
                    development,
                )
                survey.strata.append(st)
                prev_depthbot = depthtobot

            data_loading_status = True
        dbconnection.closedb()
        return data_loading_status, surveys

    def sanityCheck(self, _surveys):
        """does a sanity check on retreived data"""
        surveys = {}
        for obsid, survey in _surveys.items():
            # check whether there's at least one strata information
            if len(survey.strata) == 0:
                # raise DataSanityError(str(obsid), "No strata information")
                try:
                    print(str(obsid) + " has no strata information")
                except:
                    pass
                continue
                # del surveys[obsid]#simply remove the item without strata info
            else:
                # check whether the depths are valid
                top1 = survey.strata[0].depth_top
                bed1 = survey.strata[0].depth_bot
                for strato in survey.strata[1:]:
                    # top (n) < top (n+1)
                    if top1 > strato.depth_top:
                        raise DataSanityError(
                            str(obsid),
                            ru(
                                QCoreApplication.translate(
                                    "SurveyStore",
                                    "Top depth is incorrect (%.2f > %.2f)",
                                )
                            )
                            % (top1, strato.depth_top),
                        )
                    # bed (n) < bed (n+1)
                    if bed1 > strato.depth_bot:
                        raise DataSanityError(
                            str(obsid),
                            ru(
                                QCoreApplication.translate(
                                    "SurveyStore",
                                    "Bed depth is incorrect (%.2f > %.2f)",
                                )
                            )
                            % (bed1, strato.depth_bot),
                        )
                    # bed (n) = top (n+1)
                    if bed1 != strato.depth_top:
                        raise DataSanityError(
                            str(obsid),
                            ru(
                                QCoreApplication.translate(
                                    "SurveyStore",
                                    "Top and bed depth don't match (%.2f != %.2f)",
                                )
                            )
                            % (bed1, strato.depth_top),
                        )

                    top1 = strato.depth_top
                    bed1 = strato.depth_bot
            surveys[obsid] = survey
        return surveys


class SurveyWidget(QtWidgets.QFrame):

    def __init__(self, parent=None):
        QtWidgets.QFrame.__init__(self, parent)
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setLineWidth(3)
        self.sondaggio = {}
        # In the original ARPAT plugin the following convention was used F = points, T = vertical lines and  C = horizontal lines
        """  Following standard Qt Colors exist
            Qt.white            White (#ffffff)
            Qt.black            Black (#000000)
            Qt.red            Red (#ff0000)
            Qt.darkRed            Dark red (#800000)
            Qt.green            Green (#00ff00)
            Qt.darkGreen            Dark green (#008000)
            Qt.blue            Blue (#0000ff)
            Qt.darkBlue            Dark blue (#000080)
            Qt.cyan            Cyan (#00ffff)
            Qt.darkCyan            Dark cyan (#008080)
            Qt.magenta            Magenta (#ff00ff)
            Qt.darkMagenta            Dark magenta (#800080)
            Qt.yellow            Yellow (#ffff00)
            Qt.darkYellow            Dark yellow (#808000)
            Qt.gray            Gray (#a0a0a4)
            Qt.darkGray            Dark gray (#808080)
            Qt.lightGray            Light gray (#c0c0c0)
            Qt.transparent    a transparent black value (i.e., PySide.QtGui.QColor (0, 0, 0, 0))
        """
        # ------------------Please note!---------------------
        # Due to unicode normalize in getData function below, swedish national characters will be
        # transformed to a, a, and o when read from the stratigraphy table
        self.geoColorSymbols = defs.geocolorsymbols()
        # print(self.geoColorSymbols)#debug
        self.hydroColors = defs.hydrocolors()
        # print(self.hydroColors)#debug
        self.switchGeoHydro = 0  # Default is to show colors according to geo
        self.GeoOrComment = "geology"  # Default is that text =  geology description
        self.showDesc = True  # Default is to show text

    def setData(self, sondaggio):
        self.sondaggio = sondaggio
        # find out whether the overall distance is bigger on x or y axis
        # so columns will be sorted by their x or y coordinate
        inf = 999999999
        (x_min, y_min, x_max, y_max) = (inf, inf, -inf, -inf)
        for s in sondaggio.values():
            (x, y) = (s.coord.x(), s.coord.y())
            if x < x_min:
                x_min = x
            if y < y_min:
                y_min = y
            if x > x_max:
                x_max = x
            if y > y_max:
                y_max = y

        if x_max - x_min > y_max - y_min:
            # sort using x coordinate
            cc = lambda a: a.coord.x()
            # cc = lambda a,b: cmp(a.coord.x(), b.coord.x())
        else:
            # sort using y coordinate
            cc = lambda a: a.coord.y()
            # cc = lambda a,b: cmp(a.coord.y(), b.coord.y())
        order = sorted(self.sondaggio.values(), key=cc)
        self.order = order  # THIS SHOULD BE REPLACED BY 2L BELOW
        # for o in order:
        #    self.order.append(o.obsid)   # _CHANGE_  Should be fixed

    def setData2_nosorting(self, sondaggio):  # Without sorting
        self.order = []
        for s in sondaggio.values():
            self.order.append(s)

    def setType(self, switchGeoHydro):
        """sets whether fill columns with Geo colors (0) or Hydro colors (1)"""
        self.switchGeoHydro = switchGeoHydro
        self.update()

    def setGeoOrComment(self, GeoOrComment):
        """sets whether to print geology ("geology") or Comment ("comment")"""
        self.GeoOrComment = GeoOrComment
        self.update()

    def setShowDesc(self, show):
        self.showDesc = show
        self.update()

    def paintEvent(self, event):
        """redraws the whole widget's area"""

        QtWidgets.QFrame.paintEvent(self, event)

        # check whether there's a survey to show
        if len(self.sondaggio) == 0:
            p = QtGui.QPainter(self)
            p.drawText(
                self.rect(),
                QtCore.Qt.AlignCenter | QtCore.Qt.AlignVCenter,
                ru(QCoreApplication.translate("SurveyWidget", "No data to display")),
            )
            return

        painter = QtGui.QPainter(self)

        self.drawSurveys(self.rect(), painter)

    def drawSurveys(self, rect, painter):
        """draw surveys to specified rect with specified painter"""
        surveys = len(self.sondaggio)
        survey_width = rect.width() / surveys
        survey_height = rect.height()
        # column_width = rect.width() * 0.05
        column_width = rect.width() * 0.03
        x = 0
        margin = 4

        # find out depth interval
        depth_bot, depth_top = 999999, -999999
        for survey in self.order:
            sond = self.sondaggio[survey.obsid]
            try:
                d_top = survey.top_lvl - survey.strata[0].depth_top
                d_bed = survey.top_lvl - survey.strata[-1].depth_bot

                if d_top > depth_top:
                    depth_top = d_top
                if d_bed < depth_bot:
                    depth_bot = d_bed
            except:
                pass

        # draw surveys
        for survey in self.order:
            r = QtCore.QRect(
                int(x + margin),
                int(0 + margin),
                int(survey_width - 2 * margin),
                int(survey_height - 2 * margin),
            )
            x += survey_width
            sond = self.sondaggio[survey.obsid]
            # draw the survey
            try:
                self.drawSurvey(painter, sond, r, column_width, (depth_bot, depth_top))
            except:
                pass

    def drawSurvey(self, p, sond, sRect, column_width, interval):
        """draws one survey to rectangle in widget specified by sRect"""
        depth_top = sond.top_lvl
        depth_bot = depth_top - sond.strata[-1].depth_bot

        fm = QtGui.QFontMetrics(p.font())
        name_height = fm.height()
        depth_height = fm.height()

        # draw obsid 'name'
        label_rect = QtCore.QRect(sRect.left(), sRect.top(), sRect.width(), name_height)
        p.drawText(label_rect, QtCore.Qt.AlignVCenter, sond.obsid)

        scale = (sRect.height() - name_height - depth_height * 2) / (
            interval[1] - interval[0]
        )

        top = sRect.top() + name_height + depth_height
        y_top = top + (interval[1] - depth_top) * scale
        y_bed = top + (interval[1] - depth_bot) * scale

        # top depth
        depth_rect = QtCore.QRect(
            sRect.left(), int(y_top - depth_height), sRect.width(), int(depth_height)
        )
        p.drawText(depth_rect, QtCore.Qt.AlignVCenter, "%.1f m" % depth_top)

        # bed depth
        depth_rect = QtCore.QRect(
            sRect.left(), int(y_bed + 1), sRect.width(), int(depth_height)
        )
        p.drawText(depth_rect, QtCore.Qt.AlignVCenter, "%.1f m" % depth_bot)

        d_rect = QtCore.QRect(
            QtCore.QPoint(sRect.left(), int(y_top)),
            QtCore.QPoint(int(sRect.left() + column_width), int(y_bed)),
        )

        p.drawRect(d_rect)

        scale = d_rect.height() / (depth_top - depth_bot)
        y = d_rect.top()

        for layer in sond.strata:
            y2 = (layer.depth_bot - layer.depth_top) * scale
            # column rectangle
            c_rect = QtCore.QRect(
                QtCore.QPoint(d_rect.left(), int(y)),
                QtCore.QPoint(d_rect.right(), int(y + y2 - 1)),
            )

            # text rectangle
            t_rect = QtCore.QRect(
                QtCore.QPoint(d_rect.right() + 10, int(y)),
                QtCore.QPoint(sRect.right(), int(y + y2)),
            )

            b_type = self.geoToSymbol(
                layer.geo_short
            )  # select brush pattern depending on the geo_short
            # select brush pattern depending on usage of geo or hydro
            if self.switchGeoHydro == 0:
                color = self.textToColor(layer.geo_short, "geo")
            else:
                color = self.textToColor(layer.hydro, "hydro")
            # draw column with background color
            p.setBrush(color)
            p.drawRect(c_rect)

            # draw column with specified hatch
            p.setBrush(QtGui.QBrush(QtCore.Qt.black, b_type))
            p.drawRect(c_rect)

            # draw associated text
            if self.showDesc:
                if self.GeoOrComment == "geology":
                    p.drawText(
                        t_rect,
                        QtCore.Qt.AlignVCenter,
                        "" if layer.geology == "NULL" else layer.geology,
                    )  #'Yes' if fruit == 'Apple' else 'No'
                elif self.GeoOrComment == "comment":
                    p.drawText(
                        t_rect,
                        QtCore.Qt.AlignVCenter,
                        "" if layer.comment == "NULL" else layer.comment,
                    )
                elif self.GeoOrComment == "geoshort":
                    p.drawText(
                        t_rect,
                        QtCore.Qt.AlignVCenter,
                        "" if layer.geo_short == "NULL" else layer.geo_short,
                    )
                elif self.GeoOrComment == "hydro":
                    p.drawText(
                        t_rect,
                        QtCore.Qt.AlignVCenter,
                        "" if layer.hydro == "NULL" else layer.hydro,
                    )
                elif self.GeoOrComment == "hydro explanation":
                    if layer.hydro is None or layer.hydro == "NULL":
                        hydr = ""
                    else:
                        hydr = self.hydroColors.get(layer.hydro.strip(), "")[0]
                    p.drawText(t_rect, QtCore.Qt.AlignVCenter, hydr)

                else:
                    p.drawText(
                        t_rect,
                        QtCore.Qt.AlignVCenter,
                        "" if layer.development == "NULL" else layer.development,
                    )

            y += y2

    def textToColor(
        self, id="", type=""
    ):  # _ DEFINE (in the class method) AND USE (in this function) A DICTIONARY INSTEAD
        """returns QColor from the specified text"""

        if type == "hydro":
            if id in self.hydroColors:
                # return eval("PyQt4.QtCore.Qt" + self.hydroColors[id][2])    # Less sofisticated method to create a function call from a string (function syntax is in the string)
                return getattr(
                    QtCore.Qt, self.hydroColors[id][1]
                )  # getattr is to combine a function and a string to a combined function
            else:
                return QtCore.Qt.white
        elif type == "geo":
            # if id.lower() in self.geoColorSymbols:
            if id in self.geoColorSymbols:
                try:  # first we assume it is a predefined Qt color, hence use PyQt4.QtCore.Qt
                    # return getattr(PyQt4.QtCore.Qt, self.geoColorSymbols[id.lower()][1])
                    return getattr(QtCore.Qt, self.geoColorSymbols[id][1])
                except:  # otherwise it must be a SVG 1.0 color name, then it must be created by QtGui.QColor instead
                    return QtGui.QColor(self.geoColorSymbols[id][1])
            else:
                return QtCore.Qt.white

    def geoToSymbol(
        self, id=""
    ):  # A function to return fill type for the box representing the stratigraphy layer
        """returns Symbol from the specified text"""
        # if id.lower() in self.geoColorSymbols:

        if id in self.geoColorSymbols:
            # return getattr(PyQt4.QtCore.Qt, self.geoColorSymbols[id.lower()][0])   # Or possibly [0]?
            return getattr(QtCore.Qt, self.geoColorSymbols[id][0])  # Or possibly [0]?
        else:
            return QtCore.Qt.NoBrush

    def printDiagram(self):
        """outputs the diagram to the printer (or PDF)"""
        printer = QtPrintSupport.QPrinter(QtPrintSupport.QPrinter.HighResolution)

        # set defaults
        printer.setOrientation(QtPrintSupport.QPrinter.Landscape)

        # setting output file name results in not opening print dialog on Win
        # printer.setOutputFileName("arpat.pdf")

        # show print dialog
        dlg = QtPrintSupport.QPrintDialog(printer, self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return

        p = QtGui.QPainter()
        p.begin(printer)

        rect = printer.pageRect()
        # print "rect: ", rect.left(), rect.top(), rect.width(), rect.height()

        self.drawSurveys(rect, p)

        p.end()


class SurveyDialog(QtWidgets.QDialog):

    def __init__(self, parent=None):
        QtWidgets.QDialog.__init__(self, parent)

        self.resize(QtCore.QSize(500, 250))
        self.setWindowFlags(
            QtCore.Qt.Window
            | QtCore.Qt.WindowMinimizeButtonHint
            | QtCore.Qt.WindowMaximizeButtonHint
            | QtCore.Qt.WindowCloseButtonHint
        )

        self.setWindowTitle(
            ru(QCoreApplication.translate("SurveyDialog", "Identify Results"))
        )

        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.setMargin(5)

        self.layout2 = QtWidgets.QHBoxLayout()

        self.widget = SurveyWidget()
        self.layout.addWidget(self.widget)

        self.radGeo = QtWidgets.QRadioButton("Geo")
        self.radGeo.setChecked(True)  # Default is to show colors as per geo
        self.layout2.addWidget(self.radGeo)
        self.radHydro = QtWidgets.QRadioButton("Hydro")
        # self.radHydro.setChecked(False)  #Default is NOT to show colors as per hydro
        self.layout2.addWidget(self.radHydro)

        spacer_item = QtWidgets.QSpacerItem(100, 0)
        self.layout2.addItem(spacer_item)

        self.chkShowDesc = QtWidgets.QCheckBox(
            ru(QCoreApplication.translate("SurveyDialog", "Show text"))
        )
        self.chkShowDesc.setChecked(True)
        self.layout2.addWidget(self.chkShowDesc)

        self.GeologyOrCommentCBox = QtWidgets.QComboBox(self)
        self.GeologyOrCommentCBox.addItem("geology")
        self.GeologyOrCommentCBox.addItem("comment")
        self.GeologyOrCommentCBox.addItem("geoshort")
        self.GeologyOrCommentCBox.addItem("hydro")
        self.GeologyOrCommentCBox.addItem("hydro explanation")
        self.GeologyOrCommentCBox.addItem("development")
        self.layout2.addWidget(self.GeologyOrCommentCBox)

        self.btnPrint = QtWidgets.QPushButton(
            ru(QCoreApplication.translate("SurveyDialog", "Print"))
        )
        self.layout2.addWidget(self.btnPrint)

        self.btnClose = QtWidgets.QPushButton(
            ru(QCoreApplication.translate("SurveyDialog", "Close"))
        )
        self.layout2.addWidget(self.btnClose)

        self.layout.addLayout(self.layout2)

        self.btnClose.clicked.connect(lambda x: self.close())
        self.btnPrint.clicked.connect(self.widget.printDiagram)
        self.radGeo.toggled.connect(self.typeToggled)
        self.radHydro.toggled.connect(self.typeToggled)
        self.chkShowDesc.toggled.connect(self.widget.setShowDesc)
        self.GeologyOrCommentCBox.currentIndexChanged.connect(
            partial(self.ComboBoxUpdated)
        )
        # whenever the combobox is changed, function partial is used due to problems with currentindexChanged and Combobox)

    def close(self):
        self.accept()

    def typeToggled(self):
        if self.radGeo.isChecked():
            self.widget.setType(0)
        else:
            self.widget.setType(1)

    def ComboBoxUpdated(self):
        text = self.GeologyOrCommentCBox.currentText()
        self.widget.setGeoOrComment(text)


class DataSanityError(
    Exception
):  # Instances of this class is created whenever some data sanity checks fails
    """exception raised when data don't comply with some constraints"""

    def __init__(self, sond_id, message):
        self.sond_id = sond_id
        self.message = message

    def __str__(self):
        return "Sond_ID %s: %s" % (self.sond_id, self.message)


class DataError(
    Exception
):  # Instances of this class is created whenever some data accessing (by SurveyStore) fails
    """exception raised on problems accessing data"""

    def __init__(self, problem):
        self.problem = problem

    def __str__(self):
        return self.problem
