> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-05-26 · modified: 2026-05-26 · archived: 2026-07-31

# Logger Editor: Series Selection & Separation Controls — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add stackable series separation (source/created_at/datetime precision) with LegendPicker-based line selection to the logger editor, so users can visually isolate and edit specific data series.

**Architecture:** Three checkboxes control which dimensions separate data into distinct plot lines. A ported `LegendPicker` (from dynplot) enables click/ctrl-click selection on legend entries or plot lines, with dimming. Edit operations filter to selected lines within the current period. A "Fit period" button adjusts the date range to selected lines. All changes are in-memory; SQL generation adds WHERE filters for selected series when saving.

**Tech Stack:** Python 3, PyQt5/6, matplotlib, numpy, pandas, SQLite/PostgreSQL

**Spec:** `docs/superpowers/specs/2026-05-26-loggereditor-series-selection-design.md`

---

### Task 1: Port LegendPicker to midvatten

**Files:**
- Create: `tools/utils/legend_picker.py`
- Create: `test/test_legend_picker.py`

This is a copy-and-adapt of dynplot's `LegendPicker` class. The logger editor doesn't have `vectorlayer_id` on its artists, so `compute_legend_pick_highlight` is not needed. The core click/ctrl-click/dimming/callback behavior is identical.

- [ ] **Step 1: Write failing test for LegendPicker single-click selection**

```python
# test/test_legend_picker.py
import pytest
import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt
import matplotlib.lines

from midvatten.tools.utils.legend_picker import LegendPicker


class FakeMouseEvent:
    def __init__(self, key=None):
        self.key = key


class FakePickEvent:
    def __init__(self, artist, key=None):
        self.artist = artist
        self.mouseevent = FakeMouseEvent(key)


@pytest.fixture()
def picker_setup():
    fig, ax = plt.subplots()
    line_a = ax.plot([0, 1], [0, 1], label="A")[0]
    line_b = ax.plot([0, 1], [1, 0], label="B")[0]
    handles = [line_a, line_b]
    leg = ax.legend(handles, ["A", "B"])
    picker = LegendPicker(legend=leg, fig=fig, handles=handles)
    yield picker, fig, ax, line_a, line_b, leg
    plt.close(fig)


class TestLegendPickerSingleClick:
    def test_click_selects_line(self, picker_setup):
        picker, fig, ax, line_a, line_b, leg = picker_setup
        leg_lines = leg.get_lines()
        event = FakePickEvent(leg_lines[0])
        picker.on_pick(event)
        assert leg_lines[0] in picker.selected_legend_lines
        assert line_b.get_alpha() == 0.2

    def test_click_same_line_deselects(self, picker_setup):
        picker, fig, ax, line_a, line_b, leg = picker_setup
        leg_lines = leg.get_lines()
        event = FakePickEvent(leg_lines[0])
        picker.on_pick(event)
        picker.on_pick(event)
        assert len(picker.selected_legend_lines) == 0

    def test_click_different_line_switches(self, picker_setup):
        picker, fig, ax, line_a, line_b, leg = picker_setup
        leg_lines = leg.get_lines()
        picker.on_pick(FakePickEvent(leg_lines[0]))
        picker.on_pick(FakePickEvent(leg_lines[1]))
        assert picker.selected_legend_lines == {leg_lines[1]}
        assert line_a.get_alpha() == 0.2


class TestLegendPickerCtrlClick:
    def test_ctrl_click_adds(self, picker_setup):
        picker, fig, ax, line_a, line_b, leg = picker_setup
        leg_lines = leg.get_lines()
        picker.on_pick(FakePickEvent(leg_lines[0]))
        picker.on_pick(FakePickEvent(leg_lines[1], key="control"))
        assert picker.selected_legend_lines == {leg_lines[0], leg_lines[1]}

    def test_ctrl_click_removes(self, picker_setup):
        picker, fig, ax, line_a, line_b, leg = picker_setup
        leg_lines = leg.get_lines()
        picker.on_pick(FakePickEvent(leg_lines[0]))
        picker.on_pick(FakePickEvent(leg_lines[1], key="control"))
        picker.on_pick(FakePickEvent(leg_lines[0], key="control"))
        assert picker.selected_legend_lines == {leg_lines[1]}


class TestLegendPickerCallback:
    def test_callback_fires_with_selected_ax_lines(self, picker_setup):
        picker, fig, ax, line_a, line_b, leg = picker_setup
        received = []
        picker.register_pick_callback(lambda lines: received.append(lines))
        leg_lines = leg.get_lines()
        picker.on_pick(FakePickEvent(leg_lines[0]))
        assert len(received) == 1
        assert received[0] == [line_a]

    def test_callback_fires_empty_on_deselect(self, picker_setup):
        picker, fig, ax, line_a, line_b, leg = picker_setup
        received = []
        picker.register_pick_callback(lambda lines: received.append(lines))
        leg_lines = leg.get_lines()
        picker.on_pick(FakePickEvent(leg_lines[0]))
        picker.on_pick(FakePickEvent(leg_lines[0]))
        assert received[-1] == []


class TestLegendPickerAxisPick:
    def test_click_on_axis_line_selects(self, picker_setup):
        picker, fig, ax, line_a, line_b, leg = picker_setup
        event = FakePickEvent(line_a)
        picker.on_pick(event)
        assert len(picker.selected_legend_lines) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest test/test_legend_picker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'midvatten.tools.utils.legend_picker'`

- [ ] **Step 3: Implement LegendPicker**

