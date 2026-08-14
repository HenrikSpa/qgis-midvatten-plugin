# Midvatten db-settings JSON-first serialization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Midvatten db-settings string round-trip safe for Windows paths (and any backslash-containing value) by serializing with JSON instead of the unescaped `anything_to_string_representation`.

**Architecture:** The db-settings dict (`{"spatialite": {"dbpath": ...}}` / `{"postgis": {...}}`) is stored as a string in the QGIS project entry `("Midvatten", "database")` and in `ms.settingsdict["database"]`. Today it is written with `string_utils.anything_to_string_representation` (wraps strings in quotes but **never escapes backslashes**) and read back with `ast.literal_eval` (**does** interpret backslash escapes). That asymmetry corrupts backslash paths. This plan introduces a tiny pure serde module (`db_settings_to_string` / `db_settings_string_to_dict`), routes every db-settings **write** through JSON and every db-settings **read** through JSON-first-with-`ast`-fallback. This mirrors the JSON-first strategy already adopted in `common_utils.save_stored_settings`/`get_stored_settings`, and keeps full backward compatibility with already-stored values.

**Tech Stack:** Python 3, stdlib `json` + `ast`, pytest (repo config: `pytest.ini`, `testpaths = test`), QGIS Python environment for the qgis-dependent tests.

**Spec:** This plan is self-contained; the design was agreed in the 2026-08-14 debugging session. The "Background & Design" section below is the spec.

## Global Constraints

- Repo: `/home/hsai1/dev/midv/midvatten` (branch `ai_test`; symlinked as the deployed plugin at `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/midvatten`).
- Scope is **db-settings only** (chosen option A). Do NOT change `anything_to_string_representation` itself, and do NOT touch the other round-trip sites (fieldlogger, plot_templates, midvatten_defs, generic stored_settings) — they are out of scope for this plan.
- Backward compatibility is mandatory: existing stored db-settings strings (written by the old serializer, always forward-slash for spatialite because Qt file dialogs return `/`) MUST still read correctly. The `ast.literal_eval` fallback on read guarantees this.
- Serde module must be **pure stdlib (no qgis import)** so it is unit-testable headless.
- Tests run with pytest from the repo root: `cd /home/hsai1/dev/midv/midvatten && python3 -m pytest <path> -v`. The pure serde tests need no QGIS; the parse/integration tests import `qgis.core` and require the QGIS Python env (same env used by the existing suite).
- Follow "Python first" and existing code style. Keep diffs minimal and mechanical at the call sites.

---

## Background & Design (spec)

### Root cause (verified)
`anything_to_string_representation({"spatialite": {"dbpath": r"...\3368..."}})` emits `{"spatialite": {"dbpath": "...\3368..."}}` with the backslashes raw. `ast.literal_eval` then reads `\336` as an octal escape (`chr(0o336)` = `Þ`), leaving `8`, so `...\3368...` becomes `...Þ8...` and the db is reported "not found". Worked on Linux only because `/` has no escape meaning.

### The fix
JSON round-trips backslashes correctly (`json.dumps` escapes them; `json.loads` restores them). Existing stored spatialite values are forward-slash strings that are already valid JSON, so `json.loads` reads them directly; any legacy value that is not valid JSON falls back to `ast.literal_eval` (unchanged behavior).

### Affected sites (exhaustive, db-settings only)
Writers (build the string, store in `settingsdict["database"]` / `self.db_settings`):
- `midvsettingsdialog.py:854-856` — spatialite (`database_chosen`)
- `midvsettingsdialog.py:982-984` — postgis (`_save_db_settings`)
- `tools/create_db.py:148-150` — spatialite
- `tools/create_db.py:278-280` — postgis (serializes an existing `dbconnection.db_settings` dict)

Readers (parse the string to a dict):
- `tools/utils/db_utils/connection.py:37` — `_parse_db_settings` (the main one)
- `tools/utils/db_utils/helpers.py:107` — `get_spatialite_db_path_from_dbsettings_string`
- `midvsettingsdialog.py:740` — `DatabaseSettings` read path

