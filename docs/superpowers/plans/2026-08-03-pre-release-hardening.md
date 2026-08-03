# Pre-Release Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the security stragglers, packaging blocker, and UX violations found in the 2026-08-03 pre-release review, so ai_test is safe, packageable, and feels polished.

**Architecture:** No structural changes. Point fixes to the import SQL builder, report generators, and packaging script; a plugin-level dialog-reload mechanism; mechanical migration of outcome popups to `MessagebarAndLog`; small extractions (symbology error helper, stored-settings mixin, shared selection-check helper).

**Tech Stack:** Python 3, QGIS 3.40+ (Qt5 **and** Qt6 via `qgis.PyQt`), SQLite/SpatiaLite + PostgreSQL/PostGIS, pytest.

## Global Constraints

- **Qt5 AND Qt6 must both work.** Only import Qt through `qgis.PyQt`. Matplotlib backends only via `tools/utils/mpl_compat.py`. Never call `matplotlib.use(...)`. When adding new dialog code, use the enum forms already used in the codebase (e.g. `QtWidgets.QMessageBox.Yes`, `Qt.TextSelectableByMouse`) — they resolve on both bindings through `qgis.PyQt`; do not introduce Qt6-only `QMessageBox.StandardButton.Yes` spellings.
- **SQL safety:** identifiers via `ident()`/`quote_ident()`/`sql_ident()` (`tools/utils/db_utils/dialect.py`), values via DB-API binding (`?` SQLite, `%s` PostgreSQL). Never interpolate untrusted strings.
- **Never change database schemas** (tables, columns, views).
- **User-facing strings** wrapped in `QCoreApplication.translate("Context", "text")`.
- **Messaging doctrine:** modal dialogs ONLY for decisions the user must make. Outcomes/info/errors → `message_utils.MessagebarAndLog` (short translated `bar_msg`, details in `log_msg`). No instructional popups. See the "UX doctrine for popups" section below.
- **UX doctrine for this release:** *familiar but polished* — keep existing wording/flow recognizable to long-time users; change the mechanism (modal→bar, freeze→feedback, "restart the dialog"→auto-reload), not the vocabulary, unless the wording itself is broken.
- **Tests:** mock via `@mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")` with param `mock_messagebar`; print `mock_messagebar.mock_calls` before assert groups; mark `@pytest.mark.spatialite` / `@pytest.mark.postgis`. Never change test reference data.
- **midv_addons contract:** `common_utils.X` / `db_utils.X` re-exports, `midvatten_defs`, `GeneralCsvImportGui` signature, `test/utils_for_tests` are public API. After touching shared modules run `~/dev/midv_addons` `test_midvatten_compat.py`.
- **Between tasks run only the relevant test file(s)**; full suite (~35-45 min) only in the final task.
- Use `python3`. Run `ruff check --fix .` and `ruff format .` after each task's code changes.
- All imports module-level (no imports inside functions), except documented optional-dependency guards (`try: import psycopg2 / except ImportError`).
- **This work happens in a dedicated git worktree** (per project workflow). Do not fold worktree/branch cleanup into any task here — that is a separate human-gated pass.

---

## UX doctrine for popups (read before Tasks 9–14)

The review found 34 `pop_up_info()` sites, ~9 direct `QMessageBox`, and 11 `QInputDialog`. Most are not decisions. This is the single biggest lever on the "polished" feel, because a modal that steals focus and demands a click for something the user didn't need to decide is exactly what reads as "clunky". The fix is not to invent new UI — it is to route each message to the mechanism QGIS users already expect.

**Triage every popup with three questions, in order:**

1. **Does the program need an answer to continue?** (Yes/No, Overwrite/Cancel, choose-a-value) → this is a **decision** → keep it modal (`QMessageBox.question`, `Askuser`, or a purpose-built `QDialog`). Give buttons *verbs* ("Import anyway" / "Cancel"), not "Ok". These stay.
2. **Is it reporting what happened?** (success, "nothing selected", "file skipped", an error) → this is an **outcome** → `MessagebarAndLog`, never a modal. The message bar is non-blocking, dismissable, and native to QGIS.
3. **Is it telling the user to do something the program should do itself?** (e.g. "restart the dialog to load the change") → this is a **smell** → redesign so the program does it (apply → reload widgets in place → brief confirmation bar).

**Polished patterns to apply consistently:**

- **Level = meaning.** `info` = success / neutral outcome (short `duration=4`). `warning` = something was skipped or degraded but the operation continued. `critical` = the operation was aborted. Once levels are consistent, the bar's colour becomes information.
- **Errors never dump internals to the bar.** `bar_msg` = one translated sentence: what failed + what to do next. `log_msg` = traceback / SQL / row data. The canonical shape already exists at `tools/utils/db_utils/execution.py:44-54` — copy it.
- **Batch/loop errors are collected, not stacked.** Never one dialog (or one bar) per bad row. Accumulate into a list; emit **one** summary at the end: bar = "N rows skipped, see log message panel", log = the N details.
- **One situation, one wording, one mechanism.** "Nothing selected" / "no layer" get a single shared helper (Task 9). Long-time users should see the same sentence wherever it occurs.
- **Long operations show progress.** Wait cursor is the floor. Anything looping over N DB items gets a `QProgressDialog` with a working Cancel — the reference implementation is `tools/export_spatialite.py:220-266`.

The tasks below implement this doctrine. Familiarity is preserved by reusing the existing message *text* wherever it is already good; only the *delivery* changes.

---

### Task 1: Fix the packaging script (release blocker)

**Files:**
- Modify: `plugin_zip_and_upload.py:27-35`
- Test: `test/test_plugin_zip.py` (new)

**Interfaces:**
- Produces: corrected `IGNORE_FOLDERS` / `IGNORE_FILES` / `IGNORE_FILESUFFIX` constants consumed by `create_zipfile()`.

Context: the current `IGNORE_FOLDERS` says `"tests"` but the directory is `test`; `.venv/`, `.worktrees/`, `docs/` etc. are missing entirely. A simulated build produced 18,798 files / 1.4 GB (real payload ≈ 5 MB).

- [ ] **Step 1: Write the failing test**

```python
# test/test_plugin_zip.py
"""Guards the packaging exclusion lists in plugin_zip_and_upload.py."""

import plugin_zip_and_upload as pz

MUST_IGNORE_FOLDERS = {
    ".git", "__pycache__", "test", ".venv", ".worktrees",
    ".logger-import-worktree", ".claude", ".cursor", ".superpowers",
    ".pytest_cache", ".ruff_cache", ".idea", "docs", "scripts", "_pkgroot",
}
MUST_IGNORE_FILES = {
    ".gitignore", "plugin_zip_and_upload.py", "conftest.py", "pytest.ini",
    "pyproject.toml", ".coveragerc", "CLAUDE.md", ".claudeignore",
    ".cursorignore",
}
MUST_IGNORE_SUFFIXES = {".pyc", ".zip", ".swp", ".swo", ".orig", ".rej"}


def test_ignore_folders_cover_dev_dirs():
    assert MUST_IGNORE_FOLDERS.issubset(set(pz.IGNORE_FOLDERS))


def test_ignore_files_cover_dev_files():
    assert MUST_IGNORE_FILES.issubset(set(pz.IGNORE_FILES))


def test_ignore_suffixes_cover_editor_artifacts():
    assert MUST_IGNORE_SUFFIXES.issubset(set(pz.IGNORE_FILESUFFIX))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest test/test_plugin_zip.py -x`
Expected: FAIL (`"test" not in IGNORE_FOLDERS`, etc.)

- [ ] **Step 3: Fix the constants**

