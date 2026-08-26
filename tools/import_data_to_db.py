"""
/***************************************************************************
 This part of the Midvatten plugin handles importing of data to the database.

 This part is to a big extent based on QSpatialite plugin.
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

import io
import re
import traceback
from functools import wraps
from operator import itemgetter
from typing import Any, Callable, Optional, TypeAlias

import pandas as pd
from pandas.api.types import is_datetime64_any_dtype

try:
    import psycopg2
    import psycopg2.extras
except ImportError:  # optional — only needed for PostGIS
    psycopg2 = None
from qgis.PyQt.QtCore import QCoreApplication

from midvatten.tools.utils import common_utils, db_utils, dialog_utils, message_utils
from midvatten.tools.utils import parameter_cleaning
from midvatten.tools.utils.exceptions import UserInterruptError
from midvatten.tools.utils.db_utils import DbConnectionManager
from midvatten.tools.utils.db_utils.dialect import safe_type
from midvatten.tools.utils.date_utils import instant_key


ImportData: TypeAlias = list[list[object]] | pd.DataFrame


def _cast_or_passthrough(value_ident: str, declared_type: str) -> str:
    """Return ``CAST(value_ident AS declared_type)``, or ``value_ident``
    unchanged when ``declared_type`` is falsy.

    SQLite allows a column to have no declared type at all (affinity NONE);
    ``PRAGMA table_info`` then reports its type as ``""``. ``CAST(x AS )`` is
    invalid SQL, and silently corrupts such columns rather than failing, so a
    falsy ``declared_type`` skips the CAST and passes the value through as-is
    — this matches SQLite's own no-declared-type semantics. A truthy type is
    validated via :func:`safe_type` before interpolation, since it may come
    from an untrusted ``.sqlite`` file.
    """
    if not declared_type:
        return value_ident
    return f"CAST({value_ident} AS {safe_type(declared_type)})"


def _as_import_frame(file_data: ImportData) -> pd.DataFrame:
    """Normalize legacy rows or a typed frame at the one import boundary."""
    if isinstance(file_data, pd.DataFrame):
        frame = file_data.copy(deep=True)
    elif isinstance(file_data, list):
        if not file_data:
            return pd.DataFrame()
        header = file_data[0]
        if not isinstance(header, (list, tuple)):
            raise MidvDataImporterError(
                QCoreApplication.translate(
                    "midv_data_importer",
                    "The first import row must contain column names.",
                )
            )
        frame = pd.DataFrame.from_records(file_data[1:], columns=header)
    else:
        raise MidvDataImporterError(
            QCoreApplication.translate(
                "midv_data_importer",
                "Import data must be a list of rows or a pandas DataFrame.",
            )
        )
    if not frame.columns.is_unique:
        raise MidvDataImporterError(
            QCoreApplication.translate(
                "midv_data_importer", "Import column names must be unique."
            )
        )
    return frame.reset_index(drop=True)


def _clean_w_qual_lab_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Mechanically clean parameter/unit on their way into w_qual_lab
    (midv_addons spec 2026-08-26 §6). general_import is the choke point
    every import path funnels through, so this one hook covers the
    general CSV import, interlab4, and interlab4_batch alike."""
    frame = frame.copy()
    for column, cleaner in (
            ("parameter", parameter_cleaning.clean_parameter),
            ("unit", parameter_cleaning.clean_unit)):
        if column in frame.columns:
            frame[column] = frame[column].map(
                lambda value, _clean=cleaner:
                _clean(value) if isinstance(value, str) else value)
    return frame


