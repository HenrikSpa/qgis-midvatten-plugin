"""
/***************************************************************************
 Base class for all Midvatten data importer dialogs.
                             -------------------
        begin                : 2016-11-27
        copyright            : (C) 2016 by HenrikSpa (and joskal)
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

import qgis.PyQt
from qgis.PyQt import QtWidgets

from midvatten.tools.utils.gui_utils import WA_DeleteOnClose


class BaseImporter(QtWidgets.QMainWindow):
    """Shared scaffolding for all importer dialogs.

    Subclasses use multiple inheritance together with a UI mixin loaded via
    ``uic.loadUiType``, e.g.::

        class FieldloggerImport(BaseImporter, import_fieldlogger_ui_dialog):
            ...

    Python MRO ensures ``super().__init__(parent)`` calls
    ``QMainWindow.__init__`` via the mixin chain.

    Each subclass is responsible for:
    - Setting any importer-specific attributes before calling
      ``super().__init__(parent, msettings)``
    - Building its own widgets after ``__init__`` completes
    - Managing waiting-cursor and ``close_after_import`` in its own
      ``start_import()`` method (cursor management differs per importer)
    """

    def __init__(self, parent, msettings=None):
        self.status = False
        self.iface = parent
        self.ms = msettings
        self.ms.load_settings()
        qgis.PyQt.QtWidgets.QMainWindow.__init__(self, parent)
        self.setAttribute(WA_DeleteOnClose)
        self.setupUi(self)  # Required by Qt
        self.status = True

    def add_row(self, a_widget: QtWidgets.QWidget) -> None:
        """Append *a_widget* to the bottom of the main vertical layout."""
        self.main_vertical_layout.addWidget(a_widget)
