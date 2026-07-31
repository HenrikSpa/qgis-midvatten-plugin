> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-06-04 · modified: 2026-06-04 · archived: 2026-07-31

# Logger Editor — period-scoped duplicate resolution + run marker (Plan 2d) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user resolve duplicate timestamps period-by-period (the right source can differ per period) from a non-modal, always-above-the-editor dialog that re-scopes live to the editor's From/To, with a red "duplicates here" run-marker on the plot that shrinks as periods are cleaned.

**Architecture:** Make `_classify_duplicates` + the two bulk ops range-aware (`fr`/`to`, default = full). Add `_duplicate_runs()` (contiguous duplicate runs) and draw them as red segments at the plot bottom in `update_plot`. Make `ResolveDuplicatesDialog` a non-modal `Qt.Tool` window that reads the editor's From/To, passes the window to every op, shows scope + counts, has a "Whole dataset" button, and rebuilds when From/To changes. The editor opens it non-modally, reuses a single instance, and closes it on obsid change.

**Tech Stack:** Python 3, pandas, PyQt/QGIS, matplotlib; pytest (show()-based integration for widgets/marker).

Builds on Plan 2a/2b/2c (merged). Spec: `docs/superpowers/specs/2026-06-04-loggereditor-period-scoped-resolution-design.md`.

---

## Background the implementer must know

- Current signatures (in `tools/loggereditor.py`): `_classify_duplicates(self)`, `_remove_redundant_duplicates(self)`, `_remove_cross_source_overlaps(self, keep_source)`, `_duplicate_instants(self)`, `update_plot(self)` (ends by calling `self._refresh_dupe_banner()`), `_on_obsid_changed(self, new_index)`, `_open_resolve_dupes_dialog(self)` (currently modal `exec_`).
- The dialog (`tools/loggereditor_resolve_dupes.py`) takes an `editor`, has `_groups()`, `_bucket_counts(groups=None)`, `_cross_source_values(groups=None)`, `_on_remove_redundant()`, `_on_keep_source(src)`, `_on_show_instants(instants)`, `_after_change()`, `_rebuild()`, and a `_show_on_plot_button(kind)` helper.
- Editor date widgets: `self.from_date_time` / `self.to_date_time` (`QDateTimeEdit`); read with `.dateTime().toPyDateTime()`. They exist after `__init__` (setupUi), even without `show()`.
- `_make_editor_with_buf` (in `test/test_loggereditor_series.py`) builds an editor + buffer without `show()`. `show()`-based tests live in `test/test_loggereditor_resolve_ui.py` (helper `_setup_twin_obsid`, uses `gui_utils.set_combobox`). `_drop_dt_index` / `_twin_editor` are in `test/test_loggereditor_dupes.py`.
- matplotlib: `num2date` is already imported in loggereditor.py; `date2num` is NOT — add it. Blended transform: `from matplotlib.transforms import blended_transform_factory`.

---

## File Structure

- Modify `tools/loggereditor.py`: range params on classify+ops; `_duplicate_runs`, `_full_buffer_range`, `_draw_duplicate_marker` (called in `update_plot`); non-modal opener + obsid-change close.
- Modify `tools/loggereditor_resolve_dupes.py`: `Qt.Tool` flag; range reading; header label; "Whole dataset" button; reactive rebuild on From/To change + disconnect on close.
- Tests: `test/test_loggereditor_dupes.py` (range logic, runs) and `test/test_loggereditor_resolve_ui.py` (marker + all widget clicks + stay-open flow + lifecycle).

---

## Task 1: Range-aware classification and bulk ops

**Files:** Modify `tools/loggereditor.py`; Test `test/test_loggereditor_dupes.py`

- [ ] **Step 1: Write the failing tests**

Add to class `TestLoggerEditorDupes` (uses `_make_editor_with_buf`, `pd`):

