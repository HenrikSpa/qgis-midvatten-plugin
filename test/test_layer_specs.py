"""Unit tests for midvatten.tools.utils.layer_specs."""

from midvatten.tools.utils.layer_specs import (
    GROUPS,
    GroupSpec,
    LayerGroupName,
    LayerSpec,
)


class TestLayerSpec:
    def test_defaults(self):
        spec = LayerSpec("obs_points")
        assert spec.tablename == "obs_points"
        assert spec.display_name is None
        assert spec.geometry_column is None
        assert spec.initially_visible is True

    def test_name_falls_back_to_tablename(self):
        assert LayerSpec("screen").name == "screen"

    def test_name_uses_display_name_when_set(self):
        assert LayerSpec("screen", display_name="Observations").name == "Observations"

    def test_initially_visible_can_be_overridden(self):
        assert (
            LayerSpec("w_lvls_last_geom", initially_visible=False).initially_visible
            is False
        )


class TestGroupSpec:
    def test_all_three_groups_registered(self):
        assert set(GROUPS) == set(LayerGroupName)

    def test_each_group_is_a_group_spec(self):
        for name, group in GROUPS.items():
            assert isinstance(group, GroupSpec)
            assert group.name == name
            assert group.position_index in (0, 1)
            assert callable(group.resolve_layers)

    def test_obs_db_is_at_position_zero(self):
        assert GROUPS[LayerGroupName.OBS_DB].position_index == 0

    def test_other_groups_at_position_one(self):
        assert GROUPS[LayerGroupName.DATA_DOMAINS].position_index == 1
        assert GROUPS[LayerGroupName.DATA_TABLES].position_index == 1


class TestLayerGroupName:
    def test_string_values_stable(self):
        # These strings are externally-visible layer-tree group names;
        # breaking them would change user-facing behaviour.
        assert LayerGroupName.OBS_DB.value == "Midvatten_OBS_DB"
        assert LayerGroupName.DATA_DOMAINS.value == "Midvatten_data_domains"
        assert LayerGroupName.DATA_TABLES.value == "Midvatten_data_tables"

    def test_str_mixin_equality(self):
        # str mixin means the enum compares equal to its value and works
        # as a dict key equivalently to the raw string.
        assert LayerGroupName.OBS_DB == "Midvatten_OBS_DB"
        assert GROUPS["Midvatten_OBS_DB"] is GROUPS[LayerGroupName.OBS_DB]


class TestDefinedLayerLists:
    def test_obs_db_contains_obs_points_as_spatial(self):
        from midvatten.definitions.midvatten_defs import OBS_DB_LAYERS

        obs_points = next(s for s in OBS_DB_LAYERS if s.tablename == "obs_points")
        assert obs_points.geometry_column == "geometry"

    def test_obs_db_contains_non_spatial_entries(self):
        from midvatten.definitions.midvatten_defs import OBS_DB_LAYERS

        screen = next(s for s in OBS_DB_LAYERS if s.tablename == "screen")
        assert screen.geometry_column is None

    def test_w_lvls_last_geom_is_initially_invisible(self):
        from midvatten.definitions.midvatten_defs import OBS_DB_LAYERS

        layer = next(s for s in OBS_DB_LAYERS if s.tablename == "w_lvls_last_geom")
        assert layer.initially_visible is False

    def test_obs_p_w_lvl_logger_is_initially_invisible(self):
        from midvatten.definitions.midvatten_defs import OBS_DB_LAYERS

        layer = next(s for s in OBS_DB_LAYERS if s.tablename == "obs_p_w_lvl_logger")
        assert layer.initially_visible is False

    def test_data_tables_entries_are_non_spatial(self):
        from midvatten.definitions.midvatten_defs import DATA_TABLES_LAYERS

        assert all(s.geometry_column is None for s in DATA_TABLES_LAYERS)
