# LoggerEditor refactor analysis — problems & target architecture

Date: 2026-06-15. Subject: `tools/loggereditor.py` (item 8 of the maintainability
plan, the deliberate last and highest-risk item). This is a problem inventory to
drive a *complete* refactor, written from measurements against the current file on
`ai_test` — not impressions.

## Scale (measured)

| Metric | Value |
|---|---|
| Lines | 3,802 |
| Methods on the single `LoggerEditor` class | 137 |
| Distinct instance attributes (`self.x = …`) | 95 |
| Methods > 100 lines | 6 |
| Methods > 50 lines | 17 |
| `@fn_timer` perf decorators in production code | 34 |
| `except Exception` blocks | 8 |
| Concern reference counts | pandas/buffer **207**, matplotlib **133**, Qt **102**, DB/SQL **73** |
| Test files exercising it | 9 |
| Direct `editor._private(...)` call sites in tests | 26 |
| Sibling module reaching into `editor._private` | `loggereditor_resolve_dupes.py` (6 distinct methods) |

One class is simultaneously a Qt window, a pandas data model, a matplotlib renderer,
a SQL gateway, an undo/redo engine, and a series-metadata controller.

---

## Problem 1 — One class, five+ responsibilities (SRP)

`LoggerEditor` interleaves concerns that have no business sharing a namespace. The
reference counts above quantify it; concretely the method clusters are:

- **Pandas buffer & diff model** (no Qt needed in principle): `_compute_line_keys`,
  `_line_key_codes`, `_recompute_line_keys`, `_build_edit_mask`, `_duplicate_instants`,
  `_duplicate_runs`, `_classify_duplicates`, `_drop_rows_by_raw`,
  `_remove_redundant_duplicates`, `_remove_cross_source_overlaps`,
  `_resolve_conflict_keep`, `_full_buffer_range`, `_compute_update_statements`.
- **DB gateway** (SQL/transactions): `load_obsid_from_db`, `get_all_obsids_in_w_levels_logger`,
  `get_uncalibrated_obsids`, `_ensure_meas_ts`, `getlastcalibration`,
  `setlastcalibration`, the write half of `save_to_db`.
- **Matplotlib rendering & interaction**: `_build_ts_recarray`, `_build_head_ts_for_plot`,
  `_draw_series` (177 lines), `_draw_trend_overlay`, `_trend_release`, the cursor/slider/
  legend-pick machinery (133 matplotlib refs).
- **Qt UI state**: `show` (264 lines), comboboxes/buttons/tabs, `_build_series_tab`,
  `_update_series_tab`, dialogs, `closeEvent` (102 Qt refs).
- **Undo/redo history**: `_history_push`, `undo`, `redo`, `jump_to_history`,
  `_restore_from_history`, `_refresh_history_widget`.
- **Series-metadata CRUD**: `_on_series_create/assign/edit`, `_update_series_tab`.
- **Calibration**: `set_logger_pos`, `add_to_level_masl`, `calc_best_fit`, `match_ts_values`.

**Cost:** no concern can be read, tested, or changed in isolation; every change risks
the others; new contributors must understand all six to touch one.

## Problem 2 — 95 fields of shared mutable state, with parallel sources of truth

Ninety-five instance attributes form one giant shared-state blob that all 137 methods
read and write. Two concrete correctness-smell instances:

- **"Which obsid" has four sources of truth**: `self.obsid`, `self._buf_obsid`,
  `self._meas_obsid`, and the `selected_obsid` property (read off the combobox).
  Methods must keep them in sync by hand (e.g. `_obsid_ensure_buf_current` compares
  `self._buf_obsid == self.selected_obsid`). Divergence = stale-data bugs.
- **`self.meas_ts` vs `self._meas_ts`** are a hand-rolled two-field memo: `_meas_ts`/
  `_meas_obsid` cache the last `meas_ts` (lines 1012-1031). The caching is open-coded
  into the field set rather than encapsulated.

**Cost:** the state is the real API. Any extraction must decide *who owns each field*,
and a wrong split silently desynchronises obsid/buffer/measurement state.

## Problem 3 — God methods

| Method | Lines | What it mixes |
|---|---|---|
| `save_to_db` | 298 | dup-detection (pandas) + diff (pandas) + connect + transaction + series CRUD + buffer bookkeeping |
| `show` | 264 | widget build + 10 signal connections + plot setup + initial load |
| `_draw_series` | 177 | data shaping + matplotlib artist construction + styling |
| `load_obsid_and_init` | 174 | DB load + buffer build + cache rebuild + widget refresh |
| `_compute_update_statements` | 117 | diff → SQL statement generation |
| `_update_series_tab` | 106 | data read + widget rebuild |
| `_build_series_tab` | 100 | widget construction |

`save_to_db` was already split into compute/connect/write *stages* (item 6, 2026-06-12)
but remains 298 lines because the stages still live in one method on one class.

**Cost:** untestable in pieces; high cognitive load; merge-conflict magnets (this is the
most actively developed file in the repo).

## Problem 4 — "Private" methods are a de-facto public API (white-box coupling)

The underscore prefix is a lie. The buffer/duplicate methods are consumed across module
and test boundaries:

- **Sibling module** `tools/loggereditor_resolve_dupes.py` reaches into the editor:
  `self._editor._remove_redundant_duplicates`, `_remove_cross_source_overlaps`,
  `_full_buffer_range`, `_focus_plot_on_instants`, `_duplicate_instants`,
  `_classify_duplicates`.
- **26 test call sites** invoke `editor._private(...)` directly — `_full_buffer_range`
  (×6), `_classify_duplicates` (×5), `_history_push` (×4), `_remove_redundant_duplicates`
  (×3), `_remove_cross_source_overlaps` (×3), `_duplicate_instants` (×2), etc.

