> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-06-03 · modified: 2026-06-03 · archived: 2026-07-31

# Logger Editor — duplicate-resolution logic (Plan 2b of Plan 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the buffer-level logic the resolve-duplicates UI will call: classify each duplicated instant (redundant / cross-source / conflict) and perform the corresponding row removals on the in-memory buffer (undoable, persisted on Save).

**Architecture:** Pure methods on `LoggerEditor` operating on `self._buf`. Classification reads the competing rows at each duplicated instant. Resolution operations drop the unwanted rows by their unique `date_time_raw` (added in Plan 2a) and push an undo snapshot — exactly how `delete_selected_range` already mutates the buffer. No UI in this plan.

**Tech Stack:** Python 3, pandas, PyQt/QGIS; pytest.

This is Plan 2b of Plan 2. Plan 2a (foundation: `date_time_raw`, persist-on-save, duplicate-safe undo) is merged. Plan 2c adds the load banner + resolve dialog + plot-focus + row-level `comment` display. Spec: `docs/superpowers/specs/2026-06-03-loggereditor-duplicate-datetime-resolution-design.md`.

---

## Background the implementer must know

- A "duplicated instant" is a parsed-datetime index label occurring more than once in `self._buf`. `LoggerEditor._duplicate_instants()` (from Plan 1) returns those labels as a `pd.DatetimeIndex`.
- Competing rows for an instant are obtained with `self._buf[self._buf.index == instant]` (the index has duplicate labels, so this returns >1 row). Each row has columns: `head_cm_m`, `level_masl`, `source` (str, "" when none), `series_id` (nullable Int64), `dt_length` (int), `date_time_raw` (str, UNIQUE per row), and optionally `created_at` (str).
- `date_time_raw` is unique per row (table PK), so removing specific rows is done by `self._buf = self._buf[~self._buf["date_time_raw"].isin(drop_raws)]`.
- `_history_push(label)` snapshots the buffer for undo (Plan 2a made it duplicate-safe). Resolution ops must call it after mutating `self._buf`, so the change is undoable and persisted on the next Save.
- Do NOT call `_recompute_line_keys()` in these ops: it reads `self.separate_*_cb` checkboxes that only exist after `show()`, and the unit tests build the editor via `_make_editor_with_buf` without `show()`. Line keys are recomputed by the normal plot refresh (`update_plot`) which the dialog (2c) will call.
- Test helpers in `test/test_loggereditor_dupes.py`: `_insert_obs_point`, `_make_editor_with_buf` (from test_loggereditor_series), `pd` imported.

---

## File Structure

- Modify: `tools/loggereditor.py` — add `_classify_duplicates`, `_drop_rows_by_raw`, `_remove_redundant_duplicates`, `_remove_cross_source_overlaps`, `_resolve_conflict_keep` (placed near `_duplicate_instants`).
- Test: `test/test_loggereditor_dupes.py` — new tests for all methods.

---

## Task 1: Classify duplicated instants

**Files:**
- Modify: `tools/loggereditor.py` (add `_classify_duplicates` near `_duplicate_instants`)
- Test: `test/test_loggereditor_dupes.py`

- [ ] **Step 1: Write the failing tests**

```python
    def _twin_editor(self, **overrides):
        """Editor with three duplicated instants: one redundant, one cross-source,
        one same-source conflict (plus a clean row)."""
        kwargs = dict(
            obsid="rb1",
            dates=[
                "2024-01-01 00:00", "2024-01-01 00:00:00",   # redundant (equal values, same source)
                "2024-01-02 00:00", "2024-01-02 00:00:00",   # cross-source (source a vs b)
                "2024-01-03 00:00", "2024-01-03 00:00:00",   # conflict (same source, diff level)
                "2024-01-04 00:00:00",                        # clean
            ],
            head_values=[1.0, 1.0, 2.0, 2.0, 3.0, 3.0, 4.0],
            level_values=[10.0, 10.0, 20.0, 21.0, 30.0, 31.0, 40.0],
            series_ids=[None, None, None, None, None, None, None],
            sources=["s", "s", "a", "b", "c", "c", ""],
            series_buf={},
        )
        kwargs.update(overrides)
        _insert_obs_point("rb1")
        return _make_editor_with_buf(self.iface, self.midvatten.ms, **kwargs)

    def test_classify_duplicates_kinds(self):
        editor = self._twin_editor()
        result = {g["instant"]: g for g in editor._classify_duplicates()}
        assert set(result) == {
            pd.Timestamp("2024-01-01 00:00:00"),
            pd.Timestamp("2024-01-02 00:00:00"),
            pd.Timestamp("2024-01-03 00:00:00"),
        }
        assert result[pd.Timestamp("2024-01-01 00:00:00")]["kind"] == "redundant"
        assert result[pd.Timestamp("2024-01-02 00:00:00")]["kind"] == "cross_source"
        assert result[pd.Timestamp("2024-01-03 00:00:00")]["kind"] == "conflict"

    def test_classify_duplicates_rows_payload(self):
        editor = self._twin_editor()
        groups = {g["instant"]: g for g in editor._classify_duplicates()}
        rows = groups[pd.Timestamp("2024-01-02 00:00:00")]["rows"]
        assert len(rows) == 2
        assert {r["source"] for r in rows} == {"a", "b"}
        assert {r["date_time_raw"] for r in rows} == {
            "2024-01-02 00:00",
            "2024-01-02 00:00:00",
        }
        # each row dict exposes the fields the dialog needs
        for r in rows:
            assert set(r) >= {
                "date_time_raw", "head_cm_m", "level_masl",
                "source", "series_id", "dt_length",
            }
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest test/test_loggereditor_dupes.py -k classify_duplicates -x`
Expected: FAIL with `AttributeError: ... '_classify_duplicates'`.

