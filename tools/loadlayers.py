"""Load the default Midvatten layers into the QGIS layer tree."""

import os
import traceback

from qgis.core import QgsLayerTreeGroup, QgsProject, QgsRelation
from qgis.PyQt.QtCore import QCoreApplication

from midvatten.tools.utils import common_utils, db_utils
from midvatten.tools.utils.layer_build import build_layer, prime_feature_count
from midvatten.tools.utils.layer_specs import GROUPS, GroupSpec, LayerSpec
from midvatten.tools.utils.midvatten_utils import getcurrentlocale


class LoadLayers:
    def __init__(self, iface, settingsdict=None, group_name="Midvatten_OBS_DB"):
        if group_name not in GROUPS:
            raise ValueError(f"Unknown Midvatten layer group: {group_name!r}")
        self.iface = iface
        self.settingsdict = settingsdict or {}
        self.group: GroupSpec = GROUPS[group_name]
        self.root = QgsProject.instance().layerTreeRoot()
        self._remove_existing_group()
        self._load()

    def _remove_existing_group(self) -> None:
        existing = self.root.findGroup(self.group.name)
        if existing is not None:
            self.root.removeChildNode(existing)

    def _load(self) -> None:
        dbconnection = db_utils.DbConnectionManager()
        try:
            existing_tables = db_utils.get_tables(dbconnection, skip_views=False)
            layer_group = QgsLayerTreeGroup(name=self.group.name, checked=True)
            self.root.insertChildNode(self.group.position_index, layer_group)

            obs_points_layer = None
            screen_layer = None
            for spec in self.group.resolve_layers(dbconnection):
                layer = build_layer(spec, dbconnection, existing_tables)
                if layer is None:
                    continue
                QgsProject.instance().addMapLayers([layer], False)
                tree_layer = layer_group.insertLayer(0, layer)
                prime_feature_count(layer)
                self._apply_style(layer, spec)
                if not spec.initially_visible and tree_layer is not None:
                    tree_layer.setItemVisibilityCheckedRecursive(False)
                if spec.tablename == "obs_points":
                    obs_points_layer = layer
                elif spec.tablename == "screen":
                    screen_layer = layer

            self._register_relations(obs_points_layer, screen_layer, dbconnection)
            if obs_points_layer is not None:
                self.iface.mapCanvas().setExtent(obs_points_layer.extent())
        finally:
            dbconnection.closedb()

        self.iface.mapCanvas().refresh()

    def _apply_style(self, layer, spec: LayerSpec) -> None:
        definitions = os.path.join(os.path.dirname(__file__), "..", "definitions")
        style_sv = os.path.join(definitions, f"{spec.tablename}_sv.qml")
        style_default = os.path.join(definitions, f"{spec.tablename}.qml")
        locale_is_swedish = getcurrentlocale()[0] == "sv_SE"
        candidates = []
        if locale_is_swedish and os.path.isfile(style_sv):
            candidates.append(style_sv)
        candidates.append(style_default)
        for path in candidates:
            try:
                layer.loadNamedStyle(path)
                return
            except Exception:
                common_utils.MessagebarAndLog.info(log_msg=traceback.format_exc())

    def _register_relations(
        self,
        obs_points_layer,
        screen_layer,
        dbconnection: db_utils.DbConnectionManager,
    ) -> None:
        if self.group.name != "Midvatten_OBS_DB":
            return
        if obs_points_layer is None or screen_layer is None:
            return
        if not db_utils.verify_table_exists("screen", dbconnection=dbconnection):
            return

        rel = QgsRelation()
        rel.setId("obs_points_screen")
        rel.setName(QCoreApplication.translate("LoadLayers", "Screens"))
        rel.setReferencedLayer(obs_points_layer.id())
        rel.setReferencingLayer(screen_layer.id())
        rel.addFieldPair("obsid", "obsid")
        rel.setStrength(QgsRelation.Association)
        if rel.isValid():
            QgsProject.instance().relationManager().addRelation(rel)
        else:
            common_utils.MessagebarAndLog.warning(
                bar_msg=QCoreApplication.translate(
                    "LoadLayers",
                    "Failed to create obs_points_screen relation",
                ),
                log_msg=str(rel.validationError()),
            )
