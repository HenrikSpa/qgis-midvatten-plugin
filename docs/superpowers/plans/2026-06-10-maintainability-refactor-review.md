# Maintainability refactor review — evaluated plan

Date: 2026-06-10. Scope: production code (~170 files, ~80k lines), reviewed by subsystem
with all headline claims verified against current source (AST measurements + greps).

Status legend: **Do** (clear win), **Do with guardrails** (win, but specific risks must be
managed), **Redesign case-by-case** (not mechanical), **Don't** (rejected after evaluation).

Standing constraints for every item:

- Work happens in a dedicated git worktree; targeted tests between edits, full suite at
  slice boundaries.
- **Encoding safety**: `returnunicode()` (`tools/utils/string_utils.py:21`) is the
  encoding firewall that stops wrongly-decoded characters from entering the database
  (bytes → utf-8 → cp1252 → iso-8859-1 → ascii cascade) and normalizes None/QGIS NULL
  to `""`. No fix may remove a `returnunicode` call on a path that can carry bytes,
  QVariant, or non-str values, and no fix may change the charset cascade order.
  Any change near input decoding needs a test with å/ä/ö in both utf-8 and cp1252 input.
- Test reference data never changes in refactors; operation+save must give identical DB
  state to the old code.
- **External consumer — midv_addons** (`~/dev/midv_addons`): heavily dependent on
  midvatten's import surface. Its public contract (verified 2026-06-10):
  - Aggregator modules `midvatten.tools.utils.{common_utils, midvatten_utils,
    db_utils, date_utils, gui_utils}` *including re-exported names* such as
    `common_utils.MessagebarAndLog/Askuser/returnunicode/rstrip/UsageError`,
    `db_utils.sql_load_fr_db/sql_alter_db/DbConnectionManager/tables_columns/
    rowid_string/is_distinct_from/is_not_distinct_from`, `gui_utils.set_combobox`.
  - `midvatten.definitions.midvatten_defs`, `midvatten.tools.midvsettings.MidvSettings`,
    `midvatten.midvsettingsdialog.PostgisSettings`,
    `midvatten.tools.import_general_csv_gui.GeneralCsvImportGui` (constructed as
    `GeneralCsvImportGui(iface, ms=..., dbconnection=...)`, uses `.show()` and the
    `destroyed` signal), `midvatten.tools.utils.layer_specs.LayerSpec`,
    `midvatten.tools.utils.layer_build.build_layer`,
    and the test helper module `midvatten.test.utils_for_tests`.
  - Rule: never delete or rename anything on this surface; re-exports used by
    midv_addons stay even when in-repo callers move to source modules. After any
    slice touching these modules, run midv_addons'
    `midv_addons/test/test_midvatten_compat.py` (its purpose-built guard for exactly
    this) before merging.

---

## 1. Fix `calc_mean_diff()` NaN filter — **DONE 2026-06-11** (merged to ai_test)

`tools/utils/common_utils.py:167`: `if not math.isnan(m) or math.isnan(val)` lets a NaN
`val` through, which makes the whole mean NaN. Intent is `not (isnan(m) or isnan(val))`.

- **Gain:** Removes a real latent bug; means computed over logger data with gaps stop
  silently becoming NaN.
- **Lose/risk:** Behavior change — any caller that *relied* on NaN propagating (e.g. to
  detect "data has gaps") would change. Must check the call sites and add a regression
  test before fixing.
- **Effort:** ~1 line + caller audit + test.

## 2. Delete commented-out dead code — **DONE 2026-06-11** (merged to ai_test)

E.g. `tools/import_fieldlogger.py:1675-1685` ("Only for dev" block still containing
Python 2 syntax), `tools/drillreport.py:76-97` old rendering paths.

- **Gain:** Less noise when reading; no risk of someone reviving Python 2 era code.
- **Lose/risk:** Loses in-place hints about old behavior — mitigated fully by git
  history. Near-zero risk since nothing executes.
- **Effort:** Trivial.

## 3. Deduplicate Piper combobox loading — **DONE 2026-06-11** (merged to ai_test; final form delegates to gui_utils.set_combobox, also adopted in ts/wqual/xy loaders)

`midvsettingsdialog.py:312-338`: the same findText/setCurrentIndex block repeated for
cl/hco3/so4/na/k/ca/mg (~170 lines). Replace with a loop over
`(setting_key, combobox)` pairs.

- **Gain:** ~150 lines removed; adding a parameter becomes a one-line change; the 8
  copies can no longer drift apart.
