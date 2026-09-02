# Remaining GUI test work — execution plan

## STATUS (2026-09-02) — executed
- **Phase 1 ✅** regression tests for the 2 fixes: 48 passed (Qt5).
- **Phase 2 ✅** `--mode controls`: 34/34, every checkbox/combo/tab exercised, no crash.
- **Phase 3 ✅** `--mode outputs` plot-data: mpl plots assert drawn artists; 8/8.
- **Phase 4 ✅** `--mode fill`: obs_points/w_levels CSV + DiverOffice logger + interlab4 selectability; 6/6.
  → **found & fixed Qt6 bug #3** (interlab4 rows unselectable, missing `ItemIsEnabled`).
- **Phase 5 ✅** `--mode loggereditor`: load series + plot, duplicate detection + resolve dialog; 4/4.
- **Phase 6 ✅** `--mode dbutils`: backup/view/vacuum/stats/rows side effects; 6/6.
- **Phase 7 ⚠️** interlab4 selectability fixed (see Phase 4). Other §6 UX findings (calculators default to
  2099 date range, Piper legend junk, Swedish-only strings) are UX/product decisions — surfaced, not auto-fixed.
- **Phase 8 ✅** decision: `add_non_essential_tables` is a legacy upgrade action, not a bug (left as-is).
- **Phase 9 ❌** PostGIS GUI smoke — infra-blocked (container can't reach host 127.0.0.1:5432; `new_postgis_db`
  mutates the SHARED nosetests db → contention). PostGIS create/import already covered by postgis unit tests.
- **Phase 10 ✅** `--mode generic_actions`: drive via menu QActions (no manifest), 38 discovered, 38/38.
  → **found & fixed Qt6 bug #4** (Settings dock `addDockWidget(int)`, not in the manifest so the sweep missed it).

Net: 4 Qt6 bugs found & fixed, 7 test modes, both toolkits. Original plan below.

---



Follow-on to `2026-09-02-gui-test-pass-plan.md`. That plan's harness (coverage/create_db/fill/outputs
+ Qt5 host) is built and merged. This plan enumerates and sequences everything still untested, from the
gap analysis of 2026-09-02. Each phase adds a `runner.py` mode (or extends one), runs it in the isolated
Qt6 container, asserts real effects, and is committed on its own. Ordered by value ÷ risk.

## Phase 1 — Regression-check the two Qt6 fixes  ✅ do first, no new code
Run the existing unit tests that touch `_sectionplot.py` and `ui/compact_w_qual_report.ui` to confirm the
fixes don't regress. Find them (`grep -rl sectionplot\|compact test/`), run, report. Gate before more work.

## Phase 2 — Exercise-controls sweep (Group C)  [`--mode controls`]
Re-add `Context.exercise_controls` (removed in cleanup). For each action that opens a window in the
coverage sweep: open it, toggle every checkbox, cycle every combo through its items, walk every tab page;
assert no traceback/Critical. Catches controls that crash on interaction. Reuses the coverage dispatch.

## Phase 3 — Plot & calculator correctness (Group D+)  [extend `--mode outputs` → `--mode actions`]
Coverage only proves these *open*. Add real assertions:
- Plots (`plot_timeseries`, `plot_xy`, `plot_stratigraphy`, `plot_section`, `plot_piper`): after dispatch,
  find the matplotlib figure and assert its axes actually drew artists (`len(ax.lines)+len(ax.collections)>0`)
  — an empty plot must fail.
- `wlvlcalculate`: on a writable copy, drive the modal (set a real date range spanning the data, accept),
  assert `w_levels.level_masl` count increased / recomputed.
- `calculate_aveflow`: select PW1001, run, assert `w_flow.aveflow` populated.
- `export_fieldlogger`: drive to completion, assert a FieldForm JSON/locations file written.

## Phase 4 — The other importers (Group A fill, remainder)  [extend `--mode fill`]
Into a fresh DB (obs_points loaded first as FK parent):
- `import_logger`: DiverOffice `.MON`, Levelogger `.csv`, Hobo `.csv`, baro→meteo — cycle the format
  dropdown, run one per format, assert `w_levels_logger`/`w_logger_series`/`meteo` grew.
- CSV `w_levels_logger` with the **series-metadata block** (distinct code path).
- `import_interlab4`: UTF-16 `.lab` with the deliberate unknown site → the **Assign-obsids** dialog must
  appear and be driveable; assert `w_qual_lab` rows.
- `import_fieldlogger`: assert `w_qual_field`/`w_levels`/`w_flow`/`comments` rows.

## Phase 5 — LoggerEditor workflows  [`--mode loggereditor`]  (biggest untested tool)
On a writable copy, load the OW100 series and exercise each workflow, asserting DB/plot effects:
adjust-level (offset/calc), delete-data (selection), series tab, **resolve duplicate timestamps** (insert
dup rows in try/finally with a pristine pre-check, resolve, assert the uniqueness invariant restored),
save. One container per this mode (LoggerEditor + plots in one process segfaults — GUI_AUTOMATION §4).

## Phase 6 — DB/utils side effects (Group D, remainder)  [fold into `--mode actions`]
Assert the callback actions' real effects on a writable copy: `vacuum_db` (runs, DB intact),
`zip_db` (exactly one new `.zip`), `calculate_db_table_rows`, `load_strat_symbology`,
`refresh_spatialite_stats`, `add_view_obs_points_lines` (view created), `prepare_layers_for_qgis2threejs`.

## Phase 7 — Pin §6 UX findings as assertions (Group E)
Turn the non-crash findings into explicit checks so they can't regress: calculators must NOT default to a
2099 date range (assert the default From/To span the data), interlab4 Assign-obsids rows selectable
(`ItemIsEnabled` present), Piper legend has no junk labels. (The 2 crashes are already pinned by coverage.)

## Phase 8 — `add_non_essential_tables` robustness decision
Investigate: it errors when a table already exists (loud on Qt5, silent on Qt6). Decide with the code in
hand whether it should be idempotent (`CREATE TABLE IF NOT EXISTS` / catch-and-skip). If yes and small,
fix + assert; if it's intended (only ever run on a DB lacking them), document and make the sweep tolerate
it on the full fixture. Bring the recommendation, don't guess.

## Phase 9 — PostGIS backend  [`--mode pg_smoke`, best-effort]
Everything so far is SpatiaLite. Check for a reachable test Postgres (mind the shared-DB contention note).
If available: `new_postgis_db` create + a CSV import + an export, on an isolated schema/db. If not
reachable, document the infra requirement and stop — do not fabricate a pass.

## Phase 10 — Cross-plugin generalization (§7), proof-of-concept
Scope: a generic action-enumerator that iterates ONE other `~/dev` plugin's registered `QAction`s and
`trigger()`s each under the same oracles, proving the harness generalizes without `_actions_manifest`.
Pick the simplest in-house plugin. Full 7-plugin rollout stays a separate initiative.

## Execution rules
- One worktree (`gui-test-pass`), isolated Qt6 container per run, unique `--name`, foreground+timeout.
- Never run host QGIS on the interactive Wayland desktop without asking (it leaks dialogs).
- Commit each phase separately; keep the shared tutorial fixture pristine (writable copies only).
- After each code change, ruff + a targeted run; merge to `ai_test` at the end (or per phase if asked).
