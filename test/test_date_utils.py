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


def test_to_date_partial_dates_fill_first_of_period():
    # Missing month/day become the 1st (as pandas does), never today's date.
    import datetime

    assert date_utils.to_date("2015") == datetime.datetime(2015, 1, 1)
    assert date_utils.to_date("2015-01") == datetime.datetime(2015, 1, 1)
    assert date_utils.to_date("2015-02") == datetime.datetime(2015, 2, 1)
    assert date_utils.to_date("01-2015") == datetime.datetime(2015, 1, 1)
    assert date_utils.normalize_datestring("2015-06") == "2015-06-01"
    assert date_utils.to_YmdHMS("2015") == "2015-01-01 00:00:00"


def test_to_date_partial_dates_independent_of_today():
    # dateutil fills missing fields from "today"; on the 31st that used to
    # clamp "2015-02" to the 28th. The result must not depend on the run date.
    import datetime
    from unittest import mock

    class _FixedDateTime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 1, 31, 15, 30)

        @classmethod
        def today(cls):
            return cls(2026, 1, 31, 15, 30)

    with mock.patch("dateutil.parser._parser.datetime.datetime", _FixedDateTime):
        assert date_utils.to_date("2015-02") == datetime.datetime(2015, 2, 1)
        assert date_utils.to_date("2015") == datetime.datetime(2015, 1, 1)


def test_to_date_rejects_two_digit_years():
    # yy-mm-dd vs dd-mm-yy is ambiguous ("15-01-01" read day-first is 2001-01-15),
    # so a date with a two-digit year is rejected, as before the dateutil refactor.
    import datetime

    for s in ["15-01-01", "15-01-01 12:00", "99-12-31", "03-02-15",
              "15/02/03", "15.02.03", "150101", "15-1-1"]:
        assert date_utils.to_date(s) is None, s
        assert date_utils.normalize_datestring(s) is None, s
    # Four-digit years and full compact dates are unaffected.
    assert date_utils.to_date("2015-01-01") == datetime.datetime(2015, 1, 1)
    assert date_utils.to_date("01-01-2015") == datetime.datetime(2015, 1, 1)
    assert date_utils.to_date("20150101") == datetime.datetime(2015, 1, 1)
    assert date_utils.to_date("2015-01-01 12:00") == datetime.datetime(2015, 1, 1, 12)
