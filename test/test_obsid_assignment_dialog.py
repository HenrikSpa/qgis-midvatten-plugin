"""Tests for ObsidAssignmentDialog support code."""

import gc

from midvatten.tools.obsid_assignment_dialog import (
    EditorRow,
    ObsidAssignmentDialog,
    group_editor_rows,
)


def _row(lablittera, spec, namn, orsak=""):
    return {
        "lablittera": lablittera,
        "specifik provplats": spec,
        "provplatsnamn": namn,
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
            _row("L1", "Br2", "Brunn 2", orsak="annan"),
            _row("L2", "Br2", "Brunn 2", orsak="annan"),
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
            _row("L3", "Br2", "Brunn 2", orsak="annan"),
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

    def test_provtagningsorsak_dashes_do_not_count_as_override(self):
        """provtagningsorsak uses '-' and '0' as 'no reason' placeholders;
        those should strip to empty and NOT trigger override mode."""
        rows = [
            _row("L1", "Br1", "Brunn 1", orsak="-"),
            _row("L2", "Br1", "Brunn 1", orsak="00"),
        ]
        editor_rows = group_editor_rows(rows)
        # Both rows are clean, should dedupe into one
        assert len(editor_rows) == 1
        assert editor_rows[0].is_override is False
        assert editor_rows[0].lablitteras == ["L1", "L2"]


class TestObsidAssignmentDialogShell:
    def teardown_method(self):
        gc.collect()

    def test_dialog_shows_one_row_per_editor_row(self):
        rows = [
            EditorRow("Br1", "Brunn 1", "", ["L1", "L2"]),
            EditorRow("Br2", "Brunn 2", "", ["L3"]),
        ]
        dialog = ObsidAssignmentDialog(rows, existing_obsids=["Br1", "Br2"])
        try:
            assert dialog.table.rowCount() == 2
            assert dialog.table.item(0, 0).text() == "Br1"
            assert dialog.table.item(0, 1).text() == "Brunn 1"
            assert dialog.table.item(0, 3).text() == "2"  # #lablitteras column
        finally:
            dialog.deleteLater()

    def test_invalid_obsid_paints_cell_red(self):
        rows = [EditorRow("Br1", "Brunn 1", "", ["L1"])]
        dialog = ObsidAssignmentDialog(rows, existing_obsids=["Br1", "Br2"])
        try:
            dialog.set_obsid_value(0, "not_in_obs_points")
            assert dialog.row_has_invalid_obsid(0)
        finally:
            dialog.deleteLater()

    def test_search_filters_rows_by_any_column(self):
        rows = [
            EditorRow("Br1", "Brunn 1", "", ["L1"]),
            EditorRow("Br2", "Brunn 2", "", ["L2"]),
            EditorRow("Br10", "Brunn 10", "", ["L3"]),
        ]
        dialog = ObsidAssignmentDialog(rows, existing_obsids=["Br1", "Br2", "Br10"])
        try:
            dialog.search_input.setText("Br1")
            # Both Br1 and Br10 contain "Br1"
            visible = [
                r
                for r in range(dialog.table.rowCount())
                if not dialog.table.isRowHidden(r)
            ]
            assert len(visible) == 2
            assert dialog.row_count_label.text() == "2 / 3"
        finally:
            dialog.deleteLater()

    def test_matched_rows_hidden_by_default_and_toggleable(self):
        rows = [
            EditorRow("Br1", "Brunn 1", "", ["L1"], obsid="Br1", cached=True),
            EditorRow("Br2", "Brunn 2", "", ["L2"]),
        ]
        dialog = ObsidAssignmentDialog(rows, existing_obsids=["Br1", "Br2"])
        try:
            # Default: matched row hidden
            assert dialog.table.isRowHidden(0) is True
            assert dialog.table.isRowHidden(1) is False
            # Toggle on -> both visible
            dialog.show_matched_checkbox.setChecked(True)
            assert dialog.table.isRowHidden(0) is False
            assert dialog.table.isRowHidden(1) is False
        finally:
            dialog.deleteLater()

    def test_fill_selection_writes_obsid_to_selected_rows(self):
        from qgis.PyQt.QtCore import QItemSelectionModel

        rows = [
            EditorRow("Br1", "Brunn 1", "", ["L1"]),
            EditorRow("Br1", "Brunn 1", "", ["L2"]),
            EditorRow("Br2", "Brunn 2", "", ["L3"]),
        ]
        dialog = ObsidAssignmentDialog(rows, existing_obsids=["Br1", "Br2"])
        try:
            # Select rows 0 and 1 (Rows semantics)
            sel_model = dialog.table.selectionModel()
            sel_model.select(
                dialog.table.model().index(0, 0),
                QItemSelectionModel.Select | QItemSelectionModel.Rows,
            )
            sel_model.select(
                dialog.table.model().index(1, 0),
                QItemSelectionModel.Select | QItemSelectionModel.Rows,
            )
            dialog.fill_combo.setEditText("Br1")
            dialog.fill_selection_button.click()
            assert dialog.editor_rows[0].obsid == "Br1"
            assert dialog.editor_rows[1].obsid == "Br1"
            assert dialog.editor_rows[2].obsid == ""
        finally:
            dialog.deleteLater()
