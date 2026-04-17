"""
File I/O utilities for the Midvatten plugin.
"""

import csv
import os
import tempfile
from contextlib import contextmanager
from operator import itemgetter
from typing import Any, List, Optional, Type
from collections.abc import Iterator

import qgis.PyQt

from midvatten.tools.utils.exceptions import UserInterruptError
from midvatten.tools.utils.message_utils import MessagebarAndLog
from midvatten.tools.utils.string_utils import returnunicode, tr


@contextmanager
def tempinput(data: str, charset: str = "UTF-8", suffix: str = ".csv") -> Iterator[str]:
    """Creates and yields a temporary file from data

    The file can't be deleted in windows for some strange reason.
    There shouldn't be so many temporary files using this function
    for it to be a major problem though. Relying on windows temp file
    cleanup instead.
    """
    temp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    unicode_data = returnunicode(data)
    encoded_data = unicode_data.encode(charset)
    temp.write(encoded_data)
    temp.close()
    yield temp.name
    # os.unlink(temp.name) #TODO: This results in an error: WindowsError: [Error 32] Det går inte att komma åt filen eftersom den används av en annan process: 'c:\\users\\dator\\appdata\\local\\temp\\tmpxvcfna.csv'


def get_delimiter(
    filename: Optional[str] = None,
    rows: None = None,
    charset: str = "utf-8",
    delimiters: Optional[List[str]] = None,
    num_fields: Optional[int] = None,
    skip_empty_rows: bool = True,
) -> str:
    if filename is None:
        raise TypeError(tr("get_delimiter", "Must give filename or supply rows"))
    with open(filename, encoding=charset) as f:
        rows = f.readlines()
    if skip_empty_rows:
        rows = [row for row in rows if row.strip().strip("\r").strip("\n")]
    delimiter = get_delimiter_from_file_rows(
        rows, filename=filename, delimiters=delimiters, num_fields=num_fields
    )
    return delimiter


def get_delimiter_from_file_rows(
    rows: List[str],
    filename: Optional[str] = None,
    delimiters: Optional[List[str]] = None,
    num_fields: Optional[int] = None,
) -> str:
    if filename is None:
        filename = "the rows"
    delimiter = None
    if delimiters is None:
        delimiters = [",", ";"]
    tested_delim = []
    for _delimiter in delimiters:
        cols_on_all_rows = set()
        cols_on_all_rows.update([len(row.split(_delimiter)) for row in rows])
        if len(cols_on_all_rows) == 1:
            nr_of_cols = cols_on_all_rows.pop()
            if num_fields is not None and nr_of_cols == num_fields:
                delimiter = _delimiter
                break
            tested_delim.append((_delimiter, nr_of_cols))

    if not delimiter:
        # No delimiter worked
        if not tested_delim:
            _delimiter = ask_for_delimiter(
                question=returnunicode(
                    tr(
                        "get_delimiter_from_file_rows",
                        "Delimiter couldn't be found automatically for %s. Give the correct one (ex ';'):",
                    )
                )
                % filename
            )
            delimiter = _delimiter[0]
        else:
            if delimiter is None:
                if num_fields is not None:
                    MessagebarAndLog.critical(
                        returnunicode(
                            tr(
                                "get_delimiter_from_file_rows",
                                "Delimiter not found for %s. The file must contain %s fields, but none of %s worked as delimiter.",
                            )
                        )
                        % (filename, str(num_fields), " or ".join(delimiters))
                    )
                    return None

                lenght = max(tested_delim, key=itemgetter(1))[1]

                more_than_one_delimiter = [x[0] for x in tested_delim if x[1] == lenght]

                delimiter = max(tested_delim, key=itemgetter(1))[0]

                if lenght == 1 or len(more_than_one_delimiter) > 1:
                    _delimiter = ask_for_delimiter(
                        question=returnunicode(
                            tr(
                                "get_delimiter_from_file_rows",
                                "Delimiter couldn't be found automatically for %s. Give the correct one (ex ';'):",
                            )
                        )
                        % filename
                    )
                    delimiter = _delimiter[0]
    return delimiter


def ask_for_delimiter(
    header: str = tr("ask_for_delimiter", "Give delimiter"),
    question: str = "",
    default: str = ";",
) -> str:
    _delimiter = qgis.PyQt.QtWidgets.QInputDialog.getText(
        None,
        tr("ask_for_delimiter", "Give delimiter"),
        question,
        qgis.PyQt.QtWidgets.QLineEdit.Normal,
        default,
    )
    if not _delimiter[1]:
        MessagebarAndLog.info(
            bar_msg=returnunicode(
                tr("ask_for_delimiter", "Delimiter not given. Stopping.")
            )
        )
        raise UserInterruptError()
    else:
        delimiter = _delimiter[0]
    return delimiter


def write_printlist_to_file(
    filename: str,
    printlist: List[Any],
    dialect: Type[csv.excel] = csv.excel,
    delimiter: str = ";",
    encoding: str = "utf-8",
    **kwds,
):
    with open(filename, "w", newline="", encoding=encoding) as csvfile:
        csvwriter = csv.writer(csvfile, delimiter=delimiter, dialect=dialect, **kwds)
        # csvwriter.writerows([[bytes(returnunicode(col), encoding) for col in row] for row in printlist])
        csvwriter.writerows(returnunicode(printlist, keep_containers=True))
    MessagebarAndLog.info(
        bar_msg=returnunicode(tr("write_printlist_to_file", "Data written to file %s."))
        % filename
    )


def get_full_filename(filename: str) -> str:
    return os.path.join(
        os.sep, os.path.dirname(__file__), "../..", "definitions", filename
    )