```python
    def _two_period_editor(self):
        """Cross-source twins in two periods: Jan (a vs b) and Jun (a vs b)."""
        _insert_obs_point("rb1")
        return _make_editor_with_buf(
            self.iface, self.midvatten.ms, obsid="rb1",
            dates=[
                "2024-01-10 00:00", "2024-01-10 00:00:00",
                "2024-06-10 00:00", "2024-06-10 00:00:00",
            ],
            head_values=[1.0, 1.0, 2.0, 2.0],
            level_values=[10.0, 11.0, 20.0, 21.0],
            series_ids=[None, None, None, None],
            sources=["a", "b", "a", "b"],
            series_buf={},
        )

    def test_classify_duplicates_respects_range(self):
        editor = self._two_period_editor()
        jan = editor._classify_duplicates(
            pd.Timestamp("2024-01-01"), pd.Timestamp("2024-02-01")
        )
        assert [g["instant"] for g in jan] == [pd.Timestamp("2024-01-10 00:00:00")]
        allg = editor._classify_duplicates()
        assert len(allg) == 2  # default = full range, unchanged

    def test_cross_source_keep_is_per_period(self):
        editor = self._two_period_editor()
        # Keep 'a' in Jan only
        editor._remove_cross_source_overlaps(
            "a", pd.Timestamp("2024-01-01"), pd.Timestamp("2024-02-01")
        )
        jan = editor._buf[editor._buf.index == pd.Timestamp("2024-01-10 00:00:00")]
        assert jan["source"].tolist() == ["a"]
        # Jun still has both sources (untouched by the Jan-scoped call)
        jun = editor._buf[editor._buf.index == pd.Timestamp("2024-06-10 00:00:00")]
        assert sorted(jun["source"].tolist()) == ["a", "b"]
        # Now keep 'b' in Jun
        editor._remove_cross_source_overlaps(
            "b", pd.Timestamp("2024-06-01"), pd.Timestamp("2024-07-01")
        )
        jun = editor._buf[editor._buf.index == pd.Timestamp("2024-06-10 00:00:00")]
        assert jun["source"].tolist() == ["b"]

    def test_remove_redundant_respects_range(self):
        _insert_obs_point("rb1")
        editor = _make_editor_with_buf(
            self.iface, self.midvatten.ms, obsid="rb1",
            dates=[
                "2024-01-10 00:00", "2024-01-10 00:00:00",
                "2024-06-10 00:00", "2024-06-10 00:00:00",
            ],
            head_values=[1.0, 1.0, 2.0, 2.0],
            level_values=[10.0, 10.0, 20.0, 20.0],
            series_ids=[None, None, None, None],
            sources=["", "", "", ""], series_buf={},
        )
        n = editor._remove_redundant_duplicates(
            pd.Timestamp("2024-01-01"), pd.Timestamp("2024-02-01")
        )
        assert n == 1  # only the Jan redundant twin removed
        assert len(editor._buf[editor._buf.index == pd.Timestamp("2024-06-10 00:00:00")]) == 2
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest test/test_loggereditor_dupes.py -k "respects_range or per_period" -x`
Expected: FAIL — the methods take no `fr`/`to` (TypeError).

- [ ] **Step 3: Add `fr`/`to` to `_classify_duplicates`**

Change the signature and add the window filter right after the `dup` is computed:

```python
    def _classify_duplicates(self, fr=None, to=None) -> list[dict]:
```

After `dup = self._buf[self._buf.index.duplicated(keep=False)]` and its `if dup.empty: return []`, insert:

```python
        if fr is not None:
            dup = dup[dup.index >= fr]
        if to is not None:
            dup = dup[dup.index <= to]
        if dup.empty:
            return []
```

Update the docstring's first line to note the optional window.

- [ ] **Step 4: Thread `fr`/`to` through the two ops**

```python
    def _remove_redundant_duplicates(self, fr=None, to=None) -> int:
        ...
        for grp in self._classify_duplicates(fr, to):
        ...

    def _remove_cross_source_overlaps(self, keep_source: str, fr=None, to=None) -> int:
        ...
        for grp in self._classify_duplicates(fr, to):
        ...
```