Explicitly NOT affected (verified — these `ast.literal_eval` calls parse a hardcoded system-table tuple, not db-settings): `db_utils/backends/sqlite.py:64`, `db_utils/backends/postgresql.py:63`.

### Import-graph note
`connection.py` does not import `helpers.py` (helpers depends on connection). The serde helpers therefore go in a **new leaf module** `tools/utils/db_utils/db_settings_serde.py` that imports only stdlib, so `connection.py`, `helpers.py`, `midvsettingsdialog.py`, and `create_db.py` can all import it without cycles.

---

### Task 1: Pure db-settings serde module

**Files:**
- Create: `tools/utils/db_utils/db_settings_serde.py`
- Create: `test/test_db_settings_serde.py`
- Modify: `tools/utils/db_utils/__init__.py` (export the two functions)

**Interfaces:**
- Consumes: nothing (stdlib only).
- Produces:
  - `db_settings_to_string(db_settings: dict) -> str` — JSON serialization.
  - `db_settings_string_to_dict(db_settings_string: str) -> dict` — `json.loads` first, `ast.literal_eval` fallback. Raises `ValueError`/`SyntaxError` if neither parses (callers keep their existing try/except).

- [ ] **Step 1: Write the failing tests**

Create `test/test_db_settings_serde.py`:

```python
"""Pure serde tests: no qgis, no database."""
import pytest

from midvatten.tools.utils.db_utils.db_settings_serde import (
    db_settings_to_string,
    db_settings_string_to_dict,
)


def test_windows_path_roundtrips():
    # '\336' in '...\3368...' used to be read as octal escape 'Þ'.
    winpath = r"M:\projekt\3368 x\Arbetsdata\Databas\3368_midv_obsdb.sqlite"
    settings = {"spatialite": {"dbpath": winpath}}
    parsed = db_settings_string_to_dict(db_settings_to_string(settings))
    assert parsed == settings
    assert "Þ" not in parsed["spatialite"]["dbpath"]


def test_linux_path_roundtrips():
    settings = {"spatialite": {"dbpath": "/mnt/server/M_mv/projekt/3368/db.sqlite"}}
    assert db_settings_string_to_dict(db_settings_to_string(settings)) == settings


def test_postgis_roundtrips():
    settings = {"postgis": {"connection": "obsdb_2000/svc:host:5432/db",
                            "schema": "public"}}
    assert db_settings_string_to_dict(db_settings_to_string(settings)) == settings


def test_reads_legacy_ast_string():
    # Value as the old anything_to_string_representation would have written it
    # (double-quoted, forward-slash spatialite path) — must still parse.
    legacy = '{"spatialite": {"dbpath": "/a/b.sqlite"}}'
    assert db_settings_string_to_dict(legacy) == {
        "spatialite": {"dbpath": "/a/b.sqlite"}}


def test_reads_legacy_single_quoted_ast_string():
    # ast fallback path: single quotes are not valid JSON.
    legacy = "{'spatialite': {'dbpath': '/a/b.sqlite'}}"
    assert db_settings_string_to_dict(legacy) == {
        "spatialite": {"dbpath": "/a/b.sqlite"}}


def test_invalid_string_raises():
    with pytest.raises((ValueError, SyntaxError)):
        db_settings_string_to_dict("not a settings string")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hsai1/dev/midv/midvatten && python3 -m pytest test/test_db_settings_serde.py -v`
Expected: FAIL with `ModuleNotFoundError: ... db_settings_serde`.

- [ ] **Step 3: Create the serde module**

Create `tools/utils/db_utils/db_settings_serde.py`:

```python
"""Serialize/parse the Midvatten db-settings dict to/from its stored string.

The db-settings dict — ``{"spatialite": {"dbpath": ...}}`` or
``{"postgis": {...}}`` — is stored as a string in the QGIS project entry
("Midvatten", "database"). JSON is the current on-disk format:
``json.dumps`` escapes backslashes, so Windows paths (e.g. ``...\\3368...``,
where ``\\336`` would otherwise be read as octal ``Þ``) survive the
round-trip. ``ast.literal_eval`` remains as a read fallback for values
stored before this migration.

Pure stdlib (no qgis) so it is unit-testable headless.
"""
import ast
import json


def db_settings_to_string(db_settings: dict) -> str:
    """Serialize a db-settings dict to its stored string form (JSON)."""
    return json.dumps(db_settings)


def db_settings_string_to_dict(db_settings_string: str) -> dict:
    """Parse a stored db-settings string to a dict.

    JSON first (current format); ast.literal_eval fallback for legacy
    values. Raises ValueError/SyntaxError if neither parses — callers keep
    their existing error handling.
    """
    try:
        return json.loads(db_settings_string)
    except (json.JSONDecodeError, ValueError):
        return ast.literal_eval(db_settings_string)
```

- [ ] **Step 4: Export from the package**

In `tools/utils/db_utils/__init__.py`, add an import next to the other `db_utils` imports (e.g. after the `settings` import on line 13):

```python
from midvatten.tools.utils.db_utils.db_settings_serde import (
    db_settings_string_to_dict,
    db_settings_to_string,
)
```

And add both names to the `__all__` list in that file (alongside `"get_spatialite_db_path_from_dbsettings_string"`):

```python
    "db_settings_string_to_dict",
    "db_settings_to_string",
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/hsai1/dev/midv/midvatten && python3 -m pytest test/test_db_settings_serde.py -v`
Expected: PASS (6 passed).

- [ ] **Step 6: Commit**

```bash
cd /home/hsai1/dev/midv/midvatten
git add tools/utils/db_utils/db_settings_serde.py tools/utils/db_utils/__init__.py test/test_db_settings_serde.py
git commit -m "feat(db_utils): JSON-safe db-settings serde helpers

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Route db-settings reads through the parser

**Files:**
- Modify: `tools/utils/db_utils/connection.py` (import + line 37)
- Modify: `tools/utils/db_utils/helpers.py` (import + line 107)
- Modify: `midvsettingsdialog.py` (import + line 740)
- Test: `test/test_db_settings_serde.py` (add a qgis-level parse regression)

**Interfaces:**
- Consumes: `db_settings_string_to_dict` from Task 1.
- Produces: no new public API; `_parse_db_settings` and `get_spatialite_db_path_from_dbsettings_string` keep their existing signatures and behavior, now backslash-safe.

- [ ] **Step 1: Write the failing regression test**

Append to `test/test_db_settings_serde.py`:

```python
def test_parse_db_settings_preserves_windows_path():
    """A JSON settings string with a Windows path must parse back intact
    through the real _parse_db_settings (regression for the 'Þ' corruption)."""
    from midvatten.tools.utils.db_utils.connection import _parse_db_settings
    winpath = r"M:\projekt\3368 x\Arbetsdata\Databas\3368_midv_obsdb.sqlite"
    s = db_settings_to_string({"spatialite": {"dbpath": winpath}})
    dbtype, connection_settings, _ = _parse_db_settings(s)
    assert dbtype == "spatialite"
    assert connection_settings["dbpath"] == winpath
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /home/hsai1/dev/midv/midvatten && python3 -m pytest test/test_db_settings_serde.py::test_parse_db_settings_preserves_windows_path -v`
Expected: FAIL — current `_parse_db_settings` uses `ast.literal_eval`, so `connection_settings["dbpath"]` contains `Þ8` instead of `\3368`.
(If the QGIS env is unavailable and the test errors on `import qgis`, run it in the same environment the existing suite uses.)

- [ ] **Step 3: Update `connection.py`**

Add to the imports (near line 13, with the other `midvatten...` imports):

```python
from midvatten.tools.utils.db_utils.db_settings_serde import db_settings_string_to_dict
```

Replace line 37 (`db_settings = ast.literal_eval(db_settings)`) with:

```python
                db_settings = db_settings_string_to_dict(db_settings)
```

(Keep the surrounding `try/except Exception -> UsageError` exactly as is.)

- [ ] **Step 4: Update `helpers.py`**

Add to the imports (near line 22, with the other `db_utils` imports):

```python
from midvatten.tools.utils.db_utils.db_settings_serde import db_settings_string_to_dict
```

Replace line 107 (`db_settings = ast.literal_eval(db_settings)`) with:

```python
            db_settings = db_settings_string_to_dict(db_settings)
