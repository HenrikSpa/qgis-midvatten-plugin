# Drillreport sv/en dedup (item 17, slice 1)

Date: 2026-06-12. Branch: `html-reports` (worktree off ai_test @ 1108da8).
First slice of plan item 17 (HTML report generation). Scope: `tools/drillreport.py`
only; wqualreport overlap and HTML escaping are explicit follow-ups (escaping
changes output and is deferred per the parent plan).

## Verified state

- Three sv/en method pairs (`rpt_upper_left`, `rpt_upper_right`,
  `rpt_lower_right`) are structurally identical; differences are (a) label
  strings (sv hardcoded vs en `QCoreApplication.translate`), (b) drifted
  details: stratigraphy column widths sv 17/27/17/5/9/27 vs en
  15/27/17/9/13/21; sv coordinate rows omit the comma when `crs_name` is
  empty, en always emits `crs_name + ", "`; sv upper_left uses
  `!= ""/!= "NULL"` chains where en uses `not in _EMPTY_VALS` (same
  semantics); en upper_right indexes `row[2..8]` where sv uses attributes
  (same data via StratigraphyRow).
- `rpt_*` methods have no callers outside the class (custom_drillreport.py is
  a separate implementation; midv_addons does not use Drillreport).
- test_drillreport.py locks the SWEDISH output byte-exact on both backends.
  No English reference exists.

## Approach (byte-identical target)

1. **Capture an English golden first**: add `TestDrillreportEnglish*` mirroring
   the existing test with `is_locale_swedish` patched False, reference taken
   from CURRENT code output. Commit before any production change.
2. **Dedup**: one method per quadrant driven by a per-locale spec dict
   (labels, stratigraphy widths, crs-row formatter, unit strings). Drifted
   details are PRESERVED via the spec, not unified — unification is an output
   change and belongs to the escaping follow-up if wanted.
3. Verify: both locale reference tests byte-green on spatialite + postgis.