```python
IGNORE_FOLDERS = [
    ".git", "arkiv", "arkiv_o_dok", "__pycache__", "tests", "test", ".idea",
    ".venv", ".worktrees", ".logger-import-worktree", ".claude", ".cursor",
    ".superpowers", ".pytest_cache", ".ruff_cache", "docs", "scripts",
    "_pkgroot",
]
IGNORE_FILES = [
    ".gitignore",
    "plugin_zip_and_upload.py",
    "compile_and_prepare_for_upload_notes.txt",
    ":",
    "conftest.py",
    "pytest.ini",
    "pyproject.toml",
    ".coveragerc",
    "CLAUDE.md",
    ".claudeignore",
    ".cursorignore",
    "midvatten.pro",
    "CHANGELOG_HISTORY",
    ".swo",
    ".swp",
]
IGNORE_FILESUFFIX = (".pyc", ".zip", ".swp", ".swo", ".orig", ".rej")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest test/test_plugin_zip.py -x`
Expected: PASS

- [ ] **Step 5: Smoke-check the produced file list.** Run this check (do not commit any temporary edits):

```bash
python3 - <<'EOF'
import os
import plugin_zip_and_upload as pz
count = 0
for root, dirs, files in os.walk("."):
    dirs[:] = [d for d in dirs if d not in pz.IGNORE_FOLDERS]
    for fname in files:
        if fname in pz.IGNORE_FILES or fname.endswith(pz.IGNORE_FILESUFFIX):
            continue
        count += 1
print("files that would ship:", count)
EOF
```
Expected: on the order of 400–800 files, NOT 18,000+.

- [ ] **Step 6: Also add `.swo` and `.claude/` to `.gitignore`** (`.gitignore` currently has `.swp` and only `.claude/worktrees/`). Do NOT delete the stray `.swo` / worktrees — cleanup of existing artifacts is a separate human-gated task, not part of this plan.

- [ ] **Step 7: Commit**

```bash
git add plugin_zip_and_upload.py test/test_plugin_zip.py .gitignore
git commit -m "fix(packaging): exclude dev dirs and editor artifacts from plugin zip"
```

---

### Task 2: Metadata, dependency declarations, README

**Files:**
- Modify: `metadata.txt:14` (experimental flag), `requirements.txt`, `README.md`, `pyproject.toml`

- [ ] **Step 1:** In `metadata.txt` set `experimental=True` (version is `1.9.0b30`, a beta must not ship to the stable channel). Also fix the changelog reference text `see separate document changelog_history` → `see separate document CHANGELOG_HISTORY`.
- [ ] **Step 2:** In `requirements.txt` add (with comments):

```
numpy
pandas
matplotlib
# Optional — only needed for PostgreSQL/PostGIS databases:
psycopg2
```

- [ ] **Step 3:** Add an **Installation & dependencies** section at the top of `README.md`, before developer content: QGIS ≥ 3.40; required Python packages numpy/pandas/matplotlib (installed via the `qpip` plugin dependency on most platforms); `psycopg2` required only for PostGIS; link to `metadata.txt` changelog. Move the "Coding style" section under a `## Development` heading.
- [ ] **Step 4:** Sync `pyproject.toml` `version = "0.1.0"` → `"1.9.0b30"` (cosmetic but a trap).
- [ ] **Step 5: Commit** — `git commit -m "chore(release): mark beta experimental, declare psycopg2, add install docs"`

---

### Task 3: Make psycopg2 truly optional

**Files:**
- Modify: `tools/utils/db_utils/connection.py:16`, `tools/import_data_to_db.py:31-32`, `tools/prepareforqgis2threejs.py:26`
- Test: `test/test_optional_psycopg2.py` (new)

**Interfaces:**
- Produces: `PostgreSQLBackend` may be `None` in `connection.py` when psycopg2 is absent; backend factory raises a translated, user-visible error instead of an ImportError at plugin load.

Context: `backends/postgresql.py` imports psycopg2 hard (fine — only import that module when available), but `connection.py:16` imports it at plugin startup, and `import_data_to_db.py` / `prepareforqgis2threejs.py` import psycopg2 directly. On a QGIS install without psycopg2 the whole plugin fails to load. Note `helpers.py:13-16` already guards it correctly — use that as the pattern.

- [ ] **Step 1: Write the failing test** (block psycopg2 in a fresh subprocess so the real interpreter's already-imported psycopg2 doesn't interfere — Python-first, no shell string parsing):

```python
# test/test_optional_psycopg2.py
import subprocess
import sys
import textwrap


def test_core_modules_import_without_psycopg2():
    """The plugin must load SpatiaLite-only when psycopg2 is unavailable."""
    code = textwrap.dedent(
        """
        import sys
        # Make any import of psycopg2 raise ImportError:
        for name in list(sys.modules):
            if name == "psycopg2" or name.startswith("psycopg2."):
                del sys.modules[name]
        sys.modules["psycopg2"] = None
        import importlib
        importlib.import_module("midvatten.tools.utils.db_utils.connection")
        importlib.import_module("midvatten.tools.import_data_to_db")
        importlib.import_module("midvatten.tools.prepareforqgis2threejs")
        print("OK")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "OK" in result.stdout, result.stderr
```

- [ ] **Step 2:** Run it, expect ImportError in stderr (FAIL). Run: `python3 -m pytest test/test_optional_psycopg2.py -x`
- [ ] **Step 3:** In `connection.py` (replace the hard import at line 16):

```python
try:
    from midvatten.tools.utils.db_utils.backends.postgresql import PostgreSQLBackend
except ImportError:  # psycopg2 missing — PostGIS support unavailable
    PostgreSQLBackend = None
```

and in the backend factory (`connection.py` ~line 61-67), before constructing `PostgreSQLBackend`:

```python
if PostgreSQLBackend is None:
    raise UsageError(
        QCoreApplication.translate(
            "DbConnectionManager",
            "PostgreSQL support requires the python package psycopg2. "
            "Install it (for example: pip install psycopg2) and restart QGIS.",
        )
    )
```

Executor: import `UsageError` from `midvatten.tools.utils.exceptions` if not already imported; confirm it surfaces as a user-visible message via the plugin's `general_exception_handler`. If a more specific db-error type is already caught-and-shown by callers of the factory, use that instead — the requirement is a translated actionable message, not a traceback.

- [ ] **Step 4:** In `import_data_to_db.py` (lines 31-32) and `prepareforqgis2threejs.py` (line 26) guard the imports:

```python
try:
    import psycopg2
    import psycopg2.extras
except ImportError:  # optional — only needed for PostGIS
    psycopg2 = None
```

Then grep each `psycopg2.` usage in both files. PG-only call paths (`psycopg2.extras.execute_values`, `psycopg2.errors.*`) are only reached inside `dbconnection.is_postgresql()` branches — they cannot execute on a SQLite connection, so no further guarding is needed beyond the module-level fallback. For any exception-tuple that references `psycopg2.<Error>` outside such a branch, build a module constant:

```python
_IMPORT_INTEGRITY_ERRORS: tuple[type[Exception], ...] = (sqlite3.IntegrityError,)
if psycopg2 is not None:
    _IMPORT_INTEGRITY_ERRORS = _IMPORT_INTEGRITY_ERRORS + (psycopg2.IntegrityError,)
```

- [ ] **Step 5:** Run: `python3 -m pytest test/test_optional_psycopg2.py test/test_db_utils_spatialite.py test/test_import_data_to_db.py -x` — all PASS (local env has psycopg2, so the guarded paths must still work).
- [ ] **Step 6:** Run midv_addons compat: `cd ~/dev/midv_addons && python3 -m pytest -k test_midvatten_compat -x` — PASS.
- [ ] **Step 7: Commit** — `git commit -m "fix(deps): plugin loads and runs SpatiaLite-only when psycopg2 is absent"`