```python
# tools/utils/legend_picker.py
import matplotlib as mpl
import matplotlib.lines


class LegendPicker:
    def __init__(
        self,
        legend: mpl.legend.Legend,
        fig: mpl.figure.Figure,
        handles: list,
        picked_alpha: float = 1.0,
        other_alpha: float = 0.2,
        pickradius: int = 4,
    ):
        self.legend = legend
        self.fig = fig
        self.picked_alpha = picked_alpha
        self.other_alpha = other_alpha
        self.leg_lines_ax_lines: dict = {}
        self.original_alphas: dict = {}
        self.selected_legend_lines: set = set()
        self._pick_callback = None

        lines = [a for a in handles if isinstance(a, mpl.lines.Line2D)]
        self.leg_lines_ax_lines = self._prepare_for_pick(
            legend.get_lines(), lines, pickradius
        )
        self.ax_to_legend = {v: k for k, v in self.leg_lines_ax_lines.items()}
        fig.canvas.mpl_connect("pick_event", self.on_pick)

    def _prepare_for_pick(
        self,
        legend_lines: list,
        ax_lines: list,
        pickradius: int,
    ) -> dict:
        mapping: dict = {}
        for legend_line, ax_line in zip(legend_lines, ax_lines):
            legend_line.set_picker(pickradius)
            ax_line.set_picker(pickradius)
            mapping[legend_line] = ax_line
            self.original_alphas[legend_line] = legend_line.get_alpha()
            self.original_alphas[ax_line] = ax_line.get_alpha()
        return mapping

    def register_pick_callback(self, callback):
        self._pick_callback = callback

    def on_pick(self, event):
        artist = event.artist
        if artist in self.ax_to_legend:
            legend_line = self.ax_to_legend[artist]
        elif artist in self.leg_lines_ax_lines:
            legend_line = artist
        else:
            return

        ctrl_held = getattr(event.mouseevent, "key", None) == "control"

        if ctrl_held:
            if legend_line in self.selected_legend_lines:
                self.selected_legend_lines.discard(legend_line)
            else:
                self.selected_legend_lines.add(legend_line)
            if not self.selected_legend_lines:
                self.revert_alpha()
            else:
                self._apply_alpha()
        else:
            if self.selected_legend_lines == {legend_line}:
                self.revert_alpha()
            else:
                self.selected_legend_lines = {legend_line}
                self._apply_alpha()

    def _apply_alpha(self):
        for legend_line, ax_line in self.leg_lines_ax_lines.items():
            alpha = (
                self.picked_alpha
                if legend_line in self.selected_legend_lines
                else self.other_alpha
            )
            legend_line.set_alpha(alpha)
            ax_line.set_alpha(alpha)
        self.fig.canvas.draw_idle()
        self._fire_callback()

    def _fire_callback(self):
        if self._pick_callback:
            ax_lines = [
                self.leg_lines_ax_lines[ll] for ll in self.selected_legend_lines
            ]
            self._pick_callback(ax_lines)

    def revert_alpha(self):
        for line, alpha in self.original_alphas.items():
            line.set_alpha(alpha)
        self.selected_legend_lines = set()
        self.fig.canvas.draw_idle()
        self._fire_callback()

    def get_selected_ax_lines(self) -> list:
        return [self.leg_lines_ax_lines[ll] for ll in self.selected_legend_lines]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest test/test_legend_picker.py -v`
Expected: All tests PASS

- [ ] **Step 5: Lint and commit**

```bash
ruff check --fix tools/utils/legend_picker.py test/test_legend_picker.py
ruff format tools/utils/legend_picker.py test/test_legend_picker.py
git add tools/utils/legend_picker.py test/test_legend_picker.py
git commit -m "feat: port LegendPicker from dynplot for line selection with dimming"
```

---

### Task 2: Add separation checkboxes and _line_key column

**Files:**
- Modify: `tools/loggereditor.py` — `show()`, `load_obsid_and_init()`, `_build_ts_recarray()`

This task adds the three UI checkboxes and the `_line_key` column to `_buf`. No plot changes yet — the existing source-based drawing continues to work. The new checkboxes don't trigger re-plots until Task 3.

- [ ] **Step 1: Write failing test for _line_key computation**

```python
# test/test_loggereditor_separation.py
import pytest
import pandas as pd
import numpy as np

pytest.importorskip("qgis.PyQt")

from unittest import mock

from midvatten.tools.loggereditor import LoggerEditor


class TestLineKeyComputation:
    def test_source_only(self):
        buf = pd.DataFrame(
            {
                "head_cm_m": [1.0, 2.0, 3.0],
                "level_masl": [10.0, 20.0, 30.0],
                "source": ["A", "B", "A"],
            },
            index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
        )
        result = LoggerEditor._compute_line_keys(
            buf, separate_source=True, separate_created_at=False,
            separate_dt_precision=False, created_at_grouping=None
        )
        assert list(result) == [("A",), ("B",), ("A",)]

    def test_source_and_created_at(self):
        buf = pd.DataFrame(
            {
                "head_cm_m": [1.0, 2.0],
                "level_masl": [10.0, 20.0],
                "source": ["A", "A"],
                "created_at": ["2024-01-01 10:00:00", "2024-01-02 14:00:00"],
            },
            index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
        )
        result = LoggerEditor._compute_line_keys(
            buf, separate_source=True, separate_created_at=True,
            separate_dt_precision=False, created_at_grouping=None
        )
        assert list(result) == [
            ("A", "2024-01-01 10:00:00"),
            ("A", "2024-01-02 14:00:00"),
        ]

    def test_created_at_grouped_by_day(self):
        buf = pd.DataFrame(
            {
                "head_cm_m": [1.0, 2.0],
                "level_masl": [10.0, 20.0],
                "source": ["A", "A"],
                "created_at": ["2024-01-01 10:00:00", "2024-01-01 14:00:00"],
            },
            index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
        )
        result = LoggerEditor._compute_line_keys(
            buf, separate_source=True, separate_created_at=True,
            separate_dt_precision=False, created_at_grouping="day"
        )
        assert result[0] == result[1]  # same day → same key

    def test_dt_precision_separation(self):
        buf = pd.DataFrame(
            {
                "head_cm_m": [1.0, 2.0],
                "level_masl": [10.0, 20.0],
                "source": ["A", "A"],
                "dt_length": [16, 19],
            },
            index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
        )
        result = LoggerEditor._compute_line_keys(
            buf, separate_source=True, separate_created_at=False,
            separate_dt_precision=True, created_at_grouping=None
        )
        assert result[0] != result[1]

    def test_no_separation_single_key(self):
        buf = pd.DataFrame(
            {
                "head_cm_m": [1.0, 2.0],
                "level_masl": [10.0, 20.0],
                "source": ["A", "B"],
            },
            index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
        )
        result = LoggerEditor._compute_line_keys(
            buf, separate_source=False, separate_created_at=False,
            separate_dt_precision=False, created_at_grouping=None
        )
        assert result[0] == result[1]  # all same key
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest test/test_loggereditor_separation.py -v`
Expected: FAIL with `AttributeError: type object 'LoggerEditor' has no attribute '_compute_line_keys'`

