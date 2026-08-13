"""Tests for the headless module-level helpers extracted from Interlab4Import."""
import pytest

from midvatten.test import utils_for_tests
from midvatten.tools import import_interlab4
from midvatten.tools.utils import db_utils


def test_build_ask_obsid_table_header_and_sorted_rows():
    parsed = {
        "L2": {"metadata": {"lablittera": "L2", "provplatsnamn": "PN",
                            "specifik provplats": "SP"}},
        "L1": {"metadata": {"lablittera": "L1", "provplatsnamn": "PN",
                            "specifik provplats": "SP"}},
    }
    table = import_interlab4.build_ask_obsid_table(parsed)
    header = [str(h).strip().lower() for h in table[0]]
    lab_idx = header.index("lablittera")
    assert len(table) == 3
    assert [row[lab_idx] for row in table[1:]] == ["L1", "L2"]


def test_module_constants():
    assert import_interlab4.OBSID_ASSIGNMENT_TABLE == "zz_interlab4_obsid_assignment"
    assert import_interlab4.OBSID_CONNECTION_COLUMNS == (
        "specifik provplats", "provplatsnamn")


@pytest.mark.spatialite
class TestDbHelpers(utils_for_tests.MidvattenTestSpatialiteDbSv):

    def test_get_imported_reports(self):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('o1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_qual_lab (obsid, report, parameter, reading_txt) "
            "VALUES ('o1', 'R1', 'pH', '7')")
        assert import_interlab4.get_imported_reports("w_qual_lab") == {"R1"}

    def test_get_imported_reports_empty(self):
        assert import_interlab4.get_imported_reports("w_qual_lab") == set()

    def test_get_imported_reports_rejects_unknown_table(self):
        with pytest.raises(Exception):
            import_interlab4.get_imported_reports("obs_points; DROP TABLE x")

    def test_cache_roundtrip(self):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('o1')")
        import_interlab4.insert_obsid_assignment_rows([("SP", "PN", "o1")])
        assert import_interlab4.load_obsid_assignment_cache() == {
            ("SP", "PN"): "o1"}

    def test_insert_conflict_keeps_first_answer(self):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('o1')")
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('o2')")
        import_interlab4.insert_obsid_assignment_rows([("SP", "PN", "o1")])
        # Re-answering the same pair must not raise and must keep the first.
        import_interlab4.insert_obsid_assignment_rows([("SP", "PN", "o2")])
        assert import_interlab4.load_obsid_assignment_cache() == {
            ("SP", "PN"): "o1"}

    def test_insert_empty_rows_is_noop(self):
        import_interlab4.insert_obsid_assignment_rows([])
        assert import_interlab4.load_obsid_assignment_cache() == {}
