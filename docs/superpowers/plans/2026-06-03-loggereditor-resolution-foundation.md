# Logger Editor — duplicate-resolution foundation (Plan 2a of Plan 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the logger-editor buffer a per-row identity (raw `date_time` text) so that *removing* a duplicate twin row can be persisted on Save and undone correctly — the foundation the resolve-duplicates UI (Plan 2b/2c) builds on.

**Architecture:** The buffer keeps its datetime index (for plotting) but additionally carries the original DB `date_time` string as a `date_time_raw` column. This is the table PK component `(obsid, date_time)`, so it is unique per row even when two rows share a normalized instant. `save_to_db` computes row *deletions* by raw-text set-difference (catching a dropped twin that a label/index diff misses) and deletes via exact `WHERE obsid=? AND date_time=?`. `_restore_from_history` reconstructs the buffer by raw-text identity instead of label `.loc`, so undo/redo no longer explode on duplicate labels.

**Tech Stack:** Python 3, pandas, PyQt/QGIS, SpatiaLite/PostgreSQL via the project DB abstraction; pytest.

This is Plan 2a (foundation) of the larger Plan 2. After it lands, Plan 2b adds classification + buffer resolution operations + metadata + plot-focus, and Plan 2c adds the banner + resolve dialog. Spec: `docs/superpowers/specs/2026-06-03-loggereditor-duplicate-datetime-resolution-design.md`. Builds on Plan 1 (`docs/superpowers/plans/2026-06-03-loggereditor-duplicate-safe-save.md`).

---

## Background the implementer must know

- `w_levels_logger` PRIMARY KEY is `(obsid, date_time)` on the **raw text**. Two "twin" rows at the same normalized instant therefore have **different** raw `date_time` strings (e.g. `'2024-01-05 00:00'` vs `'2024-01-05 00:00:00'`). Twins only exist in legacy DBs created before the `uq_w_levels_logger_obsid_dt` unique index; tests reproduce that by dropping the index (`_drop_dt_index()` in `test/test_loggereditor_dupes.py`).
- The buffer `self._buf` is a pandas DataFrame indexed by **parsed** datetime (`pd.to_datetime`), which collapses twins to one index label. Today it has columns: `head_cm_m`, `level_masl`, `source`, `series_id`, `dt_length`, and optionally `created_at`. The raw text is currently used only to build the index (`r[0]` in the load query) and is then discarded.
- Plan 1 made `save_to_db` *survive* twins by skipping duplicated instants from the diff (deduped local `buf`/`original_buf`). That guard stays; this plan adds the ability to *delete* a row that the user removed from the buffer.
- `_make_editor_with_buf` in `test/test_loggereditor_series.py` builds a buffer for tests; it must be taught to populate `date_time_raw`.

---

## File Structure

- Modify: `tools/loggereditor.py`
  - `load_obsid_and_init` buffer construction — add `date_time_raw` column (Task 1).
  - `save_to_db` — compute deletions by raw text; delete by exact raw text (Task 2).
  - `_history_push` / `_restore_from_history` — carry + restore by raw-text identity (Task 3).
- Modify: `test/test_loggereditor_series.py` — `_make_editor_with_buf` populates `date_time_raw` (Task 1).
- Test: `test/test_loggereditor_dupes.py` — new tests (all tasks). Reuse `_insert_obs_point`, `_insert_logger_row`, `_make_editor_with_buf`, `_drop_dt_index`, `_fetch_col`.

---

## Task 1: Carry raw `date_time` text in the buffer

**Files:**
- Modify: `tools/loggereditor.py` (buffer construction in `load_obsid_and_init`, the `cols_data`/`buf_df` block ~lines 912-942)
- Modify: `test/test_loggereditor_series.py` (`_make_editor_with_buf`)
- Test: `test/test_loggereditor_dupes.py`

- [ ] **Step 1: Write the failing test**

Add to `TestLoggerEditorDupes` in `test/test_loggereditor_dupes.py`:

```python
    def test_buffer_carries_raw_date_time_text(self):
        """The buffer keeps the original DB date_time text per row, distinct for twins."""
        _insert_obs_point("rb1")
        editor = _make_editor_with_buf(
            self.iface, self.midvatten.ms, obsid="rb1",
            dates=["2024-01-05 00:00", "2024-01-05 00:00:00", "2024-01-06 00:00:00"],
            head_values=[1.0, 1.0, 2.0],
            level_values=[10.0, 11.0, 20.0],
            series_ids=[None, None, None],
            sources=["", "", ""], series_buf={},
        )
        assert "date_time_raw" in editor._buf.columns
        assert editor._buf["date_time_raw"].tolist() == [
            "2024-01-05 00:00",
            "2024-01-05 00:00:00",
            "2024-01-06 00:00:00",
        ]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest test/test_loggereditor_dupes.py -k carries_raw -x`
Expected: FAIL — `_make_editor_with_buf` does not add `date_time_raw` (KeyError / assertion on missing column).

- [ ] **Step 3: Teach `_make_editor_with_buf` to populate `date_time_raw`**

In `test/test_loggereditor_series.py`, in `_make_editor_with_buf`, where `buf_df` is built, add a `date_time_raw` column equal to the original `dates` list (the raw strings), keeping the same row order as the index:

```python
    buf_df = pd.DataFrame(
        {
            "head_cm_m": head_values,
            "level_masl": level_values,
            "source": sources,
            "series_id": pd.array(series_ids, dtype="Int64"),
            "dt_length": [len(d) for d in dates],
            "date_time_raw": list(dates),
        },
        index=pd.to_datetime(dates, format="ISO8601"),
    )
```

- [ ] **Step 4: Run to verify the test passes**

Run: `python3 -m pytest test/test_loggereditor_dupes.py -k carries_raw -x`
Expected: PASS.

- [ ] **Step 5: Populate `date_time_raw` in the real load path**

In `tools/loggereditor.py`, in `load_obsid_and_init`, the block that builds `cols_data` and `buf_df` (the non-empty branch). The raw text is `r[0]` of each `head_level_masl_list` row. Add it as a column so the real editor matches the test buffer:

```python
                cols_data: dict = {
                    "head_cm_m": [r[1] for r in head_level_masl_list],
                    "level_masl": [r[2] for r in head_level_masl_list],
                    "source": [r[3] for r in head_level_masl_list],
                    "series_id": pd.array(
                        [r[4] for r in head_level_masl_list], dtype="Int64"
                    ),
                    "date_time_raw": [r[0] for r in head_level_masl_list],
                }
```

And in the empty-buffer branch, add `"date_time_raw"` to `buf_cols` so the empty DataFrame has the column too:

```python
                buf_cols = ["head_cm_m", "level_masl", "source", "series_id",
                            "date_time_raw"]
```
(keep the existing appends for `created_at`/`dt_length` after it).

- [ ] **Step 6: Run no-regression set**

Run: `python3 -m pytest test/test_loggereditor_dupes.py test/test_loggereditor_series.py test/test_loggereditor_separation.py test/test_loggereditor_refseries.py -x`
Expected: all PASS (new column is additive; nothing reads it yet).

- [ ] **Step 7: Lint and commit**

```bash
ruff check --fix tools/loggereditor.py test/test_loggereditor_dupes.py test/test_loggereditor_series.py
ruff format tools/loggereditor.py test/test_loggereditor_dupes.py test/test_loggereditor_series.py
git add tools/loggereditor.py test/test_loggereditor_dupes.py test/test_loggereditor_series.py
git commit -m "feat: carry raw date_time text in loggereditor buffer (date_time_raw)"
```

---

## Task 2: Persist a removed twin — delete by raw text on save

A resolution removes a row from `self._buf`. Today `save_to_db` derives deletions from `original_buf.index.difference(buf.index)` — a label set-difference that MISSES a dropped twin (the instant label still exists via the surviving twin). Fix: derive deletions from `date_time_raw` set-difference and delete by exact raw text.

**Files:**
- Modify: `tools/loggereditor.py` — `save_to_db` deletion computation + DELETE SQL
- Test: `test/test_loggereditor_dupes.py`

- [ ] **Step 1: Write the failing test**

