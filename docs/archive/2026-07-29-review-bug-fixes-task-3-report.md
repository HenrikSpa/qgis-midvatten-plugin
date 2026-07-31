> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-07-29 · modified: 2026-07-29 · archived: 2026-07-31

# Task 3 report — guard `_log_on_main_thread` against `None` `bar_msg`

## Summary

`_log_on_main_thread` in `tools/utils/message_utils.py` unconditionally called
`QgsApplication.messageLog().logMessage(returnunicode(bar_msg), ...)` even when
`bar_msg is None`. Since `returnunicode(None)` returns `""`, every
`log_msg`-only call (40 call sites across the codebase) produced a spurious
empty entry in the QGIS message log panel. Fixed by wrapping that call in
`if bar_msg is not None:`, mirroring the identical guard already present a few
lines above (line 112) for the messagebar widget creation. Followed the
brief's TDD steps verbatim; the brief's test snippet was used as-is (it passed
without modification), with two small consistency cleanups applied afterward
during the mandatory simplify pass (see below).

Work was done in an isolated worktree (native `EnterWorktree` refused, as in
Task 2, because this subagent has a pinned cwd — it explicitly errors:
"cannot create a worktree from a subagent with a cwd override ... would
mutate the parent session's process-wide working directory"). Fell back to
the manual git-worktree path, matching the `.worktrees/` convention used by
Tasks 1 and 2: `/home/hsai1/dev/midv/midvatten/.worktrees/task3-log-msg-guard`
on branch `task3-log-msg-guard` (branched from local HEAD of `ai_test`, i.e.
from Task 2's merge commit `cc2d959`). The branch was fast-forward merged into
`ai_test` and the worktree/branch removed, following the same
sequential-merge pattern Task 2 established.

## What changed

**`tools/utils/message_utils.py`** — lines 133–135 (inside
`_log_on_main_thread`, a `@staticmethod` of `MessagebarAndLog`):

```python
-        QgsApplication.messageLog().logMessage(
-            returnunicode(bar_msg), "Midvatten", level=log_level
-        )
+        if bar_msg is not None:
+            QgsApplication.messageLog().logMessage(
+                returnunicode(bar_msg), "Midvatten", level=log_level
+            )
```

Exact match to the brief's Step 3 snippet. No other lines in this file
touched.

**`test/test_midvatten_utils.py`** — added
`test_log_msg_only_does_not_produce_empty_bar_entry` to the
`TestMessageDispatcher` class (now lines 979–993), immediately after
`test_background_thread_payload_round_trips_through_deliver`, i.e. at the end
of the class as the brief instructed ("Add to the `TestMessageDispatcher`
class").

The test calls `_log_on_main_thread(log_msg="detail only")` directly with
`qgis.utils.iface` mocked non-`None` (so the function doesn't early-return)
and `QgsApplication` mocked to capture `logMessage` calls, then asserts `""`
is never among the logged message bodies and `"detail only"` is.

## TDD sequence followed

1. Added the test from the brief verbatim (no modification needed this time,
   unlike Task 2 — the brief's snippet ran correctly as given).
2. Ran it alone — failed exactly as predicted:
   `AssertionError: assert '' not in ['', 'detail only']`.
3. Applied the one-line-guard fix (brief's Step 3, verbatim).
4. Re-ran the new test alone — passed.
5. Ran the full `test_midvatten_utils.py` suite — 55 passed (54 pre-existing
   + 1 new).
6. Ran the required combined suite
   (`test_wlevels_calc_calibr.py` + `test_midvatten_utils.py`) — 135 passed.
7. Ran `ruff check --fix` / `ruff format` — see Lint section.
8. Ran the mandatory `simplify` skill (4 parallel review agents) — see below.
9. Re-ran the combined suite after the simplify-pass edits — 135 passed
   again, unchanged.
10. Committed, fast-forward merged into `ai_test`, re-ran the combined suite
    once more on `ai_test` post-merge — 135 passed.

## Test results

New test alone, before the fix:
```
test/test_midvatten_utils.py::TestMessageDispatcher::test_log_msg_only_does_not_produce_empty_bar_entry FAILED
AssertionError: assert '' not in ['', 'detail only']
1 failed, 1 warning in 1.48s
```

New test alone, after the fix:
```
test/test_midvatten_utils.py::TestMessageDispatcher::test_log_msg_only_does_not_produce_empty_bar_entry PASSED
1 passed, 1 warning in 1.28s
```

Full `test_midvatten_utils.py`, after the fix:
```
55 passed, 3 warnings in 1.40s
```

Required combined suite, after the fix (in the worktree, pre-simplify-pass):
```
135 passed, 3 warnings in 87.74s (0:01:27)
```

Required combined suite, after the simplify-pass edits (still in worktree):
```
135 passed, 3 warnings in 87.97s (0:01:27)
```

Required combined suite, post-merge on `ai_test` (final confirmation):
```
135 passed, 3 warnings in 89.09s (0:01:29)
```

## Lint

`ruff check --fix tools/utils/message_utils.py test/test_midvatten_utils.py`
reported 2 errors, **both pre-existing and unrelated to this change**
(confirmed via `git stash` + re-running ruff against the stashed-clean
worktree — identical errors present before this diff):
- `N815` at `test/test_midvatten_utils.py:326` — mixedCase class attribute
  `qgis_PyQt_QtGui_QInputDialog_getText` in `TestAskUser` (pre-existing).
- `UP031` at `tools/utils/message_utils.py:176` — `"%s" % (msg)` in
  `pop_up_info` (pre-existing, unrelated function).

Neither is auto-fixable and neither was introduced by this diff, so both were
left untouched per "never change unrelated code."

`ruff format` reformatted the new test (collapsed a wrapped list
comprehension onto one line) — cosmetic only, reconfirmed passing after.

## Simplify-skill review (mandatory per CLAUDE.md workflow)

Ran the `simplify` skill with 4 parallel review agents (reuse, simplification,
efficiency, altitude) over `git diff HEAD`. Findings and disposition:

- **Reuse** — flagged 3 items: (1) the new `if bar_msg is not None:` guard at
  line 133 duplicates the identical condition already open at line 112, 21
  lines above — could be folded into that block; (2) the test uses nested
  `with mock.patch(): / with mock.patch():` instead of the parenthesized
  multi-context-manager style the same class already established 25 lines
  earlier; (3) `mock.patch("qgis.utils.iface")` omits `autospec=True`, unlike
  every other patch of that same target in the file (13+ occurrences).
  **Applied (3)**: added `autospec=True` for consistency, since `mock_iface`
  was being dropped anyway (see Simplification). **Not applied (1)**: see
  Altitude disposition below. **Not applied (2)**: the nested-`with` form here
  is 2 levels (not the 3+ that motivated the parenthesized style elsewhere in
  the class), and changing it would touch structure beyond the brief's
  test — left as brief-verbatim.
- **Simplification** — flagged 2 items: (1) same guard-duplication as reuse's
  item 1; (2) `mock_iface` bound via `as mock_iface` but never used in the
  test body. **Applied (2)**: dropped the unused binding
  (`with mock.patch("qgis.utils.iface", autospec=True):`). **Not applied
  (1)**: see Altitude.
- **Efficiency** — no issues; explicitly noted the fix is efficiency-*positive*
  (removes one `logMessage` + one `returnunicode(None)` call per log-only
  invocation). Flagged the same two-guards observation as negligible
  (nanoseconds) and not worth raising as a real efficiency finding.
- **Altitude** — assessed the two-guards duplication (raised by all three
  other angles) and judged it **not a genuine altitude problem**: the fix
  makes the function *more* symmetric (bar_msg and log_msg now share the same
  "if present, log it" shape, closing the original asymmetry that was the
  bug), and the two `bar_msg is not None` checks gate semantically distinct
  concerns (UI widget vs. log write) — merging them would entangle unrelated
  responsibilities rather than simplify. Called the merge idea "a
  stylistic/simplify-pass suggestion, not a design defect — legitimately out
  of scope for this one-line bug-fix brief."

**Disposition on the guard-duplication finding** (raised independently by 3 of
4 agents): **not applied**. Reasons: (a) the brief specifies this exact code
verbatim, including the comment that it "mov[es] the `bar_msg` log entry
inside a guard, matching the bar_msg widget guard already present at line
112" — i.e. two mirrored guards, not one merged block, appears to be the
brief's deliberate structure; (b) 3 of 4 review agents (simplification,
efficiency, altitude) independently characterized it as optional/negligible/
out-of-scope rather than a required fix; (c) merging would touch lines 112–132
which are outside this task's reviewed diff, for a purely stylistic gain.
Recorded here as a legitimate follow-up candidate if a third `bar_msg`-gated
block is ever added to this function.

Applied fixes only (both trivial, test-only, verified with a full re-run of
the required suite afterward — see Test results):
```python
-        with mock.patch("qgis.utils.iface") as mock_iface:
+        with mock.patch("qgis.utils.iface", autospec=True):
```

## Concerns

- The brief's test snippet needed no correction this time (unlike Task 2,
  where a missing `.show()` call had to be added). It ran and failed/passed
  exactly as the brief predicted.
- The guard-duplication finding (see Simplify section) is a legitimate,
  independently-corroborated observation but was deliberately left unapplied
  as out of scope for this brief. Flagging it explicitly in case the
  integrator wants it folded in as a follow-up.
- Two pre-existing, unrelated lint errors (`N815`, `UP031`) remain in the
  touched files — confirmed present before this diff via `git stash`, left
  untouched.
- Merge decision: followed Task 2's established sequential-merge pattern
  (fast-forward `task3-log-msg-guard` into `ai_test`, delete branch/worktree).
  This was a clean fast-forward with no conflicts since `ai_test` had not
  moved past `cc2d959` (Task 2's merge commit) in the interim.

## Commit

```
176ed5c fix(message_utils): skip empty bar_msg log entry when only log_msg is set
```
Originally on branch `task3-log-msg-guard`; now fast-forward merged into
`ai_test` (same commit hash, `ai_test` HEAD is `176ed5c`). The worktree at
`.worktrees/task3-log-msg-guard` and the `task3-log-msg-guard` branch have
been removed after the merge.