(Only the `_classify_duplicates()` calls inside each op change to `_classify_duplicates(fr, to)`; everything else stays.)

- [ ] **Step 5: Run to verify they pass**

Run: `python3 -m pytest test/test_loggereditor_dupes.py -k "respects_range or per_period" -x`
Expected: PASS.

- [ ] **Step 6: No-regression, lint, commit**

```bash
python3 -m pytest test/test_loggereditor_dupes.py -x
ruff check --fix tools/loggereditor.py test/test_loggereditor_dupes.py
ruff format tools/loggereditor.py test/test_loggereditor_dupes.py
git add tools/loggereditor.py test/test_loggereditor_dupes.py
git commit -m "feat: range-aware duplicate classification and bulk resolution ops"
```

---

## Task 2: `_duplicate_runs` and `_full_buffer_range`

**Files:** Modify `tools/loggereditor.py`; Test `test/test_loggereditor_dupes.py`

- [ ] **Step 1: Write the failing tests**

```python
    def test_duplicate_runs_merges_contiguous(self):
        _insert_obs_point("rb1")
        # Two adjacent duplicated instants form ONE run; a clean instant splits;
        # then another duplicated instant is a second run.
        editor = _make_editor_with_buf(
            self.iface, self.midvatten.ms, obsid="rb1",
            dates=[
                "2024-01-01 00:00", "2024-01-01 00:00:00",   # dup instant A
                "2024-01-02 00:00", "2024-01-02 00:00:00",   # dup instant B (adjacent to A -> same run)
                "2024-01-03 00:00:00",                        # clean -> splits
                "2024-01-04 00:00", "2024-01-04 00:00:00",   # dup instant C -> second run
            ],
            head_values=[1.0, 1.0, 2.0, 2.0, 3.0, 4.0, 4.0],
            level_values=[1.0, 1.0, 2.0, 2.0, 3.0, 4.0, 4.0],
            series_ids=[None] * 7, sources=[""] * 7, series_buf={},
        )
        runs = editor._duplicate_runs()
        assert runs == [
            (pd.Timestamp("2024-01-01 00:00:00"), pd.Timestamp("2024-01-02 00:00:00")),
            (pd.Timestamp("2024-01-04 00:00:00"), pd.Timestamp("2024-01-04 00:00:00")),
        ]

    def test_full_buffer_range(self):
        _insert_obs_point("rb1")
        editor = _make_editor_with_buf(
            self.iface, self.midvatten.ms, obsid="rb1",
            dates=["2024-01-01 00:00:00", "2024-03-01 00:00:00"],
            head_values=[1.0, 2.0], level_values=[1.0, 2.0],
            series_ids=[None, None], sources=["", ""], series_buf={},
        )
        assert editor._full_buffer_range() == (
            pd.Timestamp("2024-01-01 00:00:00"),
            pd.Timestamp("2024-03-01 00:00:00"),
        )
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest test/test_loggereditor_dupes.py -k "duplicate_runs or full_buffer_range" -x`
Expected: FAIL — methods missing.

- [ ] **Step 3: Implement both helpers**

Add near `_duplicate_instants`:

```python
    def _full_buffer_range(self) -> tuple:
        """(min, max) timestamp of the buffer index, or (None, None) if empty."""
        if self._buf is None or self._buf.empty:
            return (None, None)
        idx = self._buf.index
        return (idx.min(), idx.max())

    def _duplicate_runs(self) -> list:
        """Maximal runs of duplicated instants that are consecutive in the
        buffer's sorted distinct instants. Returns [(start_ts, end_ts), ...].
        A run breaks where a non-duplicated instant interrupts it. Scale-safe:
        an overlap of thousands of rows collapses to one run."""
        if self._buf is None or self._buf.empty:
            return []
        distinct = self._buf.index.unique().sort_values()
        dup_set = set(self._duplicate_instants())
        runs = []
        run_start = None
        prev = None
        for ts in distinct:
            if ts in dup_set:
                if run_start is None:
                    run_start = ts
                prev = ts
            else:
                if run_start is not None:
                    runs.append((run_start, prev))
                    run_start = None
        if run_start is not None:
            runs.append((run_start, prev))
        return runs
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest test/test_loggereditor_dupes.py -k "duplicate_runs or full_buffer_range" -x`
Expected: PASS.

