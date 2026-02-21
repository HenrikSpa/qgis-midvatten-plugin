# Plan: Rewrite SQL from concatenation to single-string format

**Goal:** Replace SQL built with long string concatenations like `"sql" + ph + "more sql"` by single strings using placeholders, e.g. `"sql {ph} more sql"` or f-strings, **only** where the concatenation is a single expression (no if-statements, loops, or separate function calls in the middle).

**Format to use:** Prefer f-strings, e.g. `sql = f"SELECT ... WHERE name = {ph}"`, or `.format(ph=ph)` when the same placeholder appears multiple times. For `sql_ident()` / `sql_alter_db()` templates, keep `{t}`, `{c}` etc. for the API and use f-strings for the rest, e.g. `f"SELECT ... FROM {{t}} WHERE obsid = {ph}"` so that `{t}` is still substituted by `sql_ident`.

**Out of scope (do not combine):**
- Strings separated by **if/else** (different SQL per branch): each branch can still be rewritten to one string per branch.
- Strings built inside **loops** or with **+=** that add conditional fragments.
- Strings that include **function call results** in the middle of the concatenation (e.g. `"WHERE " + db_utils.test_not_null_and_not_empty_string(...) + " AND " + ...`): leave as-is or only change the literal parts.

---

## 1. Tests (simple one-placeholder INSERT)

All of these are a single assignment with one `ph` and no conditionals in the expression. Replace by a single string.

| File | Line(s) | Current | Rewrite to |
|------|---------|--------|------------|
| test_db_utils_postgis.py | 171 | `insert_sql = "INSERT INTO obs_points (obsid) VALUES (" + ph + ")"` | `insert_sql = f"INSERT INTO obs_points (obsid) VALUES ({ph})"` |
| test_db_utils_spatialite.py | 171 | same | same |
| test_vectorlayer_spatialite.py | 90, 126, 162, 200, 247, 294 | same (6 occurrences) | same |

---

## 2. create_db.py

| Location | Current pattern | Rewrite |
|----------|-----------------|--------|
| ~555–557 | `table_descr_sql = ("SELECT name, sql from sqlite_master WHERE name = " + ph + ";")` | `table_descr_sql = f"SELECT name, sql from sqlite_master WHERE name = {ph};"` |
| ~584–587 | `sql = ("INSERT INTO about_db (tablename, ...) VALUES (" + placeholders + ")")` | `sql = f"INSERT INTO about_db (tablename, columnname, description, data_type, not_null, default_value, primary_key, foreign_key) VALUES ({placeholders})"` |
| ~616–619 | Same INSERT with 8 placeholders (inside `for column` loop; the assignment itself is one expression) | Same style: single f-string with `{placeholders}` |
| ~647–656 | `sql = ("UPDATE about_db SET description = CASE ... " + ph + " ELSE ... " + ph + " END WHERE tablename = " + ph + " and columnname = " + ph)` | Use one string with four placeholders: e.g. `sql = f"UPDATE about_db SET description = CASE WHEN description IS NULL THEN {ph} ELSE description \|\| {ph} END WHERE tablename = {ph} and columnname = {ph}"` (or `.format(ph=ph)` and literal `{ph}` in the string). |

---

## 3. tools/utils/db_utils.py

| Function | Location | Current pattern | Rewrite |
|----------|----------|-----------------|--------|
| get_srid_name | ~1538–1541 | `"SELECT ... WHERE srid = " + ph + ";"` | `f"SELECT split_part(srtext, '\"', 2) AS \"name\" FROM spatial_ref_sys WHERE srid = {ph};"` |
| test_not_null_and_not_empty_string | ~1483–1491 | `sql = col_ident + " IS NOT NULL AND " + col_ident + " !='' "` (and other branches) | Per branch: `sql = f"{col_ident} IS NOT NULL AND {col_ident} !='' "` and `sql = f"{col_ident} IS NOT NULL"`. (Branches stay separate.) |
| test_if_numeric | ~1563–1570 | `"(typeof(" + col_ident + ")=typeof(0.01) OR typeof(" + col_ident + ")=typeof(1))"` and `"pg_typeof(" + col_ident + ") in (" + type_list + ")"` | SQLite: `f"(typeof({col_ident})=typeof(0.01) OR typeof({col_ident})=typeof(1))"`. Postgres: `f"pg_typeof({col_ident}) in ({type_list})"`. |

