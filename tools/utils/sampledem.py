#! /usr/bin/env python
# -*- coding: utf-8 -*-
"""
/***************************************************************************
 This is where a DEM is sampled along a vector polyline 
                             -------------------
        begin                : 2014-08-22
        copyright            : (C) 2011 by joskal
        email                : groundwatergis [at] gmail.com
 ***************************************************************************/
"""
"""
This code is inspired from the PointSamplingTool plugin Copyright (C) 2008 Borys Jurgiel
and qchainage plugin (C) 2012 by Werner Macho
"""

import traceback
from qgis.PyQt.QtCore import QMetaType
import qgis.PyQt
from qgis.core import (
    QgsFeature,
    QgsField,
    QgsFields,
    QgsProject,
    QgsApplication,
    QgsRaster,
    QgsVectorLayer,
    QgsUnitTypes,
    QgsWkbTypes,
)


def qchain(sectionlinelayer, distance):  # original start function from qchainage
    layer = sectionlinelayer
    layerout = "temporary_memory_layer"
    startpoint = 0
    endpoint = 0
    # selectedOnly = self.selectOnlyRadioBtn.isChecked()

    projection_setting_key = "Projections/defaultBehaviour"
    qgis_settings = qgis.PyQt.QtCore.QSettings()
    old_projection_setting = qgis_settings.value(projection_setting_key)
    qgis_settings.setValue(projection_setting_key, "useGlobal")
    qgis_settings.sync()

    virt_layer, xarray = points_along_line(
        layerout, startpoint, endpoint, distance, layer
    )  # ,
    # selectedOnly)
    qgis_settings.setValue(projection_setting_key, old_projection_setting)

    return virt_layer, xarray


def create_points_at(
    startpoint, endpoint, distance, geom, fid, unit
):  # original function from qchainage
    """Creating Points at coordinates along the line"""
    length = geom.length()
    current_distance = distance
    feats = []

    if endpoint > 0:
        length = endpoint

    # set the first point at startpoint
    point = geom.interpolate(startpoint)

    field_id = QgsField(name="id", type=QMetaType.Type.Int)
    field = QgsField(name="dist", type=QMetaType.Type.Double)
    field2 = QgsField(name="unit", type=QMetaType.Type.QString)
    fields = QgsFields()

    fields.append(field_id)
    fields.append(field)
    fields.append(field2)

    feature = QgsFeature(fields)
    feature["dist"] = startpoint
    feature["id"] = fid
    feature["unit"] = unit

    feature.setGeometry(point)
    feats.append(feature)
    xarray = [feature["dist"]]

    while startpoint + current_distance <= length:
        # Get a point along the line at the current distance
        point = geom.interpolate(startpoint + current_distance)
        # Create a new QgsFeature and assign it the new geometry
        feature = QgsFeature(fields)
        feature["dist"] = startpoint + current_distance
        feature["id"] = fid
        feature["unit"] = unit
        feature.setGeometry(point)
        feats.append(feature)
        xarray.append(feature["dist"])
        # Increase the distance
        current_distance = current_distance + distance

    return feats, xarray


def points_along_line(
    layerout, startpoint, endpoint, distance, layer
):  # ,selected_only=True):#more from qchainage
    """Adding Points along the line"""
    # Create a new memory layer and add a distance attribute self.layerNameLine
    # layer_crs = virt_layer.setCrs(layer.crs())
    virt_layer = QgsVectorLayer(
        "Point?crs=%s&index=yes" % layer.crs().authid(), layerout, "memory"
    )
    provider = virt_layer.dataProvider()
    virt_layer.startEditing()  # actually writes attributes
    units = layer.crs().mapUnits()

    unit_dic = {
        QgsUnitTypes.DistanceUnit.DistanceDegrees: "Degrees",
        QgsUnitTypes.DistanceUnit.DistanceMeters: "Meters",
        QgsUnitTypes.DistanceUnit.DistanceFeet: "Feet",
        QgsUnitTypes.DistanceUnit.DistanceUnknownUnit: "Unknown",
    }
    unit = unit_dic.get(units, "Unknown")
    provider.addAttributes([QgsField("fid", QMetaType.Type.Int)])
    provider.addAttributes([QgsField("cum_dist", QMetaType.Type.Int)])
    provider.addAttributes([QgsField("unit", QMetaType.Type.QString)])

    # Loop through all (selected) features
    for feature in layer.getSelectedFeatures():
        geom = feature.geometry()
        # Add feature ID of selected feature
        fid = feature.id()
        if not geom:
            QgsApplication.messageLog().logMessage("No geometry", "QChainage")
            continue

        features, xarray = create_points_at(
            startpoint, endpoint, distance, geom, fid, unit
        )
        provider.addFeatures(features)
        virt_layer.updateExtents()

    QgsProject.instance().addMapLayers([virt_layer])
    virt_layer.commitChanges()
    virt_layer.reload()
    virt_layer.triggerRepaint()
    return virt_layer, xarray


def sampling(pointsamplinglayer, rastersamplinglayer, bands=1, extract_type="value"):
    point_layer = pointsamplinglayer
    point_provider = point_layer.dataProvider()
    raster_provider = rastersamplinglayer.dataProvider()

    identify_type = {  #'text': QgsRaster.IdentifyFormatText,
        "value": QgsRaster.IdentifyFormat.IdentifyFormatValue,
        "feature": QgsRaster.IdentifyFormat.IdentifyFormatFeature,
    }
    _type = identify_type[extract_type]
    result = []
    for feature in point_provider.getFeatures():
        geom = feature.geometry()

        if geom.wkbType() == QgsWkbTypes.Type.MultiPoint:
            point = geom.asMultiPoint()[0]
        else:
            point = geom.asPoint()

        sample = raster_provider.identify(point, _type).results()
        if sample is None or not sample:
            result.append(None)
            continue

        if extract_type == "value":
            try:
                if isinstance(bands, (list, tuple)):
                    result.append([float(sample[band]) for band in bands])
                else:
                    result.append(float(sample[bands]))
            except:  # point is out of raster extent
                traceback.print_exc()
                result.append(None)
        else:
            result.append(sample[list(sample.keys())[0]])

    return result
