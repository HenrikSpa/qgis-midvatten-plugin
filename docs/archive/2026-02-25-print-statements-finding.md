> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-02-25 · modified: 2026-02-25 · archived: 2026-07-31
> origin: ~/.claude/refactor_suggestions/finding4_print_statements.md

# Finding 4 — Debug `print()` Statements in Production Code

Replace all `print()` calls with `MessagebarAndLog` (the project's logging infrastructure).
In a QGIS plugin, stdout may be invisible to end-users; these calls bypass the log panel entirely.

## Replacement pattern

| Old | New |
|-----|-----|
| `print("some info")` | `common_utils.MessagebarAndLog.info(log_msg="some info")` |
| `print("some error: ...")` (in except block) | `common_utils.MessagebarAndLog.warning(log_msg=traceback.format_exc())` |
| `print("debug value ...")` (diagnostic) | Remove, or keep as `MessagebarAndLog.info(log_msg=...)` |

---

## tools/wqualreport_compact.py

| Line | Current code | Action |
|------|-------------|--------|
| 428 | `print(f"Something went wrong: {traceback.format_exc()}")` | → `MessagebarAndLog.warning(log_msg=traceback.format_exc())` |
| 718 | `print("here was an error: %s" % row)` | → `MessagebarAndLog.warning(log_msg=f"Row caused error: {row}")` |

---

## tools/import_data_to_db.py

| Line | Current code | Action |
|------|-------------|--------|
| 189 | `print(f"remaining_rownumbers {remaining_rownumbers=}")` | Remove (debug artifact) |
| 277 | `print(f"{remaining_rownumbers=} {all_rownumbers=}")` | Remove (debug artifact) |
| 796 | `print(f" {sql=} {skip_obsids=}")` | Remove (debug artifact) |

---

## tools/prepareforqgis2threejs.py

| Line | Current code | Action |
|------|-------------|--------|
| 125 | `print(layer.name() + " is not valid layer")` | → `MessagebarAndLog.warning(log_msg=f"{layer.name()} is not valid layer")` |
| 145 | `print("Loading stylefile %s failed." % stylefile)` | → `MessagebarAndLog.warning(log_msg=f"Loading stylefile {stylefile} failed.")` |

---

## tools/import_diveroffice.py

| Line | Current code | Action |
|------|-------------|--------|
| 513 | `print(f"Got error {traceback.format_exc()}")` | → `MessagebarAndLog.warning(log_msg=traceback.format_exc())` |

---

## tools/loggereditor.py

| Line | Current code | Action |
|------|-------------|--------|
| 290 | `print("error obsid " + str(obsid))` | → `MessagebarAndLog.warning(log_msg=f"error obsid {obsid}")` |
| 791 | `print("Error in contains_more_than_nan, recarray: " + str(a_recarray))` | → `MessagebarAndLog.warning(log_msg=f"Error in contains_more_than_nan, recarray: {a_recarray}")` |

---

## tools/create_db.py

| Line | Current code | Action |
|------|-------------|--------|
| 206 | `print(str(sql))` | → `MessagebarAndLog.info(log_msg=str(sql))` |
| 359 | `print(str(sql))` | → `MessagebarAndLog.info(log_msg=str(sql))` |
| 360 | `print("numlines: " + str(len(sql_lines)))` | → `MessagebarAndLog.info(log_msg=f"numlines: {len(sql_lines)}")` |
| 361 | `print(f"Error on line nr {str(linenr)}")` | → `MessagebarAndLog.warning(log_msg=f"Error on line nr {linenr}")` |
| 362 | `print("before " + sql_lines[linenr - 1])` | → `MessagebarAndLog.info(log_msg=f"before {sql_lines[linenr-1]}")` |
| 364 | `print("after " + sql_lines[linenr + 1])` | → `MessagebarAndLog.info(log_msg=f"after {sql_lines[linenr+1]}")` |
| 629 | `print(sql)` | → `MessagebarAndLog.info(log_msg=str(sql))` |

---

## tools/utils/midvatten_utils.py

| Line | Current code | Action |
|------|-------------|--------|
| 404 | `print(f"Tablename {tablename} not found among {existing_tables}")` | → `MessagebarAndLog.warning(log_msg=f"Tablename {tablename} not found among {existing_tables}")` |

---

## tools/strat_symbology.py

| Line | Current code | Action |
|------|-------------|--------|
| 531 | `print(str(stylename))` | Remove (debug artifact) |

---

## tools/utils/string_utils.py

| Line | Current code | Action |
|------|-------------|--------|
| 175 | `print(str(innerword))` | Remove (debug artifact) |

---

## tools/utils/date_utils.py

| Line | Current code | Action |
|------|-------------|--------|
| 247 | `print("Timeformat not supported for %s" % datestring)` | → `MessagebarAndLog.warning(log_msg=f"Timeformat not supported for {datestring}")` |

---

## tools/utils/gui_utils.py

| Line | Current code | Action |
|------|-------------|--------|
| 408 | `print(f"Error, {e}, followup:\n{traceback.format_exc()}")` | → `MessagebarAndLog.warning(log_msg=traceback.format_exc())` |

---

## tools/stratigraphy.py

| Line | Current code | Action |
|------|-------------|--------|
| 71 | `print("Load failed due: " + e.problem)` | → `MessagebarAndLog.warning(log_msg=f"Load failed due: {e.problem}")` |
| 96 | `print("DataSanityError %s" % str(e))` | → `MessagebarAndLog.warning(log_msg=f"DataSanityError {e}")` |
| 108 | `print("exception : %s" % str(e))` | → `MessagebarAndLog.warning(log_msg=f"exception: {e}")` |
| 414 | `print(str(obsid) + " has no strata information")` | → `MessagebarAndLog.info(log_msg=f"{obsid} has no strata information")` |

---

## tools/piper.py

| Line | Current code | Action |
|------|-------------|--------|
| 65 | `print(...)` (piper data row) | → `MessagebarAndLog.info(log_msg=...)` |
| 74 | `print(",".join([ru(col) for col in row]))` | → `MessagebarAndLog.info(log_msg=",".join([ru(col) for col in row]))` |
| 78 | `print("failed printing piper data...")` | → `MessagebarAndLog.warning(log_msg="failed printing piper data...")` |

---

## tools/midvsettings.py

| Line | Current code | Action |
|------|-------------|--------|
| 104 | `print(f"debug info; midvsettings.save_settings failed ...")` | → `MessagebarAndLog.warning(log_msg=...)` |

---

## tools/sectionplot.py

| Line | Current code | Action |
|------|-------------|--------|
| 1383 | `print(f"Sampling as polygon")` | → `MessagebarAndLog.info(log_msg="Sampling as polygon")` |
| 1386 | `print(f"Sampling as raster")` | → `MessagebarAndLog.info(log_msg="Sampling as raster")` |
| 2267 | `print(f"Detach pressed")` | Remove (debug artifact) |
| 2305 | `print(f"Error, {e}, followup:\n{traceback.format_exc()}")` | → `MessagebarAndLog.warning(log_msg=traceback.format_exc())` |

---

## tools/wqualreport.py

| Line | Current code | Action |
|------|-------------|--------|
| 59 | `print(...)` | → `MessagebarAndLog.info(log_msg=...)` |
| 68 | `print(...)` | → `MessagebarAndLog.info(log_msg=...)` |
| 79 | `print(...)` | → `MessagebarAndLog.info(log_msg=...)` |
| 123 | `print(...)` | → `MessagebarAndLog.info(log_msg=...)` |
| 148 | `print(...)` | → `MessagebarAndLog.info(log_msg=...)` |
| 206 | `print(...)` | → `MessagebarAndLog.info(log_msg=...)` |
| 224 | `print(...)` | → `MessagebarAndLog.info(log_msg=...)` |
| 323 | `print("here was an error: %s" % sublist)` | → `MessagebarAndLog.warning(log_msg=f"Row caused error: {sublist}")` |

---

## tools/export_fieldlogger.py

| Line | Current code | Action |
|------|-------------|--------|
| 1015 | `print(f"_parameters_inputtypes_hints {_parameters_inputtypes_hints}")` | Remove (debug artifact) |
| 1037 | `print(f"Got output {json_output}")` | Remove (debug artifact) |

---

## tools/utils/common_utils.py

| Line | Current code | Action |
|------|-------------|--------|
| 480 | `print(...)` | → `MessagebarAndLog.warning(log_msg=...)` |

---

## Verification

```bash
grep -rn "^\s*print(" tools/ --include="*.py"
# Should return 0 results after all changes
python3 -m pytest test/
```
