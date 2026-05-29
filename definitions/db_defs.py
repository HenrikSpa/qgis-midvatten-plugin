import os


def latest_database_version():
    return "1.11.1"


def sql_setup_file():
    """
    >>> os.path.isfile(sql_setup_file())
    True
    """
    return os.path.join(os.path.dirname(__file__), "create_db.sql")


def extra_datatables_sqlfile():
    """
    >>> os.path.isfile(extra_datatables_sqlfile())
    True
    """
    return os.path.join(os.path.dirname(__file__), "create_db_extra_data_tables.sql")