---

### Task 4: Gate the sys.path bootstrap to test environments

**Files:**
- Modify: `__init__.py:25-42`

Context: today the plugin prepends `/usr/share/qgis/python`, `/usr/lib/qgis/python`, and **its own directory** to `sys.path` inside the QGIS process — the last makes top-level names `tools`, `ui`, `definitions` importable process-wide and can shadow other plugins' modules. Only tests need this (`QGIS_PYTHON_PATH` is the tests' mechanism; in-repo imports use the `midvatten.` package prefix via `_pkgroot`).

- [ ] **Step 1:** Replace lines 25–42 with:

```python
# Test-harness bootstrap only: when pytest runs outside QGIS it sets
# QGIS_PYTHON_PATH so the qgis package can be imported. Inside a real QGIS
# session this env var is unset and sys.path is left untouched.
import os
import sys

_env_path = os.environ.get("QGIS_PYTHON_PATH")
if _env_path:
    for _p in _env_path.split(os.pathsep) + [
        "/usr/share/qgis/python",
        "/usr/lib/qgis/python",
        os.path.dirname(__file__),
    ]:
        if _p and os.path.isdir(_p) and _p not in sys.path:
            # Prepend so that the real QGIS modules win over any stubs.
            sys.path.insert(0, _p)
```

- [ ] **Step 2:** Verify tests still collect and run: `python3 -m pytest test/test_create_spatialite_db.py -x` — PASS. If collection breaks because the harness relied on the unconditional insert, fix how `QGIS_PYTHON_PATH` is set in `conftest.py`/CI, not the plugin.
- [ ] **Step 3: Commit** — `git commit -m "fix(init): stop polluting sys.path inside QGIS; bootstrap only under QGIS_PYTHON_PATH"`

---

### Task 5: Remove the Qt5-only matplotlib backend force

**Files:**
- Modify: `tools/calculate_level.py:26-28`

Context: `mpl.use("Qt5Agg")` contradicts Qt6 support; every other module goes through `mpl_compat`. ⚠️ Project history: an import-time `matplotlib.use()` was implicated in the detach_fig order-dependent test failures — this call may be load-bearing for suite-wide backend state, so verification here is broader than usual.

- [ ] **Step 1:** Delete the `import matplotlib as mpl` / `mpl.use("Qt5Agg")` lines. `calculate_level.py` has no other matplotlib usage (verified by grep). If a Qt-bound canvas import turns out to be needed after removal, take it from `mpl_compat` — never `mpl.use()`.
- [ ] **Step 2:** Run the backend-state-sensitive tests **in this order, in one pytest invocation** (order-dependence is the failure mode being guarded):

```bash
python3 -m pytest test/test_calclvl_spatialite.py test/test_customplot_spatialite.py test/test_sectionplot_spatialite.py -x
```
Expected: PASS. If a detach_fig-style failure appears, STOP — do not paper over it; re-read the detach_fig history (memory: `project_detach_fig_order_dependent_failure.md`) and report before proceeding.
- [ ] **Step 3: Commit** — `git commit -m "fix(qt6): drop Qt5Agg backend force in calculate_level; mpl_compat is the single source"`

---

### Task 6: Close the SQL stragglers in import_data_to_db.py

**Files:**
- Modify: `tools/utils/db_utils/dialect.py`, `tools/import_data_to_db.py:678,691,693,1059,1256`
- Test: `test/test_dialect_safe_type.py` (new) + `test/test_import_data_to_db.py`

**Interfaces:**
- Produces: `dialect.safe_type(data_type: str) -> str` — validates a declared column type for interpolation into `CAST(x AS <type>)`; returns it unchanged if safe, raises `UnsafeIdentifierError` (defined at `dialect.py:17`) otherwise.

Context: SQLite declared column types come back from `PRAGMA table_info` as arbitrary free text — a hostile `.sqlite` file controls them. Two `CAST` sites splice them raw (`:678`, `:1256`). Additionally the INSERT…SELECT column names (`:691`), the source/temp table name (`:693`), and the geometry `colname` (`:1059`) are interpolated without `ident()`, while the sibling `not_null_columns` branch three lines below correctly uses `ident()`. These are misses, not exceptions.

- [ ] **Step 1: Write the failing test for the type validator**

```python
# test/test_dialect_safe_type.py
import pytest

from midvatten.tools.utils.db_utils.dialect import safe_type, UnsafeIdentifierError


@pytest.mark.parametrize(
    "good",
    ["INTEGER", "integer", "TEXT", "REAL", "NUMERIC", "BLOB",
     "DOUBLE PRECISION", "VARCHAR(50)", "DECIMAL(10, 2)",
     "TIMESTAMP", "DATE", "BOOLEAN"],
)
def test_safe_type_allows_real_types(good):
    assert safe_type(good) == good


@pytest.mark.parametrize(
    "evil",
    ["TEXT) OR (SELECT 1) --", "INT; DROP TABLE x", "a\"b", "a'b",
     "int)--", ""],
)
def test_safe_type_rejects_injection(evil):
    with pytest.raises(UnsafeIdentifierError):
        safe_type(evil)
```

- [ ] **Step 2:** Run: `python3 -m pytest test/test_dialect_safe_type.py -x` — FAIL (no `safe_type`).
- [ ] **Step 3: Implement `safe_type` in `dialect.py`** (near the existing `UnsafeIdentifierError`):

```python
import re

# A SQL column type is an identifier word, optionally repeated (e.g.
# "DOUBLE PRECISION", "TIMESTAMP WITH TIME ZONE"), optionally with a
# parenthesised size/precision (e.g. "VARCHAR(50)", "DECIMAL(10, 2)").
_TYPE_RE = re.compile(
    r"^[A-Za-z][A-Za-z ]*(\(\s*\d+\s*(,\s*\d+\s*)?\))?$"
)


def safe_type(data_type: str) -> str:
    """Validate a declared column type before interpolating it into
    ``CAST(expr AS <type>)``. SQLite lets a .sqlite file declare a column
    with an arbitrary type string, so this is an untrusted-input guard.
    Returns the type unchanged when safe; raises UnsafeIdentifierError."""
    if not isinstance(data_type, str) or not _TYPE_RE.match(data_type.strip()):
        raise UnsafeIdentifierError(f"Unsafe column type: {data_type!r}")
    return data_type.strip()
```

- [ ] **Step 4:** Run: `python3 -m pytest test/test_dialect_safe_type.py -x` — PASS.
- [ ] **Step 5: Apply at both CAST sites in `import_data_to_db.py`.** Import `safe_type` at module top (`from midvatten.tools.utils.db_utils.dialect import safe_type`). At `:678`:

```python
sourcecols.append(
    f"""(CASE WHEN {dbconnection.ident(colname)} IS NOT NULL\n    THEN CAST({dbconnection.ident(colname)} AS {safe_type(column_headers_types[colname])}) ELSE {null_replacement} END)"""
)
```

At `:1256`:

```python
cast_exprs = ", ".join(
    f'CAST("b".{dbconnection.ident(k)} AS {safe_type(column_headers_types[to_list[idx]]))}'
    for idx, k in enumerate(from_list)
)
```

- [ ] **Step 6: Quote the remaining identifiers.** At `:691` wrap each dest column: `", ".join(dbconnection.ident(c) for c in sorted(existing_columns_in_dest_table))`. At `:693` the `source_table` value is `self.temptable_name` — pass it through `dbconnection.ident(self.temptable_name)`. At `:1059` `create_geometry_sql` builds `{colname}` from `geom_col`; change `kwargs = {"colname": dbconnection.ident(geom_col), "null": null_replacement}` and confirm the CASE expression around it still reads correctly.
- [ ] **Step 7: Run the import tests on BOTH backends**

