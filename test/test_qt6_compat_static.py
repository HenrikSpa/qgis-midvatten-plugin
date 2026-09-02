"""Static guards for Qt5/Qt6 dual compatibility (no QGIS runtime needed).

These spellings work on PyQt5 but raise AttributeError on PyQt6. The qgis.PyQt
shim does not unscope enums or alias exec_. Scoped spellings work on both.
Source of truth: midv_qt6compat/templates/test_qt6_compat_static.py — edit there.
"""
# qt6compat-template-version: 2
from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {"test", "tests", "docs", "scripts", "_pkgroot", ".venv", "venv", ".claude",
             ".worktrees", "__pycache__", "user_manuals", "dev"}

# Qt enum TYPE names; generated with:
# python3 -c "from qgis.PyQt.QtCore import Qt; print(sorted(n for n in dir(Qt) if isinstance(getattr(Qt, n), type)))"
_QT_ENUM_TYPES = frozenset((
    'Alignment', 'AlignmentFlag', 'AnchorPoint', 'ApplicationAttribute', 'ApplicationState',
    'ApplicationStates', 'ArrowType', 'AspectRatioMode', 'Axis', 'BGMode', 'BrushStyle',
    'CaseSensitivity', 'CheckState', 'ChecksumType', 'ClipOperation', 'ConnectionType',
    'ContextMenuPolicy', 'CoordinateSystem', 'Corner', 'CursorMoveStyle', 'CursorShape',
    'DateFormat', 'DayOfWeek', 'DockWidgetArea', 'DockWidgetAreas', 'DropAction', 'DropActions',
    'Edge', 'Edges', 'EnterKeyType', 'EventPriority', 'FillRule', 'FindChildOption',
    'FindChildOptions', 'FocusPolicy', 'FocusReason', 'GestureFlag', 'GestureFlags',
    'GestureState', 'GestureType', 'GlobalColor', 'HighDpiScaleFactorRoundingPolicy',
    'HitTestAccuracy', 'ImageConversionFlag', 'ImageConversionFlags', 'InputMethodHint',
    'InputMethodHints', 'InputMethodQueries', 'InputMethodQuery', 'ItemDataRole', 'ItemFlag',
    'ItemFlags', 'ItemSelectionMode', 'ItemSelectionOperation', 'Key', 'KeyboardModifier',
    'KeyboardModifiers', 'LayoutDirection', 'MaskMode', 'MatchFlag', 'MatchFlags', 'Modifier',
    'MouseButton', 'MouseButtons', 'MouseEventFlag', 'MouseEventFlags', 'MouseEventSource',
    'NativeGestureType', 'NavigationMode', 'Orientation', 'Orientations', 'PenCapStyle',
    'PenJoinStyle', 'PenStyle', 'ScreenOrientation', 'ScreenOrientations', 'ScrollBarPolicy',
    'ScrollPhase', 'ShortcutContext', 'SizeHint', 'SizeMode', 'SortOrder', 'TabFocusBehavior',
    'TextElideMode', 'TextFlag', 'TextFormat', 'TextInteractionFlag', 'TextInteractionFlags',
    'TileRule', 'TimeSpec', 'TimerType', 'ToolBarArea', 'ToolBarAreas', 'ToolButtonStyle',
    'TouchPointState', 'TouchPointStates', 'TransformationMode', 'UIEffect', 'WhiteSpaceMode',
    'WidgetAttribute', 'WindowFlags', 'WindowFrameSection', 'WindowModality', 'WindowState',
    'WindowStates', 'WindowType',
))

_CLASS_MEMBERS = (
    "Yes|No|Ok|Cancel|Accepted|Rejected|Save|Open|Close|Apply|Discard|Abort|Retry|Ignore|"
    "ResizeToContents|Stretch|Fixed|Interactive|SelectRows|SelectItems|SelectColumns|"
    "ExtendedSelection|SingleSelection|MultiSelection|NoSelection|NoEditTriggers|"
    "DoubleClicked|AllEditTriggers|Expanding|MinimumExpanding|Minimum|Maximum|Preferred|"
    "Bold|StyledPanel|Panel|Box|NoFrame|Sunken|Raised|Antialiasing|RightSide|LeftSide|"
    "AdjustToContents|AdjustToMinimumContentsLengthWithIcon|Password|Question|Information|"
    "Warning|Critical|Landscape|Portrait|VectorLayer|RasterLayer|CreateOrOverwriteFile|"
    "CreateOrOverwriteLayer|NoError"
)
# Deliberately NOT listed: QgsWkbTypes.Point/LineString/Polygon — QGIS aliases those
# itself on Qt6; the deep checker in midv_qt6compat reports them as unresolved-enum instead.

