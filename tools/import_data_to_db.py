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
import traceback
from functools import wraps
from operator import itemgetter
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd
import psycopg2
import psycopg2.extras
from qgis.PyQt.QtCore import QCoreApplication

from midvatten.tools.utils import common_utils, db_utils, dialog_utils, message_utils
from midvatten.tools.utils.exceptions import UserInterruptError
from midvatten.tools.utils.db_utils import DbConnectionManager
from midvatten.tools.utils.date_utils import instant_key


class MidvDataImporter:  # this class is intended to be a multipurpose import class  BUT loggerdata probably needs specific importer or its own subfunction
    def __init__(self) -> None:
        self.columns = 0
        self.recsbefore = 0
        self.recsafter = 0
        self.recstoimport = 0
        self.recsinfile = 0
        self.temptable_name = None
        self.csvlayer = None
        self.foreign_keys_import_question = None

    def general_import(
        self,
        dest_table: str,
        file_data: Any,
        allow_obs_fk_import: bool = False,
        _dbconnection: Optional[DbConnectionManager] = None,
        dump_temptable: bool = False,
        source_srid: Optional[int] = None,
        skip_confirmation: bool = False,
        binary_geometry: bool = False,
        defer_commit: bool = False,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        """General method for importing a list of list to a table

            self.temptableName must be the name of the table containing the new data to import.

        :param dest_table: The destination table
        :param file_data: a list of list with a header list as first row
        :param allow_obs_fk_import: True to allow creation of obsids in obs_points and obs_lines.
        :param _dbconnection: A db_utils.DbConnectionManager-instance if other than the currently selected in the midvatten
                              settings dialog.
        :param dump_temptable: True to create a csvfile from internal temporary table.
        :param source_srid: The srid of the source geometry column if the geometry is a WKT or WKB
        :param skip_confirmation: True to not ask the user to import foreign keys.
        :param binary_geometry: True if the source geometry column should be parsed as a WKB, else it's parsed as WKT.
        :return:
        """

        self.temptable_name = None
        import_messages = [
            QCoreApplication.translate(
                "midv_data_importer",
                """Note:\nForeign keys will be imported silently.""",
            )
        ]

        if skip_confirmation:
            self.foreign_keys_import_question = 1

        dbconnection: Optional[DbConnectionManager] = None
        try:
            if file_data is None or not file_data:
                return
            message_utils.MessagebarAndLog.info(
                log_msg=QCoreApplication.translate(
                    "midv_data_importer",
                    "\nImport to %s starting\n--------------------",
                )
                % dest_table
            )

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
            ) = self._validate_and_connect(dest_table, file_data, _dbconnection)

            recsinfile = len(file_data[1:])
            all_rownumbers = tuple(range(recsinfile))
            remaining_rownumbers = tuple(all_rownumbers)

            if progress_callback:
                progress_callback(
                    QCoreApplication.translate(
                        "midv_data_importer", "Creating temporary table..."
                    )
                )

            in_file_dups, in_file_dup_rownumbers = self.list_to_table(
                dbconnection, dest_table, file_data, primary_keys_for_concat
            )

            sql_remaining = dbconnection.sql_ident(
                "SELECT {rowid} FROM {t}",
                rowid=self.temptable_rowid_name,
                t=self.temptable_name,
            )
            get_remaining_rownumbers = lambda: [
                x[0] for x in dbconnection.execute_and_fetchall(sql_remaining)
            ]
            get_removed_rownumbers = lambda start_numbers, remaining: [
                x for x in start_numbers if x not in set(remaining)
            ]
            get_row_subset = lambda rownumbers: [
                ", ".join([str(x) for x in file_data[1:][rownr]])
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
                return

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
                return

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
        file_data: Any,
        _dbconnection: Optional[DbConnectionManager],
    ) -> Tuple:
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
            col for col in file_data[0] if col in column_headers_types
        ]
        existing_columns_in_temptable = file_data[0]
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
        primary_keys: List[str],
        all_rownumbers: Tuple,
        remaining_rownumbers: Tuple,
        get_remaining_rownumbers: Callable,
        get_removed_rownumbers: Callable,
        get_row_subset: Callable,
        in_file_dup_rownumbers: List[int],
        import_messages: List[str],
    ) -> Tuple:
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
        existing_columns_in_dest_table: List[str],
        remaining_rownumbers: Tuple,
        get_remaining_rownumbers: Callable,
        get_removed_rownumbers: Callable,
        get_row_subset: Callable,
        import_messages: List[str],
    ) -> Tuple:
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
        remaining_rownumbers: Tuple,
        all_rownumbers: Tuple,
        import_messages: List[str],
    ) -> None:
        """Assemble the confirmation message and ask the user whether to proceed.

        Raises UserInterruptError if the user chooses not to import.
        """
        if self.foreign_keys_import_question:
            if len(remaining_rownumbers) != len(all_rownumbers):
                message_utils.MessagebarAndLog.info(
                    log_msg=QCoreApplication.translate(
                        "midv_data_importer",
                        "Skipping confirmation dialog: %s out of %s rows to import (duplicates removed).",
                    )
                    % (str(len(remaining_rownumbers)), str(len(all_rownumbers)))
                )
            return

        if len(remaining_rownumbers) == len(all_rownumbers):
            import_messages.append(
                QCoreApplication.translate("midv_data_importer", "Proceed with import?")
            )
            self.foreign_keys_import_question = 1
        else:
            import_messages.append(
                QCoreApplication.translate(
                    "midv_data_importer",
                    """There are %s out of %s number of rows to import (see log for more info about removed rows).\n\nProceed with import?""",
                )
                % (str(len(remaining_rownumbers)), str(len(all_rownumbers)))
            )

        if import_messages:
            stop_question = dialog_utils.Askuser(
                "YesNo",
                "\n".join(import_messages),
                QCoreApplication.translate("midv_data_importer", "Info"),
            )
            if stop_question.result == 0:
                raise UserInterruptError()

    def _handle_foreign_keys(
        self,
        dbconnection: DbConnectionManager,
        dest_table: str,
        existing_columns_in_temptable: List[str],
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

    def _build_and_execute_insert(
        self,
        dbconnection: DbConnectionManager,
        dest_table: str,
        existing_columns_in_dest_table: List[str],
        existing_columns_in_temptable: List[str],
        column_headers_types: Dict[str, str],
        not_null_columns: List[str],
        source_srid: Optional[int],
        binary_geometry: bool,
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
                sourcecols.append(
                    f"""(CASE WHEN {colname} IS NOT NULL\n    THEN CAST({colname} AS {column_headers_types[colname]}) ELSE {null_replacement} END)"""
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
            "dest_columns": ", ".join(sorted(existing_columns_in_dest_table)),
            "source_table": self.temptable_name,
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
        common_utils.stop_waiting_cursor()

    def list_to_table(
        self,
        dbconnection: DbConnectionManager,
        destination_table: str,
        file_data: List[Any],
        primary_keys_for_concat: List[str],
    ) -> Tuple[int, List[int]]:
        """
        TODO: This method can be extremely slow sometimes.
        @param dbconnection:
        @param destination_table:
        @param file_data:
        @param primary_keys_for_concat:
        @return: (number of in-file duplicates skipped, their original row-numbers)
        """
        # field_name comes from the imported file's header row (user-supplied),
        # so it must be safely quoted before being spliced into CREATE TABLE.
        # quote_ident (not ident) is used so non-ASCII headers (e.g. Swedish
        # å/ä/ö) are preserved rather than rejected.
        fieldnames_types = [
            f"{db_utils.quote_ident(field_name)} TEXT" for field_name in file_data[0]
        ]
        tname = f"temp_{destination_table}_temp"
        self.temptable_rowid_name = f"{tname}_rowid"
        fieldnames_types.append(f"{self.temptable_rowid_name} INTEGER")
        self.temptable_name = dbconnection.create_temporary_table_for_import(
            tname, fieldnames_types
        )

        numskipped, in_file_dup_rownumbers = self.list_to_table_using_pandas(
            dbconnection,
            self.temptable_name,
            self.temptable_rowid_name,
            file_data,
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

    def list_to_table_using_pandas(
        self,
        dbconnection: DbConnectionManager,
        temptable_name: str,
        temptable_rowidcol: str,
        file_data: List[Any],
        primary_keys_for_concat: List[str],
    ) -> Tuple[int, List[int]]:
        numskipped = 0
        in_file_dup_rownumbers: List[int] = []
        df = pd.DataFrame.from_records(file_data[1:], columns=file_data[0])
        df[temptable_rowidcol] = df.index

        if primary_keys_for_concat:
            # Dedup key: normalize date_time to its second-instant so '00:00' and
            # '00:00:00' collapse, but fall back to the RAW text when unparseable so
            # distinct malformed dates are not merged (they escape the normalized
            # uniqueness in the DB too). The stored date_time stays raw — we compute
            # the key on a separate frame and never mutate df's columns.
            key_df = df[list(primary_keys_for_concat)].copy()
            if "date_time" in key_df.columns:
                key_df["date_time"] = key_df["date_time"].map(
                    lambda v: instant_key(v) or v
                )
            duplicate_mask = key_df.duplicated(keep="first")
            # Original file row-numbers of the in-file duplicates, so the caller can
            # report them separately from rows that already exist in the database.
            in_file_dup_rownumbers = df.loc[duplicate_mask, temptable_rowidcol].tolist()
            numskipped = len(in_file_dup_rownumbers)
            df = df[~duplicate_mask].reset_index(drop=True)

        for column in df.columns:
            try:
                df[column] = df[column].str.strip()
            except (AttributeError, TypeError):
                # Not a string column
                pass
            pass

        # Replaces NaN with None and empty strings with None so all insert paths
        # treat missing values as SQL NULL without needing post-insert UPDATE queries.
        df = df.astype(object).where(pd.notnull(df), None)
        df = df.replace("", None)

        if dbconnection.is_sqlite():
            sql = f"INSERT INTO {dbconnection.ident(temptable_name)} VALUES ({dbconnection.placeholders(len(df.columns))})"

            dbconnection.cursor.executemany(sql, list(df.itertuples(index=False)))
        else:
            csv_buffer = io.StringIO()
            df.to_csv(csv_buffer, index=False, header=False, sep=";")
            csv_buffer.seek(0)
            try:
                # null="" tells COPY to treat empty CSV fields as SQL NULL, consistent
                # with df.replace("", None) above.
                dbconnection.cursor.copy_from(
                    csv_buffer, temptable_name, sep=";", null=""
                )
            except psycopg2.errors.BadCopyFileFormat:
                # This is probably due to the separator exists in the values.
                data = list(df.itertuples(index=False))
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
        primary_keys: List[str],
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
        kwargs = {"colname": geom_col, "null": null_replacement}

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

        if int(_source_srid) == int(dest_srid):
            to_geometry = f"""{convert_func}({geom_col}, {dest_srid})"""
        else:
            to_geometry = f"""ST_Transform({convert_func}({geom_col}, {_source_srid}), {dest_srid})"""
        kwargs["to_geometry"] = to_geometry
        return sql.format(**kwargs)

    def check_and_delete_stratigraphy(
        self, existing_columns: List[str], dbconnection: DbConnectionManager
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
        foreign_keys: Dict[str, List[Tuple[str, str]]],
        existing_columns_in_temptable: List[str],
    ) -> None:
        # TODO: Empty foreign keys are probably imported now. Must add "case when...NULL" to a couple of sql questions here

        # What I want to do:
        # import all foreign keys from temptable that doesn't already exist in foreign key table
        # insert into fk_table (to1, to2) select distinct from1(cast as), from2(cast as) from temptable where concatted_from_and_case_when_null not in concatted_to_and_case_when_null

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
                f'CAST("b".{dbconnection.ident(k)} AS {column_headers_types[to_list[idx]]})'
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
