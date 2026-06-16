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
from midvatten.tools import import_general_csv_gui
from midvatten.tools.import_general_csv_gui import (
    GeneralCsvImportGui,
    ImportTableChooser,
)
from midvatten.tools.utils import db_utils, exceptions, file_utils, string_utils


@pytest.mark.active
class TestCsvEncodingHelpers:
    def test_last_encoding_returns_stored_value(self):
        with mock.patch("midvatten.tools.import_general_csv_gui.QSettings") as mock_qs:
            mock_qs.return_value.value.return_value = "cp1252"
            assert import_general_csv_gui._last_csv_encoding() == "cp1252"

    def test_last_encoding_falls_back_to_locale(self):
        with (
            mock.patch("midvatten.tools.import_general_csv_gui.QSettings") as mock_qs,
            mock.patch(
                "midvatten.tools.import_general_csv_gui.midvatten_utils.getcurrentlocale",
                return_value=("sv_SE", "iso-8859-1"),
            ),
        ):
            mock_qs.return_value.value.return_value = None
            assert import_general_csv_gui._last_csv_encoding() == "iso-8859-1"

    def test_last_encoding_falls_back_to_utf8_when_locale_encoding_is_none(self):
        with (
            mock.patch("midvatten.tools.import_general_csv_gui.QSettings") as mock_qs,
            mock.patch(
                "midvatten.tools.import_general_csv_gui.midvatten_utils.getcurrentlocale",
                return_value=(None, None),
            ),
        ):
            mock_qs.return_value.value.return_value = None
            assert import_general_csv_gui._last_csv_encoding() == "utf-8"

    def test_save_encoding_writes_setting(self):
        with mock.patch("midvatten.tools.import_general_csv_gui.QSettings") as mock_qs:
            import_general_csv_gui._save_csv_encoding("utf-8")
            mock_qs.return_value.setValue.assert_called_once_with(
                import_general_csv_gui.CSV_ENCODING_SETTING, "utf-8"
            )


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
        test_string = string_utils.anything_to_string_representation(
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
      _route_series_metadata() (dbconn.transaction() wrap) ->
      MidvDataImporter.general_import() -> INSERT into w_levels_logger.

    Targets ``w_levels_logger`` because that path invokes
    ``_route_series_metadata``, which wraps the w_logger_series inserts in
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

        with file_utils.tempinput(csv_text, "utf-8", suffix=".csv") as filename:

            @mock.patch("midvatten.tools.utils.dialog_utils.Askuser", mock.MagicMock())
            @mock.patch("qgis.utils.iface", autospec=True)
            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info", autospec=True
            )
            @mock.patch("midvatten.tools.import_general_csv_gui.CsvFileLoadDialog")
            def _run(self, filename, mock_dialog, mock_popup, mock_iface):
                instance = mock_dialog.return_value
                instance.exec.return_value = qgis.PyQt.QtWidgets.QDialog.Accepted
                instance.filename = filename
                instance.charset = "utf-8"
                instance.has_header = True

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
                }
                for column in importer.table_chooser.columns:
                    if column.db_column in file_to_db:
                        column.file_column_name = file_to_db[column.db_column]

                # source now lives in the logger-series metadata block.
                for column in importer.table_chooser.series_columns:
                    if column.db_column == "source":
                        column.file_column_name = "source"
                    else:
                        column.file_column_name = None

                importer.start_import()

            _run(self, filename)

        print(f"{mock_messagebar.mock_calls=}")

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
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

    def test_series_block_built_for_w_levels_logger(self):
        """Choosing w_levels_logger on the new schema builds a series block with
        one ColumnEntry per editable w_logger_series field; choosing another
        table builds none."""
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")

        ms = MagicMock()
        ms.settingsdict = OrderedDict()
        gui = GeneralCsvImportGui(self.iface, ms)
        gui.load_gui()
        # A non-None file_header is required for choose_method to build the grid.
        gui.table_chooser.file_header = ["obsid", "date_time", "head_cm", "source"]

        gui.table_chooser.import_method = "w_levels_logger"
        series_fields = sorted(c.db_column for c in gui.table_chooser.series_columns)
        assert series_fields == ["comment", "description", "instrument", "source"]

        gui.table_chooser.import_method = "obs_points"
        assert gui.table_chooser.series_columns == []

    def test_old_schema_source_is_plain_column_no_series_block(self):
        """Without w_logger_series / series_id, source is a normal column and
        no series block is built."""
        tables_columns = {
            "w_levels_logger": [
                (0, "obsid", "text", 1, None, 1),
                (1, "date_time", "text", 1, None, 2),
                (2, "head_cm", "double", 0, None, 0),
                (3, "source", "text", 0, None, 0),
            ],
        }
        chooser = ImportTableChooser(tables_columns, file_header=["obsid", "source"])
        chooser.import_method = "w_levels_logger"
        assert chooser.series_columns == []
        assert "source" in [c.db_column for c in chooser.columns]

    @mock.patch("midvatten.tools.import_general_csv_gui.CsvFileLoadDialog")
    def test_load_files_cancel_raises_userinterrupt(self, mock_dialog):
        mock_dialog.return_value.exec.return_value = (
            qgis.PyQt.QtWidgets.QDialog.Rejected
        )
        ms = MagicMock()
        ms.settingsdict = OrderedDict()
        importer = GeneralCsvImportGui(self.iface, ms)
        importer.load_gui()
        with pytest.raises(exceptions.UserInterruptError):
            importer.load_files()


