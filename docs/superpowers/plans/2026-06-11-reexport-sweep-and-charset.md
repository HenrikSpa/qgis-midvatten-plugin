# Re-export Sweep (non-message groups) + Charset Helper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (a) Extract a decode-with-fallback file-reading helper and adopt it in import_fieldlogger with å/ä/ö encoding regression tests; (b) migrate in-repo callers of common_utils/midvatten_utils re-exports to their source modules for the exceptions/dialog_utils/layer_utils/file_utils/string_utils groups, updating test mock-patch targets in lockstep; (c) mark the aggregator re-export blocks as the midv_addons contract.

**Architecture:** Pure behavior-preserving refactors. The re-exports themselves STAY (midv_addons public API). The message_utils group (MessagebarAndLog, pop_up_info, show_message_log, sql_failed_msg — ~80% of total volume) is deliberately DEFERRED to its own slice. Parent plan items: 9 (scoped), 15 (partial), with items 11 deferral rationale recorded.

**Tech Stack:** Python 3, pytest, QGIS env. `python3`, never `python`.

**Worktree:** `.claude/worktrees/reexport-charset-slice` branch `reexport-charset-slice` (already created from ai_test @ a205d3e).

**Scope decisions recorded (verified against source 2026-06-11):**
- Item 9 originally proposed one helper for both importers. REJECTED for interlab4: its loop scans the file header for an embedded `#tecken=` encoding DECLARATION (then uses the declared charset) — different semantics from fieldlogger's decode-the-data loop. interlab4 stays untouched.
- Item 11 (prepare_*_data) DEFERRED: read in full, `prepare_w_flow_data` is dominated by an interactive instrument-id dialog flow; shared boilerplate is only the header row + `len<2` guard (~4 lines/method). A spec-driven helper would be forced abstraction.
- Mock-patch criticality: production code reads re-exports via module attribute at call time, so `mock.patch("...common_utils.X")` intercepts today. Once a production file imports from the source module, the patch target for tests of THAT file must become the source-module path (e.g. `"midvatten.tools.utils.layer_utils.find_layer"`). Test updates must land in the same task as the production file they patch.
- `tools/sectionplot/__init__.py` and `tools/import_logger/__init__.py` re-import common_utils purely as mock-path shims — they stay (still needed by the deferred message_utils group).

---

### Task 1: Charset decode-with-fallback helper + fieldlogger adoption

**Files:**
- Modify: `tools/utils/file_utils.py` (new function)
- Modify: `tools/import_fieldlogger.py` (`select_file_and_parse_rows`, ~lines 200-238)
- Test: `test/test_file_utils.py` (create if missing; check for an existing file first)

- [ ] **Step 1: Write failing tests** for the new helper in `test/test_file_utils.py`:

```python
import pytest

from midvatten.tools.utils import file_utils


@pytest.mark.active
class TestReadlinesWithDetectedCharset:
    def test_utf8_swedish_chars(self, tmp_path):
        p = tmp_path / "f.csv"
        p.write_bytes("obsid;åäö\nrad2;ÅÄÖ\n".encode("utf-8"))
        rows, encoding = file_utils.readlines_with_detected_charset(
            str(p), ["utf-8", "cp1252"]
        )
        assert rows == ["obsid;åäö\n", "rad2;ÅÄÖ\n"]
        assert encoding == "utf-8"

    def test_cp1252_swedish_chars_fall_through(self, tmp_path):
        p = tmp_path / "f.csv"
        # 'åäö…' in cp1252; the ellipsis byte 0x85 is invalid as utf-8 start of
        # this sequence, forcing fallback to cp1252.
        p.write_bytes("obsid;åäö…\n".encode("cp1252"))
        rows, encoding = file_utils.readlines_with_detected_charset(
            str(p), ["utf-8", "cp1252"]
        )
        assert rows == ["obsid;åäö…\n"]
        assert encoding == "cp1252"

    def test_no_encoding_matches_returns_none(self, tmp_path):
        p = tmp_path / "f.csv"
        p.write_bytes(b"\xff\xfe\x00invalid for both")
        rows, encoding = file_utils.readlines_with_detected_charset(
            str(p), ["utf-8", "ascii"]
        )
        assert rows is None
        assert encoding is None
```

- [ ] **Step 2:** Run `python3 -m pytest test/test_file_utils.py -v` → FAIL (function missing).

- [ ] **Step 3: Implement** in `tools/utils/file_utils.py`:

