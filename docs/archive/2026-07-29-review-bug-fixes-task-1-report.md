> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-07-29 · modified: 2026-07-29 · archived: 2026-07-31

# Task 1 report — cursor leaks in calc_best_fit, delete_selected_range, _trend_release

## Summary

Wrapped the cursor-protected blocks of `calc_best_fit`, `delete_selected_range`, and
`_trend_release` in `tools/loggereditor.py` in `try/finally` so `common_utils.stop_waiting_cursor()`
always runs, even when the body raises. Followed the brief's TDD steps 1-7 verbatim.

Work was done in an isolated worktree (native `EnterWorktree` was unavailable to this
subagent, so fell back to the git-worktree skill's manual path):
`/home/hsai1/dev/midv/midvatten/.worktrees/task1-cursor-leaks` on branch `task1-cursor-leaks`
(branched from local HEAD of `ai_test`, per `worktree.baseRef: head` in
`.claude/settings.local.json`).

## What changed

**`tools/loggereditor.py`** (paths below are worktree-relative; same repo, branch `task1-cursor-leaks`):

- `calc_best_fit` (was lines 3141-3178, now 3140-3179 after reformatting): wrapped the body
  after `common_utils.start_waiting_cursor()` in `try:` / `finally: common_utils.stop_waiting_cursor()`.
  No behavior change — same statements, one indentation level deeper.
- `delete_selected_range` (was lines 3360-3371, now 3360-3373): wrapped the `really_delete`
  branch's body (mask build, null-set or drop, history push) in `try/finally` around the
  existing `start_waiting_cursor()`/`stop_waiting_cursor()` pair. `self.update_plot()` stays
  outside the try/finally, unchanged.
- `_trend_release` (was lines 3673-3700, now 3676-3705): wrapped the trend-correction body
  (apply correction, update buffer, log message, history push) in `try/finally`. `self.update_plot()`
  stays outside, unchanged.

All three edits matched the exact code given in the brief's Steps 3-5.

**`test/test_wlevels_calc_calibr.py`**: added `test_calc_best_fit_restores_cursor_on_exception`
after `test_obsid_label_round_trips` (end of file), exactly as specified in the brief's Step 1.
It forces `get_search_radius()` to raise, and asserts `start_waiting_cursor`/`stop_waiting_cursor`
are each called exactly once despite the exception.

## TDD sequence followed

1. Added the test — confirmed it **fails** pre-fix:
   `AssertionError: Expected 'stop_waiting_cursor' to have been called once. Called 0 times.`
2. Applied the three try/finally wraps.
3. Re-ran the new test — **passed**.
4. Ran the full target suite — **passed** (132 tests, up from the pre-existing 131).

## Test results

Baseline (before any change), `test/test_wlevels_calc_calibr.py test/test_midvatten_utils.py`:
```
131 passed, 3 warnings in 113.76s (0:01:53)
```

New test alone, before the fix (`-xvs`):
```
FAILED test/test_wlevels_calc_calibr.py::test_calc_best_fit_restores_cursor_on_exception
AssertionError: Expected 'stop_waiting_cursor' to have been called once. Called 0 times.
1 failed, 1 warning in 2.24s
```

New test alone, after the fix:
```
test/test_wlevels_calc_calibr.py::test_calc_best_fit_restores_cursor_on_exception PASSED
1 passed, 1 warning in 1.83s
```

Full target suite, after the fix (final verification, post ruff):
```
132 passed, 3 warnings in 129.82s (0:02:09)
```

`ruff check --fix tools/loggereditor.py test/test_wlevels_calc_calibr.py` → `All checks passed!`
`ruff format tools/loggereditor.py test/test_wlevels_calc_calibr.py` → `2 files left unchanged`

## Simplify-skill review (mandatory per CLAUDE.md workflow)

Ran the `simplify` skill with 4 parallel review agents (reuse, simplification, efficiency,
altitude) over `git diff HEAD`. Findings and disposition:

- **Efficiency** — no issues. Pure structural try/finally wrap; no new computation, no
  reordering, no new long-lived objects.
- **Reuse** — `common_utils.py:422-431` already defines a `@waiting_cursor` decorator doing
  exactly this try/finally shape, already used on sibling methods in the same class
  (`load_obsid_and_init` at `loggereditor.py:1152`, `update_plot` at `:2419`) and ~8 other
  tool modules. It's a near drop-in for `calc_best_fit`, but does **not** cleanly fit
  `delete_selected_range` or `_trend_release`, since their cursor starts partway through the
  method (after guard clauses / a modal confirm dialog), and no block-scoped context-manager
  equivalent exists yet (only the inverse `suspended_waiting_cursor()`).
- **Simplification** — a guard-clause rewrite of `calc_best_fit` (early `return` instead of
  nested `if/else`) would cancel out the extra indentation the try/finally adds, since
  `return` inside `try` still runs `finally`. No dead code, unused imports, or accidental
  duplication found.
- **Altitude** — fix is at the right depth for its stated scope: two other pre-existing
  call sites in this same file already use the identical bare try/finally shape
  (`loggereditor.py:276-280`, `:1369-1652`), so this diff extends an existing local idiom
  rather than inventing one. Flagged two genuinely unprotected leaks **outside this task's
  files** (`tools/w_flow_calc_aveflow.py:72-128`, `tools/wqualreport.py:79-115`) as candidates
  for a future task, and explicitly cautioned that generalizing to a shared context manager
  here would be scope creep.

**Decision: no code changes applied from the simplify pass.** Both the decorator-reuse and
guard-clause suggestions apply cleanly to `calc_best_fit` alone but not to the other two
methods, and applying either only to `calc_best_fit` would break the symmetry that is this
task's own premise ("the fix for each is the same"). Both also go beyond the brief's explicit
contract ("Produces: No new interfaces — only wraps existing calls in try/finally") and its
literal verbatim code blocks. Recorded as follow-up opportunities, not applied:
1. Consider decorating `calc_best_fit` with `@common_utils.waiting_cursor` (would need to
   move `obsid = self.load_obsid_and_init()` handling or verify cursor-depth stacking is
   still correct with it wrapping the whole method).
2. Consider a block-scoped `waiting_cursor()` context manager (a companion to the existing
   inverse `suspended_waiting_cursor()`) to give `delete_selected_range` and `_trend_release`
   a reuse target too, then revisit all three uniformly.
3. Two unrelated unprotected `start_waiting_cursor`/`stop_waiting_cursor` sites exist in
   `tools/w_flow_calc_aveflow.py:72-128` and `tools/wqualreport.py:79-115` — same bug class,
   out of scope for this task.

## Concerns

- None blocking. The two out-of-scope unprotected cursor-leak sites found by the altitude
  reviewer (`w_flow_calc_aveflow.py`, `wqualreport.py`) are worth a follow-up task/plan entry
  but are not part of this task's brief.
- The worktree `.worktrees/task1-cursor-leaks` (branch `task1-cursor-leaks`, HEAD `9f27216`)
  is left in place for the parent/integrator to merge or inspect; it was not merged into
  `ai_test` since that is an integration decision outside this task's scope.

## Commit

```
9f27216 fix(loggereditor): wrap cursor-protected blocks in try/finally
```
(on branch `task1-cursor-leaks`, worktree `/home/hsai1/dev/midv/midvatten/.worktrees/task1-cursor-leaks`)
