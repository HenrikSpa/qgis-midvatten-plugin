"""Test that ui_types.py is in sync with secplotdockwidget.ui."""

import pathlib


def test_ui_types_up_to_date():
    """Fail if ui_types.py has drifted from secplotdockwidget.ui."""
    from midvatten.tools.sectionplot.generate_ui_types import generate

    here = pathlib.Path(__file__).parent.parent  # repo root
    ui_file = here / "ui" / "secplotdockwidget.ui"
    ui_types_file = here / "tools" / "sectionplot" / "ui_types.py"
    current = ui_types_file.read_text()
    expected = generate(ui_file)
    assert current == expected, (
        "ui_types.py is stale — run: python tools/sectionplot/generate_ui_types.py"
    )
