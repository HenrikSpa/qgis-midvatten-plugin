> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-07-27 · modified: 2026-07-27 · archived: 2026-07-31

# Post-review cleanup — progress ledger

Worktree: .worktrees/post-review-cleanup, branch cleanup/post-review-2026-07-27, based on ai_test @ 55b51e9
Plan: docs/superpowers/plans/2026-07-27-post-review-cleanup.md (Task 0 + 17 tasks)

Task 0: complete (commit 428dda5) — HOBO meridiem locale fix, unblocks the red baseline.
  Pre-fix baseline: 6 failed, 436 passed, 1 skipped.
  Root cause: strptime %p is locale-dependent; sv_SE defines no AM/PM strings.
  Verified: TestHoboParser 12 passed, TestLoggerImportHoboSpatialite::test_basic_hobo_import passed.
Baseline (post-Task-0): 448 passed, 1 skipped, 0 failed @ 428dda5
Task 1: complete (commits 428dda5..6bb186f, review clean/Approved)
  Deviation ratified: folded brief's assertions into existing
  test_empty_logger_frame_has_exact_schema_and_dtypes rather than adding a
  near-duplicate. Plan constraint amended accordingly (commit follows).
  Minor: test name no longer signals what it guards — left alone deliberately.
Task 2: complete (commits c4a2924..09d3264, review Approved)
  Verified independently: 151 passed (implementer report had landed in the MAIN
  checkout, not the worktree — moved into place; give future implementers a
  reminder that the report path is inside the worktree).
  Copies/file: water-level 5->3, barometric 4->2; two .loc[:,CANONICAL] slices removed.
  MINOR (defer to final review):
   - test_import_logger_pipeline.py:445 new alias test duplicates the fixture and
     parametrize axis of the test at :415; hoist shared fixture, rename to convey
     "default options" path. Reviewer judged it partially justified (shortest copy chain).
   - pipeline.py:402 kind check no-ops for a future third LoggerDataKind where the
     deleted table would KeyError. No action today (only 2 kinds).
   - pipeline.py:63 allow_extra_columns is order-strict where the old .loc slice
     was order-tolerant. Tightening; no in-repo caller affected.
Task 3: complete (commits 09d3264..03d56ef, review Approved)
  Purely subtractive (+4/-27). Reviewer verified branch equivalence by substitution
  incl. the .copy(); existing tests pin both arms and WATER_LEVEL_COLUMNS ordering.
  Brief had 2 errors, both caught by implementer: -k "post_resolution" matches nothing
  (real name: test_post_pipeline_uses_kind_policy_...), and ruff F401 is disabled repo-wide.
  Plan amended (a6cdc1b) so remaining tasks use `ruff check --select F401`.
  MINOR (defer to final review): pipeline.py:391 tests positively for WATER_LEVEL while
  :394 tests positively for BAROMETRIC — a future third kind would be routed
  inconsistently. Latent only; enum has exactly 2 members.
Task 4: complete (commits a6cdc1b..4eac62b, review Approved)
  Brief bug caught by implementer: Step 4 specified `inserted_count > 0`, which is NOT
  the negation of the original `== 0` and raises TypeError on mocked None/MagicMock —
  swallowed by the worker's broad except into a false database-failure. Used `!= 0`.
  Reviewer verified the 6-row truth table, DELETE conditions, definite assignment,
  and COUNT side effects all unchanged.
  NOTE: implementer used bare `git stash` (forbidden here). Verified no loss;
  plan amended to forbid it (commit before 4eac62b).
  MINOR (defer to final review):
   - test_import_logger_workers.py:392 asserts constant identity but nothing asserts
     the consumer behaviour: importer.py:871 summary.no_new_rows has no coverage.
   - test_import_logger_workers.py:11 module-scope `importer` import couples the
     worker/threading tests to GUI loadUiType at import time; a broken .ui now fails
     collection of all 11 worker tests.
Task 5: complete (commits 4eac62b..48e9ac3, review Approved)
  Extraction verified byte-equivalent: transaction boundary, closedb-on-every-path,
  SQL text, and the `if import_to_db and any(BAROMETRIC)` guard all unchanged.
  Implementer found existing coverage only hit the "already exists" branch (Swedish
  fixture pre-seeds 'pressure' as 'Lufttryck' via insert_datadomain_sv.sql:7) and
  added a real-SpatiaLite test for INSERT + idempotence. Justified.
  MINOR (defer to final review):
   - test_import_logger.py:3586 asserts against BARO_METEO_PARAMS[0] rather than a
     literal — partly self-referential.
   - importer.py:626 _ensure_baro_meteo_parameters never uses self; DB seeding still
     lives on the GUI class. Brief-mandated shape.
   - PostGIS %s placeholder path of the extracted method has no coverage (pre-existing).
