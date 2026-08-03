from midvatten.tools.utils.db_utils.backends.base import Backend
from midvatten.tools.utils.db_utils.backends.sqlite import SQLiteBackend

try:
    from midvatten.tools.utils.db_utils.backends.postgresql import (
        PostgreSQLBackend,
        postgis_internal_tables,
    )
except ImportError:  # psycopg2 missing — PostGIS support unavailable
    PostgreSQLBackend = None
    postgis_internal_tables = None

__all__ = ["Backend", "SQLiteBackend", "PostgreSQLBackend", "postgis_internal_tables"]
