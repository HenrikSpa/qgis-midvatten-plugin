"""ExportSpatialite — exports the current Midvatten database to a new SpatiaLite file."""

import logging
import os

from qgis.PyQt.QtCore import QCoreApplication, QSettings

from midvatten.tools.create_db import NewDb
from midvatten.tools.export_data import ExportData
from midvatten.tools.utils import common_utils, db_utils

log = logging.getLogger(__name__)


class ExportSpatialite:
    def __init__(self, iface, ms):
        self._iface = iface
        self._ms = ms

    def show(self) -> None:
        common_utils.start_waiting_cursor()

        obsid_p = common_utils.get_selected_features_as_tuple("obs_points")
        obsid_l = common_utils.get_selected_features_as_tuple("obs_lines")
        log.debug("Selected obs_points to export:%s", obsid_p)
        log.debug("Selected obs_lines to export:%s", obsid_l)
        common_utils.stop_waiting_cursor()

        selected_all = (
            QCoreApplication.translate("Midvatten", "selected")
            if any([obsid_p, obsid_l])
            else QCoreApplication.translate("Midvatten", "all")
        )

        sanity = common_utils.Askuser(
            "YesNo",
            QCoreApplication.translate(
                "Midvatten",
                """This will create a new empty Midvatten DB with predefined design\nand fill the database with data from %s obs_points and obs_lines.\n\nContinue?""",
            )
            % selected_all,
            QCoreApplication.translate("Midvatten", "Are you sure?"),
        )
        if sanity.result == 1:
            common_utils.start_waiting_cursor()
            source_srid = db_utils.sql_load_fr_db(
                """SELECT srid FROM geometry_columns WHERE f_table_name = 'obs_points';"""
            )[1][0][0]
            w_levels_logger_timezone = db_utils.get_timezone_from_db("w_levels_logger")
            w_levels_timezone = db_utils.get_timezone_from_db("w_levels")
            common_utils.stop_waiting_cursor()
            user_chosen_epsg_code = common_utils.ask_for_export_crs(source_srid)
            common_utils.start_waiting_cursor()

            if not user_chosen_epsg_code:
                common_utils.stop_waiting_cursor()
                return None

            filenamepath = os.path.join(os.path.dirname(__file__), "..", "metadata.txt")
            ini_text = QSettings(filenamepath, QSettings.Format.IniFormat)
            verno = str(ini_text.value("version"))

            newdbinstance = NewDb()
            newdbinstance.create_new_spatialite_db(
                verno,
                user_select_crs="n",
                epsg_code=user_chosen_epsg_code,
                delete_srids=False,
                w_levels_logger_timezone=w_levels_logger_timezone,
                w_levels_timezone=w_levels_timezone,
            )
            common_utils.start_waiting_cursor()
            if newdbinstance.db_settings:
                new_dbpath = db_utils.get_spatialite_db_path_from_dbsettings_string(
                    newdbinstance.db_settings
                )
                if not new_dbpath:
                    common_utils.MessagebarAndLog.critical(
                        bar_msg=QCoreApplication.translate(
                            "export_spatialite",
                            "Export to spatialite failed, see log message panel",
                        ),
                        button=True,
                    )
                    common_utils.stop_waiting_cursor()
                    return
                exportinstance = ExportData(self._iface, self._ms)
                exportinstance.ID_obs_points = obsid_p
                exportinstance.ID_obs_lines = obsid_l
                exportinstance.export_2_splite(new_dbpath, user_chosen_epsg_code)

            common_utils.stop_waiting_cursor()
