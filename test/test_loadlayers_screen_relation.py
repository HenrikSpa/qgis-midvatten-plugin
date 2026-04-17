#! /usr/bin/env python
"""
Tests for obs_points ↔ screen QgsRelation registration in LoadLayers.

Covers:
  - After load_layers() the relationManager holds a relation with id
    'obs_points_screen', correct layer references, and correct field pair.
  - When the screen table is absent (older DB), no relation is registered
    and no exception is raised.
"""

from unittest import mock

import pytest
from qgis.core import QgsProject

from midvatten.test import utils_for_tests
from midvatten.tools import loadlayers
from midvatten.tools.utils import db_utils


class LoadLayersScreenRelationMixin:
    """Tests for QgsRelation 'obs_points_screen' registration."""

    def _call_load_layers(self):
        """Invoke LoadLayers for the OBS_DB group using a mocked iface."""
        with mock.patch(
            "midvatten.tools.utils.common_utils.MessagebarAndLog"
        ) as mock_messagebar:
            ll = loadlayers.LoadLayers(self.iface, self.midvatten.ms.settingsdict)
        return ll, mock_messagebar

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_relation_registered_after_load(self, mock_messagebar):
        """relationManager contains 'obs_points_screen' after LoadLayers."""
        loadlayers.LoadLayers(self.iface, self.midvatten.ms.settingsdict)

        print(f"{mock_messagebar.mock_calls=}")

        relations = QgsProject.instance().relationManager().relations()
        assert "obs_points_screen" in relations, (
            f"Expected 'obs_points_screen' in relations, got: {list(relations.keys())}"
        )

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_relation_referenced_layer_is_obs_points(self, mock_messagebar):
        """The relation's referenced layer is obs_points."""
        loadlayers.LoadLayers(self.iface, self.midvatten.ms.settingsdict)

        print(f"{mock_messagebar.mock_calls=}")

        rel = QgsProject.instance().relationManager().relations()["obs_points_screen"]
        assert rel.referencedLayer().name() == "obs_points"

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_relation_referencing_layer_is_screen(self, mock_messagebar):
        """The relation's referencing layer is screen."""
        loadlayers.LoadLayers(self.iface, self.midvatten.ms.settingsdict)

        print(f"{mock_messagebar.mock_calls=}")

        rel = QgsProject.instance().relationManager().relations()["obs_points_screen"]
        assert rel.referencingLayer().name() == "screen"

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_relation_field_pair(self, mock_messagebar):
        """The relation links obsid (referenced) → obsid (referencing)."""
        loadlayers.LoadLayers(self.iface, self.midvatten.ms.settingsdict)

        print(f"{mock_messagebar.mock_calls=}")

        rel = QgsProject.instance().relationManager().relations()["obs_points_screen"]
        field_pairs = rel.fieldPairs()
        # fieldPairs() returns {referencing_field: referenced_field}
        assert field_pairs == {"obsid": "obsid"}

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_no_relation_when_screen_table_absent(self, mock_messagebar):
        """No relation is registered and no exception raised when screen table absent."""
        # Drop the screen table to simulate an older DB without the feature.
        dbconnection = db_utils.DbConnectionManager()
        try:
            dbconnection.execute("DROP TABLE IF EXISTS screen")
            dbconnection.commit()
        finally:
            dbconnection.closedb()

        loadlayers.LoadLayers(self.iface, self.midvatten.ms.settingsdict)

        print(f"{mock_messagebar.mock_calls=}")

        relations = QgsProject.instance().relationManager().relations()
        assert "obs_points_screen" not in relations
        assert not mock_messagebar.critical.called


# ---------------------------------------------------------------------------
# Concrete test class (spatialite only)
# ---------------------------------------------------------------------------


@pytest.mark.spatialite
class TestLoadLayersScreenRelationSpatialite(
    LoadLayersScreenRelationMixin,
    utils_for_tests.MidvattenTestSpatialiteDbEn,
):
    pass
