# Logger Editor — duplicate-datetime detection, safe save, and resolution

**Date:** 2026-06-03
**Component:** `tools/loggereditor.py` (+ small load-query change), `w_levels_logger` / `w_logger_series`
**Status:** Design approved, pending spec review

## Problem

Saving in the Logger Editor crashes for obsids that contain two rows sharing the
same *normalized instant* (e.g. `Rb0403_L`):

```
CRITICAL  Save failed.
CRITICAL  Boolean index has wrong length: 94854 instead of 94853
```

### Root cause (confirmed)

`w_levels_logger` has `PRIMARY KEY (obsid, date_time)` on the **raw text**. A row
can therefore exist twice for the same instant when the raw `date_time` text
differs (e.g. `'2021-03-01 00:00'` vs `'2021-03-01 00:00:00'`). A separate
`UNIQUE INDEX (obsid, datetime(date_time))` forbids this, but older / manually
upgraded databases predate it, so the data exists in the wild.

The editor indexes the buffer by **parsed** datetime, which collapses both raw
texts to a single `DatetimeIndex` label. In `save_to_db`:

```python
common_index = self._original_buf.index.intersection(self._buf.index)  # dedups -> 94853
orig_vals = self._original_buf.loc[common_index, "level_masl"]          # .loc returns both -> 94854
new_vals  = self._buf.loc[common_index, "level_masl"]                   # -> 94854
changed_mask = ~((orig_vals == new_vals) | ...)                         # length 94854
changed_index = common_index[changed_mask]    # 94854-mask on 94853-index -> CRASH
```

Reproduced exactly: one duplicated index label makes `.loc[common_index]` one
row longer than the deduplicated `common_index`, so the boolean mask no longer
fits. The same pattern exists for the `series_id` update at the section near
`common = self._original_buf.index.intersection(self._buf.index)` further down.

### The deeper bug behind the crash

The save SQL targets rows by `WHERE obsid = ? AND datetime(date_time) = ?`
(normalized) with **no per-row discriminator**. So even if the crash were merely
silenced, any UPDATE/DELETE for a duplicated instant would hit **both** twin
rows. A diff-only fix would convert a safe crash into silent corruption of the
row the user did not edit. The crash and this latent corruption share one root
cause: **rows sharing a normalized instant are not uniquely addressable by the
save model.**

### Design decision (from the user)

Duplicate normalized instants for one obsid are **not wanted** — this is a
deliberate data-quality invariant (import-time hooks enforce it only
partially). Therefore the editor must **not** become fluent in editing
individual twins. Instead it must:

1. never crash on existing duplicates;
2. never silently overwrite/lose data;
3. **warn but not block** — a single bad instant must not stop the user from
   saving and showing fresh data to a customer;
4. help the user *clean* duplicates with good UX that scales from 3 to 10 000,
   never deleting silently and letting the user **compare alternatives** first.

## Approach

**Buffer-based resolution + a duplicate-safe save guard**, contained in
`loggereditor.py`, reusing the existing undo-history and save-on-Save model.

Rejected alternatives:

- *Direct DB deletes from the dialog* — bypass undo and the buffer, conflict
  with unsaved edits.
- *Per-twin raw-text addressing in save* — would make the editor support a state
  the project has decided to eliminate; wrong direction.
- *Import-time / migration only* — already tried ("worked half-well") and does
  not help the data the user is editing now. Worth hardening later; out of scope
  here.

Duplicates are removed before save in the normal path; the save guard makes save
safe even when the user chooses to leave duplicates in place.

## Components

### 1. Detection

- Duplicate set = repeated parsed-datetime index labels in `_buf`:
  `_buf.index.duplicated(keep=False)`. This equals "same normalized instant,
  different raw text", matching the DB `(obsid, datetime(date_time))` semantics.
- Runs after a buffer is loaded for an obsid.
- A small helper returns, per duplicated instant, the competing buffer rows
  (with their `_line_key`, `head_cm_m`, `level_masl`, `source`, row `comment`,
  `series_id`, `dt_length`, `created_at`).

### 2. Load banner (non-blocking)

- When duplicates exist, show a messagebar warning:
  `⚠ N duplicate timestamps for <obsid>` plus a `Resolve duplicates…` button.
- Never blocks plotting or saving. The existing "Separate by …" toggles stay in
  the right panel (not duplicated in the banner).

### 3. Resolve dialog — classification per duplicated instant

For each duplicated instant, classify by the competing rows:

- **① Redundant** — same source, equal `head_cm` *and* equal `level_masl`
  (null == null). Truly redundant twins.
  - Action: one button `Remove N redundant rows`. Keeps the **higher
    datetime-precision** row (longest `dt_length`; tie-break newest
    `created_at`), drops the coarser twin. No padding/rewriting — only a drop.
  - Shows a **preview sample** (kept vs deleted) before applying.
- **② Cross-source overlap** — twins differ by `source` (and/or `series_id`).
  - Shows the overlapping sources/series with their metadata
    (`source`, `instrument`, `description`, `comment`) and a value sample.
  - User picks which source/series to keep **at the overlapping instants**;
    deletes only the other source's rows **at those instants**. Each series
    keeps all its non-overlapping data — no whole-series deletion.
- **③ Same-source value conflict** — same source but `head_cm` or `level_masl`
  differ.
  - Per-instant table showing both rows' values + metadata; user picks the
    survivor.

Classification order per instant: differing source → ②; else all values equal →
①; else → ③.

### 4. Visual comparison on the main plot

The dialog drives the **existing** plot rather than only showing tables. When
the user inspects a bucket or a specific conflict, the tool:

- enables the relevant "Separate by …" toggle (datetime precision for ①/③,
  source for ②) so the twins draw as distinct lines;
- sets `selected_line_keys` to the competing lines;
- sets the from/to date range to the affected instants and calls `update_plot`.

Pure reuse of existing `selected_line_keys` + from/to date + `update_plot`
machinery. Lets the user eyeball the twins before deleting.

### 5. Metadata for decisions

- Row-level `comment` (`w_levels_logger.comment`) is shown for competing rows.
  The buffer load query must additionally `SELECT comment` **conditionally** on
  the column being present (multi-schema compatibility, like `created_at`).
- Series metadata (`source`, `instrument`, `description`, `comment`) comes from
  the already-loaded `_series_buf` for the `series_join` schema variant.

### 6. Save guard (warn, don't block)

- At the top of `save_to_db`, pre-filter any still-duplicated parsed-datetime
  instants out of the diff inputs (drop every row whose normalized instant is
  duplicated in `_buf`). The remaining rows have a unique index, so the existing
  diff/intersection/`_compute_update_statements` logic runs unchanged — no
  crash.
- Emit one warning listing the skipped instants (count + sample).
- Result: all edits on unique instants persist; duplicated instants are left
  untouched in the DB until the user resolves them. Edits made to a duplicated
  instant are not written (and the warning says so).

## Data flow

```
load obsid -> build _buf (parsed-datetime index)
           -> detect duplicates -> banner + enable Resolve button
Resolve dialog -> classify -> [preview / drive main plot] -> user action
           -> drop/keep rows in _buf -> _history_push (undoable) -> update_plot
Save -> save_to_db pre-filters remaining duplicate instants (warn)
     -> diff unique remainder -> write -> commit
```

All resolution edits are ordinary buffer mutations: undoable via existing
history, persisted only on Save.

## Error handling

- Save never raises on duplicates (guard + warning).
- Resolution never deletes without showing the competing rows first.
- No silent survivor pick in conflict buckets; bulk redundant removal shows a
  preview and uses the agreed precision rule.
- Dialog operates only on the in-memory buffer; closing it without Save loses
  nothing to the DB and is undoable in-session.

## Related minor fix (separate mechanism)

`getlastcalibration` does `self.lastcalibr[0]` on a possibly-empty list,
producing the log line `Getting last calibration failed for obsid Rb0403_L,
msg: list index out of range`. Guard the empty-list case to return `[]`.
Independent of the duplicate work; fixed in the same branch.

## Testing (failing tests first)

1. **Save no longer crashes on a duplicated instant** and leaves **both** DB
   rows intact (asserts the untouched twin's stored value is unchanged) — guards
   against both the crash and the silent-overwrite regression.
2. **Bulk-remove-redundant** drops the coarse twin, keeps the higher-precision
   row; DB after Save has one row per instant with the precise raw text.
3. **Cross-source resolution** removes only the non-kept source's rows at the
   overlapping instants; non-overlapping rows of both series remain.
4. **Same-source conflict** keeps exactly the chosen row.
5. **Detection** flags the right instants and none when data is clean.
6. **`getlastcalibration`** returns `[]` safely on empty input.

Backend coverage: SpatiaLite and PostgreSQL where the save path is exercised.

## Out of scope

- Hardening import-time duplicate prevention.
- A standalone DB migration to add the unique index to old databases.
- Editing individual twins as first-class entities.
