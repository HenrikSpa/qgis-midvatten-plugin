"""
/***************************************************************************
 Shared mixin for Qt dialogs that persist a subset of their widget values as
 "stored settings" -- a dict saved via common_utils.save_stored_settings() /
 loaded via common_utils.get_stored_settings() -- and let the user view and
 edit those settings as a Python-literal/JSON string.

 Extracted from tools/custom_drillreport.py and tools/wqualreport_compact.py,
 where this ~150-line block was duplicated verbatim. wqualreport_compact's
 version is the superset kept here: it also handles QRadioButton/QComboBox
 widgets, not just QPlainTextEdit/QCheckBox/QLineEdit.

 Extracting it also fixes a latent bug: both original copies emitted
 QCoreApplication.translate("DrillreportUi", ...) for their error messages,
 so wqualreport_compact's messages were filed under the drillreport
 translation context. The mixin uses its own neutral "StoredSettings"
 context instead.
                              -------------------
        begin                : 2026-08-03
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

import ast
import json

import qgis.PyQt
from qgis.PyQt.QtCore import QCoreApplication

from midvatten.tools.utils import (
    common_utils,
    exceptions,
    gui_utils,
    message_utils,
    string_utils,
)
from midvatten.tools.utils.string_utils import returnunicode as ru

_TRANSLATE_CONTEXT = "StoredSettings"


class StoredSettingsMixin:
    """Load/save/edit a widget-value "stored settings" dict for a Qt dialog.

    Host classes must have, before these methods are used:
        self.ms                  -- settings manager passed to
                                     common_utils.get/save_stored_settings
        self.stored_settings_key -- str key the dict is persisted under
        self.stored_settings     -- the current dict (replaced in place by
                                     save_stored_settings())

    save_stored_settings() and ask_and_update_stored_settings() also need
    self.save_attrnames: an explicit list of widget attribute names to
    persist, one attribute per line-edit/checkbox/etc. on the dialog.

    QCheckBox/QRadioButton restore is delegated to
    _apply_checkbox_or_radio_value(), an overridable hook: the two dialogs
    this mixin was extracted from need genuinely different behavior here
    (not just different widget types), so it is not folded into the
    shared dispatch loop below. See that method's docstring.
    """

    def update_from_stored_settings(self, stored_settings):
        if isinstance(stored_settings, dict) and stored_settings:
            for attr, val in stored_settings.items():
                try:
                    selfattr = getattr(self, attr)
                except AttributeError:
                    pass
                else:
                    if isinstance(selfattr, qgis.PyQt.QtWidgets.QPlainTextEdit):
                        if isinstance(val, (list, tuple)):
                            val = "\n".join(val)
                        selfattr.setPlainText(val)
                    elif isinstance(
                        selfattr,
                        (
                            qgis.PyQt.QtWidgets.QCheckBox,
                            qgis.PyQt.QtWidgets.QRadioButton,
                        ),
                    ):
                        self._apply_checkbox_or_radio_value(selfattr, val)
                    elif isinstance(selfattr, qgis.PyQt.QtWidgets.QLineEdit):
                        selfattr.setText(val)
                    elif isinstance(selfattr, qgis.PyQt.QtWidgets.QComboBox):
                        gui_utils.set_combobox(selfattr, val, add_if_not_exists=False)

    def _apply_checkbox_or_radio_value(self, widget, val):
        """Default (wqualreport_compact) semantics: only act when val is
        truthy, and use click() rather than setChecked() so any slots
        connected to the widget's own `clicked` signal still fire (e.g.
        compact's mutually-exclusive radio buttons, which flip a sibling
        widget off in a connected lambda).

        Hosts whose checkboxes have no such side effects, and that need to
        be able to restore an explicit False too, should override this
        (see custom_drillreport.DrillreportUi)."""
        if bool(val):
            widget.click()

    @common_utils.general_exception_handler
    def ask_and_update_stored_settings(self):
        self.stored_settings = self.ask_for_stored_settings(self.stored_settings)
        self.update_from_stored_settings(self.stored_settings)
        self.save_stored_settings(self.save_attrnames)

    def save_stored_settings(self, save_attrnames):
        stored_settings = {}
        for attrname in save_attrnames:
            try:
                attr = getattr(self, attrname)
            except Exception:
                message_utils.MessagebarAndLog.info(
                    log_msg=QCoreApplication.translate(
                        _TRANSLATE_CONTEXT,
                        "Programming error. Attribute name %s didn't exist in self.",
                    )
                    % attrname
                )
            else:
                if isinstance(attr, qgis.PyQt.QtWidgets.QPlainTextEdit):
                    val = [x for x in attr.toPlainText().split("\n") if x]
                elif isinstance(
                    attr,
                    (qgis.PyQt.QtWidgets.QCheckBox, qgis.PyQt.QtWidgets.QRadioButton),
                ):
                    val = attr.isChecked()
                elif isinstance(attr, qgis.PyQt.QtWidgets.QLineEdit):
                    val = attr.text()
                elif isinstance(attr, qgis.PyQt.QtWidgets.QComboBox):
                    val = attr.currentText()
                else:
                    message_utils.MessagebarAndLog.info(
                        log_msg=QCoreApplication.translate(
                            _TRANSLATE_CONTEXT,
                            "Programming error. The Qt-type %s is unhandled.",
                        )
                        % str(type(attr))
                    )
                    continue
                stored_settings[attrname] = val

        self.stored_settings = stored_settings

        common_utils.save_stored_settings(
            self.ms, self.stored_settings, self.stored_settings_key
        )

    def ask_for_stored_settings(self, stored_settings):
        old_string = string_utils.anything_to_string_representation(
            stored_settings,
            itemjoiner=",\n",
            pad="    ",
            dictformatter="{\n%s}",
            listformatter="[\n%s]",
            tupleformatter="(\n%s, )",
        )

        msg = QCoreApplication.translate(
            _TRANSLATE_CONTEXT,
            "Replace the settings string with a new settings string.",
        )

        new_string = qgis.PyQt.QtWidgets.QInputDialog.getText(
            None,
            QCoreApplication.translate(_TRANSLATE_CONTEXT, "Edit settings string"),
            msg,
            qgis.PyQt.QtWidgets.QLineEdit.Normal,
            old_string,
        )
        if not new_string[1]:
            raise exceptions.UserInterruptError()

        new_string_text = ru(new_string[0])
        if not new_string_text:
            return {}

        try:
            try:
                as_dict = json.loads(new_string_text)
            except (json.JSONDecodeError, ValueError):
                as_dict = ast.literal_eval(new_string_text)
        except Exception as e:
            message_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    _TRANSLATE_CONTEXT,
                    "Translating string to dict failed, see log message panel",
                ),
                log_msg=str(e),
            )
            raise exceptions.UsageError()
        else:
            return as_dict
