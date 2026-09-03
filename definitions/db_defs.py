import os


def latest_database_version():
    # The newest plugin version whose schema differs from older databases.
    # Compared in warn_about_old_database() against the "Midvatten plugin X.Y.Z"
    # marker stamped into about_db at creation/upgrade. Bump ONLY when the schema
    # changes (not on every release), so the "database is old" warning fires only
    # for databases that predate the current schema.
    return "2.0.0"


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
