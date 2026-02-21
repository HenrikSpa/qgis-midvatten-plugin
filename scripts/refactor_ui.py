#!/usr/bin/env python3
"""
Apply UI widget renames: update .ui files and Python references.
Run from repo root: python scripts/refactor_ui.py
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# Package and UI dirs are at repo root (midvatten is the repository root)
UI_DIR = REPO_ROOT / "ui"

# UI file -> Python files that use it (load the form); paths relative to repo root
UI_TO_PYTHON = {
    "midvsettingsdock.ui": ["midvsettingsdialog.py"],
    "strat_symbology_dialog.ui": ["tools/strat_symbology.py"],
    "secplotdockwidget.ui": ["tools/sectionplot.py"],
    "calibr_logger_dialog_integrated.ui": ["tools/loggereditor.py"],
    "customplotdialog.ui": ["tools/customplot.py"],
    "custom_drillreport.ui": ["tools/custom_drillreport.py"],
    "calc_aveflow_dialog.ui": ["tools/w_flow_calc_aveflow.py"],
    "calc_lvl_dialog.ui": ["tools/calculate_level.py"],
    "calculate_statistics_ui.ui": ["tools/calculate_statistics.py"],
    "compact_w_qual_report.ui": ["tools/wqualreport_compact.py"],
    "import_fieldlogger.ui": [
        "tools/import_fieldlogger.py",
        "tools/import_general_csv_gui.py",
        "tools/import_diveroffice.py",
        "tools/export_fieldlogger.py",
    ],
    "import_interlab4.ui": ["tools/import_interlab4.py"],
    "fieldlogger_parameter_browser.ui": ["tools/export_fieldlogger.py"],
    "selected_features.ui": ["tools/column_values_from_selected_features.py"],
    "not_found_gui.ui": ["tools/utils/common_utils.py"],
}


def camel_to_snake(name: str) -> str:
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    s2 = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()
    return re.sub(r"_+", "_", s2).strip("_")


def is_valid_snake(name: str) -> bool:
    return name == name.lower() and "-" not in name and " " not in name


def get_ui_renames(ui_path: Path) -> list[tuple[str, str]]:
    """Return [(old_name, new_name), ...] for widgets/layouts that need renaming."""
    renames = []
    tree = ET.parse(ui_path)
    for elem in tree.getroot().iter():
        if elem.tag in ("widget", "layout"):
            name = elem.get("name")
            if name and not is_valid_snake(name):
                target = camel_to_snake(name)
                if target != name:
                    renames.append((name, target))
    return renames


def apply_ui_renames(ui_path: Path, renames: list[tuple[str, str]]) -> None:
    """Apply renames to .ui file (widget/layout name= and connections)."""
    path = REPO_ROOT / ui_path
    text = path.read_text()
    for old, new in renames:
        # Widget/layout name attribute
        text = re.sub(rf'\bname="{re.escape(old)}"', f'name="{new}"', text)
        # Connections: sender and receiver
        text = re.sub(
            rf"<sender>{re.escape(old)}</sender>", f"<sender>{new}</sender>", text
        )
        text = re.sub(
            rf"<receiver>{re.escape(old)}</receiver>",
            f"<receiver>{new}</receiver>",
            text,
        )
    path.write_text(text)


def apply_python_renames(py_path: Path, renames: list[tuple[str, str]]) -> None:
    """Apply self.old -> self.new in Python file."""
    path = REPO_ROOT / py_path
    text = path.read_text()
    for old, new in renames:
        # self.oldName -> self.new_name (word boundary to avoid partial matches)
        text = re.sub(rf"\bself\.{re.escape(old)}\b", f"self.{new}", text)
    path.write_text(text)


def main():
    for ui_file in sorted(UI_DIR.glob("*.ui")):
        ui_rel = f"ui/{ui_file.name}"
        renames = get_ui_renames(ui_file)
        if not renames:
            continue
        print(f"Processing {ui_rel}: {len(renames)} renames")
        apply_ui_renames(Path(ui_rel), renames)
        py_files = UI_TO_PYTHON.get(ui_file.name, [])
        for py_rel in py_files:
            py_path = REPO_ROOT / py_rel
            if py_path.exists():
                apply_python_renames(Path(py_rel), renames)
                print(f"  Updated {py_rel}")


if __name__ == "__main__":
    main()