Task 6: complete (commit 55ed824, review Approved)
  GUI dedup: one _build_utc_offset_section + _start_import_from_gui. Reviewer confirmed
  add_row (base_importer.py:55-57) is a bare addWidget, so assigning attributes after
  the call is inert. Layout/build order, strings, translation context all preserved.
Task 7: complete (commit 00339e2, review Approved) -- NOT BUILT BY THIS PROCESS.
  Found as UNCOMMITTED edits in this worktree, made by a concurrent agent working the
  same plan. Verified against the Task 7 brief, tests + ruff run, then committed with
  provenance recorded in the commit message. Reviewed under extra scrutiny: helper
  semantics, all three lookup orders, and the `section` shadowing claim all confirmed.
  MINOR (defer to final review):
   - importer.py:483 _start_import_from_gui untested (old lambdas equally untested).
   - importer.py:191 utcoffset_label/utcoffset_row have zero repo readers; kept
     deliberately for out-of-repo compatibility.
   - test_import_logger.py:3603 no -> None annotation, no spatialite/postgis marker.
CONCURRENCY INCIDENT: another agent edited this worktree. No commits of mine were
  contaminated (parsers.py appeared only in my 428dda5; both test edits were mine).
  ai_test unmoved at 55b51e9. Stash stack empty.
Task 8: complete (commits 00339e2..ecd81c2 + follow-up, review Approved)
  Both call sites verified byte-equivalent incl. the +1 asymmetry (series path) vs
  source_lines[...] lookup (frame path), and raw-value interpolation in messages.
  Reviewer independently confirmed .mask("") == .replace("", pd.NA) on string dtype
  across 5 NA-shaped inputs. Dtype asymmetry preserved as an intentional absence.
  Reviewer Minor #1 FIXED immediately (not deferred): the new test used a default
  RangeIndex so it could not fail a label-vs-positional regression; added a
  non-default-index case.
  MINOR (defer): parsers.py:466 inlined column local slightly obscures the
  positional-read / label-write split (pre-existing, brief-mandated form).
Task 9: complete (commits fe1a30c..a7c003b + follow-up, review Approved)
  Deletion gate VERIFIED BY ME (reviewer correctly could not see outside the repo):
  zero hits for get_all_obsids_in_w_levels_logger in ~/dev/midv_addons, and a sanity
  grep confirms the search does find other loggereditor refs there, so the negative
  is real. In-repo: zero remaining references.
  Reviewer confirmed the flattened loop guard equivalent for all 4 combinations, the
  suffix strip unchanged, and every edited test assertion is an unchanged context line.
  Reviewer Minor FIXED immediately: removed a comment my brief mandated that duplicated
  the one directly above it.
  NOTE (pre-existing, out of scope): loggereditor.py:3317 `elif selected_obsid is None:`
  is unreachable -- selected_obsid returns str on every path. Not a regression.
Task 10: complete (commits b829cf5..673d81a, review Approved)
  MY BRIEF HAD A LATENT BUG; the Step 5 gate caught it. _series_tab is assigned at
  loggereditor.py:455 INSIDE `if self._schema_variant == "series_join":`, so its
  hasattr guard is load-bearing -- literal Step 4 would have AttributeError'd on save
  for every source_col/no_source (older schema) user. Guard kept with a why-comment.
  tab_widget (:130, setupUi) and _ref_series (:2782, first stmt of unconditionally
  called _setup_ref_dock) guards correctly removed.
  SQL verified byte-identical incl. lowercase `'' as source`; series_join untouched.
  MINOR (defer to final review):
   - no_source SQL path has NO executing test; correctness rests on byte-identity.
   - has_created_at/has_comment now derived twice (brief-mandated cost of dropping
     the 4-tuple); both read the same attribute so cannot diverge.
   - _ref_series guard removal narrows one failure path: a save click during a
     half-constructed window now raises instead of no-opping. Intended.
