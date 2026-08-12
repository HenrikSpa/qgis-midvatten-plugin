# Interlab4 obsid session-draft restore — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make "Save draft && close" in the Interlab4 obsid-assignment dialog remember exactly what the user typed — for all rows including override rows — and restore it visibly on the next "Start import" within the same import-window session.

**Architecture:** Add a per-window, in-memory draft (`lablittera -> obsid` plus a skipped set) on the `Interlab4Import` instance. A new `EditorRow.drafted` flag makes restored rows render as normal visible/editable rows even when they also live in the durable `zz_interlab4_obsid_assignment` cache. Two pure helpers (`apply_session_draft`, `merge_session_draft`) do restore and capture; `start_import` calls them. No DB or project-file writes for the draft; the durable-cache code path is unchanged.

**Tech Stack:** Python 3, PyQt5/QGIS, pytest. Backend-agnostic (no SQL touched).

## Global Constraints

- Use `python3`, not `python`.
- Full design/spec: `docs/superpowers/specs/2026-08-12-interlab4-obsid-session-draft-design.md`.
- Never change DB schemas. This plan touches **no** SQL and does **not** modify `_insert_cache_rows` or `_load_obsid_assignment_cache`.
- Imports must be module-level (PEP 8) and from specific source modules.
- After Python edits run `ruff check --fix .` and `ruff format .`.
- Mock `MessagebarAndLog` in tests via `@mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")` with param name `mock_messagebar`.
- Do not change existing test reference data.
- Run the touched test files between tasks; do not run the full suite until the end (it takes ~33-43 min).
- Commit after each task.

## File Structure

- `tools/obsid_assignment_dialog.py` — add `EditorRow.drafted` field; add pure functions `apply_session_draft` and `merge_session_draft`; make greying/hiding skip drafted rows.
- `tools/import_interlab4.py` — add the two instance draft containers in `__init__`; import and call the two new helpers in `start_import`.
- `test/test_obsid_assignment_dialog.py` — unit tests for the field/display and the two pure functions.
- `test/test_import_interlab4.py` — one integration test driving two `start_import` cycles.

---

### Task 1: `EditorRow.drafted` field + drafted rows render visibly

**Files:**
- Modify: `tools/obsid_assignment_dialog.py` (dataclass `EditorRow` ~line 39-55; `_populate_table` ~line 309; `_apply_filters` ~line 356)
- Test: `test/test_obsid_assignment_dialog.py`

**Interfaces:**
- Produces: `EditorRow` gains `drafted: bool = False` (appended after `skipped`, so all existing positional/keyword constructions stay valid). Display rule everywhere becomes: a row is greyed/hidden only when `cached and not drafted`.

- [ ] **Step 1: Write the failing test**

Add to the `class` that holds `test_matched_rows_hidden_by_default_and_toggleable` in `test/test_obsid_assignment_dialog.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest test/test_obsid_assignment_dialog.py::TestObsidAssignmentDialog::test_drafted_row_visible_even_when_cached -x`
(If the class name differs, target the file: `python3 -m pytest test/test_obsid_assignment_dialog.py -k drafted -x`.)
Expected: FAIL — `EditorRow.__init__() got an unexpected keyword argument 'drafted'`.

- [ ] **Step 3: Add the field**

In `tools/obsid_assignment_dialog.py`, in the `EditorRow` dataclass, after the existing `skipped: bool = False` line, add:

```python
    drafted: bool = False
```

- [ ] **Step 4: Make greying skip drafted rows**

In `_populate_table`, change the greying guard:

```python
                if row.cached and not row.drafted:
```
(was `if row.cached:`)

- [ ] **Step 5: Make hiding skip drafted rows**

In `_apply_filters`, change the hide guard:

