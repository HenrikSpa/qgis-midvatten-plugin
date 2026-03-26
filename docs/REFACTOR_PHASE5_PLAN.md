# Refactor Phase 5: Maintainability Improvements

Each task is independent and can be done by a clean agent in a single session.
Tasks are ordered by impact. Each task should end with `python3 -m pytest test/ -x`
passing and a commit.

## Task Index

- [ ] **Task 1**: Delete dead code (16 dead methods, unused imports, legacy comments)
- [ ] **Task 2**: Replace debug `print()` with `logging.debug()` (30+ calls)
- [ ] **Task 3**: Simplify `returnunicode`/`ru` and remove no-op calls (183 occurrences)
- [ ] **Task 4**: Move `dbtype` branches to backend methods (19 string checks)
- [ ] **Task 5**: Rename camelCase methods to snake_case (21 methods)
- [ ] **Task 6**: Fix QMainWindow/QDialog init mismatch (9 classes)
- [ ] **Task 7**: Decompose `general_import()` (421-line monolith)
- [ ] **Task 8**: Migrate callers off `common_utils` re-exports
- [ ] **Task 9**: Fix remaining style issues (mutable defaults, `== None`, etc.)
- [ ] **Task 10**: Decompose `initGui()` in `midvatten_plugin.py` (381 lines)

## Prerequisites

- Branch: `ai_test`
- Read `CLAUDE.md` before starting any task
- Read `docs/REFACTOR_ASSESSMENT.md` for context
- Run `ruff check --fix . && ruff format .` after code changes

---

## Task 1: Delete dead code

Delete these 16 confirmed-dead methods (defined but never called anywhere):

| File | Line | Method |
|------|------|--------|
| `tools/export_fieldlogger.py` | 1551 | `get_selected()` |
| `tools/import_data_to_db.py` | 582 | `sanitize()` |
| `tools/import_data_to_db.py` | 885 | `import_error_msg()` |
| `tools/import_fieldlogger.py` | 352 | `sublocation_to_groups()` |
| `tools/import_fieldlogger.py` | 1886 | `set_settings()` |
| `tools/loggereditor.py` | 535 | `sql_into_recarray()` |
| `tools/piper.py` | 1074 | `to_piper_coords()` |
| `tools/piper.py` | 1086 | `get_triangle_nodes()` |
| `tools/utils/common_utils.py` | 847 | `current_time()` |
| `tools/utils/midvatten_utils.py` | 1193 | `style_from_filename()` |
| `tools/utils/db_utils/backends/base.py` | 177 | `is_distinct_from_sql()` |
| `tools/utils/db_utils/backends/base.py` | 181 | `is_not_distinct_from_sql()` |
| `tools/utils/db_utils/backends/postgresql.py` | 305 | `is_distinct_from_sql()` |
| `tools/utils/db_utils/backends/postgresql.py` | 308 | `is_not_distinct_from_sql()` |
| `tools/utils/db_utils/backends/sqlite.py` | 278 | `is_distinct_from_sql()` |
| `tools/utils/db_utils/backends/sqlite.py` | 281 | `is_not_distinct_from_sql()` |

Also remove:
- Unused imports: `traceback` in `loggereditor.py`, `io` in `import_fieldlogger.py`,
  `io` in `import_diveroffice.py`, `io` in `import_interlab4.py`, `sql_alter_db` in
  `import_interlab4.py`
- Legacy comments: `# _CHANGE_`, `# fix_print_with_import`, `# THIS IS TSPLOT-method`
  in `stratigraphy.py` and `piper.py`
- Commented-out code blocks (search for `# self.` patterns — about 40 instances)

**Verify**: grep for each deleted method name to confirm no callers exist.

---

## Task 2: Replace debug `print()` with `logging`

Add a module-level logger to files that contain debug prints:

```python
import logging
log = logging.getLogger(__name__)
```

Replace `print()` calls with `log.debug()`. This way:
- Regular users never see them (QGIS default log level is WARNING)
- Developers can enable them by setting `logging.getLogger("midvatten").setLevel(logging.DEBUG)`

Known locations (30+ calls):
- `tools/stratigraphy.py`: lines 71 and others
- `tools/piper.py`: lines 65, 72, 75
- `tools/loggereditor.py`: lines 289, 789
- `tools/create_db.py`: lines 206, 367-372
- `tools/sectionplot.py`: lines 1376, 1379
- Scan all `tools/` files for remaining `print(` calls

Do NOT convert `print()` calls that are inside test files.

---

## Task 3: Simplify `returnunicode` and remove no-op calls

### Background: what `ru()` actually does in Python 3

Tested empirically (see `/tmp/test_ru_difference.py`):

| Input type | Without `ru()` via `%s` | With `ru()` via `%s` |
|------------|------------------------|---------------------|
| `str` | works | identical (no-op) |
| `int`/`float` | works | identical (no-op) |
| `None` | prints `"None"` | prints `""` |
| `bytes` | prints `"b'\\xe4'"` repr | **also** prints repr (bytes decoding is dead code!) |