- [ ] **Step 5: Lint, commit**

```bash
ruff check --fix tools/loggereditor.py test/test_loggereditor_dupes.py
ruff format tools/loggereditor.py test/test_loggereditor_dupes.py
git add tools/loggereditor.py test/test_loggereditor_dupes.py
git commit -m "feat: _duplicate_runs and _full_buffer_range helpers"
```

---

## Task 3: Red duplicate-run marker on the plot

**Files:** Modify `tools/loggereditor.py`; Test `test/test_loggereditor_resolve_ui.py`

- [ ] **Step 1: Write the failing test**

Append to class `TestResolveUiSpatialite`:

```python
    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_duplicate_marker_drawn_and_shrinks(self, mock_messagebar):
        _setup_twin_obsid()  # rb1: one duplicated instant at 2024-01-01 + a clean row
        editor = LoggerEditor(self.iface, self.midvatten.ms)
        editor.show()
        gui_utils.set_combobox(editor.combobox_obsid, "rb1")
        editor.update_plot()
        print(f"{mock_messagebar.mock_calls=}")
        assert len(editor._dupe_marker_artists) == 1  # one run

        # remove the duplicate, redraw -> marker gone
        editor._buf = editor._buf[editor._buf["date_time_raw"] != "2024-01-01 00:00"]
        editor.update_plot()
        assert editor._dupe_marker_artists == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest test/test_loggereditor_resolve_ui.py -k duplicate_marker -x`
Expected: FAIL — no `_dupe_marker_artists`.

- [ ] **Step 3: Add the import and the marker method**

At the top of `tools/loggereditor.py`, add to the matplotlib imports: `from matplotlib.dates import date2num` (next to the existing `num2date` import) and `from matplotlib.transforms import blended_transform_factory`.

In `__init__`, initialize `self._dupe_marker_artists: list = []`.

Add the method:

```python
    def _draw_duplicate_marker(self) -> None:
        """Draw red segments along the axes bottom, one per duplicate run, so the
        user sees where duplicates remain. Recomputed on every redraw, so it
        shrinks as periods are resolved."""
        self._dupe_marker_artists = []
        if self._buf is None:
            return
        runs = self._duplicate_runs()
        if not runs:
            return
        trans = blended_transform_factory(self.axes.transData, self.axes.transAxes)
        for start, end in runs:
            (line,) = self.axes.plot(
                [date2num(start), date2num(end)],
                [0.02, 0.02],
                transform=trans,
                color="red",
                linewidth=3,
                marker="|",
                markersize=8,
                solid_capstyle="butt",
                clip_on=False,
                zorder=5,
            )
            self._dupe_marker_artists.append(line)
```

- [ ] **Step 4: Call it in `update_plot`**

In `update_plot`, immediately before the final `self._refresh_dupe_banner()` call, add `self._draw_duplicate_marker()`. (Both run only when a buffer is loaded; `update_plot` already returns early when `obsid is None`, before any drawing.)

Because `update_plot` does `self.axes.clear()` near its start, stale marker artists from the previous redraw are already removed from the axes; resetting `self._dupe_marker_artists = []` at the top of `_draw_duplicate_marker` keeps the tracking list in sync.

- [ ] **Step 5: Run to verify it passes**

Run: `python3 -m pytest test/test_loggereditor_resolve_ui.py -k duplicate_marker -x`
Expected: PASS.