```python
    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_save_persists_removed_twin(self, mock_messagebar):
        """Dropping one twin row from the buffer deletes exactly that DB row on save."""
        _insert_obs_point("rb1")
        _drop_dt_index()
        _insert_logger_row("rb1", "2024-01-05 00:00", 100.0, 10.0)
        _insert_logger_row("rb1", "2024-01-05 00:00:00", 100.0, 11.0)
        _insert_logger_row("rb1", "2024-01-06 00:00:00", 200.0, 20.0)

        editor = _make_editor_with_buf(
            self.iface, self.midvatten.ms, obsid="rb1",
            dates=["2024-01-05 00:00", "2024-01-05 00:00:00", "2024-01-06 00:00:00"],
            head_values=[1.0, 1.0, 2.0],
            level_values=[10.0, 11.0, 20.0],
            series_ids=[None, None, None],
            sources=["", "", ""], series_buf={},
        )
        # Resolve: drop the coarse twin (raw text "2024-01-05 00:00"), keep the precise one.
        editor._buf = editor._buf[editor._buf["date_time_raw"] != "2024-01-05 00:00"]

        result = editor.save_to_db()
        print(f"{mock_messagebar.mock_calls=}")
        assert result is True

        by_dt = _fetch_col("rb1", "level_masl")
        # The coarse twin row is gone; the precise twin and the clean row remain.
        assert "2024-01-05 00:00" not in by_dt
        assert by_dt["2024-01-05 00:00:00"] == 11.0
        assert by_dt["2024-01-06 00:00:00"] == 20.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest test/test_loggereditor_dupes.py -k persists_removed_twin -x`
Expected: FAIL — the coarse twin row still exists in the DB (deletion missed it), so `"2024-01-05 00:00" not in by_dt` fails (and/or the Plan-1 crash path returns and result is False).

- [ ] **Step 3: Compute deletions by raw text and delete by exact raw text**

In `save_to_db`, the deletion currently looks like:

```python
            deleted_indices = original_buf.index.difference(buf.index)
            delete_params = list(
                zip(
                    [obsid] * len(deleted_indices),
                    deleted_indices.strftime(_DT_FMT),
                )
            )
```

Replace it with raw-text set-difference over the **full** buffers (`self._original_buf`/`self._buf`, NOT the deduped `original_buf`/`buf`), so a dropped twin is caught:

```python
            orig_raw = self._original_buf["date_time_raw"]
            buf_raw = set(self._buf["date_time_raw"])
            deleted_raw = [r for r in orig_raw if r not in buf_raw]
            delete_params = [(obsid, raw) for raw in deleted_raw]
```

Then change the DELETE statement's WHERE to match the exact raw text instead of the normalized `dt_eq`. Find the delete block:

```python
                    if delete_params:
                        delete_sql = (
                            f"DELETE FROM {tbl} WHERE {ident('obsid')} = {ph}"
                            f" AND {dt_eq}"
                        )
                        dbconnection.executemany(delete_sql, delete_params)
```

and change `{dt_eq}` to an exact raw-text match:

```python
                    if delete_params:
                        delete_sql = (
                            f"DELETE FROM {tbl} WHERE {ident('obsid')} = {ph}"
                            f" AND {ident('date_time')} = {ph}"
                        )
                        dbconnection.executemany(delete_sql, delete_params)
```

