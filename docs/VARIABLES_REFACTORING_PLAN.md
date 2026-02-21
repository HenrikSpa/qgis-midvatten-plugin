# Plan: Variables refactoring (homogeneous coding style, step 6)

This plan is for a **new agent** to continue the Midvatten coding-style work. Steps 1–5 are done (tooling, audit, constants, classes, UI forms, functions/methods). This document covers **step 6: variables refactoring** only.

**Target convention (unchanged):** Variables and instance attributes → `lowercase_with_underscores` (snake_case).

---

## 1. Scope

**In scope:**

- **Local variables** in functions/methods that use camelCase or PascalCase (e.g. `dataType`, `TableCombobox`, `My_format`).
- **Instance attributes** (`self.xxx`) that are **not** UI widget names (UI names were already refactored in step 5). Examples: `self.readingSettings`, `self.settingsareloaded`, `self.obsnp_nospecformat`.
- **Module-level variables** that are not constants (constants = UPPER_CASE; already correct or out of scope). If a module-level name is not UPPER_CASE and is not a constant, rename to snake_case.

**Out of scope / do not rename:**

- **UI-derived attributes:** Any `self.<name>` that comes from a `.ui` file (widget/layout objectName). Those were renamed in step 5; only fix if you find a missed reference.
- **Names used in `getattr(self, name)` / `setattr(self, name, …)`:** The string `name` must match the actual attribute name. If the attribute was already refactored (e.g. widget name), the string should already be snake_case. When refactoring **non-UI** variables, if a variable holds a **widget name** used in `getattr(self, var)`, either leave it or change it in sync with the attribute (usually already done).
- **Type hints and type aliases:** e.g. `Dict`, `List`, `Optional` from `typing` — leave as-is (they are type names). Local variables that shadow typing names (e.g. `Dict = {...}`) should be renamed to something like `result_dict` or `data_dict` to avoid N806 and confusion.

---

## 2. Discovery

**Preferred: use Ruff**

From repo root (midvatten):

```bash
ruff check . --select N806,N816
```

- **N806:** variable in function scope should be lowercase.
- **N816:** mixedCase variable in global scope.

Ruff reports file, line, and name. Optionally:

```bash
ruff check . --select N806,N816 --output-format=json
```

to get machine-readable output for a script.

**Optional: extend the audit script**

The repo has `scripts/style_audit.py`. You can add a function that:

- Walks Python files under the repository (excluding `.venv`).
- Uses `ast` to find:
  - Assignments to local variables (e.g. `Name` in `Assign.targets`).
  - Assignments to `self.attr` (instance attributes).
- Filters names that are not already snake_case (e.g. regex or `name != name.lower()` with allowed underscores).
- Outputs `file:line: current_name -> suggested_snake_name`.

Suggested name mapping: camelCase/PascalCase → snake_case (e.g. `readingSettings` → `reading_settings`). Handle existing underscores (e.g. `obsnp_nospecformat` is already snake_case).

---

## 3. Refactoring order and batching

- **By module:** Refactor one module (one `.py` file) or a small group of related files at a time.
- **Within a file:** Prefer doing all renames for that file in one go so that references (e.g. same variable used on multiple lines) are updated together.
- **Run tests after each batch:** e.g. run the test suite or the tests that touch the modified module. If there is no test for a module, run the full suite and/or a quick smoke test (e.g. load plugin, open a dialog).

Suggested order (by risk / dependency):

1. **Definitions and utils** (e.g. `definitions/midvatten_defs.py`, `tools/utils/*.py`) — few UI dependencies, many variables.
2. **Core plugin and settings** (e.g. `midvatten_plugin.py`, `midvsettings.py`, `midvsettingsdialog.py`) — already partially refactored; fix remaining variables.
3. **Tools** (e.g. `customplot.py`, `sectionplot.py`, `strat_symbology.py`, import/export tools) — refactor per file.
4. **Tests** — last, so test code matches the style of the code under test.

