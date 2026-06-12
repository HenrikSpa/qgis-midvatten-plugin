# message_utils re-export sweep (item 15 completion)

Date: 2026-06-12. Branch: `message-utils-sweep` (worktree off ai_test @ a848b9f).
Completes plan item 15 (docs/superpowers/plans/2026-06-10-maintainability-refactor-review.md):
the message_utils group — `MessagebarAndLog`, `pop_up_info`, `show_message_log`,
`sql_failed_msg` — was deferred from the 2026-06-11 sweep as ~80% of the volume.

Verified scope (2026-06-12):
- 263 production sites in 34 `tools/` files use `common_utils.X` / `midvatten_utils.X`.
- 16 utils-layer modules import the names bare from `message_utils` and call them
  unqualified (~130 sites).
- 264 test patch targets, all `MessagebarAndLog`: 253 on
  `midvatten.tools.utils.common_utils.`, 11 on `midvatten.tools.utils.midvatten_utils.`.
- midv_addons: 18 patches on `common_utils.MessagebarAndLog`, intercepting its OWN
  calls (its prod code uses the `common_utils.` prefix) — unaffected while the
  re-export stays. Re-exports stay per the midv_addons contract.

## Key design decision: one canonical patch target

Today a patch on `common_utils.MessagebarAndLog` intercepts (a) tools/ calls via the
`common_utils.` prefix and (b) bare-name calls inside common_utils itself
(`general_exception_handler` criticals, calc_* messages) — but NOT bare-name calls in
db_utils/layer_utils/etc. After this sweep, ALL production calls are module-qualified
`message_utils.X`, so a single patch target
`midvatten.tools.utils.message_utils.MessagebarAndLog` intercepts everything —
a strict superset of today's interception.

Risk accepted: tests asserting exact call counts may now see additional calls from
utils-layer internals that previously bypassed the mock. Such failures are visible
and mean the assertion was blind, not that behavior changed; fix the test to match
the (unchanged) real message traffic — never the production code, never reference data.

## Phases (one commit each)

1. **Phase A — utils layer**: in the 15 source modules with bare-name calls
   (common_utils, midvatten_utils, db_utils/*, layer_utils, file_utils, gui_utils,
   dialog_utils, midvsettings, midvatten_defs), qualify calls as `message_utils.X`
   via `from midvatten.tools.utils import message_utils`. In common_utils and
   midvatten_utils the existing `from ...message_utils import ...` re-export lines
   STAY (midv_addons contract) — add `# noqa: F401` to `MessagebarAndLog` there since
   it loses its last in-module use. `string_utils.py` untouched (function-level
   import is cycle-breaking and already call-time-resolved). `message_utils.py`
   untouched (defines the names).
2. **Phase B — tools/ sweep**: `common_utils.X`/`midvatten_utils.X` →
   `message_utils.X` at the 263 sites; add the module import; let ruff drop
   now-unused aggregator imports.
3. **Phase C — tests**: replace the dotted target strings
   `midvatten.tools.utils.{common_utils,midvatten_utils}.MessagebarAndLog` →
   `midvatten.tools.utils.message_utils.MessagebarAndLog` everywhere in test/
   (string-literal replace; handles multi-line patch() calls). Update the CLAUDE.md
   testing convention to the new target.

## Verification

- `ruff check --fix .` + `ruff format` (revert out-of-scope reformat noise).
- Targeted: test_midvatten_utils, test_db_utils*, test_import_fieldlogger,
  test_loggereditor (representative patch-heavy files).
- Full suite at slice boundary (last green: 1121 passed @ a848b9f).
- midv_addons contract: direct import verification of the surface
  (compat test hangs in this env).
