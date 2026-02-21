#!/usr/bin/env python3
"""
Audit script for coding style refactoring.
Produces rename lists for constants, classes, UI, functions, variables.
Run from repo root: python scripts/style_audit.py
"""

import ast
import re
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# Package and UI dirs are at repo root (midvatten is the repository root)
MIDVATTEN = REPO_ROOT
UI_DIR = REPO_ROOT / "ui"


def camel_to_snake(name: str) -> str:
    """Convert CamelCase/camelCase to snake_case."""
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    s2 = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()
    return re.sub(r"_+", "_", s2).strip("_")  # collapse multiple underscores


def is_valid_snake(name: str) -> bool:
    """Check if name is already valid snake_case."""
    return name == name.lower() and "-" not in name and " " not in name


def is_valid_capwords(name: str) -> bool:
    """Check if name is valid CapWords (class names)."""
    if not name or name[0].islower():
        return False
    return all(c.isalnum() or c == "_" for c in name)


def audit_ui_files():
    """Parse .ui files and extract widget/layout object names that need renaming.
    Only <widget> and <layout> elements have objectName (name attr); <property> uses name for property name.
    """
    results = []
    for ui_file in UI_DIR.glob("*.ui"):
        try:
            tree = ET.parse(ui_file)
            root = tree.getroot()
            for elem in root.iter():
                if elem.tag in ("widget", "layout"):
                    name = elem.get("name")
                    if name and not is_valid_snake(name):
                        target = camel_to_snake(name)
                        if target != name:
                            results.append(
                                (str(ui_file.relative_to(REPO_ROOT)), name, target)
                            )
        except ET.ParseError as e:
            results.append((str(ui_file), f"PARSE_ERROR: {e}", ""))
    return results


def _find_parent_class(tree: ast.AST, target_node: ast.AST) -> bool:
    """Return True if target_node is nested inside a ClassDef."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.Module)):
            for child in getattr(node, "body", []):
                if child is target_node:
                    return isinstance(node, ast.ClassDef)
                if _find_parent_class(ast.Module(body=[child]), target_node):
                    return isinstance(node, ast.ClassDef)
    return False


def audit_python_files():
    """Use AST to find classes, functions, methods."""
    classes = []
    functions = []
    methods = []

    for py_file in MIDVATTEN.rglob("*.py"):
        if ".venv" in str(py_file):
            continue
        try:
            rel = py_file.relative_to(REPO_ROOT)
            with open(py_file) as f:
                tree = ast.parse(f.read())

            def visit(node, in_class=False):
                if isinstance(node, ast.ClassDef):
                    if not is_valid_capwords(node.name) and not node.name.startswith(
                        "_"
                    ):
                        target = "".join(w.capitalize() for w in node.name.split("_"))
                        classes.append((str(rel), node.lineno, node.name, target))
                    for child in node.body:
                        visit(child, in_class=True)
                elif isinstance(node, ast.FunctionDef):
                    if not is_valid_snake(node.name) and not node.name.startswith("_"):
                        target = camel_to_snake(node.name)
                        if target != node.name:
                            if in_class:
                                methods.append(
                                    (str(rel), node.lineno, node.name, target)
                                )
                            else:
                                functions.append(
                                    (str(rel), node.lineno, node.name, target)
                                )
                    for child in node.body:
                        visit(child, in_class)
                elif hasattr(node, "body"):
                    for child in node.body:
                        visit(child, in_class)

            for child in tree.body:
                visit(child)
        except (SyntaxError, OSError):
            pass
    return classes, functions, methods


def main():
    print("=== UI widget names to rename ===\n")
    for ui_path, old, new in audit_ui_files():
        if new:
            print(f"  {ui_path}: {old!r} -> {new!r}")

    print("\n=== Classes to rename (CapWords) ===\n")
    classes, functions, methods = audit_python_files()
    for path, line, old, new in classes:
        print(f"  {path}:{line}: {old!r} -> {new!r}")

    print("\n=== Functions to rename (snake_case) ===\n")
    for path, line, old, new in functions[:50]:  # Limit output
        print(f"  {path}:{line}: {old!r} -> {new!r}")
    if len(functions) > 50:
        print(f"  ... and {len(functions) - 50} more")

    print("\n=== Methods to rename (snake_case) ===\n")
    for path, line, old, new in methods[:80]:
        print(f"  {path}:{line}: {old!r} -> {new!r}")
    if len(methods) > 80:
        print(f"  ... and {len(methods) - 80} more")


if __name__ == "__main__":
    main()
