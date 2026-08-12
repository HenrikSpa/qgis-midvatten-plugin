# Interlab4 obsid assignment — session draft restore

**Date:** 2026-08-12
**Status:** Design approved, ready for implementation plan
**Files touched:** `tools/obsid_assignment_dialog.py`, `tools/import_interlab4.py`, tests

## Problem

In the Interlab4 import, "Start import" opens the obsid-assignment dialog. The
user fills obsids (e.g. via "Fill selection"), clicks **Save draft && close**,
and the dialog closes. On the next "Start import" the dialog reopens but the
obsids the user just entered are **gone** — the obsid column is empty and the
rows must be redone every time.

### Root cause

Rows whose `provtagningsorsak` is non-empty are classified as **override rows**
(`_has_override`, `obsid_assignment_dialog.py`). Real interlab4 data almost
always populates `provtagningsorsak` (e.g. "Dricksvatten enligt SLVFS 2001:30"),
so most or all rows are override rows.

The only persistence today is the durable table `zz_interlab4_obsid_assignment`,
written by `_insert_cache_rows` and keyed on `(specifik_provplats,
provplatsnamn)`. `fan_out_filled_rows` **deliberately excludes override rows**
from that table (`if not row.is_override and not row.cached`), because a
`(spec, namn)` key cannot safely represent per-sample overrides. Consequence:
"Save draft" silently discards every override row's obsid, so they reappear
empty on the next import.

A secondary, pre-existing surprise: clean (non-override) rows *are* saved to the
durable table, but on reopen they come back `cached=True` and are hidden by the
default-off "Show matched rows" filter, so they also look "gone."

## Goal

Add an in-memory, per-session draft so that reopening the dialog within the same
import-window session restores **exactly what the user typed** — for **all**
rows (override and clean) — shown as normal visible, editable filled rows.

### Non-goals / out of scope (pre-existing, separate concerns)

- Editing or clearing a value that already exists in the durable
  `zz_interlab4_obsid_assignment` table does **not** remove it from that table.
- The default-off "Show matched rows" filter for genuinely auto-matched (durable
  cache) rows is unchanged.
- No persistence across QGIS restarts or across separate import-window
  instances. Draft is session-only, by explicit choice.
- No writing to the QGIS project file or to any DB table.

## Design

### Two stores, clearly separated

| Store | Key | Lifetime | Role |
|---|---|---|---|
| `zz_interlab4_obsid_assignment` (exists today) | `(spec, namn)` | durable | background *auto-match* of clean rows across future files |
| session draft (new) | `lablittera` | current import window | *restore exactly what the user typed*, incl. override rows |

`lablittera` is the unique id of one lab result. A draft entry keyed on it can
only ever re-attach to that same sample; it structurally cannot leak onto a
different sample the way a `(spec, namn)` key can. This is *why* the "only
restore what I typed, never auto-match a different file" property holds for free.

Precedence: the session draft wins on display and is shown as a normal editable
row. A value that came only from the durable auto-match table is shown greyed
(as today). The user can always tell "I typed this" from "auto-matched from the
learned table."

The session draft is independent of the "Assign obsid using table" checkbox — it
works even when the durable table is disabled or absent.

### 1. Storage & lifetime

On the `Interlab4Import` instance (`import_interlab4.py`), initialised in
`__init__`:

```python
self._obsid_session_draft: dict[str, str] = {}   # lablittera -> obsid
self._obsid_session_skipped: set[str] = set()      # lablitteras marked [skipped]
```

A new `Interlab4Import` is created each time the import tool is opened from the
menu (`tool_class=Interlab4Import` in `midvatten_plugin.py`), so the draft
persists across "Start import" clicks *within one open import window* and is
discarded when that window is closed. This matches the agreed "current session
only" scope.

### 2. The `drafted` flag

Add one field to `EditorRow` (`obsid_assignment_dialog.py`):

```python
drafted: bool = False
```

It is set at restore time and leaves `cached` untouched. It changes only two
things:

- **Display.** A row is greyed (`_populate_table`) and hidden
  (`_apply_filters`) only when `cached and not drafted`. So any drafted row is a
  normal visible, editable filled row — even if it is also in the durable table.
  Rows that were auto-matched from the durable table but *not* typed this
  session keep today's greyed/hidden behaviour.
- **Nothing else.** `fan_out_filled_rows` continues to key off
  `cached` / `is_override` only; `drafted` never triggers a durable insert. The
  existing "reload marks the row `cached=True`" mechanism keeps preventing the
  primary-key double-insert on repeated saves. **No change to
  `_insert_cache_rows` is required.**

Why this is safe for the durable table:
- Override row, drafted: `is_override=True` → excluded from durable insert. Never
  a PK issue.
- Clean row, first Save draft: `cached=False`, drafted → inserted to durable
  once (normal learning).
