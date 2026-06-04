# Logger Editor — period-scoped duplicate resolution + duplicate-run marker (Plan 2d)

**Date:** 2026-06-04
**Component:** `tools/loggereditor.py`, `tools/loggereditor_resolve_dupes.py`
**Status:** Design approved, pending spec review
**Builds on:** Plan 2a/2b/2c (merged) — `_duplicate_instants`, `_classify_duplicates`, `_remove_redundant_duplicates`, `_remove_cross_source_overlaps`, `_resolve_conflict_keep`, `_focus_plot_on_instants`, banner, `ResolveDuplicatesDialog`.

## Problem

The cross-source resolution `_remove_cross_source_overlaps(keep_source)` is **global**: it assumes one source supersedes everywhere. In reality which source is authoritative can vary by period — source A may supersede in Jan–Mar, source B in Apr–Jun. A single global keep-source choice corrupts the period where the other source should win. Users need to resolve duplicates **period by period**, and need to *see* where unresolved duplicates remain.

## Design

### A. Range-aware resolution (the substance)

- `_classify_duplicates(fr=None, to=None)` filters the duplicated rows to the inclusive `[fr, to]` datetime window before grouping. `None`/`None` means the full range — backward-compatible, so existing callers and Plan 2b tests are unaffected.
- `_remove_redundant_duplicates(fr=None, to=None)` and `_remove_cross_source_overlaps(keep_source, fr=None, to=None)` thread the window through to `_classify_duplicates`. "Keep source A" therefore means *keep A within this period* — the per-period-supersession fix.
- Conflicts are resolved via the plot (Plan 2c decision), so they are unaffected by range params.
- The dialog reads the editor's current `From`/`To` (`self._editor.from_date_time` / `to_date_time`, `.dateTime().toPyDateTime()`) and passes them to classification + every op. A header label states the active scope and counts, e.g. *"Resolving within 2021-01-01 – 2021-03-31 — 8402 of 25107 duplicates in range"*. A **"Whole dataset"** button widens the working scope to all data (sets the editor From/To to the buffer's full extent, then refreshes), so a user who does not care about periods still gets one-click global resolution.

### B. Duplicate-run marker

- `_duplicate_runs() -> list[tuple]`: returns `(start_ts, end_ts)` for each maximal **run** of duplicated instants — consecutive in the buffer's sorted *distinct* instants. A run breaks where a non-duplicated instant interrupts it. Pure and unit-testable; scale-safe (a 10 000-row overlap collapses to one run, so the marker draws O(runs) not O(rows)).
- Drawn during `update_plot` as red line segments with end markers along the axes bottom, using a blended transform (x in data coords, y at ~0.02 axes-fraction so it pins to the bottom regardless of the y data range). The marker is recomputed every redraw, so it shrinks the instant a period is resolved in the buffer and disappears when no duplicates remain. The marker artist(s) are tracked so they are cleared/redrawn cleanly each `update_plot` (no accumulation).

### C. Workflow

1. Load an obsid with duplicates → banner appears + red runs at the bottom.
2. Aim `From`/`To` at a run (type, the existing "set from/to from selection" buttons, or the dialog's "Show on plot").
3. *Resolve duplicates…* → dialog scoped to that window → pick keep-source for *that* period, or bulk-remove redundant in-window.
4. Buffer updates → that run shrinks/vanishes. Repeat for the next period.
5. Save persists all resolutions at once (Plan 2a delete-by-raw-text).

### D. Components / interfaces

- `LoggerEditor._classify_duplicates(fr=None, to=None)` — add window filter.
- `LoggerEditor._remove_redundant_duplicates(fr=None, to=None)`, `_remove_cross_source_overlaps(keep_source, fr=None, to=None)` — add window params.
- `LoggerEditor._duplicate_runs() -> list[tuple]` — new, pure.
- `LoggerEditor._draw_duplicate_marker()` (or inline in `update_plot`) — new; clears prior marker artists, draws current runs.
- `LoggerEditor._full_buffer_range() -> tuple` — helper returning (min_ts, max_ts) of `_buf.index` (used by "Whole dataset").
- `ResolveDuplicatesDialog` — read editor From/To; pass to ops; header label with scope + counts; "Whole dataset" button (sets editor From/To to `_full_buffer_range()` and refreshes); existing buckets otherwise unchanged.

### E. Testing — every user-facing widget is click-tested

Per the project rule that integration tests must exercise the real user flow, **each button/widget is driven by clicking the actual widget** (e.g. `QPushButton.click()`, `gui_utils.set_combobox`) inside a `show()`-based test — not by calling the `_on_*` handler directly. Modal `exec_` is avoided by constructing the dialog directly (as Plan 2c tests do) and clicking its buttons, and by patching `ResolveDuplicatesDialog.exec_` when testing the banner button.

Widget coverage (all via real clicks):
- **Banner "Resolve duplicates…" button** — with `exec_` patched, `_resolve_dupes_btn.click()` opens a dialog scoped to the editor's range; banner refreshes afterward.
- **Dialog "Remove N redundant rows" button** — `.click()` removes the coarse twins in range, buffer shrinks, `_dirty` set.
- **Each cross-source "Keep '<source>'" button** — `.click()` keeps that source in the current window only; a twin in a *different* window with a different keep-source is left untouched (the per-period correctness test).
- **"Show on plot" buttons (all three buckets)** — `.click()` enables datetime-precision separation and sets the From/To around the bucket's instants (editor shown).
- **"Whole dataset" button** — `.click()` sets editor From/To to the full extent and the dialog re-scopes (header/counts update to the totals).

Pure/state coverage:
- `_duplicate_runs()` merges contiguous duplicated instants into runs and breaks on a clean instant (unit).
- `_classify_duplicates(fr, to)` and the two ops respect the window (unit), and default (None) behaves as before.
- **Marker integration** (show()-based): after load+update_plot the marker artist(s) exist with one segment per run; after resolving a period the marker has fewer/shorter segments; when all resolved the marker is empty.

Backends: SpatiaLite for the buffer/dialog logic; the show()-based marker/widget tests run under the existing spatialite (and where cheap, postgis) calibr harness.

## Out of scope
- Clickable red-segment selection (set the period by clicking the marker) — possible later; v1 uses the From/To widgets.
- Per-instant conflict enumeration (Plan 2c decided: resolve conflicts via the plot).
- Shaded-band marker styling (chosen: bottom runs only).