The bytes decoding branch (lines 104-115 in `string_utils.py`) is dead code:
`str(bytes_val)` on line 102 produces the repr string before the `isinstance(decoded, bytes)`
check on line 104 ever fires.

**In Python 3, `ru()` only changes behavior for `None` (converts to `""`).**

`ru()` around `translate()` is NOT needed: `translate()` returns `str` in Python 3,
and `%s` formatting handles any value type natively.

### Step 1: Simplify `returnunicode` itself

In `tools/utils/string_utils.py`, remove dead branches:
- PyQt4 `QVariant`, `QString`, `QPyNullVariant` checks (PyQt4 is dead)
- PyQt5 `QString` check (doesn't exist in Python 3 PyQt5)
- The bytes decoding loop (lines 104-115) — dead code in Python 3
- Add actual bytes handling BEFORE the `str()` fallback (the current code
  converts bytes to repr-string before the decode loop runs)

The simplified function should be:
```python
def returnunicode(anything, keep_containers=False):
    if isinstance(anything, str):
        return anything
    if anything is None:
        return ""
    if isinstance(anything, bytes):
        for charset in ["utf-8", "cp1252", "iso-8859-1", "ascii"]:
            try:
                return anything.decode(charset)
            except (UnicodeDecodeError, UnicodeEncodeError):
                continue
        return str(anything)  # fallback to repr
    if isinstance(anything, (list, tuple, dict, OrderedDict)):
        # ... existing recursive logic ...
    return str(anything)
```

### Step 2: Remove `ru()` from guaranteed-str call sites

These are no-ops and can be removed mechanically:
- `ru(QCoreApplication.translate(...))` — 131 occurrences. `translate()` returns `str`.
- `ru("string literal")` — input is already `str`
- `ru(f"...")` — f-strings are already `str`

### Step 3: Evaluate remaining `ru()` call sites

For `% ru(value)` patterns (~14 occurrences): decide case by case whether
`None -> ""` conversion is intentional or just cargo-culted. If the code
should display "None" for missing values, remove `ru()`. If empty string
is correct, keep it or replace with `(value or "")`.

### Step 4: Consider renaming

After cleanup, `ru()` will mainly serve as "safe stringify" for external data
(`None -> ""`, bytes decoding). Consider renaming to `safe_str()` to clarify.

---

## Task 4: Move `dbtype` branches to backend methods

`tools/utils/db_utils/helpers.py` has 19 `dbconnection.dbtype` string checks.
Each should become a polymorphic backend method.

Candidates (each is a small, self-contained change):

| Function | Lines | What to extract |
|----------|-------|-----------------|
| `backup_db` | 45 | SQLite-only logic -> `SQLiteBackend.backup()` |
| `get_srid_name` | 105 | Different SQL per backend -> `Backend.get_srid_name()` |
| `get_latlon_for_all_obsids` | 238 | Y/X vs ST_Y/ST_X -> `Backend.latlon_sql()` |
| `rowid_string` | 331 | Trivial dispatch -> `Backend.rowid_string()` |
| `test_if_numeric` | 373 | Different SQL -> `Backend.numeric_test_sql()` |
| `cast_date_time_as_epoch` | varies | Different SQL -> `Backend.epoch_cast_sql()` |
| `cast_null` | varies | Different SQL -> `Backend.null_cast_sql()` |
| `test_not_null_and_not_empty_string` | 177 | Different SQL -> `Backend.not_null_sql()` |
| `is_distinct_from` | 158 | Already has dead backend methods — wire them up |
| `is_not_distinct_from` | 163 | Same as above |

Also:
- Move `_log_execute_error` (duplicated identically in sqlite.py and postgresql.py)
  into `base.py`.
- Stop accessing `dbconnection._backend` directly from `helpers.py` and `sqlfile.py`.
  Add facade methods to `DbConnectionManager` instead.

---

## Task 5: Rename camelCase methods to snake_case

Only rename methods that are OUR code (not Qt/QGIS API overrides).
Library methods like `setupUi()`, `closeEvent()`, `showEvent()`, `eventFilter()`
must stay camelCase because they override Qt virtuals.

**Our methods to rename** (21 in production code):

`tools/stratigraphy.py` (14 methods — the main target):
- `initStore` -> `init_store`
- `showSurvey` -> `show_survey`
- `getData` -> `get_data`
- `_getDataStep1` -> `_get_data_step1`
- `_getDataStep2` -> `_get_data_step2`
- `sanityCheck` -> `sanity_check`
- `setData` -> `set_data`
- `setData2_nosorting` -> `set_data2_nosorting`
- `setType` -> `set_type`
- `setGeoOrComment` -> `set_geo_or_comment`
- `setShowDesc` -> `set_show_desc`
- `drawSurveys` -> `draw_surveys`
- `drawSurvey` -> `draw_survey`
- `textToColor` -> `text_to_color`
- `geoToSymbol` -> `geo_to_symbol`
- `printDiagram` -> `print_diagram`
- `typeToggled` -> `type_toggled`

Other files:
- `sectionplot.py`: `initUI` -> `init_ui`
- `customplot.py`: `refreshPlot` -> `refresh_plot`
- `layer_utils.py`: `getQgisVectorLayers` -> `get_qgis_vector_layers`,
  `getselectedobjectnames` -> `get_selected_object_names`
- `util_translate.py`: `getTranslate` -> `get_translate`

Use grep to find all callers and update them. Some of these are called from
tests too.

---

## Task 6: Fix QMainWindow/QDialog init mismatch

9 classes declare `QMainWindow` as parent but call `QDialog.__init__()`:
- `customplot.py:64,68`
- `import_diveroffice.py:67,75`
- `loggereditor.py:34,37`
- `import_fieldlogger.py:60,66`
- `export_fieldlogger.py:216,221`
- `import_interlab4.py:52,58`
- `import_general_csv_gui.py:51,57`
- `wqualreport_compact.py:50,57`
- `custom_drillreport.py:44,49`

For each: change the `__init__` call to match the declared parent class.
E.g., `QMainWindow.__init__(self, parent)` instead of `QDialog.__init__(self, parent)`.

Test carefully — this could affect window flags or close behavior.

---

## Task 7: Decompose `general_import()`

`tools/import_data_to_db.py:48-468` (421 lines, 10 responsibilities).

Extract into named steps:
1. `_validate_and_connect()` — connection setup, schema introspection
2. `_create_temp_table()` — temp table creation via `list_to_table`
3. `_remove_duplicate_datetimes()` — date_time dedup logic
4. `_handle_foreign_keys()` — FK import with user confirmation
5. `_build_insert_sql()` — column mapping, type casting, SQL construction
6. `_execute_insert()` — the actual INSERT with geometry handling
7. `_report_results()` — record counting and user messaging

Also extract the duplicated cleanup code (except block lines 438-451 and
else block lines 453-467) into a `_cleanup()` method or use a `finally` block.

---

## Task 8: Migrate callers off `common_utils` re-exports

Update import statements across the codebase to import from the specific
modules instead of `common_utils`:

| Old import | New import |
|------------|-----------|
| `from ...common_utils import MessagebarAndLog` | `from ...message_utils import MessagebarAndLog` |
| `from ...common_utils import returnunicode` | `from ...string_utils import returnunicode` |
| `from ...common_utils import NotFoundQuestion` | `from ...dialog_utils import NotFoundQuestion` |
| `from ...common_utils import find_layer` | `from ...layer_utils import find_layer` |
| etc. | etc. |

After migration, remove the re-exports from `common_utils.py`. This can be
done incrementally — one import group at a time, verifying tests pass after each.

Also move remaining misplaced functions out of `common_utils.py`:
- `ContinuousColorCycle`, `PickAnnotator` -> new `plot_utils.py`
- `save_stored_settings`, `get_stored_settings` -> `settings_utils.py` or `midvsettings.py`
- `waiting_cursor`, `start_waiting_cursor`, `stop_waiting_cursor` -> `gui_utils.py`
- `general_exception_handler` -> `exceptions.py`
- `verify_this_layer_selected_and_not_in_edit_mode` -> `layer_utils.py`

---

## Task 9: Fix remaining style issues

A collection of smaller fixes that can be done together:

- Fix 6 mutable default arguments (`settingsdict={}` etc.) — use `None` + `if`
- Fix 4 `== None` -> `is None`
- Fix 2 `== True` -> bare truth test
- Remove `@fn_timer` from production code in `loggereditor.py` (36 uses) or
  make it a no-op unless a DEBUG env var is set
- Standardize import style: always use `from qgis.PyQt import ...` (not
  `import qgis.PyQt` with qualified access, not `from PyQt5 import ...`)

---

## Task 10: Decompose `initGui()` in `midvatten_plugin.py`

381 lines of action registration. Split by category:

```python
def initGui(self):
    self._create_actions()
    self._build_menus()
    self._connect_signals()

def _create_actions(self):
    self._create_import_actions()
    self._create_export_actions()
    self._create_edit_actions()
    self._create_plot_actions()
    self._create_report_actions()
    self._create_db_management_actions()
    self._create_utility_actions()
    self._create_top_level_actions()

def _build_menus(self):
    ...

def _connect_signals(self):
    ...
```

---

## Notes for agents

- Always read `CLAUDE.md` first
- Run `python3 -m pytest test/ -x` after changes — all 642 tests must pass
- Run `ruff check --fix . && ruff format .` after Python changes
- Use `python3`, not `python`
- Commit with a descriptive message after each task
- Do not change database schemas
- Do not change test reference data unless explicitly told to