- [ ] **Step 3: Implement `_classify_duplicates`**

Add to `LoggerEditor` (near `_duplicate_instants`):

```python
    @staticmethod
    def _values_all_equal(values: list) -> bool:
        """True if all values are equal, treating NaN/NA as equal to NaN/NA."""
        first = values[0]
        for v in values[1:]:
            both_na = pd.isna(first) and pd.isna(v)
            if not both_na and v != first:
                return False
        return True

    def _classify_duplicates(self) -> list[dict]:
        """Classify each duplicated instant in _buf.

        Returns a list of dicts: {"instant": Timestamp, "kind": str,
        "rows": [row-dict, ...]}, where kind is one of:
          - "cross_source": the competing rows come from >1 distinct source
          - "redundant":    same source and equal head_cm_m AND level_masl
          - "conflict":     same source but head_cm_m or level_masl differ
        """
        if self._buf is None:
            return []
        row_cols = ["date_time_raw", "head_cm_m", "level_masl", "source", "dt_length"]
        groups = []
        for instant in self._duplicate_instants():
            sub = self._buf[self._buf.index == instant]
            rows = []
            for _, r in sub.iterrows():
                row = {c: r[c] for c in row_cols}
                row["series_id"] = (
                    None if pd.isna(r["series_id"]) else int(r["series_id"])
                )
                if "created_at" in sub.columns:
                    row["created_at"] = r["created_at"]
                rows.append(row)
            sources = {r["source"] for r in rows}
            if len(sources) > 1:
                kind = "cross_source"
            elif self._values_all_equal(
                [r["head_cm_m"] for r in rows]
            ) and self._values_all_equal([r["level_masl"] for r in rows]):
                kind = "redundant"
            else:
                kind = "conflict"
            groups.append({"instant": instant, "kind": kind, "rows": rows})
        return groups
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest test/test_loggereditor_dupes.py -k classify_duplicates -x`
Expected: PASS.

- [ ] **Step 5: No-regression + lint + commit**

```bash
python3 -m pytest test/test_loggereditor_dupes.py -x
ruff check --fix tools/loggereditor.py test/test_loggereditor_dupes.py
ruff format tools/loggereditor.py test/test_loggereditor_dupes.py
git add tools/loggereditor.py test/test_loggereditor_dupes.py
git commit -m "feat: classify duplicated instants in loggereditor (redundant/cross-source/conflict)"
```

---

## Task 2: Buffer resolution operations

**Files:**
- Modify: `tools/loggereditor.py` (add `_drop_rows_by_raw`, `_remove_redundant_duplicates`, `_remove_cross_source_overlaps`, `_resolve_conflict_keep`)
- Test: `test/test_loggereditor_dupes.py`

- [ ] **Step 1: Write the failing tests**

```python
    def test_remove_redundant_duplicates_keeps_higher_precision(self):
        editor = self._twin_editor()
        n = editor._remove_redundant_duplicates()
        assert n == 1  # one coarse twin dropped at the redundant instant
        # The redundant instant now has exactly the higher-precision row.
        sub = editor._buf[editor._buf.index == pd.Timestamp("2024-01-01 00:00:00")]
        assert sub["date_time_raw"].tolist() == ["2024-01-01 00:00:00"]
        # cross-source and conflict instants are untouched.
        assert len(editor._buf[editor._buf.index == pd.Timestamp("2024-01-02 00:00:00")]) == 2
        assert len(editor._buf[editor._buf.index == pd.Timestamp("2024-01-03 00:00:00")]) == 2
        assert editor._dirty is True

    def test_remove_cross_source_overlaps_keeps_chosen_source(self):
        editor = self._twin_editor()
        n = editor._remove_cross_source_overlaps("a")
        assert n == 1  # the source-"b" row at the cross-source instant dropped
        sub = editor._buf[editor._buf.index == pd.Timestamp("2024-01-02 00:00:00")]
        assert sub["source"].tolist() == ["a"]
        # redundant/conflict instants untouched.
        assert len(editor._buf[editor._buf.index == pd.Timestamp("2024-01-01 00:00:00")]) == 2

    def test_resolve_conflict_keep(self):
        editor = self._twin_editor()
        editor._resolve_conflict_keep(
            pd.Timestamp("2024-01-03 00:00:00"), "2024-01-03 00:00:00"
        )
        sub = editor._buf[editor._buf.index == pd.Timestamp("2024-01-03 00:00:00")]
        assert sub["date_time_raw"].tolist() == ["2024-01-03 00:00:00"]
        assert sub["level_masl"].tolist() == [31.0]

    def test_resolution_is_undoable(self):
        editor = self._twin_editor()
        before = len(editor._buf)
        editor._remove_redundant_duplicates()
        assert len(editor._buf) == before - 1
        editor.undo()
        assert len(editor._buf) == before
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest test/test_loggereditor_dupes.py -k "redundant_duplicates_keeps or cross_source_overlaps or resolve_conflict_keep or resolution_is_undoable" -x`
Expected: FAIL with `AttributeError` on the new methods.

