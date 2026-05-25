"""
File I/O utilities for the Midvatten plugin.
"""

import csv
import os
import tempfile
from contextlib import contextmanager
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
) -> Optional[str]:
    if filename is None:
        raise TypeError(tr("get_delimiter", "Must give filename or supply rows"))
    with open(filename, encoding=charset) as f:
        rows = f.readlines()
    if skip_empty_rows:
        rows = [row for row in rows if row.strip().strip("\r").strip("\n")]
    delimiter = get_delimiter_from_file_rows(
        rows, filename=filename, delimiters=delimiters, num_fields=num_fields
    )
    if delimiter is None:
        _result = ask_for_delimiter(
            question=returnunicode(
                tr(
                    "get_delimiter",
                    "Delimiter couldn't be found automatically for %s. Give the correct one (ex ';'):",
                )
            )
            % filename
        )
        delimiter = _result[0]
    return delimiter


def _count_columns(row: str, delimiter: str) -> int:
    if len(delimiter) == 1:
        return len(next(csv.reader([row], delimiter=delimiter)))
    return len(row.split(delimiter))


def get_delimiter_from_file_rows(
    rows: List[str],
    filename: Optional[str] = None,
    delimiters: Optional[List[str]] = None,
    num_fields: Optional[int] = None,
) -> Optional[str]:
    if filename is None:
        filename = "the rows"
    if delimiters is None:
        delimiters = [";", ","]

    # When num_fields is specified, test candidates in order (caller knows the structure)
    if num_fields is not None:
        any_consistent = False
        for candidate in delimiters:
            col_counts = {_count_columns(row, candidate) for row in rows}
            if len(col_counts) == 1:
                any_consistent = True
                if col_counts.pop() == num_fields:
                    return candidate
        if any_consistent:
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

    # Try csv.Sniffer for auto-detection (handles quoting and escaping)
    single_char_delims = "".join(d for d in delimiters if len(d) == 1)
    if single_char_delims:
        try:
            dialect = csv.Sniffer().sniff(
                "\n".join(r.rstrip("\r\n") for r in rows),
                delimiters=single_char_delims,
            )
            if dialect.delimiter in delimiters:
                return dialect.delimiter
        except csv.Error:
            pass

    # Fallback: column-counting per candidate (quote-aware for single-char)
    best_delim = None
    best_cols = 0
    for candidate in delimiters:
        col_counts = {_count_columns(row, candidate) for row in rows}
        if len(col_counts) != 1:
            continue
        nr_of_cols = col_counts.pop()
        if nr_of_cols > best_cols:
            best_cols = nr_of_cols
            best_delim = candidate

    if best_delim is not None and best_cols > 1:
        return best_delim

    return None


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


_PLUGIN_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


def plugin_path(*parts: str) -> str:
    """Absolute path under the plugin root (<plugin>/)."""
    return os.path.join(_PLUGIN_ROOT, *parts)


def definitions_path(*parts: str) -> str:
    """Absolute path under <plugin>/definitions/."""
    return os.path.join(_PLUGIN_ROOT, "definitions", *parts)


def ui_path(*parts: str) -> str:
    """Absolute path under <plugin>/ui/."""
    return os.path.join(_PLUGIN_ROOT, "ui", *parts)


def templates_path(*parts: str) -> str:
    """Absolute path under <plugin>/templates/."""
    return os.path.join(_PLUGIN_ROOT, "templates", *parts)