- [ ] **Step 6: No-regression, lint, commit**

```bash
python3 -m pytest test/test_loggereditor_resolve_ui.py test/test_loggereditor_dupes.py -x
ruff check --fix tools/loggereditor.py test/test_loggereditor_resolve_ui.py
ruff format tools/loggereditor.py test/test_loggereditor_resolve_ui.py
git add tools/loggereditor.py test/test_loggereditor_resolve_ui.py
git commit -m "feat: red duplicate-run marker on the logger plot"
```

---

## Task 4: Non-modal, on-top, period-scoped reactive dialog

**Files:** Modify `tools/loggereditor_resolve_dupes.py`, `tools/loggereditor.py`; Test `test/test_loggereditor_resolve_ui.py`

- [ ] **Step 1: Write the failing tests**

Append to `test/test_loggereditor_resolve_ui.py`. Add helper at top of the file (module level, after `_setup_twin_obsid`):

```python
def _setup_two_period_obsid():
    db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('rb1')")
    _drop_dt_index()
    db_utils.sql_alter_db(
        "INSERT INTO w_logger_series (obsid, source) VALUES ('rb1','a'),('rb1','b')"
    )
    rows = db_utils.sql_load_fr_db(
        "SELECT id, source FROM w_logger_series WHERE obsid='rb1' ORDER BY id"
    )[1]
    sid = {src: i for i, src in rows}
    db_utils.sql_alter_db(
        "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl, series_id)"
        f" VALUES ('rb1','2024-01-10 00:00',1,10.0,{sid['a']}),"
        f" ('rb1','2024-01-10 00:00:00',1,11.0,{sid['b']}),"
        f" ('rb1','2024-06-10 00:00',2,20.0,{sid['a']}),"
        f" ('rb1','2024-06-10 00:00:00',2,21.0,{sid['b']})"
    )
```

Tests (in `TestResolveUiSpatialite`):