---

## 4. import_data_to_db.py

| Location | Current | Rewrite |
|----------|--------|--------|
| ~590–592 | `sql = dbconnection.sql_ident("INSERT INTO {t} VALUES (" + placeholders + ")", t=temptable_name)` | `sql = dbconnection.sql_ident(f"INSERT INTO {{t}} VALUES ({placeholders})", t=temptable_name)` |

---

## 5. loggereditor.py

| Location | Current pattern | Rewrite |
|----------|-----------------|--------|
| ~300–304 | `meas_sql = ("SELECT date_time, level_masl FROM w_levels WHERE obsid = " + ph + " ORDER BY date_time")` | `meas_sql = f"SELECT date_time, level_masl FROM w_levels WHERE obsid = {ph} ORDER BY date_time"` |
| ~317–321 and ~323–326 | `head_level_masl_sql = ("SELECT ... FROM w_levels_logger WHERE obsid = " + ph + " ORDER BY date_time")` (two branches) | Each branch: single f-string with `{ph}`. |
| ~449–454 | `sql = ("SELECT date_time, (level_masl - (head_cm/100)) AS loggerpos FROM w_levels_logger WHERE date_time = (SELECT max(date_time) ... WHERE obsid = " + ph + " AND ...) AND obsid = " + ph)` | One f-string with two placeholders: `sql = f"SELECT date_time, (level_masl - (head_cm/100)) AS loggerpos FROM w_levels_logger WHERE date_time = (SELECT max(date_time) AS date_time FROM w_levels_logger WHERE obsid = {ph} AND (CASE WHEN level_masl IS NULL THEN -1000 ELSE level_masl END) > -990 AND level_masl IS NOT NULL AND head_cm IS NOT NULL) AND obsid = {ph}"` (or use .format(ph=ph) with literal `{ph}` in the string). |
| ~523–536 (update_level_masl_from_level_masl) | Long concatenation of literals, `ph`, and `date_time_as_epoch` | One f-string: `sql = f"UPDATE w_levels_logger SET level_masl = {ph} + level_masl WHERE obsid = {ph} AND level_masl IS NOT NULL AND {date_time_as_epoch} >= {ph} AND {date_time_as_epoch} <= {ph}"`. |
| ~558–571 (update_level_masl_from_head) | Same structure with `head_cm / 100` | One f-string with `{ph}` and `{date_time_as_epoch}`. |
| ~1156–1165 | `where_dt_sql = (" AND " + date_time_as_epoch + " >= " + ph + " AND " + date_time_as_epoch + " <= " + ph)` | `where_dt_sql = f" AND {date_time_as_epoch} >= {ph} AND {date_time_as_epoch} <= {ph}"` |
| ~1169–1175 and ~1188–1194 | `sql = ("UPDATE " + table_ident + " SET level_masl = NULL WHERE obsid = " + ph + where_dt_sql)` and similar DELETE | `sql = f"UPDATE {table_ident} SET level_masl = NULL WHERE obsid = {ph}{where_dt_sql}"` and `sql = f"DELETE FROM {table_ident} WHERE obsid = {ph}{where_dt_sql}"` (after rewriting `where_dt_sql` as above). |

---

## 6. sectionplot.py

