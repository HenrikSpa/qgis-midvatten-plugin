# Database refactor – instructions for the next agent

Use this document as the main instructions to continue the database refactor. For context and what’s already done, read **`docs/DB_REFACTOR_PLAN_AND_LOG.md`** (sections “Log: Done” and “Log: Remaining”).

---

## 1. What’s in place

- **`tools/utils/db_utils/`** – Package (single entry point) with backends (SQLiteBackend, PostgreSQLBackend), factory (`create_backend`), facade (DbConnectionManager), execution, schema, helpers, sqlfile, dialect, settings, errors. Existing imports `from midvatten.tools.utils import db_utils` use this package directly.
- **Option A** is in use: db_settings keys stay `"spatialite"` and `"postgis"`.
- Execute API: single `sql: str` and optional `args`; `all_args` supported for backward compatibility.

---

## 2. What you should do (in order)

### 2.1 Fix the failing test

- **Test:** `test/test_db_utils_spatialite.py` → `TestSqlInjectionHardening.test_in_clause_does_not_expand_scope`
- **Symptom:** After inserting P1 and P2 via `sql_alter_db`, a new `DbConnectionManager()` runs `SELECT obsid FROM obs_points WHERE obsid IN (?)` with args `["P1"]` and gets `[]` instead of one row.
- **Likely cause:** Different database used for inserts (in `sql_alter_db` with `use_or_create_connection(None)`) and for the query (new `DbConnectionManager()`). The test base `MidvattenTestSpatialiteDbSv` sets up a temp DB via `self.midvatten.new_db()` and project settings; confirm that both code paths use the same project database (same path / same db_settings).
- **Actions:**
  1. In the test, verify how the project “Midvatten” / “database” setting is set after `new_db()` and what `DbConnectionManager()` and `use_or_create_connection(None)` read.
  2. If the test uses a temp DB path, ensure that path is what’s written to the project and that no code overwrites it between the inserts and the query.
  3. Fix the test or the code so that inserts and the subsequent query hit the same database. Then re-run the test until it passes.

### 2.2 Run the full test suite (in this order)

From the **midvatten repository root**, run:

1. **Create-DB tests (must pass first):**
   ```bash
   nosetests3 test/test_create_spatialite_db.py test/test_create_postgis_db.py --failure-detail --with-doctest --nologcapture --stop
   ```

2. **DB utils and midvatten utils:**
   ```bash
   nosetests3 test/test_db_utils_spatialite.py test/test_db_utils_postgis.py test/test_midvatten_utils.py test/test_midvatten_defs.py --failure-detail --with-doctest --nologcapture --stop
   ```

3. **Tests that touch the modified DB code** (e.g. export, import, sectionplot, stratigraphy, etc. – any test that uses `db_utils` or `DbConnectionManager`). Run them and fix any failures.

4. **Full suite:**
   ```bash
   nosetests3 --failure-detail --with-doctest --nologcapture --stop
   ```

Fix any failing tests; do not change test reference data or expectations unless the product behaviour was intentionally changed and the test should be updated.

### 2.3 Lint and format

- Run:  
  `ruff check --fix .`  
  then:  
  `ruff format .`  
- Resolve any remaining issues (e.g. type hints: use `list` / `tuple` instead of `List` / `Tuple` where ruff or project style require it). Apply to `tools/utils/db_utils/` as needed.

### 2.4 Optional: i18n and naming

- If any user-facing strings still say “spatialite” or “postgis” and the product owner wants “SQLite” / “PostgreSQL” in the UI, update the strings in the code and add or adjust entries in the i18n files under `i18n/` as needed. Do not change the **stored** db_settings keys (`"spatialite"` / `"postgis"`); those stay for backward compatibility (Option A).

---

## 3. Rules to follow

- **Database schema:** Do not change table/column/view names or SQL schema unless explicitly asked.
- **Tests:** Follow `.cursor/rules/testing-rules/` (create/run/modify). Use the MessagebarAndLog mock and `--failure-detail --with-doctest --nologcapture --stop` when running nosetests3.
- **Style:** Follow PEP8 and project rules (e.g. `.cursor/rules/rule-for-coding-style.mdc`); use ruff for check and format.
- **db_utils compatibility:** The package `midvatten.tools.utils.db_utils` is the single entry point; anything importable from it must remain so. Use grep for `from midvatten.tools.utils.db_utils import` and `db_utils.` to find usages and ensure they still work.

---

## 4. Updating the log

After each logical chunk of work:

1. Open **`docs/DB_REFACTOR_PLAN_AND_LOG.md`**.
2. Under **“Log: Done”**, add a short line describing what you did (e.g. “Fixed test_in_clause_does_not_expand_scope; cause was …”, “Ruff fixes in db/”, “Full test suite passes”).
3. Under **“Log: Remaining”**, remove or rephrase items that are done and add any new follow-ups you discover.

---

## 5. If you need to hand off again

If you run out of context or time:

1. Update **“Log: Done”** and **“Log: Remaining”** in `docs/DB_REFACTOR_PLAN_AND_LOG.md` with the current state.
2. Tell the user: “Continue the database refactor using the instructions in **`docs/DB_REFACTOR_NEXT_STEPS.md`**. Start from section 2 and use the log in **`docs/DB_REFACTOR_PLAN_AND_LOG.md`** for what’s done and what’s left.”

That gives the next agent the same entry point and a clear list of next steps.