```python
            if not show_matched and row.cached and not row.drafted:
```
(was `if not show_matched and row.cached:`)

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m pytest test/test_obsid_assignment_dialog.py -x`
Expected: PASS (new test plus all existing dialog tests).

- [ ] **Step 7: Lint and commit**

```bash
ruff check --fix . && ruff format .
git add tools/obsid_assignment_dialog.py test/test_obsid_assignment_dialog.py
git commit -m "feat(interlab4): EditorRow.drafted flag renders restored rows visibly"
```

---

### Task 2: `apply_session_draft` pure function (restore)

**Files:**
- Modify: `tools/obsid_assignment_dialog.py` (add function near `fan_out_filled_rows`, ~line 155)
- Test: `test/test_obsid_assignment_dialog.py`

**Interfaces:**
- Consumes: `EditorRow` (with `drafted` from Task 1), `group_editor_rows`.
- Produces: `apply_session_draft(editor_rows: list[EditorRow], draft: dict[str, str], skipped: set[str]) -> None` — mutates rows in place. For each row: if any lablittera is in `skipped`, set `row.skipped = True`; else if any lablittera is in `draft`, set `row.obsid` to the first match and `row.drafted = True`.

- [ ] **Step 1: Write the failing tests**

Add a new test class to `test/test_obsid_assignment_dialog.py` (import updated below):

```python
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
```

Update the import at the top of the test file to include the new name:

```python
from midvatten.tools.obsid_assignment_dialog import (
    EditorRow,
    ObsidAssignmentDialog,
    apply_session_draft,
    group_editor_rows,
)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest test/test_obsid_assignment_dialog.py::TestApplySessionDraft -x`
Expected: FAIL — `ImportError: cannot import name 'apply_session_draft'`.

- [ ] **Step 3: Implement the function**

In `tools/obsid_assignment_dialog.py`, immediately after `fan_out_filled_rows`, add:

```python
def apply_session_draft(
    editor_rows: list[EditorRow],
    draft: dict[str, str],
    skipped: set[str],
) -> None:
    """Overlay a per-lablittera session draft onto freshly grouped rows.

    Restores exactly what the user typed this session. For each row: if any of
    its lablitteras was skipped, mark it skipped; else if any was filled, set the
    obsid to the first matching draft value and flag it `drafted` (so it renders
    as a normal visible row even when it is also in the durable cache).
    """
    for row in editor_rows:
        if any(lab in skipped for lab in row.lablitteras):
            row.skipped = True
            continue
        for lab in row.lablitteras:
            if lab in draft:
                row.obsid = draft[lab]
                row.drafted = True
                break
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest test/test_obsid_assignment_dialog.py::TestApplySessionDraft -x`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check --fix . && ruff format .
git add tools/obsid_assignment_dialog.py test/test_obsid_assignment_dialog.py
git commit -m "feat(interlab4): apply_session_draft restores typed obsids onto rows"
```

---

### Task 3: `merge_session_draft` pure function (capture)

**Files:**
- Modify: `tools/obsid_assignment_dialog.py` (add function after `apply_session_draft`)
- Test: `test/test_obsid_assignment_dialog.py`

**Interfaces:**
- Produces: `merge_session_draft(draft: dict[str, str], skipped_set: set[str], shown_lablitteras: set[str], filled: dict[str, str], skipped: set[str]) -> None` — mutates `draft` and `skipped_set` to mirror the dialog's current state for exactly the lablitteras shown this round. Fills recorded, skips recorded, cleared values dropped; lablitteras not in `shown_lablitteras` are left untouched.

- [ ] **Step 1: Write the failing tests**

Add a new test class to `test/test_obsid_assignment_dialog.py`:

```python
class TestMergeSessionDraft:
    def test_records_fills_and_skips(self):
        draft, skipped_set = {}, set()
        merge_session_draft(
            draft, skipped_set, {"L1", "L2"}, {"L1": "Br1"}, {"L2"}
        )
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
```

Update the test-file import to add `merge_session_draft`:

```python
from midvatten.tools.obsid_assignment_dialog import (
    EditorRow,
    ObsidAssignmentDialog,
    apply_session_draft,
    group_editor_rows,
    merge_session_draft,
)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest test/test_obsid_assignment_dialog.py::TestMergeSessionDraft -x`
Expected: FAIL — `ImportError: cannot import name 'merge_session_draft'`.

- [ ] **Step 3: Implement the function**

In `tools/obsid_assignment_dialog.py`, immediately after `apply_session_draft`, add:

```python
def merge_session_draft(
    draft: dict[str, str],
    skipped_set: set[str],
    shown_lablitteras: set[str],
    filled: dict[str, str],
    skipped: set[str],
) -> None:
    """Mirror the dialog's current state into the session draft.

    Only the lablitteras shown this round are reconciled, so a value the user
    cleared before saving is forgotten rather than resurrected, while
    lablitteras filtered out this round (e.g. already-imported reports) keep
    their earlier draft state.
    """
    for lab in shown_lablitteras:
        if lab in filled:
            draft[lab] = filled[lab]
            skipped_set.discard(lab)
        elif lab in skipped:
            skipped_set.add(lab)
            draft.pop(lab, None)
        else:
            draft.pop(lab, None)
            skipped_set.discard(lab)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest test/test_obsid_assignment_dialog.py::TestMergeSessionDraft -x`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check --fix . && ruff format .