```python
def readlines_with_detected_charset(
    filename: str, encodings: list[str]
) -> tuple[list[str] | None, str | None]:
    """Read all lines from filename, trying encodings in order.

    Returns (rows, encoding) for the first encoding that decodes without
    error, or (None, None) if none does. The encodings list is caller-owned:
    importers have intentionally different lists (e.g. interlab4 files are
    often utf-16) — never unify them here.
    """
    for encoding in encodings:
        try:
            with open(filename, encoding=encoding) as f:
                return f.readlines(), encoding
        except UnicodeDecodeError:
            continue
    return None, None
```

(Match the file's existing typing style — it uses `Iterator`/`Optional` imports from typing; use the same convention the file already uses if it differs from the above.)

- [ ] **Step 4:** Tests pass.

- [ ] **Step 5: Adopt in import_fieldlogger.** In `select_file_and_parse_rows`, the current loop tries each encoding, calling `common_utils.get_delimiter(filename=..., charset=encoding, ...)` then `open(...)`+`readlines()`+`row_parser`. Restructure to decode ONCE via the helper, preserving exact behavior:

```python
        observations = []
        for filename in filenames:
            filename = ru(filename)
            rows, encoding = file_utils.readlines_with_detected_charset(
                filename, ["utf-8", "cp1252"]
            )
            if rows is None:
                continue
            delimiter = file_utils.get_delimiter_from_file_rows(
                rows, filename=filename, delimiters=[";", ","], num_fields=5
            )
            if delimiter is None:
                return None
            observations.extend(row_parser(rows, delimiter))
```

CAUTION — verify before using `get_delimiter_from_file_rows`: read both `file_utils.get_delimiter` and `file_utils.get_delimiter_from_file_rows` signatures/behavior first. `get_delimiter` opens the file itself with the charset; `get_delimiter_from_file_rows` works on already-read rows. If their signatures or not-found behavior differ (e.g. ask-user fallback inside `get_delimiter`), replicate the OLD behavior exactly — the old code returned None from the whole method when delimiter was None, and silently skipped a file when ALL encodings failed (the `for/else` break pattern). If exact equivalence via `get_delimiter_from_file_rows` is not achievable, keep calling `get_delimiter(filename=..., charset=encoding, ...)` with the detected encoding instead — the helper still removes the decode loop. Behavior must be identical; when in doubt report DONE_WITH_CONCERNS.

Add `from midvatten.tools.utils import file_utils` to import_fieldlogger's imports (module-level) if not present.

- [ ] **Step 6:** Run `python3 -m pytest test/test_import_fieldlogger.py test/test_import_fieldlogger_backends.py test/test_file_utils.py -q` → all pass.

- [ ] **Step 7:** Commit: `feat: charset decode-with-fallback helper; adopt in fieldlogger import`

### Task 2: Sweep — exceptions + string_utils + file_utils groups

Transformation rule (per name): in each production caller file, ensure a module-level import of the source module (`from midvatten.tools.utils import string_utils` etc. — or extend an existing one), and rewrite `common_utils.NAME(` → `sourcemodule.NAME(` (also bare references like `except common_utils.UsageError`). Do NOT remove the `common_utils` import if the file still uses native common_utils names (most do). Do NOT touch the re-export lines in common_utils itself.

Names and source modules (verified):
- exceptions: `UsageError`, `UserInterruptError`
- string_utils: `returnunicode`, `anything_to_string_representation`, `isfloat`, `isinteger`, `isdate`, `lists_to_string`, `lstrip`, `rstrip`, `tr`, `unicode_2_utf8`
- file_utils: `get_delimiter`, `get_delimiter_from_file_rows`, `ask_for_delimiter`, `tempinput`, `write_printlist_to_file`

**Method:** grep, don't trust any pre-made list:
```bash
grep -rn "common_utils\.\(UsageError\|UserInterruptError\|returnunicode\|anything_to_string_representation\|isfloat\|isinteger\|isdate\|lists_to_string\|lstrip\|rstrip\|unicode_2_utf8\|get_delimiter\|get_delimiter_from_file_rows\|ask_for_delimiter\|tempinput\|write_printlist_to_file\)" --include="*.py" . --exclude-dir=test --exclude-dir=.worktrees --exclude-dir=.claude --exclude-dir=_pkgroot
```
(also the same for `midvatten_utils\.` prefix, and separately FOR test/ — test files using these names directly should migrate the same way; `mock.patch` targets naming these via any `...common_utils.NAME` path must move to `midvatten.tools.utils.<sourcemodule>.NAME` ONLY for names whose production callers were migrated in this task.)

NOTE: `common_utils.tr` — check carefully; `tr` is also a common local idiom. Only rewrite attribute accesses on the modules.

- [ ] **Step 1:** Build the live grep list. **Step 2:** Apply rewrites + imports. **Step 3:** Update test direct-accesses and patch targets for these names. **Step 4:** Run the test files corresponding to every touched production file (e.g. touched import_interlab4.py → run test_import_interlab4*.py). **Step 5:** `ruff check` touched files (no new errors), `ruff format --check`. **Step 6:** Commit: `refactor: import exceptions/string_utils/file_utils names from source modules`

### Task 3: Sweep — layer_utils group

Names: `find_layer`, `get_active_layer`, `get_qgis_vector_layers`, `get_selected_features_as_tuple`, `get_selected_object_names`, `selection_check`, `strat_selection_check`, `verify_layer_selection`.

Same method as Task 2 (grep both `common_utils.` AND `midvatten_utils.` prefixes — `midvatten_utils.find_layer` has production callers in export_data.py per test patch evidence). Known patch targets to move (verify each is still accurate at execution time):
- `"midvatten.tools.utils.midvatten_utils.find_layer"` in test/test_export_data.py (7 sites) → `"midvatten.tools.utils.layer_utils.find_layer"` (only if export_data.py production call is migrated in this task)
- `"midvatten.tools.sectionplot.common_utils.find_layer"` in test_sectionplot*.py (5 sites)
- `"midvatten.tools.utils.common_utils.get_selected_features_as_tuple"` (test_import_general_csv_gui_backends.py, test_calculate_statistics.py, test_export_data.py)
- `"midvatten.tools.sectionplot.common_utils.get_selected_object_names"` (test_piper.py, test_w_flow_calc_aveflow_spatialite.py, test_sectionplot_tem_spatialite.py)

- [ ] Steps as Task 2. Tests to run: all test files corresponding to touched production files (expect: export_data, sectionplot suite, piper, w_flow_calc_aveflow, calculate_statistics, import_general_csv backends, stratigraphy...). Commit: `refactor: import layer_utils names from source module`

### Task 4: Sweep — dialog_utils group

Names: `Askuser`, `NotFoundQuestion`, `HtmlDialog`, `ask_for_export_crs`, `ask_user_about_stopping`.

Same method. Known patch-target families to move (verify live): `...common_utils.Askuser` (test_w_flow_calc_aveflow_spatialite, test_wlevels_calc_calibr, test_import_fieldlogger_backends, test_import_general_csv_gui, test_import_interlab4, test_datetime_parity), `...common_utils.NotFoundQuestion` (test_import_interlab4*, test_interlab4_bulk_editor_integration, test_import_fieldlogger*, test_import_logger).

IMPORTANT for patch targets of the form `"midvatten.tools.import_data_to_db.common_utils.Askuser"`: after migrating import_data_to_db.py to `dialog_utils.Askuser`, the equivalent target is `"midvatten.tools.utils.dialog_utils.Askuser"` (one canonical path; the module-attribute is shared).

- [ ] Steps as Task 2. Tests: the listed test files. Commit: `refactor: import dialog_utils names from source module`

### Task 5: Mark the aggregator re-export blocks as external API

In `tools/utils/common_utils.py` (top re-export block) and `tools/utils/midvatten_utils.py` (re-export imports), add a short comment above each block:

```python
# Re-exports below are PUBLIC API for external consumers (midv_addons imports
# these via common_utils/midvatten_utils). Do not remove or rename them even
# when no in-repo caller remains. See docs/superpowers/plans/
# 2026-06-10-maintainability-refactor-review.md (midv_addons contract).
```

- [ ] Add comments; `ruff format --check`; commit: `docs: mark aggregator re-exports as midv_addons public API`

### Task 6: Verification

- [ ] `ruff check` + `ruff format` over changed files (pre-existing errors on untouched lines are out of scope).
- [ ] Invoke `simplify` skill over the branch diff.
- [ ] Run midv_addons compat check: `cd ~/dev/midv_addons && python3 -m pytest midv_addons/test/test_midvatten_compat.py -q` (if nose-only, try `python3 -m pytest` first; report if it can't run).
- [ ] FULL test suite in the worktree (`python3 -m pytest test/ -q`, ~33-43 min) — this slice touches enough files to be a sprint boundary. Known pre-existing failures (if any) must match a baseline run of ai_test; when in doubt, run baseline too.
- [ ] Final whole-branch review, then finishing-a-development-branch (merge target ai_test, ask user).