_MASK_TOKEN_TYPES = {tokenize.STRING, tokenize.COMMENT} | {
    getattr(tokenize, n) for n in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END") if hasattr(tokenize, n)
}

FORBIDDEN = {
    "raw PyQt5/PyQt6 import (use qgis.PyQt)": re.compile(r"^\s*(from|import)\s+PyQt[56]\b"),
    "exec_() was removed in PyQt6 (use exec())": re.compile(r"\.exec_\("),
    "unscoped Qt namespace member (use Qt.<EnumType>.<Member>)": re.compile(
        r"\bQt\.[A-Za-z_]\w*\b(?![.(\w])"
    ),
    "unscoped class enum member (use QClass.<EnumType>.<Member>)": re.compile(
        rf"\bQ[A-Za-z]\w*\.({_CLASS_MEMBERS})\b(?![.(\w])"
    ),
    "unscoped QGIS message level (use Qgis.MessageLevel.X)": re.compile(
        r"\bQgis\.(Info|Warning|Critical|Success|NoLevel)\b"
    ),
    "instance-level enum member (use ClassName.EnumType.Member)": re.compile(
        r"\b[a-z_][a-z0-9_]*\.(Accepted|Rejected|Yes|No|Ok|Cancel|Checked|Unchecked)\b"
    ),
    "bare 'import sip' (use from qgis.PyQt import sip)": re.compile(r"^\s*import sip\b"),
}


def _mask_strings_and_comments(text: str) -> list[str]:
    """Tokenize and mask STRING, COMMENT, FSTRING_* tokens with spaces; preserve line/column layout.

    Returns masked lines (with tokens masked to spaces). On tokenize errors, falls back to raw lines
    with comments stripped by the '#' split (since the caller can't tokenize, it uses simple # splitting).
    """
    lines = text.split("\n")
    chars = [list(line) for line in lines]
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return [line.split("#", 1)[0] for line in lines]

    for tok in tokens:
        if tok.type not in _MASK_TOKEN_TYPES:
            continue
        (srow, scol), (erow, ecol) = tok.start, tok.end
        for row in range(srow - 1, erow):
            if row >= len(chars):
                break
            start = scol if row == srow - 1 else 0
            end = ecol if row == erow - 1 else len(chars[row])
            for i in range(start, min(end, len(chars[row]))):
                chars[row][i] = " "
    return ["".join(c) for c in chars]


def _plugin_sources(root: Path) -> tuple[Path, list[str]]:
    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        # Skip if any path component is in SKIP_DIRS or starts with "." (hidden dirs)
        if any(part in SKIP_DIRS or part.startswith(".") for part in rel.parts) or path.is_symlink():
            continue
        yield rel, path.read_text(encoding="utf-8").splitlines()


def collect_hits(root: Path | None = None) -> list[str]:
    """Scan plugin root for Qt6-incompatible patterns. Match against masked lines, report original."""
    if root is None:
        root = PLUGIN_ROOT
    hits = []
    for rel, lines in _plugin_sources(root):
        original_text = "\n".join(lines)
        masked_lines = _mask_strings_and_comments(original_text)

        for lineno, (original_line, masked_line) in enumerate(zip(lines, masked_lines), 1):
            for label, pattern in FORBIDDEN.items():
                matches = list(pattern.finditer(masked_line))
                if not matches:
                    continue
                if "unscoped Qt namespace member" in label:
                    # Qt.X is legal to reference bare when X is a Qt enum TYPE name
                    # (e.g. Qt.GlobalColor). Checked per match, not just the first
                    # Qt. on the line -- a line can mix an allowed type reference
                    # with a genuine unscoped member (e.g. "Qt.ItemDataRole.UserRole,
                    # Qt.Checked"), and only the latter should be a hit.
                    if all(m.group(0).split(".", 1)[1] in _QT_ENUM_TYPES for m in matches):
                        continue
                hits.append(f"{rel}:{lineno}: {label}: {original_line.strip()}")
    return hits


def test_no_qt6_incompatible_patterns():
    hits = collect_hits()
    assert not hits, "\n".join(hits)