git add tools/obsid_assignment_dialog.py test/test_obsid_assignment_dialog.py
git commit -m "feat(interlab4): merge_session_draft captures dialog state per lablittera"
```

---

### Task 4: Wire the session draft into `Interlab4Import`

**Files:**
- Modify: `tools/import_interlab4.py` (import block ~line 31-36; `__init__` ~line 66-71; `start_import` ~line 287-311)
- Test: `test/test_import_interlab4.py` (add a method to `TestInterlab4ImportSpatialite`, ~line 870)

**Interfaces:**
- Consumes: `apply_session_draft`, `merge_session_draft` (Tasks 2-3); existing `group_editor_rows`, `fan_out_filled_rows`, `DialogOutcome`, `ObsidAssignmentDialog`.
- Produces: `Interlab4Import` gains `self._obsid_session_draft: dict[str, str]` and `self._obsid_session_skipped: set[str]`, populated on `SAVE_DRAFT` and re-applied on every `start_import`.

- [ ] **Step 1: Write the failing integration test**

Add to `class TestInterlab4ImportSpatialite` in `test/test_import_interlab4.py`:

```python
    _OVERRIDE_LINES = (
        "#Interlab",
        "#Version=4.0",
        "#Tecken=UTF-8",
        "#Textavgränsare=Nej",
        "#Decimaltecken=,",
        "#Provadm",
        "Lablittera;Namn;Adress;Postnr;Ort;Kommunkod;Projekt;Laboratorium;"
        "Provtyp;Provtagare;Registertyp;ProvplatsID;Provplatsnamn;"
        "Specifik provplats;Provtagningsorsak;Provtyp;Provtypspecifikation;"
        "Bedömning;Kemisk bedömning;Mikrobiologisk bedömning;Kommentar;År;"
        "Provtagningsdatum;Provtagningstid;Inlämningsdatum;Inlämningstid;",
        "DM-1;MFR;;;;;Demoproj;Demo-Lab;NSG;DV;;;VattA;SpA;Kontroll;"
        "Dricksvatten;Utgående;Nej;Tjänligt;;;2010;2010-09-07;10:15;"
        "2010-09-07;14:15;",
        "#Provdat",
        "Lablittera;Metodbeteckning;Parameter;Mätvärdetext;Mätvärdetal;"
        "Mätvärdetalanm;Enhet;Rapporteringsgräns;Detektionsgräns;"
        "Mätosäkerhet;Mätvärdespår;Parameterbedömning;Kommentar;",
        "DM-1;Metod-1;Kalium;;5;;mg/l;;;;;;;",
        "#Slut",
    )

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_save_draft_restores_override_rows_next_cycle(self, mock_messagebar):
        # An override row (non-empty Provtagningsorsak) is never written to the
        # durable table; the in-memory session draft must bring it back.
        captured = {}
        calls = {"n": 0}

        def fake_dialog(
            editor_rows, existing_obsids, reload_callback=None, parent=None
        ):
            fake = mock.MagicMock()
            fake.editor_rows = editor_rows
            calls["n"] += 1
            if calls["n"] == 1:
                for row in editor_rows:
                    row.obsid = "Rb17"
                fake.outcome = DialogOutcome.SAVE_DRAFT
            else:
                captured["rows"] = list(editor_rows)
                fake.outcome = DialogOutcome.CANCEL
            fake.exec_ = lambda: None
            return fake

        with file_utils.tempinput(
            "\n".join(self._OVERRIDE_LINES), "utf-8", suffix=".lab"
        ) as filename:

            @mock.patch(
                "midvatten.tools.import_interlab4.ObsidAssignmentDialog",
                side_effect=fake_dialog,
            )
            @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
            @mock.patch(
                "midvatten.tools.utils.dialog_utils.Askuser",
                mocks_for_tests.mock_askuser.get_v,
            )
            @mock.patch("midvatten.tools.utils.midvatten_utils.select_files")
            def _run(self, fname, mock_select_files, mock_notfound, mock_dialog):
                mock_select_files.return_value = [fname]
                importer = Interlab4Import(self.iface, self.midvatten.ms)
                importer.init_gui()
                # Keep the durable table out of it; prove the session draft alone
                # restores the override row.
                importer.use_obsid_assignment_table.setChecked(False)
                importer.load_files()
                labs = importer.metadata_filter.get_selected_lablitteras()
                ignore = importer.ignore_provtagningsorsak.isChecked()
                # Cycle 1: fill + Save draft (returns Cancel, imports nothing).
                importer.start_import(importer.all_lab_results, labs, ignore)
                # Cycle 2: reopen -> the draft should pre-fill the override row.
                importer.start_import(importer.all_lab_results, labs, ignore)

            _run(self, filename)

        print(f"{mock_messagebar.mock_calls=}")
        restored = captured["rows"]
        override = [r for r in restored if r.is_override]
        assert override, f"expected an override row, got {restored}"
        assert all(r.obsid == "Rb17" for r in override)
        assert all(r.drafted for r in override)
