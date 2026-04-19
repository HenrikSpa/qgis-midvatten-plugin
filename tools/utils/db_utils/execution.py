"""
Unified execution API and connection context manager.
Execute functions take a single sql: str and optional args (no batch).
"""

import traceback
from contextlib import contextmanager
from typing import Callable, Any, Optional

from qgis.PyQt.QtCore import QCoreApplication

from midvatten.tools.utils.message_utils import MessagebarAndLog, sql_failed_msg
from midvatten.tools.utils.string_utils import returnunicode as ru
from midvatten.tools.utils.db_utils.connection import DbConnectionManager


@contextmanager
def use_or_create_connection(dbconnection: Optional[DbConnectionManager]):
    """Yield dbconnection; if None, create DbConnectionManager and close when done."""
    created = False
    if dbconnection is None:
        dbconnection = DbConnectionManager()
        created = True
    try:
        yield dbconnection
    except Exception:
        raise
    finally:
        if created:
            dbconnection.closedb()


def sql_load_fr_db(
    sql: str,
    dbconnection: Optional[DbConnectionManager] = None,
    print_error_message_in_bar: bool = True,
    execute_args: Optional[Any] = None,
) -> Any:
    """Execute sql (single statement), return (True, rows) or (False, [])."""
    with use_or_create_connection(dbconnection) as dbconnection:
        try:
            result = dbconnection.execute_and_fetchall(sql, args=execute_args)
        except Exception as e:
            textstring = QCoreApplication.translate(
                "sql_load_fr_db",
                """DB error!\n SQL causing this error:%s\nMsg:\n%s""",
            ) % (ru(sql), str(e))
            if print_error_message_in_bar:
                MessagebarAndLog.warning(bar_msg=sql_failed_msg(), duration=4)
            MessagebarAndLog.warning(log_msg=textstring)
            return (False, [])
        return (True, result)


def sql_alter_db(
    sql: str,
    dbconnection: Optional[DbConnectionManager] = None,
    all_args: Optional[Any] = None,
) -> None:
    """Execute sql (single statement) and commit. For SQLite, turn PRAGMA foreign_keys ON first."""
    # Backward compat: all_args=[(x,)] -> pass args=(x,) for single statement
    args = all_args
    if isinstance(all_args, (list, tuple)) and len(all_args) == 1:
        args = all_args[0]
    with use_or_create_connection(dbconnection) as dbconnection:
        if dbconnection.is_sqlite():
            try:
                dbconnection.execute("PRAGMA foreign_keys = ON")
            except Exception:
                MessagebarAndLog.info(log_msg=traceback.format_exc())
        try:
            dbconnection.execute_and_commit(sql, args=args)
        except Exception as e:
            textstring = QCoreApplication.translate(
                "sql_alter_db",
                """DB error!\n SQL causing this error:%s\nMsg:\n%s""",
            ) % (ru(sql), str(e))
            MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "sql_alter_db",
                    "Some sql failure, see log for additional info.",
                ),
                log_msg=textstring,
                duration=4,
            )


def check_connection_ok(write_error_msg: bool = True) -> bool:
    """Return True if a default DbConnectionManager can connect and close."""
    from qgis.core import QgsProject

    # Prefer project setting; fall back to MidvSettings if empty
    try:
        db_settings = QgsProject.instance().readEntry("Midvatten", "database")[0]
    except Exception:
        db_settings = ""
    if not db_settings:
        try:
            from midvatten.tools.midvsettings import MidvSettings

            msettings = MidvSettings()
            db_settings = msettings.settingsdict.get("database", "")
        except Exception:
            db_settings = ""

    if not db_settings:
        if write_error_msg:
            MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "DbConnectionManager",
                    "Database setting was empty. Check DB tab in Midvatten settings.",
                ),
                duration=30,
            )
        return False

    try:
        dbconnection = DbConnectionManager(db_settings)
        connection_ok = dbconnection.connect2db()
        dbconnection.closedb()
    except Exception as e:
        if write_error_msg:
            MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "check_connection_ok", "Could not connect to db: %s"
                )
                % str(e),
                duration=30,
            )
        connection_ok = False
    return connection_ok


def if_connection_ok(func: Callable) -> Callable:
    """Decorator: run func only if check_connection_ok() is True."""

    def func_wrapper(*args, **kwargs):
        if check_connection_ok():
            return func(*args, **kwargs)
        return None

    return func_wrapper