Tasks 11+12: complete (commits 673d81a..d01dd5d + follow-up, both Approved)
  T11: _manage_wait_cursor in __init__; reviewer confirmed all 6 sites, no getattr left,
  and every read provably post-__init__.
  T12A: tuple->dict payload. T12B: first about_db row wins (deliberate behaviour change).
  T12C: SKIPPED by implementer with a sound cost argument -- my brief's rewrite would
  scan `rows` N+1 times vs N. Reviewer agreed skipping was right (and noted a
  max-over-tuples form that would be marginally better than both; not worth a commit).
  Reviewer Minors FIXED immediately: direct main-thread call still passed positionally
  (now one payload for both paths); added a test driving the real emit site.
  PLAN AMENDED: ruff must be run on touched files, not `.` (matplotlib_replacements.py
  has pre-existing format drift that a bare `ruff format .` would sweep into a commit).
  NOTE pre-existing, out of scope: unused typing.Any at import_data_to_db.py:27;
  N815 at test_midvatten_utils.py:326; UP031 at message_utils.py:175.

=== PHASE 1 CHECKPOINT: PASSED ===
Full suite -m "not postgis": 968 passed, 1 skipped, 290 deselected, 0 failed (15m12s).
Collected-ID diff vs pre-cleanup baseline 428dda5: 958 -> 969, ZERO removed, 11 added,
all 11 traceable to Tasks 2,4,5,7,8,9,11,12 + follow-ups. Nothing was silently dropped.
CAVEAT: 290 postgis tests deselected throughout Phase 1 (shared PG db contended by other
agents). PostGIS paths remain UNVERIFIED -- needs one clean `-m postgis` run at the end.
Tasks 13-15: complete (commits d633be1..4b59ca0, all three Approved)
  Pure moves, verbatim discipline verified independently: Task 13's moved loop renders
  as diff CONTEXT (byte-identical incl. indentation), and an AST stale-name scan of
  _parse returns empty. Task 14's _first_metadata_value swap verified equivalent
  incl. the empty-string-vs-missing-key edge. data_headers rebinding preserved;
  exception line arithmetic intact.
  MY "under 150" TARGET WAS WRONG: 329 - 112 = 217. Not a defect in the work.
  Reviewer named further candidates: identity resolution (-27), data-row slicing (-19),
  column selection (-15), delimiter boundary predicate (-13) => ~143. Doing these as 15b.
  MINOR (defer): parsers.py:859 `if header_row_idx >= 0:` is provably unreachable-false
  (data_start_row is always >= 1 and None is excluded earlier). Brief-mandated; delete
  in a separate task.
  COVERAGE DEBT (addressing in 15b): all 4 raises in _resolve_csv_header and the
  ValueError in _resolve_declared_channels are UNTESTED -- zero grep hits for their
  messages. A mangled line number or dropped raw_rows arg would not be caught.
Task 15b: complete (commits 4b59ca0..c25e9c8, Approved) -- follow-up I added after the
  13-15 review showed my 150 target needed 4 more extractions.
  _read_identity, _slice_data_rows, _build_column_selection,
  _delimiter_is_at_timestamp_boundary. _parse: 217 -> 147 (329 originally, -55%).
  All 4 named risks verified: is_csv stayed in _parse and is order-safe; the 1c sort
  still operates on the zipped pair; the 1d predicate keeps the True initialiser so
  the empty-source_lines case is unchanged; all 5 new tests reach their intended raise
  rather than tripping an earlier validation (reviewer traced each).
  Coverage debt CLOSED: 5 previously untested raises now covered, 4 asserting
  line_number AND raw_text. Implementer mutation-tested (+1 -> +0 fails all four),
  reviewer confirmed the assertions are real, not just match= on message text.