```

Confirm the test file already imports `mock`, `DialogOutcome`, `file_utils`, `mocks_for_tests`, and `Interlab4Import` (it does, used by the existing `_run_interlab4_import`). If `DialogOutcome` is not yet imported at module scope, add it:

```python
from midvatten.tools.obsid_assignment_dialog import DialogOutcome
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest "test/test_import_interlab4.py::TestInterlab4ImportSpatialite::test_save_draft_restores_override_rows_next_cycle" -x`
Expected: FAIL — on cycle 2 the override row has `obsid == ""` / `drafted is False`, because `start_import` does not yet capture or restore the draft.

- [ ] **Step 3: Import the two helpers in production code**

In `tools/import_interlab4.py`, extend the existing import from `obsid_assignment_dialog` (currently `DialogOutcome, ObsidAssignmentDialog, ask_obsid_rows_as_dicts, fan_out_filled_rows, group_editor_rows`) to also import the new helpers:

```python
from midvatten.tools.obsid_assignment_dialog import (
    DialogOutcome,
    ObsidAssignmentDialog,
    apply_session_draft,
    ask_obsid_rows_as_dicts,
    fan_out_filled_rows,
    group_editor_rows,
    merge_session_draft,
)
```
(Match the module's existing import style/path; the key is adding `apply_session_draft` and `merge_session_draft`.)

- [ ] **Step 4: Add the draft containers in `__init__`**

In `Interlab4Import.__init__`, after `super().__init__(iface, ms)` and the `setWindowTitle(...)` call, add:

```python
        self._obsid_session_draft: dict[str, str] = {}
        self._obsid_session_skipped: set[str] = set()
```

- [ ] **Step 5: Restore the draft before showing the dialog**

In `start_import`, immediately after the line
`editor_rows = group_editor_rows(row_dicts, cache_matches=cache_pair_map)`
add:

```python
            apply_session_draft(
                editor_rows,
                self._obsid_session_draft,
                self._obsid_session_skipped,
            )
```

- [ ] **Step 6: Capture the draft on Save draft**

In `start_import`, replace the existing SAVE_DRAFT block:

```python
            if dialog.outcome == DialogOutcome.SAVE_DRAFT:
                self.status = True
                return Cancel()
```
with:

```python
            if dialog.outcome == DialogOutcome.SAVE_DRAFT:
                shown_lablitteras = {
                    lab for row in dialog.editor_rows for lab in row.lablitteras
                }
                merge_session_draft(
                    self._obsid_session_draft,
                    self._obsid_session_skipped,
                    shown_lablitteras,
                    filled,
                    skipped,
                )
                self.status = True
                return Cancel()
```
(`filled` and `skipped` are already bound just above from `fan_out_filled_rows(dialog.editor_rows)`.)

- [ ] **Step 7: Run the integration test to verify it passes**

Run: `python3 -m pytest "test/test_import_interlab4.py::TestInterlab4ImportSpatialite::test_save_draft_restores_override_rows_next_cycle" -x`
Expected: PASS.

- [ ] **Step 8: Run the full interlab4 + dialog test files**

Run:
```bash
python3 -m pytest test/test_obsid_assignment_dialog.py test/test_import_interlab4.py -x
```
Expected: PASS (no regressions in the existing flows).

- [ ] **Step 9: Lint and commit**

```bash
ruff check --fix . && ruff format .
git add tools/import_interlab4.py test/test_import_interlab4.py
git commit -m "feat(interlab4): restore typed obsids from an in-memory session draft"
```

---

## Final verification

- [ ] Run the backend integration file to confirm the durable-cache path is untouched:
  `python3 -m pytest test/test_import_interlab4_backends.py -x`
- [ ] Run `test/test_midvatten_compat.py` in `~/dev/midv_addons` if `obsid_assignment_dialog` / `import_interlab4` public surface is consumed there (adding functions is additive, but confirm).
- [ ] Manual sanity (optional, real QGIS): import an interlab4 file whose rows have a `Provtagningsorsak`, fill obsids, Save draft && close, Start import again → the obsids are pre-filled and visible.

## Self-review notes

- **Spec coverage:** storage/lifetime (Task 4 §4-6), `drafted` flag + display (Task 1), capture/restore pure fns (Tasks 2-3), independence from durable table (integration test disables it), testing (all tasks). Out-of-scope items are not implemented, as intended.
- **Type consistency:** `apply_session_draft(editor_rows, draft, skipped)` and `merge_session_draft(draft, skipped_set, shown_lablitteras, filled, skipped)` signatures are identical in their defining task, the test, and the `start_import` call sites.
- **No durable-cache change:** `_insert_cache_rows` / `_load_obsid_assignment_cache` are not modified; the reload→`cached=True` mechanism still prevents PK double-inserts.