- [ ] **Step 3: Add `_compute_line_keys` static method**

In `tools/loggereditor.py`, add this static method to the `LoggerEditor` class (after the `_MAX_HISTORY = 200` line, around line 55):

```python
    @staticmethod
    def _compute_line_keys(
        buf: pd.DataFrame,
        separate_source: bool,
        separate_created_at: bool,
        separate_dt_precision: bool,
        created_at_grouping: str | None,
    ) -> list[tuple]:
        n = len(buf)
        if n == 0:
            return []
        parts: list[list] = []
        if separate_source and "source" in buf.columns:
            parts.append(buf["source"].fillna("").tolist())
        if separate_created_at and "created_at" in buf.columns:
            ca = buf["created_at"].fillna("")
            if created_at_grouping == "hour":
                ca = ca.str[:13]  # "YYYY-MM-DD HH"
            elif created_at_grouping == "day":
                ca = ca.str[:10]  # "YYYY-MM-DD"
            parts.append(ca.tolist())
        if separate_dt_precision and "dt_length" in buf.columns:
            parts.append(buf["dt_length"].tolist())
        if not parts:
            return [("_all",)] * n
        return list(zip(*parts))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest test/test_loggereditor_separation.py -v`
Expected: All tests PASS

- [ ] **Step 5: Add checkboxes in `show()` and column loading in `load_obsid_and_init()`**

In `tools/loggereditor.py`, in the `show()` method, after schema detection (after `self._schema_variant = ...`, around line 221), add the checkboxes programmatically:

```python
        # Separation checkboxes — added to grid_layout_7 (rows 3-5)
        from qgis.PyQt.QtWidgets import QCheckBox

        self.separate_source_cb = QCheckBox(
            QCoreApplication.translate("Calibrlogger", "Separate by source")
        )
        self.separate_source_cb.setChecked(True)
        self.separate_source_cb.setFont(self.logger_line_nodes.font())

        self.separate_created_at_cb = QCheckBox(
            QCoreApplication.translate("Calibrlogger", "Separate by import time")
        )
        self.separate_created_at_cb.setFont(self.logger_line_nodes.font())

        self.separate_dt_precision_cb = QCheckBox(
            QCoreApplication.translate("Calibrlogger", "Separate by datetime precision")
        )
        self.separate_dt_precision_cb.setFont(self.logger_line_nodes.font())

        self.grid_layout_7.addWidget(self.separate_source_cb, 3, 0, 1, 2)
        self.grid_layout_7.addWidget(self.separate_created_at_cb, 4, 0, 1, 2)
        self.grid_layout_7.addWidget(self.separate_dt_precision_cb, 5, 0, 1, 2)

        # Disable unavailable checkboxes based on schema
        existing_columns = db_utils.tables_columns(table="w_levels_logger").get(
            "w_levels_logger", []
        )
        if self._schema_variant == "no_source":
            self.separate_source_cb.setEnabled(False)
            self.separate_source_cb.setChecked(False)
            self.separate_source_cb.setToolTip(
                QCoreApplication.translate(
                    "Calibrlogger",
                    "Source column not available in this database",
                )
            )
        if "created_at" not in existing_columns:
            self.separate_created_at_cb.setEnabled(False)
            self.separate_created_at_cb.setToolTip(
                QCoreApplication.translate(
                    "Calibrlogger",
                    "created_at column not available in this database",
                )
            )

        self._created_at_grouping: str | None = None
```

Then connect the checkboxes to trigger `update_plot()` (add after the checkbox setup):

```python
        self.separate_source_cb.stateChanged.connect(lambda _: self.update_plot())
        self.separate_created_at_cb.stateChanged.connect(
            lambda _: self._on_created_at_toggled()
        )
        self.separate_dt_precision_cb.stateChanged.connect(lambda _: self.update_plot())
```

In `load_obsid_and_init()`, modify the SQL queries to also fetch `created_at` and `LENGTH(date_time)` when available. Change the query block (lines 513-524) to:

```python
            # Build extra columns for separation dimensions
            extra_cols = ""
            extra_cols_list = []
            if "created_at" in existing_columns:
                extra_cols_list.append("l.created_at" if schema_variant == "series_join" else "created_at")
            extra_cols_list.append(
                f"LENGTH(l.date_time)" if schema_variant == "series_join" else "LENGTH(date_time)"
            )
            if extra_cols_list:
                extra_cols = ", " + ", ".join(extra_cols_list)

            if schema_variant == "series_join":
                head_level_masl_sql = (
                    f"SELECT l.date_time, l.head_cm / 100, l.level_masl,"
                    f" TRIM(COALESCE(s.source, '')){extra_cols}"
                    f" FROM w_levels_logger l"
                    f" LEFT JOIN w_logger_series s ON s.id = l.series_id"
                    f" WHERE l.obsid = {ph} ORDER BY l.date_time"
                )
            elif schema_variant == "source_col":
                head_level_masl_sql = (
                    f"SELECT date_time, head_cm / 100, level_masl,"
                    f" TRIM(COALESCE(source, '')){extra_cols}"
                    f" FROM w_levels_logger WHERE obsid = {ph} ORDER BY date_time"
                )
            else:
                head_level_masl_sql = (
                    f"SELECT date_time, head_cm / 100, level_masl,"
                    f" '' as source{extra_cols}"
                    f" FROM w_levels_logger WHERE obsid = {ph} ORDER BY date_time"
                )
```

And update the DataFrame construction (lines 531-543) to include the new columns:

```python
            if head_level_masl_list:
                buf_dict = {
                    "head_cm_m": [r[1] for r in head_level_masl_list],
                    "level_masl": [r[2] for r in head_level_masl_list],
                    "source": [r[3] for r in head_level_masl_list],
                }
                col_idx = 4
                if "created_at" in existing_columns:
                    buf_dict["created_at"] = [r[col_idx] for r in head_level_masl_list]
                    col_idx += 1
                buf_dict["dt_length"] = [r[col_idx] for r in head_level_masl_list]

                buf_df = pd.DataFrame(
                    buf_dict,
                    index=pd.to_datetime(
                        [r[0] for r in head_level_masl_list]
                    ).to_pydatetime(),
                )
            else:
                buf_df = pd.DataFrame(columns=["head_cm_m", "level_masl", "source"])
```

