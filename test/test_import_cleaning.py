# test/test_import_cleaning.py
"""general_import cleans parameter/unit on their way into w_qual_lab
(spec §6 hook 1). This choke point covers ALL import paths: general CSV,
core interlab4, and interlab4_batch."""
import pandas as pd

from midvatten.tools.import_data_to_db import (
    _as_import_frame, _clean_w_qual_lab_frame)


def test_clean_w_qual_lab_frame():
    frame = pd.DataFrame({
        "obsid": ["o1", "o2"],
        "parameter": ["Bly Pb ", "pH"],
        "unit": [" \u03bcg/l\r\n", None],
        "reading_num": [1.0, 7.5],
    })
    cleaned = _clean_w_qual_lab_frame(frame)
    assert list(cleaned["parameter"]) == ["Bly Pb", "pH"]
    assert cleaned["unit"][0] == "µg/l"
    assert cleaned["unit"][1] is None
    assert frame["parameter"][0] == "Bly Pb "  # input untouched


def test_clean_w_qual_lab_frame_without_unit_column():
    frame = pd.DataFrame({"obsid": ["o1"], "parameter": ["Bly Pb "]})
    assert list(_clean_w_qual_lab_frame(frame)["parameter"]) == ["Bly Pb"]


def test_list_of_lists_roundtrip():
    table = [["obsid", "parameter", "unit"],
             ["o1", "Bly Pb ", "\u03bcg/l"]]
    cleaned = _clean_w_qual_lab_frame(_as_import_frame(table))
    assert cleaned["parameter"][0] == "Bly Pb"
    assert cleaned["unit"][0] == "µg/l"
