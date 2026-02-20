"""
/***************************************************************************
Name                 : Util Translator
Description          : Add translation
Date                 : July, 2017
copyright            : (C) 2017 by Luiz Motta
email                : motta.luiz@gmail.com

 ***************************************************************************/
 
 /***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/

For create file 'qm'
1) Define that files need for translation: PLUGIN_NAME.pro
2) Create 'ts': pylupdate4 -verbose PLUGIN_NAME.pro
3) Edit your translation: QtLinquist
4) Create 'qm': lrelease PLUGIN_NAME_LOCALE.ts (Ex.: _pt_BR)

"""
import glob
import os

from qgis.PyQt.QtCore import (
    QFileInfo,
    QSettings,
    QLocale,
    QTranslator,
    QCoreApplication,
)
from qgis.core import QgsApplication, Qgis


def getTranslate(name_plugin: str, name_dir: None = None):
    if name_dir is None:
        name_dir = name_plugin

    plugin_path = os.path.join("python", "plugins", name_dir)

    user_path = QFileInfo(QgsApplication.qgisUserDatabaseFilePath()).path()
    user_plugin_path = os.path.join(user_path, plugin_path)

    system_path = QgsApplication.prefixPath()
    system_plugin_path = os.path.join(system_path, plugin_path)

    pp = user_plugin_path if QFileInfo(user_plugin_path).exists() else system_plugin_path

    override_locale = QSettings().value("locale/overrideFlag", False, type=bool)
    if override_locale:
        qm_path_filepattern = os.path.join(
            "i18n",
            "{0}_{1}_*.qm".format(
                name_plugin, QSettings().value("locale/userLocale", "")
            ),
        )

        qmfiles = glob.glob(os.path.join(pp, qm_path_filepattern))
        if qmfiles:
            translation_file = sorted(qmfiles)[0]
            QgsApplication.messageLog().logMessage(
                (
                    f"QGIS location overried is activated. Using the first found translationfile for pattern {qm_path_filepattern}."
                ),
                "Midvatten",
                level=Qgis.Info,
            )
        else:
            QgsApplication.messageLog().logMessage(
                (
                    f"QGIS location overried is activated. No translation file found using pattern {qm_path_filepattern}, no translation file installed!"
                ),
                "Midvatten",
                level=Qgis.Info,
            )
            return
    else:
        locale_full_name = QLocale.system().name()
        qm_path_file = os.path.join(
            "i18n", f"{name_plugin}_{locale_full_name}.qm"
        )
        translation_file = os.path.join(pp, qm_path_file)

    if QFileInfo(translation_file).exists():
        translator = QTranslator()
        translator.load(translation_file)
        QCoreApplication.installTranslator(translator)
        QgsApplication.messageLog().logMessage(
            (f"Installed translation file {translation_file}"),
            "Midvatten",
            level=Qgis.Info,
        )
        return translator
    else:
        QgsApplication.messageLog().logMessage(
            (
                f"translationFile {translation_file} didn't exist, no translation file installed!"
            ),
            "Midvatten",
            level=Qgis.Info,
        )