After building `buf_df` (after `self._buf = buf_df`, around line 544), add:

```python
            self._recompute_line_keys()
```

And add the helper method to the class:

```python
    def _recompute_line_keys(self):
        if self._buf is not None and not self._buf.empty:
            self._buf["_line_key"] = self._compute_line_keys(
                self._buf,
                separate_source=self.separate_source_cb.isChecked(),
                separate_created_at=self.separate_created_at_cb.isChecked(),
                separate_dt_precision=self.separate_dt_precision_cb.isChecked(),
                created_at_grouping=self._created_at_grouping,
            )
        self._legend_picker = None  # invalidate picker on key change
```

Store `existing_columns` as `self._existing_columns` so it's accessible outside `show()` and `load_obsid_and_init()`. Set it once in `show()` and reuse in `load_obsid_and_init()`.

- [ ] **Step 6: Lint and commit**

```bash
ruff check --fix tools/loggereditor.py test/test_loggereditor_separation.py
ruff format tools/loggereditor.py test/test_loggereditor_separation.py
git add tools/loggereditor.py test/test_loggereditor_separation.py
git commit -m "feat: add separation checkboxes and _line_key column to logger editor"
```

---

### Task 3: Draw series by _line_key instead of source

**Files:**
- Modify: `tools/loggereditor.py` — `_build_ts_recarray()`, `_draw_series()`

Replace the source-based iteration in `_draw_series()` with `_line_key`-based iteration. The recarray gains a `line_key` field.

- [ ] **Step 1: Write failing test for _line_key-based recarray**

```python
# Append to test/test_loggereditor_separation.py

class TestBuildTsRecarrayWithLineKey:
    def test_recarray_has_line_key_field(self):
        buf = pd.DataFrame(
            {
                "head_cm_m": [1.0, 2.0],
                "level_masl": [10.0, 20.0],
                "source": ["A", "B"],
                "_line_key": [("A",), ("B",)],
            },
            index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
        )
        result = LoggerEditor._build_ts_recarray(None, buf, "level_masl")
        assert "line_key" in result.dtype.names
        assert result.line_key[0] == ("A",)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest test/test_loggereditor_separation.py::TestBuildTsRecarrayWithLineKey -v`
Expected: FAIL

- [ ] **Step 3: Modify `_build_ts_recarray` to include line_key**

In `tools/loggereditor.py`, modify `_build_ts_recarray()` (lines 382-406). Add `line_key` as a field in the recarray dtype:

```python
    def _build_ts_recarray(
        self,
        buf: pd.DataFrame,
        col: str,
        values_override: np.ndarray | None = None,
    ) -> np.recarray:
        n = len(buf)
        max_src_len = max(
            (len(str(s)) for s in buf["source"] if s is not None), default=1
        )
        has_line_key = "_line_key" in buf.columns
        rec = np.recarray(
            n,
            dtype=[
                ("date_time", object),
                ("values", float),
                ("source", f"U{max_src_len}"),
                ("line_key", object),
            ],
        )
        rec.date_time[:] = buf.index.strftime(_DT_FMT)
        if values_override is not None:
            rec.values[:] = values_override
        else:
            rec.values[:] = buf[col].to_numpy(dtype=float)
        rec.source[:] = buf["source"].to_numpy()
        if has_line_key:
            rec.line_key[:] = buf["_line_key"].tolist()
        else:
            rec.line_key[:] = [("_all",)] * n
        return rec
```

- [ ] **Step 4: Modify `_draw_series` to iterate by line_key**

Replace the source-based iteration in `_draw_series()` (lines 1180-1214) with line_key-based iteration:

```python
        if self.level_masl_ts.size and self.contains_more_than_nan(self.level_masl_ts):
            self.logger_artist = self.plot_recarray(
                self.axes,
                self.level_masl_ts,
                obsid
                + QCoreApplication.translate(
                    "Calibrlogger", " logger water level for editing"
                ),
                time_list=logger_time_list,
                style=dict(
                    linestyle="none", picker=5, marker=None, zorder=10, color="white"
                ),
            )[0]

            unique_keys = list(dict.fromkeys(self.level_masl_ts.line_key))
            self._line_key_to_artist = {}
            for idx, key in enumerate(unique_keys):
                label = self._label_for_line_key(obsid, key)
                ts = self.level_masl_ts.copy()
                mask = np.array([k != key for k in ts.line_key])
                ts.values[mask] = np.nan
                try:
                    color = logger_level_masl_colors[idx]
                except IndexError:
                    color = np.random.rand(3, 1).ravel()
                a = self.plot_recarray(
                    self.axes,
                    ts,
                    label,
                    time_list=logger_time_list,
                    style=dict(
                        linestyle="-",
                        picker=0,
                        markersize=3,
                        marker=marker,
                        zorder=10,
                        color=color,
                    ),
                )[0]
                a._line_key = key
                self.logger_plot_artists.append(a)
                self._line_key_to_artist[key] = a
                handles.append(a)
                labels.append(label)
```

Do the same for the head series block (lines 1219-1251) — iterate by `line_key` from `self.head_ts_for_plot` instead of by source.

Add the label helper method:

```python
    def _label_for_line_key(self, obsid: str, key: tuple) -> str:
        label = obsid + QCoreApplication.translate(
            "Calibrlogger", " logger water level"
        )
        parts = []
        dim_idx = 0
        if self.separate_source_cb.isChecked():
            src = key[dim_idx]
            dim_idx += 1
            if src and str(src).strip():
                parts.append(str(src))
        if self.separate_created_at_cb.isChecked():
            parts.append(f"imported={key[dim_idx]}")
            dim_idx += 1
        if self.separate_dt_precision_cb.isChecked():
            parts.append(f"dt_len={key[dim_idx]}")
            dim_idx += 1
        if parts:
            label += ", " + ", ".join(parts)
        return label
```

- [ ] **Step 5: Run existing tests to confirm no regression**