```python
    def _open_dialog(self, editor):
        from qgis.PyQt.QtWidgets import QPushButton

        # full range so the dialog sees all duplicates initially
        fr, to = editor._full_buffer_range()
        editor.from_date_time.setDateTime(fr)
        editor.to_date_time.setDateTime(to)
        editor._resolve_dupes_btn.click()
        return editor._resolve_dialog

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_banner_button_opens_nonmodal_tool_dialog(self, mock_messagebar):
        from qgis.PyQt.QtCore import Qt

        _setup_twin_obsid()
        editor = LoggerEditor(self.iface, self.midvatten.ms)
        editor.show()
        gui_utils.set_combobox(editor.combobox_obsid, "rb1")
        editor.update_plot()
        editor._resolve_dupes_btn.click()
        dlg = editor._resolve_dialog
        assert dlg is not None
        assert dlg.isVisible() is True
        assert (dlg.windowFlags() & Qt.Tool) == Qt.Tool
        assert dlg.parent() is editor
        # clicking again reuses the same instance
        editor._resolve_dupes_btn.click()
        assert editor._resolve_dialog is dlg

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_dialog_stay_open_resolves_two_periods(self, mock_messagebar):
        from qgis.PyQt.QtWidgets import QPushButton

        _setup_two_period_obsid()
        editor = LoggerEditor(self.iface, self.midvatten.ms)
        editor.show()
        gui_utils.set_combobox(editor.combobox_obsid, "rb1")
        editor.update_plot()
        dlg = self._open_dialog(editor)

        def keep_button(src):
            for b in dlg.findChildren(QPushButton):
                if b.text() == ("Keep '%s'" % src):
                    return b
            return None

        # Period A (Jan): keep 'a'
        editor.from_date_time.setDateTime(pd.Timestamp("2024-01-01"))
        editor.to_date_time.setDateTime(pd.Timestamp("2024-02-01"))
        keep_button("a").click()  # dialog still open, scoped to Jan
        # Period B (Jun): keep 'b' — SAME dialog instance
        assert editor._resolve_dialog is dlg
        editor.from_date_time.setDateTime(pd.Timestamp("2024-06-01"))
        editor.to_date_time.setDateTime(pd.Timestamp("2024-07-01"))
        keep_button("b").click()

        print(f"{mock_messagebar.mock_calls=}")
        jan = editor._buf[editor._buf.index == pd.Timestamp("2024-01-10 00:00:00")]
        jun = editor._buf[editor._buf.index == pd.Timestamp("2024-06-10 00:00:00")]
        assert jan["source"].tolist() == ["a"]
        assert jun["source"].tolist() == ["b"]

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_whole_dataset_button_widens_scope(self, mock_messagebar):
        from qgis.PyQt.QtWidgets import QPushButton

        _setup_two_period_obsid()
        editor = LoggerEditor(self.iface, self.midvatten.ms)
        editor.show()
        gui_utils.set_combobox(editor.combobox_obsid, "rb1")
        editor.update_plot()
        # open scoped to Jan only
        editor.from_date_time.setDateTime(pd.Timestamp("2024-01-01"))
        editor.to_date_time.setDateTime(pd.Timestamp("2024-02-01"))
        editor._resolve_dupes_btn.click()
        dlg = editor._resolve_dialog
        assert len(dlg._groups()) == 1  # only Jan in scope
        for b in dlg.findChildren(QPushButton):
            if b.text() == "Whole dataset":
                b.click()
                break
        assert len(dlg._groups()) == 2  # both periods now in scope

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_changing_obsid_closes_dialog(self, mock_messagebar):
        _setup_twin_obsid()
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('clean1')")
        db_utils.sql_alter_db(
            "INSERT INTO w_levels_logger (obsid, date_time, head_cm, level_masl)"
            " VALUES ('clean1','2024-03-01 00:00:00',1,1.0)"
        )
        editor = LoggerEditor(self.iface, self.midvatten.ms)
        editor.show()
        gui_utils.set_combobox(editor.combobox_obsid, "rb1")
        editor.update_plot()
        editor._resolve_dupes_btn.click()
        assert editor._resolve_dialog is not None
        gui_utils.set_combobox(editor.combobox_obsid, "clean1")
        assert editor._resolve_dialog is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest test/test_loggereditor_resolve_ui.py -k "nonmodal_tool or stay_open or whole_dataset or closes_dialog" -x`
Expected: FAIL (no `_resolve_dialog` attribute / `Keep '...'` buttons not range-scoped / no "Whole dataset" button).

- [ ] **Step 3: Make the dialog `Qt.Tool`, range-aware, with header + "Whole dataset"**

In `tools/loggereditor_resolve_dupes.py`:

Add imports: `from qgis.PyQt.QtCore import QCoreApplication, Qt` (add `Qt`).

In `__init__`, after `super().__init__(parent or editor)` add the tool-window flag and store editor; build a header label and a "Whole dataset" button; connect to the editor's date signals:

```python
    def __init__(self, editor, parent=None):
        super().__init__(parent or editor)
        self._editor = editor
        self.setWindowFlags(self.windowFlags() | Qt.Tool)
        self.setWindowTitle(_tr("Resolve duplicate timestamps"))
        self.resize(640, 480)
        self._outer = QVBoxLayout(self)
        self._header = QLabel("", self)
        self._header.setWordWrap(True)
        self._outer.addWidget(self._header)
        whole = QPushButton(_tr("Whole dataset"), self)
        whole.clicked.connect(self._on_whole_dataset)
        self._outer.addWidget(whole)
        self._body_holder = QVBoxLayout()
        self._outer.addLayout(self._body_holder)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        self._outer.addWidget(buttons)
        editor.from_date_time.dateTimeChanged.connect(self._on_range_changed)
        editor.to_date_time.dateTimeChanged.connect(self._on_range_changed)
        self._rebuild()
```

Add the range helpers + new handlers (place with the other actions):

