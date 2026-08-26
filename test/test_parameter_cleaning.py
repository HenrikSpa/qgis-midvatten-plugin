"""Tests for the mechanical string cleaner (spec 2026-08-26 §5).

The DIRTY/MUST_NOT_TOUCH lists are the reference corpus: extend them,
never trim them.
"""
import pytest

from midvatten.tools.utils.parameter_cleaning import (
    clean_parameter, clean_unit)

DIRTY_TO_CLEAN = [
    ("Bly Pb ", "Bly Pb"),
    (" Kalcium", "Kalcium"),
    ("Konduktivitet\r\n", "Konduktivitet"),
    ("Nitrat-\tkväve", "Nitrat- kväve"),
    ("Bly\u00a0Pb", "Bly Pb"),                # NBSP
    ("Bly\u202fPb", "Bly Pb"),                # narrow NBSP
    ("Bly\u2009Pb", "Bly Pb"),                # thin space
    ("Am\u00admonium", "Ammonium"),           # soft hyphen deleted (D2)
    ("\ufeffpH", "pH"),                        # BOM
    ("Zero\u200bwidth", "Zerowidth"),          # zero-width space
    ("Flera   mellanslag", "Flera mellanslag"),
    ("μg/l", "µg/l"),               # Greek mu -> micro sign (D1)
    ("mg/l \r\n", "mg/l"),
    (" \t ", ""),                              # whitespace-only -> empty
]

MUST_NOT_TOUCH = [
    "Bly, Pb", "pH", "mg/kgTS", "% TS", "mg HCO3/l",
    "PFOS (Perfluoroktansulfonsyra)", "µg/l", "o,p-DDT",
    "Sulfat, SO4", "Turbiditet FNU", "COD-Mn", "1,2-dikloretan",
    "Escherichia coli", "Konduktivitet 25°C",
]


@pytest.mark.parametrize("dirty,expected", DIRTY_TO_CLEAN)
def test_cleans_dirt(dirty, expected):
    assert clean_parameter(dirty) == expected
    assert clean_unit(dirty) == expected


@pytest.mark.parametrize("value", MUST_NOT_TOUCH)
def test_must_not_touch(value):
    assert clean_parameter(value) == value
    assert clean_unit(value) == value


@pytest.mark.parametrize(
    "value", [d for d, _ in DIRTY_TO_CLEAN] + MUST_NOT_TOUCH)
def test_idempotent(value):
    once = clean_parameter(value)
    assert clean_parameter(once) == once


def test_none_passes_through():
    assert clean_parameter(None) is None
    assert clean_unit(None) is None


# --- Floor equivalence (spec §5): Python cleaning is a superset of the
# old SQL view expressions, so applying the old semantics to an
# already-Python-cleaned string is a no-op.

def _old_sql_parameter(value):
    # trim(x, ' ' || char(10) || char(13))
    return value.strip(" \n\r")


def _old_sql_unit(value):
    # COALESCE + collapse space runs + trim(' '||char(10)||char(13))
    value = "" if value is None else value
    while "  " in value:
        value = value.replace("  ", " ")
    return value.strip(" \n\r")


@pytest.mark.parametrize(
    "value", [d for d, _ in DIRTY_TO_CLEAN] + MUST_NOT_TOUCH)
def test_floor_equivalence(value):
    cleaned = clean_parameter(value)
    assert _old_sql_parameter(cleaned) == cleaned
    assert _old_sql_unit(cleaned) == cleaned
