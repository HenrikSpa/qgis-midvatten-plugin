import pytest
from unittest import mock

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


@pytest.mark.active
class TestGetDelimiterRows:
    def test_rows_param_skips_file_read(self):
        delimiter = file_utils.get_delimiter(
            filename="not_opened.csv",
            rows=["a;b;c;d;e\n", "1;2;3;4;5\n"],
            delimiters=[";", ","],
            num_fields=5,
        )
        assert delimiter == ";"

    def test_tolerant_detection_uses_complete_rows(self):
        delimiter = file_utils.get_delimiter_from_file_rows(
            [
                "2023/10/05 13:00:00;9.470\n",
                "2023/10/05 14:00:00;978.667;12.110\n",
            ],
            delimiters=[";", ","],
            num_fields=3,
            allow_ragged_rows=True,
        )
        assert delimiter == ";"


@pytest.mark.active
class TestWritePrintlistToFile:
    def test_notifies_by_default(self, tmp_path):
        path = tmp_path / "default.csv"
        with mock.patch(
            "midvatten.tools.utils.file_utils.message_utils.MessagebarAndLog"
        ) as messagebar:
            file_utils.write_printlist_to_file(str(path), [["a", "b"]])

        messagebar.info.assert_called_once()
        assert "default.csv" in messagebar.info.call_args.kwargs["bar_msg"]

    def test_notification_can_be_suppressed(self, tmp_path):
        path = tmp_path / "silent.csv"
        with mock.patch(
            "midvatten.tools.utils.file_utils.message_utils.MessagebarAndLog"
        ) as messagebar:
            file_utils.write_printlist_to_file(str(path), [["a", "b"]], notify=False)

        messagebar.info.assert_not_called()

    def test_non_authorized_write_cannot_replace_existing_file(self, tmp_path):
        path = tmp_path / "protected.csv"
        path.write_text("original", encoding="utf-8")

        with pytest.raises(FileExistsError):
            file_utils.write_printlist_to_file(
                str(path), [["replacement"]], notify=False, overwrite=False
            )

        assert path.read_text(encoding="utf-8") == "original"

    def test_authorized_write_replaces_existing_file(self, tmp_path):
        path = tmp_path / "replace.csv"
        path.write_text("original", encoding="utf-8")

        file_utils.write_printlist_to_file(
            str(path), [["replacement"]], notify=False, overwrite=True
        )

        assert path.read_text(encoding="utf-8") == "replacement\n"
