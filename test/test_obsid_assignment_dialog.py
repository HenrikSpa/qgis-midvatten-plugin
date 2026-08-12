"""Tests for ObsidAssignmentDialog support code."""

import gc

from qgis.PyQt.QtCore import Qt

from midvatten.tools.obsid_assignment_dialog import (
    EditorRow,
    ObsidAssignmentDialog,
    apply_session_draft,
    collect_drafted_obsids,
    group_editor_rows,
    merge_session_draft,
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


class TestApplySessionDraft:
    def test_fills_override_row(self):
        rows = group_editor_rows([_row("L9", "Sp", "Namn", orsak="annan")])
        apply_session_draft(rows, {"L9": "Rb17"}, set())
        assert rows[0].obsid == "Rb17"
        assert rows[0].drafted is True

    def test_marks_skipped(self):
        rows = group_editor_rows([_row("L9", "Sp", "Namn", orsak="annan")])
        apply_session_draft(rows, {}, {"L9"})
        assert rows[0].skipped is True

    def test_leaves_undrafted_row_untouched(self):
        rows = group_editor_rows([_row("L1", "Br1", "Brunn 1")])
        apply_session_draft(rows, {"OTHER": "X"}, set())
        assert rows[0].obsid == ""
        assert rows[0].drafted is False

    def test_first_match_wins_for_clean_group(self):
        rows = group_editor_rows(
            [_row("L1", "Br1", "Brunn 1"), _row("L2", "Br1", "Brunn 1")]
        )
        apply_session_draft(rows, {"L1": "Br1", "L2": "Br1"}, set())
        assert len(rows) == 1
        assert rows[0].obsid == "Br1"
        assert rows[0].drafted is True


class TestMergeSessionDraft:
    def test_records_fills_and_skips(self):
        draft, skipped_set = {}, set()
        merge_session_draft(draft, skipped_set, {"L1", "L2"}, {"L1": "Br1"}, {"L2"})
        assert draft == {"L1": "Br1"}
        assert skipped_set == {"L2"}

    def test_drops_cleared_shown_lablittera(self):
        draft, skipped_set = {"L1": "Br1"}, set()
        # L1 is shown again but now empty (user cleared it) -> forget it.
        merge_session_draft(draft, skipped_set, {"L1"}, {}, set())
        assert draft == {}

    def test_leaves_unshown_lablitteras_untouched(self):
        draft, skipped_set = {"L9": "Old"}, set()
        merge_session_draft(draft, skipped_set, {"L1"}, {"L1": "Br1"}, set())
        assert draft == {"L9": "Old", "L1": "Br1"}

    def test_fill_overrides_previous_skip(self):
        draft, skipped_set = {}, {"L1"}
        merge_session_draft(draft, skipped_set, {"L1"}, {"L1": "Br1"}, set())
        assert draft == {"L1": "Br1"}
        assert skipped_set == set()


class TestCollectDraftedObsids:
    def test_includes_user_touched_rows(self):
        rows = group_editor_rows([_row("L1", "Br1", "Brunn 1")])
        rows[0].obsid = "Br1"
        rows[0].drafted = True
        assert collect_drafted_obsids(rows) == {"L1": "Br1"}

    def test_excludes_untouched_cached_rows(self):
        # Auto-matched from the durable cache: has obsid, but drafted stays False.
        rows = group_editor_rows(
            [_row("L1", "Br1", "Brunn 1")],
            cache_matches={("Br1", "Brunn 1"): "Br1"},
        )
        assert rows[0].cached is True and rows[0].drafted is False
        assert collect_drafted_obsids(rows) == {}

    def test_excludes_skipped_rows(self):
        rows = group_editor_rows([_row("L1", "Br1", "Brunn 1")])
        rows[0].obsid = "Br1"
        rows[0].drafted = True
        rows[0].skipped = True
        assert collect_drafted_obsids(rows) == {}


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

    def test_drafted_row_visible_even_when_cached(self):
        rows = [
            EditorRow(
                "Br1", "Brunn 1", "", ["L1"], obsid="Br1", cached=True, drafted=True
            ),
            EditorRow("Br2", "Brunn 2", "", ["L2"], obsid="Br2", cached=True),
        ]
        dialog = ObsidAssignmentDialog(rows, existing_obsids=["Br1", "Br2"])
        try:
            # Row 0 was typed this session -> visible despite being cached.
            assert dialog.table.isRowHidden(0) is False
            # Row 1 is only auto-matched from the durable table -> stays hidden.
            assert dialog.table.isRowHidden(1) is True
        finally:
            dialog.deleteLater()

    def test_restored_skipped_row_is_rendered_noneditable(self):
        rows = [EditorRow("Br1", "Brunn 1", "", ["L1"], skipped=True)]
        dialog = ObsidAssignmentDialog(rows, existing_obsids=["Br1"])
        try:
            from midvatten.tools.obsid_assignment_dialog import _COL_OBSID

            item = dialog.table.item(0, _COL_OBSID)
            assert item.text() == "[skipped]"
            assert not (item.flags() & Qt.ItemIsEditable)
        finally:
            dialog.deleteLater()

    def test_fill_selection_marks_row_drafted(self):
        from qgis.PyQt.QtCore import QItemSelectionModel

        rows = [EditorRow("Br1", "Brunn 1", "", ["L1"])]
        dialog = ObsidAssignmentDialog(rows, existing_obsids=["Br1"])
        try:
            sel = dialog.table.selectionModel()
            sel.select(
                dialog.table.model().index(0, 0),
                QItemSelectionModel.Select | QItemSelectionModel.Rows,
            )
            dialog.fill_combo.setEditText("Br1")
            dialog.fill_selection_button.click()
            assert dialog.editor_rows[0].drafted is True
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

    def test_skip_and_unskip_selected_rows(self):
        rows = [EditorRow("Br1", "Brunn 1", "", ["L1"])]
        dialog = ObsidAssignmentDialog(rows, existing_obsids=["Br1"])
        try:
            dialog.table.selectRow(0)
            dialog.skip_selection_button.click()
            assert dialog.editor_rows[0].skipped is True
            assert dialog.table.item(0, 4).text() == "[skipped]"
            dialog.unskip_selection_button.click()
            assert dialog.editor_rows[0].skipped is False
        finally:
            dialog.deleteLater()

    def test_reload_obsids_refreshes_completer(self):
        rows = [EditorRow("Br1", "Brunn 1", "", ["L1"])]
        dialog = ObsidAssignmentDialog(
            rows,
            existing_obsids=["Br1"],
            reload_callback=lambda: ["Br1", "Br2", "BrNEW"],
        )
        try:
            dialog.reload_obsids_button.click()
            assert "BrNEW" in dialog.existing_obsids
            assert dialog.fill_combo.findText("BrNEW") >= 0
        finally:
            dialog.deleteLater()

    def test_save_draft_produces_expected_result(self):
        from midvatten.tools.obsid_assignment_dialog import DialogOutcome

        rows = [EditorRow("Br1", "Brunn 1", "", ["L1"], obsid="Br1")]
        dialog = ObsidAssignmentDialog(rows, existing_obsids=["Br1"])
        try:
            dialog.save_draft_button.click()
            assert dialog.outcome == DialogOutcome.SAVE_DRAFT
        finally:
            dialog.deleteLater()

    def test_apply_produces_expected_result(self):
        from midvatten.tools.obsid_assignment_dialog import DialogOutcome

        rows = [EditorRow("Br1", "Brunn 1", "", ["L1"], obsid="Br1")]
        dialog = ObsidAssignmentDialog(rows, existing_obsids=["Br1"])
        try:
            dialog.apply_button.click()
            assert dialog.outcome == DialogOutcome.APPLY
        finally:
            dialog.deleteLater()

    def test_apply_blocked_on_invalid_obsid(self, monkeypatch):
        rows = [EditorRow("Br1", "Brunn 1", "", ["L1"])]
        dialog = ObsidAssignmentDialog(rows, existing_obsids=["Br1"])
        try:
            dialog.set_obsid_value(0, "not_a_real_obsid")
            warnings = []
            monkeypatch.setattr(
                dialog, "_warn_invalid_obsid", lambda: warnings.append(1)
            )
            dialog.apply_button.click()
            assert dialog.outcome is None
            assert warnings == [1]
        finally:
            dialog.deleteLater()

    def test_fill_after_sort_writes_to_correct_editor_row(self):
        """After the user clicks a header to sort, the visual row index no
        longer matches editor_rows. Filling an obsid cell must update the
        EditorRow that is actually shown at the visual row, not the list
        element at that index."""
        from qgis.PyQt.QtCore import Qt

        rows = [
            EditorRow("Br1", "Brunn 1", "", ["L1"]),
            EditorRow("Br2", "Brunn 2", "", ["L2"]),
            EditorRow("Br3", "Brunn 3", "", ["L3"]),
        ]
        dialog = ObsidAssignmentDialog(rows, existing_obsids=["Br1", "Br2", "Br3"])
        try:
            # Sort spec_provplats descending: visual order becomes Br3, Br2, Br1
            dialog.table.sortByColumn(0, Qt.DescendingOrder)
            # Top visual row is now the EditorRow originally at index 2 (Br3).
            dialog.set_obsid_value(0, "Br3")
            assert dialog.editor_rows[2].obsid == "Br3"
            assert dialog.editor_rows[0].obsid == ""
            assert dialog.editor_rows[1].obsid == ""
        finally:
            dialog.deleteLater()


def test_ask_obsid_rows_as_dicts_handles_lowercase_headers():
    from midvatten.tools.obsid_assignment_dialog import ask_obsid_rows_as_dicts

    ask_obsid_table = [
        ["Lablittera", "Specifik Provplats", "Provplatsnamn", "Provtagningsorsak"],
        ["L1", "Br1", "Brunn 1", ""],
        ["L2", "Br1", "Brunn 1", "egentl. Br3"],
    ]
    rows = ask_obsid_rows_as_dicts(ask_obsid_table)
    assert rows[0]["lablittera"] == "L1"
    assert rows[0]["specifik provplats"] == "Br1"
    assert rows[1]["provtagningsorsak"] == "egentl. Br3"


def test_fan_out_filled_rows_into_lablittera_map():
    from midvatten.tools.obsid_assignment_dialog import (
        EditorRow,
        fan_out_filled_rows,
    )

    rows = [
        EditorRow("Br1", "Brunn 1", "", ["L1", "L2"], obsid="Br1"),
        EditorRow("Br2", "Brunn 2", "", ["L3"], skipped=True),
        EditorRow(
            "Br3", "Brunn 3", "egentl. Br3", ["L4"], obsid="Br3", is_override=True
        ),
        EditorRow("Br4", "Brunn 4", "", ["L5"]),  # unfilled
    ]
    filled, skipped, cache_rows = fan_out_filled_rows(rows)
    assert filled == {"L1": "Br1", "L2": "Br1", "L4": "Br3"}
    assert skipped == {"L3"}
    # Override row is not added to cache_rows
    assert cache_rows == [("Br1", "Brunn 1", "Br1")]