```bash
python3 -m pytest test/test_import_data_to_db_spatialite.py test/test_import_data_to_db_postgis.py -x
```
Expected: PASS. (If PostGIS shows `about_db_pkey` UniqueViolation, another agent is using the shared test DB — retry later, it is not your bug.)

- [ ] **Step 8: Commit** — `git commit -m "fix(sql): validate CAST types and quote identifiers in import INSERT...SELECT"`

---

### Task 7: HTML-escape report output (stored XSS)

**Files:**
- Create: `tools/utils/html_utils.py`
- Modify: `tools/drillreport.py` (`_row` at :220, `write_obsid` at :233), `tools/wqualreport.py:314-320`, `tools/wqualreport_compact.py:670+`, `tools/wqualreport_core.py:47`
- Test: `test/test_html_escaping.py` (new)

**Interfaces:**
- Produces: `html_utils.esc(value) -> str` — `returnunicode` + `html.escape`, safe for interpolation into report HTML.

Context: report generators concatenate free-text DB columns (comment, geology, obsid, parameter) straight into HTML, write to a temp file, and open it at a `file://` origin in the user's browser. On a shared PostGIS DB that is stored XSS. There is no `html.escape` anywhere in the codebase today. The `_strip_html` flag in `export_data.py:283` confirms HTML content lands in these columns.

- [ ] **Step 1: Write the failing test**

```python
# test/test_html_escaping.py
from midvatten.tools.utils.html_utils import esc


def test_esc_neutralizes_script():
    assert esc("<script>alert(1)</script>") == (
        "&lt;script&gt;alert(1)&lt;/script&gt;"
    )


def test_esc_escapes_quotes_and_amp():
    assert esc('a & "b" <c>') == "a &amp; &quot;b&quot; &lt;c&gt;"


def test_esc_handles_none():
    assert esc(None) == ""
```

- [ ] **Step 2:** Run: `python3 -m pytest test/test_html_escaping.py -x` — FAIL.
- [ ] **Step 3: Implement `tools/utils/html_utils.py`**

```python
"""Escaping helpers for report HTML written to disk and opened in a browser.

Report values come from user data (including shared PostGIS databases) and are
opened at a file:// origin, so every interpolated value must be escaped.
"""

import html

from midvatten.tools.utils.string_utils import returnunicode


def esc(value) -> str:
    """Return *value* as an HTML-safe string (None -> '')."""
    return html.escape(returnunicode(value), quote=True)
```

- [ ] **Step 4:** Run: `python3 -m pytest test/test_html_escaping.py -x` — PASS.
- [ ] **Step 5: Apply `esc()` to every interpolated *data* value** (not the static markup) in the report builders. Key sites:
  - `drillreport.py:_row` → `f"...{esc(label)}...{esc(value)}..."` — but check: some report cells intentionally contain markup the plugin itself built (e.g. nested tables). Escape only leaf DB values; where a helper is handed pre-built HTML, escape at the point the raw DB column enters, not at the outer concatenation. Trace each `rpt += <db value>` (e.g. `drillreport.py:233 rpt += obsid` → `rpt += esc(obsid)`).
  - `wqualreport.py:314-318` → `[esc(x) for x in sublist]` in both the header and data branches.
  - `wqualreport_compact.py` table writer → same treatment for cell values.
  - `wqualreport_core.py:47` title → already uses `ru(title)`; change to `esc(title)`.
- [ ] **Step 6: Guard against test-reference churn.** These reports have reference-data tests (`test_drillreport_*`, `test_wqualreport*`). Escaping changes output for values containing `< > & " '`. Run:

```bash
python3 -m pytest test/test_drillreport_spatialite.py test/test_wqualreport_spatialite.py -x
```
If a reference test fails, inspect the diff: if the only change is `&` / `<` becoming entities on genuine data values, the *reference data* legitimately changes here (this is the rare "explicitly told to" case — the fix is correct and the old output was the bug). If markup the plugin itself emits got escaped, you over-escaped — narrow the `esc()` calls to leaf values. Document which reference files changed and why in the commit body.
- [ ] **Step 7: Commit** — `git commit -m "fix(security): HTML-escape user data in generated reports (stored XSS)"`

---

### Task 8: Harden temp-file/dir creation

**Files:**
- Modify: `tools/wqualreport_core.py:19-24`, `tools/drillreport.py:58-60`, `tools/custom_drillreport.py:343-345`, `tools/utils/db_utils/backends/base.py:353`
- Test: `test/test_report_tempdir.py` (new)

**Interfaces:**
- Produces: report/CSV temp paths under a per-invocation `tempfile.mkdtemp()` directory instead of a fixed world-writable `/tmp/midvatten_reports`.

Context: fixed path `os.path.join(QDir.tempPath(), "midvatten_reports")` with fixed filenames and default umask is symlink/pre-creation attackable on shared Linux hosts (bandit B108), plus a TOCTOU between `exists()` and `makedirs()`. `base.py:353` writes `{table}.csv` into `gettempdir()` (table name is already validated by `sql_ident`, so this is only the predictable-name issue).

- [ ] **Step 1: Write the failing test** (the folder helper must not reuse a fixed shared path):

```python
# test/test_report_tempdir.py
import os

from midvatten.tools import wqualreport_core


def test_report_folder_is_private_and_unique():
    a = wqualreport_core.report_folder()
    b = wqualreport_core.report_folder()
    # Each call yields a fresh private dir, not a shared fixed one:
    assert a != b
    assert os.path.isdir(a)
    # Not group/other writable:
    mode = os.stat(a).st_mode
    assert not (mode & 0o022)
```

- [ ] **Step 2:** Run: `python3 -m pytest test/test_report_tempdir.py -x` — FAIL (current impl returns a shared fixed path).
- [ ] **Step 3: Change `wqualreport_core.report_folder()`**

```python
import tempfile

def report_folder() -> str:
    """Create and return a fresh private temp directory for a report."""
    return tempfile.mkdtemp(prefix="midvatten_report_")
```

`report_path()` already composes `report_folder()` + `REPORT_FILENAME`; leaving the filename fixed is fine now that the *directory* is private and unique.

- [ ] **Step 4: Apply the same `mkdtemp` pattern** in `drillreport.py:58-60` and `custom_drillreport.py:343-345` (replace the `os.path.join(QDir.tempPath(), "midvatten_reports")` + `makedirs` block). In `base.py:353` change the CSV path to `os.path.join(tempfile.mkdtemp(prefix="midvatten_csv_"), f"{table_name}.csv")`.
- [ ] **Step 5:** Run: `python3 -m pytest test/test_report_tempdir.py test/test_drillreport_spatialite.py -x` — PASS.
- [ ] **Step 6: Commit** — `git commit -m "fix(security): use private mkdtemp dirs for reports and CSV dumps"`

---

### Task 9: Shared selection-check helper (UX foundation)

**Files:**
- Modify: `tools/utils/layer_utils.py` (fix the broken string at :105; add helpers), and callers in Task 10.
- Test: `test/test_layer_utils.py` (extend or create)

**Interfaces:**
- Produces:
  - `layer_utils.warn_no_selection() -> None` — emits the single canonical "select at least one object" message via `MessagebarAndLog.warning`.
  - `layer_utils.warn_no_layer(field: str = "obsid") -> None` — canonical "select a layer with field X" message.
- These become the one mechanism every tool uses for "nothing selected" / "no suitable layer".

