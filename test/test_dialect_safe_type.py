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
    ],
)
def test_safe_type_allows_real_types(good):
    assert safe_type(good) == good


@pytest.mark.parametrize(
    "evil",
    ["TEXT) OR (SELECT 1) --", "INT; DROP TABLE x", 'a"b', "a'b", "int)--", ""],
)
def test_safe_type_rejects_injection(evil):
    with pytest.raises(UnsafeIdentifierError):
        safe_type(evil)
