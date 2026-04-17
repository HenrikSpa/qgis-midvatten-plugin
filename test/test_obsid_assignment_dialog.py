"""Tests for ObsidAssignmentDialog support code."""

from midvatten.tools.obsid_assignment_dialog import (
    EditorRow,
    group_editor_rows,
)


def _row(lablittera, spec, namn, mark="", orsak=""):
    return {
        "lablittera": lablittera,
        "specifik provplats": spec,
        "provplatsnamn": namn,
        "provmärkning": mark,
        "provtagningsorsak": orsak,
    }


class TestGroupEditorRows:
    def test_clean_rows_dedupe_by_pair(self):
        rows = [
            _row("L1", "Br1", "Brunn 1"),
            _row("L2", "Br1", "Brunn 1"),
            _row("L3", "Br2", "Brunn 2"),
        ]
        editor_rows = group_editor_rows(rows)
        assert len(editor_rows) == 2
        br1 = next(r for r in editor_rows if r.specifik_provplats == "Br1")
        assert br1.lablitteras == ["L1", "L2"]
        assert br1.is_override is False

    def test_override_rows_are_not_deduped(self):
        rows = [
            _row("L1", "Br2", "Brunn 2", mark="egentl. Br3"),
            _row("L2", "Br2", "Brunn 2", mark="egentl. Br3"),
        ]
        editor_rows = group_editor_rows(rows)
        assert len(editor_rows) == 2
        assert all(r.is_override for r in editor_rows)
        assert [r.lablitteras for r in editor_rows] == [["L1"], ["L2"]]

    def test_provtagningsorsak_also_triggers_override(self):
        rows = [
            _row("L1", "Br1", "Brunn 1", orsak="annan"),
        ]
        editor_rows = group_editor_rows(rows)
        assert editor_rows[0].is_override is True

    def test_mixed_clean_and_override(self):
        rows = [
            _row("L1", "Br1", "Brunn 1"),
            _row("L2", "Br1", "Brunn 1"),
            _row("L3", "Br2", "Brunn 2", mark="egentl. Br3"),
        ]
        editor_rows = group_editor_rows(rows)
        clean = [r for r in editor_rows if not r.is_override]
        override = [r for r in editor_rows if r.is_override]
        assert len(clean) == 1 and clean[0].lablitteras == ["L1", "L2"]
        assert len(override) == 1 and override[0].lablitteras == ["L3"]

    def test_prefill_from_cache(self):
        rows = [_row("L1", "Br1", "Brunn 1")]
        cache = {("Br1", "Brunn 1"): "Br1"}
        editor_rows = group_editor_rows(rows, cache_matches=cache)
        assert editor_rows[0].obsid == "Br1"
        assert editor_rows[0].cached is True
