# Custom general report: direct Word (.docx) export — design

Date: 2026-06-10
Branch: `docx-general-report` (worktree of `ai_test`)

## Problem

The custom general report (`tools/custom_drillreport.py`, menu "General report")
generates an HTML file that users open in a browser and copy-paste into Word.
This loses page-break control and is an extra manual step. The report should be
exportable directly as a `.docx` file.

Requirements from the user:

- Tables must be compact vertically (small font, no extra spacing).
- No table may span across a page break — a block that does not fit on the
  current page moves to the next page. Exception: a table too long for one A4
  page is allowed to break (between rows, never inside a row).
- The feature is optional. Nothing breaks if the docx library is missing: the
  Word output option is visible but disabled, with a tooltip explaining why
  and how to install the dependency.
- The Word file is written via a save dialog only (no auto-open afterwards).
- The existing HTML report stays exactly as it is today.

## Dependency

`python-docx` (MIT). It is not bundled with QGIS and not packaged in OSGeo4W
(checked the OSGeo4W v2 x86_64 package index: 318 `python3-*` packages, no
docx). However, its only compiled dependency, `lxml`, *is* shipped by
OSGeo4W/QGIS, so `pip install python-docx` in the OSGeo4W shell (or system
pip on Linux) is a pure-Python install.

Consequently `python-docx` is an **optional runtime dependency**:

- `requirements.txt` is unchanged.
- The docx renderer module does `try: import docx / except ImportError:
  docx = None` at module level and exposes `DOCX_AVAILABLE: bool`.

## Architecture

Shared data collection with two renderers:

```
DrillreportUi (dialog, output-format radio: HTML | Word)
    └── OK button ──┬─ HTML selected ──► Drillreport (HTML, unchanged output)
                    └─ Word selected ──► DocxReportWriter (new)
                          both consume ▲
            collect_report_data() (extracted from Drillreport.__init__)
```

### 1. `tools/custom_drillreport_core.py` — extract data collection

The shared pieces live in a new module `custom_drillreport_core.py` (pattern
precedent: `wqualreport_core.py`) rather than in `custom_drillreport.py`
itself: the dialog module imports the docx module (for `DOCX_AVAILABLE`), and
the docx module needs the shared helpers — keeping them in
`custom_drillreport.py` would create a circular import.

The DB-querying half of `Drillreport.__init__` moves to a module-level
function `collect_report_data(...)`:

- obs_points query for the selected obsids (existing column list).
- stratigraphy query (existing `depth` → `depthtop`/`depthbot` expansion).
- CRS srid + name lookup.
- Per-obsid slicing into:
  - `general_data: list[(translated_header, raw_value)]` + `general_rounding`
  - `geo_data` + `geo_rounding` (including the appended "XY Reference system"
    row when east/north is requested)
  - `strat_data: list[row]` + `strat_sql_columns_list`
  - `comment_data: list[str]` (subject to `include_comments` and the existing
    empty/placeholder filtering)

Return value: a list of per-obsid records (dataclass `ObsidReportData`) plus
shared metadata (strat column list, strat column widths, CRS string). The
existing HTML writer consumes this structure; **its output must remain
byte-identical** — the existing tests in
`test/test_custom_drillreport_ui_spatialite.py` are the guard, and no test
reference data may change.

Value formatting currently embedded in the HTML writers is extracted into
module-level helpers shared by both renderers:

- `format_value(value, rounding, decimal_separator)` — NULL→"", max-precision
  rounding rule, decimal separator replacement (same semantics as today).
- The `skip_empty` filtering rule for two-column tables.

### 2. `tools/custom_drillreport_docx.py` — new renderer

`DocxReportWriter` takes the same per-obsid data plus the same dialog settings
(`header_in_table`, `skip_empty`, the four section headers,
`empty_row_between_obsids`, `topleft_topright_colwidths`, `general_colwidth`,
`geo_colwidth`, `decimal_separator`) and a target file path.

Document structure, mirroring the HTML layout per obsid:

- A4 page size, moderate margins (2 cm).
- One outer 2-column table per obsid:
  - Row 1 (only when `header_in_table`): merged cell with the obsid as a bold
    header. When unchecked, the obsid is a heading paragraph before the table.
  - Row 2: left cell = general info as key/value rows; right cell = geo info.
    Column split from `topleft_topright_colwidths` (default 60/40). When there
    is no geo data the general table takes the full width (merged row).
  - Row 3 (when strat or comment data exists): merged cell containing the
    stratigraphy table (column widths from the `column;width` syntax in the
    strat settings) and the comment paragraph.
  - Key/value pairs and the strat rows are nested tables inside the outer
    cells (python-docx `cell.add_table()`), with relative widths from
    `general_colwidth` / `geo_colwidth`.
- Section headers (general/geo/strat/comment) rendered as small bold
  underlined paragraphs, as in the HTML.
- Comments: `com_onerow`/`com_html` hold Qt rich-text HTML; converted to plain
  text with `QTextDocument.setHtml(...).toPlainText()`.

Compactness:

