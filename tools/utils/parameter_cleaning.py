"""Mechanical cleaning of lab parameter/unit strings.

The single source of truth for what "mechanically clean" means — used by
general_import (all w_qual_lab import paths), and via the midv_addons
re-export by the interlab4 writer, the parameter_name_sync harvest, and
the in-place cleaning tool. Pure stdlib, no qgis/pandas imports:
importable headless.

Spec: midv_addons
docs/superpowers/specs/2026-08-26-lab-string-cleaning-design.md §5.
Cleaning removes characters that carry no meaning. It never translates,
never changes case, never repairs mojibake (spec §3).
"""
from __future__ import annotations

import re

# Whitespace-class characters that become a plain space: ASCII control
# whitespace + Unicode space variants seen in lab/Excel exports.
_TO_SPACE = "\r\n\t\f\v\u00a0\u202f\u2007" + "".join(
    chr(c) for c in range(0x2000, 0x200B))
# Invisible characters deleted outright: zero-widths, BOM, soft hyphen.
_TO_DELETE = "\u200b\u200c\u200d\ufeff\u00ad"

_TRANSLATION = {ord(c): " " for c in _TO_SPACE}
_TRANSLATION.update({ord(c): None for c in _TO_DELETE})
_TRANSLATION[0x03BC] = "µ"  # Greek small mu -> micro sign (D1)

_MULTISPACE = re.compile(" {2,}")


def clean_parameter(value: str | None) -> str | None:
    if value is None:
        return None
    return _MULTISPACE.sub(" ", value.translate(_TRANSLATION)).strip(" ")


def clean_unit(value: str | None) -> str | None:
    # Same transform as clean_parameter by design (spec §5); separate
    # name so call sites document intent and the two may diverge later.
    return clean_parameter(value)
