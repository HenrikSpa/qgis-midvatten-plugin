# Backlog

Ideas and deferred work without an active branch. One line each; details in
the linked archived doc where one exists.

- [ ] Finish narrowing the remaining `except Exception` megablocks — `save_to_db` was split into compute/connect/write stages, the rest are untouched (details: docs/archive/2026-06-10-maintainability-refactor-review-plan.md)
- [ ] Classify remaining user-message sites by intent: migrate pure `QMessageBox.information()` outcome popups to `MessagebarAndLog`, and redesign instructional popups as disabled-action-plus-tooltip (details: docs/archive/2026-06-10-maintainability-refactor-review-plan.md)
- [ ] Consolidate the ~34 scattered `strptime`/`strftime` sites across 12 modules, including `fix_date()` in `tools/import_logger/parsers.py`, without changing stored timestamps (details: docs/archive/2026-06-10-maintainability-refactor-review-plan.md)
- [ ] Split `definitions/midvatten_defs.py` lazily: move the locale helpers to their own module to break the `midvatten_utils` import cycle, then peel off new concerns opportunistically (details: docs/archive/2026-06-10-maintainability-refactor-review-plan.md)
- [ ] Decide whether to deprecate the legacy `wqualreport` in favour of `wqualreport_compact` — a product decision, not a refactor (details: docs/archive/2026-06-10-maintainability-refactor-review-plan.md)
- [ ] HTML-escape report field values so obsids and comments containing `<` or `&` stop breaking report output (changes user-visible output; needs sign-off) (details: docs/archive/2026-06-12-drillreport-locale-dedup-plan.md)
- [ ] Make `start_waiting_cursor`/`stop_waiting_cursor` no-ops off the GUI thread and delete the `manage_wait_cursor` parameter, attribute and three guards from `import_data_to_db` (details: docs/archive/2026-07-27-post-review-cleanup-OUTCOMES-plan.md)
- [ ] Switch `import_exception_handler` (`tools/import_data_to_db.py:1296`) from a bare `stop_waiting_cursor()` to `unwind_waiting_cursor(entry_depth)` so there is one cursor-restoration policy (details: docs/archive/2026-07-29-cursor-scope-and-destination-table-plan.md)
- [ ] Replace `LoggerDbImportResult.reason`'s status-code-plus-traceback string with an `ImportOutcome` enum so the GUI owns the wording (details: docs/archive/2026-07-27-post-review-cleanup-OUTCOMES-plan.md)
- [ ] Replace the six parallel per-format tables/branches in `tools/import_logger/importer.py` with one `_format_sections` registry, so adding a format is one registration (details: docs/archive/2026-07-27-post-review-cleanup-OUTCOMES-plan.md)
- [ ] Benchmark and, if safe, drop the six trailing defensive `.copy()` calls in `tools/import_logger/pipeline.py` (~120 ms and ~100 MB per 500k-row file) (details: docs/archive/2026-07-27-post-review-cleanup-OUTCOMES-plan.md)
- [ ] Decide whether `_report_parse_failures` should stop double-logging every parse failure in two wordings per run (changes log verbosity) (details: docs/archive/2026-07-27-post-review-cleanup-OUTCOMES-plan.md)
- [ ] Direct Word (.docx) export for the custom general report — on hold since 2026-06-11 pending confirmation that users want it (details: docs/archive/2026-06-10-custom-drillreport-docx-export-plan.md)
- [ ] Re-ground the motivation for an integer primary key on `obs_points`/`obs_lines` (tool compat / FID semantics, not the already-fixed 100-row bug) before deciding whether to migrate (details: docs/archive/2026-04-18-integer-pk-schema-migration-design-spec.md)
- [ ] Decompose `LoggerEditor` (3,857 lines, 138 methods, one class) into a thin Qt coordinator over unit-testable collaborators, one slice at a time (details: docs/archive/2026-06-15-loggereditor-refactor-HANDOVER-spec.md)
- [ ] Add cursor-leak regression tests for `delete_selected_range` and `_trend_release` — only `calc_best_fit` got one (details: docs/archive/2026-07-29-review-bug-fixes-progress.md)
- [ ] Strat symbology: deepest-stratum shadow paints rows the geology layer skips (TODO at `tools/strat_symbology.py:99`) — see `docs/superpowers/plans/2026-02-25-strat-symbology-shadow-else-bug.md`.
