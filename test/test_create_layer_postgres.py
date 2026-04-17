"""Verify that create_layer sets estimatedmetadata=false on PostgreSQL URIs."""

from unittest import mock

from midvatten.tools.utils import midvatten_utils


def test_estimatedmetadata_false_set_for_postgres():
    dbconnection = mock.MagicMock()
    dbconnection.dbtype = "postgis"
    dbconnection.uri = mock.MagicMock()
    dbconnection.schemas.return_value = "public"

    with (
        mock.patch.object(midvatten_utils, "db_utils") as db_utils_mock,
        mock.patch.object(midvatten_utils, "QgsVectorLayer"),
    ):
        db_utils_mock.DbConnectionManager = type(dbconnection)
        db_utils_mock.get_dbtype.return_value = "postgres"

        midvatten_utils.create_layer("obs_points", dbconnection=dbconnection)

    dbconnection.uri.setParam.assert_called_with("estimatedmetadata", "false")


def test_estimatedmetadata_not_set_for_spatialite():
    dbconnection = mock.MagicMock()
    dbconnection.dbtype = "spatialite"
    dbconnection.uri = mock.MagicMock()
    dbconnection.schemas.return_value = ""

    with (
        mock.patch.object(midvatten_utils, "db_utils") as db_utils_mock,
        mock.patch.object(midvatten_utils, "QgsVectorLayer"),
    ):
        db_utils_mock.DbConnectionManager = type(dbconnection)
        db_utils_mock.get_dbtype.return_value = "spatialite"

        midvatten_utils.create_layer("obs_points", dbconnection=dbconnection)

    set_param_calls = [
        call
        for call in dbconnection.uri.setParam.call_args_list
        if call.args and call.args[0] == "estimatedmetadata"
    ]
    assert set_param_calls == []
