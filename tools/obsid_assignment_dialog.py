"""Bulk obsid assignment editor for Interlab4 (and reusable elsewhere).

Pure-Python support code for the dialog lives at the top of this module so it
can be imported and unit-tested without requiring a Qt event loop. The
QWidget / QDialog classes live below, after the imports guard.
"""

from __future__ import annotations

from dataclasses import dataclass, field


_OVERRIDE_FIELDS = ("provmärkning", "provtagningsorsak")


@dataclass
class EditorRow:
    """One row in the ObsidAssignmentDialog table.

    Clean rows (no override text) represent a set of lablitteras sharing the
    same (spec_provplats, provplatsnamn). Override rows represent a single
    lablittera with hand-written override text that must be judged per sample.
    """

    specifik_provplats: str
    provplatsnamn: str
    provmärkning: str
    provtagningsorsak: str
    lablitteras: list[str] = field(default_factory=list)
    obsid: str = ""
    cached: bool = False
    is_override: bool = False
    skipped: bool = False


def _has_override(row: dict) -> bool:
    for key in _OVERRIDE_FIELDS:
        value = (row.get(key) or "").strip()
        if key == "provtagningsorsak":
            # Match the existing sanitisation in import_interlab4.py:
            # "-" or "0" placeholders in provtagningsorsak mean "no reason".
            value = value.replace("-", "").replace("0", "").strip()
        if value:
            return True
    return False


def group_editor_rows(
    rows: list[dict],
    cache_matches: dict[tuple[str, str], str] | None = None,
) -> list[EditorRow]:
    """Group raw per-lablittera metadata into EditorRow instances.

    `rows` is a list of dicts with lowercase header keys (lablittera,
    specifik provplats, provplatsnamn, provmärkning?, provtagningsorsak?).
    `cache_matches` maps (spec_provplats, provplatsnamn) -> obsid from
    zz_interlab4_obsid_assignment.
    """
    cache_matches = cache_matches or {}
    clean_groups: dict[tuple[str, str], EditorRow] = {}
    override_rows: list[EditorRow] = []

    for row in rows:
        spec = row.get("specifik provplats", "") or ""
        namn = row.get("provplatsnamn", "") or ""
        mark = row.get("provmärkning", "") or ""
        orsak = row.get("provtagningsorsak", "") or ""
        lablittera = row.get("lablittera", "") or ""
        is_override = _has_override(row)

        if is_override:
            override_rows.append(
                EditorRow(
                    specifik_provplats=spec,
                    provplatsnamn=namn,
                    provmärkning=mark,
                    provtagningsorsak=orsak,
                    lablitteras=[lablittera],
                    is_override=True,
                )
            )
        else:
            key = (spec, namn)
            existing = clean_groups.get(key)
            if existing is None:
                cached_obsid = cache_matches.get(key, "")
                clean_groups[key] = EditorRow(
                    specifik_provplats=spec,
                    provplatsnamn=namn,
                    provmärkning=mark,
                    provtagningsorsak=orsak,
                    lablitteras=[lablittera],
                    obsid=cached_obsid,
                    cached=bool(cached_obsid),
                    is_override=False,
                )
            else:
                existing.lablitteras.append(lablittera)

    return list(clean_groups.values()) + override_rows