```python
    def _range(self):
        fr = self._editor.from_date_time.dateTime().toPyDateTime().replace(tzinfo=None)
        to = self._editor.to_date_time.dateTime().toPyDateTime().replace(tzinfo=None)
        return fr, to

    def _on_range_changed(self, *args) -> None:
        self._rebuild()

    def _on_whole_dataset(self) -> None:
        fr, to = self._editor._full_buffer_range()
        if fr is not None:
            self._editor.from_date_time.setDateTime(fr)
            self._editor.to_date_time.setDateTime(to)
        self._rebuild()

    def closeEvent(self, event):  # noqa: N802
        for sig in (
            self._editor.from_date_time.dateTimeChanged,
            self._editor.to_date_time.dateTimeChanged,
        ):
            try:
                sig.disconnect(self._on_range_changed)
            except (TypeError, RuntimeError):
                pass
        super().closeEvent(event)
```

Change `_groups` to scope by range, and update the action handlers + `_cross_source_values` / `_bucket_counts` to use the scoped groups:

```python
    def _groups(self) -> list:
        return self._editor._classify_duplicates(*self._range())

    def _on_remove_redundant(self) -> None:
        self._editor._remove_redundant_duplicates(*self._range())
        self._after_change()

    def _on_keep_source(self, keep_source: str) -> None:
        self._editor._remove_cross_source_overlaps(keep_source, *self._range())
        self._after_change()
```

In `_rebuild`, set the header text with scope + counts (compute total via the editor, in-range via the scoped groups). At the top of `_rebuild`, after `groups = self._groups()`:

```python
        fr, to = self._range()
        total = len(self._editor._duplicate_instants())
        self._header.setText(
            _tr("Resolving within %s – %s — %s of %s duplicate instants in range")
            % (
                fr.strftime("%Y-%m-%d %H:%M"),
                to.strftime("%Y-%m-%d %H:%M"),
                len(groups),
                total,
            )
        )
```

Keep the existing bucket rendering (it already calls `_bucket_counts(groups)` and `_cross_source_values(groups)` and the "Show on plot" buttons). The "Show on plot" instants come from `self._groups()` (already range-scoped now) — no change needed there.

- [ ] **Step 4: Make the editor open it non-modally, reuse one instance, and close on obsid change**

In `tools/loggereditor.py`:

In `__init__`, add `self._resolve_dialog = None`.

Replace `_open_resolve_dupes_dialog`:

```python
    def _open_resolve_dupes_dialog(self) -> None:
        if not self._duplicate_instants().size:
            return
        if self._resolve_dialog is not None:
            self._resolve_dialog.raise_()
            self._resolve_dialog.activateWindow()
            self._resolve_dialog._rebuild()
            return
        dlg = ResolveDuplicatesDialog(self)
        self._resolve_dialog = dlg
        dlg.finished.connect(lambda _result: self._on_resolve_dialog_closed())
        dlg.show()

    def _on_resolve_dialog_closed(self) -> None:
        self._resolve_dialog = None
```

Add a helper to close it and call it from `_on_obsid_changed`:

```python
    def _close_resolve_dialog(self) -> None:
        if self._resolve_dialog is not None:
            self._resolve_dialog.close()
            self._resolve_dialog = None
```

In `_on_obsid_changed`, call `self._close_resolve_dialog()` as the FIRST line (before the dirty check), so switching obsid always tears down the stale dialog.

- [ ] **Step 5: Run the new tests**

Run: `python3 -m pytest test/test_loggereditor_resolve_ui.py -k "nonmodal_tool or stay_open or whole_dataset or closes_dialog" -x`
Expected: PASS.

- [ ] **Step 6: Update the existing 2c dialog tests that assumed full-range behavior**