Context: the review found 9 wordings across 4 mechanisms for "nothing selected", and `layer_utils.py` contradicts itself internally (`:94` critical bar, `:105` broken `"""`-leaked string, `:111` `pop_up_info`). Consolidate to one helper, message-bar based. Keep the most familiar wording.

- [ ] **Step 1: Fix the leaked triple-quote at `layer_utils.py:105`** — the user-facing/translated string is literally `'"""Error, select exactly %s object in the qgis layer!'`. Remove the stray `"""`:

```python
message_utils.MessagebarAndLog.critical(
    bar_msg=tr(
        "selection_check",
        "Error, select exactly %s object in the qgis layer!",
    )
    % str(selectedfeatures)
)
```

(This changes a translation-catalogue key — acceptable, the old key was malformed.)

- [ ] **Step 2: Write the failing test**

```python
# test/test_layer_utils.py
from unittest import mock

from midvatten.tools.utils import layer_utils


@mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
def test_warn_no_selection_uses_warning_bar(mock_messagebar):
    layer_utils.warn_no_selection()
    print(mock_messagebar.mock_calls)
    assert mock_messagebar.warning.called
    assert not mock_messagebar.critical.called


@mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
def test_warn_no_layer_names_the_field(mock_messagebar):
    layer_utils.warn_no_layer("obsid")
    print(mock_messagebar.mock_calls)
    (_, _, kwargs) = mock_messagebar.warning.mock_calls[0]
    assert "obsid" in kwargs["bar_msg"]
```

- [ ] **Step 3:** Run: `python3 -m pytest test/test_layer_utils.py -x` — FAIL.
- [ ] **Step 4: Add the helpers to `layer_utils.py`**

```python
def warn_no_selection() -> None:
    """Canonical 'nothing selected' outcome (message bar, not a popup)."""
    message_utils.MessagebarAndLog.warning(
        bar_msg=tr(
            "selection_check",
            "Select at least one object in the layer first.",
        ),
        duration=4,
    )


def warn_no_layer(field: str = "obsid") -> None:
    """Canonical 'no suitable layer' outcome (message bar, not a popup)."""
    message_utils.MessagebarAndLog.warning(
        bar_msg=tr(
            "selection_check",
            "Select a layer that has a '%s' field first.",
        )
        % field,
        duration=4,
    )
```

Also change `layer_utils.py:111` (`pop_up_info(...)` for the missing-obsid-field case) to call `warn_no_layer("obsid")`.

- [ ] **Step 5:** Run: `python3 -m pytest test/test_layer_utils.py -x` — PASS.
- [ ] **Step 6: Commit** — `git commit -m "feat(ux): single message-bar helper for 'nothing selected' / 'no layer'"`

---

### Task 10: Migrate outcome popups to the message bar

**Files (all `pop_up_info` → `MessagebarAndLog`, or → the Task 9 helper):**
- Test: for each tool touched, add/extend a `mock_messagebar`-based test asserting the bar is used and no `pop_up_info` is called.

**Interfaces:**
- Consumes: `layer_utils.warn_no_selection` / `warn_no_layer` (Task 9), `MessagebarAndLog` (info/warning/critical).

Context: these are outcome/info modals that should never steal focus. This is mechanical — **keep the existing sentence** wherever it is already clear (familiarity), change only the mechanism. Do NOT touch the genuine-decision popups (`export_spatialite.py:72`, `import_interlab4.py:943`, `loggereditor.py:1010,1784`, `obsid_assignment_dialog.py:459`, `dialog_utils.py:52`, `ask_for_charset`, `ask_for_delimiter`, `ask_for_export_crs`).

**Migration inventory** (each: `pop_up_info` → mechanism). Level rule: "must select / nothing to do" = `warning`; "operation aborted" = `critical`; neutral outcome = `info`, `duration=4`.

| file:line | new mechanism |
|---|---|
| `drillreport.py:66` "Must select one or more obsids!" | `layer_utils.warn_no_selection()` |
| `custom_drillreport.py:351` "Must select one or more obsids!" | `layer_utils.warn_no_selection()` |
| `tsplot.py:178,185` "select at least one point…" | `warning` bar, keep wording |
| `xyplot.py:221,227` "select at least one point with xy data" | `warning` bar, keep wording |
| `stratigraphy.py:84` "No selection / No features are selected" | `warning` bar |
| `stratigraphy.py:97` "Data sanity problem, obsid: %s" | `warning` bar, obsid in `bar_msg` |
| `calculate_level.py:83,98,152,165` "Adjustment aborted! …" | `critical` bar, keep wording |
| `loggereditor.py:3152,3161,3269,3302,3311` no-match/obsid-changed outcomes | `warning`/`info` bar per meaning |
| `export_fieldlogger.py:929,936` "Writing of file failed!: %s" | `critical` bar + `log_msg=str(e)` |
| `import_fieldlogger.py:575` "Must choose at least one parameter import method" | `warning` bar (also remove the duplicate `pop_up_info`+`critical` double-notify) |
| `import_general_csv_gui.py:917` "Layer %s is currently in editing mode." | `warning` bar |
| `create_db.py:180` "needs spatialite4…" | `critical` bar; improve text (Task note below) |

- [ ] **Step 1 (per tool): Write the failing test.** Example for drillreport:

```python
@mock.patch("midvatten.tools.utils.message_utils.pop_up_info")
@mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
def test_no_obsid_uses_bar_not_popup(mock_messagebar, mock_popup, ...):
    # invoke the no-selection path
    ...
    print(mock_messagebar.mock_calls)
    assert not mock_popup.called
    assert mock_messagebar.warning.called
```

- [ ] **Step 2:** Run it — FAIL (popup still used).
- [ ] **Step 3:** Apply the swap from the table. For `create_db.py:180`, improve the message while migrating: `"This database needs SpatiaLite 4 or newer, which is not available in your QGIS install. Update QGIS or install a newer SpatiaLite to create the database."`
- [ ] **Step 4:** Run the tool's test file(s) — PASS. Suggested batching by test file: `test_drillreport_*`, `test_calclvl_*`, `test_import_*`. Commit per logical group, e.g.:

```bash
git commit -m "feat(ux): report/plot 'nothing selected' outcomes use the message bar"
git commit -m "feat(ux): import outcome messages use the message bar, not modals"
```

- [ ] **Step 5:** Grep to confirm no *outcome* `pop_up_info` remains outside the decision list: `grep -rn 'pop_up_info' tools/ | grep -v test`. Every remaining hit must be a genuine decision or moved to Task 12/13.

---

### Task 11: Fix strat_symbology error reporting (worst module)

**Files:**
- Modify: `tools/strat_symbology.py:215-338` (16 sites)
- Test: `test/test_strat_symbology.py` (create if absent — a unit test around one `add_generic_symbology` failure)

**Interfaces:**
- Consumes: `MessagebarAndLog.warning` with `bar_msg` + `log_msg`.

Context: 16 sites do `except Exception: MessagebarAndLog.info(bar_msg=traceback.format_exc())` — a full traceback in a calm blue info bar, up to ~10 stacked from one click, untranslated. The canonical shape is `execution.py:44-54`.

- [ ] **Step 1: Add a module-level helper in `strat_symbology.py`**

```python
def _report_symbology_error(symbology_name: str, exc: Exception) -> None:
    message_utils.MessagebarAndLog.warning(
        bar_msg=QCoreApplication.translate(
            "StratSymbology",
            "Could not apply symbology '%s', see log message panel.",
        )
        % symbology_name,
        log_msg=traceback.format_exc(),
        duration=4,
    )
```