Task 16: complete (commits c25e9c8..ea9818c, Approved)
  5 pure extractions; start_import 255 -> 167 (-88). Reviewer verified mechanically:
  2 string-identical after dedent, 2 AST-body-identical, 1 side-by-side unparse.
  All 3 named risks clean: decorators/args/full return set byte-identical by AST
  (return / return False / return True x2 / finally progress.close()); no return
  swallowed into a helper; both cursor pairs bracket only their modal; both mutating
  methods write through the summary param with no local copy.
  Declared deviations all verified: ParsedLoggerFile import (needed, inert at runtime
  via __future__ annotations); _resolve_obsids statement reorder (neither statement
  reads what the other writes); inlined destination local (same subscript, same
  KeyError timing).
  MY "under 130" TARGET WAS WRONG AGAIN: base was 255 not 275; 5 extractions give 167.
  DECIDED NOT to chase it further -- goal is named stages, not an invented number.
  DEFERRED extraction candidates (reviewer-named, if ever wanted): parse-request
  builder (-14), series-spec construction (-13), preparation loop (-21, 6 params),
  latest-dates lookup (-8), CSV export (-10).
  MINOR (defer to final review):
   - _report_parse_failures has ZERO assertion coverage (grep finds no test touching
     parse_failures or its messages). Rests on the body being character-identical.
   - importer.py:636 parsed_files = [] unannotated while the method promises
     list[ParsedLoggerFile].
   - PRE-EXISTING: _parse_gui_date_bound is called before the try:, so a ValueError
     on a malformed date bound escapes with `progress` shown and never closed.
   - PRE-EXISTING: the CSV QFileDialog modal runs with the waiting cursor active,
     unlike the other two modals which are bracketed by stop/start.
Task 17: complete (commits b24e879..898dfb8 + follow-up, Approved)
  Counted cursor stack; both marker constants and all setattr/getattr sites gone.
  Full suite: 975 passed, 1 skipped, 290 deselected, 0 failed. (My 968 reference was
  stale -- predated Task 15b/16 test additions; implementer reconciled via collect-only:
  their change contributes exactly +2.)
  The two protected 55b51e9 tests provably untouched (test hunk has ZERO deletions)
  and pass for the right structural reason.
  Reviewer surveyed all ~40 call sites: NO site starts without a stop, and an
  independent grep confirms nothing outside common_utils.py touches Qt's cursor stack
  -- so _cursor_depth exactly mirrors the plugin's own contribution and the guard can
  only suppress a pop when the plugin holds no push. That is the whole safety argument.
  Hang hazard I introduced in the brief FIXED: while -> bounded for. Fixture -> autouse.
  MINOR (defer): main-thread-only invariant of _cursor_depth is documented only in the
  task report, not at the call site.

=== FINAL WHOLE-BRANCH REVIEW: Ready with fixes ===
36 commits, 18 files, +3671/-559. No defect found in shipped behaviour; all 25 new
helpers have call sites (no orphans); the 3 deliberate behaviour changes each verified
independently (sv_SE %p failure reproduced; LIMIT 1 provenance confirmed from the
round-trip baseline test; grep proved nothing outside common_utils touches Qt's cursor
stack, which is the whole safety argument for the counted stack).
Cross-task check found ONE thing only the whole revealed: Tasks 2 and 3 independently
traded two loud KeyErrors for two SILENT defaults pointing in opposite directions --
an unknown LoggerDataKind would skip the missing-head policy AND be shaped as water
level, i.e. written to the wrong destination table. FIXED (else: raise).
2 Important findings, both test-only, both FIXED:
  - module-scope dialog import in the worker/threading test module (dragged loadUiType
    into a pure-logic module) for an assertion that only restated import aliasing.
  - a tautological assertion I introduced in the Task 9 brief.
Also fixed: GUI-thread-only invariant now documented at the cursor call site.
24 ledger Minors triaged: 2 fix-before-merge (done), 1 already-moot, 21 acceptable debt.
Remaining acceptable debt for a follow-up commit on ai_test:
  parsers.py:919 dead `delimiter = None`; parsers.py:925 unreachable-false guard;
  rename _read_identity -> _resolve_identity for family consistency.
Verification: bandit 107->106 Medium / 0 High. Plan greps clean. _parse 147,
start_import 167. Collected-ID diff vs baseline: zero tests removed.

=== midv_addons COMPAT GATE ===
The compat SUITE ITSELF IS BROKEN, pre-existing and unrelated to this branch:
it hangs at pytest COLLECTION (not during a test), identically against the
UNMODIFIED main checkout -- verified by running --collect-only both ways, both
timed out. Root cause: test_midvatten_compat.py:16 does
`from nose.plugins.attrib import attr`; nose is dead on Python 3.12.
Substituted a direct contract check instead: extracted all 42 names the suite
imports from midv_addons.plugins.midvatten_imports, imported that module with
midvatten resolved to THIS WORKTREE (asserted, not assumed), and confirmed every
name resolves. MISSING: none. This covers the four cursor functions Task 17
changed (start_waiting_cursor, stop_waiting_cursor, waiting_cursor,
general_exception_handler), which are all in the contract.
NOTE for the user: the compat suite needs its nose import removed to be runnable
again. That is midv_addons work, out of scope here.

