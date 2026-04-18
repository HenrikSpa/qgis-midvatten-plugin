#! /usr/bin/env python
"""Generate ui_types.py from secplotdockwidget.ui. Run after changing the .ui file."""

import pathlib
import xml.etree.ElementTree as ET

# Widget classes known to not be in QtWidgets — map to a safe fallback type expression.
# "Line" is a QFrame used as a horizontal/vertical separator in Qt Designer.
_CLASS_OVERRIDES: dict[str, str] = {
    "Line": "QtWidgets.QFrame",
}

# Classes that are not in QtWidgets at all — annotate with "object".
_QGIS_OR_CUSTOM_PREFIXES = ("Qgs", "Qg3d", "Qgp")


def _type_expr(cls: str) -> str:
    """Return the annotation expression for a given Qt Designer widget class name."""
    if cls in _CLASS_OVERRIDES:
        return _CLASS_OVERRIDES[cls]
    # QGIS-specific or other third-party widgets
    if any(cls.startswith(p) for p in _QGIS_OR_CUSTOM_PREFIXES):
        return "object"
    return f"QtWidgets.{cls}"


def generate(ui_path: pathlib.Path) -> str:
    tree = ET.parse(ui_path)
    lines = [
        "# AUTO-GENERATED from secplotdockwidget.ui — do not edit manually.",
        "# Regenerate: python tools/sectionplot/generate_ui_types.py",
        "from qgis.PyQt import QtWidgets",
        "",
        "",
        "class SecPlotUi:",
    ]
    seen: set[str] = set()
    for elem in tree.iter("widget"):
        name = elem.get("name")
        cls = elem.get("class")
        if name and cls and name not in seen and name != "SecPlotDock":
            lines.append(f"    {name}: {_type_expr(cls)}")
            seen.add(name)
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    here = pathlib.Path(__file__).parent
    # Find the .ui file — it lives in the ui/ directory two levels up from tools/sectionplot/
    ui_file = here.parent.parent / "ui" / "secplotdockwidget.ui"
    out = here / "ui_types.py"
    out.write_text(generate(ui_file))
    print(f"Written {out}")
