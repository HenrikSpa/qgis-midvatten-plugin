> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-04-29 · modified: 2026-04-29 · archived: 2026-07-31

# CSV Export — HTML Strip & Export Dialog

**Date:** 2026-04-29
**Branch:** `feature/csv-export-html-strip`

## Problem

`obs_points.com_html` stores rich-text HTML content. When exported to CSV the HTML attribute
quote characters (`"`) combined with embedded newlines produce broken rows in Excel and
LibreOffice — cells bleed across rows because the CSV quoting becomes too complex to parse
reliably.

## Solution

Strip HTML from `com_html` before writing to CSV, converting it to readable plain text with
logical line-breaks preserved. Controlled by a checkbox in a new export dialog (default: on).

## New export dialog (`ExportCsvDialog`)

Replaces the bare `QFileDialog.getExistingDirectory` call in `show()`. Contains:

- Read-only `QLineEdit` + **Browse…** button (opens `QFileDialog.getExistingDirectory`)
- Checkbox: *"Convert rich-text (HTML) fields to plain text"* — checked by default
- `QDialogButtonBox` (OK / Cancel); OK disabled until a folder is chosen

Exposes two properties: `export_folder: str`, `strip_html: bool`.

## HTML-to-plaintext conversion (`html_to_plaintext`)

Standalone function in `export_data.py` using Python stdlib only (`html.parser`, `re`).

**Guard:** Only processes a value if `re.search(r'<[a-zA-Z][^>]*>', value)` matches. Plain text
containing `< 5 l/s` or `<5 l/s` is left unchanged because neither starts a tag.

**When HTML is detected:**
- Block-level tags (`p`, `br`, `div`, `li`, `tr`, `h1`–`h6`) emit `\n` on open and close
- All other tags are dropped silently
- HTML entities decoded by `HTMLParser` (convert_charrefs=True default) — `&lt;` → `<`, etc.
- Runs of 3+ newlines collapsed to 2; result is stripped of leading/trailing whitespace

## Changes to `ExportData`

| Location | Change |
|---|---|
| `show()` | Construct and exec `ExportCsvDialog`; pass `export_folder` and `strip_html` to `export_2_csv` |
| `export_2_csv(exportfolder, strip_html=True)` | Accept and store `strip_html` as `self._strip_html`; pass it to each `to_csv` call via `write_data` |
| `write_data(…, strip_html=True)` | Forward `strip_html` to `to_writer` calls |
| `to_csv(…, strip_html=True)` | After fetching rows, find column indices where header == `"com_html"` and apply `html_to_plaintext` to those cells |

No changes to `write_printlist_to_file` or any other shared utility.

## Testing

- Unit tests for `html_to_plaintext`: multi-paragraph HTML, `<br>`, entities, plain text with
  `<5 l/s`, already-plain text
- Integration test: export `obs_points` with an HTML `com_html` value; assert the CSV cell is
  plain text with newlines intact and no HTML tags
