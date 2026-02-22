"""QGIS/PostgreSQL connection settings. No dependency on backends."""

from qgis.PyQt.QtCore import QSettings

from midvatten.tools.utils.common_utils import returnunicode as ru


def get_postgis_connections() -> dict[str, dict[str, str]]:
    qs = QSettings()
    postgresql_connections: dict[str, dict[str, str]] = {}
    for k in sorted(qs.allKeys()):
        k = ru(k)
        if k.startswith("PostgreSQL"):
            cols = k.split("/")
            conn_name = cols[2]
            try:
                setting = cols[3]
            except IndexError:
                continue
            value = qs.value(k)
            postgresql_connections.setdefault(conn_name, {})[setting] = value
    postgresql_connections = ru(postgresql_connections, keep_containers=True)
    return postgresql_connections