- [ ] **Step 3: Implement the operations**

Add to `LoggerEditor`:

```python
    def _drop_rows_by_raw(self, drop_raws: set, label: str) -> None:
        """Drop buffer rows whose date_time_raw is in drop_raws; snapshot for undo.

        date_time_raw is unique per row, so this removes exactly the chosen rows.
        Line keys are recomputed by the next plot refresh, not here (this method
        is callable without show())."""
        if not drop_raws:
            return
        self._buf = self._buf[~self._buf["date_time_raw"].isin(drop_raws)]
        self._history_push(label)

    def _remove_redundant_duplicates(self) -> int:
        """Drop coarse twins at every 'redundant' instant, keeping the row with
        the highest datetime precision (longest dt_length; tie-break newest
        created_at when available). Returns the number of rows removed."""
        drop_raws = set()
        for grp in self._classify_duplicates():
            if grp["kind"] != "redundant":
                continue
            keep = max(
                grp["rows"],
                key=lambda r: (r["dt_length"], r.get("created_at", "")),
            )
            for r in grp["rows"]:
                if r["date_time_raw"] != keep["date_time_raw"]:
                    drop_raws.add(r["date_time_raw"])
        self._drop_rows_by_raw(drop_raws, "Remove redundant duplicates")
        return len(drop_raws)

    def _remove_cross_source_overlaps(self, keep_source: str) -> int:
        """At every 'cross_source' instant where keep_source is present, drop the
        rows from the other sources. Instants without keep_source are left
        untouched (never emptied). Returns the number of rows removed."""
        drop_raws = set()
        for grp in self._classify_duplicates():
            if grp["kind"] != "cross_source":
                continue
            sources_here = {r["source"] for r in grp["rows"]}
            if keep_source not in sources_here:
                continue
            for r in grp["rows"]:
                if r["source"] != keep_source:
                    drop_raws.add(r["date_time_raw"])
        self._drop_rows_by_raw(drop_raws, "Remove cross-source overlaps")
        return len(drop_raws)

    def _resolve_conflict_keep(self, instant: pd.Timestamp, keep_raw: str) -> int:
        """At a single duplicated instant, keep the row whose date_time_raw is
        keep_raw and drop the others. Returns the number of rows removed."""
        sub = self._buf[self._buf.index == instant]
        drop_raws = {
            r for r in sub["date_time_raw"].tolist() if r != keep_raw
        }
        self._drop_rows_by_raw(drop_raws, "Resolve duplicate conflict")
        return len(drop_raws)
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest test/test_loggereditor_dupes.py -k "redundant_duplicates_keeps or cross_source_overlaps or resolve_conflict_keep or resolution_is_undoable" -x`
Expected: PASS.

- [ ] **Step 5: No-regression + lint + commit**

```bash
python3 -m pytest test/test_loggereditor_dupes.py test/test_loggereditor_series.py test/test_loggereditor_separation.py -x
ruff check --fix tools/loggereditor.py test/test_loggereditor_dupes.py
ruff format tools/loggereditor.py test/test_loggereditor_dupes.py
git add tools/loggereditor.py test/test_loggereditor_dupes.py
git commit -m "feat: buffer resolution ops for duplicate instants (redundant/cross-source/conflict)"
```

---

## Self-Review

**Spec coverage (logic slice):** classification into the three buckets (Task 1) and the three resolution operations — bulk-remove-redundant keeping higher precision, cross-source overlap removal keeping a chosen source, per-instant conflict keep (Task 2). All undoable via `_history_push` and persisted by Plan 2a's save. Deferred to Plan 2c: row-level `comment` loading/display, the plot-focus helper, the load banner, and the resolve dialog.

**Placeholder scan:** none — every step has concrete code and commands.

**Type consistency:** `_classify_duplicates` returns `list[dict]` with keys `instant` (Timestamp), `kind` (str), `rows` (list of dicts with `date_time_raw`/`head_cm_m`/`level_masl`/`source`/`series_id`/`dt_length`/optional `created_at`). `_remove_redundant_duplicates`/`_remove_cross_source_overlaps`/`_resolve_conflict_keep` return `int` and all funnel through `_drop_rows_by_raw(set, str)`. `_values_all_equal` is a staticmethod used only inside `_classify_duplicates`. The `_twin_editor` test helper is defined once in the test class and reused by both tasks.

**Edge note:** `_remove_cross_source_overlaps` deliberately skips instants where `keep_source` is absent (never empties an instant) — matches the spec's "delete only the overlapping rows of the non-kept source." The dialog (2c) will only offer sources actually present.