---

## 4. Special cases and pitfalls

- **`getattr(self, name)` / `setattr(self, name, …)`:**  
  The second argument is the attribute name. Only change it if you are renaming that attribute. Many of these reference UI widget names (already snake_case). Do not rename UI widget names again; only ensure any **variable that holds** such a name is updated if the attribute was renamed (usually already done in step 5).

- **Type-like names used as variables:**  
  e.g. `Dict = {...}` in `midvatten_defs.py`. Ruff N806 will flag `Dict`. Rename to e.g. `result_dict` or `color_dict` and update all references in that function.

- **Single-letter or short names:**  
  Leave as-is (e.g. `i`, `j`, `k`, `n`, `x`, `y`). Ruff usually does not require renaming these.

- **Names that must stay (API / Qt / QGIS):**  
  Do not rename parameters or attributes that are part of an external API (e.g. Qt slot parameters). Our style applies to Midvatten’s own variables and attributes.

- **Private names:**  
  Keep leading underscore; make the rest snake_case (e.g. `_internalHelper` → `_internal_helper`).

---

## 5. Checklist for each file

1. Run Ruff for that file:  
   `ruff check path/to/file.py --select N806,N816`
2. List renames: current_name → new_name (snake_case).
3. For each rename:
   - Replace definition/assignment (e.g. `variableName =` → `variable_name =`).
   - Replace all other references in the same file (search for the old name).
   - If it’s `self.attr`, search the repo for `self.attr` and update other files that reference it.
4. If the file uses `getattr(self, var)` or `setattr(self, var, …)` and `var` is built from a refactored name, update the string or variable that builds `var` so it matches the new attribute name.
5. Run tests (full or relevant subset).
6. Commit (e.g. “Style: variables to snake_case in midvatten_defs.py”).

---

## 6. Reference: key files with variables to fix

From earlier findings (Ruff N806 and codebase search), likely hotspots include:

- **definitions/midvatten_defs.py** — e.g. `Dict` used as variable name; fix and update references.
- **tools/midvsettings.py** — e.g. `readingSettings`, `settingsareloaded` (already snake_case), `dataType`, `functions`, `output` in loops.
- **midvatten_plugin.py** — instance attributes and locals (e.g. `first_start` already ok; check for camelCase).
- **tools/piper.py** — e.g. `My_format`, `obsimport`, `obsnp_nospecformat`, `obsrecarray` (some already snake_case).
- **tools/customplot.py**, **sectionplot.py**, **strat_symbology.py** — many locals and instance attributes; refactor in small batches and run tests.
- **tools/import_*.py**, **export_*.py** — same approach.

Ruff’s output is the source of truth for what to rename; the list above is only a starting point.

---

## 7. Tooling reminder

- **Lint:** From repo root, `ruff check .` (or path to a subfolder).
- **Format:** `ruff format .`.
- **Config:** `pyproject.toml` at repo root; `.venv` excluded. N806/N816 are part of the “N” (pep8-naming) rules already selected.

After variables refactoring, the codebase should pass Ruff naming rules (N801, N802, N806, N815, N816, etc.) for the files in the repository, with only the documented exclusions (e.g. `classFactory`, `initGui`, Qt overrides) in `extend-ignore-names`.

---

## 8. Summary for the new agent

1. **Goal:** Rename variables and non-UI instance attributes to `lowercase_with_underscores` across the repository.
2. **Discovery:** Run `ruff check . --select N806,N816` and optionally extend `scripts/style_audit.py` for a rename list.
3. **Order:** Refactor by module/file; run tests after each batch.
4. **Care with:** `getattr`/`setattr` (only change if the attribute is being renamed); type-like variable names (e.g. `Dict` → `result_dict`); and UI-derived attributes (already done in step 5).
5. **Done when:** Ruff N806/N816 are clear (or only expected exclusions remain) and tests pass.