Run: `python3 -m pytest test/test_loggereditor_separation.py -v`
Expected: PASS

- [ ] **Step 6: Lint and commit**

```bash
ruff check --fix tools/loggereditor.py test/test_loggereditor_separation.py
ruff format tools/loggereditor.py test/test_loggereditor_separation.py
git add tools/loggereditor.py test/test_loggereditor_separation.py
git commit -m "feat: draw logger series by composite _line_key instead of source"
```

---

### Task 4: created_at warning dialog and auto-grouping

**Files:**
- Modify: `tools/loggereditor.py` — add `_on_created_at_toggled()` method

- [ ] **Step 1: Write failing test for created_at grouping dialog logic**

```python
# Append to test/test_loggereditor_separation.py

class TestCreatedAtGrouping:
    def test_group_by_hour_truncates(self):
        buf = pd.DataFrame(
            {
                "head_cm_m": [1.0, 2.0],
                "level_masl": [10.0, 20.0],
                "source": ["A", "A"],
                "created_at": ["2024-01-01 10:05:00", "2024-01-01 10:22:00"],
            },
            index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
        )
        result = LoggerEditor._compute_line_keys(
            buf, separate_source=False, separate_created_at=True,
            separate_dt_precision=False, created_at_grouping="hour"
        )
        assert result[0] == result[1]  # same hour

    def test_group_by_hour_different_hours(self):
        buf = pd.DataFrame(
            {
                "head_cm_m": [1.0, 2.0],
                "level_masl": [10.0, 20.0],
                "source": ["A", "A"],
                "created_at": ["2024-01-01 10:05:00", "2024-01-01 14:22:00"],
            },
            index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
        )
        result = LoggerEditor._compute_line_keys(
            buf, separate_source=False, separate_created_at=True,
            separate_dt_precision=False, created_at_grouping="hour"
        )
        assert result[0] != result[1]  # different hours
```

- [ ] **Step 2: Run test to verify it passes** (grouping logic already implemented in Task 2)

Run: `python3 -m pytest test/test_loggereditor_separation.py::TestCreatedAtGrouping -v`
Expected: PASS (the `_compute_line_keys` method already handles hour/day grouping)

- [ ] **Step 3: Implement `_on_created_at_toggled()` with warning dialog**

Add to `LoggerEditor` class:

```python
    def _on_created_at_toggled(self):
        if not self.separate_created_at_cb.isChecked():
            self._created_at_grouping = None
            self.update_plot()
            return

        if self._buf is None or "created_at" not in self._buf.columns:
            self.update_plot()
            return

        distinct_count = self._buf["created_at"].nunique()
        if distinct_count <= 10:
            self._created_at_grouping = None
            self.update_plot()
            return

        from qgis.PyQt.QtWidgets import QMessageBox

        box = QMessageBox(self)
        box.setWindowTitle(
            QCoreApplication.translate("Calibrlogger", "Many import timestamps")
        )
        box.setText(
            QCoreApplication.translate(
                "Calibrlogger",
                "Found {} distinct import timestamps. This may clutter the plot.",
            ).format(distinct_count)
        )
        btn_hour = box.addButton(
            QCoreApplication.translate("Calibrlogger", "Group by hour"),
            QMessageBox.ActionRole,
        )
        btn_day = box.addButton(
            QCoreApplication.translate("Calibrlogger", "Group by day"),
            QMessageBox.ActionRole,
        )
        btn_continue = box.addButton(
            QCoreApplication.translate("Calibrlogger", "Continue without grouping"),
            QMessageBox.ActionRole,
        )
        btn_cancel = box.addButton(QMessageBox.Cancel)

        box.exec_()
        clicked = box.clickedButton()

        if clicked is btn_hour:
            self._created_at_grouping = "hour"
        elif clicked is btn_day:
            self._created_at_grouping = "day"
        elif clicked is btn_continue:
            self._created_at_grouping = None
        else:
            self.separate_created_at_cb.blockSignals(True)
            self.separate_created_at_cb.setChecked(False)
            self.separate_created_at_cb.blockSignals(False)
            return

        self.update_plot()
```

- [ ] **Step 4: Lint and commit**

```bash
ruff check --fix tools/loggereditor.py test/test_loggereditor_separation.py
ruff format tools/loggereditor.py test/test_loggereditor_separation.py
git add tools/loggereditor.py test/test_loggereditor_separation.py
git commit -m "feat: add created_at warning dialog with auto-grouping options"
```

---

### Task 5: Integrate LegendPicker into logger editor

**Files:**
- Modify: `tools/loggereditor.py` — `_finish_plot()`, `update_plot()`

- [ ] **Step 1: Write failing test for LegendPicker integration**

```python
# Append to test/test_loggereditor_separation.py

class TestLegendPickerIntegration:
    def test_picker_created_after_plot(self):
        """LegendPicker should exist after _finish_plot and track logger artists."""
        # This test verifies the attribute exists after plot creation.
        # Full integration test requires QGIS; this is a minimal structure check.
        assert hasattr(LoggerEditor, '_on_legend_pick')
```

- [ ] **Step 2: Add LegendPicker to `_finish_plot()`**

In `_finish_plot()` (line 1275-1278), replace the legend creation block:

```python
        if self.axes.legend_ is None:
            leg = self.axes.legend(handles, labels)
```

with:

```python
        from midvatten.tools.utils.legend_picker import LegendPicker

        leg = self.axes.legend(handles, labels)
        pickable_handles = [h for h in handles if hasattr(h, "_line_key")]
        if pickable_handles:
            self._legend_picker = LegendPicker(
                legend=leg, fig=self.calibrplotfigure, handles=pickable_handles
            )
            self._legend_picker.register_pick_callback(self._on_legend_pick)
        else:
            self._legend_picker = None
```

Note: remove the `if self.axes.legend_ is None:` guard — the legend should always be recreated since `self.axes.clear()` is called in `update_plot()`.

- [ ] **Step 3: Add `_on_legend_pick` callback and `selected_line_keys` property**

Add to `LoggerEditor` class:

```python
    def _on_legend_pick(self, ax_lines: list):
        self._selected_line_keys = set()
        for line in ax_lines:
            if hasattr(line, "_line_key"):
                self._selected_line_keys.add(line._line_key)
        self.plot_or_update_selected_line()
        self._update_fit_period_button_state()

    @property
    def selected_line_keys(self) -> set:
        return getattr(self, "_selected_line_keys", set())
```

