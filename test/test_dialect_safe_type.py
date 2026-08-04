import pytest

from midvatten.tools.utils.db_utils.dialect import safe_type, UnsafeIdentifierError


@pytest.mark.parametrize(
    "good",
    [
        "INTEGER",
        "integer",
        "TEXT",
        "REAL",
        "NUMERIC",
        "BLOB",
        "DOUBLE PRECISION",
        "VARCHAR(50)",
        "DECIMAL(10, 2)",
        "TIMESTAMP",
        "DATE",
        "BOOLEAN",
        # Digit-bearing declared types are valid SQLite/PG type names and
        # appear in tables created by external tools (PG dumps, ogr2ogr).
        "FLOAT8",
        "INT2",
        "INT4",
        "INT8",
        "VARCHAR2(30)",
        "NVARCHAR2(50)",
    ],
)
def test_safe_type_allows_real_types(good):
    assert safe_type(good) == good


@pytest.mark.parametrize(
    "evil",
    ["TEXT) OR (SELECT 1) --", "INT; DROP TABLE x", 'a"b', "a'b", "int)--", "", "8FLOAT"],
)
def test_safe_type_rejects_injection(evil):
    with pytest.raises(UnsafeIdentifierError):
        safe_type(evil)
