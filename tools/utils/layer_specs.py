"""Typed specs for QGIS layers loaded by the Midvatten plugin.

Replaces the parallel-array API of `add_layers_to_list` with a single
`LayerSpec` per layer, letting spatial and non-spatial layers mix freely
in one list.
"""

from dataclasses import dataclass
from typing import Callable, Optional

from midvatten.tools.utils.db_utils import DbConnectionManager


@dataclass
class LayerSpec:
    """Declarative description of one QGIS layer to load.

    `geometry_column=None` means non-spatial.
    """

    tablename: str
    display_name: Optional[str] = None
    geometry_column: Optional[str] = None
    initially_visible: bool = True

    @property
    def name(self) -> str:
        return self.display_name or self.tablename


@dataclass
class GroupSpec:
    """Describes one of the top-level layer groups the plugin creates.

    `resolve_layers` is a callable rather than a plain list so groups
    whose membership depends on DB introspection (e.g. all `zz_*` tables)
    can compute their specs at load time.
    """

    name: str
    position_index: int
    resolve_layers: Callable[[DbConnectionManager], list[LayerSpec]]


def _obs_db_layers(_db: DbConnectionManager) -> list[LayerSpec]:
    from midvatten.definitions.midvatten_defs import OBS_DB_LAYERS

    return list(OBS_DB_LAYERS)


def _data_tables_layers(_db: DbConnectionManager) -> list[LayerSpec]:
    from midvatten.definitions.midvatten_defs import DATA_TABLES_LAYERS

    return list(DATA_TABLES_LAYERS)


def _data_domain_layers(db: DbConnectionManager) -> list[LayerSpec]:
    from midvatten.tools.utils import db_utils

    tables_columns = db_utils.tables_columns(dbconnection=db)
    return [LayerSpec(t) for t in tables_columns.keys() if t.startswith("zz_")]


GROUPS: dict[str, GroupSpec] = {
    "Midvatten_OBS_DB": GroupSpec(
        name="Midvatten_OBS_DB", position_index=0, resolve_layers=_obs_db_layers
    ),
    "Midvatten_data_domains": GroupSpec(
        name="Midvatten_data_domains",
        position_index=1,
        resolve_layers=_data_domain_layers,
    ),
    "Midvatten_data_tables": GroupSpec(
        name="Midvatten_data_tables",
        position_index=1,
        resolve_layers=_data_tables_layers,
    ),
}
