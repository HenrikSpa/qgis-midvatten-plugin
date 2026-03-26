"""
QGIS layer utilities for the Midvatten plugin.
"""

import qgis.utils
from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import QgsMapLayer, QgsProject

from midvatten.tools.utils.exceptions import UsageError
from midvatten.tools.utils.message_utils import MessagebarAndLog, pop_up_info
from midvatten.tools.utils.string_utils import returnunicode, tr


def get_active_layer():
    iface = qgis.utils.iface
    if iface is not None:
        return iface.activeLayer()
    else:
        return False


def find_layer(layer_name: str):
    found_layers = [
        layer
        for name, layer in QgsProject.instance().mapLayers().items()
        if layer.name() == layer_name
    ]

    if len(found_layers) == 0:
        raise UsageError(
            returnunicode(tr("find_layer", "The layer %s was not found!")) % layer_name
        )
    elif len(found_layers) > 1:
        raise UsageError(
            returnunicode(
                tr(
                    "find_layer",
                    'Found %s layers with the name "%s". There can be only one!',
                )
            )
            % (str(len(found_layers)), layer_name)
        )
    else:
        return found_layers[0]


def get_selected_object_names(layer="default", column_name="obsid"):
    """Returns a list of obsid as unicode

    layer is an optional argument, if not given then activelayer is used
    """
    if layer == "default":
        layer = get_active_layer()
    if not layer:
        return []
    selectedobs = layer.selectedFeatures()
    kolumnindex = layer.dataProvider().fieldNameIndex(
        column_name
    )  # OGR data provier is used to find index for column named 'obsid'
    if kolumnindex == -1:
        kolumnindex = layer.dataProvider().fieldNameIndex(
            column_name.upper()
        )  # backwards compatibility
    observations = [
        obs[kolumnindex] for obs in selectedobs
    ]  # value in column obsid is stored as unicode
    return observations


def get_qgis_vector_layers():
    """Return list of all valid QgsVectorLayer in QgsProject"""
    layermap = QgsProject.instance().mapLayers()
    layerlist = []
    for name, layer in layermap.items():
        if layer.isValid() and layer.type() == QgsMapLayer.LayerType.VectorLayer:
            layerlist.append(layer)
    return layerlist


def selection_check(
    layer="", selectedfeatures=0
):  # defaultvalue selectedfeatures=0 is for a check if any features are selected at all, the number is unimportant
    if (
        layer.dataProvider().fieldNameIndex("obsid") > -1
        or layer.dataProvider().fieldNameIndex("OBSID") > -1
    ):  # 'OBSID' to get backwards compatibility
        if selectedfeatures == 0 and layer.selectedFeatureCount() > 0:
            return "ok"
        elif (
            not (selectedfeatures == 0)
            and layer.selectedFeatureCount() == selectedfeatures
        ):
            return "ok"
        elif selectedfeatures == 0 and not (layer.selectedFeatureCount() > 0):
            MessagebarAndLog.critical(
                bar_msg=tr(
                    "selection_check",
                    "Error, select at least one object in the qgis layer!",
                )
            )
        else:
            MessagebarAndLog.critical(
                bar_msg=returnunicode(
                    tr(
                        "selection_check",
                        '"""Error, select exactly %s object in the qgis layer!',
                    )
                )
                % str(selectedfeatures)
            )
    else:
        pop_up_info(
            tr("selection_check", "Select a qgis layer that has a field obsid!")
        )


def strat_selection_check(layer=""):
    if (
        layer.dataProvider().fieldNameIndex("h_gs") > -1
        or layer.dataProvider().fieldNameIndex("h_toc") > -1
        or layer.dataProvider().fieldNameIndex("SURF_LVL") > -1
    ):  # SURF_LVL to enable backwards compatibility
        return "ok"
    else:
        MessagebarAndLog.critical(
            bar_msg=returnunicode(
                tr(
                    "strat_selection_check",
                    "Error, select a qgis layer with field h_gs!",
                )
            )
        )


def get_selected_features_as_tuple(layer_name=None, column_name=None):
    """Returns all selected features from layername

    Returns a tuple of obsids stored as unicode
    """
    if layer_name is not None:
        if isinstance(layer_name, str):
            obs_points_layer = find_layer(layer_name)
        elif isinstance(layer_name, QgsMapLayer):
            obs_points_layer = layer_name
        else:
            MessagebarAndLog.info(
                log_msg=tr(
                    "get_selected_features_as_tuple",
                    'Programming error: The layername "%s" was not str or QgsMapLayer!',
                )
                % str(layer_name)
            )
            obs_points_layer = None

        if obs_points_layer is None:
            return tuple()
        if column_name is not None:
            selected_obs_points = get_selected_object_names(
                layer=obs_points_layer, column_name=column_name
            )
        else:
            selected_obs_points = get_selected_object_names(layer=obs_points_layer)
    else:
        if column_name is not None:
            selected_obs_points = get_selected_object_names(column_name=column_name)
        else:
            selected_obs_points = get_selected_object_names()
    # module midv_exporting depends on obsid being a tuple
    # we cannot send unicode as string to sql because it would include the u' so str() is used
    obsidtuple = tuple([returnunicode(id) for id in selected_obs_points])
    return obsidtuple


def verify_layer_selection(
    current_error_signal: int, required_number_of_selected_features: int = 0
):
    layer = get_active_layer()
    if layer:
        if not (selection_check(layer) == "ok"):
            current_error_signal += 1
            if required_number_of_selected_features == 0:
                MessagebarAndLog.critical(
                    bar_msg=tr(
                        "verify_layer_selection",
                        "Error, you have to select some features!",
                    )
                )
            else:
                MessagebarAndLog.critical(
                    bar_msg=returnunicode(
                        tr(
                            "verify_layer_selection",
                            "Error, you have to select exactly %s features!",
                        )
                    )
                    % str(required_number_of_selected_features)
                )
    else:
        MessagebarAndLog.critical(
            bar_msg=tr(
                "verify_layer_selection", "Error, you have to select a relevant layer!"
            )
        )
        current_error_signal += 1
    return current_error_signal
