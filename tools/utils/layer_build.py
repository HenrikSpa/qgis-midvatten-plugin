"""Build QgsVectorLayer instances from LayerSpec descriptions.

`prime_feature_count()` is the fix for the long-standing "attribute
table only shows 100 rows" bug: QGIS sizes its attribute-table cache as
`featureCount() + 100`, and a stale/zero `featureCount()` caps the cache
at 100. Priming it on the QGIS provider's own connection before the
dual-view observes the layer makes the cache open to the correct size.
"""

from typing import Optional

from qgis.core import Qgis, QgsVectorLayer

from midvatten.tools.utils.db_utils import DbConnectionManager, get_tables
from midvatten.tools.utils.layer_specs import LayerSpec
from midvatten.tools.utils.midvatten_utils import (
    compare_verson_lists,
    create_layer,
    version_comparison_list,
)

_KEY_COLUMN_FALLBACKS: tuple[Optional[str], ...] = (None, "obsid", "rowid")


def _legacy_view_name(tablename: str, existing_tables: list[str]) -> Optional[str]:
    """Return the `view_obs_points` / `view_obs_lines` replacement table
    name to use on QGIS < 3.16 (see QGIS issue #28453), or None if no
    substitution applies.
    """
    if tablename not in ("obs_points", "obs_lines"):
        return None
    if f"view_{tablename}" not in existing_tables:
        return None
    is_old = compare_verson_lists(
        version_comparison_list(Qgis.QGIS_VERSION),
        version_comparison_list("3.16"),
    )
    if not is_old:
        return None
    return f"view_{tablename}"


def build_layer(
    spec: LayerSpec,
    dbconnection: DbConnectionManager,
    existing_tables: Optional[list[str]] = None,
) -> Optional[QgsVectorLayer]:
    """Create a valid QgsVectorLayer for `spec`, or None if no
    combination of key columns produces a valid layer.

    Pass `existing_tables` (from `db_utils.get_tables(..., skip_views=False)`)
    when calling in a loop, to avoid re-running the schema introspection
    query per spec.

    The key-column fallback order `(None, "obsid", "rowid")` matters:
    `None` first lets QGIS autodetect the primary key, which is correct
    for tables with composite PKs (e.g. `(obsid, date_time)` — most
    Midvatten tables). The named fallbacks only fire for views that lack
    a declared PK.
    """
    if existing_tables is None:
        existing_tables = get_tables(dbconnection, skip_views=False)
    if spec.tablename not in existing_tables:
        return None

    legacy = _legacy_view_name(spec.tablename, existing_tables)
    source_table = legacy or spec.tablename

    for key_column in _KEY_COLUMN_FALLBACKS:
        layer = create_layer(
            source_table,
            geometrycolumn=spec.geometry_column,
            dbconnection=dbconnection,
            layername=spec.name,
            keycolumn=key_column,
        )
        if layer.isValid():
            return layer
    return None


def prime_feature_count(layer: QgsVectorLayer) -> None:
    """Force the provider to compute `featureCount()` now, before any
    attribute-table dual-view observes the layer. Without this, QGIS
    sizes the attribute-table row cache as `featureCount() + 100` against
    a stale zero count and caps the table at exactly 100 rows.
    """
    layer.dataProvider().reloadData()
    layer.updateExtents()
    _ = layer.featureCount()
