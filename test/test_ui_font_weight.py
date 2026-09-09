"""Guard against Qt5-scale <weight> values baked into .ui files.

Qt Designer stored QFont weights on the Qt5 0-99 scale (50 = Normal, 75 = Bold).
Qt6 reinterprets the raw integer on the CSS 1-1000 scale (400 = Normal,
700 = Bold, 100 = Thin), so a hardcoded ``<weight>50</weight>`` becomes a
hairline weight. On Linux the usual fallback (DejaVu Sans) has no thin face so
the glyphs snap back to Regular and the bug is invisible; on Windows the
fallback (Segoe UI) has thin faces, so every label renders as a near-invisible
hairline. Removing the ``<weight>`` element lets the widget inherit the normal
application font weight on both toolkits; bold is preserved by ``<bold>true</bold>``.

See docs/GUI_AUTOMATION.md ("Qt6 font weights") for the full story.
"""

from __future__ import annotations

import re
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent / "ui"


def test_no_hardcoded_font_weights_in_ui_files():
    offenders = []
    for ui in sorted(UI_DIR.glob("*.ui")):
        n = len(re.findall(r"<weight>\d+</weight>", ui.read_text(encoding="utf-8")))
        if n:
            offenders.append(f"{ui.name}: {n} hardcoded <weight> element(s)")
    assert not offenders, (
        "Qt5-scale <weight> in .ui files renders as hairline text on Qt6/Windows; "
        "remove the <weight> lines (keep <bold> for bold headers):\n"
        + "\n".join(offenders)
    )
