from midvatten.tools.utils import date_utils


def test_instant_key():
    # Same instant -> same key (so 00:00 and 00:00:00 dedup); different second -> different key.
    assert date_utils.instant_key("2015-01-01 00:00") == date_utils.instant_key(
        "2015-01-01 00:00:00"
    )
    assert date_utils.instant_key("2015-01-01 00:00") != date_utils.instant_key(
        "2015-01-01 00:00:01"
    )
    # date-only normalizes to start-of-day instant (matches SQLite datetime())
    assert date_utils.instant_key("2015-06-01") == date_utils.instant_key(
        "2015-06-01 00:00:00"
    )
    # unparseable / empty -> None (escapes uniqueness, like datetime()->NULL)
    assert date_utils.instant_key("garbage") is None
    assert date_utils.instant_key(None) is None
    assert date_utils.instant_key("") is None
