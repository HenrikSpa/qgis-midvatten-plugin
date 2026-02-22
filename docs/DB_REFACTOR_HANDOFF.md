# Database refactor – copy-paste instructions for next agent

Copy-paste the block below to a new agent to continue the database refactor.

---

## Copy from here

**Task:** Continue the database refactor. Use **`docs/DB_REFACTOR_NEXT_STEPS.md`** as the main instructions and **`docs/DB_REFACTOR_PLAN_AND_LOG.md`** for what’s done and what’s left.

**Already done (you can skip):**
- Section 2.1: Fixed failing test `test_in_clause_does_not_expand_scope` (DbConnectionManager was unwrapping single-element tuple args; now only unwraps list-of-one-row).
- Section 2.2 steps 1–2: Create-DB tests and db_utils/midvatten_utils/defs tests run and pass. Exported `sqlite_internal_tables` and `postgis_internal_tables` from db package and db_utils. Fixed `get_srid_name` for PostGIS (use `srtext`, extract short name; `test_drillreport_postgis` passes).
- Section 2.3: Ruff format applied; type hints in `tools/utils/db/` updated (List/Tuple/Dict → list/tuple/dict).

**What you should do (in order):**
1. **Run the full test suite** from the midvatten repo root:
   ```bash
   nosetests3 --failure-detail --with-doctest --nologcapture --stop
   ```
   Fix any failing tests. Do not change test reference data unless product behaviour was intentionally changed.

2. **Update the log:** In `docs/DB_REFACTOR_PLAN_AND_LOG.md`, under “Log: Done” add a line if you fixed anything (e.g. “Full test suite passes” or “Fixed …”). Under “Log: Remaining” remove or rephrase items that are done.

3. **Optional:** If project style requires it, resolve remaining ruff in `tools/utils/db/` (UP031 percent format, W291 trailing whitespace). Optional: update i18n under `i18n/` if user-facing strings change.

**Rules:** Do not change database schema (table/column/view names). Follow `.cursor/rules/testing-rules/` for tests. Keep everything that used to be importable from `midvatten.tools.utils.db_utils` still importable. Use ruff for check/format; follow PEP8.

**If you hand off again:** Update “Log: Done” and “Log: Remaining” in `docs/DB_REFACTOR_PLAN_AND_LOG.md`, then tell the user: “Continue the database refactor using **`docs/DB_REFACTOR_NEXT_STEPS.md`** from section 2 and **`docs/DB_REFACTOR_PLAN_AND_LOG.md`** for what’s done and left.”

## Copy to here
