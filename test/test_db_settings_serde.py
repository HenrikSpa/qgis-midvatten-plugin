"""Pure serde tests: no qgis, no database."""
import pytest

from midvatten.tools.utils.db_utils.db_settings_serde import (
    db_settings_to_string,
    db_settings_string_to_dict,
)


def test_windows_path_roundtrips():
    # '\336' in '...\3368...' used to be read as octal escape 'Þ'.
    winpath = r"M:\projekt\3368 x\Arbetsdata\Databas\3368_midv_obsdb.sqlite"
    settings = {"spatialite": {"dbpath": winpath}}
    parsed = db_settings_string_to_dict(db_settings_to_string(settings))
    assert parsed == settings
    assert "Þ" not in parsed["spatialite"]["dbpath"]


def test_linux_path_roundtrips():
    settings = {"spatialite": {"dbpath": "/mnt/server/M_mv/projekt/3368/db.sqlite"}}
    assert db_settings_string_to_dict(db_settings_to_string(settings)) == settings


def test_postgis_roundtrips():
    settings = {"postgis": {"connection": "obsdb_2000/svc:host:5432/db",
                            "schema": "public"}}
    assert db_settings_string_to_dict(db_settings_to_string(settings)) == settings


def test_reads_legacy_ast_string():
    # Value as the old anything_to_string_representation would have written it
    # (double-quoted, forward-slash spatialite path) — must still parse.
    legacy = '{"spatialite": {"dbpath": "/a/b.sqlite"}}'
    assert db_settings_string_to_dict(legacy) == {
        "spatialite": {"dbpath": "/a/b.sqlite"}}


def test_reads_legacy_single_quoted_ast_string():
    # ast fallback path: single quotes are not valid JSON.
    legacy = "{'spatialite': {'dbpath': '/a/b.sqlite'}}"
    assert db_settings_string_to_dict(legacy) == {
        "spatialite": {"dbpath": "/a/b.sqlite"}}


def test_invalid_string_raises():
    with pytest.raises((ValueError, SyntaxError)):
        db_settings_string_to_dict("not a settings string")