- [ ] **Step 2:** Replace all 16 `except` blocks. `StyleNotFoundError` and the bare `except Exception` collapse into one handler each per site:

```python
except (StyleNotFoundError, Exception) as e:
    _report_symbology_error(symbology, e)
```

(Executor: `StyleNotFoundError` is a subclass of `Exception`, so a single `except Exception as e` suffices; keep the specific type only if a different message is wanted for missing-style vs other errors — the review says one message is fine.)

- [ ] **Step 3: Test** — build a layer group where one style name is missing, assert exactly one `warning` call with the traceback in `log_msg`, not `bar_msg`, and `info` is not used for the error.
- [ ] **Step 4:** Run: `python3 -m pytest test/test_strat_symbology.py -x` — PASS.
- [ ] **Step 5: Commit** — `git commit -m "fix(ux): strat_symbology reports short warnings, tracebacks go to the log"`

---

### Task 12: interlab4 — collect parse errors instead of one modal per row

**Files:**
- Modify: `tools/import_interlab4.py:460-600` (`parse`)
- Test: `test/test_import_interlab4.py` (extend)

**Interfaces:**
- Produces: `parse()` accumulates row/file errors in a list and emits ONE summary via `MessagebarAndLog` after the loop; no `pop_up_info` inside the loop.

Context: this is the review's worst modal-in-loop. The obsid-*assignment* rework did not touch these — they are structural file-parse errors in the reader. `:570` ("parameter missing on row %s") fires once per bad row; `:474` and `:580` are bounded per file. All three should feed one summary.

- [ ] **Step 1: Write the failing test** — feed `parse()` an interlab4 file with 3 rows missing the `parameter` column; assert `pop_up_info` is NOT called and exactly one `MessagebarAndLog.warning` summarises "3 rows skipped".

```python
@mock.patch("midvatten.tools.utils.message_utils.pop_up_info")
@mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
def test_parse_collects_row_errors(mock_messagebar, mock_popup, tmp_path):
    f = tmp_path / "bad.txt"
    f.write_text(<interlab4 content with 3 parameter-less data rows>, encoding="cp1252")
    Interlab4Import.parse(<instance>, [str(f)])
    print(mock_messagebar.mock_calls)
    assert not mock_popup.called
    warn_msgs = " ".join(str(c) for c in mock_messagebar.warning.mock_calls)
    assert "3" in warn_msgs
```

(Executor: reuse an existing interlab4 fixture from the current test file for valid structure, then delete the `parameter` cell from 3 data rows.)

- [ ] **Step 2:** Run — FAIL (modal per row).
- [ ] **Step 3: Refactor `parse()`.** Introduce a local `parse_errors: list[str] = []` at the top of the method. Replace the three `pop_up_info(...)` calls:
  - `:474` → `parse_errors.append(tr("Interlab4Import", "File %s: could not read file information, skipped.") % filename); continue`
  - `:570` → `parse_errors.append(tr("Interlab4Import", "%s: parameter column missing, row skipped.") % filename); continue` (drop the raw `cols` dump; put row detail in the log summary if wanted)
  - `:580` → `parse_errors.append(tr("Interlab4Import", "%s: data appeared before its metadata; file aborted.") % filename); file_error = True; break`
  After all files are processed, before `return all_lab_results`:

```python
if parse_errors:
    message_utils.MessagebarAndLog.warning(
        bar_msg=QCoreApplication.translate(
            "Interlab4Import",
            "%s parsing problem(s) while reading lab files, see log message panel.",
        )
        % len(parse_errors),
        log_msg="\n".join(parse_errors),
        duration=5,
    )
```

- [ ] **Step 4:** Run: `python3 -m pytest test/test_import_interlab4.py -x` — PASS.
- [ ] **Step 5: Commit** — `git commit -m "fix(ux): interlab4 collects parse errors into one summary, not a modal per row"`

---

### Task 13: Replace "restart the dialog" popups with confirm + auto-reload

**Files:**
- Modify: `tools/export_fieldlogger.py:656,682,1005`, `tools/import_fieldlogger.py:171`
- Test: `test/test_export_fieldlogger.py` / `test/test_import_fieldlogger.py` (extend)

**Interfaces:**
- Produces: each settings-changing action applies the change, refreshes the dialog's widgets in place, and confirms with a brief message bar — no "restart the dialog" instruction.

Context: these four popups exist because changing settings does not refresh the already-open dialog's widgets, so the tool asks the user to restart it. That is the "program telling the user to do the program's job" smell. The polished fix: rebuild the affected widgets from the new settings in place. Both dialogs already have the construction logic in `__init__`; factor the input-field construction into a method and call it after the change.

**Design note (familiar but polished):** the user's mental model is "I changed a setting, the dialog now reflects it." Auto-reload delivers exactly that with zero new concepts. If in-place rebuild proves too invasive this close to release, the acceptable fallback is close-and-reopen: emit a `reload_requested` signal the plugin connects to re-dispatch the tool (see `midvatten_plugin._dispatch`), preserving the persistent-tool tracking. Prefer in-place; use the signal only if rebuild touches too much.

- [ ] **Step 1 (export_fieldlogger): Extract the input-field build.** In `ExportToFieldLogger.__init__`, the block that constructs the parameter browser / parameter groups from stored settings becomes a method:

```python
def _rebuild_input_fields_from_settings(self) -> None:
    """(Re)build the parameter browser and group widgets from stored settings.
    Called from __init__ and after any settings change so the open dialog
    always reflects current settings."""
    ...  # move the existing construction code here; clear old widgets first
```

Call it at the end of `__init__` where that code used to be.

- [ ] **Step 2: Write the failing test** — after `restore_default_settings()`, assert `pop_up_info` is NOT called and the widgets reflect defaults (e.g. a known default parameter group is present); assert a brief `MessagebarAndLog.info` confirmation fired.
- [ ] **Step 3: Rewire the three export_fieldlogger sites.** In `restore_default_settings` (:656), `settings_strings_dialogs` (:682) and `clear_settings` (:1005): after saving settings, call `self._rebuild_input_fields_from_settings()`, then replace the `pop_up_info(...)` with:

```python
message_utils.MessagebarAndLog.info(
    bar_msg=QCoreApplication.translate(
        "ExportToFieldLogger", "Settings updated."
    ),
    duration=3,
)
```

- [ ] **Step 4 (import_fieldlogger:171):** same treatment — the `clear_settings_button` lambda currently saves settings then pops "Restart import Fieldlogger dialog". Extract an `_rebuild_from_settings()` for the parameter widgets, call it, and confirm with an `info` bar. Also unwind the awkward `lambda: [x() for x in [...]]` into a plain method `clear_settings(self)` connected to the button (cleaner, and needed to call the rebuild).
- [ ] **Step 5:** Run: `python3 -m pytest test/test_export_fieldlogger.py test/test_import_fieldlogger.py -x` — PASS.
- [ ] **Step 6: Commit** — `git commit -m "feat(ux): fieldlogger settings changes reload the dialog in place, no restart prompt"`

---

### Task 14: Fix the remaining UX widget mismatches (targeted, low-risk)

**Files:**
- Modify: `tools/export_fieldlogger.py:783` (Preview), `tools/drillreport.py:415-421` (debug SQL popup), `tools/utils/dialog_utils.py:40` (YesNo icon), and the untranslated shared-dialog strings at `dialog_utils.py:119,125,132`.

Context: a grab-bag of small "doesn't behave as expected" issues that add up to the polished feel. Each is independent; commit together.

- [ ] **Step 1: export_fieldlogger Preview (:783).** `QMessageBox.information(None, "Preview", output)` dumps the whole export payload into an unscrollable, unparented, untranslated modal. Replace with a proper resizable, scrollable, read-only dialog:

