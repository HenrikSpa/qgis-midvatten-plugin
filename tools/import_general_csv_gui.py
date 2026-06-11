"""
/***************************************************************************
 This part of the Midvatten plugin handles importing of data to the database
  from the fieldlogger format.

 This part is to a big extent based on QSpatialite plugin.
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

import copy
import csv
from operator import itemgetter

import qgis.PyQt
from qgis.PyQt.QtCore import QCoreApplication

import midvatten.definitions.midvatten_defs as defs
from midvatten.tools import import_data_to_db
from midvatten.tools.utils import (
    common_utils,
    midvatten_utils,
    db_utils,
    date_utils,
    exceptions,
    file_utils,
)
from midvatten.tools.utils.file_utils import ui_path
from midvatten.tools.utils.string_utils import returnunicode as ru
from midvatten.tools.utils.gui_utils import (
    RowEntry,
    VRowEntry,
    WA_DeleteOnClose,
    get_line,
    RowEntryGrid,
    DistinctValuesBrowser,
)
from typing import Any, Dict, List, Tuple

import_ui_dialog = qgis.PyQt.uic.loadUiType(ui_path("import_fieldlogger.ui"))[0]

# Editable w_logger_series fields the CSV importer can map for w_levels_logger.
SERIES_FIELDS = ("source", "instrument", "description", "comment")
# Carrier columns ride the import pipeline under this prefix so series mappings
# stay row-aligned and never collide with real columns (e.g. ``comment``, which
# exists in both tables). It is the contract between get_series_translation
# (producer) and _route_series_metadata (consumer); keep the prefix in one place.
SERIES_CARRIER_PREFIX = "__series_"


def series_carrier(field: str) -> str:
    return SERIES_CARRIER_PREFIX + field


class GeneralCsvImportGui(qgis.PyQt.QtWidgets.QMainWindow, import_ui_dialog):
    def __init__(self, iface, ms, dbconnection=None):
        self.iface = iface
        self.ms = ms
        self.ms.load_settings()
        qgis.PyQt.QtWidgets.QMainWindow.__init__(self, iface.mainWindow())
        self.setAttribute(WA_DeleteOnClose)
        self.setupUi(self)  # Required by Qt
        self.setWindowTitle(
            QCoreApplication.translate("GeneralCsvImportGui", "Csv import")
        )
        self.table_chooser = None
        self.file_data = None
        self.srid = None
        self.dbconnection = dbconnection

    def show(self) -> None:
        self.load_gui()
        super().show()
        self.activateWindow()

    def load_gui(self):
        self.tables_columns_info = {
            k: v
            for (k, v) in db_utils.db_tables_columns_info(
                dbconnection=self.dbconnection
            ).items()
            if not k.endswith("_geom")
        }
        # On the new schema, source has moved from w_levels_logger to
        # w_logger_series. The chooser renders a dedicated "Logger series
        # metadata" block for w_levels_logger (see ImportTableChooser.
        # _append_series_block); source and the other series fields are mapped
        # there and routed into w_logger_series by _route_series_metadata.
        self.table_chooser = ImportTableChooser(
            self.tables_columns_info,
            file_header=None,
            embed_chooser_in_layout=False,
        )
        self.main_vertical_layout.addWidget(self.table_chooser)
        self.main_vertical_layout.addStretch()
        # General buttons
        self.select_file_button = qgis.PyQt.QtWidgets.QPushButton(
            QCoreApplication.translate("GeneralCsvImportGui", "Load data from file")
        )
        self.grid_layout_buttons.addWidget(self.select_file_button, 0, 0)
        self.select_file_button.clicked.connect(lambda x: self.select_file())

        self.import_all_features_button = qgis.PyQt.QtWidgets.QPushButton(
            QCoreApplication.translate(
                "GeneralCsvImportGui",
                "Load data from all features\nfrom active layer",
            )
        )
        self.grid_layout_buttons.addWidget(self.import_all_features_button, 1, 0)
        self.import_all_features_button.clicked.connect(
            lambda x: self.import_all_features()
        )

        self.import_selected_features_button = qgis.PyQt.QtWidgets.QPushButton(
            QCoreApplication.translate(
                "GeneralCsvImportGui",
                "Load data from selected features\nfrom active layer",
            )
        )
        self.grid_layout_buttons.addWidget(self.import_selected_features_button, 2, 0)
        self.import_selected_features_button.clicked.connect(
            lambda x: self.import_selected_features()
        )

        self.grid_layout_buttons.addWidget(self.table_chooser.chooser_widget, 3, 0)
        self.table_chooser.set_chooser_enabled(False)

        self.grid_layout_buttons.addWidget(get_line(), 4, 0)

        tables_columns = db_utils.tables_columns()
        self.distinct_value_browser = DistinctValuesBrowser(tables_columns)
        self.grid_layout_buttons.addWidget(self.distinct_value_browser, 5, 0)

        self.grid_layout_buttons.addWidget(get_line(), 6, 0)

        self.close_after_import = qgis.PyQt.QtWidgets.QCheckBox(
            QCoreApplication.translate(
                "GeneralCsvImportGui", "Close dialog after import"
            )
        )
        self.close_after_import.setChecked(True)
        self.grid_layout_buttons.addWidget(self.close_after_import, 7, 0)

        self.start_import_button = qgis.PyQt.QtWidgets.QPushButton(
            QCoreApplication.translate("GeneralCsvImportGui", "Start import")
        )
        self.grid_layout_buttons.addWidget(self.start_import_button, 8, 0)
        self.start_import_button.clicked.connect(lambda x: self.start_import())

        self.grid_layout_buttons.setRowStretch(9, 1)
        self.setGeometry(100, 100, 1800, 800)

    @common_utils.general_exception_handler
    def select_file(self):
        self.load_files()
        self.table_chooser.reload()
        self._on_file_data_loaded()

    @common_utils.general_exception_handler
    @common_utils.waiting_cursor
    def import_all_features(self):
        self.load_from_active_layer(only_selected=False)
        self.table_chooser.reload()
        self._on_file_data_loaded()

    @common_utils.general_exception_handler
    @common_utils.waiting_cursor
    def import_selected_features(self):
        self.load_from_active_layer(only_selected=True)
        self.table_chooser.reload()
        self._on_file_data_loaded()

    def load_files(self):
        charset = midvatten_utils.ask_for_charset()
        if not charset:
            raise exceptions.UserInterruptError()
        filename = midvatten_utils.select_files(
            only_one_file=True,
            extension=QCoreApplication.translate(
                "GeneralCsvImportGui",
                "Comma or semicolon separated csv file %s;;Comma or semicolon separated csv text file %s;;Comma or semicolon separated file %s",
            )
            % ("(*.csv)", "(*.txt)", "(*.*)"),
        )
        if isinstance(filename, (list, tuple)):
            filename = filename[0]

        filename = ru(filename)

        delimiter = file_utils.get_delimiter(
            filename=filename, charset=charset, delimiters=[",", ";"]
        )
        self.file_data = self.file_to_list(filename, charset, delimiter)

        common_utils.stop_waiting_cursor()
        header_question = common_utils.Askuser(
            question="YesNo",
            msg=QCoreApplication.translate(
                "GeneralCsvImportGui", """Does the file contain a header?"""
            ),
        )
        common_utils.start_waiting_cursor()

        if header_question.result:
            # Remove duplicate header entries
            header = self.file_data[0]
            seen = set()
            seen_add = seen.add
            remove_cols = [
                idx for idx, x in enumerate(header) if x and (x in seen or seen_add(x))
            ]
            self.file_data = [
                [col for idx, col in enumerate(row) if idx not in remove_cols]
                for row in self.file_data
            ]

            self.table_chooser.file_header = self.file_data[0]
        else:
            header = ["Column " + str(colnr) for colnr in range(len(self.file_data[0]))]
            self.table_chooser.file_header = header
            self.file_data.reverse()
            self.file_data.append(header)
            self.file_data.reverse()
        common_utils.stop_waiting_cursor()

    def _on_file_data_loaded(self):
        if self.file_data is not None:
            for button in (
                self.select_file_button,
                self.import_all_features_button,
                self.import_selected_features_button,
            ):
                button.setEnabled(False)
            self.table_chooser.set_chooser_enabled(True)

    @staticmethod
    def file_to_list(filename, charset, delimiter, quotechar='"'):
        common_utils.start_waiting_cursor()
        try:
            with open(filename, encoding=str(charset)) as f:
                rows_unsplit = [row.lstrip().rstrip("\n").rstrip("\r") for row in f]
                csvreader = csv.reader(
                    rows_unsplit, delimiter=delimiter, quotechar=quotechar
                )
                file_data = [ru(row, keep_containers=True) for row in csvreader]
        except Exception:
            common_utils.stop_waiting_cursor()
            raise
        else:
            common_utils.stop_waiting_cursor()
        return file_data

    def load_from_active_layer(self, only_selected=False):
        self.file_data = None
        self.table_chooser.file_header = None

        active_layer = common_utils.get_active_layer()
        if not active_layer:
            common_utils.MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "GeneralCsvImportGui", "Import error, no layer selected."
                )
            )
            return None

        if not only_selected:
            active_layer.selectAll()

        features = list(active_layer.getSelectedFeatures())
        file_data = self.parse_features_into_file_data(features, active_layer)

        geometries = [
            feature.geometry().asWkt() if feature.geometry().asWkt() else None
            for feature in features
        ]
        if any(geometries):
            geom_name = "geometry"
            while geom_name in file_data[0]:
                geom_name += "_"
            file_data[0].append(geom_name)
            [file_data[idx + 1].append(wkt) for idx, wkt in enumerate(geometries)]

        self.file_data = file_data
        self.srid = active_layer.crs().authid()
        self.table_chooser.file_header = file_data[0]

    def parse_features_into_file_data(self, features, active_layer):
        return [[ru(field.name()) for field in active_layer.fields()]] + [
            [
                (
                    ru(attr)
                    if all(
                        [
                            ru(attr).strip() != "NULL",
                            attr is not None,
                        ]
                    )
                    else ""
                )
                for attr in feature
            ]
            for feature in features
        ]

    @common_utils.waiting_cursor
    @common_utils.general_exception_handler
    @import_data_to_db.import_exception_handler
    def start_import(self):
        """
        TODO: I have NO IDEA where the dummy parameter is coming from. It gets the value False for some reason!
        :param dummy:
        :return:
        """
        if self.file_data is None:
            raise exceptions.UsageError(
                QCoreApplication.translate(
                    "GeneralCsvImportGui", "Error, must select a file first!"
                )
            )

        translation_dict = self.table_chooser.get_translation_dict()

        dest_table = self.table_chooser.import_method

        # Series metadata mappings merge into translation_dict under their
        # namespaced __series_<field> carrier targets, so the existing
        # StaticValue-injection and translate/reorder pipeline carries them
        # through row-aligned. _route_series_metadata consumes and strips them.
        if dest_table == "w_levels_logger":
            for (
                file_column,
                carriers,
            ) in self.table_chooser.get_series_translation().items():
                translation_dict[file_column] = (
                    translation_dict.get(file_column, []) + carriers
                )

        file_data = copy.deepcopy(self.file_data)

        foreign_keys = db_utils.get_foreign_keys(
            dest_table, dbconnection=self.dbconnection
        )

        foreign_key_obsid_tables = [
            tname
            for tname, colnames in foreign_keys.items()
            for colname in colnames
            if colname[0] == "obsid"
        ]
        if len(foreign_key_obsid_tables) == 1:
            foreign_key_obsid_table = foreign_key_obsid_tables[0]
        else:
            foreign_key_obsid_table = dest_table
        for file_column in list(translation_dict.keys()):
            alter_colnames = []
            new_value = None
            # Check if obsid should be set from selection and add an obsid-column if so.
            if isinstance(file_column, Obsids_from_selection):
                selected = common_utils.get_selected_features_as_tuple()
                if len(selected) != 1:
                    common_utils.MessagebarAndLog.critical(
                        bar_msg=QCoreApplication.translate(
                            "GeneralCsvImportGui",
                            "Import error, must select 1 obsid",
                        ),
                        duration=60,
                    )
                    return "cancel"
                alter_colnames = ["obsid"]
                new_value = selected[0]
            elif isinstance(file_column, StaticValue):
                if translation_dict[file_column]:
                    alter_colnames = translation_dict[file_column]
                    new_value = file_column.value
            for alter_colname in alter_colnames:
                if alter_colnames is not None and new_value is not None:
                    try:
                        colindex = file_data[0].index(alter_colname)
                    except ValueError:
                        colindex = len(file_data[0])
                        file_data[0].append(alter_colname)

                    for row in file_data[1:]:
                        if colindex + 1 < len(file_data[0]):
                            row[colindex] = new_value
                        else:
                            row.append(new_value)

                    del translation_dict[file_column]

                    translation_dict[alter_colname] = [alter_colname]

        columns_factors = self.table_chooser.get_columns_factors_dict()

        # Translate column names and add columns that appear more than once
        file_data = self.translate_and_reorder_file_data(file_data, translation_dict)
        file_data = self.convert_comma_to_points_for_double_columns(
            file_data, self.tables_columns_info[dest_table]
        )
        if columns_factors:
            file_data = self.multiply_by_factor(file_data, columns_factors)
        file_data = self.remove_preceding_trailing_spaces_tabs(file_data)
        if (
            foreign_key_obsid_table
            and foreign_key_obsid_table != dest_table
            and "obsid" in file_data[0]
        ):
            file_data = common_utils.filter_nonexisting_values_and_ask(
                file_data,
                "obsid",
                db_utils.get_all_obsids(foreign_key_obsid_table),
                try_capitalize=False,
            )

        file_data = self.reformat_date_time(file_data)

        if dest_table == "w_levels_logger":
            file_data = self._route_series_metadata(file_data)

        importer = import_data_to_db.MidvDataImporter()
        answer = importer.general_import(
            dest_table=dest_table,
            file_data=file_data,
            source_srid=self.srid,
            _dbconnection=self.dbconnection,
        )
        common_utils.stop_waiting_cursor()

        if self.close_after_import.isChecked():
            self.close()

    def _route_series_metadata(self, file_data: List[List[Any]]) -> List[List[Any]]:
        """Turn ``__series_*`` carrier columns into ``w_logger_series`` rows and
        a ``series_id`` column on each w_levels_logger row.

        One series row is created per distinct
        ``(obsid, source, instrument, description, comment)`` tuple. Ids are
        captured at INSERT time (never re-queried), so two batches that reuse
        the same metadata still get distinct series. Always creates new series
        rows, never matches existing ones. A stray ``series_id`` column from the
        CSV is dropped with a warning: cross-DB integer ids don't translate.
        """
        if not file_data or len(file_data) < 2:
            return file_data

        header = list(file_data[0])
        rows = [list(r) for r in file_data[1:]]

        carrier_cols = [c for c in header if c.startswith(SERIES_CARRIER_PREFIX)]
        if not carrier_cols:
            return [header] + rows

        # Drop any stray CSV series_id: cross-database ids do not translate.
        if "series_id" in header:
            idx = header.index("series_id")
            header.pop(idx)
            for row in rows:
                if idx < len(row):
                    row.pop(idx)
            common_utils.MessagebarAndLog.warning(
                log_msg=QCoreApplication.translate(
                    "GeneralCsvImportGui",
                    "Ignoring 'series_id' column from CSV on import to"
                    " w_levels_logger: cross-database ids do not translate."
                    " Use the logger series metadata fields to group rows into"
                    " new series instead.",
                )
            )

        # One carrier-stripping projection shared by every exit path.
        keep = [i for i, c in enumerate(header) if c not in carrier_cols]
        stripped_header = [header[i] for i in keep]

        def _project(row):
            return [row[i] if i < len(row) else None for i in keep]

        def _stripped():
            return [stripped_header] + [_project(r) for r in rows]

        existing_tables = db_utils.tables_columns(dbconnection=self.dbconnection)
        if "w_logger_series" not in existing_tables:
            return _stripped()
        if "series_id" not in existing_tables.get("w_levels_logger", []):
            return _stripped()
        if "obsid" not in header:
            common_utils.MessagebarAndLog.warning(
                log_msg=QCoreApplication.translate(
                    "GeneralCsvImportGui",
                    "Logger series metadata supplied but no 'obsid' column;"
                    " cannot create w_logger_series rows. Series metadata will"
                    " be dropped.",
                )
            )
            return _stripped()

        present_fields = [f for f in SERIES_FIELDS if series_carrier(f) in header]
        obsid_idx = header.index("obsid")
        field_idx = {f: header.index(series_carrier(f)) for f in present_fields}

        def _norm(value):
            return value if value not in ("", None) else None

        def _key(row):
            obsid = row[obsid_idx] if obsid_idx < len(row) else None
            vals = tuple(
                _norm(row[field_idx[f]]) if field_idx[f] < len(row) else None
                for f in present_fields
            )
            return obsid, vals

        dbconn = (
            self.dbconnection
            if self.dbconnection is not None
            else db_utils.DbConnectionManager()
        )
        close_dbconn = self.dbconnection is None
        colnames = ", ".join(["obsid"] + present_fields)
        try:
            placeholders = dbconn.placeholders(1 + len(present_fields))
            key_to_sid: Dict[Tuple[Any, Tuple[Any, ...]], int] = {}
            # Atomic: a mid-loop failure rolls back every series row rather than
            # leaving key_to_sid pointing at uncommitted ids.
            with dbconn.transaction():
                for row in rows:
                    obsid, vals = _key(row)
                    if not obsid:
                        continue
                    key = (obsid, vals)
                    if key in key_to_sid:
                        continue
                    dbconn.execute(
                        f"INSERT INTO w_logger_series ({colnames})"
                        f" VALUES ({placeholders})",
                        (obsid,) + vals,
                    )
                    key_to_sid[key] = db_utils.get_last_insert_id(dbconn)
        finally:
            if close_dbconn:
                dbconn.closedb()

        new_header = stripped_header + ["series_id"]
        new_rows = []
        for row in rows:
            obsid, vals = _key(row)
            sid = key_to_sid.get((obsid, vals)) if obsid else None
            new_row = _project(row)
            new_row.append(sid)
            new_rows.append(new_row)
        return [new_header] + new_rows

    @staticmethod
    def translate_and_reorder_file_data(
        file_data: List[List[str]], translation_dict: Dict[str, List[str]]
    ) -> List[List[str]]:
        # The loop "for db_column in sorted(db_columns)" is used for cases where one file column is sent to multiple database columns.
        new_file_header = [
            db_column
            for file_column, db_columns in sorted(translation_dict.items())
            for db_column in sorted(db_columns)
        ]
        file_column_index = {
            file_column: idx for idx, file_column in enumerate(file_data[0])
        }
        reordered_rows = [
            [
                row[file_column_index[file_column]]
                for file_column, db_columns in sorted(translation_dict.items())
                for db_column in sorted(db_columns)
            ]
            for row in file_data[1:]
        ]
        return [new_file_header] + reordered_rows

    @staticmethod
    def convert_comma_to_points_for_double_columns(
        file_data: List[List[str]],
        table_column: Tuple[
            Tuple[int, str, str, int, None, int], Tuple[int, str, str, int, None, int]
        ],
    ) -> List[List[str]]:
        """
        Converts comma to point for columns with column types real or double
        :param file_data: a list of lists like [['obsid', 'date_time', 'reading'], ['obs1', '2017-04-12 11:03', '123,456']]
        :param table_column: a tuple like ((6, 'comment', 'text', 0, None, 0), (4, 'cond_mscm', 'double', 0, None, 0), (1, 'date_time', 'text', 1, None, 2), (2, 'head_cm', 'double', 0, None, 0), (5, 'level_masl', 'double', 0, None, 0), (0, 'obsid', 'text', 1, None, 1), (3, 'temp_degc', 'double', 0, None, 0))
        :return: file_data where double and real column types have been converted from comma to point.
        """
        table_column_dict = {column[1]: column[2] for column in table_column}
        colnrs_to_convert = {
            colnr
            for colnr, col in enumerate(file_data[0])
            if table_column_dict.get(col, "").lower()
            in ("double", "double precision", "real")
        }
        new_data = [file_data[0]]
        for row in file_data[1:]:
            new_row = [
                col.replace(",", ".")
                if colnr in colnrs_to_convert and col is not None
                else col
                for colnr, col in enumerate(row)
            ]
            new_data.append(new_row)
        return new_data

    @staticmethod
    def multiply_by_factor(file_data, columns_factors):
        """
        Multiplies all values in the file data with a given factor for each column
        :param file_data: a list of lists like [['obsid', 'date_time', 'reading'], ['obs1', '2017-04-12 11:03', '123,456']]
        :param table_columns_factors: a dict like {'reading': 10}
        :return: file_data where the columns have been multiplied by the factor.
        """
        header = file_data[0]
        factor_colnrs = {
            colnr: columns_factors[col]
            for colnr, col in enumerate(header)
            if col in columns_factors
        }
        new_data = [header]
        for row in file_data[1:]:
            new_row = list(row)
            for colnr, factor in factor_colnrs.items():
                if common_utils.to_float_or_none(new_row[colnr]) is not None:
                    new_row[colnr] = str(float(new_row[colnr]) * factor)
            new_data.append(new_row)
        return new_data

    @staticmethod
    def reformat_date_time(file_data):
        try:
            colnrs_to_convert = [file_data[0].index("date_time")]
        except ValueError:
            return file_data

        num_rows_before = len(file_data)
        new_file_data = [file_data[0]]
        for row in file_data[1:]:
            reformatted_dates = {}
            skip_row = False
            for colnr in colnrs_to_convert:
                result = date_utils.normalize_datestring(row[colnr])
                if result is None:
                    skip_row = True
                    break
                reformatted_dates[colnr] = result
            if skip_row:
                continue
            new_row = [
                reformatted_dates.get(colnr, col) for colnr, col in enumerate(row)
            ]
            new_file_data.append(new_row)

        num_removed_rows = num_rows_before - len(new_file_data)
        if num_removed_rows > 0:
            common_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "GeneralCsvImportGui",
                    "%s rows without parsable date_time format skipped during import",
                )
                % str(num_removed_rows)
            )
        return new_file_data

    @staticmethod
    def remove_preceding_trailing_spaces_tabs(file_data):
        file_data = [
            [
                col.lstrip().rstrip() if all([rownr > 0, col is not None]) else col
                for colnr, col in enumerate(row)
            ]
            for rownr, row in enumerate(file_data)
        ]
        return file_data


class ImportTableChooser(VRowEntry):
    def __init__(
        self,
        tables_columns,
        file_header=None,
        embed_chooser_in_layout: bool = True,
    ):
        super().__init__()
        self.tables_columns = tables_columns
        self.file_header = file_header
        self.columns = []
        self.series_columns = []
        self.grid = None
        self.numeric_datatypes = db_utils.numeric_datatypes()

        self.chooser_row = RowEntry()

        self.label = qgis.PyQt.QtWidgets.QLabel(
            QCoreApplication.translate("ImportTableChooser", "Import to table")
        )
        self.__import_method = qgis.PyQt.QtWidgets.QComboBox()
        self.__import_method.addItem("")
        self.__import_method.addItems(
            sorted(list(tables_columns.keys()), key=lambda s: s.lower())
        )

        self.__import_method.currentIndexChanged.connect(self.choose_method)

        for widget in [self.label, self.__import_method]:
            self.chooser_row.layout().addWidget(widget)
        self.chooser_row.layout().insertStretch(-1, 5)

        if embed_chooser_in_layout:
            self.layout().addWidget(self.chooser_row)

        self.specific_info_widget = VRowEntry()
        self.specific_info_widget.layout().addWidget(get_line())
        self.specific_table_info = qgis.PyQt.QtWidgets.QLabel()
        self.specific_info_widget.layout().addWidget(self.specific_table_info)
        self.specific_info_widget.layout().addWidget(get_line())

        self.layout().addWidget(self.specific_info_widget)

    def get_translation_dict(self):
        translation_dict = {}
        for column_entry in self.columns:
            file_column_name = column_entry.file_column_name
            if file_column_name:
                column_list = translation_dict.get(file_column_name, [])
                column_list = copy.deepcopy(column_list)
                column_list.append(column_entry.db_column)
                translation_dict[file_column_name] = column_list
        return translation_dict

    def get_series_translation(self):
        """translation_dict-shaped mapping for series fields, but every target
        is the namespaced carrier ``__series_<field>`` so it can never collide
        with a real column (notably ``comment``, which exists in both tables)."""
        series_translation = {}
        for column_entry in self.series_columns:
            file_column_name = column_entry.file_column_name
            if file_column_name:
                carrier = series_carrier(column_entry.db_column)
                existing = series_translation.get(file_column_name, [])
                series_translation[file_column_name] = existing + [carrier]
        return series_translation

    def get_columns_factors_dict(self):
        columns_factors = dict(
            [
                (column_entry.db_column, column_entry.factor)
                for column_entry in self.columns
                if column_entry.column_type in self.numeric_datatypes
                and column_entry.factor != 1
            ]
        )

        return columns_factors

    @property
    def import_method(self):
        return str(self.__import_method.currentText())

    @import_method.setter
    def import_method(self, value):
        index = self.__import_method.findText(ru(value))
        if index != -1:
            self.__import_method.setCurrentIndex(index)

    def choose_method(self):
        tables_columns = self.tables_columns
        file_header = self.file_header
        import_method_name = self.import_method
        try:
            layer = common_utils.find_layer(import_method_name)
        except exceptions.UsageError:
            pass
        else:
            if layer is not None:
                if layer.isEditable():
                    common_utils.pop_up_info(
                        QCoreApplication.translate(
                            "ImportTableChooser",
                            "Layer %s is currently in editing mode.\nPlease exit this mode before proceeding with this operation.",
                        )
                        % str(layer.name()),
                        QCoreApplication.translate("GeneralCsvImportGui", "Error"),
                    )
                    self.import_method = ""
                    import_method_name = None

        self.specific_table_info.setText(
            defs.specific_table_info.get(import_method_name, "")
        )

        if file_header is None:
            return None

        if self.grid is not None:
            self.layout().removeWidget(self.grid)
            self.grid.close()

        self.columns = []
        self.series_columns = []

        if not import_method_name:
            return None

        self.grid = RowEntryGrid()
        self.layout().addWidget(self.grid)

        self.grid.layout().addWidget(
            qgis.PyQt.QtWidgets.QLabel(
                QCoreApplication.translate("ImportTableChooser", "Column name")
            ),
            0,
            0,
        )
        self.grid.layout().addWidget(
            qgis.PyQt.QtWidgets.QLabel(
                QCoreApplication.translate("ImportTableChooser", "File column")
            ),
            0,
            1,
        )
        self.grid.layout().addWidget(
            qgis.PyQt.QtWidgets.QLabel(
                QCoreApplication.translate("ImportTableChooser", "Static value")
            ),
            0,
            2,
        )
        self.grid.layout().addWidget(
            qgis.PyQt.QtWidgets.QLabel(
                QCoreApplication.translate("ImportTableChooser", "Factor")
            ),
            0,
            3,
        )
        self.grid.layout().addWidget(
            qgis.PyQt.QtWidgets.QLabel(
                QCoreApplication.translate(
                    "ImportTableChooser", "Ignore not null warning"
                )
            ),
            0,
            4,
        )

        for index, tables_columns_info in enumerate(
            sorted(tables_columns[import_method_name], key=itemgetter(0))
        ):
            column = ColumnEntry(
                tables_columns_info, file_header, self.numeric_datatypes
            )
            rownr = self.grid.layout().rowCount()
            for colnr, wid in enumerate(column.column_widgets):
                self.grid.layout().addWidget(wid, rownr, colnr)
            self.columns.append(column)

        self._append_series_block(import_method_name, file_header)

        self.grid.layout().setColumnStretch(5, 5)

    def _append_series_block(self, import_method_name, file_header):
        """For w_levels_logger on the new schema, render a separated block of
        ColumnEntry rows mapping the editable w_logger_series fields."""
        if import_method_name != "w_levels_logger":
            return
        series_info = self.tables_columns.get("w_logger_series")
        wll_info = self.tables_columns.get("w_levels_logger", [])
        has_series_id = any(col[1] == "series_id" for col in wll_info)
        if not series_info or not has_series_id:
            return

        rownr = self.grid.layout().rowCount()
        self.grid.layout().addWidget(get_line(), rownr, 0, 1, 5)
        rownr = self.grid.layout().rowCount()
        self.grid.layout().addWidget(
            qgis.PyQt.QtWidgets.QLabel(
                QCoreApplication.translate(
                    "ImportTableChooser",
                    "Logger series metadata (w_logger_series)",
                )
            ),
            rownr,
            0,
            1,
            5,
        )

        # ColumnEntry prefills each field to a same-named CSV column. That is
        # convenient for series-only fields (e.g. source), but for a field whose
        # name also exists on w_levels_logger (comment) the CSV column is meant
        # for the logger row; auto-mapping it into the series key too would
        # fragment the batch into one series per distinct value. Suppress the
        # prefill for those shared names so they stay opt-in.
        info_by_name = {col[1]: col for col in series_info}
        wll_colnames = {col[1] for col in wll_info}
        for field in SERIES_FIELDS:
            col_info = info_by_name.get(field)
            if col_info is None:
                continue
            column = ColumnEntry(col_info, file_header, self.numeric_datatypes)
            if field in wll_colnames:
                column.file_column_name = None
            rownr = self.grid.layout().rowCount()
            for colnr, wid in enumerate(column.column_widgets):
                self.grid.layout().addWidget(wid, rownr, colnr)
            self.series_columns.append(column)

    def reload(self):
        import_method = self.import_method
        self.import_method = ""
        self.import_method = import_method

    @property
    def chooser_widget(self):
        return self.chooser_row

    def set_chooser_enabled(self, enabled: bool):
        self.__import_method.setEnabled(enabled)
        self.label.setEnabled(enabled)


class ColumnEntry:
    def __init__(self, tables_columns_info, file_header, numeric_datatypes):
        self.tables_columns_info = tables_columns_info
        self.obsids_from_selection = None
        self.file_header = file_header

        self.db_column = tables_columns_info[1]
        self.column_type = tables_columns_info[2]
        # Required means NOT NULL AND no column default. A column with a
        # default (e.g. ``created_at DEFAULT CURRENT_TIMESTAMP``) does not
        # need to be supplied by the CSV - the DB fills it in.
        _has_default = tables_columns_info[4] not in (None, "")
        self.notnull = int(tables_columns_info[3]) and not _has_default
        pk = int(tables_columns_info[5])
        concatted_info = ", ".join(
            [
                _x
                for _x in [
                    self.column_type,
                    "not null" if self.notnull else False,
                    "primary key" if pk else False,
                ]
                if _x
            ]
        )
        label = qgis.PyQt.QtWidgets.QLabel(
            " ".join(["Column ", self.db_column, f"({concatted_info})"])
        )

        self.column_widgets = [label]
        self._all_widgets = [label]

        self.combobox = qgis.PyQt.QtWidgets.QComboBox()
        self.combobox.setEditable(True)
        self.combobox.addItem("")
        self.combobox.addItems(sorted(self.file_header, key=lambda s: s.lower()))

        if self.db_column == "obsid":
            self.obsids_from_selection = qgis.PyQt.QtWidgets.QCheckBox(
                QCoreApplication.translate("ColumnEntry", "Obsid from qgis selection")
            )
            self.obsids_from_selection.setToolTip(
                QCoreApplication.translate(
                    "ColumnEntry",
                    "Select 1 obsid from obs_points or obs_lines attribute table or map.",
                )
            )
            self.obsids_from_selection.clicked.connect(
                lambda x: self.obsids_from_selection_checked()
            )

            self.obsid_widget = RowEntry()
            self.obsid_widget.layout().addWidget(self.obsids_from_selection)
            self.obsid_widget.layout().addWidget(self.combobox)

            self._all_widgets.extend(
                [self.obsids_from_selection, self.combobox, self.obsid_widget]
            )

            self.column_widgets.append(self.obsid_widget)
        else:
            self.column_widgets.append(self.combobox)
            self._all_widgets.extend(self.column_widgets)

        self.static_checkbox = qgis.PyQt.QtWidgets.QCheckBox()
        self.static_checkbox.setToolTip(
            QCoreApplication.translate(
                "ColumnEntry",
                "The supplied string will be written to the current column name for all\nimported rows instead of being read from file column.",
            )
        )
        self.column_widgets.append(self.static_checkbox)
        self._all_widgets.append(self.static_checkbox)

        self._factor = qgis.PyQt.QtWidgets.QLineEdit()
        self._factor.setText("1")
        self._factor.setToolTip(
            QCoreApplication.translate(
                "ColumnEntry",
                "Multiply each imported value in the column with a factor.",
            )
        )
        self._factor.setFixedWidth(40)
        self.column_widgets.append(self._factor)
        self._all_widgets.append(self._factor)

        if self.column_type not in numeric_datatypes:
            self._factor.setVisible(False)

        self._ignore_not_null_checkbox = qgis.PyQt.QtWidgets.QCheckBox()
        self._ignore_not_null_checkbox.setToolTip(
            QCoreApplication.translate(
                "ColumnEntry",
                "Ignores not null warning and try to import anyway. Check when importing to Postgres SERIAL PRIMARY KEY columns.",
            )
        )
        self._ignore_not_null_checkbox.setChecked(False)
        self.column_widgets.append(self._ignore_not_null_checkbox)
        self._all_widgets.append(self._ignore_not_null_checkbox)

        self.static_checkbox.clicked.connect(lambda x: self.static_checkbox_checked())

        # This line prefills the columns if the header names matches the database column names
        self.file_column_name = self.db_column

    @property
    def file_column_name(self):
        if self.obsids_from_selection is not None:
            if self.obsids_from_selection.isChecked():
                return Obsids_from_selection()

        selected = ru(self.combobox.currentText())
        if self.static_checkbox.isChecked():
            selected = StaticValue(ru(self.combobox.currentText()))

        if (
            self.notnull
            and not selected
            and not self._ignore_not_null_checkbox.isChecked()
        ):
            raise exceptions.UsageError(
                QCoreApplication.translate(
                    "ColumnEntry", "Import error, the column %s must have a value"
                )
                % self.db_column
            )

        if (
            selected
            and not self.static_checkbox.isChecked()
            and selected not in self.file_header
        ):
            raise exceptions.UsageError(
                QCoreApplication.translate(
                    "ColumnEntry",
                    "Import error, the chosen file column for the column %s did not exist in the file header.",
                )
                % self.db_column
            )
        else:
            return selected

    @file_column_name.setter
    def file_column_name(self, value):
        if value is None:
            self.combobox.setCurrentIndex(0)
        elif self.static_checkbox.isChecked():
            self.combobox.setEditText(value)
        else:
            index = self.combobox.findText(ru(value))
            if index != -1:
                self.combobox.setCurrentIndex(index)

    def obsids_from_selection_checked(self):
        if self.obsids_from_selection.isChecked():
            self.combobox.setEnabled(False)
            self.static_checkbox.setChecked(False)
        else:
            self.combobox.setEnabled(True)

    def static_checkbox_checked(self):
        if self.static_checkbox.isChecked():
            self.combobox.setEnabled(True)
            if isinstance(self.obsids_from_selection, qgis.PyQt.QtWidgets.QCheckBox):
                self.obsids_from_selection.setChecked(False)

    @property
    def factor(self):
        value = self._factor.text()
        as_float = common_utils.to_float_or_none(value)
        if isinstance(as_float, float):
            return as_float
        else:
            return None

    @factor.setter
    def factor(self, value):
        as_float = common_utils.to_float_or_none(value)
        if isinstance(as_float, float):
            self._factor.setText(str(as_float))


class Obsids_from_selection:
    def __init__(self):
        pass


class StaticValue:
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return str(self.value)

    def __repr__(self):
        return str(self.value)
