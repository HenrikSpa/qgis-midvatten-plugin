"""
/***************************************************************************
 This is the place to store some global (for the Midvatten plugin) utility functions.
 NOTE - if using this file, it has to be imported by midvatten_plugin.py
                             -------------------
        begin                : 2011-10-18
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

import ast
import copy
import json
import locale
import logging
import os
import re
from typing import List, Optional, Tuple, TYPE_CHECKING

import matplotlib as mpl
from packaging.version import Version, InvalidVersion
import qgis.PyQt
from matplotlib import pyplot as plt
from qgis.PyQt import QtWidgets, QtCore
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QDesktopServices
from qgis.core import QgsProject
from qgis.core import QgsVectorLayer

from midvatten.tools.utils.db_utils import DbConnectionManager

if TYPE_CHECKING:
    from midvatten.tools.midvsettings import MidvSettings

try:
    pass
except Exception:
    pandas_on = False
else:
    pandas_on = True


from midvatten.tools.utils.message_utils import MessagebarAndLog
from midvatten.tools.utils.layer_utils import find_layer
from midvatten.tools.utils.string_utils import (
    returnunicode as ru,
    returnunicode,
    anything_to_string_representation,
)
from midvatten.tools.utils.exceptions import UsageError, UserInterruptError
from midvatten.tools.utils.file_utils import definitions_path
from midvatten.tools.utils.dialog_utils import Askuser
from midvatten.tools.utils.common_utils import (
    transpose_lists_of_lists,
    general_exception_handler,
    get_save_file_name_no_extension,
)

from midvatten.definitions.db_defs import latest_database_version

from midvatten.tools.utils import db_utils

log = logging.getLogger(__name__)


def verify_msettings_loaded_and_layer_edit_mode(
    iface: qgis.gui.QgisInterface,
    mset: "MidvSettings",
    allcritical_layers: Tuple[str] = ("",),
    only_error_if_editing_enabled: bool = True,
) -> int:
    if isinstance(allcritical_layers, str):
        allcritical_layers = (allcritical_layers,)

    errorsignal = 0
    if not mset.settingsareloaded:
        mset.load_settings()
    for layername in allcritical_layers:
        if not layername:
            continue
        try:
            layerexists = find_layer(str(layername))
        except UsageError:
            if not only_error_if_editing_enabled:
                errorsignal += 1
                MessagebarAndLog.warning(
                    bar_msg=QCoreApplication.translate(
                        "verify_msettings_loaded_and_layer_edit_mode",
                        "Error layer %s is required but missing!",
                    )
                    % str(layername)
                )
                errorsignal += 1
        else:
            if layerexists:
                if layerexists.isEditable():
                    MessagebarAndLog.warning(
                        bar_msg=QCoreApplication.translate(
                            "verify_msettings_loaded_and_layer_edit_mode",
                            "Error %s is currently in editing mode.\nPlease exit this mode before proceeding with this operation.",
                        )
                        % str(layerexists.name())
                    )
                    # pop_up_info("Layer " + str(layerexists.name()) + " is currently in editing mode.\nPlease exit this mode before proceeding with this operation.", "Warning")
                    errorsignal += 1

    if not mset.settingsdict["database"]:
        MessagebarAndLog.warning(
            bar_msg=QCoreApplication.translate(
                "verify_msettings_loaded_and_layer_edit_mode",
                "Error, No database found. Please check your Midvatten Settings. Reset if needed.",
            )
        )
        errorsignal += 1
    else:
        try:
            connection_ok = db_utils.check_connection_ok()
        except db_utils.DatabaseLockedError:
            MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "verify_msettings_loaded_and_layer_edit_mode",
                    "Databas is already in use",
                )
            )
            errorsignal += 1
        else:
            if not connection_ok:
                MessagebarAndLog.warning(
                    bar_msg=QCoreApplication.translate(
                        "verify_msettings_loaded_and_layer_edit_mode",
                        "Error, The selected database doesn't exist. Please check your Midvatten Settings and database location. Reset if needed.",
                    )
                )
                errorsignal += 1

    return errorsignal


# These DB query helpers now live in db_utils; re-exported here for backward compatibility.


def ask_for_charset(default_charset=None, msg=None):
    try:  # MacOSX fix2
        localencoding = getcurrentlocale()[1]
        if default_charset is None:
            if msg is None:
                msg = (
                    QCoreApplication.translate(
                        "ask_for_charset",
                        "Give charset used in the file, normally\niso-8859-1, utf-8, cp1250 or cp1252.\n\nOn your computer %s is default.",
                    )
                    % localencoding
                )
            charsetchoosen = QtWidgets.QInputDialog.getText(
                None,
                QCoreApplication.translate("ask_for_charset", "Set charset encoding"),
                msg,
                QtWidgets.QLineEdit.Normal,
                getcurrentlocale()[1],
            )[0]
        else:
            if msg is None:
                msg = QCoreApplication.translate(
                    "ask_for_charset",
                    "Give charset used in the file, default charset on normally\nutf-8, iso-8859-1, cp1250 or cp1252.",
                )
            charsetchoosen = QtWidgets.QInputDialog.getText(
                None,
                QCoreApplication.translate("ask_for_charset", "Set charset encoding"),
                msg,
                QtWidgets.QLineEdit.Normal,
                default_charset,
            )[0]
    except Exception as e:
        if default_charset is None:
            default_charset = "utf-8"
        if msg is None:
            msg = QCoreApplication.translate(
                "ask_for_charset",
                "Give charset used in the file, default charset on normally\nutf-8, iso-8859-1, cp1250 or cp1252.",
            )
        charsetchoosen = QtWidgets.QInputDialog.getText(
            None,
            QCoreApplication.translate("ask_for_charset", "Set charset encoding"),
            msg,
            QtWidgets.QLineEdit.Normal,
            default_charset,
        )[0]

    return str(charsetchoosen)


def add_triggers_to_obs_points(filename: str):
    """
    /*
    * These are quick-fixes for updating coords from geometry and the other way around
    * Please notice that these are AFTER insert/update although BEFORE should be preferrable?
    * Also, srid is not yet read from the
    */

    -- geometry updated after coordinates are inserted
    CREATE TRIGGER "after_insert_obs_points_geom_fr_coords" AFTER INSERT ON "obs_points"
    WHEN (0 < (select count() from obs_points where ((NEW.east is not null) AND (NEW.north is not null) AND (NEW.geometry IS NULL))))
    BEGIN
        UPDATE obs_points
        SET  geometry = MakePoint(east, north, (select srid from geometry_columns where f_table_name = 'obs_points'))
        WHERE (NEW.east is not null) AND (NEW.north is not null) AND (NEW.geometry IS NULL);
    END;

    -- coordinates updated after geometries are inserted
    CREATE TRIGGER "after_insert_obs_points_coords_fr_geom" AFTER INSERT ON "obs_points"
    WHEN (0 < (select count() from obs_points where ((NEW.east is null) AND (NEW.north is null) AND (NEW.geometry is not NULL))))
    BEGIN
        UPDATE obs_points
        SET  east = X(geometry), north = Y(geometry)
        WHERE (NEW.east is null) AND (NEW.north is null) AND (NEW.geometry is not NULL);
    END;

    -- coordinates updated after geometries are updated
    CREATE TRIGGER "after_update_obs_points_coords_fr_geom" AFTER UPDATE ON "obs_points"
    WHEN (0 < (select count() from obs_points where NEW.geometry != OLD.geometry) )
    BEGIN
        UPDATE obs_points
        SET  east = X(geometry), north = Y(geometry)
        WHERE (NEW.geometry != OLD.geometry);
    END;

    -- geometry updated after coordinates are updated
    CREATE TRIGGER "after_update_obs_points_geom_fr_coords" AFTER UPDATE ON "obs_points"
    WHEN (0 < (select count() from obs_points where ((NEW.east != OLD.east) OR (NEW.north != OLD.north))) )
    BEGIN
        UPDATE obs_points
        SET  geometry = MakePoint(east, north, (select srid from geometry_columns where f_table_name = 'obs_points'))
        WHERE ((NEW.east != OLD.east) OR (NEW.north != OLD.north));
    END;
    :return:
    """
    db_utils.execute_sqlfile_using_func(
        definitions_path(filename),
        db_utils.sql_alter_db,
    )


def getcurrentlocale(
    print_error_message_in_bar: bool = True, dbconnection=None
) -> List[str]:
    if not isinstance(dbconnection, db_utils.DbConnectionManager):
        try:
            dbconnection = db_utils.DbConnectionManager()
        except UsageError:
            # The user has not selected a database.
            dbconnection_created = False
            dbconnection = None
        else:
            dbconnection_created = True
    else:
        dbconnection_created = False

    if dbconnection is not None:
        db_locale = get_locale_from_db(
            print_error_message_in_bar=print_error_message_in_bar,
            dbconnection=dbconnection,
        )
    else:
        db_locale = None

    if dbconnection_created:
        dbconnection.closedb()

    if db_locale is not None and db_locale:
        return [db_locale, locale.getencoding()]
    else:
        return locale.getlocale()


def is_locale_swedish(dbconnection=None) -> bool:
    """True when the resolved locale (DB override + system fallback) is
    Swedish. Use for branches that can't go through
    QCoreApplication.translate — image-file picking, `_sv.qml` fallbacks,
    and hardcoded strings in reports that pre-date i18n.
    """
    return getcurrentlocale(dbconnection=dbconnection)[0] == "sv_SE"


def get_locale_from_db(
    print_error_message_in_bar: bool = True,
    dbconnection: Optional[DbConnectionManager] = None,
) -> str:
    if not isinstance(dbconnection, db_utils.DbConnectionManager):
        dbconnection = db_utils.DbConnectionManager()
        dbconnection_created = True
    else:
        dbconnection_created = False

    connection_ok, locale_row = db_utils.sql_load_fr_db(
        "SELECT description FROM about_db WHERE description LIKE 'locale:%'",
        print_error_message_in_bar=print_error_message_in_bar,
        dbconnection=dbconnection,
    )

    if dbconnection_created:
        dbconnection.closedb()

    if connection_ok:
        try:
            locale_setting = ru(locale_row, keep_containers=True)[0][0].split(":")
        except IndexError:
            return None

        try:
            locale_setting = locale_setting[1]
        except IndexError:
            return None
        else:
            return locale_setting
    else:
        MessagebarAndLog.info(
            log_msg=QCoreApplication.translate(
                "get_locale_from_db",
                "Connection to db failed when getting locale from db.",
            )
        )
        return None


from midvatten.tools.utils.db_utils.helpers import (  # noqa: E402
    list_of_lists_from_table,
)


def create_layer(
    tablename,
    geometrycolumn=None,
    sql=None,
    keycolumn=None,
    dbconnection=None,
    layername=None,
):
    if not isinstance(dbconnection, db_utils.DbConnectionManager):
        dbconnection = db_utils.DbConnectionManager()
        dbconnection_created = True
    else:
        dbconnection_created = False

    uri = dbconnection.uri
    dbtype = dbconnection.dbtype
    schema = dbconnection.schemas()
    # For QgsVectorLayer, dbtype has to be postgres instead of postgis
    dbtype = db_utils.get_dbtype(dbtype)

    uri.setDataSource(schema, tablename, geometrycolumn, sql, keycolumn)
    _name = tablename if layername is None else layername
    layer = QgsVectorLayer(uri.uri(), _name, dbtype)

    if dbconnection_created:
        dbconnection.closedb()
    return layer

    if dbconnection_created:
        dbconnection.closedb()


def warn_about_old_database():
    try:
        dbconnection = db_utils.DbConnectionManager()
    except UsageError:
        # Probably empty project
        return

    try:
        try:
            dbconnection.cursor.execute("""SELECT description FROM about_db LIMIT 1""")
            rows = dbconnection.cursor.fetchall()
        except Exception as e:
            MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "warn_about_old_database",
                    "Database might not be a valid Midvatten database!",
                ),
                log_msg=QCoreApplication.translate("warn_about_old_database", "msg: %s")
                % str(e),
            )
            return

        try:
            row = rows[0][0]
        except Exception:
            MessagebarAndLog.info(
                log_msg=QCoreApplication.translate(
                    "warn_about_old_database",
                    "No row returned from about_db when searching for version.",
                )
            )
            return
        if row:
            patterns = [
                r"""Midvatten plugin Version ([0-9\.a-b]+)""",
                r"""Midvatten plugin ([0-9\.a-b]+)""",
            ]
            version = None
            for pattern in patterns:
                m = re.search(pattern, row)
                if m:
                    version = m.groups()[0]
                    break

            if version:
                wikipage = "https://github.com/jkall/qgis-midvatten-plugin/wiki/6.-Database-management#upgrade-database"

                is_old = compare_verson_lists(
                    version_comparison_list(version),
                    version_comparison_list(latest_database_version()),
                )

                if is_old:
                    MessagebarAndLog.info(
                        bar_msg=QCoreApplication.translate(
                            "warn_about_old_database",
                            """The database version appears to be older than %s. An upgrade is suggested! See %s""",
                        )
                        % (latest_database_version(), wikipage),
                        duration=4,
                    )
    finally:
        dbconnection.closedb()


def version_comparison_list(version_string: str) -> Optional[Version]:
    """Return a Version object for comparison, or None if unparseable."""
    try:
        return Version(version_string)
    except InvalidVersion:
        return None


def compare_verson_lists(
    testlist: Optional[Version], reflist: Optional[Version]
) -> bool:
    """Return True if testlist version is older than reflist version.

    Returns False if either version could not be parsed.
    """
    if testlist is None or reflist is None:
        return False
    return testlist < reflist


def add_view_obs_points_obs_lines():
    dbconnection = db_utils.DbConnectionManager()
    if not dbconnection.is_sqlite():
        MessagebarAndLog.info(
            bar_msg=QCoreApplication.translate(
                "Midvatten", "Views not added for PostGIS databases (not needed)!"
            )
        )
        dbconnection.closedb()
        return

    connection_ok = dbconnection.connect2db()
    if connection_ok:
        dbconnection.execute("""DROP VIEW IF EXISTS view_obs_points;""")
        dbconnection.execute("""DROP VIEW IF EXISTS view_obs_lines;""")
        dbconnection.execute(
            """DELETE FROM views_geometry_columns WHERE view_name IN ('view_obs_points', 'view_obs_lines');"""
        )
        db_utils.execute_sqlfile(definitions_path("qgis3_obsp_fix.sql"), dbconnection)
        dbconnection.commit_and_closedb()
        MessagebarAndLog.info(
            bar_msg=QCoreApplication.translate(
                "Midvatten",
                'Views added. Please reload layers (Midvatten>Load default db-layers to qgis or "F7").',
            )
        )


def add_non_essential_tables(dbconnection=None):
    connection_created = False
    if dbconnection is None:
        connection_created = True
        dbconnection = db_utils.DbConnectionManager()

    connection_ok = dbconnection.connect2db()
    if connection_ok:
        with dbconnection.transaction():
            db_utils.execute_sqlfile(
                definitions_path("create_db_extra_data_tables.sql"),
                dbconnection,
                merge_newlines=True,
            )
        MessagebarAndLog.info(
            bar_msg=QCoreApplication.translate(
                "Midvatten",
                "Tables added. Load tables using Midvatten>Utilities>Load data tables to qgis.",
            )
        )
    if connection_created:
        dbconnection.closedb()


def select_files(
    only_one_file: bool = True, extension: str = "csv (*.csv)"
) -> List[str]:
    """Asks users to select file(s)"""
    try:
        dir = os.path.dirname(
            db_utils.get_spatialite_db_path_from_dbsettings_string(
                QgsProject.instance().readEntry("Midvatten", "database")[0]
            )
        )
    except Exception as e:
        MessagebarAndLog.info(
            log_msg=returnunicode(
                QCoreApplication.translate(
                    "select_files",
                    "Getting directory for select_files failed with msg %s",
                )
            )
            % str(e)
        )
        dir = ""

    if only_one_file:
        csvpath = [
            QtWidgets.QFileDialog.getOpenFileName(
                parent=None,
                caption=QCoreApplication.translate("select_files", "Select file"),
                directory=dir,
                filter=extension,
            )[0]
        ]
    else:
        csvpath = QtWidgets.QFileDialog.getOpenFileNames(
            parent=None,
            caption=QCoreApplication.translate("select_files", "Select files"),
            directory=dir,
            filter=extension,
        )[0]
    csvpath = [returnunicode(p) for p in csvpath if p]
    if not csvpath:
        MessagebarAndLog.info(
            log_msg=returnunicode(
                QCoreApplication.translate("select_files", "No file selected!")
            )
        )
        raise UserInterruptError()
    return csvpath


def create_markdown_table_from_table(
    tablename, transposed=False, only_description=False
):
    """Used externally to generate markdown tables for the GitHub wiki."""
    table = list_of_lists_from_table(tablename)
    if only_description:
        descr_idx = table[0].index("description")
        tablename_idx = table[0].index("tablename")
        columnname_idx = table[0].index("columnname")

        table = [
            [row[tablename_idx], row[columnname_idx], row[descr_idx]] for row in table
        ]

    if transposed:
        table = transpose_lists_of_lists(table)
        for row in table:
            row[0] = f"**{row[0]}**"

    column_names = table[0]
    table_contents = table[1:]

    printlist = ["|{}|".format(" | ".join(column_names))]
    printlist.append(
        "|{}|".format(" | ".join([":---" for idx, x in enumerate(column_names)]))
    )
    printlist.extend(
        [
            "|{}|".format(
                " | ".join([item if item is not None else "" for item in row])
            )
            for row in table_contents
        ]
    )
    return "\n".join(printlist)


class PlotTemplates:
    def __init__(
        self,
        plot_object,
        template_list,
        edit_button,
        load_button,
        save_as_button,
        import_button,
        remove_button,
        template_folder,
        templates_settingskey,
        loaded_template_settingskey,
        fallback_template,
        msettings=None,
    ):

        # Gui objects
        self.template_list = template_list
        self.edit_button = edit_button
        self.load_button = load_button
        self.save_as_button = save_as_button
        self.import_button = import_button
        self.remove_button = remove_button

        self.ms = msettings
        self.templates = {}
        self.loaded_template = {}

        self.template_folder = template_folder
        self.fallback_template = fallback_template
        self.templates_settingskey = templates_settingskey
        self.loaded_template_settingskey = loaded_template_settingskey

        self.templates = {}

        self.import_saved_templates()
        self.import_from_template_folder()

        try:
            self.loaded_template = self.string_to_dict(
                self.ms.settingsdict[self.loaded_template_settingskey]
            )
        except Exception:
            MessagebarAndLog.warning(
                bar_msg=returnunicode(
                    QCoreApplication.translate(
                        "PlotTemplates",
                        "Failed to load saved template, loading default template instead.",
                    )
                )
            )
        if self.loaded_template:
            MessagebarAndLog.info(
                log_msg=returnunicode(
                    QCoreApplication.translate(
                        "PlotTemplates", "Loaded template from midvatten settings %s."
                    )
                )
                % self.loaded_template_settingskey
            )

        default_filename = os.path.join(self.template_folder, "default.txt")

        if not self.loaded_template:
            if not os.path.isfile(default_filename):
                MessagebarAndLog.warning(
                    bar_msg=returnunicode(
                        QCoreApplication.translate(
                            "PlotTemplates",
                            "Default template not found, loading hard coded default template.",
                        )
                    )
                )
            else:
                try:
                    self.load(self.templates[default_filename]["template"])
                except Exception as e:
                    MessagebarAndLog.warning(
                        bar_msg=returnunicode(
                            QCoreApplication.translate(
                                "PlotTemplates",
                                "Failed to load default template, loading hard coded default template.",
                            )
                        ),
                        log_msg=returnunicode(
                            QCoreApplication.translate("PlotTemplates", "Error msg %s")
                        )
                        % str(e),
                    )
            if self.loaded_template:
                MessagebarAndLog.info(
                    log_msg=returnunicode(
                        QCoreApplication.translate(
                            "PlotTemplates",
                            "Loaded template from default template file.",
                        )
                    )
                )

        if not self.loaded_template:
            self.loaded_template = self.fallback_template
            if self.loaded_template:
                MessagebarAndLog.info(
                    log_msg=returnunicode(
                        QCoreApplication.translate(
                            "PlotTemplates",
                            "Loaded template from default hard coded template.",
                        )
                    )
                )

        self.edit_button.clicked.connect(lambda x: self.edit())
        self.load_button.clicked.connect(lambda x: self.load())
        self.save_as_button.clicked.connect(lambda x: self.save_as())
        self.import_button.clicked.connect(lambda x: self.import_templates())
        self.remove_button.clicked.connect(lambda x: self.remove())

    @general_exception_handler
    def edit(self):
        old_string = self.readable_output(self.loaded_template)

        msg = returnunicode(
            QCoreApplication.translate(
                "StoredSettings",
                "Replace the settings string with a new settings string.",
            )
        )
        new_string = qgis.PyQt.QtWidgets.QInputDialog.getText(
            None,
            returnunicode(
                QCoreApplication.translate("StoredSettings", "Edit settings")
            ),
            msg,
            qgis.PyQt.QtWidgets.QLineEdit.Normal,
            old_string,
        )
        if not new_string[1]:
            raise UserInterruptError()

        as_dict = self.string_to_dict(returnunicode(new_string[0]))

        self.loaded_template = as_dict

    @general_exception_handler
    def load(self, template=None):
        if isinstance(template, dict):
            self.loaded_template = template
        else:
            selected = self.template_list.selectedItems()
            if selected:
                filename = selected[0].filename
                template = self.parse_template(filename)
                if template:
                    self.templates[filename] = template
                self.loaded_template = self.templates[filename]["template"]

    @general_exception_handler
    def save_as(self):
        filename = get_save_file_name_no_extension(
            parent=None,
            caption=returnunicode(
                QCoreApplication.translate("PlotTemplates", "Choose a file name")
            ),
            directory="",
            filter="txt (*.txt)",
        )
        as_str = self.readable_output(self.loaded_template)
        with open(filename, "w", encoding="utf8") as of:
            of.write(as_str)

        name = os.path.splitext(os.path.basename(filename))[0]
        template = copy.deepcopy(self.loaded_template)
        self.templates[filename] = {
            "filename": filename,
            "template": template,
            "name": name,
        }

        self.update_settingsdict()
        self.update_template_list()

    @general_exception_handler
    def import_templates(self, filenames=None):
        if filenames is None:
            filenames = select_files(only_one_file=False, extension="")
        templates = {}
        if filenames:
            for filename in filenames:
                if not filename:
                    continue

                processed_before = filename in list(self.templates.keys())
                processed_now = filename in list(templates.keys())

                if not processed_before and not processed_now:
                    template = self.parse_template(filename)
                    if template:
                        templates[filename] = template

        self.templates.update(templates)
        self.update_settingsdict()
        self.update_template_list()

    @general_exception_handler
    def remove(self):
        selected = self.template_list.selectedItems()
        if selected:
            filename = selected[0].filename
            del self.templates[filename]
            self.update_settingsdict()
            self.update_template_list()

    @general_exception_handler
    def import_from_template_folder(self):
        for root, dirs, files in os.walk(self.template_folder):
            if files:
                filenames = [os.path.join(root, filename) for filename in files]
                self.import_templates(filenames)

    @general_exception_handler
    def import_saved_templates(self):
        filenames = [
            x for x in self.ms.settingsdict[self.templates_settingskey].split(";") if x
        ]
        if filenames:
            MessagebarAndLog.info(
                log_msg=returnunicode(
                    QCoreApplication.translate("", "Loading saved templates %s")
                )
                % "\n".join(filenames)
            )
            self.import_templates(filenames)

    def parse_template(self, filename):
        name = os.path.splitext(os.path.basename(filename))[0]
        if not os.path.isfile(filename):
            raise UsageError(
                returnunicode(
                    QCoreApplication.translate("PlotTemplates", '"%s" was not a file.')
                )
                % filename
            )
        try:
            with open(filename, encoding="utf-8") as f:
                lines = "".join([line for line in f if line])
        except Exception as e:
            MessagebarAndLog.critical(
                bar_msg=returnunicode(
                    QCoreApplication.translate(
                        "PlotTemplates",
                        "Loading template %s failed, see log message panel",
                    )
                )
                % filename,
                log_msg=returnunicode(
                    QCoreApplication.translate(
                        "PlotTemplates", "Reading file failed, msg:\n%s"
                    )
                )
                % returnunicode(str(e)),
            )
            raise

        if lines:
            try:
                template = self.string_to_dict("".join(lines))
            except Exception as e:
                MessagebarAndLog.critical(
                    bar_msg=returnunicode(
                        QCoreApplication.translate(
                            "PlotTemplates",
                            "Loading template %s failed, see log message panel",
                        )
                    )
                    % filename,
                    log_msg=returnunicode(
                        QCoreApplication.translate(
                            "PlotTemplates", "Parsing file rows failed, msg:\n%s"
                        )
                    )
                    % returnunicode(str(e)),
                )
                raise
            else:
                return {"filename": filename, "template": template, "name": name}
        else:
            return {}

    def update_settingsdict(self):
        self.ms.settingsdict[self.templates_settingskey] = ";".join(
            list(self.templates.keys())
        )
        self.ms.save_settings(self.templates_settingskey)

    def update_template_list(self):
        self.template_list.clear()
        for filename, template in sorted(
            iter(self.templates.items()), key=lambda x: os.path.basename(x[0])
        ):
            qlistwidgetitem = qgis.PyQt.QtWidgets.QListWidgetItem()
            qlistwidgetitem.setText(template["name"])
            qlistwidgetitem.filename = template["filename"]
            self.template_list.addItem(qlistwidgetitem)

    def readable_output(self, a_dict=None):
        if a_dict is None:
            a_dict = self.loaded_template
        return anything_to_string_representation(
            a_dict,
            itemjoiner=",\n",
            pad="    ",
            dictformatter="{\n%s}",
            listformatter="[\n%s]",
            tupleformatter="(\n%s, )",
        )

    def string_to_dict(self, the_string):
        the_string = returnunicode(the_string)
        if not the_string:
            return ""
        try:
            try:
                as_dict = json.loads(the_string)
            except (json.JSONDecodeError, ValueError):
                as_dict = ast.literal_eval(the_string)
        except Exception as e:
            MessagebarAndLog.warning(
                bar_msg=returnunicode(
                    QCoreApplication.translate(
                        "StoredSettings",
                        "Translating string to dict failed, see log message panel",
                    )
                ),
                log_msg=returnunicode(
                    QCoreApplication.translate(
                        "StoredSettings", "Error %s\nfor string\n%s"
                    )
                )
                % (str(e), the_string),
            )
        else:
            return as_dict


def _sanitize_mplstyle_content(content: str) -> tuple[str, list[str]]:
    """Return (cleaned_content, skipped_keys) after dropping keys unknown to this matplotlib."""
    lines = []
    skipped: list[str] = []
    for line in content.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            lines.append(line)
            continue
        if ":" not in stripped:
            lines.append(line)
            continue
        key, _, _ = stripped.partition(":")
        key = key.strip()
        if key in mpl.rcParams:
            lines.append(line)
        else:
            skipped.append(key)
    return "".join(lines), skipped


class _FixStylesDialog(QtWidgets.QDialog):
    """Dialog that lets the user inspect and fix .mplstyle files in the stylelib."""

    def __init__(self, style_folder: str, style_extension: str, parent=None):
        super().__init__(parent)
        self.style_folder = style_folder
        self.style_extension = style_extension
        self.fixed_any = False
        self._setup_ui()
        self._scan()

    def _setup_ui(self):
        self.setWindowTitle(
            QCoreApplication.translate("_FixStylesDialog", "Fix style files")
        )
        layout = QtWidgets.QVBoxLayout(self)

        layout.addWidget(
            QtWidgets.QLabel(
                QCoreApplication.translate(
                    "_FixStylesDialog",
                    "Select style files to fix (unknown rcParams keys will be removed):",
                )
            )
        )

        self._list = QtWidgets.QListWidget()
        self._list.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._list)

        sel_row = QtWidgets.QHBoxLayout()
        btn_all = QtWidgets.QPushButton(
            QCoreApplication.translate("_FixStylesDialog", "Select all")
        )
        btn_none = QtWidgets.QPushButton(
            QCoreApplication.translate("_FixStylesDialog", "Deselect all")
        )
        btn_all.clicked.connect(lambda: self._set_all(True))
        btn_none.clicked.connect(lambda: self._set_all(False))
        sel_row.addWidget(btn_all)
        sel_row.addWidget(btn_none)
        sel_row.addStretch()
        layout.addLayout(sel_row)

        btn_row = QtWidgets.QHBoxLayout()
        self._fix_btn = QtWidgets.QPushButton(
            QCoreApplication.translate("_FixStylesDialog", "Fix selected")
        )
        close_btn = QtWidgets.QPushButton(
            QCoreApplication.translate("_FixStylesDialog", "Close")
        )
        self._fix_btn.clicked.connect(self._fix_selected)
        close_btn.clicked.connect(self.accept)
        btn_row.addStretch()
        btn_row.addWidget(self._fix_btn)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self.resize(520, 320)

    def _scan(self):
        self._list.blockSignals(True)
        self._list.clear()
        self._info: dict = {}

        if os.path.isdir(self.style_folder):
            for fname in sorted(os.listdir(self.style_folder)):
                if not fname.endswith(self.style_extension):
                    continue
                fpath = os.path.join(self.style_folder, fname)
                try:
                    with open(fpath, encoding="utf-8") as f:
                        raw = f.read()
                    content, skipped = _sanitize_mplstyle_content(raw)
                except Exception:
                    content, skipped = "", []

                style_name = os.path.splitext(fname)[0]
                self._info[fname] = (fpath, content, skipped)

                item = QtWidgets.QListWidgetItem()
                if skipped:
                    label = QCoreApplication.translate(
                        "_FixStylesDialog", "%s  —  %d unknown key(s): %s"
                    ) % (style_name, len(skipped), ", ".join(skipped))
                    item.setCheckState(QtCore.Qt.Checked)
                else:
                    label = (
                        QCoreApplication.translate("_FixStylesDialog", "%s  —  OK")
                        % style_name
                    )
                    item.setCheckState(QtCore.Qt.Unchecked)
                item.setText(label)
                item.setData(QtCore.Qt.UserRole, fname)
                self._list.addItem(item)

        self._list.blockSignals(False)
        self._update_fix_btn()

    def _set_all(self, checked: bool):
        state = QtCore.Qt.Checked if checked else QtCore.Qt.Unchecked
        self._list.blockSignals(True)
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(state)
        self._list.blockSignals(False)
        self._update_fix_btn()

    def _on_item_changed(self, _item):
        self._update_fix_btn()

    def _update_fix_btn(self):
        any_checked = any(
            self._list.item(i).checkState() == QtCore.Qt.Checked
            for i in range(self._list.count())
        )
        self._fix_btn.setEnabled(any_checked)

    def _fix_selected(self):
        fixed: list[str] = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.checkState() != QtCore.Qt.Checked:
                continue
            fname = item.data(QtCore.Qt.UserRole)
            fpath, content, skipped = self._info.get(fname, (None, "", []))
            if not fpath or not skipped:
                continue
            try:
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(content)
                fixed.append(os.path.splitext(fname)[0])
                self.fixed_any = True
            except Exception as e:
                MessagebarAndLog.warning(
                    bar_msg=QCoreApplication.translate(
                        "_FixStylesDialog", "Failed to fix style file '%s'."
                    )
                    % fname,
                    log_msg=str(e),
                )
        if fixed:
            MessagebarAndLog.info(
                bar_msg=QCoreApplication.translate(
                    "_FixStylesDialog",
                    "Fixed %d style file(s): %s",
                )
                % (len(fixed), ", ".join(fixed))
            )
            self._scan()


class MatplotlibStyles:
    def __init__(
        self,
        plot_object,
        style_list,
        import_button,
        open_folder_button,
        available_settings_button,
        save_as_button,
        fix_styles_button,
        last_used_style_settingskey,
        defaultstyle_stylename,
        msettings=None,
    ):

        # Gui objects
        self.style_list = style_list
        self.import_button = import_button
        self.open_folder_button = open_folder_button
        self.available_settings_button = available_settings_button
        self.save_as_button = save_as_button
        self.fix_styles_button = fix_styles_button

        self.style_extension = ".mplstyle"
        self.style_folder = os.path.join(mpl.get_configdir(), "stylelib")
        if os.path.isdir(mpl.get_configdir()):
            if os.path.exists(self.style_folder):
                if not os.path.isdir(self.style_folder):
                    MessagebarAndLog.warning(
                        bar_msg=returnunicode(
                            QCoreApplication.translate(
                                "MatplotlibStyles",
                                """Matplotlib style folder %s was not a directory!""",
                            )
                        )
                        % self.style_folder
                    )
            else:
                try:
                    os.makedirs(self.style_folder)
                except Exception as e:
                    MessagebarAndLog.warning(
                        bar_msg=returnunicode(
                            QCoreApplication.translate(
                                "MatplotlibStyles",
                                """Could not create style folder %s, see log message panel!""",
                            )
                        )
                        % self.style_folder,
                        log_msg=str(e),
                    )
                else:
                    MessagebarAndLog.info(
                        bar_msg=returnunicode(
                            QCoreApplication.translate(
                                "MatplotlibStyles",
                                """Matplotlib style folder created %s.""",
                            )
                        )
                        % self.style_folder
                    )
        else:
            MessagebarAndLog.warning(
                bar_msg=returnunicode(
                    QCoreApplication.translate(
                        "MatplotlibStyles",
                        """Matplotlib config directory not found. User styles not used.""",
                    )
                )
            )

        if not os.path.isdir(self.style_folder):
            os.mkdir(self.style_folder)

        self.ms = msettings

        self.defaultstyle_stylename = defaultstyle_stylename

        self.last_used_style_settingskey = last_used_style_settingskey

        # Always write the Midvatten default so the installed copy stays current.
        self.save_style_to_stylelib(self.defaultstyle_stylename)
        self.update_style_list()
        try:
            last_used_style = self.ms.settingsdict[self.last_used_style_settingskey]
        except Exception:
            MessagebarAndLog.warning(
                bar_msg=returnunicode(
                    QCoreApplication.translate(
                        "MatplotlibStyles",
                        "Failed to load saved style, loading default style instead.",
                    )
                )
            )
        else:
            self.select_style_in_list(last_used_style)

        self.import_button.clicked.connect(lambda x: self.import_style())
        self.open_folder_button.clicked.connect(lambda x: self.open_folder())
        self.available_settings_button.clicked.connect(
            lambda x: self.available_settings_to_log()
        )
        self.save_as_button.clicked.connect(lambda x: self.save_as())
        self.fix_styles_button.clicked.connect(lambda x: self.fix_styles())

    @general_exception_handler
    def fix_styles(self):
        """Open a dialog where the user can select which style files to sanitize."""
        dialog = _FixStylesDialog(self.style_folder, self.style_extension)
        dialog.exec_()
        if dialog.fixed_any:
            self.update_style_list()

    def save_style_to_stylelib(self, stylestring_stylename):
        filename = self.filename_from_style(stylestring_stylename[1])
        content, skipped = _sanitize_mplstyle_content(stylestring_stylename[0])
        if skipped:
            MessagebarAndLog.warning(
                bar_msg=returnunicode(
                    QCoreApplication.translate(
                        "MatplotlibStyles",
                        "Style '%s': removed %d rcParams key(s) not supported by this matplotlib version (see log).",
                    )
                )
                % (stylestring_stylename[1], len(skipped)),
                log_msg=returnunicode(
                    QCoreApplication.translate(
                        "MatplotlibStyles",
                        "Style '%s': removed unsupported rcParams keys: %s",
                    )
                )
                % (stylestring_stylename[1], ", ".join(skipped)),
            )
        with open(filename, "w", encoding="utf-8") as of:
            of.write(content)
        mpl.style.reload_library()

    def get_selected_style(self):
        selected = self.style_list.selectedItems()
        if selected:
            return selected[0].text()

    def filename_from_style(self, style):
        filename = os.path.join(self.style_folder, style + self.style_extension)
        return filename

    @general_exception_handler
    def load(self, drawfunc, plot_widget_navigationtoolbar_name=None):
        # mpl.rcdefaults()
        fallback_style = "fallback_" + self.defaultstyle_stylename[1]
        self.save_style_to_stylelib([self.defaultstyle_stylename[0], fallback_style])
        styles = [
            self.get_selected_style(),
            self.defaultstyle_stylename[1],
            fallback_style,
            "default",
        ]

        use_style = None
        for _style in styles:
            if not _style:
                continue
            try:
                with plt.style.context(_style):
                    pass
            except Exception as e:
                # Before falling back, try to auto-fix the style file by removing unknown keys.
                style_file = self.filename_from_style(_style)
                if os.path.isfile(style_file):
                    try:
                        with open(style_file, encoding="utf-8") as rf:
                            raw = rf.read()
                        content, skipped = _sanitize_mplstyle_content(raw)
                        if skipped:
                            with open(style_file, "w", encoding="utf-8") as wf:
                                wf.write(content)
                            mpl.style.reload_library()
                            with plt.style.context(_style):
                                pass
                            MessagebarAndLog.warning(
                                bar_msg=returnunicode(
                                    QCoreApplication.translate(
                                        "MatplotlibStyles",
                                        "Style '%s': auto-removed %d unsupported rcParams key(s) (see log).",
                                    )
                                )
                                % (_style, len(skipped)),
                                log_msg=returnunicode(
                                    QCoreApplication.translate(
                                        "MatplotlibStyles",
                                        "Style '%s': auto-removed unsupported rcParams keys: %s",
                                    )
                                )
                                % (_style, ", ".join(skipped)),
                            )
                            use_style = _style
                            break
                    except Exception:
                        pass
                MessagebarAndLog.warning(
                    bar_msg=returnunicode(
                        QCoreApplication.translate(
                            "MatplotlibStyles",
                            "Failed to load style, check style settings in %s.",
                        )
                    )
                    % self.filename_from_style(_style),
                    log_msg=returnunicode(
                        QCoreApplication.translate("MatplotlibStyles", "Error msg %s")
                    )
                    % str(e),
                )
            else:
                use_style = _style
                break

        if use_style is not None:
            with mpl.style.context(use_style, after_reset=True):
                drawfunc()
            if plot_widget_navigationtoolbar_name is not None:
                navigationtoolbar = getattr(
                    plot_widget_navigationtoolbar_name[0],
                    plot_widget_navigationtoolbar_name[1],
                )
                navigationtoolbar.midv_use_style = use_style
        else:
            drawfunc()

    @general_exception_handler
    def import_style(self, filenames=None):
        if filenames is None:
            filenames = select_files(only_one_file=False, extension="")
        if filenames:
            for filename in filenames:
                if not filename:
                    continue

                folder, _filename = os.path.split(filename)
                basename, ext = os.path.splitext(_filename)
                newname = basename + self.style_extension
                new_fullname = os.path.join(self.style_folder, newname)
                if os.path.isfile(new_fullname):
                    answer = Askuser(
                        question="YesNo",
                        msg=returnunicode(
                            QCoreApplication.translate(
                                "MatplotlibStyles", "The style file existed. Overwrite?"
                            )
                        ),
                    )
                    if not answer:
                        return
                with open(filename, encoding="utf-8", errors="replace") as rf:
                    raw = rf.read()
                content, skipped = _sanitize_mplstyle_content(raw)
                with open(new_fullname, "w", encoding="utf-8") as wf:
                    wf.write(content)
                if skipped:
                    MessagebarAndLog.warning(
                        bar_msg=returnunicode(
                            QCoreApplication.translate(
                                "MatplotlibStyles",
                                "Imported style '%s': removed %d rcParams key(s) not supported by this matplotlib version (see log).",
                            )
                        )
                        % (basename, len(skipped)),
                        log_msg=returnunicode(
                            QCoreApplication.translate(
                                "MatplotlibStyles",
                                "Imported style '%s': removed unsupported rcParams keys: %s",
                            )
                        )
                        % (basename, ", ".join(skipped)),
                    )
            self.update_style_list()

    @general_exception_handler
    def save_as(self):
        filename = get_save_file_name_no_extension(
            parent=None,
            caption=returnunicode(
                QCoreApplication.translate("MatplotlibStyles", "Choose a file name")
            ),
            directory=self.style_folder,
            filter="mplstyle (*.mplstyle)",
        )
        if not filename.endswith(".mplstyle"):
            basename, ext = os.path.splitext(filename)
            filename = basename + ".mplstyle"
        with plt.style.context(self.get_selected_style()):
            rcparams = self.rcparams()
        with open(filename, "w", encoding="utf8") as of:
            of.write(rcparams)
        self.update_style_list()

    @general_exception_handler
    def open_folder(self):
        url = QtCore.QUrl(self.style_folder, QtCore.QUrl.TolerantMode)
        QDesktopServices.openUrl(url)

    def update_settingsdict(self):
        self.ms.settingsdict[self.last_used_style_settingskey] = (
            self.get_selected_style()
        )
        self.ms.save_settings(self.last_used_style_settingskey)

    def update_style_list(self):
        mpl.style.reload_library()
        selected_style = self.get_selected_style()
        self.style_list.clear()
        for style in sorted(plt.style.available):
            qlistwidgetitem = qgis.PyQt.QtWidgets.QListWidgetItem()
            qlistwidgetitem.setText(style)
            self.style_list.addItem(qlistwidgetitem)
            if style == selected_style:
                qlistwidgetitem.setSelected(True)

    def available_settings_to_log(self):
        rows = self.rcparams()
        MessagebarAndLog.info(
            bar_msg=returnunicode(
                QCoreApplication.translate(
                    "MatplotlibStyles", "rcParams written to log, see log messages"
                )
            ),
            log_msg=rows,
        )

    def rcparams(self):
        def format_v(v):
            if isinstance(v, (list, tuple)):
                if v:
                    return ",".join([str(_v) for _v in v])
                else:
                    return ""
            else:
                return str(v)

        return "\n".join(
            [f"{str(k)}: {format_v(v)}" for k, v in sorted(mpl.rcParams.items())]
        )

    def select_style_in_list(self, style):
        for idx in range(self.style_list.count()):
            item = self.style_list.item(idx)
            if item.text() == style:
                item.setSelected(True)
            else:
                item.setSelected(False)
