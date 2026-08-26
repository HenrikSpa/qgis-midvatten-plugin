# test/test_import_cleaning.py
"""general_import cleans parameter/unit on their way into w_qual_lab
(spec §6 hook 1). This choke point covers ALL import paths: general CSV,
core interlab4, and interlab4_batch."""
from unittest import mock

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


def test_log_cleaned_values_logs_distinct_changes():
    from midvatten.tools import import_data_to_db
    before = pd.DataFrame({
        "parameter": ["Bly Pb ", "Bly Pb ", "pH"],
        "unit": ["mg/l", "mg/l", None],
    })
    after = import_data_to_db._clean_w_qual_lab_frame(before)
    with mock.patch.object(import_data_to_db.message_utils,
                           "MessagebarAndLog") as mal:
        import_data_to_db._log_cleaned_values(before, after)
    assert mal.info.called
    kwargs = mal.info.call_args.kwargs
    assert "bar_msg" not in kwargs
    log_msg = kwargs["log_msg"]
    assert "1" in log_msg                       # one distinct changed value
    assert "'Bly Pb '" in log_msg and "'Bly Pb'" in log_msg


def test_log_cleaned_values_silent_when_nothing_changed():
    from midvatten.tools import import_data_to_db
    before = pd.DataFrame({"parameter": ["pH"], "unit": [None]})
    after = import_data_to_db._clean_w_qual_lab_frame(before)
    with mock.patch.object(import_data_to_db.message_utils,
                           "MessagebarAndLog") as mal:
        import_data_to_db._log_cleaned_values(before, after)
    assert not mal.info.called
