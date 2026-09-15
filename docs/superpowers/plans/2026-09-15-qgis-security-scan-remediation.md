# Midvatten 2.0.0 — QGIS plugin repository security-scan remediation

## Why the upload was blocked

plugins.qgis.org now runs an automated **Security & Quality Scan** on every uploaded
version (QEP-409). Two checks are **CRITICAL/blocking**: **Bandit** and **detect-secrets**.
Our 2.0.0 zip failed **Bandit only** (40% pass rate, 1 critical check failed).

Scanner facts (verified from `qgis-app/plugins/security_scanner.py`):
- Bandit is invoked `bandit -r <dir> -f json --quiet` with an explicit test-include list.
- `--ignore-nosec` is **never passed** → inline `# nosec` comments **are honored**.
- Pass = `issues_found == 0`. **Every finding must be suppressed or removed** to unblock.
- It does **not** reliably read the plugin's own bandit config → per-line `# nosec` is the
  robust, precedent-backed path (cf. FilterMate PR #74 → 0 B608).
- File-Permissions check flags only `.py` files whose zip entry has the Unix exec bit; it is
  **non-blocking** (warning).
- detect-secrets: **0 findings — PASS**. Suspicious-files: **0 — PASS**.
- A blocked version cannot be unblocked; we must upload a **new** version that scans clean.

## Findings inventory (from the scan report, reproduced locally with bandit 1.9.3)

| Check | Rule | Count | Blocking? |
|---|---|---|---|
| Bandit | **B608** possible SQL injection (f-string SQL) | **104** | YES |
| Bandit | **B110** try/except/pass | **15** | YES |
| Bandit | **B101** assert used | **1** | YES |
| File Permissions | `.py` with exec bit | 19 | no (warning) |
| Flake8 | style/quality | 6 | no |
| detect-secrets | — | 0 | PASS |

Total blocking Bandit findings: **120** across 40 files.

## Security assessment (the real question, not just the scanner's)

The plugin has a genuine safe-SQL layer (`tools/utils/db_utils/dialect.py`):
`ident()`/`quote_ident()` (validated, double-quoted identifiers), `sql_ident()` (identifier-only
template format), `in_clause()`/`placeholder()`/`placeholders()` (DB-API `?`/`%s` binding),
`sql_literal()` (escaped literal). Values are bound; identifiers — which cannot be bound — are
quoted through these helpers. Bandit's B608 fires on *any* f-string/`%`/`.format()` in a SQL
string and cannot see that the interpolated parts are already safe.

**Audit result (4 parallel reviewers, all 120 Bandit sites traced + manual spot-checks):**
**0 REAL injections.** Every one of the 104 B608 sites interpolates only (a) an
`ident()`/`sql_ident()`/`quote_ident()`-quoted identifier, (b) a placeholder string
(`?`/`%s` via `placeholder()`/`placeholders()`/`in_clause()`), (c) a `sql_literal()`-escaped
value, or (d) a hardcoded constant — with all *values* DB-API-bound. The genuinely
user/settings-derived identifiers (`loggereditor.py:3014` ref-series x/y/table cols;
`loggereditor_refseries.py:104`; `sectionplot/data.py:350` screen text col;
`wqualreport.py` param/unit/sort cols; `import_interlab4.py:1491` allowlisted) are all gated by
`ident()` which validates + quotes and raises `UnsafeIdentifierError` on anything unexpected.
All 15 B110 sites are harmless best-effort cleanup (rollback/close/deleteLater/cancel/UI-refresh).
B101 is an internal invariant. **Conclusion: the scan is 100% false positives — a
scanner-compliance task, not a vulnerability fix.**

Out-of-scope hardening nit (NOT flagged by Bandit, NOT exploitable today, optional):
`tools/sectionplot/data.py` `get_length_along()` (~lines 124/139) `.format()`s `temptable_name`
and `funcname` without `ident()`. Both are effectively trusted (hardcoded default table +
allowlisted function names). Wrap in `ident()` for defense-in-depth *if* that code is touched.

## Remediation

### 1. Bandit B608 (104) — REQUIRED
For every confirmed-safe site, add a scoped suppression with a short justification, e.g.:
```python
sql = f"SELECT {col_ident} FROM {table_ident} WHERE obsid = {ph}"  # nosec B608 - ident()+placeholder, no raw values
```
Placement must be on the physical line Bandit attributes the finding to (verify with bandit, do
not guess). Any site the audit marks REAL gets a proper code fix (route the identifier through
`ident()` / bind the value) instead of `# nosec`.

### 2. Bandit B110 (15) — REQUIRED
These are best-effort cleanup paths (rollback/close/deleteLater/cancel). Add `# nosec B110 -
best-effort cleanup` on the reported line. (Alternative if preferred: replace `pass` with a
`message_utils.MessagebarAndLog.debug/warning` log — more churn, behavior change; not chosen.)

### 3. Bandit B101 (1) — REQUIRED, real fix
`tools/export_engine.py:326` — replace the `assert` invariant with an explicit raise so it is not
stripped under `python -O`:
```python
if "source" not in src_cols or "obsid" not in src_cols:
    raise ValueError("_migrate_logger_chunk called but src_cols missing 'source' or 'obsid'")
```

### 4. File Permissions (19) — RECOMMENDED (clears the warning)
`git update-index --chmod=-x` on the 19 tracked `100755` `.py` files, then commit. (`git archive`
ships git's mode bits, so a plain `chmod` is not enough.) Optionally normalize other shipping
`100755` assets (icons/ui/sql/qml/templates/metadata.txt/resources.qrc) to 644 for cleanliness —
not required (scanner only flags `.py`).

### 5. Flake8 (6) — OPTIONAL
Non-blocking. Worth doing: `loadlayers.py:131` F821 undefined `QgsVectorLayer` (latent NameError —
add the import). Also F402 loop-var shadowing `tick` (loggereditor.py:2908/2914) and E731 lambda
assignments (piper.py:920, stratigraphy.py:485/489).

## Verification (Luna must run, evidence required)
1. Working-tree scan clean:
   `bandit -r . -x ./test,./.venv,./docs,./scripts,./.claude,./.worktrees,./_pkgroot,./__pycache__ -q -f json`
   → `results == []`.
2. Archive-parity scan (mirrors what the server sees):
   `git archive --prefix=midvatten/ HEAD | tar -x -C <tmp>` then `bandit -r <tmp>/midvatten -q` → 0.
3. `ruff check .` and `ruff format --check .` clean.
4. Targeted tests for touched export/upgrade path + `test/test_qt6_compat_static.py`; do NOT change
   any test reference data.
5. Confirm the 19 `.py` are mode `100644` in `git ls-files -s`.

## Out of scope
No schema changes. No behavior changes beyond the B101 assert→raise. Do not touch the shared QGIS
plugins symlink. Bump version (metadata.txt + pyproject.toml) is a release step, handled after the
scan passes — flag it, don't guess the number.