**Cost:** this is the single biggest refactor constraint. Moving any of these methods to
a collaborator breaks a sibling module *and* up to 26 tests at once. The tests are
white-box — they assert on internal methods rather than user-facing behaviour — so they
both pin the current shape and must be migrated in lockstep with any extraction.

## Problem 5 — Data/DB/plot logic only testable through the full Qt object

Because the pure-data buffer logic lives on the QMainWindow subclass, the duplicate
handling and diff computation — which carry **strict byte-exact reference-data
invariants** (one row per obsid per normalized second; `test_loggereditor_dupes.py`
asserts exact DB state) — can only be exercised by constructing the whole editor with a
real SpatiaLite DB and QGIS layers. There is no seam to unit-test the diff/dup model on
plain DataFrames.

**Cost:** slow, fragile tests; the highest-risk logic in the file has the least isolable
coverage.

## Problem 6 — Signal lifecycle inside `show()`

10 of the 35 `.connect()` calls happen inside `show()` (lines 209-472). LoggerEditor is a
persistent, reused window (per `midvatten_plugin._dispatch`); item 7 audited this class
and found its show()-time connects are `hasattr`-guarded, so it is currently safe — but
the guard pattern is implicit and easy to break during decomposition.

**Cost:** any reshuffle of `show()` can silently reintroduce double-connect bugs unless
the guard is made explicit.

## Problem 7 — Perf instrumentation woven into production structure

34 `@fn_timer` decorators (a no-op unless `MIDVATTEN_TIMING` is set) are sprinkled across
methods. They are harmless at runtime but are structural noise that reflects past
perf-firefighting on this exact file (the recent `loggereditor-perf` work) and mark the
methods that were hot — useful signal, but they clutter the class surface.

## Problem 8 — Remaining broad `except Exception` blocks

8 remain. `save_to_db`'s were narrowed (item 6); the rest still collapse distinct failure
modes. Lower priority than the structural problems but part of the same cleanup.

---

## Blast radius

Changing `LoggerEditor` touches: `tools/loggereditor_resolve_dupes.py` (sibling dialog),
and 9 test files (`test_loggereditor_{dupes,series,refseries,resolve_ui,separation,
plot_interaction,plot_limits}.py`, `test_wlevels_calc_calibr.py`). 26 of those tests bind
to private methods.

---

## Target architecture (proposed)

Decompose the god class into a thin Qt coordinator delegating to plain-Python
collaborators that can be unit-tested without Qt:

- **`LoggerBuffer`** — owns `_buf`/`_original_buf`/`_series_buf` and ALL pure-pandas
  logic: line keys, edit masks, the duplicate model (`classify/duplicate_runs/
  remove_redundant/remove_cross_source/resolve_conflict/full_range`), and the diff →
  update-statement computation. No Qt, no SQL, no matplotlib. Unit-testable on plain
  DataFrames — this is where the reference-data invariants belong.
- **`LoggerRepository`** (DB gateway) — every SQL string, `DbConnectionManager`, and
  transaction. Takes/returns plain data; the buffer and repository never import Qt.
- **`LoggerPlot`** — matplotlib artist construction, trend overlay, cursor/slider/legend
  interaction. Holds the axes/figure, not the data.
- **`HistoryStack`** — undo/redo snapshots, decoupled from the history *widget*.
- **`SeriesController`** — series-metadata CRUD + its tab.
- **`LoggerEditor`** — the QMainWindow: builds widgets, wires signals once, and
  coordinates the collaborators. Target: a few hundred lines.

A single owned obsid (on the coordinator or buffer) replaces the four parallel fields;
`meas_ts` memoization moves inside the repository/buffer.

## Why this is hard — sequencing constraints

1. **The white-box API must move in lockstep.** The 26 test sites and the resolve-dupes
   dialog call `editor._method()`. Two viable strategies:
   - **(a) Strangler with delegation:** introduce `LoggerBuffer`, move the *logic* there,
     and keep thin `editor._method(...)` wrappers that forward to `self._buffer.method()`.
     Sibling module and tests keep working unchanged; a later slice migrates them to
     `editor.buffer.method()` and deletes the wrappers. Lowest risk, two passes.
   - **(b) Migrate callers up front:** change the dialog + 26 tests to `editor.buffer.*`
     in the same slice as the extraction. Fewer total steps, larger blast per slice.
   Recommendation: **(a)** — it keeps every slice green and reviewable.
2. **Reference-data invariants are non-negotiable.** Before moving the duplicate/diff
   logic, add DataFrame-level characterization tests for `LoggerBuffer` so the move is
   proven byte-identical, then keep the existing full-GUI dup tests as the backstop.
3. **One collaborator per slice**, full `test_loggereditor*` + `test_import_logger`
   between slices, full suite at slice boundaries.
4. **Make the `show()` connect-guard explicit** before reshuffling `show()`.

## Suggested slice order

1. `LoggerBuffer` extraction (strangler + delegation) — the pure-data model first, as the
   original plan intended; unblocks isolated testing of the riskiest logic.
2. `LoggerRepository` — pull all SQL out; buffer becomes DB-free.
3. `HistoryStack` — small, self-contained.
4. `LoggerPlot` — largest mechanical move; isolate matplotlib.
5. `SeriesController` — series tab + CRUD.
6. Collapse the `editor._method` wrappers: migrate the resolve-dupes dialog and the 26
   tests to the collaborator interfaces; delete wrappers.
7. Final pass: shrink `show()`/`__init__`, fold the four obsid fields into one, retire the
   `meas_ts`/`_meas_ts` parallel pair.

Each slice is independently mergeable and leaves the suite green; the big risk
(duplicate/diff correctness) is retired first and behind characterization tests.