```

(Keep the surrounding `try/except Exception` logging/return `""` exactly as is.)

- [ ] **Step 5: Update `midvsettingsdialog.py` read path**

Add to the imports (near line 15, with the other imports; `string_utils` is already imported here):

```python
from midvatten.tools.utils.db_utils.db_settings_serde import db_settings_string_to_dict
```

Replace line 740 (`db_settings = ast.literal_eval(_db_settings)`) with:

```python
            db_settings = db_settings_string_to_dict(_db_settings)
```

(Keep the surrounding `try/except` warning exactly as is.)

- [ ] **Step 6: Run the regression + existing db tests**

Run:
```bash
cd /home/hsai1/dev/midv/midvatten && python3 -m pytest \
  test/test_db_settings_serde.py test/test_db_utils.py test/test_midvsettingsdialog.py -v
```
Expected: PASS (new regression passes; existing tests unaffected).

- [ ] **Step 7: Commit**

```bash
cd /home/hsai1/dev/midv/midvatten
git add tools/utils/db_utils/connection.py tools/utils/db_utils/helpers.py midvsettingsdialog.py test/test_db_settings_serde.py
git commit -m "fix(db_utils): parse db-settings JSON-first so Windows paths survive

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Route db-settings writes through the serializer

**Files:**
- Modify: `midvsettingsdialog.py` (lines 854-856 spatialite; 982-984 postgis)
- Modify: `tools/create_db.py` (import + lines 148-150 spatialite; 278-280 postgis)
- Test: `test/test_db_settings_serde.py` (add a full write→read round-trip)

**Interfaces:**
- Consumes: `db_settings_to_string` from Task 1; `db_settings_string_to_dict` / `_parse_db_settings` from Tasks 1-2.
- Produces: `settingsdict["database"]` / `self.db_settings` now hold JSON strings.

- [ ] **Step 1: Write the failing write→read round-trip test**

Append to `test/test_db_settings_serde.py`:

```python
def test_write_then_parse_windows_path():
    """The string a writer produces for a Windows path must parse back to
    the same path through _parse_db_settings."""
    from midvatten.tools.utils.db_utils.connection import _parse_db_settings
    winpath = r"S:\projekt\3368 x\Arbetsdata\Databas\3368_midv_obsdb.sqlite"
    written = db_settings_to_string({"spatialite": {"dbpath": winpath}})
    # writer output must be valid JSON (the on-disk contract)
    import json
    assert json.loads(written)["spatialite"]["dbpath"] == winpath
    _, connection_settings, _ = _parse_db_settings(written)
    assert connection_settings["dbpath"] == winpath
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /home/hsai1/dev/midv/midvatten && python3 -m pytest test/test_db_settings_serde.py::test_write_then_parse_windows_path -v`
Expected: PASS already for the serde-based assertions? No — this test only uses `db_settings_to_string` (already JSON from Task 1) and `_parse_db_settings` (JSON-first from Task 2), so it should PASS. This test locks the writer contract; if Task 1/2 are done it is green. Its purpose is to guard the write sites you change in Steps 3-4. If it fails, Task 1 or 2 is incomplete — fix those first.

- [ ] **Step 3: Update `midvsettingsdialog.py` writers**

`string_utils` is imported here; add (if not already added in Task 2) the serializer import near line 15:

```python
from midvatten.tools.utils.db_utils.db_settings_serde import db_settings_to_string
```

Replace the spatialite writer at lines 854-856:

```python
        self.midvsettingsdialogdock.ms.settingsdict["database"] = (
            db_settings_to_string({"spatialite": {"dbpath": dbpath}})
        )
```

Replace the postgis writer at lines 982-984:

```python
            self.midvsettingsdialogdock.ms.settingsdict["database"] = (
                db_settings_to_string(
                    {"postgis": {"connection": self.connection, "schema": self.schema}}
                )
            )
```

- [ ] **Step 4: Update `tools/create_db.py` writers**

