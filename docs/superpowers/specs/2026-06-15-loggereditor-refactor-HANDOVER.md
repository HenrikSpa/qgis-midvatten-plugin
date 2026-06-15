# LoggerEditor refactor — handover to a fresh-context agent

Date: 2026-06-15. Branch state at handover: `ai_test` @ `5c389d4`.
This is the kickoff brief for the **item 8** refactor of `tools/loggereditor.py`
(the maintainability plan's deliberate last and highest-risk item). It is written
for an agent that has **none** of the prior session's context. Read this top to
bottom before touching code.

---

## Handover message (paste this to start the new agent)

> You are taking over the LoggerEditor refactor (item 8 of the Midvatten
> maintainability plan). Goal: turn a 3,802-line god class into a thin Qt
> coordinator over clean, unit-testable collaborators — using a **hybrid
> approach**: design a fresh domain model, build it from scratch with its own
> fast tests, then cut the existing GUI over to it incrementally, deleting old
> code as each piece is proven against the existing test suite.
>
> Start by reading, in order: (1) this handover, (2)
> `docs/superpowers/specs/2026-06-15-loggereditor-refactor-analysis.md` (the
> measured problem inventory + target architecture), (3) the memory files listed
> below, (4) `CLAUDE.md`. Then do **Slice 0 — the domain-modeling spike** (no
> production edits) and bring the target-model design back for sign-off BEFORE
> building anything. Do not start cutting code until the model design is approved.

---

## Mission

Decompose `LoggerEditor` into: `LoggerBuffer` (pure pandas data/diff/duplicate
model), `LoggerRepository` (all SQL), `LoggerPlot` (matplotlib), `HistoryStack`
(undo/redo), `SeriesController` (series tab + CRUD), and a slim `LoggerEditor`
QMainWindow coordinator. The analysis doc has the full target architecture and the
evidence behind it.

**Why hybrid (not a pure technical-layer split, not a from-scratch rewrite):** a
pure mechanical split risks "the same logic, distributed across 6 files." A
from-scratch rewrite throws away hard-won, recently-fixed bug knowledge and breaks
the test safety net all at once. The hybrid designs the core model fresh (the real
upside of starting over) while keeping the old code running and the existing tests
green as the oracle during cutover.

## Required reading (durable artifacts)

1. `docs/superpowers/specs/2026-06-15-loggereditor-refactor-analysis.md` — measured
   problems, target architecture, why-it's-hard, slice order. **The core brief.**
2. `docs/superpowers/plans/2026-06-10-maintainability-refactor-review.md` — item 8
   entry + standing constraints; the rest of the plan is DONE.
3. Memory files (`~/.claude/projects/-home-hsai1-dev-midv-midvatten/memory/`):
   - `project_loggereditor_dupe_datetime_work.md` — the duplicate-datetime feature.
   - `project_datetime_duplicate_rule.md` — the one-row-per-obsid-per-second rule.
   - `project_loggereditor_perf_invariants.md` — perf work that MUST be preserved
     (replot 9s→0.35s, vectorized selection, line-key caching). Do not regress it.
   - `feedback_test_reference_data_invariant.md` — operation+save must give
     identical DB state; fix impl, never the reference data.
   - `project_returnunicode_encoding_firewall.md` — never drop `returnunicode` on
     byte/QVariant/None paths; never reorder its cascade.
   - `feedback_integration_tests_user_flow.md`,
     `feedback_targeted_tests_between_slices.md`,
     `feedback_ai_test_is_the_living_branch.md`.
4. `CLAUDE.md` — repo rules (SQL safety via `ident()`/param binding, no schema
   changes, test conventions, ruff).

## Hard constraints (non-negotiable)

- **Byte-exact reference-data invariants.** The duplicate/diff/save logic is pinned
  by `test_loggereditor_dupes.py` and others asserting exact DB state. Operation +
  save must produce identical DB rows to today. Before MOVING any of this logic, add
  DataFrame-level characterization tests proving the new model is byte-identical;
  keep the existing full-GUI tests as the backstop.
- **No schema changes** (table/column/view names) unless explicitly asked.
- **Encoding firewall** — keep `returnunicode` on all byte/QVariant/None paths.
- **Preserve the recent perf work** (see perf-invariants memory).
- **White-box test coupling is the central difficulty.** 26 test call sites and the
  sibling module `tools/loggereditor_resolve_dupes.py` call `editor._private(...)`
  directly (`_remove_redundant_duplicates`, `_remove_cross_source_overlaps`,
  `_full_buffer_range`, `_classify_duplicates`, `_duplicate_instants`,
  `_resolve_conflict_keep`, `_focus_plot_on_instants`, `_history_push`). Use
  **strangler-with-delegation**: move logic into the collaborator, keep thin
  `editor._method(...)` forwarders so the dialog and tests keep passing; migrate
  callers and delete forwarders in a LATER slice.

**Good news — one risk dimension is absent:** `midv_addons` does NOT import or use
`LoggerEditor` (verified 2026-06-15). The midv_addons API contract — which
constrained earlier slices — does **not** apply to this file. The class is
constructed only by `midvatten_plugin._dispatch` and by tests.

## The class also IS the "calibrate logger" tool

`LoggerEditor` doubles as the calibration tool; `test_wlevels_calc_calibr.py`
constructs it 9× and exercises `set_logger_pos`, `add_to_level_masl`,
`calc_best_fit`, `match_ts_values`. Treat calibration as a first-class concern
(candidate collaborator), not an afterthought.

## Approach & slice order (hybrid)

- **Slice 0 — domain-modeling spike (DO THIS FIRST, no production edits).** Read the
  dup/save tests as the behavioral spec. Define the clean model: an editable
  `LoggerSeries` with an explicit edit/`ChangeSet` representation, a
  `DuplicateConflict` concept, and `Calibration`. Question whether "mutate a pandas
  buffer and diff on save" is the right core or an accident driving the complexity
  (the four parallel obsid fields — `obsid`/`_buf_obsid`/`_meas_obsid`/
  `selected_obsid` — and the `meas_ts`/`_meas_ts` memo are symptoms). Produce a
  design doc and **get user sign-off before building.**
- **Slice 1 — `LoggerBuffer`** (strangler + delegation): build the pure-data model
  fresh with DataFrame-level unit tests; keep `editor._method` forwarders. Retires
  the riskiest logic first behind isolated tests.
- **Slice 2 — `LoggerRepository`**: pull all SQL out; buffer becomes DB-free.
- **Slice 3 — `HistoryStack`** (small, self-contained).
- **Slice 4 — `LoggerPlot`**: isolate matplotlib (largest mechanical move; mind the
  perf invariants and the `show()` connect-guard).
- **Slice 5 — `SeriesController`** + the calibration concern.
- **Slice 6 — collapse forwarders**: migrate `loggereditor_resolve_dupes.py` and the
  26 test sites to the collaborator interfaces; delete the `editor._method` shims.
- **Slice 7 — final**: shrink `show()`/`__init__`, fold the four obsid fields into
  one, retire the `meas_ts`/`_meas_ts` pair, narrow remaining broad excepts.

Each slice: independently mergeable, suite green at the boundary.

## Repo workflow (per the maintainability slices to date)

- **One git worktree per slice**, branched from `ai_test` (use the
  `superpowers:using-git-worktrees` skill / `EnterWorktree`). Worktrees live under
  `.claude/worktrees/`.
- **After any code change, run the `simplify` skill** on the slice diff (CLAUDE.md
  requirement).
- **Tests:** `python3 -m pytest` (NOT `python`). Targeted `test_loggereditor*` +
  `test_import_logger` + `test_wlevels_calc_calibr` between edits; **full suite
  (`python3 -m pytest test/`, ~34 min) at each slice boundary** — run it in the
  background. Last known green: **1137 passed, 1 skipped**.
- **Imports in worktrees** resolve via repo-local `_pkgroot/` + root `conftest.py`.
  **Never repoint** `~/.local/share/QGIS/.../plugins/midvatten` — it breaks other
  agents.
- **Merge:** fast-forward only into local `ai_test`, after verifying ai_test hasn't
  moved under you / working tree clean / ff possible; remove only your own worktree +
  branch; never prune. **`ai_test` is the living branch — never merge to `master`.**
  If `ai_test` advanced while you worked, `git rebase ai_test` your slice first.
- **Mock `MessagebarAndLog`** via `@mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")`
  (param `mock_messagebar`); print `mock_messagebar.mock_calls` before asserts.

## Coordination (important — this is the most actively developed file in the repo)

Before starting each slice: `git worktree list` and `git branch --list "*logger*"`
to check for in-flight loggereditor work, and confirm the latest loggereditor commits
are on `ai_test`. The `loggereditor-perf` / `perf-loggereditor-selection` work landed
2026-06-12 (all merged). If another agent is mid-flight on this file, coordinate or
wait — a parallel god-class decomposition will conflict badly.

## Current state snapshot (2026-06-15)

- `ai_test` @ `5c389d4`. `tools/loggereditor.py` = 3,802 lines, 137 methods, 95
  instance attributes.
- Maintainability plan: items 1–4, 7, 9, 12, 13, 15, 17 DONE; 6 PARTIAL (save_to_db
  stages done); 5/10/11/14 deferred-or-folded; 16 keep. **Item 8 is all that
  remains.**
- Test files for this feature: `test_loggereditor_{dupes,plot_interaction,
  plot_limits,refseries,resolve_ui,separation,series}.py` + `test_wlevels_calc_calibr.py`;
  sibling `tools/loggereditor_resolve_dupes.py`.

## Your first action

Read the required-reading list, then execute **Slice 0** (domain spike) and return a
target-model design for sign-off. Do not write production code until that design is
approved.
