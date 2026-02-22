"""Database-related exceptions."""


class DatabaseLockedError(Exception):
    """Raised when SQLite database is locked (e.g. -journal/-wal file present)."""

    pass
