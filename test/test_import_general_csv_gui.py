"""
/***************************************************************************
 This part of the Midvatten plugin tests the module that handles importing of
  measurements.

 This part is to a big extent based on QSpatialite plugin.
                             -------------------
        begin                : 2016-03-08
        copyright            : (C) 2016 by joskal (HenrikSpa)
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

from collections import OrderedDict
from unittest import mock
from unittest.mock import MagicMock

import pytest
import qgis.PyQt

from midvatten.test import utils_for_tests
from midvatten.tools.import_general_csv_gui import GeneralCsvImportGui
from midvatten.tools.utils import common_utils
from midvatten.tools.utils import db_utils


@pytest.mark.active
class TestStaticMethods:
    def test_translate_and_reorder_file_data(self):
        file_data = [["obsid", "acol", "acol2"], ["rb1", "1", "2"]]

        translation_dict = {
            "obsid": ["obsid"],
            "acol": ["num", "txt"],
            "acol2": ["comment"],
        }

        test_string = utils_for_tests.create_test_string(
            GeneralCsvImportGui.translate_and_reorder_file_data(
                file_data, translation_dict
            )
        )
        reference_string = "[[num, txt, comment, obsid], [1, 1, 2, rb1]]"
        assert test_string == reference_string

    def test_convert_comma_to_points_for_double_columns(self):
        file_data = [
            ["obsid", "date_time", "reading"],
            ["obs1,1", "2017-04-12 11:03", "123,456"],
        ]

        # (6, 'comment', 'text', 0, None, 0)
        tables_columns = (
            (0, "obsid", "text", 0, None, 0),
            (1, "reading", "double", 0, None, 0),
        )
        test_string = common_utils.anything_to_string_representation(
            GeneralCsvImportGui.convert_comma_to_points_for_double_columns(
                file_data, tables_columns
            )
        )
        reference = '[["obsid", "date_time", "reading"], ["obs1,1", "2017-04-12 11:03", "123.456"]]'
        assert test_string == reference


@pytest.mark.spatialite
class TestGeneralCsvImportSpatialite(utils_for_tests.MidvattenTestSpatialiteDbSv):
    """Integration tests for GeneralCsvImportGui.start_import().

    Exercises the full user-triggered path that import_general_csv_gui runs
    when the user clicks "Start import":
      load_files() -> table chooser wiring -> start_import() ->
      _route_source_to_logger_series() (new dbconn.transaction() wrap) ->
      MidvDataImporter.general_import() -> INSERT into w_levels_logger.

    Targets ``w_levels_logger`` because that path invokes
    ``_route_source_to_logger_series``, which was recently wrapped in
    ``dbconn.transaction()``; this test guards that wrap end-to-end.
    """

    def _run_w_levels_logger_import(self, mock_messagebar):
        csv_text = "\n".join(
            [
                "obsid,date_time,head_cm,source",
                "rb1,2016-03-15 10:30:00,100.0,fileA",
                "rb1,2016-03-15 11:00:00,101.0,fileA",
                "rb1,2016-03-15 12:00:00,102.0,fileB",
            ]
        )

        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")

        with common_utils.tempinput(csv_text, "utf-8", suffix=".csv") as filename:

            @mock.patch("midvatten.tools.import_data_to_db.common_utils.Askuser")
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch("qgis.PyQt.QtWidgets.QInputDialog.getText")
            @mock.patch(
                "midvatten.tools.import_data_to_db.common_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch.object(qgis.PyQt.QtWidgets.QFileDialog, "getOpenFileName")
            def _run(
                self,
                filename,
                mock_filename,
                mock_popup,
                mock_encoding,
                mock_iface,
                mock_askuser,
            ):
                mock_filename.return_value = [filename]
                mock_encoding.return_value = ["utf-8", True]

                def side_effect(*args, **kwargs):
                    mock_result = mock.MagicMock()
                    if "msg" in kwargs and kwargs["msg"].startswith(
                        "Does the file contain a header?"
                    ):
                        mock_result.result = 1
                        return mock_result
                    if len(args) > 1:
                        if args[1].startswith("Do you want to confirm"):
                            mock_result.result = 0
                            return mock_result
                        elif args[1].startswith("Do you want to import all"):
                            mock_result.result = 0
                            return mock_result
                        elif args[1].startswith("Note:\nForeign keys"):
                            mock_result.result = 1
                            return mock_result
                        elif args[1].startswith("Please note!\nThere are"):
                            mock_result.result = 1
                            return mock_result
                        elif args[1].startswith("It is a strong recommendation"):
                            mock_result.result = 0
                            return mock_result
                    return mock_result

                mock_askuser.side_effect = side_effect

                ms = MagicMock()
                ms.settingsdict = OrderedDict()
                importer = GeneralCsvImportGui(self.iface, ms)
                importer.load_gui()
                importer.load_files()
                importer.table_chooser.import_method = "w_levels_logger"

                file_to_db = {
                    "obsid": "obsid",
                    "date_time": "date_time",
                    "head_cm": "head_cm",
                    "source": "source",
                }
                for column in importer.table_chooser.columns:
                    if column.db_column in file_to_db:
                        column.file_column_name = file_to_db[column.db_column]

                importer.start_import()

            _run(self, filename)

        print(f"{mock_messagebar.mock_calls=}")

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_start_import_into_w_levels_logger_routes_source_to_series(
        self, mock_messagebar
    ):
        self._run_w_levels_logger_import(mock_messagebar)

        series_result = db_utils.sql_load_fr_db(
            "SELECT obsid, source FROM w_logger_series ORDER BY obsid, source"
        )
        assert series_result[0] is True
        assert [tuple(r) for r in series_result[1]] == [
            ("rb1", "fileA"),
            ("rb1", "fileB"),
        ]

        rows_result = db_utils.sql_load_fr_db(
            "SELECT l.obsid, l.date_time, l.head_cm, s.source"
            " FROM w_levels_logger l"
            " LEFT JOIN w_logger_series s ON s.id = l.series_id"
            " ORDER BY l.date_time"
        )
        assert rows_result[0] is True
        assert [tuple(r) for r in rows_result[1]] == [
            ("rb1", "2016-03-15 10:30:00", 100.0, "fileA"),
            ("rb1", "2016-03-15 11:00:00", 101.0, "fileA"),
            ("rb1", "2016-03-15 12:00:00", 102.0, "fileB"),
        ]