- Clean row, later opens: durable reload sets `cached=True`; draft overlay also
  sets `drafted=True` → visible, but excluded from re-insert (`cached=True`). No
  PK violation.

### 3. Capture and restore (pure functions)

Two pure, unit-testable helpers live beside `group_editor_rows` and
`fan_out_filled_rows` in `obsid_assignment_dialog.py`.

**Restore** — applied in `start_import` immediately after
`group_editor_rows(...)`, before the dialog is constructed:

```python
def apply_session_draft(
    editor_rows: list[EditorRow],
    draft: dict[str, str],
    skipped: set[str],
) -> None:
    """Overlay a per-lablittera session draft onto freshly grouped rows.

    For each row: if any of its lablitteras is in `skipped`, mark row.skipped;
    else if any is in `draft`, set row.obsid to that value and row.drafted=True.
    Rows with no drafted lablittera are left unchanged.
    """
```

- For a clean group (several lablitteras, one shared obsid), all its lablitteras
  carry the same drafted obsid, so the first match is authoritative. If a rare
  inconsistency arises (file changed mid-session), the first match wins.
- First-ever open: draft empty → no-op.

**Capture** — invoked in `start_import` **only** on
`DialogOutcome.SAVE_DRAFT` (the Cancel → "Save draft" choice routes through the
same outcome). `fan_out_filled_rows` already returns per-lablittera `filled` and
`skipped`. A helper mirrors the *current* dialog state for exactly the
lablitteras shown this round:

```python
def merge_session_draft(
    draft: dict[str, str],
    skipped_set: set[str],
    shown_lablitteras: set[str],
    filled: dict[str, str],
    skipped: set[str],
) -> None:
    """Mutate draft/skipped_set to mirror the dialog state for shown rows.

    For each lablittera in shown_lablitteras:
      - in `filled`  -> draft[lab] = filled[lab]; skipped_set.discard(lab)
      - in `skipped` -> skipped_set.add(lab);     draft.pop(lab, None)
      - otherwise (cleared / untouched-empty) -> draft.pop(lab, None);
                                                  skipped_set.discard(lab)
    Lablitteras not in shown_lablitteras are left untouched (they were filtered
    out this round, e.g. already-imported reports).
    """
```

`shown_lablitteras` is the union of `row.lablitteras` over `dialog.editor_rows`.
Mirroring (rather than a plain `update`) ensures a value the user *cleared*
before saving does not resurrect from the draft on reopen.

### Control-flow summary in `start_import`

```
editor_rows = group_editor_rows(row_dicts, cache_matches=cache_pair_map)
apply_session_draft(editor_rows, self._obsid_session_draft,
                    self._obsid_session_skipped)          # NEW: restore
dialog = ObsidAssignmentDialog(editor_rows, ...)
dialog.exec_()
...
filled, skipped, cache_rows = fan_out_filled_rows(dialog.editor_rows)
self._insert_cache_rows(connection_columns, cache_rows)   # unchanged
if dialog.outcome == DialogOutcome.SAVE_DRAFT:
    shown = {lab for r in dialog.editor_rows for lab in r.lablitteras}
    merge_session_draft(self._obsid_session_draft,
                        self._obsid_session_skipped,
                        shown, filled, skipped)            # NEW: capture
    self.status = True
    return Cancel()
```

## Testing

Follow project conventions: mock `MessagebarAndLog`; integration tests lead with
the user-facing `start_import` flow using the existing dialog mock pattern.

**Unit (pure functions) — `test_obsid_assignment_dialog.py`:**
- `apply_session_draft`: sets `obsid` + `drafted=True` for a matching override
  row; marks `skipped`; leaves undrafted rows untouched; first match wins for a
  multi-lablittera clean group.
- `merge_session_draft`: fills recorded; skips recorded; a *cleared* shown
  lablittera removed from the draft; lablitteras not shown left untouched.

**Dialog display — `test_obsid_assignment_dialog.py`:**
- A `drafted and cached` row is visible and not greyed; a `cached`-only row is
  hidden (extends the existing hide/show test).

**Integration — `test_import_interlab4.py` (or backends):**
- Drive **two `start_import` cycles** on one `Interlab4Import` instance with a
  dialog mock (in the style of `_make_passthrough_dialog`) that fills an override
  row and returns `SAVE_DRAFT` on cycle 1. On cycle 2, assert the reopened
  `editor_rows` for that override lablittera come back with the typed obsid and
  `drafted=True` (visible), without a durable-table row having been written.

## Risks / edge cases

- **Multi-lablittera clean group with inconsistent drafted obsids** — first
  match wins; documented, and cannot occur unless the underlying file changes
  between imports in the same session.
- **Durable table disabled** — session draft still restores all rows (clean +
  override); nothing is written to the durable table; no PK risk.
- **Repeated Save draft of a clean row** — durable reload sets `cached=True`
  before the second save, so `fan_out_filled_rows` excludes it and there is no
  PK double-insert.
