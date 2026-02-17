# -*- coding: utf-8 -*-
"""
/***************************************************************************
 This is the part of the Midvatten plugin that prepares a number of spatial views 
 in your spatialite midvatten database that are suitable for creating 3D plots with qgis2threejs.
 The spatial views are added into your qgis project group "stratigraphy_layers_for_qgis2threejs" 
                              -------------------
        begin                : 20150129
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


import os

import matplotlib as mpl
import psycopg2.errors
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QColor
from qgis.core import QgsProject

from midvatten.definitions import midvatten_defs as defs
from midvatten.tools.utils import common_utils, db_utils, midvatten_utils
from midvatten.tools.utils.common_utils import returnunicode as ru


class PrepareForQgis2Threejs(object):
    def __init__(self, iface, settingsdict={}):

        self.dbconnection = db_utils.DbConnectionManager()

        self.settingsdict = settingsdict
        self.strat_layers_dict = defs.plot_types_dict("english")
        self.symbolcolors_dict = defs.plot_colors_dict()
        # make all the keys only ascii and only lower case and also add 'strat_' as prefix
        for key, v in list(self.strat_layers_dict.items()):
            newkey = "strat_" + common_utils.return_lower_ascii_string(key)
            self.strat_layers_dict[newkey] = self.strat_layers_dict[key]
            del self.strat_layers_dict[key]
        for key, v in list(
            self.symbolcolors_dict.items()
        ):  # THIS IS NOT USED YET make all the keys only ascii and only lower case and also add 'strat_' as prefix
            newkey = "strat_" + common_utils.return_lower_ascii_string(key)
            self.symbolcolors_dict[newkey] = self.symbolcolors_dict[key]
            del self.symbolcolors_dict[key]
        self.iface = iface
        self.root = QgsProject.instance().layerTreeRoot()
        self.remove_views()
        self.drop_db_views()
        self.create_db_views()
        self.dbconnection.commit()
        self.add_layers()
        self.dbconnection.closedb()

    def add_layers(
        self,
    ):  # not tested and not ready, must fix basic styles (preferrably colors based on some definition dicitonary
        MyGroup = self.root.insertGroup(
            0, "stratigraphy_layers_for_qgis2threejs"
        )  # verify this is inserted at top

        canvas = self.iface.mapCanvas()

        list_with_all_strat_layer = list(self.strat_layers_dict.keys())

        list_with_all_strat_layer.append("strat_obs_p_for_qgsi2threejs")

        colors = []

        layer_list = []
        midvatten_utils.add_layers_to_list(
            layer_list,
            list_with_all_strat_layer,
            geometrycolumn="geometry",
            dbconnection=self.dbconnection,
        )

        for strat_layer_view in list_with_all_strat_layer:
            try:
                supplied_color = self.symbolcolors_dict[strat_layer_view]
            except KeyError:
                color = None
            else:
                try:
                    # matplotlib 2
                    color = mpl.colors.to_rgbsupplied_color()
                except AttributeError:
                    try:
                        # matplotlib 1
                        converter = mpl.colors.ColorConverter()
                        color = converter.to_rgb(supplied_color)
                        color = [x * 255 for x in color]
                    except Exception as e:
                        common_utils.MessagebarAndLog.warning(
                            bar_msg=ru(
                                QCoreApplication.translate(
                                    "PrepareForQgis2Threejs",
                                    "Setting color from dict failed",
                                )
                            ),
                            log_msg=ru(
                                QCoreApplication.translate(
                                    "PrepareForQgis2Threejs", "Error msg %s"
                                )
                            )
                            % str(e),
                        )
                        color = None

            colors.append(color)

        for idx, layer in enumerate(
            layer_list
        ):  # now loop over all the layers, add them to canvas and set colors
            if not layer.isValid():
                try:
                    print(layer.name() + " is not valid layer")
                except:
                    pass
                pass
            else:
                # TODO: Made this a comment, but there might be some hidden feature that's still needed!
                # map_canvas_layer_list.append(QgsMapCanvasLayer(layer))

                # now try to load the style file
                stylefile = os.path.join(
                    os.sep,
                    os.path.dirname(__file__),
                    "..",
                    "definitions",
                    layer.name() + ".qml",
                )
                try:
                    layer.loadNamedStyle(stylefile)
                except:
                    try:
                        print("Loading stylefile %s failed." % stylefile)
                    except:
                        pass

                color = colors[idx]
                if color:
                    current_symbol = layer.renderer().symbol()
                    current_symbol.setColor(
                        QColor.fromRgb(int(color[0]), int(color[1]), int(color[2]))
                    )

                QgsProject.instance().addMapLayers([layer], False)
                MyGroup.insertLayer(0, layer)

            # finally refresh canvas
            canvas.refresh()

    def create_db_views(self):
        SQLFile = os.path.join(
            os.sep,
            os.path.dirname(__file__),
            "..",
            "definitions",
            "add_spatial_views_for_gis2threejs.sql",
        )

        if self.dbconnection.dbtype == "spatialite":
            self.dbconnection.execute(
                r"""create view strat_obs_p_for_qgsi2threejs as select distinct "a"."rowid" as "rowid", "a"."obsid" as "obsid", "a"."geometry" as "geometry" from "obs_points" as "a" JOIN "stratigraphy" as "b" using ("obsid") where (typeof("a"."h_toc") in ('integer', 'real') or typeof("a"."h_gs") in ('integer', 'real'))"""
            )
            self.dbconnection.execute(
                r"""insert into views_geometry_columns (view_name, view_geometry, view_rowid, f_table_name, f_geometry_column, read_only) values ('strat_obs_p_for_qgsi2threejs', 'geometry', 'rowid', 'obs_points', 'geometry',1);"""
            )
        else:
            try:
                self.dbconnection.execute(
                    r"""CREATE VIEW strat_obs_p_for_qgsi2threejs AS 
                    SELECT ROW_NUMBER() OVER (ORDER BY obsid) rowid, obsid, "geometry"
                    FROM "obs_points"
                    WHERE EXISTS (SELECT s.obsid FROM stratigraphy s WHERE s.obsid = obs_points.obsid LIMIT 1)
                    AND COALESCE(h_toc, h_gs, 0) > 0;
                    """
                )
            except psycopg2.errors.DuplicateTable:
                common_utils.MessagebarAndLog.info(
                    log_msg=ru(
                        QCoreApplication.translate(
                            "PrepareForQgis2Threejs",
                            "Table strat_obs_p_for_qgsi2threejs already existed and is not recreated.",
                        )
                    )
                )

        for key in self.strat_layers_dict.keys():
            with open(SQLFile, "r") as f:
                for linecounter, line in enumerate(f):
                    if not linecounter:
                        # first line is encoding info....
                        continue
                    if not line.startswith(self.dbconnection.dbtype.upper()):
                        continue
                    line = common_utils.lstrip(self.dbconnection.dbtype.upper(), line)
                    if self.strat_layers_dict[key] is None:
                        params = tuple(
                            [
                                x
                                for k, v in self.strat_layers_dict.items()
                                for x in v
                                if k != key
                            ]
                        )
                        condition = "NOT IN"
                    else:
                        params = self.strat_layers_dict[key]
                        condition = "IN"

                    # TODO UNSAFE SQL WARNING. The params has to be added using
                    #  string concatenation for views.
                    sqliteline = line.replace("CHANGETOVIEWNAME", key).replace(
                        "CHANGETOPLOTTYPESDICTVALUE",
                        "{} ({})".format(
                            condition, common_utils.sql_unicode_list(params)
                        ),
                    )

                    try:
                        self.dbconnection.execute(sqliteline)
                    except psycopg2.errors.DuplicateTable:
                        common_utils.MessagebarAndLog.info(
                            log_msg=ru(
                                QCoreApplication.translate(
                                    "PrepareForQgis2Threejs",
                                    "Table %s already existed and is not recreated.",
                                )
                            )
                            % ru(key)
                        )

    def drop_db_views(self):
        self.dbconnection.drop_view("strat_obs_p_for_qgsi2threejs")
        for key in self.strat_layers_dict:
            self.dbconnection.drop_view(key)

    def remove_views(self):
        remove_group = self.root.findGroup("stratigraphy_layers_for_qgis2threejs")
        self.root.removeChildNode(remove_group)
