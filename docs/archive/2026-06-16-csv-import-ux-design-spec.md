> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-06-16 · modified: 2026-06-16 · archived: 2026-07-31

# CSV import UX cleanup: one load dialog + quieter foreign-key handling

**Date:** 2026-06-16
**Branch:** `csv-import-ux` (from `ai_test`)
**Files:** `tools/import_general_csv_gui.py`, `tools/import_data_to_db.py` (+ tests)

## Problem

The General CSV importer subjects the user to a chain of modal prompts that are
either mis-ordered or non-actionable:

1. **Loading a file is three sequential popups.** Clicking *"Load data from
   file"* fires, in order: `ask_for_charset()` (an encoding prompt shown
   **before** any file is chosen — answered by reflex, with no information),
   then the native file picker, then a *"Does the file contain a header?"*
   yes/no dialog. Three windows to load one file, and the first one asks a
   question you can't yet answer.

2. **The start-import confirmation is non-actionable noise.** Clicking *"Start
   import"* shows a modal seeded with *"Note: Foreign keys will be imported
   silently. Proceed with import?"*. The foreign-key line is informational only
   — there is no choice to make about it, and it is never a reason to abort.
   The confirmation fires on **every** import, even when nothing is wrong.

This modal lives in **shared** code (`MidvDataImporter.general_import` →
`_ask_user_to_proceed`), so it also fires for the Fieldlogger and Interlab4
importers. The logger importer already passes `skip_confirmation=True`.

## Design

### Part 1 — One consolidated "Load data from file" dialog

A new `CsvFileLoadDialog(QtWidgets.QDialog)` in `import_general_csv_gui.py`
replaces the three sequential popups with a single window:

```
┌─ Load data from file ──────────────────────┐
│ File:     [/path/to/data.csv ] [Browse…]   │
│ Encoding: [iso-8859-1       ▼]  (editable)  │
│ [x] First row is a header                   │
│ Preview:                                    │
│   obsid;date_time;level_masl                │
│   Björkån;2024-01-01 09:00;3,14             │
│   …(first ~5 lines, decoded live)…          │
│                          [ OK ]  [ Cancel ] │
└─────────────────────────────────────────────┘
```

Widgets:

- **File row** — a read-only path field + **Browse…** button. Browse calls the
  existing `midvatten_utils.select_files(only_one_file=True, extension=<the
  current csv/txt/* filter>)`, preserving its "default the picker directory to
  the database folder" behaviour. The chosen path fills the field and refreshes
  the preview.
- **Encoding** — an *editable* `QComboBox` prefilled with
  `utf-8, iso-8859-1, cp1250, cp1252`. Default selection = the last-used
  encoding (persisted in `QgsSettings`, key `Midvatten/csv_import_encoding`),
  falling back to the OS locale (`midvatten_utils.getcurrentlocale()[1]`) on
  first run. Editable so an unusual charset can still be typed.
  `currentTextChanged` refreshes the preview. On OK the current value is saved
  back as the new last-used.
- **First row is a header** — `QCheckBox`, checked by default (the common case).
- **Preview** — a read-only `QPlainTextEdit` showing the first ~5 lines of the
  chosen file decoded with the currently-selected encoding, opened with
  `errors="replace"` so a wrong charset shows visible mojibake (`Ã¥Ã¤Ã¶`)
  rather than raising or hiding the problem. Re-rendered whenever the file or
  encoding changes. This makes the encoding guess **verifiable** before import —
  directly defending the `returnunicode` mojibake firewall, since charset cannot
  be auto-detected reliably (pure-ASCII files are valid under all four listed
  encodings simultaneously).
- **OK / Cancel** (`QDialogButtonBox`). OK is disabled until a file is chosen.

On accept the dialog exposes `.filename`, `.charset`, `.has_header`.

`GeneralCsvImportGui.load_files()` is rewritten to open this one dialog instead
of calling `ask_for_charset()` + `select_files()` + the header `Askuser`:

```python
dlg = CsvFileLoadDialog(self, default_encoding=<last-used or locale>)
if dlg.exec() != QtWidgets.QDialog.Accepted:
    raise exceptions.UserInterruptError()   # same as today's empty-charset/no-file path
filename, charset, has_header = dlg.filename, dlg.charset, dlg.has_header
delimiter = file_utils.get_delimiter(filename=filename, charset=charset, delimiters=[",", ";"])
self.file_data = self.file_to_list(filename, charset, delimiter)
# existing header-dedup vs "Column N" generation, driven by `has_header`
```