The Plan 2c tests in `test/test_loggereditor_dupes.py` (`test_resolve_dialog_remove_redundant`, `test_resolve_dialog_cross_source_keep`, `test_resolve_dialog_summary_counts`, `test_resolve_dialog_conflict_bucket_has_no_per_row_buttons`) build the dialog via `_twin_editor()` (no `show()`). The dialog now reads `editor.from_date_time`/`to_date_time`, whose default `QDateTimeEdit` values will NOT span the 2024 test data, so the scoped groups would be empty. Fix each by setting the editor's range to full before asserting:

```python
        editor = self._twin_editor()
        fr, to = editor._full_buffer_range()
        editor.from_date_time.setDateTime(fr)
        editor.to_date_time.setDateTime(to)
        dlg = ResolveDuplicatesDialog(editor)
```

Apply that 3-line insert (after building `editor`, before constructing the dialog) to each of the four 2c dialog tests. This is a legitimate test update: the dialog's contract changed from "always global" to "scoped to the editor's range", and these tests must establish the range.

- [ ] **Step 7: Full no-regression, lint, commit**

```bash
python3 -m pytest test/test_loggereditor_dupes.py test/test_loggereditor_resolve_ui.py test/test_loggereditor_series.py test/test_loggereditor_separation.py test/test_loggereditor_refseries.py test/test_wlevels_calc_calibr.py -m spatialite -x
ruff check --fix tools/loggereditor.py tools/loggereditor_resolve_dupes.py test/test_loggereditor_dupes.py test/test_loggereditor_resolve_ui.py
ruff format tools/loggereditor.py tools/loggereditor_resolve_dupes.py test/test_loggereditor_dupes.py test/test_loggereditor_resolve_ui.py
git add -A
git commit -m "feat: non-modal on-top period-scoped resolve dialog (reactive to From/To)"
```

---

## Self-Review

**Spec coverage:** range-aware classify+ops (Task 1); `_duplicate_runs` + `_full_buffer_range` (Task 2); red run-marker that shrinks (Task 3); non-modal `Qt.Tool` dialog, range header + counts, "Whole dataset", live re-scope on From/To change, reuse single instance, close on obsid change (Task 4). Every user-facing widget is clicked in a `show()` test: banner button (`test_banner_button_opens_nonmodal_tool_dialog`), keep-source buttons + stay-open multi-period (`test_dialog_stay_open_resolves_two_periods`), "Whole dataset" (`test_whole_dataset_button_widens_scope`), obsid-change lifecycle (`test_changing_obsid_closes_dialog`), marker (`test_duplicate_marker_drawn_and_shrinks`). Redundant button + "Show on plot" remain covered by the existing 2c/2d dialog and resolve-ui tests (existing `test_focus_plot...` and the 2c redundant test, now range-set).

**Placeholder scan:** none — all steps have concrete code/commands.

**Type consistency:** `_classify_duplicates(fr=None, to=None)`, `_remove_redundant_duplicates(fr=None, to=None)`, `_remove_cross_source_overlaps(keep_source, fr=None, to=None)` — call sites in the dialog use `*self._range()` (positional fr,to) consistently. `_duplicate_runs() -> list[(Timestamp,Timestamp)]` consumed by `_draw_duplicate_marker`. `_full_buffer_range() -> (Timestamp,Timestamp)` consumed by `_on_whole_dataset` and tests. Editor attrs `_resolve_dialog`, `_dupe_marker_artists` initialized in `__init__`. Dialog handler names (`_on_remove_redundant`, `_on_keep_source`, `_on_whole_dataset`, `_on_range_changed`) consistent between Task 4 code and tests (which click buttons, not call handlers).

**Risk notes:**
- `date2num(pd.Timestamp)` works (matplotlib accepts datetime-likes). The marker uses a blended transform so y is axes-fraction; `clip_on=False` keeps end markers visible at the very bottom.
- Default `QDateTimeEdit` range not spanning data → addressed in Task 4 Step 6 (tests set full range; real users have a loaded plot whose From/To they control, and "Whole dataset" is one click).
- Disconnecting signals in `closeEvent` is guarded against double-disconnect.