- **Lose/risk:** A bug in the shared loop now affects all 8 parameters at once instead
  of one. Slightly less greppable per-parameter. Low risk overall — behavior is
  mechanical.
- **Effort:** Small; covered by opening the settings dialog in existing tests.

## 4. Add `@functools.wraps` to decorators — **DONE 2026-06-11** (merged to ai_test; all 5 wrapper decorators covered incl. import_exception_handler and waiting_cursor)

`general_exception_handler` (`common_utils.py:492`) and `if_connection_ok`
(`db_utils/execution.py:137`) currently destroy `__name__`/`__doc__`.

- **Gain:** Tracebacks and logs show the real function name; `help()` works; mock
  patching by name is reliable.
- **Lose/risk:** Essentially none; `functools.wraps` is the stdlib idiom.
- **Effort:** Trivial.

## 5. Messaging by intent — **Redesign case-by-case** (revised)

Original idea ("migrate all 33 QMessageBox to MessagebarAndLog") is **rejected**:
verified usage shows most modal dialogs are decision points (Yes/No/Cancel,
Accept/Reject/Destructive roles in `loggereditor.py`, `obsid_assignment_dialog.py`,
`dialog_utils.py`, `export_spatialite.py`) where blocking is the point — the message
bar is easy to miss and a missed decision is worse than an interruption.

Classify each message site by intent instead:

| Intent | Right tool | Action |
|---|---|---|
| Decision required (confirm destructive, choose option) | Modal dialog | Keep; consolidate through `dialog_utils` helpers |
| Outcome report (success, non-blocking failure) | `MessagebarAndLog` | Migrate the few pure `QMessageBox.information()` popups |
| Instruction ("you must first do X") | Neither — UX smell | Redesign: disable action until preconditions hold (tooltip says why), inline validation, or put the remedy on a dialog button |

- **Gain:** Uniform decision dialogs; all outcomes searchable in the log; instructional
  popups replaced by UI that makes the next step self-evident (the
  `midvatten_plugin._dispatch` precondition pattern is the in-repo model).
- **Lose/risk:** Case-by-case work, not a sweep — each instructional popup needs a small
  UX decision. Moving a message to the bar risks users missing it, so anything a user
  must *act on* stays modal. Misclassification is the main risk; review each site with
  the table above.
- **Effort:** Small per site; spread over time, piggybacked on other work in each file.

## 6. Narrow megablock try/excepts — **PARTIAL 2026-06-12** (headline offender done: loggereditor.save_to_db split into compute/connect/write stages with truthful per-stage messages + tracebacks; closedb now guaranteed for statement-prep failures; the pre-try duplicate-detection section — which propagated uncaught — brought under the compute stage; failure-stage regression tests added. Remaining: other except-Exception megablocks, per-file as touched)

188 `except Exception` blocks; worst verified offenders are in
`tools/loggereditor.py:1279` (176-line try with a nested 126-line one inside
`save_to_db()`). Failures in duplicate detection, diffing, or DB writes all surface as
one undifferentiated error.

- **Gain:** Debuggability — errors point at the failing concern; partial-failure states
  become distinguishable; narrower blocks force thinking about what each step can throw.
- **Lose/risk:** The blanket catches currently guarantee the GUI never crashes mid-save;
  narrowing them can let an unanticipated exception escape and abort a save differently
  than before. Mitigate: keep `@general_exception_handler` as the outer safety net and
  only narrow the *inner* blocks; never change what gets committed vs rolled back.
- **Effort:** Medium, file by file; start with `save_to_db()` since it guards DB writes.

## 7. Signal/slot lifecycle cleanup — **DONE 2026-06-12** (full audit of ~280 connect() sites against the three leak shapes found exactly one issue: GeneralCsvImportGui rebuilt+reconnected its GUI on every show() — latent via the plugin dispatcher (fresh instance per open) but unguarded for direct external callers; fixed with a build-once flag + idempotence test. LoggerEditor show() connects are hasattr-guarded, fieldlogger dynamic widgets recreated per open, no self-capturing lambdas on iface/canvas signals)

263 `.connect()` vs 4 `.disconnect()` calls; lambda connections recreated per dialog
open (`midvatten_plugin.py:756`, dynamic widgets in `import_fieldlogger.py` /
`export_fieldlogger.py`).

- **Gain:** Stops handler accumulation/memory growth in long QGIS sessions; removes a
  class of "action fires twice" bugs after reopening dialogs.