Leave the UPDATE / series paths unchanged (they still operate on the deduped `buf`/`original_buf` from Plan 1's guard). Rationale: a resolved instant is no longer duplicated, so its kept row is present in the deduped view and updates normally; deletions now key on unique raw text and so target exactly the removed row(s) — including a dropped twin.

- [ ] **Step 4: Run the new test to verify it passes**

Run: `python3 -m pytest test/test_loggereditor_dupes.py -k persists_removed_twin -x`
Expected: PASS.

- [ ] **Step 5: Run no-regression set (delete path is exercised by existing tests)**

Run: `python3 -m pytest test/test_loggereditor_dupes.py test/test_loggereditor_series.py test/test_loggereditor_separation.py test/test_loggereditor_refseries.py -x`
Expected: all PASS. In particular the existing `test_save_does_not_range_over_skipped_twin` and `test_save_with_duplicate_instant_does_not_crash_or_corrupt` must still pass (twins NOT removed there → their raw texts are still in `buf` → not deleted).

- [ ] **Step 6: Lint and commit**

```bash
ruff check --fix tools/loggereditor.py test/test_loggereditor_dupes.py
ruff format tools/loggereditor.py test/test_loggereditor_dupes.py
git add tools/loggereditor.py test/test_loggereditor_dupes.py
git commit -m "fix: persist removed loggereditor rows by exact raw date_time text"
```

---

## Task 3: Duplicate-safe undo/redo

`_restore_from_history` rebuilds the buffer with `self._original_buf.loc[entry["present_index"]]`. With duplicate datetime labels this returns the wrong number of rows (each duplicated label matches multiple source rows). Carry the raw-text order in each history entry and restore by raw-text identity (unique).

**Files:**
- Modify: `tools/loggereditor.py` — `_history_push` (store `present_raw`), `_restore_from_history` (restore by raw text)
- Test: `test/test_loggereditor_dupes.py`

- [ ] **Step 1: Write the failing test**

```python
    def test_undo_redo_with_twins_present(self):
        """Editing then undo/redo must not corrupt a buffer that contains twins."""
        _insert_obs_point("rb1")
        editor = _make_editor_with_buf(
            self.iface, self.midvatten.ms, obsid="rb1",
            dates=["2024-01-05 00:00", "2024-01-05 00:00:00", "2024-01-06 00:00:00"],
            head_values=[1.0, 1.0, 2.0],
            level_values=[10.0, 11.0, 20.0],
            series_ids=[None, None, None],
            sources=["", "", ""], series_buf={},
        )
        # Edit the clean row and snapshot.
        editor._buf.loc[pd.Timestamp("2024-01-06 00:00:00"), "level_masl"] = 99.0
        editor._history_push("edit")
        assert len(editor._buf) == 3  # no row explosion from the twin label

        editor.undo()
        assert len(editor._buf) == 3
        assert editor._buf["date_time_raw"].tolist() == [
            "2024-01-05 00:00",
            "2024-01-05 00:00:00",
            "2024-01-06 00:00:00",
        ]
        # the edit was reverted
        assert editor._buf.loc[pd.Timestamp("2024-01-06 00:00:00"), "level_masl"] == 20.0

        editor.redo()
        assert len(editor._buf) == 3
        assert editor._buf.loc[pd.Timestamp("2024-01-06 00:00:00"), "level_masl"] == 99.0

    def test_undo_restores_removed_twin(self):
        """Undo after removing a twin brings the removed row back."""
        _insert_obs_point("rb1")
        editor = _make_editor_with_buf(
            self.iface, self.midvatten.ms, obsid="rb1",
            dates=["2024-01-05 00:00", "2024-01-05 00:00:00", "2024-01-06 00:00:00"],
            head_values=[1.0, 1.0, 2.0],
            level_values=[10.0, 11.0, 20.0],
            series_ids=[None, None, None],
            sources=["", "", ""], series_buf={},
        )
        editor._buf = editor._buf[editor._buf["date_time_raw"] != "2024-01-05 00:00"]
        editor._history_push("remove twin")
        assert len(editor._buf) == 2

        editor.undo()
        assert len(editor._buf) == 3
        assert "2024-01-05 00:00" in editor._buf["date_time_raw"].tolist()
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest test/test_loggereditor_dupes.py -k "undo_redo_with_twins or undo_restores_removed_twin" -x`
Expected: FAIL — the label `.loc` reconstruction explodes the row count (lengths != 3 / mismatch error) because the twin label `2024-01-05 00:00:00` matches two rows in `_original_buf`.

- [ ] **Step 3: Store raw-text identity in history snapshots**

In `_history_push`, add `present_raw` to the entry (the buffer's `date_time_raw` order):

```python
        entry = {
            "label": label,
            "timestamp": datetime.datetime.now(),
            "level_masl": self._buf["level_masl"].copy(),
            "present_index": self._buf.index.copy(),
            "present_raw": self._buf["date_time_raw"].tolist(),
            "series_id": self._buf["series_id"].copy(),
            "series_buf": {k: dict(v) for k, v in self._series_buf.items()},
            "source": (
                self._buf["source"].copy() if "source" in self._buf.columns else None
            ),
        }
```

- [ ] **Step 4: Restore by raw-text identity**

In `_restore_from_history`, replace the label-based reconstruction with a raw-text-keyed one. The raw text is unique in `_original_buf` (PK), so a raw-text lookup returns exactly one row per requested key, in order:

```python
    def _restore_from_history(self, pos: int) -> None:
        entry = self._history[pos]
        ob_by_raw = self._original_buf.set_index("date_time_raw", drop=False)
        present_raw = entry.get("present_raw")
        if present_raw is None:
            # Back-compat for snapshots taken before present_raw existed.
            self._buf = self._original_buf.loc[entry["present_index"]].copy()
        else:
            self._buf = ob_by_raw.loc[present_raw].copy()
            self._buf.index = entry["present_index"]
        self._buf["level_masl"] = entry["level_masl"].to_numpy()
        self._buf["series_id"] = entry["series_id"].to_numpy()
        if entry.get("source") is not None and "source" in self._buf.columns:
            self._buf["source"] = entry["source"].to_numpy()
        self._series_buf = {k: dict(v) for k, v in entry["series_buf"].items()}
        if hasattr(self, "_series_last_shown_id"):
            self._series_last_shown_id = None
        self._buf_version += 1
        self._dirty = pos != 0
        self._refresh_window_title()
        self._refresh_history_widget()
        self.update_plot()
```

Notes for the implementer:
- `ob_by_raw.loc[present_raw]` selects rows by unique raw text in the snapshot's order; `self._buf.index = entry["present_index"]` restores the datetime index (which may contain duplicate labels — that is fine as a stored value, we just don't *select* by it).
- The mutable columns (`level_masl`, `series_id`, `source`) are overlaid as position-aligned numpy arrays (`.to_numpy()`) to avoid pandas index-alignment on duplicate labels.

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `python3 -m pytest test/test_loggereditor_dupes.py -k "undo_redo_with_twins or undo_restores_removed_twin" -x`
Expected: PASS.

- [ ] **Step 6: Run the existing undo/redo + full logger-editor sets (no regressions)**

Run: `python3 -m pytest test/test_loggereditor_dupes.py test/test_loggereditor_series.py test/test_loggereditor_separation.py test/test_loggereditor_refseries.py test/test_wlevels_calc_calibr.py -m spatialite -x`
Expected: all PASS (the existing `test_undo_reverts_buffer`/`test_redo_after_undo` exercise the non-twin path through the new code).

- [ ] **Step 7: Lint and commit**

```bash
ruff check --fix tools/loggereditor.py test/test_loggereditor_dupes.py
ruff format tools/loggereditor.py test/test_loggereditor_dupes.py
git add tools/loggereditor.py test/test_loggereditor_dupes.py
git commit -m "fix: duplicate-safe loggereditor undo/redo via raw date_time identity"
```

---

## Self-Review

**Spec coverage (foundation slice of Plan 2):** The spec's resolution actions all remove rows from the buffer and rely on Save to persist + undo to revert. Task 1 adds the row identity; Task 2 makes removal persist; Task 3 makes removal undoable. Classification, the three resolution operations, metadata display, plot-focus, the banner, and the dialog are explicitly deferred to Plan 2b/2c (not in scope here).

**Placeholder scan:** none — every step has concrete code and commands.

**Type consistency:** `date_time_raw` is a `list[str]`/object column in both the test helper and the real load path. `present_raw` is `list[str]` in `_history_push` and consumed by `.loc[present_raw]` in `_restore_from_history`. Deletions use `(obsid, raw)` tuples matched by `WHERE obsid=? AND date_time=?`. `_fetch_col`, `_drop_dt_index`, `_insert_logger_row`, `_make_editor_with_buf` all already exist from Plan 1.

**Risk note:** Task 2 changes the DELETE WHERE from normalized (`dt_eq`) to exact raw text. This is correct because `date_time_raw` is the stored DB text, so exact match always hits. Existing non-twin delete tests (`test_delete_range` in `test_wlevels_calc_calibr.py`) must stay green — they delete rows whose raw text is in `original_buf` but not `buf`, which the new set-difference handles identically.
