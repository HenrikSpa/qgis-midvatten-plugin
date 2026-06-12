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

import locale
import logging
import os
import re
from typing import List, Optional, Tuple, TYPE_CHECKING

from packaging.version import Version, InvalidVersion
import qgis.gui
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import QgsProject
from qgis.core import QgsVectorLayer

from midvatten.tools.utils.db_utils import DbConnectionManager

if TYPE_CHECKING:
    from midvatten.tools.midvsettings import MidvSettings

# The imports below double as PUBLIC re-exports for external consumers
# (midv_addons imports these names via midvatten_utils). Do not remove or
# rename them even when no in-repo caller remains. In-repo code should import
# these specific names from the source modules instead. See docs/superpowers/plans/
# 2026-06-10-maintainability-refactor-review.md (midv_addons contract).
from midvatten.tools.utils.message_utils import MessagebarAndLog  # noqa: F401
from midvatten.tools.utils.layer_utils import find_layer
from midvatten.tools.utils.string_utils import (
    returnunicode as ru,
    returnunicode,
)
from midvatten.tools.utils.exceptions import UsageError, UserInterruptError
from midvatten.tools.utils.file_utils import definitions_path
from midvatten.tools.utils.common_utils import (
    transpose_lists_of_lists,
)

from midvatten.definitions.db_defs import latest_database_version

from midvatten.tools.utils import db_utils, message_utils

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
                message_utils.MessagebarAndLog.warning(
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
                    message_utils.MessagebarAndLog.warning(
                        bar_msg=QCoreApplication.translate(
                            "verify_msettings_loaded_and_layer_edit_mode",
                            "Error %s is currently in editing mode.\nPlease exit this mode before proceeding with this operation.",
                        )
                        % str(layerexists.name())
                    )
                    errorsignal += 1

    if not mset.settingsdict["database"]:
        message_utils.MessagebarAndLog.warning(
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
            message_utils.MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "verify_msettings_loaded_and_layer_edit_mode",
                    "Databas is already in use",
                )
            )
            errorsignal += 1
        else:
            if not connection_ok:
                message_utils.MessagebarAndLog.warning(
                    bar_msg=QCoreApplication.translate(
                        "verify_msettings_loaded_and_layer_edit_mode",
                        "Error, The selected database doesn't exist. Please check your Midvatten Settings and database location. Reset if needed.",
                    )
                )
                errorsignal += 1

    return errorsignal


# These DB query helpers now live in db_utils; re-exported here for backward compatibility.


def ask_for_charset(
    default_charset: Optional[str] = None, msg: Optional[str] = None
) -> str:
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
    print_error_message_in_bar: bool = True,
    dbconnection: Optional[DbConnectionManager] = None,
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


def is_locale_swedish(dbconnection: Optional[DbConnectionManager] = None) -> bool:
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
        message_utils.MessagebarAndLog.info(
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
    tablename: str,
    geometrycolumn: Optional[str] = None,
    sql: Optional[str] = None,
    keycolumn: Optional[str] = None,
    dbconnection: Optional[DbConnectionManager] = None,
    layername: Optional[str] = None,
) -> QgsVectorLayer:
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


def warn_about_old_database() -> None:
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
            message_utils.MessagebarAndLog.warning(
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
            message_utils.MessagebarAndLog.info(
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
                    message_utils.MessagebarAndLog.info(
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


def add_view_obs_points_obs_lines() -> None:
    dbconnection = db_utils.DbConnectionManager()
    if not dbconnection.is_sqlite():
        message_utils.MessagebarAndLog.info(
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
        message_utils.MessagebarAndLog.info(
            bar_msg=QCoreApplication.translate(
                "Midvatten",
                'Views added. Please reload layers (Midvatten>Load default db-layers to qgis or "F7").',
            )
        )


def add_non_essential_tables(
    dbconnection: Optional[DbConnectionManager] = None,
) -> None:
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
        message_utils.MessagebarAndLog.info(
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
        message_utils.MessagebarAndLog.info(
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
        message_utils.MessagebarAndLog.info(
            log_msg=returnunicode(
                QCoreApplication.translate("select_files", "No file selected!")
            )
        )
        raise UserInterruptError()
    return csvpath


def create_markdown_table_from_table(
    tablename: str, transposed: bool = False, only_description: bool = False
) -> str:
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