- **Lose/risk:** Qt already auto-disconnects when the receiver QObject is destroyed —
  so many of the 263 are fine, and adding disconnect logic everywhere would be noise.
  Real risk is over-engineering. Scope to the verified leak shapes only: persistent
  windows that are reused (not destroyed), lambdas capturing `self`, and connect calls
  inside loops/show(). Disconnecting the wrong signal can silently kill functionality —
  every touched dialog needs its open→use→close→reopen flow exercised.
- **Effort:** Medium audit, small fixes.

## 8. LoggerEditor decomposition — **Do with guardrails** (largest item)

`tools/loggereditor.py`: 3,677 lines, ~135 methods, one class mixing data buffer,
matplotlib rendering, Qt UI state, and DB transactions. Verified god methods: `show()`
264 lines, `save_to_db()` 251, `_draw_series()` 174, `load_obsid_and_init()` 169.

- **Gain:** The most actively developed file in the repo (three plan docs in flight)
  becomes navigable; buffer/diff logic becomes unit-testable without Qt; merge
  conflicts between parallel work shrink.
- **Lose/risk:** Highest-risk refactor in the plan. The class state is shared across
  all concerns (135 methods touching the same attributes), so extraction can subtly
  change behavior — especially around save/duplicate handling, which has strict
  reference-data invariants. Verified 2026-06-10: no loggereditor plans are in flight
  (series-editing, move-fix, and the duplicate-resolution UI are all merged to
  ai_test; the leftover `.worktrees/` entries are stale). Mitigate: one extracted
  collaborator per slice (start with the pure-data buffer/diff model); full
  `test_loggereditor*` + `test_import_logger` between slices; check for newly started
  loggereditor work before beginning.
- **Effort:** Large, multi-slice.

## 9. Importer charset-detection consolidation — **DONE (scoped) 2026-06-11** (merged to ai_test; helper + fieldlogger + å/ä/ö tests; interlab4 intentionally untouched — its loop reads an embedded #tecken= declaration, different semantics)

Hand-rolled encoding loops: `import_fieldlogger.py:209-226` tries utf-8/cp1252;
`import_interlab4.py:639-661` tries utf-16/utf-8/iso-8859-1; each with its own
ask-the-user fallback.

- **Gain:** One tested `read_file_with_detected_charset(filename, encodings, ...)`
  helper; consistent ask-the-user fallback; new importers get correct decoding for free.
- **Lose/risk:** **This is exactly where bad-encoding data could re-enter the DB.** The
  per-importer encoding lists differ *for a reason* (interlab4 files are often utf-16;
  fieldlogger files are utf-8/cp1252) — the shared helper must take the encoding list
  as a parameter per importer, not unify it. A wrong-order cascade can "successfully"
  decode cp1252 bytes as iso-8859-1 and write mojibake to the database. Mitigate:
  helper preserves each importer's exact current list and order; regression tests
  import reference files containing å/ä/ö in utf-8, cp1252, and utf-16 and assert the
  exact DB strings; `returnunicode` calls on these paths stay.
- **Effort:** Small-medium, mostly tests.

## 10. Date parsing consolidation — **Do, inside the datetime-canonicalization work**

~39 scattered strptime/strftime sites plus custom `fix_date()` in
`import_logger/parsers.py:35-59` (HOBO AM/PM + timezone handling).

- **Gain:** One place to fix format bugs; aligns with the in-flight
  datetime-canonicalization backend-parity plan instead of competing with it.
- **Lose/risk:** Date parsing changes can silently shift stored timestamps —
  reference-data invariant applies hard here (one row per obsid per normalized second).
  The HOBO-specific quirks in `fix_date()` are domain knowledge, not cruft; they move,
  they don't get "simplified". Doing this separately from the canonicalization plan
  would mean touching the same code twice.
- **Effort:** Medium; fold into existing plan, don't run as its own slice.

## 11. `prepare_*_data()` boilerplate in import_fieldlogger — **DEFERRED 2026-06-11** (read in full: w_flow is dominated by an interactive instrument-id dialog; shared boilerplate is ~4 lines/method — a spec-driven helper would be forced abstraction)

`import_fieldlogger.py:345-470`: four near-identical 50–120-line methods building
header-row + observation-rows lists (w_levels, comments, w_flow, w_qual_field).

- **Gain:** One column-spec-driven helper; adding a parameter type stops requiring a
  copy-paste of 100 lines; divergence between the four copies becomes impossible.