Add to the imports (with the other `db_utils`/`string_utils` imports at the top of the file):

```python
from midvatten.tools.utils.db_utils.db_settings_serde import db_settings_to_string
```

Replace the spatialite writer at lines 148-150:

```python
        self.db_settings = ru(
            db_settings_to_string({"spatialite": {"dbpath": dbpath}})
        )
```

Replace the postgis writer at lines 278-280 (inside the `if not isinstance(db_settings, str):` branch):

```python
            self.db_settings = ru(db_settings_to_string(dbconnection.db_settings))
```

(Leave the `else: self.db_settings = ru(db_settings)` branch unchanged — that value is already a stored string.)

- [ ] **Step 5: Run the round-trip + affected suites**

Run:
```bash
cd /home/hsai1/dev/midv/midvatten && python3 -m pytest \
  test/test_db_settings_serde.py test/test_midvsettingsdialog.py \
  test/test_create_spatialite_db.py test/test_create_postgis_db.py -v
```
Expected: PASS. (create/settings tests exercise the writers end to end; they must still create and reconnect to the db.)

- [ ] **Step 6: Commit**

```bash
cd /home/hsai1/dev/midv/midvatten
git add midvsettingsdialog.py tools/create_db.py test/test_db_settings_serde.py
git commit -m "fix(db): write db-settings as JSON (backslash-safe)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Changelog, version note, full-suite verification

**Files:**
- Modify: `CHANGELOG_HISTORY` (or the changelog mechanism the repo uses — confirm by reading the top of `CHANGELOG_HISTORY`)
- Modify: `metadata.txt` (only if the team's release convention bumps the version for a fix; current `version=1.9.0b32`)

**Interfaces:** none (docs/metadata only).

- [ ] **Step 1: Add a changelog entry**

Read the current top entries of `CHANGELOG_HISTORY` to match format/language (Swedish, per project convention), then add an entry describing: "Rättar fel där SpatiaLite-databaser med Windows-sökvägar (omvänt snedstreck) inte kunde öppnas — sökvägen sparas nu som JSON." Match the existing bullet/heading style exactly.

- [ ] **Step 2: (Conditional) bump version**

If the release convention bumps `version=` in `metadata.txt` for bug fixes, increment the beta suffix (e.g. `1.9.0b32` → `1.9.0b33`). If unsure, leave unchanged and note it for the maintainer — do not guess a scheme.

- [ ] **Step 3: Run the full db-related suite once more**

Run:
```bash
cd /home/hsai1/dev/midv/midvatten && python3 -m pytest \
  test/test_db_settings_serde.py test/test_db_utils.py test/test_db_utils_executemany.py \
  test/test_midvsettingsdialog.py test/test_create_spatialite_db.py \
  test/test_create_postgis_db.py test/test_stored_settings_mixin.py -v
```
Expected: PASS (no regressions across the db-settings surface).

- [ ] **Step 4: Commit**

```bash
cd /home/hsai1/dev/midv/midvatten
git add CHANGELOG_HISTORY metadata.txt
git commit -m "docs(changelog): note db-settings Windows-path fix

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Post-implementation notes

- **Deployment order:** The `midv_addons` interlab4_batch tool already normalizes its dbpath to forward slashes before serializing, so its output is valid JSON and reads correctly under the new core reader — no conflict. Per the standing rule, deploy midvatten (core) first, then re-verify the interlab4_batch monthly workflow on Windows against project 3368.
- **Manual Windows verification:** After deploy, in QGIS on Windows, set a SpatiaLite db on an `M:\...`/`S:\...` path with a project number containing an octal-triggering digit run (e.g. `3368`), save settings, reopen the project, and confirm the db connects. This exercises the real Qt→settings→reconnect path that unit tests approximate.
- **Out of scope (candidate follow-up):** the other `anything_to_string_representation`+`ast.literal_eval` round-trips (fieldlogger export, plot_templates, midvatten_defs config) share the same asymmetry but store field names/config rather than paths. If a backslash-bearing value ever reaches them, the same JSON-first treatment applies. Track separately if desired.
