# -*- coding: utf-8 -*-
"""
/***************************************************************************
 Midvatten
                                 A QGIS plugin
A toolset that makes QGIS an interface for editing/viewing hydrogeological
observational data (drillings, water levels, seismic data etc) stored in a
SQLite or PostgreSQL database.
                             -------------------
        begin                : 2012-03-05
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
 This script initializes the plugin, making it known to QGIS.
"""
import monkeytype


# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load Midvatten class from file midvatten_plugin.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    with monkeytype.trace():
        from .midvatten_plugin import Midvatten

        return Midvatten(iface)
