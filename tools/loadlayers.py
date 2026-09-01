"""Load the default Midvatten layers into the QGIS layer tree."""

import os
import traceback

from qgis.core import (
    QgsAttributeEditorContainer,
    QgsAttributeEditorHtmlElement,
    QgsLayerTreeGroup,
    QgsProject,
    QgsRelation,
)
from qgis.PyQt.QtCore import QCoreApplication

from midvatten.tools.utils import db_utils, message_utils
from midvatten.tools.utils.file_utils import definitions_path
from midvatten.tools.utils.layer_build import build_layer
from midvatten.tools.utils.layer_specs import (
    GROUPS,
    GroupSpec,
    LayerGroupName,
    LayerSpec,
)
from midvatten.tools.utils.midvatten_utils import is_locale_swedish


class LoadLayers:
    def __init__(self, iface, settingsdict=None, group_name=LayerGroupName.OBS_DB):
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
            obs_points_spec = None
            screen_layer = None
            for spec in self.group.resolve_layers(dbconnection):
                layer = build_layer(spec, dbconnection, existing_tables)
                if layer is None:
                    continue
                QgsProject.instance().addMapLayers([layer], False)
                tree_layer = layer_group.insertLayer(0, layer)
                self._apply_style(layer, spec)
                if not spec.initially_visible and tree_layer is not None:
                    tree_layer.setItemVisibilityCheckedRecursive(False)
                if spec.tablename == "obs_points":
                    obs_points_layer = layer
                    obs_points_spec = spec
                elif spec.tablename == "screen":
                    screen_layer = layer

            relation_registered = self._register_relations(
                obs_points_layer, screen_layer, dbconnection
            )
            if relation_registered:
                self._apply_style(obs_points_layer, obs_points_spec)
            if obs_points_layer is not None:
                self.iface.mapCanvas().setExtent(obs_points_layer.extent())
        finally:
            dbconnection.closedb()

        self.iface.mapCanvas().refresh()

    def _apply_style(self, layer, spec: LayerSpec) -> None:
        style_sv = definitions_path(f"{spec.tablename}_sv.qml")
        style_default = definitions_path(f"{spec.tablename}.qml")
        locale_is_swedish = is_locale_swedish()
        candidates = []
        if locale_is_swedish and os.path.isfile(style_sv):
            candidates.append(style_sv)
        candidates.append(style_default)
        for path in candidates:
            try:
                layer.loadNamedStyle(path)
                return
            except Exception:
                message_utils.MessagebarAndLog.info(log_msg=traceback.format_exc())

    def _register_relations(
        self,
        obs_points_layer,
        screen_layer,
        dbconnection: db_utils.DbConnectionManager,
    ) -> bool:
        if self.group.name != LayerGroupName.OBS_DB.value:
            return False
        if obs_points_layer is None:
            return False

        if screen_layer is None or not db_utils.verify_table_exists(
            "screen", dbconnection=dbconnection
        ):
            self._apply_screens_placeholder(obs_points_layer)
            return False

        rel = QgsRelation()
        rel.setId("obs_points_screen")
        rel.setName(QCoreApplication.translate("LoadLayers", "Screens"))
        rel.setReferencedLayer(obs_points_layer.id())
        rel.setReferencingLayer(screen_layer.id())
        rel.addFieldPair("obsid", "obsid")
        rel.setStrength(QgsRelation.RelationStrength.Association)
        if rel.isValid():
            QgsProject.instance().relationManager().addRelation(rel)
            return True
        message_utils.MessagebarAndLog.warning(
            bar_msg=QCoreApplication.translate(
                "LoadLayers",
                "Failed to create obs_points_screen relation",
            ),
            log_msg=str(rel.validationError()),
        )
        return False

    def _apply_screens_placeholder(self, obs_points_layer: "QgsVectorLayer") -> None:
        locale_is_swedish = is_locale_swedish()
        config = obs_points_layer.editFormConfig()
        root = config.invisibleRootContainer()
        tab_name = "filter" if locale_is_swedish else "screens"
        for child in root.children():
            if (
                isinstance(child, QgsAttributeEditorContainer)
                and child.name() == tab_name
            ):
                child.clear()
                placeholder = QgsAttributeEditorHtmlElement("", child)
                if locale_is_swedish:
                    html = (
                        "<p><b>Filter (filterrör)</b></p>"
                        "<p>Den här fliken visar filterrörens placering för varje observationspunkt.</p>"
                        "<p>Filter-tabellen saknas i din databas. "
                        "Uppgradera databasen för att aktivera den här funktionen.</p>"
                    )
                else:
                    html = (
                        "<p><b>Screens (filter intervals)</b></p>"
                        "<p>This tab shows the screen/filter intervals for each observation point.</p>"
                        "<p>The screen table is not present in your database. "
                        "Please upgrade your database to enable this feature.</p>"
                    )
                placeholder.setHtmlCode(html)
                child.addChildElement(placeholder)
                break
        obs_points_layer.setEditFormConfig(config)
