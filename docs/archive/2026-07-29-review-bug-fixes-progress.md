> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-07-29 · modified: 2026-07-29 · archived: 2026-07-31

# SDD ledger — plan: docs/superpowers/plans/2026-07-29-review-bug-fixes.md

## Tasks
- Task 1: cursor leaks in calc_best_fit, delete_selected_range, _trend_release — complete (9f27216, merged)
- Task 2: _restore_from_history dirty flag comparison — complete (cc2d959, merged)
  - Task 2: minor (deferred): test missing `print(mock_messagebar.mock_calls)` before asserts (stylistic consistency)
- Task 3: _log_on_main_thread empty bar_msg guard — complete (176ed5c, merged)
  - Task 3: minor (deferred): fold the new `if bar_msg is not None:` guard (message_utils.py:133) into the identical guard at line 112 — flagged by 3/4 simplify agents as duplication but judged out of scope for this one-line brief; see task-3-report.md

## Final whole-branch review
- Range: 0563e1f..176ed5c (3 commits)
- Verdict: Ready to merge — no Critical or Important findings
- Minor (cosmetic, all deferred): missing mock_calls print in dirty-flag test, duplicate bar_msg guards, only 1/3 cursor methods has a regression test
