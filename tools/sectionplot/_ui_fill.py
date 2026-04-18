#! /usr/bin/env python
"""
UI population helpers for the SectionPlot dock widget.

These functions fill dynamic combo boxes and list widgets from the database.
They are standalone (no ``self`` references) so they are independently
testable; they receive the UI widget container and the DB connection as
explicit arguments.
"""

import ast
import json

import matplotlib.pyplot as plt
from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import QgsProject

from midvatten.tools.utils import common_utils, db_utils
from midvatten.tools.utils.gui_utils import set_combobox
from midvatten.tools.utils.string_utils import returnunicode as ru


def fill_tem(ui, ms, dbconnection, line_feature=None):
    """Populate TEM-related combo boxes from saved settings and the database.

    Clears and re-populates ``tem_colormap``, ``tem_norm``, ``tem_shading``,
    and ``tem_model_name`` on *ui*, restoring saved selections from *ms*.
    When *line_feature* is provided and the ``tem_data`` table exists in the
    DB the inversion names for that feature are loaded into ``tem_model_name``.
    """
    ui.tem_model_name.clear()
    ui.tem_colormap.clear()
    ui.tem_norm.clear()
    ui.tem_shading.clear()

    ui.tem_colormap.addItems(plt.colormaps())
    ui.tem_norm.addItems(["log", "linear"])
    ui.tem_shading.addItems(["nearest", "gouraud"])

    set_combobox(
        ui.tem_colormap,
        ms.settingsdict.get("secplot_tem_colormap", "jet"),
        add_if_not_exists=False,
    )
    set_combobox(
        ui.tem_norm,
        ms.settingsdict.get("secplot_tem_norm", "log"),
        add_if_not_exists=False,
    )
    set_combobox(
        ui.tem_shading,
        ms.settingsdict.get("secplot_tem_shading", "nearest"),
        add_if_not_exists=False,
    )
    ui.tem_vmin.setText(ms.settingsdict.get("secplot_tem_vmin", ""))
    ui.tem_vmax.setText(ms.settingsdict.get("secplot_tem_vmax", ""))
    ui.tem_snap.setChecked(ms.settingsdict.get("secplot_tem_snap", False))
    ui.tem_rasterized.setChecked(ms.settingsdict.get("secplot_tem_rasterized", False))
    ui.tem_edgecolors.setText(ms.settingsdict.get("secplot_tem_edgecolors", ""))
    ui.tem_alpha_above_doi.setValue(
        float(ms.settingsdict.get("secplot_tem_alpha_above_doi", 1.0))
    )
    ui.tem_alpha_below_doi.setValue(
        float(ms.settingsdict.get("secplot_tem_alpha_below_doi", 0.7))
    )
    ui.tem_data_fit.setChecked(ms.settingsdict.get("secplot_tem_data_fit", False))
    ui.tem_model_name.addItem("")

    if line_feature is None:
        return

    tables = db_utils.get_tables()
    if "tem_data" not in tables:
        ui.tem_model_name.setToolTip(
            QCoreApplication.translate(
                "SectionPlot",
                "Upgrade (export) the database to add the table tem_data.",
            )
        )
        return

    obsid = line_feature.attribute("obsid")
    res = dbconnection.execute_and_fetchall(
        f"SELECT DISTINCT inversion_name FROM tem_data WHERE obsid = {dbconnection.placeholder()}",
        args=(obsid,),
    )
    if res:
        ui.tem_model_name.addItems([x[0] for x in res])

    set_combobox(
        ui.tem_model_name,
        ms.settingsdict.get("secplot_tem_model_name", ""),
        add_if_not_exists=False,
    )


def fill_images(ui, ms, dbconnection, line_feature):
    """Populate the images list widget from saved settings and the database."""
    ui.images_images.clear()
    ui.images_alpha.setText(ms.settingsdict.get("secplot_images_alpha", ""))
    ui.images_zorder.setText(ms.settingsdict.get("secplot_images_zorder", ""))
    ui.images_clip.setChecked(ms.settingsdict.get("secplot_images_clip", True))

    if line_feature is None:
        return

    tables = db_utils.get_tables()
    if "profile_images" not in tables:
        ui.images_images.addItem(
            QCoreApplication.translate(
                "SectionPlot", "Table profile_images missing in database."
            )
        )
        ui.images_images.setToolTip(
            QCoreApplication.translate(
                "SectionPlot",
                "Upgrade (export) the database to add the table profile_images.",
            )
        )
        return

    obsid = line_feature.attribute("obsid")
    res = dbconnection.execute_and_fetchall(
        f"SELECT alias FROM profile_images WHERE obsid = {dbconnection.placeholder()}",
        args=(obsid,),
    )
    if res:
        ui.images_images.addItems([x[0] for x in sorted(res)])

    selected_images = ms.settingsdict.get("secplot_images_images", "[]")
    if selected_images.strip():
        try:
            selected_images = json.loads(selected_images.strip())
        except (json.JSONDecodeError, ValueError):
            selected_images = ast.literal_eval(selected_images.strip())
        for idx in range(ui.images_images.count()):
            item = ui.images_images.item(idx)
            if item.text() in selected_images:
                item.setSelected(True)


def fill_dem_list(ui, ms, line_layer=None):
    """Populate the DEM list widget from QGIS raster layers.

    Returns ``(dem_layers, rasterselection)`` — the dict of name→layer and
    the list of currently selected layer names.
    """
    ui.dem_list.clear()
    if line_layer is None:
        return {}, []

    dem_layers = {}
    line_crs = line_layer.crs()
    msg = []
    layers = [
        QgsProject.instance().mapLayer(_id) for _id in QgsProject.instance().mapLayers()
    ]
    for layer in layers:
        if layer.type() == layer.RasterLayer:
            if layer.bandCount() != 1:
                msg.append(
                    f'Sectionplot: Layer "{ru(layer.name())}" omitted due to more than one layer band.'
                )
            elif layer.crs().authid()[5:] != line_crs.authid()[5:]:
                msg.append(
                    f'Sectionplot: Layer "{ru(layer.name())}" omitted due to wrong CRS'
                    f' ("{line_crs.authid()}" is required, was "{layer.crs().authid()}".'
                )
            else:
                dem_layers[str(layer.name())] = layer
                ui.dem_list.addItem(str(layer.name()))
                item = ui.dem_list.item(ui.dem_list.count() - 1)
                if item.text() in ms.settingsdict["secplotselectedDEMs"]:
                    item.setSelected(True)

    if msg:
        common_utils.MessagebarAndLog.info(
            bar_msg=QCoreApplication.translate(
                "SectionPlot",
                "One or more layers were omitted due to unfulfilled requirements, see log message panel.",
            ),
            log_msg="\n".join(msg),
            duration=30,
        )

    rasterselection = [item.text() for item in ui.dem_list.selectedItems()]
    return dem_layers, rasterselection
