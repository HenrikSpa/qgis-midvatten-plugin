"""Serialize the Midvatten db-settings dict to its stored string form.

The db-settings dict — ``{"spatialite": {"dbpath": ...}}`` or
``{"postgis": {...}}`` — is stored as a string in the QGIS project entry
("Midvatten", "database"). ``json.dumps`` escapes backslashes, so Windows
paths (e.g. ``...\\3368...``, where ``\\336`` would otherwise be read back
as octal ``Þ``) survive the round-trip. Readers use ``ast.literal_eval``,
which decodes ``json.dumps`` output (escaped backslashes) correctly, so no
reader change is needed.

Pure stdlib (no qgis) so it is unit-testable headless.
"""
import json


def db_settings_to_string(db_settings: dict) -> str:
    """Serialize a db-settings dict to its stored string form (JSON)."""
    return json.dumps(db_settings)
