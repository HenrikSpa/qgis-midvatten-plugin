import pytest

from midvatten.tools.utils import file_utils


@pytest.mark.active
class TestReadlinesWithDetectedCharset:
    def test_utf8_swedish_chars(self, tmp_path):
        p = tmp_path / "f.csv"
        p.write_bytes("obsid;åäö\nrad2;ÅÄÖ\n".encode())
        rows, encoding = file_utils.readlines_with_detected_charset(
            str(p), ["utf-8", "cp1252"]
        )
        assert rows == ["obsid;åäö\n", "rad2;ÅÄÖ\n"]
        assert encoding == "utf-8"

    def test_cp1252_swedish_chars_fall_through(self, tmp_path):
        p = tmp_path / "f.csv"
        # 'åäö…' in cp1252; the 0xe5 byte ('å') is not valid utf-8 here,
        # forcing fallback to cp1252.
        p.write_bytes("obsid;åäö…\n".encode("cp1252"))
        rows, encoding = file_utils.readlines_with_detected_charset(
            str(p), ["utf-8", "cp1252"]
        )
        assert rows == ["obsid;åäö…\n"]
        assert encoding == "cp1252"

    def test_no_encoding_matches_returns_none(self, tmp_path):
        p = tmp_path / "f.csv"
        p.write_bytes(b"\xff\xfe\x00invalid for both")
        rows, encoding = file_utils.readlines_with_detected_charset(
            str(p), ["utf-8", "ascii"]
        )
        assert rows is None
        assert encoding is None