```python
dlg = QtWidgets.QDialog(self)
dlg.setWindowTitle(QCoreApplication.translate("ExportToFieldLogger", "Preview"))
layout = QtWidgets.QVBoxLayout(dlg)
text = QtWidgets.QPlainTextEdit(dlg)
text.setReadOnly(True)
text.setPlainText(output)
layout.addWidget(text)
buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close, parent=dlg)
buttons.rejected.connect(dlg.reject)
buttons.accepted.connect(dlg.accept)
layout.addWidget(buttons)
dlg.resize(700, 500)
dlg.exec()
```

- [ ] **Step 2: drillreport debug SQL (:415-421).** `pop_up_info(sql)` when `debug == "y"` is a dev affordance in a prod path. Route it to the log only: `message_utils.MessagebarAndLog.info(log_msg=sql)` — no modal. (If `debug` is never settable by users, this can simply be deleted; verify how `debug` is set before removing.)
- [ ] **Step 3: dialog_utils YesNo icon (:40).** `Askuser("YesNo")` uses `QMessageBox.information` (ⓘ icon) for a Yes/No question. Change to `QMessageBox.question`. This is a genuine decision dialog — it stays modal, only the icon is corrected.
- [ ] **Step 4: Translate the shared NotFoundQuestion strings.** `dialog_utils.py:119` `dialogtitle="Warning"`, `:125` `combobox_label="Similar values found in db (choose or edit):"`, `:132` `button_names=["Ignore","Cancel","Ok"]` are defaults on the most-seen import-mismatch dialog and render untranslated. Wrap each default in `tr("NotFoundQuestion", ...)`. Keep button object-name logic (`.lower()`) working — set `objectName` from the untranslated key, display text from the translated string. Adjust `button_clicked`/`set_answer_and_value` if they compare on display text (they compare on `objectName`, so translating display text is safe — verify).
- [ ] **Step 5: Tests.** Add a `mock_messagebar`/widget test for the Preview dialog (asserts a `QDialog` with a read-only `QPlainTextEdit`, not a `QMessageBox`), and a test that `NotFoundQuestion` button object-names remain the stable English keys after translation.
- [ ] **Step 6:** Run: `python3 -m pytest test/test_export_fieldlogger.py test/test_import_data_to_db_spatialite.py -x` — PASS (NotFoundQuestion is exercised through import).
- [ ] **Step 7: Commit** — `git commit -m "feat(ux): scrollable export preview, correct dialog icons, translate shared import dialog"`

---

### Task 15: Add progress feedback to no-feedback long operations

**Files:**
- Modify: `tools/drillreport.py:81-88`, `tools/custom_drillreport.py:472`, `tools/piper.py` (main build)
- Reference implementation: `tools/export_spatialite.py:220-266`

Context: these loop over N selected obsids doing multiple DB queries + HTML/plot generation with **no** cursor, progress, or `processEvents`. Scope this task to the *cheapest correct* improvement — a `QProgressDialog` with cancel around the per-obsid loop — not a full threaded worker (that is post-release). Heavier freezers (`import_data_to_db`, sectionplot, customplot) are left for post-release; note that explicitly so it is not mistaken for "all done".

- [ ] **Step 1 (drillreport):** wrap the `for obsid in obsids:` loop (both the merged and per-obsid branches) in a `QProgressDialog`:

```python
progress = QtWidgets.QProgressDialog(
    QCoreApplication.translate("Drillreport", "Generating report…"),
    QCoreApplication.translate("Drillreport", "Cancel"),
    0, len(obsids),
)
progress.setWindowModality(qgis.PyQt.QtCore.Qt.WindowModal)
progress.setMinimumDuration(0)
for i, obsid in enumerate(obsids):
    if progress.wasCanceled():
        break
    progress.setValue(i)
    self.write_obsid(obsid, rpt, imgpath, logopath, f)
progress.setValue(len(obsids))
```

- [ ] **Step 2 (custom_drillreport:472, piper):** apply the same wrapper around their per-item loops. For piper, if there is no natural per-item loop (single plot build), a wait cursor via `common_utils.start_waiting_cursor()` / `stop_waiting_cursor()` in try/finally is the minimum — verify what the heavy span is first.
- [ ] **Step 3:** These are GUI-timing changes; they have no unit-testable assertion beyond "still produces the report". Run: `python3 -m pytest test/test_drillreport_spatialite.py -x` — PASS (report output unchanged; progress dialog is not exercised headless but must not break the flow).
- [ ] **Step 4: Commit** — `git commit -m "feat(ux): progress dialog with cancel for drill/custom-drill/piper report loops"`

---

### Task 16: Extract the stored-settings mixin (only real duplication)

**Files:**
- Create: `tools/utils/gui_utils.py` addition `StoredSettingsMixin` (or a new `tools/utils/stored_settings.py`)
- Modify: `tools/custom_drillreport.py:132-320`, `tools/wqualreport_compact.py:251-370`
- Test: `test/test_stored_settings_mixin.py` (new)

**Interfaces:**
- Produces: `StoredSettingsMixin` with `update_from_stored_settings`, `save_stored_settings(save_attrnames)`, `ask_for_stored_settings(stored_settings)`, `ask_and_update_stored_settings()` — the `wqualreport_compact` superset version (handles `QPlainTextEdit`/`QCheckBox`/`QRadioButton`/`QLineEdit`/`QComboBox`).

Context: the review found exactly one genuine ~150-line copy-paste: the stored-settings UI block duplicated between these two files. `wqualreport_compact`'s version is a strict superset. Extracting it also fixes a latent bug: `custom_drillreport` and `wqualreport_compact` both emit `QCoreApplication.translate("DrillreportUi", ...)`, so the compact-wqual dialog's errors are filed under the *drillreport* translation context.

- [ ] **Step 1: Write the failing test** — instantiate a tiny dummy class mixing in `StoredSettingsMixin` with a couple of fake Qt widgets (use real `QLineEdit`/`QCheckBox`), round-trip settings through `save_stored_settings` → `update_from_stored_settings`, assert values survive. Assert the translate context used in error paths is a shared/neutral context, not `"DrillreportUi"` for the compact case.
- [ ] **Step 2:** Run — FAIL (no mixin).
- [ ] **Step 3: Create the mixin** from the `wqualreport_compact` version. Use a neutral translate context `"StoredSettings"` for the mixin's own messages. Keep method signatures identical to the compact version so it is the drop-in.
- [ ] **Step 4: Make both classes inherit the mixin** and delete their local copies. Verify `custom_drillreport` passes its attribute list via `save_attrnames` (the compact version already parameterises this; custom_drillreport hardcoded it — pass the same list explicitly).
- [ ] **Step 5:** Run: `python3 -m pytest test/test_stored_settings_mixin.py test/test_drillreport_spatialite.py test/test_wqualreport_spatialite.py -x` — PASS.
- [ ] **Step 6: Commit** — `git commit -m "refactor(ux): extract StoredSettingsMixin; fixes wrong translate context in compact wqual report"`

---

### Task 17: Hoist the fake-circular lazy imports in the db layer

**Files:**
- Modify: `tools/utils/db_utils/backends/base.py:2` (docstring), `:148,:154,:160,:320` (lazy imports)

Context: `base.py:148,154,160` lazily import `dialect.ident`/`sql_ident`/`in_clause` inside one-line methods, and `:320` lazily imports `string_utils` — but `dialect.py` imports only stdlib and there is no cycle. These are per-call import lookups on the hottest path for nothing. Also `base.py:2` claims "All dialect-specific logic lives in SQLiteBackend and PostgreSQLBackend", which is false — `schema.py` has 7 `is_sqlite()` forks; fix the docstring so it stops misleading.