- **Lose/risk:** The four methods have small intentional differences (column sets,
  value formatting) that must survive as explicit spec entries, not get averaged away.
  Existing import tests with reference data cover this well.
- **Effort:** Small-medium.

## 12. `GeneralCsvImportGui` inherits `BaseImporter` — **Do**

`import_general_csv_gui.py:60` inherits `QMainWindow` directly and reimplements what
`BaseImporter` provides; the other importers use the base class.

- **Gain:** One importer lifecycle (window setup, settings, `add_row`); base-class
  fixes reach all importers.
- **Lose/risk:** Behavior differences between its hand-rolled init and the base class
  may be load-bearing (window flags, settings keys). Diff the two inits first; keep
  settings keys identical so users don't lose saved import configs. **midv_addons
  constructs this class directly** (`GeneralCsvImportGui(iface, ms=..., dbconnection=...)`,
  bergy_dialog.py) and relies on `.show()` and the `destroyed` signal — the constructor
  signature and QWidget lifetime semantics must not change.
- **Effort:** Small.

## 13. Extract GUI classes from midvatten_utils — **DONE 2026-06-15** (move phase 2026-06-12: pure move to tools/utils/plot_templates.py, midvatten_utils 1479→585 lines, select_files module-qualified so 96 mock targets keep intercepting, no re-export needed — midv_addons verified not using the classes; side win: importing midvatten_utils no longer loads matplotlib.pyplot (~0.3s) on non-plot paths. Slice 2 2026-06-15: the planned shared base was EVALUATED AND DECLINED — the two classes' method NAMES overlap but BODIES differ fundamentally (serialized-dict .txt files in an in-memory registry vs .mplstyle files in matplotlib's global stylelib via plt.style.context + rcParams sanitization); a base would be empty-ABC ceremony or a parameterization larger than the two classes (same trap as the HtmlTableBuilder decline in item 17). Genuine cleanup done instead: removed the dead plot_object first parameter from both __init__s + both prod call sites + 6 test call sites + a now-dead test mock, and a duplicate self.templates={} assignment. NOTE from contract check: midv_addons references midvatten_utils.{unicode_, rstrip, create_dict_from_db} which do NOT exist — pre-existing breakage on midv_addons' side, not from this slice)

`midvatten_utils.py:601-1476`: `PlotTemplates` and `MatplotlibStyles` are ~875 lines of
widget code in a utils module, with replicated import/parse/save/load methods.

- **Gain:** utils module drops ~60% of its bulk; the two classes share a base and stop
  drifting; "utils" regains a meaning.
- **Lose/risk:** Import-path churn (callers + tests must update); the shared-base
  unification could change template parsing edge cases — extract first (move, no logic
  change), unify second (separate slice). No re-export was needed (verified: midv_addons
  does NOT use PlotTemplates/MatplotlibStyles); the move-phase slice shipped without one,
  and midvatten_utils still imports cleanly.
- **Effort:** Medium, mechanical.

## 14. Split `midvatten_defs.py` — **Do, lazily**

1,552 lines mixing settings defaults, color palettes, schema constants, and a ~400-line
`export_fieldlogger_defaults()` config generator.

- **Gain:** Each concern findable; fewer merge conflicts in a file everything imports.
- **Lose/risk:** Everything imports it — a hard split is a repo-wide import churn with
  zero behavior gain, and the circular-import situation with midvatten_utils
  (`midvatten_defs.py:40` imports locale helpers back) needs untangling first.
  midv_addons imports `midvatten.definitions.midvatten_defs` directly, so the module
  path and its public names must keep working regardless of any split. Cheaper
  variant: split *new* concerns out opportunistically and move the locale helpers to
  their own module to break the cycle; don't do a big-bang split.
- **Effort:** Big-bang: large. Lazy variant: small per step. Choose lazy.

## 15. Re-export shims: sweep internal callers, keep the shims — **DONE 2026-06-12** (all 6 groups merged to ai_test; message_utils slice: 263 prod sites in 34 tools files + ~130 utils-layer bare calls qualified as message_utils.X + 472 test patch targets canonicalized to midvatten.tools.utils.message_utils.<name>; see docs/superpowers/plans/2026-06-12-message-utils-sweep.md)

~37 in-repo production callers still use re-exported names (`common_utils.pop_up_info`,
`common_utils.find_layer`, …); CLAUDE.md already mandates importing from source modules.
Original idea was to retire the shims afterwards — **rejected**: the re-exports are the
public API for midv_addons (see standing constraint), which imports
`common_utils.MessagebarAndLog`, `returnunicode`, `UsageError`, etc. through them.

