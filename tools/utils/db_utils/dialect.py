"""
Shared SQL identifier and literal safety. Used by both SQLite and PostgreSQL backends.
"""

import re
from typing import Any, Optional, Protocol
from collections.abc import Iterable, Sequence


class HasPlaceholderString(Protocol):
    def placeholder(self, count: int) -> str: ...


_IDENT_PART_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class UnsafeIdentifierError(ValueError):
    """Raised when an identifier is not safe for interpolation into SQL."""

    pass


def _split_qualified_identifier(name: str) -> list[str]:
    if not isinstance(name, str) or not name.strip():
        raise UnsafeIdentifierError(
            f"Identifier must be a non-empty string, got {name!r}"
        )
    if any(ch in name for ch in ['"', "'", ";", "\\", "\n", "\r", "\t"]):
        raise UnsafeIdentifierError(
            f"Identifier contained forbidden characters: {name!r}"
        )
    parts = [p for p in name.split(".") if p]
    if not parts:
        raise UnsafeIdentifierError(f"Identifier had no parts: {name!r}")
    for part in parts:
        if not _IDENT_PART_RE.match(part):
            raise UnsafeIdentifierError(f"Unsafe identifier part {part!r} in {name!r}")
    return parts


def ident(
    name: str,
    *,
    allowed: Optional[Iterable[str]] = None,
) -> str:
    """Safely quote/compose an SQL identifier.

    Identifiers cannot be bound via DB-API parameters, so we validate + quote.
    Works the same for SQLite and PostgreSQL (double quotes).
    """
    if allowed is not None and name not in set(allowed):
        raise UnsafeIdentifierError(f"Identifier {name!r} was not in allowed list")
    parts = _split_qualified_identifier(name)
    return ".".join([f'"{p}"' for p in parts])


def quote_ident(name: str) -> str:
    """Quote a single SQL identifier by escaping, allowing any printable character.

    Unlike :func:`ident`, this does NOT restrict the character set, so it is
    safe for user-supplied names that may legitimately contain non-ASCII
    characters (e.g. Swedish å/ä/ö in imported file headers). It also does NOT
    split on ``.`` — a name containing a dot is treated as a single identifier.
    NUL and other control characters are rejected.

    Use this only for names that cannot be validated against an allowed list
    (e.g. arbitrary import-file column headers). For schema-controlled names,
    prefer :func:`ident`.
    """
    if not isinstance(name, str) or not name.strip():
        raise UnsafeIdentifierError(
            f"Identifier must be a non-empty string, got {name!r}"
        )
    if any(ch in name for ch in ("\x00", "\n", "\r", "\t")):
        raise UnsafeIdentifierError(
            f"Identifier contained forbidden control characters: {name!r}"
        )
    return '"' + name.replace('"', '""') + '"'


def sql_ident(template: str, /, **identifiers: str) -> str:
    """Format a template where substitutions are IDENTIFIERS ONLY.

    Values must still be passed using DB-API parameters.
    """
    fmt = {k: ident(v) for k, v in identifiers.items()}
    return template.format(**fmt)


def in_clause(
    backend: HasPlaceholderString, values: Sequence[Any]
) -> tuple[str, list[Any]]:
    """Return (clause_sql, args) for use as: ... IN {clause_sql}.

    Empty sequences become (NULL) which yields no matches in IN expressions.
    """
    if values is None:
        raise ValueError("values must not be None")
    values_list = list(values)
    if not values_list:
        return "(NULL)", []
    placeholders = backend.placeholders(len(values_list))
    return f"({placeholders})", values_list


def sql_literal(value: Any) -> str:
    """Safely embed a literal value into SQL text (last resort).

    Prefer DB-API parameters whenever possible.
    """
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if "\x00" in text:
        raise ValueError("NUL byte not allowed in SQL literal")
    return "'" + text.replace("'", "''") + "'"


def sql_literal_list(values: Sequence[Any]) -> str:
    return ", ".join([sql_literal(v) for v in values])
