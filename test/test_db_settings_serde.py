"""Serde tests: db_settings_to_string must round-trip through the real
production reader (ast.literal_eval), which is what DbConnectionManager uses."""
import ast
import json

from midvatten.tools.utils.db_utils.db_settings_serde import db_settings_to_string


def _read_back(s):
    # Mirror the production reader: ast.literal_eval decodes the escaped
    # backslashes json.dumps produces.
    return ast.literal_eval(s)


def test_windows_path_survives_real_reader():
    # '\336' in '...\3368...' used to be read as octal escape 'Þ'.
    winpath = r"M:\projekt\3368 x\Arbetsdata\Databas\3368_midv_obsdb.sqlite"
    settings = {"spatialite": {"dbpath": winpath}}
    parsed = _read_back(db_settings_to_string(settings))
    assert parsed == settings
    assert "Þ" not in parsed["spatialite"]["dbpath"]


def test_linux_path_roundtrips():
    settings = {"spatialite": {"dbpath": "/mnt/server/M_mv/projekt/3368/db.sqlite"}}
    assert _read_back(db_settings_to_string(settings)) == settings


def test_postgis_roundtrips():
    settings = {"postgis": {"connection": "obsdb_2000/svc:host:5432/db",
                            "schema": "public"}}
    assert _read_back(db_settings_to_string(settings)) == settings


def test_output_is_json():
    winpath = r"S:\projekt\3368 x\db.sqlite"
    s = db_settings_to_string({"spatialite": {"dbpath": winpath}})
    assert json.loads(s)["spatialite"]["dbpath"] == winpath