- **Gain:** In-repo imports tell the truth about dependencies; matches the documented
  convention; the shims become a thin, *documented* external API layer instead of an
  accident.
- **Lose/risk:** Pure churn with no behavior change — easy to review but touches many
  files at once (noisy diff). Mock patch targets in tests reference the old paths;
  those tests must be updated in the same slice or they silently stop intercepting.
  The shims themselves must not shrink — add a comment in each aggregator module
  marking the re-exports as the midv_addons contract so nobody "cleans them up".
- **Effort:** Small-medium, one mechanical sweep + test patch-target fixes + run
  midv_addons compat test.

## 16. `returnunicode` — **Keep; do not retire** (revised)

123 production call sites. Previously classed as "Python 2 legacy"; that was wrong.
It is the active encoding firewall: created to stop wrongly-decoded characters from
entering the database, and it also normalizes QGIS NULL/None to `""` (see memory:
QGIS NULL regression already broke tests once when "dead" branches were removed).

- **Gain (of keeping):** Continued protection at every input boundary; no risk of
  re-introducing mojibake into user databases that are expensive to clean.
- **Lose (of keeping):** Some redundant calls on provably-str values (minor overhead,
  minor noise); mixed str/container return type stays slightly awkward.
- **Verdict:** The asymmetry is decisive — redundant calls cost almost nothing; a
  missing call can corrupt user data. Only allowed changes: add type hints/docstring
  documenting its firewall role, and stop *adding* calls where input is statically
  `str`. No bulk removal, no cascade reordering, no "simplification" of the
  QGIS-NULL/bytes branches.

## 17. HTML report generation — **DONE (scoped) 2026-06-12** (drillreport: sv/en pairs collapsed to one method per quadrant via _locale_spec(), byte-identical incl. preserved drift quirks, verified by byte-exact golden tests for BOTH locales — the en one translate-patched for host independence; also fixed: English report crashed on stratigraphy rows. 803→454 lines. wqualreport vs compact: evaluated 2026-06-12 — shared plumbing already lives in wqualreport_core; remaining overlap is conceptual only (per-obsid SQL pivot vs pandas pivot_table, different HTML); unifying = rewriting the legacy report on the compact engine = output change = product decision, NOT a refactor — dropped from this plan; dead isnan/sql_list helpers removed. REMAINING follow-up outside this plan: HTML escaping (changes output), legacy-wqualreport deprecation decision)

`drillreport.py` builds HTML via `rpt +=` concatenation with no escaping; four
English/Swedish method pairs (~400 lines, ~80% identical); `wqualreport.py` and
`wqualreport_compact.py` overlap despite `wqualreport_core.py` existing.

- **Gain:** `HtmlTableBuilder` + locale-strings dict collapse ~½ of the report code;
  escaping happens in one place (obsid/comment fields with `<`/`&` currently break
  report HTML); Swedish/English stop drifting apart.
- **Lose/risk:** Report output is user-visible — byte-identical output is the safe
  target for the first slice (pure restructure), with escaping fixes as an explicit
  follow-up since escaping *changes output* for affected strings. Avoid adding a
  template-engine dependency (Jinja2) — plain helpers suffice and QGIS plugin deps are
  costly.
- **Effort:** Medium, well-contained.

---

## Rejected after evaluation

- **Migrate all QMessageBox → MessagebarAndLog** (see item 5): most are decision
  dialogs where modal blocking is correct.
- **Remove/retire returnunicode** (see item 16): it is the encoding firewall, not
  legacy.
- **"Dead" plugin methods at `midvatten_plugin.py:767+`**: not dead — wired via
  ActionSpec callbacks. No action.
- **Big-bang midvatten_defs split** (see item 14): import churn without behavior gain;
  lazy split instead.

## Sequencing

1. Item 1 (bug fix) + items 2–4 (quick wins) — one small slice.
2. Item 9 (charset helper, with encoding regression tests) and item 11 — importer slice.
3. Item 15 (re-export sweep) — mechanical slice.
4. Items 6–7 (exceptions, signals) — per-file, piggybacked or standalone.
5. Item 17 (reports), item 13 (GUI extraction) — contained slices.
6. Item 10 folds into the datetime-canonicalization plan.
7. Item 8 (LoggerEditor split) — last, because it is the highest-risk item, not
   because anything blocks it (all loggereditor plans verified merged 2026-06-10).
8. Items 5 and 14 — opportunistic, case-by-case alongside other work.
