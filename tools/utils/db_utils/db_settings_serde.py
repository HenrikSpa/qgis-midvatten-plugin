"""Serialize/parse the Midvatten db-settings dict to/from its stored string.

The db-settings dict — ``{"spatialite": {"dbpath": ...}}`` or
``{"postgis": {...}}`` — is stored as a string in the QGIS project entry
("Midvatten", "database"). JSON is the current on-disk format:
``json.dumps`` escapes backslashes, so Windows paths (e.g. ``...\\3368...``,
where ``\\336`` would otherwise be read as octal ``Þ``) survive the
round-trip. ``ast.literal_eval`` remains as a read fallback for values
stored before this migration.

Pure stdlib (no qgis) so it is unit-testable headless.
"""
import ast
import json


def db_settings_to_string(db_settings: dict) -> str:
    """Serialize a db-settings dict to its stored string form (JSON)."""
    return json.dumps(db_settings)


def db_settings_string_to_dict(db_settings_string: str) -> dict:
    """Parse a stored db-settings string to a dict.

    JSON first (current format); ast.literal_eval fallback for legacy
    values. Raises ValueError/SyntaxError if neither parses — callers keep
    their existing error handling.
    """
    try:
        return json.loads(db_settings_string)
    except (json.JSONDecodeError, ValueError):
        return ast.literal_eval(db_settings_string)