class MidvDataImporter:  # this class is intended to be a multipurpose import class  BUT loggerdata probably needs specific importer or its own subfunction
    def __init__(self) -> None:
        self.columns = 0
        self.recsbefore = 0
        self.recsafter = 0
        self.recstoimport = 0
        self.recsinfile = 0
        self.temptable_name = None
        self.csvlayer = None
        self.confirmation_handled = None
        self._manage_wait_cursor = True

    def general_import(
        self,
        dest_table: str,
        file_data: ImportData,
        allow_obs_fk_import: bool = False,
        _dbconnection: Optional[DbConnectionManager] = None,
        dump_temptable: bool = False,
        source_srid: Optional[int] = None,
        skip_confirmation: bool = False,
        binary_geometry: bool = False,
        defer_commit: bool = False,
        progress_callback: Optional[Callable[[str], None]] = None,
        manage_wait_cursor: bool = True,
        raise_insert_errors: bool = False,
    ) -> int:
        """General method for importing legacy rows or a pandas DataFrame.

            self.temptableName must be the name of the table containing the new data to import.

        :param dest_table: The destination table
        :param file_data: a list of list with a header list as first row
        :param allow_obs_fk_import: True to allow creation of obsids in obs_points and obs_lines.
        :param _dbconnection: A db_utils.DbConnectionManager-instance if other than the currently selected in the midvatten
                              settings dialog.
        :param dump_temptable: True to create a csvfile from internal temporary table.
        :param source_srid: The srid of the source geometry column if the geometry is a WKT or WKB
        :param skip_confirmation: True to suppress the row-drop confirmation dialog (e.g. headless/batch imports).
        :param binary_geometry: True if the source geometry column should be parsed as a WKB, else it's parsed as WKT.
        :param raise_insert_errors: Re-raise final INSERT errors after logging them.
        :return:
        """

        self.temptable_name = None
        self._manage_wait_cursor = manage_wait_cursor
        import_messages = []
        nr_imported = 0

        if skip_confirmation:
            self.confirmation_handled = 1

        dbconnection: Optional[DbConnectionManager] = None
        try:
            import_frame = _as_import_frame(file_data)
            if import_frame.empty:
                return 0
            if dest_table == "w_qual_lab":
                import_frame = _clean_w_qual_lab_frame(import_frame)
            message_utils.MessagebarAndLog.info(
                log_msg=QCoreApplication.translate(
                    "midv_data_importer",
                    "\nImport to %s starting\n--------------------",
                )
                % dest_table
            )

            if self._manage_wait_cursor:
                common_utils.start_waiting_cursor()

            if progress_callback:
                progress_callback(
                    QCoreApplication.translate(
                        "midv_data_importer", "Validating columns..."
                    )
                )

            (
                dbconnection,
                table_info,
                column_headers_types,
                primary_keys,
                not_null_columns,
                existing_columns_in_dest_table,
                existing_columns_in_temptable,
                primary_keys_for_concat,
            ) = self._validate_and_connect(dest_table, import_frame, _dbconnection)

            if "date_time" in primary_keys:
                if progress_callback:
                    progress_callback(
                        QCoreApplication.translate(
                            "midv_data_importer",
                            "Optimizing duplicate timestamp lookup...",
                        )
                    )
                self.ensure_normalized_datetime_index(
                    dbconnection, dest_table, primary_keys
                )

            recsinfile = len(import_frame)
            all_rownumbers = tuple(range(recsinfile))
            remaining_rownumbers = tuple(all_rownumbers)

            if progress_callback:
                progress_callback(
                    QCoreApplication.translate(
                        "midv_data_importer", "Creating temporary table..."
                    )
                )

            in_file_dups, in_file_dup_rownumbers = self.dataframe_to_table(
                dbconnection, dest_table, import_frame, primary_keys_for_concat
            )

            sql_remaining = dbconnection.sql_ident(
                "SELECT {rowid} FROM {t}",
                rowid=self.temptable_rowid_name,
                t=self.temptable_name,
            )

            def get_remaining_rownumbers() -> list[int]:
                return [x[0] for x in dbconnection.execute_and_fetchall(sql_remaining)]

            def get_removed_rownumbers(
                start_numbers: tuple[int, ...] | list[int],
                remaining: tuple[int, ...] | list[int],
            ) -> list[int]:
                remaining_set = set(remaining)
                return [x for x in start_numbers if x not in remaining_set]

            def get_row_subset(
                rownumbers: tuple[int, ...] | list[int],
            ) -> list[str]:
                return [
                    ", ".join(str(value) for value in import_frame.iloc[rownr].tolist())
                    for rownr in rownumbers[:10]
                ]

            if progress_callback:
                progress_callback(
                    QCoreApplication.translate(
                        "midv_data_importer", "Checking for duplicate timestamps..."
                    )
                )

            # Delete records from self.temptable where yyyy-mm-dd hh:mm or yyyy-mm-dd hh:mm:ss already exist for the same date.
            (
                remaining_rownumbers,
                import_messages,
                already_in_db,
            ) = self._remove_duplicate_datetimes(
                dbconnection,
                dest_table,
                primary_keys,
                all_rownumbers,
                remaining_rownumbers,
                get_remaining_rownumbers,
                get_removed_rownumbers,
                get_row_subset,
                in_file_dup_rownumbers,
                import_messages,
            )
            if remaining_rownumbers is None:
                return 0

            # Special cases for some tables
            remaining_rownumbers, import_messages = self._handle_special_table_cases(
                dbconnection,
                dest_table,
                existing_columns_in_dest_table,
                remaining_rownumbers,
                get_remaining_rownumbers,
                get_removed_rownumbers,
                get_row_subset,
                import_messages,
            )
            if remaining_rownumbers is None:
                return 0

            # Dump temptable to csv for debugging
            if dump_temptable:
                dbconnection.dump_table_2_csv(self.temptable_name)

            self._ask_user_to_proceed(
                remaining_rownumbers, all_rownumbers, import_messages
            )

            self._handle_foreign_keys(
                dbconnection,
                dest_table,
                existing_columns_in_temptable,
                allow_obs_fk_import,
            )

            if progress_callback:
                progress_callback(
                    QCoreApplication.translate(
                        "midv_data_importer", "Importing rows..."
                    )
                )

            nr_imported = self._build_and_execute_insert(
                dbconnection,
                dest_table,
                existing_columns_in_dest_table,
                existing_columns_in_temptable,
                column_headers_types,
                not_null_columns,
                source_srid,
                binary_geometry,
                raise_insert_errors,
            )

            nr_excluded = recsinfile - nr_imported
            message_utils.MessagebarAndLog.info(
                bar_msg=self._import_summary_bar_msg(
                    nr_imported, nr_excluded, dest_table, already_in_db, in_file_dups
                ),
                log_msg="--------------------",
            )

        except Exception:
            self._cleanup(dbconnection, _dbconnection, commit=False)
            raise
        else:
            self._cleanup(dbconnection, _dbconnection, commit=not defer_commit)
        return nr_imported

    def _import_summary_bar_msg(
        self,
        nr_imported: int,
        nr_excluded: int,
        dest_table: str,
        already_in_db: int,
        in_file_dups: int,
    ) -> str:
        """Build the final summary, naming each cause of exclusion.

        When rows were removed by either dedup process, the excluded count is
        broken down by cause; any remaining exclusions (e.g. missing required
        values) are reported as "other reasons". Falls back to the plain message
        when neither dedup process removed anything.
        """
        clauses = []
        if already_in_db:
            clauses.append(
                QCoreApplication.translate(
                    "midv_data_importer", "%s already existed in the database"
                )
                % str(already_in_db)
            )
        if in_file_dups:
            clauses.append(
                QCoreApplication.translate(
                    "midv_data_importer", "%s duplicated within the file"
                )
                % str(in_file_dups)
            )
        remainder = nr_excluded - already_in_db - in_file_dups
        if clauses and remainder > 0:
            clauses.append(
                QCoreApplication.translate("midv_data_importer", "%s for other reasons")
                % str(remainder)
            )
        if clauses:
            return QCoreApplication.translate(
                "midv_data_importer",
                "%s rows imported, %s excluded for table %s (%s). See log message panel for details.",
            ) % (str(nr_imported), str(nr_excluded), dest_table, ", ".join(clauses))
        return QCoreApplication.translate(
            "midv_data_importer",
            "%s rows imported and %s excluded for table %s. See log message panel for details",
        ) % (str(nr_imported), str(nr_excluded), dest_table)

    def _validate_and_connect(
        self,
        dest_table: str,
        import_frame: pd.DataFrame,
        _dbconnection: Optional[DbConnectionManager],
    ) -> tuple:
        """Set up DB connection, activate foreign keys, introspect schema, validate columns.

        Returns (dbconnection, table_info, column_headers_types, primary_keys,
                 not_null_columns, existing_columns_in_dest_table,
                 existing_columns_in_temptable, primary_keys_for_concat).
        """
        if not isinstance(_dbconnection, db_utils.DbConnectionManager):
            dbconnection = db_utils.DbConnectionManager()
        else:
            dbconnection = _dbconnection

        db_utils.activate_foreign_keys(activated=True, dbconnection=dbconnection)

        table_info = db_utils.db_tables_columns_info(
            table=dest_table, dbconnection=dbconnection
        )
        if not table_info:
            raise MidvDataImporterError(
                QCoreApplication.translate(
                    "midv_data_importer",
                    "The table %s did not exist. Update the database to latest version.",
                )
                % dest_table
            )
        else:
            table_info = table_info[dest_table]

        # POINT and LINESTRING must be cast as BLOB. So change the type to BLOB.
        column_headers_types = db_utils.change_cast_type_for_geometry_columns(
            dbconnection, table_info, dest_table
        )
        primary_keys = [
            row[1] for row in table_info if int(row[5])
        ]  # Not null columns are allowed if they have a default value.
        not_null_columns = [
            row[1] for row in table_info if int(row[3]) and row[4] is None
        ]
        # Only use the columns that exist in the goal table.
        existing_columns_in_dest_table = [
            col for col in import_frame.columns if col in column_headers_types
        ]
        existing_columns_in_temptable = import_frame.columns.tolist()
        missing_columns = [
            column
            for column in not_null_columns
            if column not in existing_columns_in_dest_table
        ]

        if missing_columns:
            raise MidvDataImporterError(
                QCoreApplication.translate(
                    "midv_data_importer",
                    "Required columns %s are missing for table %s",
                )
                % (", ".join(missing_columns), dest_table)
            )

        primary_keys_for_concat = [
            pk for pk in primary_keys if pk in existing_columns_in_temptable
        ]

        return (
            dbconnection,
            table_info,
            column_headers_types,
            primary_keys,
            not_null_columns,
            existing_columns_in_dest_table,
            existing_columns_in_temptable,
            primary_keys_for_concat,
        )

    def _remove_duplicate_datetimes(
        self,
        dbconnection: DbConnectionManager,
        dest_table: str,
        primary_keys: list[str],
        all_rownumbers: tuple,
        remaining_rownumbers: tuple,
        get_remaining_rownumbers: Callable,
        get_removed_rownumbers: Callable,
        get_row_subset: Callable,
        in_file_dup_rownumbers: list[int],
        import_messages: list[str],
    ) -> tuple:
        """Delete temp rows whose date_time already exists in the destination table.

        Returns (remaining_rownumbers, import_messages, already_in_db_count), where
        remaining_rownumbers is None if all rows were removed (caller should abort).
        already_in_db_count counts only rows removed here (already in the database),
        never the in-file duplicates dropped earlier.
        """
        if "date_time" not in primary_keys:
            return remaining_rownumbers, import_messages, 0

        rows_deleted = self.delete_existing_date_times_from_temptable(
            primary_keys, dest_table, dbconnection
        )
        if rows_deleted == 0:
            # Common case: no pre-existing data — skip the DB round-trip.
            return remaining_rownumbers, import_messages, 0

        remaining_rownumbers = get_remaining_rownumbers()
        if not remaining_rownumbers:
            message_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "midv_data_importer",
                    "Nothing imported to %s: every row already exists in the database.",
                )
                % dest_table
            )
            return None, import_messages, rows_deleted

        # rows_deleted is the authoritative count of rows already in the DB. For the
        # log we also show a sample of WHICH rows: "all removed" MINUS the in-file
        # duplicates dropped before the temp table was populated (those never reached
        # the DB check, so showing them here would mis-attribute them).
        in_file_dup_set = set(in_file_dup_rownumbers)
        removed_rows_sample = [
            rownr
            for rownr in get_removed_rownumbers(all_rownumbers, remaining_rownumbers)
            if rownr not in in_file_dup_set
        ]
        if removed_rows_sample:
            message_utils.MessagebarAndLog.info(
                log_msg=QCoreApplication.translate(
                    "midv_data_importer",
                    "%s rows were skipped because a row with the same primary key "
                    "already exists in the database table %s (date_time matched to "
                    "the second). Subset of skipped rows:\n%s",
                )
                % (
                    str(rows_deleted),
                    dest_table,
                    "\n".join(get_row_subset(removed_rows_sample)),
                )
            )
            import_messages.append(
                QCoreApplication.translate(
                    "midv_data_importer",
                    "%s rows already exist in the database and were skipped.",
                )
                % str(rows_deleted)
            )

        return remaining_rownumbers, import_messages, rows_deleted

    def _handle_special_table_cases(
        self,
        dbconnection: DbConnectionManager,
        dest_table: str,
        existing_columns_in_dest_table: list[str],
        remaining_rownumbers: tuple,
        get_remaining_rownumbers: Callable,
        get_removed_rownumbers: Callable,
        get_row_subset: Callable,
        import_messages: list[str],
    ) -> tuple:
        """Apply table-specific pre-import transformations.

        Handles stratigraphy validation and w_qual_field unit normalization.
        Returns (remaining_rownumbers, import_messages), where remaining_rownumbers
        is None if all rows were removed (caller should abort).
        """
        if dest_table == "stratigraphy":
            self.check_and_delete_stratigraphy(
                existing_columns_in_dest_table, dbconnection
            )
            remaining_rownumbers_after_stratigraphy = get_remaining_rownumbers()
            if not remaining_rownumbers_after_stratigraphy:
                message_utils.MessagebarAndLog.warning(
                    bar_msg=QCoreApplication.translate(
                        "midv_data_importer",
                        "Nothing imported to %s after deleting stratigraphy rows with errors.",
                    )
                    % dest_table
                )
                return None, import_messages

            removed_rownumbers = get_removed_rownumbers(
                remaining_rownumbers, remaining_rownumbers_after_stratigraphy
            )
            if removed_rownumbers:
                removed_rows = get_row_subset(removed_rownumbers)
                message_utils.MessagebarAndLog.info(
                    log_msg=QCoreApplication.translate(
                        "midv_data_importer",
                        "Skipped %s rows due to problems with stratigraphy. Subset of skipped rows:\n%s",
                    )
                    % (str(len(removed_rownumbers)), "\n".join(removed_rows))
                )
                import_messages.append(
                    QCoreApplication.translate(
                        "midv_data_importer",
                        "Skipped %s rows due to problems with stratigraphy.",
                    )
                    % str(len(removed_rownumbers))
                )
            remaining_rownumbers = remaining_rownumbers_after_stratigraphy

        elif dest_table == "w_qual_field":
            self.convert_null_unit_to_empty_string(
                self.temptable_name, "unit", dbconnection
            )

        return remaining_rownumbers, import_messages

    def _ask_user_to_proceed(
        self,
        remaining_rownumbers: tuple,
        all_rownumbers: tuple,
        import_messages: list[str],
    ) -> None:
        """Confirm only when rows would actually be dropped (real data loss).

        When nothing is dropped, clicking "Start import" is itself the
        go-ahead — no modal. Accumulated per-cause detail is always logged
        quietly so it is never lost. Raises UserInterruptError if the user
        declines. The ``confirmation_handled`` latch preserves the
        "ask at most once per import session" behaviour for multi-table
        imports and ``skip_confirmation``.
        """
        if import_messages:
            message_utils.MessagebarAndLog.info(log_msg="\n".join(import_messages))

        rows_dropped = len(remaining_rownumbers) != len(all_rownumbers)
        if not rows_dropped:
            return

        if self.confirmation_handled:
            message_utils.MessagebarAndLog.info(
                log_msg=QCoreApplication.translate(
                    "midv_data_importer",
                    "Skipping confirmation dialog: %s out of %s rows to import (duplicates removed).",
                )
                % (str(len(remaining_rownumbers)), str(len(all_rownumbers)))
            )
            return

        msg = QCoreApplication.translate(
            "midv_data_importer",
            "There are %s out of %s number of rows to import (see log for more info about removed rows).\n\nProceed with import?",
        ) % (str(len(remaining_rownumbers)), str(len(all_rownumbers)))

        # Set before the dialog so a declined import also counts as "already
        # asked" (the session aborts anyway via UserInterruptError).
        self.confirmation_handled = 1
        stop_question = dialog_utils.Askuser(
            "YesNo",
            msg,
            QCoreApplication.translate("midv_data_importer", "Info"),
        )
        if stop_question.result == 0:
            raise UserInterruptError()

    def _handle_foreign_keys(
        self,
        dbconnection: DbConnectionManager,
        dest_table: str,
        existing_columns_in_temptable: list[str],
        allow_obs_fk_import: bool,
    ) -> None:
        """Detect and import foreign key rows for the destination table."""
        foreign_keys = db_utils.get_foreign_keys(dest_table, dbconnection=dbconnection)
        if foreign_keys:
            if not allow_obs_fk_import:
                for table in ["obs_points", "obs_lines"]:
                    if table in foreign_keys:
                        del foreign_keys[table]
            if foreign_keys:
                self.import_foreign_keys(
                    dbconnection,
                    dest_table,
                    self.temptable_name,
                    foreign_keys,
                    existing_columns_in_temptable,
                )
                message_utils.MessagebarAndLog.info(
                    log_msg=QCoreApplication.translate(
                        "midv_data_importer",
                        "Foreign keys for %s are imported automatically.",
                    )
                    % dest_table
                )

    def _build_and_execute_insert(
        self,
        dbconnection: DbConnectionManager,
        dest_table: str,
        existing_columns_in_dest_table: list[str],
        existing_columns_in_temptable: list[str],
        column_headers_types: dict[str, str],
        not_null_columns: list[str],
        source_srid: Optional[int],
        binary_geometry: bool,
        raise_insert_errors: bool,
    ) -> int:
        """Build and execute the INSERT … SELECT from the temp table to the destination.

        Returns the number of rows actually inserted.
        """
        # Check if current table has geometry:
        geom_columns = db_utils.get_geometry_types(
            dest_table, dbconnection=dbconnection
        )
        sourcecols = []
        for colname in sorted(existing_columns_in_dest_table):
            null_replacement = db_utils.cast_null(
                column_headers_types[colname], dbconnection
            )
            if colname in geom_columns and colname in existing_columns_in_temptable:
                sourcecols.append(
                    self.create_geometry_sql(
                        colname,
                        dest_table,
                        dbconnection,
                        source_srid,
                        null_replacement,
                        binary_geometry,
                    )
                )
            else:
                colname_ident = dbconnection.ident(colname)
                sourcecols.append(
                    f"""(CASE WHEN {colname_ident} IS NOT NULL\n    THEN {_cast_or_passthrough(colname_ident, column_headers_types[colname])} ELSE {null_replacement} END)"""
                )

        if dbconnection.is_postgresql():
            dest_table_with_schema = dbconnection.ident(
                f"{dbconnection.schema}.{dest_table}"
            )
        else:
            dest_table_with_schema = dbconnection.ident(dest_table)

        sql = """INSERT INTO {dest_table} ({dest_columns})\nSELECT {source_columns}\nFROM {source_table}\n"""
        kwargs = {
            "dest_table": dest_table_with_schema,
            "dest_columns": ", ".join(
                dbconnection.ident(c) for c in sorted(existing_columns_in_dest_table)
            ),
            "source_table": dbconnection.ident(self.temptable_name),
            "source_columns": ",\n    ".join(sourcecols),
        }
        if not_null_columns:
            sql += """WHERE {notnullcheck}"""
            kwargs["notnullcheck"] = " AND ".join(
                [
                    f"{dbconnection.ident(notnullcol)} IS NOT NULL"
                    for notnullcol in sorted(not_null_columns)
                ]
            )
        sql = sql.format(**kwargs)

        sql = db_utils.add_insert_or_ignore_to_sql(sql, dbconnection)
        try:
            dbconnection.execute(sql)
        except Exception as e:
            try:
                str(e)
            except UnicodeDecodeError:
                message_utils.MessagebarAndLog.critical(
                    bar_msg=QCoreApplication.translate(
                        "midv_data_importer",
                        "Import failed, see log message panel",
                    ),
                    log_msg=QCoreApplication.translate(
                        "midv_data_importer", "Sql\n%s  failed."
                    )
                    % (sql),
                    duration=999,
                )
            else:
                message_utils.MessagebarAndLog.critical(
                    bar_msg=QCoreApplication.translate(
                        "midv_data_importer",
                        "Import failed, see log message panel",
                    ),
                    log_msg=QCoreApplication.translate(
                        "midv_data_importer", "Sql\n%s  failed.\nMsg:\n%s"
                    )
                    % (sql, str(e)),
                    duration=999,
                )
            if raise_insert_errors:
                raise
            return 0
        return dbconnection.cursor.rowcount

    def _cleanup(
        self,
        dbconnection: Optional[DbConnectionManager],
        _dbconnection: Optional[DbConnectionManager],
        commit: bool,
    ) -> None:
        """Commit or roll back and release resources after import succeeds or fails."""
        if dbconnection is None:
            if self._manage_wait_cursor:
                common_utils.stop_waiting_cursor()
            return
        if commit:
            dbconnection.commit()
        # If an external dbconnection is supplied, do not close it.
        if _dbconnection is None:
            try:
                dbconnection.closedb()
            except Exception:
                message_utils.MessagebarAndLog.info(log_msg=traceback.format_exc())
        else:
            if self.temptable_name is not None:
                dbconnection.drop_temporary_table(self.temptable_name)
        if self._manage_wait_cursor:
            common_utils.stop_waiting_cursor()

    def list_to_table(
        self,
        dbconnection: DbConnectionManager,
        destination_table: str,
        file_data: ImportData,
        primary_keys_for_concat: list[str],
    ) -> tuple[int, list[int]]:
        """Legacy staging wrapper retained for non-logger callers and tests."""
        return self.dataframe_to_table(
            dbconnection,
            destination_table,
            _as_import_frame(file_data),
            primary_keys_for_concat,
        )

    def dataframe_to_table(
        self,
        dbconnection: DbConnectionManager,
        destination_table: str,
        import_frame: pd.DataFrame,
        primary_keys_for_concat: list[str],
    ) -> tuple[int, list[int]]:
        """Create and bulk-load the import staging table from a normalized frame."""
        # Field names originate in imported data and therefore require quoting.
        # quote_ident preserves valid non-ASCII names while preventing injection.
        fieldnames_types = [
            f"{db_utils.quote_ident(field_name)} TEXT"
            for field_name in import_frame.columns
        ]
        tname = f"temp_{destination_table}_temp"
        self.temptable_rowid_name = f"{tname}_rowid"
        fieldnames_types.append(f"{self.temptable_rowid_name} INTEGER")
        self.temptable_name = dbconnection.create_temporary_table_for_import(
            tname, fieldnames_types
        )

        numskipped, in_file_dup_rownumbers = self.dataframe_to_table_using_pandas(
            dbconnection,
            self.temptable_name,
            self.temptable_rowid_name,
            import_frame,
            primary_keys_for_concat,
        )

        if numskipped:
            message_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "midv_data_importer",
                    "%s rows skipped (duplicated within the file)",
                )
                % str(numskipped),
                log_msg=QCoreApplication.translate(
                    "midv_data_importer",
                    "%s rows were skipped because they are duplicated within the "
                    "imported file itself (same primary key, e.g. obsid + date_time). "
                    "The database was not involved for these.",
                )
                % str(numskipped),
            )
        return numskipped, in_file_dup_rownumbers

    def dataframe_to_table_using_pandas(
        self,
        dbconnection: DbConnectionManager,
        temptable_name: str,
        temptable_rowidcol: str,
        import_frame: pd.DataFrame,
        primary_keys_for_concat: list[str],
    ) -> tuple[int, list[int]]:
        """Deduplicate and bulk-load a normalized import frame."""
        numskipped = 0
        in_file_dup_rownumbers: list[int] = []
        df = import_frame.copy(deep=True).reset_index(drop=True)
        df[temptable_rowidcol] = range(len(df))

        if primary_keys_for_concat:
            key_df = df[list(primary_keys_for_concat)].copy()
            if "date_time" in key_df.columns:
                date_values = key_df["date_time"]
                if is_datetime64_any_dtype(date_values.dtype):
                    key_df["date_time"] = date_values.dt.floor("s")
                else:
                    key_df["date_time"] = date_values.map(
                        lambda value: instant_key(value) or value
                    )
            duplicate_mask = key_df.duplicated(keep="first")
            in_file_dup_rownumbers = df.loc[duplicate_mask, temptable_rowidcol].tolist()
            numskipped = len(in_file_dup_rownumbers)
            df = df.loc[~duplicate_mask].reset_index(drop=True)

        for column in df.columns:
            if is_datetime64_any_dtype(df[column].dtype):
                df[column] = df[column].dt.strftime("%Y-%m-%d %H:%M:%S")
                continue
            if df[column].dtype == object or isinstance(
                df[column].dtype, pd.StringDtype
            ):
                df[column] = df[column].map(
                    lambda value: value.strip() if isinstance(value, str) else value
                )

        # Database drivers receive Python None for every pandas null. Numeric
        # values remain numeric; only datetime columns are formatted to text.
        df = df.astype(object).where(pd.notnull(df), None).replace("", None)

        if dbconnection.is_sqlite():
            sql = (
                f"INSERT INTO {dbconnection.ident(temptable_name)} VALUES "
                f"({dbconnection.placeholders(len(df.columns))})"
            )
            dbconnection.cursor.executemany(sql, df.itertuples(index=False, name=None))
        else:
            csv_buffer = io.StringIO()
            df.to_csv(csv_buffer, index=False, header=False, sep=";")
            csv_buffer.seek(0)
            try:
                dbconnection.cursor.copy_from(
                    csv_buffer, temptable_name, sep=";", null=""
                )
            except psycopg2.errors.BadCopyFileFormat:
                data = list(df.itertuples(index=False, name=None))
                ph = dbconnection.placeholders(len(df.columns))
                sql = dbconnection.sql_ident(
                    "INSERT INTO {t} VALUES %s",
                    t=temptable_name,
                )
                psycopg2.extras.execute_values(
                    dbconnection.cursor, sql, data, template=f"({ph})"
                )

        return numskipped, in_file_dup_rownumbers

    def delete_existing_date_times_from_temptable(
        self,
        primary_keys: list[str],
        dest_table: str,
        dbconnection: DbConnectionManager,
    ) -> int:
        """Delete temp rows already present in dest at the same normalized instant.

        date_time is compared via the backend's normalized-instant expression
        (the same one the unique index uses), so duplicates are detected at
        second precision and the expression index assists the lookup. Other
        primary-key columns are compared by exact identity.
        """
        temp_ident = dbconnection.ident(self.temptable_name)
        dest_ident = (
            dbconnection.ident(f"{dbconnection.schema}.{dest_table}")
            if dbconnection.is_postgresql()
            else dbconnection.ident(dest_table)
        )
        conditions = []
        for pk in primary_keys:
            q = dbconnection.ident(pk)
            if pk == "date_time":
                conditions.append(
                    f"{dbconnection.normalized_instant_sql(f'd.{q}')} "
                    f"= {dbconnection.normalized_instant_sql(f'{temp_ident}.{q}')}"
                )
            else:
                conditions.append(f"d.{q} = {temp_ident}.{q}")
        sql = (
            f"DELETE FROM {temp_ident} WHERE EXISTS ("
            f"SELECT 1 FROM {dest_ident} d WHERE {' AND '.join(conditions)})"
        )
        dbconnection.execute(sql)
        return dbconnection.cursor.rowcount

    @staticmethod
    def _normalise_index_definition(definition: str) -> str:
        """Return a comparison-friendly index definition."""
        return re.sub(r'[\s"]+', "", definition).lower()

    def has_normalized_datetime_index(
        self,
        dbconnection: DbConnectionManager,
        dest_table: str,
        primary_keys: list[str],
    ) -> bool:
        """Whether an index can satisfy the normalized duplicate lookup.

        Definitions are inspected instead of trusting an index name. Some
        legacy PostgreSQL databases contain the current canonical name on a
        raw ``date_time`` index, which does not help the normalized query.
        """
        if "date_time" not in primary_keys:
            return True

        if dbconnection.is_sqlite():
            rows = dbconnection.execute_and_fetchall(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'index' AND tbl_name = ? AND sql IS NOT NULL",
                (dest_table,),
            )
            marker = "datetime(date_time)"
        else:
            ph = dbconnection.placeholder()
            rows = dbconnection.execute_and_fetchall(
                "SELECT indexdef FROM pg_indexes "
                f"WHERE schemaname = {ph} AND tablename = {ph}",
                (dbconnection.schema, dest_table),
            )
            marker = "midv_to_instant(date_time)"

        required_columns = [
            re.compile(rf"[(,]{re.escape(pk.lower())}[,)]")
            for pk in primary_keys
            if pk != "date_time"
        ]
        for row in rows:
            definition = self._normalise_index_definition(str(row[0] or ""))
            if marker not in definition:
                continue
            if all(pattern.search(definition) for pattern in required_columns):
                return True
        return False

    def ensure_normalized_datetime_index(
        self,
        dbconnection: DbConnectionManager,
        dest_table: str,
        primary_keys: list[str],
    ) -> bool:
        """Create the lookup index required by normalized duplicate removal.

        The supporting index is deliberately non-unique. Legacy databases may
        already contain differently-formatted timestamps representing the same
        instant; importing data must not silently delete those rows or fail an
        otherwise safe performance migration. New databases retain their
        schema-defined UNIQUE index, which is detected and reused.

        Returns True when an index was created and False when a suitable index
        already existed.
        """
        if "date_time" not in primary_keys or self.has_normalized_datetime_index(
            dbconnection, dest_table, primary_keys
        ):
            return False

        index_name = f"idx_midv_import_{dest_table}_instant"
        table_ident = (
            dbconnection.ident(f"{dbconnection.schema}.{dest_table}")
            if dbconnection.is_postgresql()
            else dbconnection.ident(dest_table)
        )
        expressions = []
        for pk in primary_keys:
            q = dbconnection.ident(pk)
            expressions.append(
                dbconnection.normalized_instant_sql(q) if pk == "date_time" else q
            )
        sql = (
            f"CREATE INDEX IF NOT EXISTS {dbconnection.ident(index_name)} "
            f"ON {table_ident} ({', '.join(expressions)})"
        )
        try:
            dbconnection.execute(sql)
            if not self.has_normalized_datetime_index(
                dbconnection, dest_table, primary_keys
            ):
                raise RuntimeError(
                    f"index name {index_name!r} already has another definition"
                )
        except Exception as e:
            raise MidvDataImporterError(
                QCoreApplication.translate(
                    "midv_data_importer",
                    "The normalized timestamp index required for importing to %s "
                    "could not be created. The import was stopped to avoid a very "
                    "slow duplicate scan. Error: %s",
                )
                % (dest_table, str(e))
            ) from e

        return True

    def create_geometry_sql(
        self,
        geom_col: str,
        table_name: str,
        dbconnection: DbConnectionManager,
        source_srid: int,
        null_replacement: str,
        binary_geometry: bool = False,
    ) -> str:
        # Calculate the geometry
        # THIS IS DUE TO WKT-import of geometries below
        dest_srid = dbconnection.get_srid(table_name, geometry_column=geom_col)

        convert_func = (
            """ST_GeomFromWKB""" if binary_geometry else """ST_GeomFromText"""
        )

        sql = """(CASE WHEN ({colname} !='' AND {colname} !=' ' AND {colname} IS NOT NULL)\n    THEN {to_geometry} ELSE {null} END)"""
        kwargs = {"colname": dbconnection.ident(geom_col), "null": null_replacement}

        if source_srid is None:
            # Assume it's the same as the destination.
            _source_srid = dest_srid
        else:
            if str(source_srid).startswith("EPSG:"):
                _source_srid = source_srid.split(":")[-1]
            else:
                _source_srid = source_srid

            try:
                int(_source_srid)
            except (ValueError, TypeError) as e:
                raise MidvDataImporterError(
                    QCoreApplication.translate(
                        "midv_data_importer",
                        'Source srid "%s" was not a valid EPSG srid. Check coordinate reference system of the source.',
                    )
                    % str(_source_srid)
                ) from e

        try:
            int(dest_srid)
        except (ValueError, TypeError) as e:
            raise MidvDataImporterError(
                QCoreApplication.translate(
                    "midv_data_importer",
                    'Database srid "%s" was not a valid EPSG srid. Check coordinate reference system of the databases',
                )
                % str(dest_srid)
            ) from e

        geom_col_ident = dbconnection.ident(geom_col)
        if int(_source_srid) == int(dest_srid):
            to_geometry = f"""{convert_func}({geom_col_ident}, {dest_srid})"""
        else:
            to_geometry = f"""ST_Transform({convert_func}({geom_col_ident}, {_source_srid}), {dest_srid})"""
        kwargs["to_geometry"] = to_geometry
        return sql.format(**kwargs)

    def check_and_delete_stratigraphy(
        self, existing_columns: list[str], dbconnection: DbConnectionManager
    ) -> None:
        if all(
            [
                "stratid" in existing_columns,
                "depthtop" in existing_columns,
                "depthbot" in existing_columns,
            ]
        ):
            skip_obsids = []
            strat_sql = dbconnection.sql_ident(
                "SELECT obsid, stratid, depthtop, depthbot FROM {t}",
                t=self.temptable_name,
            )
            obsid_strat = db_utils.get_sql_result_as_dict(
                strat_sql,
                dbconnection=dbconnection,
            )[1]
            for obsid, stratid_depthbot_depthtop in obsid_strat.items():
                # Turn everything to float
                try:
                    strats = [[float(x) for x in y] for y in stratid_depthbot_depthtop]
                except (ValueError, TypeError) as e:
                    raise MidvDataImporterError(
                        QCoreApplication.translate(
                            "midv_data_importer",
                            'ValueError: %s. Obsid "%s", stratid: "%s", depthtop: "%s", depthbot: "%s"',
                        )
                        % (
                            str(e),
                            obsid,
                            stratid_depthbot_depthtop[0][0],
                            stratid_depthbot_depthtop[0][1],
                            stratid_depthbot_depthtop[0][2],
                        )
                    )
                sorted_strats = sorted(strats, key=itemgetter(0))
                stratid_idx = 0
                depthtop_idx = 1
                depthbot_idx = 2
                for index in range(len(sorted_strats)):
                    if index == 0:
                        continue
                    # Check that there is no gap in the stratid:
                    if (
                        float(sorted_strats[index][stratid_idx])
                        - float(sorted_strats[index - 1][stratid_idx])
                        != 1
                    ):
                        message_utils.MessagebarAndLog.info(
                            QCoreApplication.translate(
                                "midv_data_importer",
                                "The obsid %s will not be imported due to gaps in stratid",
                            )
                            % obsid
                        )
                        skip_obsids.append(obsid)
                        break
                    # Check that the current depthtop is equal to the previous depthbot
                    elif (
                        sorted_strats[index][depthtop_idx]
                        != sorted_strats[index - 1][depthbot_idx]
                    ):
                        message_utils.MessagebarAndLog.info(
                            QCoreApplication.translate(
                                "midv_data_importer",
                                "The obsid %s will not be imported due to gaps in depthtop/depthbot",
                            )
                            % obsid
                        )
                        skip_obsids.append(obsid)
                        break
            if skip_obsids:
                temp_ident = dbconnection.ident(self.temptable_name)
                placeholders = dbconnection.placeholders(len(skip_obsids))
                sql = f"DELETE FROM {temp_ident} WHERE obsid IN ({placeholders})"
                message_utils.MessagebarAndLog.info(log_msg=f" {sql=} {skip_obsids=}")
                dbconnection.execute(sql, all_args=[tuple(skip_obsids)])

    def convert_null_unit_to_empty_string(
        self, temptable_name: str, column: str, dbconnection: DbConnectionManager
    ) -> None:
        sql = dbconnection.sql_ident(
            "UPDATE {t} SET {c} = TRIM(COALESCE({c}, ''))",
            t=temptable_name,
            c=column,
        )
        dbconnection.execute(sql)

    def import_foreign_keys(
        self,
        dbconnection: DbConnectionManager,
        dest_table: str,
        temptablename: str,
        foreign_keys: dict[str, list[tuple[str, str]]],
        existing_columns_in_temptable: list[str],
    ) -> None:
        for fk_table, from_to_fields in foreign_keys.items():
            from_list = [x[0] for x in from_to_fields]
            to_list = [x[1] for x in from_to_fields]
            if not all([_from in existing_columns_in_temptable for _from in from_list]):
                message_utils.MessagebarAndLog.warning(
                    bar_msg=QCoreApplication.translate(
                        "midv_data_importer",
                        "Import of foreign keys failed, see log message panel",
                    ),
                    log_msg=QCoreApplication.translate(
                        "midv_data_importer",
                        "There were keys missing for importing to fk_table %s, so no import was done.",
                    )
                    % fk_table,
                )
                continue

            fk_table_ident = dbconnection.ident(fk_table)
            nr_fk_before = dbconnection.execute_and_fetchall(
                f"SELECT count(*) FROM {fk_table_ident}"
            )[0][0]
            table_info = db_utils.db_tables_columns_info(
                table=fk_table, dbconnection=dbconnection
            )[fk_table]
            column_headers_types = dict([(row[1], row[2]) for row in table_info])
            # Skip auto-populate for tables that have NOT NULL columns outside
            # the FK target columns. Those rows can't be synthesised from just
            # the FK values (e.g., w_logger_series.obsid is required) — the
            # caller is responsible for creating them up front.
            required_outside_to_list = [
                row[1]
                for row in table_info
                if str(row[3]) == "1" and row[1] not in to_list and not row[4]
            ]
            if required_outside_to_list:
                continue

            null_replacement_string = (
                "NULL_NULL_NULL_NULL_NULL_NULL_NULL_NULL_NULL_NULL"
            )
            temptable_ident = dbconnection.ident(temptablename)
            to_list_idents = ", ".join(dbconnection.ident(k) for k in to_list)
            concatted_from_string = "||".join(
                f"CASE WHEN {dbconnection.ident(x)} IS NULL THEN "
                f"'{null_replacement_string}' ELSE {dbconnection.ident(x)} END"
                for x in from_list
            )
            concatted_to_string = "||".join(
                f"CASE WHEN {dbconnection.ident(x)} IS NULL THEN "
                f"'{null_replacement_string}' ELSE {dbconnection.ident(x)} END"
                for x in to_list
            )
            cast_exprs = ", ".join(
                _cast_or_passthrough(
                    f'"b".{dbconnection.ident(k)}',
                    column_headers_types[to_list[idx]],
                )
                for idx, k in enumerate(from_list)
            )
            and_parts = " AND ".join(
                f'"b".{dbconnection.ident(k)} IS NOT NULL AND '
                f"\"b\".{dbconnection.ident(k)} != '' "
                for k in from_list
            )
            sql = (
                f"INSERT INTO {fk_table_ident} ({to_list_idents}) "
                f"SELECT DISTINCT {cast_exprs} FROM {temptable_ident} AS b "
                f"WHERE {concatted_from_string} NOT IN "
                f"(SELECT {concatted_to_string} FROM {fk_table_ident}) "
                f"AND {and_parts}"
            )
            dbconnection.execute(sql)

            nr_fk_after = dbconnection.execute_and_fetchall(
                f"SELECT count(*) FROM {fk_table_ident}"
            )[0][0]
            if nr_fk_after > nr_fk_before:
                message_utils.MessagebarAndLog.info(
                    log_msg=QCoreApplication.translate(
                        "midv_data_importer",
                        "In total %s rows were imported to foreign key table %s while importing to %s.",
                    )
                    % (str(nr_fk_after - nr_fk_before), fk_table, dest_table)
                )


class MidvDataImporterError(Exception):
    pass


def import_exception_handler(func: Callable) -> Callable:
    @wraps(func)
    def new_func(*args, **kwargs):
        try:
            result = func(*args, **kwargs)
        except MidvDataImporterError as e:
            common_utils.stop_waiting_cursor()
            message_utils.MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "midv_data_importer", "Import error, see log message panel"
                ),
                log_msg=str(e),
            )
        else:
            return result

    return new_func
