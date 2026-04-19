"""
Execute SQL from file with dialect-prefixed lines.
Supports SPATIALITE/POSTGIS and SQLITE/POSTGRESQL prefixes (Option B).
"""

import re
from typing import Callable

from midvatten.tools.utils.string_utils import lstrip, returnunicode as ru
from midvatten.tools.utils.message_utils import MessagebarAndLog, sql_failed_msg
from qgis.PyQt.QtCore import QCoreApplication

from midvatten.tools.utils.db_utils.connection import DbConnectionManager
from midvatten.tools.utils.db_utils.execution import sql_alter_db


# Dialect line prefixes: (keywords for this backend, keywords for the other)
_SQLITE_KEYWORDS = ("SPATIALITE", "SQLITE")
_POSTGRESQL_KEYWORDS = ("POSTGIS", "POSTGRESQL")


def _strip_dialect_prefix(line: str, is_sqlite: bool) -> str:
    """Strip the dialect keyword from the start of line if it matches this backend."""
    if is_sqlite:
        for kw in _SQLITE_KEYWORDS:
            if line.strip().upper().startswith(kw):
                return lstrip(kw, line.strip()).strip()
    else:
        for kw in _POSTGRESQL_KEYWORDS:
            if line.strip().upper().startswith(kw):
                return lstrip(kw, line.strip()).strip()
    return line.strip()


def _line_is_for_other_dialect(line: str, is_sqlite: bool) -> bool:
    """True if line is prefixed with the other backend's keyword (should skip)."""
    upper = line.strip().upper()
    if is_sqlite:
        return any(upper.startswith(kw) for kw in _POSTGRESQL_KEYWORDS)
    return any(upper.startswith(kw) for kw in _SQLITE_KEYWORDS)


def _transform_line_for_postgresql(line: str) -> str:
    """Apply PostgreSQL-specific transformations (rowid -> CTID, double -> double precision)."""
    line = re.sub(r"rowid as rowid", "CTID as rowid", line, flags=re.IGNORECASE)
    line = re.sub(r"\bdouble\b", "double precision", line, flags=re.IGNORECASE)
    return line


def execute_sqlfile_using_func(
    sqlfilename: str,
    function: Callable = sql_alter_db,
) -> None:
    with open(sqlfilename) as f:
        f.readline()  # first line is encoding info
        for line in f:
            if not line or line.startswith("#"):
                continue
            function(line)


def execute_sqlfile(
    sqlfilename: str,
    dbconnection: DbConnectionManager,
    merge_newlines: bool = False,
) -> None:
    is_sqlite = dbconnection.is_sqlite()
    is_postgresql = dbconnection.is_postgresql()

    with open(sqlfilename) as f:
        lines = [line.rstrip("\n") for rownr, line in enumerate(f) if rownr > 0]
    lines = [
        _strip_dialect_prefix(line, is_sqlite)
        for line in lines
        if line.strip()
        and not line.strip().startswith("#")
        and not _line_is_for_other_dialect(line, is_sqlite)
    ]

    if merge_newlines:
        lines = [f"{line};" for line in " ".join(lines).split(";") if line.strip()]

    for line in lines:
        if line:
            if is_postgresql:
                line = _transform_line_for_postgresql(line)
            try:
                dbconnection.execute(line)
            except Exception as e:
                MessagebarAndLog.critical(
                    bar_msg=sql_failed_msg(),
                    log_msg=QCoreApplication.translate(
                        "NewDb", "sql failed:\n%s\nerror msg:\n%s\n"
                    )
                    % (ru(line), str(e)),
                )
