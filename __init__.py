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
# TODO: This should probably not be needed when the code is run from within QGIS
# ---------------------------------
import os
import sys

_qgis_extra_paths = []
_env_path = os.environ.get("QGIS_PYTHON_PATH")
if _env_path:
    _qgis_extra_paths.extend(_env_path.split(os.pathsep))
_qgis_extra_paths.extend(
    ["/usr/share/qgis/python", "/usr/lib/qgis/python", os.path.join(__file__, "..")]
)
# ---------------------------------

for _p in _qgis_extra_paths:
    if _p and os.path.isdir(_p) and _p not in sys.path:
        # Prepend so that the real QGIS modules win over any stubs.
        sys.path.insert(0, _p)


# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load Midvatten class from file midvatten_plugin.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    from .midvatten_plugin import Midvatten

    return Midvatten(iface)