| Location | Current | Rewrite |
|----------|--------|--------|
| ~2645–2653 | `sql = self.dbconnection.sql_ident("INSERT INTO {t} (dummyfield, geometry) VALUES ('0', ST_GeomFromText(" + ph + ", " + ph + "))", t=...)` | `sql = self.dbconnection.sql_ident(f"INSERT INTO {{t}} (dummyfield, geometry) VALUES ('0', ST_GeomFromText({ph}, {ph}))", t=self.temptable_name)` (ensure `ph` is defined before this). |
| ~2021–2025 | `sql = self.dbconnection.sql_ident("SELECT date_time, level_masl, obsid FROM {t} WHERE obsid IN (" + self.dbconnection.placeholder_string(...) + ")", t=...)` | Assign placeholder string to a variable, then e.g. `sql = self.dbconnection.sql_ident(f"SELECT date_time, level_masl, obsid FROM {{t}} WHERE obsid IN ({placeholders})", t=..., )` with `placeholders = self.dbconnection.placeholder_string(list(self.obsids_x_position.keys()))`. |

---

## 7. midvatten_plugin.py

| Location | Current | Rewrite |
|----------|--------|--------|
| ~1635–1638 | `sql = dbconnection.sql_ident("SELECT obsid FROM {t} WHERE obsid = " + dbconnection.placeholder_sign(), t=...)` | `ph = dbconnection.placeholder_sign()` then `sql = dbconnection.sql_ident(f"SELECT obsid FROM {{t}} WHERE obsid = {ph}", t=self.ms.settingsdict["wqualtable"])` so that the template is a single string. |

---

## 8. customplot.py

| Location | Current | Rewrite / note |
|----------|--------|----------------|
| ~1273–1280 | `sql = dbconnection.sql_ident("SELECT DISTINCT {c} FROM {t} WHERE {oc} IN " + clause + " ORDER BY {c}", ...)` | Single string: `sql = dbconnection.sql_ident(f"SELECT DISTINCT {{c}} FROM {{t}} WHERE {{oc}} IN {clause} ORDER BY {{c}}", c=..., t=..., oc=...)`. |

**Do not change:** The construction of `_sql` that uses `+ db_utils.test_not_null_and_not_empty_string(...) + " AND " + ...` (function call in the middle). The later `sql = _sql + f" AND ..."` inside loops/conditionals are also out of scope for “combining into one”; leave as-is.

---

## 9. wqualreport.py

**Do not combine:** SQL is built with `sql += ...` and if/else on `date_time` and optional columns. Strings are conditionally extended; leave structure as-is.

---

## 10. custom_drillreport.py

**Optional (per-branch):** The assignments like `sql = r"""select Count(%s) from w_levels where obsid = '%s'""" % (column, obsid)` are in if/else branches. Each branch is a single assignment; if desired, these could be converted to use placeholders and a single string per branch (e.g. with `dbconnection.placeholder_sign()` and execute_args). This is a separate “safe SQL” refactor; not required for the “single string instead of concatenation” plan.

---

## Order of work and testing

1. **Tests first:** Apply changes in `test_db_utils_postgis.py`, `test_db_utils_spatialite.py`, and `test_vectorlayer_spatialite.py`; run the create_db and db_utils tests to ensure nothing breaks.
2. **db_utils.py:** Refactor `get_srid_name`, `test_not_null_and_not_empty_string`, `test_if_numeric`; run tests again.
3. **create_db.py:** Refactor all four patterns; run `test_create_spatialite_db.py` (and related) as per project rules.
4. **import_data_to_db.py**, **loggereditor.py**, **sectionplot.py**, **midvatten_plugin.py**, **customplot.py** in any order; run the relevant tests after each file.

**Test command (from repo root or test):**  
`nosetests3 test_create_spatialite_db.py --failure-detail --with-doctest --nologcapture` then other tests as needed.

---

## Summary

| Category | Files | Count of changes |
|----------|--------|------------------|
| Tests | test_db_utils_postgis, test_db_utils_spatialite, test_vectorlayer_spatialite | 8 simple INSERTs |
| Core / DB | create_db.py, db_utils.py, import_data_to_db.py | 8+ edits |
| Tools | loggereditor.py, sectionplot.py, midvatten_plugin.py, customplot.py | 12+ edits |
| Out of scope | wqualreport.py (conditional +=), customplot _sql (function in middle) | 0 |

All targeted edits are “one assignment → one string” with no if/loop/function call in the middle of the concatenation.