- [ ] **Step 1:** Move the four imports to module top of `base.py`. Run the smallest importing test to prove no cycle appears: `python3 -m pytest test/test_db_utils_spatialite.py -x`.
- [ ] **Step 2:** If (and only if) a real ImportError cycle surfaces, revert that one import and leave a one-line comment naming the cycle — but the review verified `dialect.py` and `string_utils` have no back-edge, so this should be clean.
- [ ] **Step 3:** Fix the `base.py:2` docstring to: `"""Backend base class. Most dialect-specific SQL lives in SQLiteBackend/PostgreSQLBackend; a few introspection forks remain in schema.py."""`
- [ ] **Step 4: Commit** — `git commit -m "refactor(db): hoist non-circular lazy imports in backend base; correct docstring"`

---

### Task 18: Document the aggregator-import rule (prevent regression)

**Files:**
- Modify: `CLAUDE.md`
- Memory: add a project memory noting the rule is now documented.

Context: the refactor drove in-repo `common_utils`/`midvatten_utils` re-export usage to **zero**, but nothing documents the rule, so the next contributor (human or agent) will re-introduce the drift. This is a 5-line doc change with outsized leverage.

- [ ] **Step 1:** Under CLAUDE.md "Code Style" or a new "Imports" heading add:

```markdown
### Imports
- Import from the specific source module, not the aggregators: use
  `string_utils`, `message_utils`, `layer_utils`, `dialog_utils`, `exceptions`
  directly — not `common_utils.X` / `midvatten_utils.X` re-exports.
- The `common_utils` / `midvatten_utils` re-export blocks and the `db_utils.X`
  names exist ONLY as the midv_addons public API. Do not add new in-repo call
  sites through them; do not remove them either.
```

- [ ] **Step 2:** Commit — `git commit -m "docs: document the source-module import rule in CLAUDE.md"`

---

### Task 19: Resolve the two data-correctness TODOs

**Files:**
- Investigate: `tools/import_general_csv_gui.py:451`, `tools/import_data_to_db.py:1197`

Context: two TODOs describe possible data bugs, not style. They must be either confirmed-and-fixed or refuted-and-deleted before release — a shipped "I have NO IDEA where this comes from" comment is a red flag.

- [ ] **Step 1 (`import_general_csv_gui.py:451`):** "I have NO IDEA where the dummy parameter is coming from. It gets the value False." Trace the `dummy`/`False` parameter into `start_import`. Write a test that drives `start_import` with a representative CSV and asserts the imported rows are correct (no phantom column/value). If behaviour is correct, delete the comment; if wrong, fix and keep a test.
- [ ] **Step 2 (`import_data_to_db.py:1197`):** "Empty foreign keys are probably imported now. Must add case-when-NULL." Write a test importing rows where an FK column is empty/NULL; assert no bogus FK row is created (the `and_parts` filter at `:1259-1263` already excludes empty strings — verify it covers the reported case). If covered, delete the TODO; if not, add the NULL guard and a test.
- [ ] **Step 3:** Run: `python3 -m pytest test/test_import_data_to_db_spatialite.py test/test_import_general_csv*.py -x` — PASS.
- [ ] **Step 4: Commit** — `git commit -m "fix(import): resolve FK-null and csv-dummy-param TODOs with regression tests"` (or `docs:` if only comments were removed after confirming correctness).

---

### Task 20: Recompile translations, final verification, compat gate

**Files:**
- Modify: `i18n/*.ts` (regenerate), `i18n/*.qm` (recompile)

Context: `.ts` sources are May-dated, `.qm` compiled files are Feb-dated, `default_eng.qm` is 16 bytes (empty). All strings added since Feb — including everything this plan adds — ship untranslated unless regenerated. This must be the LAST code-affecting step so all new `translate()` strings are captured.

- [ ] **Step 1:** Update `midvatten.pro` SOURCES if new files were added (`tools/utils/html_utils.py`, any new modules). The `compile_and_prepare_for_upload_notes.txt` documents the process.
- [ ] **Step 2:** Regenerate `.ts`: `pylupdate5 -verbose midvatten.pro` (or the Qt6 equivalent available in the env; confirm which `pylupdate` exists).
- [ ] **Step 3:** Recompile `.qm`: `lrelease i18n/midvatten_*.ts`. Verify `default_eng.qm` is no longer 16 bytes.
- [ ] **Step 4: Full suite** (sprint boundary — this is where the ~35-45 min run is justified):

```bash
python3 -m pytest test/ -x
```
Expected: PASS. If PostGIS UniqueViolations appear, confirm no other agent is using the shared DB, then rerun the postgis subset alone.

- [ ] **Step 5: midv_addons compat gate:** `cd ~/dev/midv_addons && python3 -m pytest -k test_midvatten_compat -x` — PASS. (Shared modules touched: `layer_utils`, `db_utils` internals, `common_utils`? — verify the re-export surface is intact.)
- [ ] **Step 6:** `ruff check .` and `ruff format --check .` on the touched files clean (do NOT run the repo-wide autofix sweep here — that 500-file diff is a deliberate post-release first commit).
- [ ] **Step 7: Commit** — `git commit -m "chore(i18n): regenerate and recompile translations for the release"`

---

## Deferred to post-release (explicitly NOT in this plan)

Listed so "done with this plan" is not mistaken for "everything the review found":

- Repo-wide ruff modernization sweep (~615 findings, UP006/UP031/…) — make it the FIRST commit after the release tag so the huge mechanical diff doesn't hide real changes.
- Threaded workers + progress for the heavy freezers: `import_data_to_db` (~1150 lines under one cursor), sectionplot, customplot. Task 15 only covers the zero-feedback report loops.
- `export_fieldlogger_defaults` data-table extraction (~150 lines), `anything_to_string_representation` collapse, the three 250-280-line `__init__`/`show` UI-build splits, `save_to_db` stage extraction.
- Delete confirmed-dead `date_to_epoch`, `LegendPicker.get_selected_ax_lines`, `common_utils.Timer`/`timer` (midv_addons-visible module — small contract risk, do deliberately).
- CSV formula-injection neutralisation on export (`file_utils.py:204`) — lower priority than HTML XSS; add a `'` prefix to cells starting `= + - @` if desired.
- Git/worktree hygiene: 8 unpushed commits, 8 registered worktrees (2 on `/tmp`, 1 already merged), untracked `.claude/`/`.swo`. Separate human-gated cleanup pass — per project rule, never bundled into feature work.

---

## Self-review notes

- **Qt5/Qt6:** every new dialog/enum in Tasks 13-15 uses `qgis.PyQt` and the enum spellings already present in the codebase; Task 5 removes the one Qt6-breaking `mpl.use`. Constraint satisfied.
- **Familiar-but-polished:** Tasks 10-14 preserve existing wording where it is already clear and change only the delivery mechanism; new sentences appear only where the old text was broken (`create_db` spatialite4), a raw dump (interlab4 `cols`), or missing (translate defaults). No new concepts are introduced to the user.
- **Security coverage:** F1 (CAST types) + identifier stragglers = Task 6; F14 (HTML XSS) = Task 7; F10/F11 (temp dirs) = Task 8. F7 (temp_postgis_passwords key) and F15 (CSV formula injection) are noted for post-release; F7 is currently unpopulated so no live leak.
- **Interfaces:** `safe_type`, `esc`, `warn_no_selection`/`warn_no_layer`, `StoredSettingsMixin`, `_rebuild_input_fields_from_settings` are each defined in the task that first produces them and consumed by name later. No forward references to undefined symbols.
