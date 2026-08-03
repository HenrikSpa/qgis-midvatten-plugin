from midvatten.tools.utils.html_utils import esc


def test_esc_neutralizes_script():
    assert esc("<script>alert(1)</script>") == (
        "&lt;script&gt;alert(1)&lt;/script&gt;"
    )


def test_esc_escapes_quotes_and_amp():
    assert esc('a & "b" <c>') == "a &amp; &quot;b&quot; &lt;c&gt;"


def test_esc_handles_none():
    assert esc(None) == ""
