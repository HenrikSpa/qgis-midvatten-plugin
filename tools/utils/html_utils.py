"""Escaping helpers for report HTML written to disk and opened in a browser.

Report values come from user data (including shared PostGIS databases) and are
opened at a file:// origin, so every interpolated value must be escaped.
"""

import html

from midvatten.tools.utils.string_utils import returnunicode


def esc(value) -> str:
    """Return *value* as an HTML-safe string (None -> '')."""
    return html.escape(returnunicode(value), quote=True)
