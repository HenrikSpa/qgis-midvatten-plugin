# Ruff full check report summary

Generated from: `ruff check . --statistics`

**Total: 1170 errors.** Of these, **424 are fixable** with `ruff check . --fix` (441 more with `--unsafe-fixes`).

---

## By rule (count → code → description)

| Count | Code   | Description |
|------:|--------|-------------|
| 178   | UP031  | Use format specifiers instead of percent format (`%` → f-string or `.format`) |
| 159   | UP006  | Use builtin generics for type annotations (`List` → `list`, etc.) |
| 150   | E722   | Do not use bare `except:` (use `except Exception:` or specific type) |
| 103   | UP009  | UTF-8 encoding declaration unnecessary (fixable) |
| 95    | UP032  | Use f-string instead of `.format()` (fixable) |
| 73    | UP026  | `mock` deprecated, use `unittest.mock` (fixable) |
| 71    | W291   | Trailing whitespace |
| 70    | UP004  | Class inherits from `object` (redundant in Python 3) (fixable) |
| 54    | N802   | Function name should be lowercase (many in test QGIS iface mocks) |
| 32    | UP035  | Deprecated typing import (e.g. `List` from `typing`) |
| 26    | UP020  | Use builtin `open` instead of alias (fixable) |
| 24    | E741   | Ambiguous variable name (e.g. `l`, `I`) |
| 23    | E402   | Module-level import not at top of file |
| 19    | UP008  | Use `super()` instead of `super(Class, self)` (fixable) |
| 16    | N803   | Argument name should be lowercase |
| 16    | W293   | Blank line contains whitespace |
| 13    | UP015  | Redundant open mode (e.g. `open(..., "r")`) (fixable) |
| 8     | E713   | Use `not in` for membership test (fixable) |
| 7     | UP030  | Format literals |
| 6     | E731   | Do not assign lambda (use def) |
| 6     | W605   | Invalid escape sequence (use raw string) |
| 5     | E711   | Compare to `None` with `is` / `is not` |
| 3     | UP034  | Extraneous parentheses (fixable) |
| 2     | E712   | Compare to True/False with `is` |
| 2     | E721   | Use `isinstance()` for type comparison |
| 2     | N815   | Variable in class scope should not be mixedCase (e.g. Qt signals in test mocks) |
| 2     | UP024  | Use `OSError` instead of alias (fixable) |
| 1     | E401   | Multiple imports on one line (fixable) |
| 1     | N801   | Class name should be CapWords |
| 1     | UP012  | Unnecessary encode UTF-8 (fixable) |
| 1     | UP018  | Unnecessary literal (fixable) |
| 1     | W292   | No newline at end of file (fixable) |

---

## Categories and suggested handling

### 1. Safe auto-fixes (run `ruff check . --fix`)

Fixes many of: UP009, UP032, UP026, UP004, UP020, UP008, UP015, E713, UP034, UP024, E401, UP012, UP018, W292.  
Does **not** fix: UP031, UP006, E722, W291, N802, N803, E741, E402, etc.

### 2. Test / QGIS mock naming (N802, N815)

- **test/_qgis_interface.py**: Methods like `addLayers`, `addLayer`, `zoomFull`, `addVectorLayer` and attribute `currentLayerChanged` mirror the **QGIS/Qt API** (camelCase). Renaming them would break tests that expect the real API shape.
- **Suggestion:** Add a per-file ignore for the test mock, e.g. in `pyproject.toml`:
  - `"test/_qgis_interface.py" = ["N802", "N815"]`
  so Ruff allows these API-matching names.

### 3. Manual or careful fixes

- **E722 (bare except):** Replace with `except Exception:` (or a more specific type) after reviewing each site.
- **UP031 / percent format:** Convert `%` formatting to f-strings or `.format()`; do file-by-file to avoid logic changes.
- **UP006 / UP035 (typing):** Replace `List`, `Dict`, etc. with `list`, `dict` and update imports; ensure no compatibility issues.
- **E402:** Move imports to top or add `# noqa` where late import is intentional (e.g. after QGIS init).
- **N803 (argument names):** Rename function parameters to snake_case; update call sites (e.g. `gridLayout_db` in midvsettingsdialog.py).
- **E741 (ambiguous names):** Rename variables like `l` to `line` or `lst` (avoid changing test reference data if comparisons depend on output).

### 4. Whitespace (W291, W293)

Can be fixed automatically by Ruff format: `ruff format .` (formatter may fix some of these; for strict cleanup, run `ruff check --fix` for W291/W293).

---

## Quick commands

```bash
# See all diagnostics
ruff check .

# Only naming (already passing after variable refactor)
ruff check . --select N806,N816

# Apply safe fixes (review diff before committing)
ruff check . --fix

# Format code
ruff format .
```

---

## Optional: extend `pyproject.toml` for test mocks

To silence N802/N815 in the QGIS interface mock only:

```toml
[tool.ruff.lint.per-file-ignores]
"test/**/*.py" = ["N802"]
"test/_qgis_interface.py" = ["N802", "N815"]
```

Or add the specific method/signal names to `extend-ignore-names` if you prefer to keep naming strict elsewhere.
