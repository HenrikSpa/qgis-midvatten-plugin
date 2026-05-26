"""
/***************************************************************************
 This part of the Midvatten plugin handles dates.
                             -------------------
        begin                : 2016-03-09
        copyright            : (C) 2016 by HenrikSpa
        email                : groundwatergis [at] gmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import datetime
import logging
import re
from typing import Union

import pandas as pd
import pytz
from dateutil import parser as dateutil_parser
from qgis.PyQt.QtCore import QCoreApplication

from midvatten.tools.utils.string_utils import returnunicode as ru

log = logging.getLogger(__name__)

_YEAR_PREFIX = re.compile(r"\d{4}")


def to_date(
    astring: Union[str, datetime.datetime, datetime.date],
) -> datetime.datetime | None:
    """
    Converts a string or date object to a datetime.

    >>> to_date('2015-01-01')
    datetime.datetime(2015, 1, 1, 0, 0)
    >>> to_date('2015-01-01 12:00')
    datetime.datetime(2015, 1, 1, 12, 0)
    >>> to_date(datetime.datetime(2015, 1, 1, 12, 0))
    datetime.datetime(2015, 1, 1, 12, 0)
    >>> to_date('01-01-2015 01:01:01')
    datetime.datetime(2015, 1, 1, 1, 1, 1)
    >>> to_date('2015/01/01 12:00:00')
    datetime.datetime(2015, 1, 1, 12, 0)
    >>> to_date('20150101')
    datetime.datetime(2015, 1, 1, 0, 0)
    >>> to_date('2010-09-07')
    datetime.datetime(2010, 9, 7, 0, 0)
    >>> to_date('07-09-2010')
    datetime.datetime(2010, 9, 7, 0, 0)
    >>> to_date('abc') is None
    True
    """
    if isinstance(astring, (datetime.datetime, datetime.date)):
        return astring
    try:
        s = str(astring).strip()
        if _YEAR_PREFIX.match(s):
            return dateutil_parser.parse(s, yearfirst=True)
        return dateutil_parser.parse(s, dayfirst=True)
    except (ValueError, TypeError, OverflowError):
        return None


def to_YmdHMS(astring: Union[str, datetime.datetime, datetime.date]) -> str | None:  # noqa: N802
    """
    Converts a date string or object to '%Y-%m-%d %H:%M:%S' format.

    >>> to_YmdHMS('2015-01-01')
    '2015-01-01 00:00:00'
    >>> to_YmdHMS('01-01-2015 01:01:01')
    '2015-01-01 01:01:01'
    >>> to_YmdHMS('abc') is None
    True
    """
    dt = to_date(astring)
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def normalize_datestring(
    astring: Union[str, datetime.datetime, datetime.date],
) -> str | None:
    """
    Normalizes a date string to ISO format, preserving the input's time precision.

    >>> normalize_datestring('2015/01/01')
    '2015-01-01'
    >>> normalize_datestring('01-01-2015 01:01')
    '2015-01-01 01:01'
    >>> normalize_datestring('2015-01-01 01:01:01')
    '2015-01-01 01:01:01'
    >>> normalize_datestring('abc') is None
    True
    """
    dt = to_date(astring)
    if dt is None:
        return None
    s = str(astring).strip()
    if ":" not in s:
        return dt.strftime("%Y-%m-%d")
    if s.count(":") >= 2:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return dt.strftime("%Y-%m-%d %H:%M")


def to_dates(
    strings: list[str], dayfirst: bool = True
) -> list[datetime.datetime | None]:
    """
    Batch-convert date strings to datetimes using pd.to_datetime.

    >>> to_dates(['2015-01-01', '2016-02-03 12:00'])
    [datetime.datetime(2015, 1, 1, 0, 0), datetime.datetime(2016, 2, 3, 12, 0)]
    >>> to_dates(['2015-01-01', 'bad', '2016-01-01'])
    [datetime.datetime(2015, 1, 1, 0, 0), None, datetime.datetime(2016, 1, 1, 0, 0)]
    """
    if not strings:
        return []
    result = pd.to_datetime(strings, format="mixed", dayfirst=dayfirst, errors="coerce")
    return [None if pd.isna(ts) else ts.to_pydatetime() for ts in result]


def dateshift(
    adate: Union[str, datetime.datetime], n: Union[int, float, str], step_lenght: str
) -> datetime.datetime | None:
    """
    Shifts a date n step_lenghts and returns a new date object.

    >>> dateshift('2015-02-01', -5, 'days')
    datetime.datetime(2015, 1, 27, 0, 0)
    >>> dateshift('2016-03-01', -24, 'hours')
    datetime.datetime(2016, 2, 29, 0, 0)
    """
    if isinstance(n, str):
        n = float(n)
    adate = to_date(adate)
    if adate is None:
        return None

    step_lenght = step_lenght.lower()
    if not step_lenght.endswith("s"):
        step_lenght += "s"

    if step_lenght == "microseconds":
        td = datetime.timedelta(microseconds=n)
    elif step_lenght == "milliseconds":
        td = datetime.timedelta(milliseconds=n)
    elif step_lenght == "seconds":
        td = datetime.timedelta(seconds=n)
    elif step_lenght == "minutes":
        td = datetime.timedelta(minutes=n)
    elif step_lenght == "hours":
        td = datetime.timedelta(hours=n)
    elif step_lenght == "days":
        td = datetime.timedelta(days=n)
    elif step_lenght == "weeks":
        td = datetime.timedelta(weeks=n)
    else:
        return None
    new_date = adate + td
    return new_date


def date_to_epoch(astring: Union[str, datetime.datetime]) -> datetime.timedelta:
    return to_date(astring) - datetime.datetime(1970, 1, 1)


def parse_timezone_to_timedelta(tz_string: str) -> datetime.timedelta:
    """

    :param tz_string:
    :return:

    >>> parse_timezone_to_timedelta('GMT+02:00')
    datetime.timedelta(seconds=7200)
    >>> parse_timezone_to_timedelta('GMT')
    datetime.timedelta(0)
    >>> parse_timezone_to_timedelta('GMT00:00')
    datetime.timedelta(0)
    >>> parse_timezone_to_timedelta('GMT-11:00')
    datetime.timedelta(days=-1, seconds=46800)
    >>> parse_timezone_to_timedelta('GMT+14:00')
    datetime.timedelta(seconds=50400)
    >>> parse_timezone_to_timedelta('GMT+2')
    datetime.timedelta(seconds=7200)
    >>> parse_timezone_to_timedelta('GMT+02:35')
    datetime.timedelta(seconds=9300)
    >>> parse_timezone_to_timedelta('UTC+02:00')
    datetime.timedelta(seconds=7200)
    >>> parse_timezone_to_timedelta('UTC')
    datetime.timedelta(0)
    >>> parse_timezone_to_timedelta('UTC00:00')
    datetime.timedelta(0)
    >>> parse_timezone_to_timedelta('UTC-11:00')
    datetime.timedelta(days=-1, seconds=46800)
    >>> parse_timezone_to_timedelta('UTC+14:00')
    datetime.timedelta(seconds=50400)
    >>> parse_timezone_to_timedelta('UTC+2')
    datetime.timedelta(seconds=7200)
    >>> parse_timezone_to_timedelta('UTC+02:35')
    datetime.timedelta(seconds=9300)
    >>> parse_timezone_to_timedelta('01234 UTC+02:35')
    datetime.timedelta(seconds=9300)
    >>> parse_timezone_to_timedelta('01234\tUTC+02:35')
    datetime.timedelta(seconds=9300)
    >>> parse_timezone_to_timedelta('-227495\tUTC+02:35')
    datetime.timedelta(seconds=9300)
    """
    _tz_string = ru(tz_string).lower()
    match = re.match(
        r"[\-a-zA-Z0-9\ \t]*(gmt|utc)([\+\-]*)([0-9]+)([\:]*[0-9]*)",
        _tz_string,
        re.IGNORECASE,
    )
    if match is None:
        if not _tz_string.replace("gmt", "").replace("utc", ""):
            res = ("", "", "", "")
        else:
            raise ValueError(
                QCoreApplication.translate(
                    "parse_timezone_to_timedelta",
                    "Timezone string %s could not be parsed!",
                )
                % tz_string
            )
    else:
        res = match.groups()
    if res[1] == "-":
        sign = -1
    else:
        sign = 1
    hours = int(res[2]) * sign if res[2] else 0
    minutes = int(res[3].lstrip(":")) * sign if res[3].lstrip(":") else 0
    td = datetime.timedelta(hours=hours, minutes=minutes)
    return td


def change_timezone(
    date_or_string: Union[str, datetime.datetime], from_timezone: str, to_timezone: str
) -> datetime.datetime:
    """
    Converts a datetime between timezones. Always returns a naive datetime.

    >>> change_timezone('2022-03-27 00:00', 'Europe/Stockholm', 'UTC+1')
    datetime.datetime(2022, 3, 27, 0, 0)
    >>> change_timezone('2022-03-28 00:00', 'Europe/Stockholm', 'UTC+1')
    datetime.datetime(2022, 3, 27, 23, 0)
    >>> change_timezone('2022-03-27 23:00', 'UTC+1', 'Europe/Stockholm')
    datetime.datetime(2022, 3, 28, 0, 0)
    >>> change_timezone('2022-10-30 00:00', 'Europe/Stockholm', 'UTC+1')
    datetime.datetime(2022, 10, 29, 23, 0)
    >>> change_timezone('2022-10-31 00:00', 'Europe/Stockholm', 'UTC+1')
    datetime.datetime(2022, 10, 31, 0, 0)
    """

    def get_tz_and_timedelta(tz_string):
        if tz_string.lower().startswith("utc"):
            new_tz = pytz.utc
            timedelta = parse_timezone_to_timedelta(tz_string)
        else:
            new_tz = pytz.timezone(tz_string)
            timedelta = None
        return new_tz, timedelta

    tz_naive = to_date(date_or_string)

    tz, td = get_tz_and_timedelta(from_timezone)
    try:
        tz_aware = tz.localize(tz_naive, is_dst=None)
    except AttributeError:
        raise Exception(
            f"Error changing timezone for '{date_or_string}', returned '{tz_naive}'."
        )
    if td:
        tz_aware = tz_aware - td

    new_tz, new_td = get_tz_and_timedelta(to_timezone)
    new_date = tz_aware.astimezone(new_tz)
    if new_td is not None:
        new_date = new_date + new_td

    return new_date.replace(tzinfo=None)


def get_pytz_timezones() -> list[str]:
    return pytz.all_timezones