@pytest.mark.spatialite
class TestShowIsIdempotent(utils_for_tests.MidvattenTestSpatialiteDbSv):
    """Re-showing the same instance must not rebuild widgets or re-connect
    button signals (GeneralCsvImportGui is constructed directly by external
    callers that own the instance lifetime)."""

    def test_second_show_does_not_duplicate_gui(self):
        ms = MagicMock()
        ms.settingsdict = OrderedDict()
        gui = GeneralCsvImportGui(self.iface, ms)

        gui.show()
        button_rows = gui.grid_layout_buttons.count()
        select_button = gui.select_file_button

        gui.show()

        assert gui.grid_layout_buttons.count() == button_rows
        assert gui.select_file_button is select_button
        # One connection: one slot invocation per click
        with mock.patch.object(gui, "select_file") as select_file:
            gui.select_file_button.clicked.emit(False)
        assert select_file.call_count == 1


@pytest.mark.spatialite
class TestCsvFileLoadDialog(utils_for_tests.MidvattenTestSpatialiteDbSv):
    def _dialog(self):
        with mock.patch("midvatten.tools.import_general_csv_gui.QSettings") as mock_qs:
            mock_qs.return_value.value.return_value = "utf-8"
            return import_general_csv_gui.CsvFileLoadDialog()

    def test_ok_disabled_until_file_chosen(self):
        dlg = self._dialog()
        assert dlg._ok_button().isEnabled() is False

    def test_properties_reflect_widgets(self):
        dlg = self._dialog()
        dlg._encoding.setEditText("cp1252")
        dlg._header.setChecked(False)
        assert dlg.charset == "cp1252"
        assert dlg.has_header is False

    def test_preview_renders_readable_text_with_correct_encoding(self):
        csv_text = "obsid;date_time;level\nBjörkån;2024-01-01;3,14\n"
        with file_utils.tempinput(csv_text, "utf-8", suffix=".csv") as filename:
            dlg = self._dialog()
            dlg._filename = filename
            dlg._encoding.setEditText("utf-8")
            dlg._refresh_preview()
            assert "Björkån" in dlg._preview.toPlainText()

    def test_preview_shows_mojibake_with_wrong_encoding(self):
        # File written as utf-8, read as cp1252 -> the å/ä/ö become mojibake.
        csv_text = "obsid\nBjörkån\n"
        with file_utils.tempinput(csv_text, "utf-8", suffix=".csv") as filename:
            dlg = self._dialog()
            dlg._filename = filename
            dlg._encoding.setEditText("cp1252")
            dlg._refresh_preview()
            preview = dlg._preview.toPlainText()
            assert "Björkån" not in preview
            assert "BjÃ" in preview  # mis-decoded utf-8 multibyte sequence

    def test_browse_cancel_leaves_ok_disabled(self):
        dlg = self._dialog()
        with mock.patch(
            "midvatten.tools.import_general_csv_gui.midvatten_utils.select_files",
            side_effect=exceptions.UserInterruptError(),
        ):
            dlg._browse()
        assert dlg._ok_button().isEnabled() is False
        assert dlg.filename is None

    def test_accept_saves_encoding(self):
        dlg = self._dialog()
        dlg._encoding.setEditText("iso-8859-1")
        with mock.patch("midvatten.tools.import_general_csv_gui.QSettings") as mock_qs:
            dlg.accept()
        mock_qs.return_value.setValue.assert_called_once_with(
            import_general_csv_gui.CSV_ENCODING_SETTING, "iso-8859-1"
        )