Initialize `self._selected_line_keys = set()` in `__init__` or early in `show()`.

- [ ] **Step 4: Modify `plot_or_update_selected_line()` to respect line selection**

Change `plot_or_update_selected_line()` to only show selected-line nodes when lines are selected:

```python
    def plot_or_update_selected_line(self):
        if self.logger_artist is None:
            return
        fr_d_t = self.from_date_time.dateTime().toPyDateTime().replace(tzinfo=None)
        to_d_t = self.to_date_time.dateTime().toPyDateTime().replace(tzinfo=None)
        xdata = self.logger_artist.get_xdata()

        selected_keys = self.selected_line_keys
        has_key_filter = bool(selected_keys) and "_line_key" in self._buf.columns

        ydata = []
        for idx, y in enumerate(self.logger_artist.get_ydata()):
            in_period = fr_d_t <= xdata[idx].replace(tzinfo=None) <= to_d_t
            if has_key_filter and in_period:
                buf_idx = min(idx, len(self._buf) - 1)
                in_selection = self._buf.iloc[buf_idx]["_line_key"] in selected_keys
                ydata.append(y if in_selection else None)
            else:
                ydata.append(y if in_period else None)

        if self.selected_line is None:
            self.selected_line = self.axes.plot(
                xdata,
                ydata,
                linestyle="none",
                marker="o",
                markerfacecolor="None",
                markeredgecolor="black",
                markeredgewidth=1,
                markersize=4,
                zorder=30,
                label=QCoreApplication.translate("Calibrlogger", "Selected nodes"),
            )[0]
        else:
            self.selected_line.set_ydata(ydata)
        self.canvas.draw_idle()
```

- [ ] **Step 5: Reset selection on obsid change or plot update**

In `update_plot()`, after `self.selected_line = None` (line 1094), add:

```python
        self._selected_line_keys = set()
```

- [ ] **Step 6: Run tests**

Run: `python3 -m pytest test/test_legend_picker.py test/test_loggereditor_separation.py -v`
Expected: All PASS

- [ ] **Step 7: Lint and commit**

```bash
ruff check --fix tools/loggereditor.py
ruff format tools/loggereditor.py
git add tools/loggereditor.py
git commit -m "feat: integrate LegendPicker into logger editor for line selection"
```

---

### Task 6: Add "Fit period to selection" button

**Files:**
- Modify: `tools/loggereditor.py` — `show()`, add `_fit_period_to_selection()` and `_update_fit_period_button_state()`

- [ ] **Step 1: Add button in `show()` near the from/to date controls**

After the separation checkboxes in `show()`, add:

```python
        self.fit_period_btn = QPushButton(
            QCoreApplication.translate("Calibrlogger", "Fit period to selection")
        )
        self.fit_period_btn.setFont(self.logger_line_nodes.font())
        self.fit_period_btn.setEnabled(False)
        self.fit_period_btn.setToolTip(
            QCoreApplication.translate(
                "Calibrlogger",
                "Set from/to dates to cover the selected lines' full time range",
            )
        )
        self.fit_period_btn.clicked.connect(self._fit_period_to_selection)
        self.grid_layout_7.addWidget(self.fit_period_btn, 6, 0, 1, 2)
```

- [ ] **Step 2: Implement `_fit_period_to_selection()`**

```python
    def _fit_period_to_selection(self):
        if not self.selected_line_keys or self._buf is None:
            return
        mask = self._buf["_line_key"].isin(self.selected_line_keys)
        selected_data = self._buf.loc[mask]
        if selected_data.empty:
            return
        self.from_date_time.setDateTime(selected_data.index.min())
        self.to_date_time.setDateTime(selected_data.index.max())

    def _update_fit_period_button_state(self):
        if hasattr(self, "fit_period_btn"):
            self.fit_period_btn.setEnabled(bool(self.selected_line_keys))
```

- [ ] **Step 3: Reset button state in `update_plot()`**

In `update_plot()`, after `self._selected_line_keys = set()`, add:

```python
        self._update_fit_period_button_state()
```

- [ ] **Step 4: Lint and commit**

```bash
ruff check --fix tools/loggereditor.py
ruff format tools/loggereditor.py
git add tools/loggereditor.py
git commit -m "feat: add 'Fit period to selection' button to logger editor"
```

---

### Task 7: Filter edit operations by selected lines

**Files:**
- Modify: `tools/loggereditor.py` — `update_level_masl_from_head()`, `update_level_masl_from_level_masl()`, `delete_selected_range()`, `_trend_release()`

All edit operations currently filter only by date range. Add a line-key filter when lines are selected.

- [ ] **Step 1: Write failing test for filtered edit mask**

```python
# Append to test/test_loggereditor_separation.py

class TestEditMaskFiltering:
    def test_mask_includes_line_key_filter(self):
        buf = pd.DataFrame(
            {
                "head_cm_m": [1.0, 2.0, 3.0],
                "level_masl": [10.0, 20.0, 30.0],
                "source": ["A", "B", "A"],
                "_line_key": [("A",), ("B",), ("A",)],
            },
            index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
        )
        fr = pd.Timestamp("2024-01-01")
        to = pd.Timestamp("2024-01-03")
        selected_keys = {("A",)}

        mask = (
            (fr <= buf.index)
            & (buf.index <= to)
            & buf["level_masl"].notna()
        )
        if selected_keys and "_line_key" in buf.columns:
            mask = mask & buf["_line_key"].isin(selected_keys)

        assert mask.sum() == 2  # only source A rows
        assert not mask.iloc[1]  # source B excluded
```

- [ ] **Step 2: Run test to verify it passes** (this is a pure pandas test)

Run: `python3 -m pytest test/test_loggereditor_separation.py::TestEditMaskFiltering -v`
Expected: PASS

- [ ] **Step 3: Create a shared mask-building helper**

Add to `LoggerEditor` class:

```python
    def _build_edit_mask(
        self, fr_d_t, to_d_t, value_col: str | None = None
    ) -> pd.Series:
        fr = pd.Timestamp(fr_d_t)
        to = pd.Timestamp(to_d_t)
        mask = (fr <= self._buf.index) & (self._buf.index <= to)
        if value_col is not None:
            mask = mask & self._buf[value_col].notna()
        if self.selected_line_keys and "_line_key" in self._buf.columns:
            mask = mask & self._buf["_line_key"].isin(self.selected_line_keys)
        return mask
```

- [ ] **Step 4: Update `update_level_masl_from_head()` to use shared mask**

Replace the mask building (lines 1047-1052) with:

```python
        mask = self._build_edit_mask(fr_d_t, to_d_t, value_col="head_cm_m")
```

- [ ] **Step 5: Update `update_level_masl_from_level_masl()` to use shared mask**

Replace the mask building (lines 1025-1031) with:

```python
        mask = self._build_edit_mask(fr_d_t, to_d_t, value_col="level_masl")
```

- [ ] **Step 6: Update `delete_selected_range()` to use shared mask**

Replace the mask building (line 1826) with:

```python
        mask = self._build_edit_mask(fr_d_t, to_d_t)
```

- [ ] **Step 7: Update `_trend_release()` to use shared mask**

In `_trend_release()` (around lines 2122-2123), replace the mask building with:

```python
        mask = self._build_edit_mask(fr_d_t, to_d_t, value_col="level_masl")
```

- [ ] **Step 8: Run tests**

Run: `python3 -m pytest test/test_loggereditor_separation.py -v`
Expected: All PASS

- [ ] **Step 9: Lint and commit**

```bash
ruff check --fix tools/loggereditor.py test/test_loggereditor_separation.py
ruff format tools/loggereditor.py test/test_loggereditor_separation.py
git add tools/loggereditor.py test/test_loggereditor_separation.py
git commit -m "feat: filter edit operations by selected line keys"
```

---

### Task 8: Extend SQL WHERE clauses for selected-line saves

**Files:**
- Modify: `tools/loggereditor.py` — `_compute_update_statements()`, `save_to_db()`

When lines are selected and the edit used a line-key filter, the range-based SQL UPDATE paths need matching WHERE extensions so they don't over-update rows belonging to other series.

- [ ] **Step 1: Write failing test for SQL WHERE extension**

```python
# Append to test/test_loggereditor_separation.py
from unittest import mock

class TestSqlWhereExtension:
    def test_range_update_includes_source_filter(self):
        """Range-based UPDATE should include source filter when lines were selected."""
        editor = mock.MagicMock(spec=LoggerEditor)
        editor._schema_variant = "source_col"
        editor.selected_line_keys = {("A",)}
        editor.separate_source_cb = mock.MagicMock()
        editor.separate_source_cb.isChecked.return_value = True
        editor.separate_created_at_cb = mock.MagicMock()
        editor.separate_created_at_cb.isChecked.return_value = False
        editor.separate_dt_precision_cb = mock.MagicMock()
        editor.separate_dt_precision_cb.isChecked.return_value = False

        # This test validates the helper that builds the WHERE extension
        where, params = LoggerEditor._build_selection_where(
            editor, ph="?"
        )
        assert "source" in where.lower()
        assert "A" in params
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest test/test_loggereditor_separation.py::TestSqlWhereExtension -v`
Expected: FAIL with `AttributeError: ... '_build_selection_where'`

- [ ] **Step 3: Implement `_build_selection_where()` helper**

Add to `LoggerEditor` class:

```python
    def _build_selection_where(self, ph: str) -> tuple[str, list]:
        if not self.selected_line_keys:
            return "", []

        clauses = []
        params = []
        dim_idx = 0

        if self.separate_source_cb.isChecked():
            sources = sorted({k[dim_idx] for k in self.selected_line_keys})
            dim_idx += 1
            if self._schema_variant == "series_join":
                sub = f"(SELECT {ident('id')} FROM {ident('w_logger_series')} WHERE {ident('source')} IN ({', '.join(ph for _ in sources)}))"
                clauses.append(f"{ident('series_id')} IN {sub}")
                params.extend(sources)
            elif self._schema_variant == "source_col":
                placeholders = ", ".join(ph for _ in sources)
                clauses.append(f"{ident('source')} IN ({placeholders})")
                params.extend(sources)

        if self.separate_created_at_cb.isChecked() and dim_idx < len(next(iter(self.selected_line_keys))):
            ca_values = sorted({k[dim_idx] for k in self.selected_line_keys})
            dim_idx += 1
            if self._created_at_grouping == "hour":
                or_parts = []
                for ca in ca_values:
                    or_parts.append(
                        f"({ident('created_at')} >= {ph} AND {ident('created_at')} < {ph})"
                    )
                    params.append(ca + ":00:00")
                    hour_int = int(ca[-2:])
                    next_hour = ca[:11] + f"{hour_int + 1:02d}:00:00"
                    params.append(next_hour)
                clauses.append("(" + " OR ".join(or_parts) + ")")
            elif self._created_at_grouping == "day":
                or_parts = []
                for ca in ca_values:
                    or_parts.append(
                        f"({ident('created_at')} >= {ph} AND {ident('created_at')} < {ph})"
                    )
                    params.append(ca + " 00:00:00")
                    from datetime import datetime as _dt, timedelta
                    next_day = (_dt.strptime(ca, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
                    params.append(next_day + " 00:00:00")
                clauses.append("(" + " OR ".join(or_parts) + ")")
            else:
                placeholders = ", ".join(ph for _ in ca_values)
                clauses.append(f"{ident('created_at')} IN ({placeholders})")
                params.extend(ca_values)

        if not clauses:
            return "", []
        return " AND " + " AND ".join(clauses), params
```

- [ ] **Step 4: Inject selection WHERE into `_compute_update_statements()`**

Modify `_compute_update_statements()` to accept and use the selection WHERE. In `save_to_db()`, before calling `_compute_update_statements()`, compute the selection WHERE:

```python
            sel_where, sel_params = self._build_selection_where(ph)
```

Pass `sel_where` and `sel_params` as extra parameters to `_compute_update_statements()`.

In `_compute_update_statements()`, extend the signature:

```python
    def _compute_update_statements(
        self,
        changed_index: pd.DatetimeIndex,
        orig_changed: pd.Series,
        new_changed: pd.Series,
        head_changed: pd.Series,
        obsid: str,
        tbl: str,
        ph: str,
        is_sqlite: bool,
        sel_where: str = "",
        sel_params: list | None = None,
    ) -> tuple[list[tuple], list[tuple]]:
```

Then append `sel_where` to `where_range`:

```python
        where_range = f"{obsid_col} = {ph} AND {dt_between}{sel_where}"
```

And prepend `sel_params` to each range statement's params tuple. For the "set to NULL" pattern:

```python
            if grp_new.isna().all():
                sql = f"UPDATE {tbl} SET {level_col} = NULL WHERE {where_range}"
                range_stmts.append((sql, (obsid, t1, t2, *(_sel_params or []))))
                continue
```

Wait — the params order needs to match the SQL placeholder order. Since `sel_where` is appended after `{dt_between}`, the sel_params go after `(obsid, t1, t2)`:

For set-null: `(obsid, t1, t2, *sel_params)`
For logger-pos: `(C, obsid, t1, t2, *sel_params)`
For add-offset: `(D, obsid, t1, t2, *sel_params)`

Also extend `delete_sql` in `save_to_db()` with the selection WHERE:

```python
                    if delete_params:
                        delete_sql = (
                            f"DELETE FROM {tbl} WHERE {ident('obsid')} = {ph}"
                            f" AND {dt_eq}{sel_where}"
                        )
                        # Extend each delete_params tuple with sel_params
                        if sel_params:
                            delete_params = [p + tuple(sel_params) for p in delete_params]
                        dbconnection.executemany(delete_sql, delete_params)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest test/test_loggereditor_separation.py::TestSqlWhereExtension -v`
Expected: PASS

- [ ] **Step 6: Run full test suite for regression check**

Run: `python3 -m pytest test/ -x --timeout=300`
Expected: PASS

- [ ] **Step 7: Lint and commit**

```bash
ruff check --fix tools/loggereditor.py test/test_loggereditor_separation.py
ruff format tools/loggereditor.py test/test_loggereditor_separation.py
git add tools/loggereditor.py test/test_loggereditor_separation.py
git commit -m "feat: extend SQL WHERE clauses for series-filtered saves"
```

---

### Task 9: Batched plot creation with abort

**Files:**
- Modify: `tools/loggereditor.py` — `_draw_series()`

When total line count exceeds 15, draw incrementally with a progress dialog.

- [ ] **Step 1: Add batched drawing to `_draw_series()`**

After computing `unique_keys` in `_draw_series()`, add:

```python
            if len(unique_keys) > 15:
                from qgis.PyQt.QtWidgets import QProgressDialog
                from qgis.PyQt.QtCore import Qt as QtCore_Qt

                progress = QProgressDialog(
                    QCoreApplication.translate(
                        "Calibrlogger", "Drawing {} lines...".format(len(unique_keys))
                    ),
                    QCoreApplication.translate("Calibrlogger", "Abort"),
                    0,
                    len(unique_keys),
                    self,
                )
                progress.setWindowModality(QtCore_Qt.WindowModal)
            else:
                progress = None
```

Then inside the loop, after each artist is created:

```python
                if progress is not None:
                    progress.setValue(idx + 1)
                    qgis.PyQt.QtWidgets.QApplication.processEvents()
                    if progress.wasCanceled():
                        break
```

After the loop, if aborted, revert the last-changed toggle:

```python
            if progress is not None and progress.wasCanceled():
                # Revert: undo the most recent toggle change
                if self.separate_created_at_cb.isChecked():
                    self.separate_created_at_cb.blockSignals(True)
                    self.separate_created_at_cb.setChecked(False)
                    self.separate_created_at_cb.blockSignals(False)
                elif self.separate_dt_precision_cb.isChecked():
                    self.separate_dt_precision_cb.blockSignals(True)
                    self.separate_dt_precision_cb.setChecked(False)
                    self.separate_dt_precision_cb.blockSignals(False)
                self._recompute_line_keys()
```

- [ ] **Step 2: Lint and commit**

```bash
ruff check --fix tools/loggereditor.py
ruff format tools/loggereditor.py
git add tools/loggereditor.py
git commit -m "feat: batched plot creation with progress dialog and abort for >15 lines"
```

---

### Task 10: Recompute _line_key on toggle and reload

**Files:**
- Modify: `tools/loggereditor.py`

Ensure `_recompute_line_keys()` is called on every path that changes separation state or reloads data.

- [ ] **Step 1: Add call in `load_obsid_and_init()` on buffer reuse path**

In the buffer-reuse path (around line 500, the `if obsid == self._buf_obsid` branch), add `self._recompute_line_keys()` before the return. This ensures toggle changes are reflected even when the buffer is cached.

- [ ] **Step 2: Add call in `update_plot()` before `_draw_series()`**

In `update_plot()`, after `obsid = self.load_obsid_and_init()` (line 1089), add:

```python
        self._recompute_line_keys()
```

This ensures keys are fresh for every plot cycle.

- [ ] **Step 3: Lint and commit**

```bash
ruff check --fix tools/loggereditor.py
ruff format tools/loggereditor.py
git add tools/loggereditor.py
git commit -m "fix: recompute _line_key on toggle change and data reload"
```

---

### Task 11: Manual integration test

**Files:** None (manual testing)

- [ ] **Step 1: Run full test suite**

```bash
python3 -m pytest test/ -x --timeout=300
```
Expected: All PASS

- [ ] **Step 2: Run ruff**

```bash
ruff check tools/loggereditor.py tools/utils/legend_picker.py
ruff format --check tools/loggereditor.py tools/utils/legend_picker.py
```
Expected: No issues

- [ ] **Step 3: Verify in QGIS** (if available)

Open the logger editor in QGIS with test data that has multiple sources:
1. Verify "Separate by source" is checked by default and shows multiple colored lines
2. Click a legend entry — other lines should dim
3. Ctrl+click a second legend entry — both should be bright
4. Select a period with rectangle selector
5. Click "Set logger position" — only selected lines in the period should be affected
6. Toggle "Separate by import time" — if >10 distinct values, dialog should appear
7. Click "Fit period to selection" — from/to should adjust to selected lines' extent