- 8 pt font for table content, obsid header slightly larger (12 pt bold).
- Paragraph `space_before = space_after = 0`, single line spacing.
- Minimal table cell margins (set via `tblCellMar` OxmlElement, since
  python-docx has no direct API).
- `table.autofit = False` with explicit column widths.

Page-break behavior (the core requirement):

- Every table row gets `w:cantSplit` in its `trPr` — a row never breaks
  across pages.
- All paragraphs in an obsid block except those in the last row get
  `keep_with_next = True`. Word then moves the entire block to the next page
  when it does not fit, and when a block is taller than one A4 page Word
  breaks it cleanly between rows. This delegates the "keep together, unless
  too long" rule to Word's own layout engine.
- `empty_row_between_obsids` adds an extra empty paragraph between blocks.

Small XML helpers in the same module: `_set_cant_split(row)`,
`_set_cell_margins(table, ...)`.

### 3. Dialog changes

- `ui/custom_drillreport.ui`: an "Output format" radio group with two
  `QRadioButton`s, `radio_format_html` ("HTML") and `radio_format_word`
  ("Word (.docx)"). HTML is the default. The existing OK/Cancel buttons stay.
- The selected format is persisted with the other dialog settings through the
  existing `save_stored_settings` / `update_from_stored_settings` machinery
  (extend those to handle `QRadioButton` state).
- `DrillreportUi.__init__`:
  - If `DOCX_AVAILABLE` is false: `radio_format_word.setEnabled(False)` plus a
    translated tooltip — "Requires the python-docx package. Install it with
    'pip install python-docx' (OSGeo4W shell on Windows)." HTML remains
    selected and OK behaves exactly as today. A stored setting of "Word" is
    ignored while the library is missing.
  - OK with HTML selected: unchanged behavior (temp file + open in browser).
  - OK with Word selected: same settings gathering and validation as the HTML
    path (selected obsids required, settings saved), then
    `QFileDialog.getSaveFileName` with a `*.docx` filter. Cancel aborts
    silently. On success: `MessagebarAndLog.info` with the saved path. On
    write failure (e.g. file locked by Word): `MessagebarAndLog.critical`
    with the OS error in the log panel.
- User-facing strings use `QCoreApplication.translate`.

### 4. Tests

New `test/test_custom_drillreport_docx_spatialite.py`, following the style of
`test_custom_drillreport_ui_spatialite.py` (same fixtures/markers, mocked
`MessagebarAndLog` with `mock_calls` printing):

- User-facing flow first: build `DrillreportUi`, insert test data, select the
  Word radio option, mock `QFileDialog.getSaveFileName` to a temp path, click
  OK, reopen the file with python-docx and assert obsid, strat values, and
  custom headers appear.
- `cantSplit` present in the document XML for table rows; keep-with-next set
  on block paragraphs.
- Decimal separator and rounding applied as in the HTML path.
- Save-dialog cancel produces no file and no error.
- Word radio option disabled with tooltip (and HTML still working) when
  `DOCX_AVAILABLE` is patched to False.
- Output-format choice round-trips through stored settings.
- All existing HTML tests pass unchanged (byte-identical HTML guard).

Tests are marked `@pytest.mark.spatialite`; they may `pytest.importorskip`
on python-docx so suites on machines without it skip rather than fail.

## Error handling summary

| Situation | Behavior |
|---|---|
| python-docx missing | Word radio option disabled + tooltip; HTML path unaffected |
| No obsids selected | Existing critical message + `UsageError` (shared with OK path) |
| Save dialog cancelled | Silent return |
| File not writable / locked | `MessagebarAndLog.critical`, no crash |

## Alternatives considered and rejected

- **Qt `QTextDocumentWriter` → .odt (dependency-free).** Verified in the QGIS
  environment: paragraph-level `PageBreak_AlwaysBefore` survives ODT export
  (`fo:break-before`), table-level does not. A two-pass approach (lay out at
  A4, measure each table with `frameBoundingRect`, set an explicit break on
  the heading of any table that would straddle a page) would work and is
  stable under content deletion (breaks are anchored properties, not spacer
  paragraphs). Rejected because the break decisions are static — computed
  with Qt font metrics at generation time, so a borderline table can still
  straddle when Word renders the .odt — and the output is .odt, not .docx.
  python-docx's `cantSplit`/keep-with-next is evaluated by Word at view time
  and stays correct during later editing.
- **Post-processing Qt's ODT `content.xml`** to inject ODF keep-together
  attributes (`style:may-break-between-rows="false"`): dynamic and
  dependency-free in theory, but Word's ODT import fidelity for that
  attribute is unverified.
- **openpyxl** (which OSGeo4W does ship as `python3-openpyxl`): Excel .xlsx
  only; no Word document model.
- **HTML→docx conversion and hand-rolled OOXML**: see Architecture decision —
  unreliable page-break control, respectively high maintenance.

## Out of scope

- Auto-opening the generated document.
- Any change to the HTML output, the plain `drillreport.py` report, or
  database schemas.
- Bundling/vendoring python-docx.
- Embedding images/logo in the Word file (the HTML report does not embed any
  in this report either).