=== POSTGIS GATE: PASSED ===
python3 -m pytest test/ -m postgis: 289 passed, 1 skipped, 0 failed (13m33s), run on an
uncontended database after the other agent stopped. Combined with the 975 non-postgis
passes, every test in the suite has now run green against this branch.
ALL GATES GREEN. Branch ready for the merge decision.

=== /simplify PASS (post-merge, 4 parallel reviewers over origin/ai_test..HEAD) ===
Strong convergence: the wait-cursor mechanism was flagged independently by 3 of the
4 angles, _ensure_baro_meteo_parameters by 3.

APPLIED (6) -- full suite unchanged at 975 passed / 0 failed:
 - pipeline.py _copy_with_data: dropped reset_index(drop=True). Provable no-op
   (validate_logger_frame requires a zero-based RangeIndex and all 3 callers validate
   first) that cost a SECOND full deep copy: ~35ms + 20MB per call on a 500k-row file,
   paid even when no timezone conversion happens.
 - importer.py start_import: now @common_utils.waiting_cursor instead of one manual
   push hand-paired with four pops. Verified depth returns to 0 on normal return,
   early return, modal pause/resume and exception (5 push / 5 pop).
 - importer.py _ensure_baro_meteo_parameters: uses db_utils.add_insert_or_ignore_to_sql
   + use_or_create_connection instead of two hand-rolled schemes. Drops a SELECT
   round trip per parameter.
 - workers.py: skip the COUNT(*) when inserted_count == 0 -- it cannot change the
   outcome (the series is deleted either way). ~1s on a 50-file PostGIS import @20ms RTT.
 - parsers.py _delimiter_is_at_timestamp_boundary: compile the regex once (was 3.2x
   slower, ~0.5s per 500k-row .mon) and early-return instead of sentinel+break.
 - parsers.py _slice_data_rows: walk backwards by index; rows[::-1] copied every line
   pointer in the file to examine one or two entries.

SKIPPED -- MEASURED PERF OPPORTUNITY, deliberately not taken:
 - Six trailing .copy() calls on already-materialised frames (pipeline.py:395 written
   by this work, plus :261,:267,:273,:327,:330,:358). Measured ~120ms and ~100MB per
   500k-row water-level file. Safe under pandas 2.3.3 with CoW off (each preceding op
   deep-copies) AND under CoW, but the argument rests on frame shape/dtypes. Kept the
   defensive copy as cheap insurance. Revisit deliberately, with a benchmark.

SKIPPED -- BEHAVIOUR CHANGE, not cleanup:
 - _report_parse_failures double-logs: every parse failure is emitted twice per run,
   in two different wordings (_report_import_summary already reports the same list).
   Pre-existing; the extraction only gave it a name. Folding it in changes log verbosity.

SKIPPED -- COHERENT FOLLOW-UP DESIGN PASS (out of scope for a cleanup, worth doing):
 - Make start/stop_waiting_cursor no-op off the GUI thread (the check MessagebarAndLog
   already does), then delete the manage_wait_cursor flag threaded through
   import_data_to_db as a public param + attribute + 3 guards. Two sibling GUI-touching
   utilities currently sit at opposite altitudes.
 - Ship waiting_cursor_scope() and suspended_waiting_cursor() on top of the depth
   counter. 13 sites hand-roll stop->modal->start (9 in create_db.py), and that idiom
   is WRONG under nesting: at depth 2 the single stop leaves the cursor up during the
   modal -- the mechanism-level cause of the known QFileDialog cursor bug.
 - import_data_to_db.py:1296 import_exception_handler still uses a bare single pop
   instead of the new unwind_waiting_cursor(entry_depth). Two restoration policies.
 - _DESTINATION_TABLES (kind->table) lives in the GUI dialog while kind->frame-shape
   lives in pipeline.py. A meteo-shaped frame written to w_levels_logger is a
   data-corruption class of failure, and the two maps are edited in different layers.
   One kind spec in models.py would also give BARO_METEO_PARAMS a correct home.
 - LoggerDbImportResult.reason carries both a status code and a traceback; classify on
   an ImportOutcome enum instead so the GUI owns the wording.
 - importer.py has six parallel per-format tables/branches; a _format_sections registry
   would make adding a format one registration instead of six edits.
