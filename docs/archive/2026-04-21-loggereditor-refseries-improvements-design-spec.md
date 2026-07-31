> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-04-21 · modified: 2026-04-21 · archived: 2026-07-31

# Logger Editor — Reference Series Improvements

**Date:** 2026-04-21
**Branch:** ai_test (built in own worktree)
**Files touched:** `tools/loggereditor_refseries.py`, `tools/loggereditor.py`

---

## Problem

1. The values list inside each `_FilterRow` clips at ~4 visible rows (`setMaximumHeight(90)`). Resizing the dialog only adds dead space below the filter scroll area because the scroll area also has a hard cap (`setMaximumHeight(280)`).

2. When multiple values are selected across filter rows, `_build_ref_query` wraps them all into `WHERE col IN (…)`, producing one combined/resampled series instead of one line per combination.

---

## Change 1 — Filter List Grows Vertically

**File:** `tools/loggereditor_refseries.py`

### `_FilterRow.__init__`
- Remove `self.values_list.setMaximumHeight(90)`.
- The `QListWidget` will now size to its content and scroll internally when the list is long.

### `RefSeriesDialog.__init__`
- Remove `scroll.setMaximumHeight(280)`.
- Change `main_layout.addWidget(scroll)` → `main_layout.addWidget(scroll, 1)`.
  - Stretch factor 1 makes the scroll area claim all vertical space left over after the fixed-height rows (table, ycol, resample, normalise, scale, style, label, buttons).

No structural changes; the dialog can now be resized and the filter area grows with it.

---

## Change 2 — One Plot Per Filter Combination

**File:** `tools/loggereditor.py`

The stored series dict format is unchanged. All expansion is a rendering-time concern.

### New helper: `_iter_filter_combos(filters: list[dict])`

Module-level function. Takes the `filters` list from a series dict and yields one `dict[str, str]` (mapping `col → single_value`) per cartesian-product combination.

- If every filter has exactly one value selected, yields one item (existing single-series behaviour, no change to output).
- If any filter has zero values, that filter is skipped (no constraint on that column).
- Uses `itertools.product` over the per-filter value lists.

### Refactored: `_plot_ref_series(conn, s)`

Replaces the current single-query implementation:

```
combos = list(_iter_filter_combos(s.get("filters", [])))
is_multi = len(combos) > 1
for combo in combos:
    _plot_one_combo(conn, s, combo, is_multi)
```

### New private method: `_plot_one_combo(conn, s, combo, is_multi)`

Contains the current fetch → DataFrame → resample → normalise → scale → plot pipeline, adapted to:
- Receive a `combo: dict[str, str]` (one value per filter col) instead of the full filter list.
- Pass `combo` to `_build_ref_query` to generate single-equality WHERE clauses (`col = ?`).
- Apply the label rules below.

### Updated: `_build_ref_query(conn, s, combo)`

Adds an optional `combo: dict[str, str]` parameter. When provided, generates `col = ?` clauses instead of `col IN (…)`.

### Label logic (inside `_plot_one_combo`)

```python
combo_str = ", ".join(str(v) for v in combo.values())
user_label = s.get("label", "")
if is_multi:
    label = f"{user_label} ({combo_str})" if user_label else combo_str
else:
    label = user_label or _ref_series_auto_label(s)
```

| Combinations | User label set | Effective label |
|---|---|---|
| 1 | yes | `"My label"` |
| 1 | no | existing `_ref_series_auto_label(s)` → `"table.col [filter]"` |
| N | yes | `"My label (A, X)"` |
| N | no | `"A, X"` |

---

## Out of Scope

- No changes to the stored dict schema (`loggered_ref_series` JSON).
- No changes to the `from_dict` / `to_dict` round-trip.
- No changes to resample, normalise, scale, or style logic.