The downstream pipeline (delimiter detection, `file_to_list`, header
deduplication / synthetic `"Column N"` names) is **unchanged** — only its inputs
now come from the dialog instead of three popups.

`ask_for_charset()` stays in the codebase (Interlab4, Fieldlogger, and others
still call it). The encoding/header widgets are irrelevant to the
*"Load from active layer"* buttons, which are untouched.

### Part 2 — Quieter foreign-key handling at start import (shared, all importers)

Builds directly on the landed duplicate-message work (`bc65dd9`): the per-cause
detail lines (in-file dups vs already-in-DB) already accumulate in
`import_messages`. This change adjusts **when** the modal fires and removes the
FK noise, without disturbing that wording.

In `MidvDataImporter.general_import`:
- Seed `import_messages = []` instead of with the *"Foreign keys will be
  imported silently"* note.

In `_handle_foreign_keys` (the place FK rows are actually imported):
- When `foreign_keys` is non-empty and rows are imported, emit a **quiet log
  message** (`MessagebarAndLog.info(log_msg=…)`, log panel only — no popup, no
  message bar): *"Foreign keys were imported automatically."* This appears only
  when the destination table actually has foreign keys, so it is accurate rather
  than the old unconditional note.

Rewrite `_ask_user_to_proceed` so the **modal appears only when rows would be
dropped** — the one case with a real decision (data loss):

```python
def _ask_user_to_proceed(self, remaining_rownumbers, all_rownumbers, import_messages):
    rows_dropped = len(remaining_rownumbers) != len(all_rownumbers)

    # Preserve accumulated per-cause detail quietly even when no modal shows.
    if import_messages:
        message_utils.MessagebarAndLog.info(log_msg="\n".join(import_messages))

    if not rows_dropped:
        return  # clicking "Start import" is itself the go-ahead

    if self.foreign_keys_import_question:   # already confirmed once, or skip_confirmation
        message_utils.MessagebarAndLog.info(
            log_msg=<"Skipping confirmation dialog: %s out of %s rows…"> )
        return

    msg = <"There are %s out of %s rows to import (see log for removed rows).\n\nProceed with import?">
    self.foreign_keys_import_question = 1
    if dialog_utils.Askuser("YesNo", msg, "Info").result == 0:
        raise UserInterruptError()
```

This preserves the "ask at most once per import session" latch (multi-table
imports such as Fieldlogger), preserves `skip_confirmation=True` (logger
importer never blocks), keeps the reworded duplicate detail in the row-loss
modal, and drops the always-on, never-rejected confirmation.

## Scope guardrails

- **No DB schema changes.** DB end-state for any import is byte-identical to
  today — only dialog flow and logging change. No test reference data changes.
- `GeneralCsvImportGui.__init__(self, iface, ms, dbconnection=None)` signature is
  **unchanged** (midv_addons public-API contract). Run midv_addons
  `test_midvatten_compat.py` after.
- Part 2 changes shared `general_import`, so it applies to CSV, Fieldlogger, and
  Interlab4 (intended — the FK note is equally non-actionable in all three).
- Encoding cannot be reliably auto-detected — the dialog never guesses silently;
  the preview lets the user verify their explicit choice.
- All user-facing strings via `QCoreApplication.translate(...)`.
- New imports are module-level (no in-function imports).

## Tests

`test/test_import_general_csv_gui.py`, `test/test_import_general_csv_gui_backends.py`:
- Replace mocking of `ask_for_charset` / `select_files` / the header `Askuser`
  with the new `CsvFileLoadDialog` (mock it to return a fixed
  filename/charset/has_header). Cover header-present and header-absent paths.
- New unit tests for `CsvFileLoadDialog`: encoding default = last-used else
  locale; last-used persists on accept; preview re-renders on encoding change;
  preview tolerates an undecodable byte sequence (`errors="replace"`); OK gated
  on a chosen file.

`test/test_import_data_to_db.py`:
- No rows dropped → **no** `Askuser` modal; import proceeds; FK note appears only
  as a log message (and only when the table has foreign keys).
- Rows dropped + first call → modal fires once with the reworded per-cause
  detail; declining raises `UserInterruptError`.
- Rows dropped + `skip_confirmation=True` (or latch already set) → no modal, quiet
  "skipping confirmation" log.
- FK note text no longer appears in any modal.
