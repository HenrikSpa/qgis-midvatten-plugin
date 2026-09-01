"""Static guards for Qt5/Qt6 dual compatibility.

These patterns work on PyQt5 but raise AttributeError on PyQt6 (see the QGIS
wiki "Plugin migration to be compatible with Qt5 and Qt6"). No QGIS runtime is
needed; the test scans the shipped plugin sources once and checks every pattern.
"""

import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {
    "test",
    "docs",
    "scripts",
    "_pkgroot",
    ".venv",
    ".claude",
    ".worktrees",
    ".logger-import-worktree",
    "__pycache__",
}

FORBIDDEN = {
    "unscoped QGIS message level (use Qgis.MessageLevel.X)": re.compile(
        r"\bQgis\.(Info|Warning|Critical|Success|NoLevel)\b"
    ),
    "exec_() was removed in PyQt6 (use exec())": re.compile(r"\.exec_\("),
    "unscoped enum on an instance (use QDialog.DialogCode.X etc.)": re.compile(
        r"\b[a-z_][a-z0-9_]*\.(Accepted|Rejected|Yes|No|Ok|Cancel|Checked|Unchecked)\b"
    ),
}


def _plugin_sources():
    for path in PLUGIN_ROOT.rglob("*.py"):
        rel = path.relative_to(PLUGIN_ROOT)
        if rel.parts[0] in SKIP_DIRS or path.name == "resources.py":
            continue
        yield rel, path.read_text(encoding="utf-8").splitlines()


def test_no_qt6_incompatible_patterns():
    hits = []
    for rel, lines in _plugin_sources():
        for lineno, line in enumerate(lines, 1):
            code = line.split("#", 1)[0]
            for label, pattern in FORBIDDEN.items():
                if pattern.search(code):
                    hits.append(f"{rel}:{lineno}: {label}: {line.strip()}")
    assert not hits, "\n".join(hits)
