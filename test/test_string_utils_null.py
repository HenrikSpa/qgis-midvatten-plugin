"""
Regression guard for QGIS NULL handling in
midvatten.tools.utils.string_utils.returnunicode.

The `isNull()` branch is the project's documented #1 regression risk: a
prior incident lost it during a refactor, causing QGIS NULL sentinels to
be stringified as "NULL" instead of being converted to the empty string.
These tests lock the behaviour in so a future refactor that drops the
branch fails fast.
"""

from unittest import mock

from midvatten.tools.utils.string_utils import returnunicode


class _FakeNull:
    """Minimal stand-in for a QGIS NULL / QVariant-null-like object.

    Keeping the check version-independent: we only rely on the duck-typed
    `isNull()` contract that `returnunicode` uses.
    """

    def isNull(self) -> bool:  # noqa: N802 - mirrors Qt's camelCase API
        return True


@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_returnunicode_python_none_returns_empty_string(mock_messagebar):
    print(f"{mock_messagebar.mock_calls=}")
    assert returnunicode(None) == ""


@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_returnunicode_qgis_null_returns_empty_string(mock_messagebar):
    from qgis.core import NULL

    print(f"{mock_messagebar.mock_calls=}")
    assert returnunicode(NULL) == ""


@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
def test_returnunicode_fake_object_with_isnull_true_returns_empty(mock_messagebar):
    print(f"{mock_messagebar.mock_calls=}")
    assert returnunicode(_FakeNull()) == ""
