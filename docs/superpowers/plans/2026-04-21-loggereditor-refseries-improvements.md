# Logger Editor — Reference Series Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the filter list to grow vertically with the dialog, and produce one plot per cartesian-product combination of selected filter values.

**Architecture:** Two independent changes. Layout fix removes hard-coded `setMaximumHeight` caps in `loggereditor_refseries.py` and gives the scroll area a stretch factor. Per-combination plotting refactors `_plot_ref_series` in `loggereditor.py` to compute a cartesian product via a new `_iter_filter_combos` helper and delegate to a new `_plot_one_combo` method per combination. `_build_ref_query` is updated to take a single-value combo dict (one `col = ?` per filter) instead of the multi-value filter list.

**Tech Stack:** Python 3, PyQt5/6 (QGIS), pandas, matplotlib, itertools (stdlib).

---

## File Map

| File | What changes |
|---|---|
| `tools/loggereditor_refseries.py` | Remove `setMaximumHeight` on `values_list` (line 60) and scroll area (line 161); add stretch factor 1 to `addWidget(scroll)` (line 169) |
| `tools/loggereditor.py` | Add `import itertools`; add `_iter_filter_combos`, `_ref_series_combo_label` module-level functions; refactor `_plot_ref_series` into combo loop + `_plot_one_combo`; update `_build_ref_query` signature |
| `test/test_loggereditor_refseries.py` | Update `_build_ref_query` mirror + its tests; add mirrors + tests for `_iter_filter_combos` and `_ref_series_combo_label` |

---

### Task 1: Layout fix — filter list grows with dialog

**Files:**
- Modify: `tools/loggereditor_refseries.py:60` — remove `setMaximumHeight(90)` from `values_list`
- Modify: `tools/loggereditor_refseries.py:161` — remove `scroll.setMaximumHeight(280)`
- Modify: `tools/loggereditor_refseries.py:169` — add stretch factor to scroll area

- [ ] **Step 1: Make the three edits**

In `_FilterRow.__init__` at line 60, delete this line:
```python
        self.values_list.setMaximumHeight(90)
```

In `RefSeriesDialog.__init__` at line 161, delete this line:
```python
        scroll.setMaximumHeight(280)
```
(Keep `scroll.setMinimumHeight(60)` on the line below.)

At line 169, change:
```python
        main_layout.addWidget(scroll)
```
to:
```python
        main_layout.addWidget(scroll, 1)
```

- [ ] **Step 2: Run existing tests**

```
python3 -m pytest test/test_loggereditor_refseries.py -x -v
```
Expected: all existing tests pass.

- [ ] **Step 3: Ruff**

```
ruff check --fix tools/loggereditor_refseries.py && ruff format tools/loggereditor_refseries.py
```

- [ ] **Step 4: Commit**

```
git add tools/loggereditor_refseries.py
git commit -F - <<'EOF'
fix(loggereditor): allow filter list to grow vertically with dialog

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
```

---

### Task 2: `_iter_filter_combos` helper

**Files:**
- Modify: `tools/loggereditor.py` — add `import itertools` and module-level `_iter_filter_combos`
- Modify: `test/test_loggereditor_refseries.py` — add mirror function + tests

- [ ] **Step 1: Add tests to the test file**

Add `import itertools` at the top of `test/test_loggereditor_refseries.py` (after the existing imports).

Add this mirror function and tests at the bottom of `test/test_loggereditor_refseries.py`:

```python
# ---------------------------------------------------------------------------
# _iter_filter_combos
# ---------------------------------------------------------------------------


def _iter_filter_combos(filters: list[dict]):
    """Mirror of loggereditor._iter_filter_combos for testing."""
    active = [(f["col"], f["values"]) for f in filters if f.get("values")]
    if not active:
        yield {}
        return
    cols = [col for col, _ in active]
    value_lists = [vals for _, vals in active]
    for combo_vals in itertools.product(*value_lists):
        yield dict(zip(cols, combo_vals))


def test_iter_filter_combos_no_filters():
    combos = list(_iter_filter_combos([]))
    assert combos == [{}]


def test_iter_filter_combos_single_filter_single_value():
    combos = list(_iter_filter_combos([{"col": "obsid", "values": ["A"]}]))
    assert combos == [{"obsid": "A"}]


def test_iter_filter_combos_single_filter_multi_value():
    combos = list(_iter_filter_combos([{"col": "obsid", "values": ["A", "B"]}]))
    assert combos == [{"obsid": "A"}, {"obsid": "B"}]


def test_iter_filter_combos_two_filters_cartesian():
    filters = [
        {"col": "obsid", "values": ["A", "B"]},
        {"col": "parameter", "values": ["X", "Y"]},
    ]
    combos = list(_iter_filter_combos(filters))
    assert len(combos) == 4
    assert {"obsid": "A", "parameter": "X"} in combos
    assert {"obsid": "A", "parameter": "Y"} in combos
    assert {"obsid": "B", "parameter": "X"} in combos
    assert {"obsid": "B", "parameter": "Y"} in combos


def test_iter_filter_combos_empty_values_skipped():
    filters = [
        {"col": "obsid", "values": []},
        {"col": "parameter", "values": ["X"]},
    ]
    combos = list(_iter_filter_combos(filters))
    assert combos == [{"parameter": "X"}]
```

- [ ] **Step 2: Run to confirm new tests pass with the mirror**

```
python3 -m pytest test/test_loggereditor_refseries.py -x -v -k "iter_filter"
```
Expected: 5 new tests pass.

- [ ] **Step 3: Add `itertools` import and `_iter_filter_combos` to `loggereditor.py`**

In `loggereditor.py`, add `import itertools` to the stdlib imports block (after `import os`, around line 6):
```python
import itertools
```

Add this function in `loggereditor.py` near line 1667, just before `_ref_series_filter_str`:

```python
def _iter_filter_combos(filters: list[dict]):
    """Yield one {col: value} mapping per cartesian-product combination of selected filter values."""
    active = [(f["col"], f["values"]) for f in filters if f.get("values")]
    if not active:
        yield {}
        return
    cols = [col for col, _ in active]
    value_lists = [vals for _, vals in active]
    for combo_vals in itertools.product(*value_lists):
        yield dict(zip(cols, combo_vals))
```

- [ ] **Step 4: Run full test file**

```
python3 -m pytest test/test_loggereditor_refseries.py -x -v
```
Expected: all tests pass.

- [ ] **Step 5: Ruff**

```
ruff check --fix tools/loggereditor.py test/test_loggereditor_refseries.py && ruff format tools/loggereditor.py test/test_loggereditor_refseries.py
```

- [ ] **Step 6: Commit**

```
git add tools/loggereditor.py test/test_loggereditor_refseries.py
git commit -F - <<'EOF'
feat(loggereditor): add _iter_filter_combos for cartesian product of filter values

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
```

---

### Task 3: Update `_build_ref_query` to accept a combo dict

**Files:**
- Modify: `tools/loggereditor.py:943-959` — update method signature and body
- Modify: `test/test_loggereditor_refseries.py` — replace mirror + replace 5 old tests with 4 new ones

- [ ] **Step 1: Replace the mirror and tests in the test file**

Replace the existing `_build_ref_query` mirror (currently lines 17–31) with:

```python
def _build_ref_query(conn, s: dict, combo: dict) -> tuple:
    ph = conn.placeholder()
    sql = f"SELECT {ident(s['x_col'])}, {ident(s['y_col'])} FROM {ident(s['table'])}"
    where_parts: list[str] = []
    params: list = []
    for col, val in combo.items():
        where_parts.append(f"{ident(col)} = {ph}")
        params.append(val)
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)
    sql += f" ORDER BY {ident(s['x_col'])}"
    return sql, params
```

Replace the five existing `test_build_ref_query_*` tests with these four:

```python
def test_build_ref_query_no_combo():
    sql, params = _build_ref_query(_StubConn(), _BASE, {})
    assert '"date_time"' in sql
    assert '"rdep"' in sql
    assert '"meteo"' in sql
    assert "WHERE" not in sql
    assert params == []
    assert sql.endswith('ORDER BY "date_time"')


def test_build_ref_query_single_value_combo():
    sql, params = _build_ref_query(_StubConn(), _BASE, {"obsid": "A01"})
    assert '"obsid" = ?' in sql
    assert params == ["A01"]


def test_build_ref_query_two_col_combo():
    sql, params = _build_ref_query(
        _StubConn(), _BASE, {"obsid": "A01", "parameter": "rain"}
    )
    assert '"obsid" = ?' in sql
    assert '"parameter" = ?' in sql
    assert " AND " in sql
    assert params == ["A01", "rain"]


def test_build_ref_query_postgres_placeholder():
    sql, params = _build_ref_query(_StubConn("%s"), _BASE, {"obsid": "X"})
    assert '"obsid" = %s' in sql
    assert params == ["X"]
```

- [ ] **Step 2: Run tests to confirm mirror tests pass**

```
python3 -m pytest test/test_loggereditor_refseries.py -x -v -k "build_ref_query"
```
Expected: 4 tests pass.

- [ ] **Step 3: Update `_build_ref_query` in `loggereditor.py`**

Replace the method body at lines 943–959 with:

```python
    def _build_ref_query(self, conn, s: dict, combo: dict) -> tuple:
        ph = conn.placeholder()
        sql = (
            f"SELECT {ident(s['x_col'])}, {ident(s['y_col'])} FROM {ident(s['table'])}"
        )
        where_parts: list[str] = []
        params: list = []
        for col, val in combo.items():
            where_parts.append(f"{ident(col)} = {ph}")
            params.append(val)
        if where_parts:
            sql += " WHERE " + " AND ".join(where_parts)
        sql += f" ORDER BY {ident(s['x_col'])}"
        return sql, params
```

- [ ] **Step 4: Run full test file**

```
python3 -m pytest test/test_loggereditor_refseries.py -x -v
```
Expected: all tests pass.

- [ ] **Step 5: Ruff**

```
ruff check --fix tools/loggereditor.py test/test_loggereditor_refseries.py && ruff format tools/loggereditor.py test/test_loggereditor_refseries.py
```

- [ ] **Step 6: Commit**

```
git add tools/loggereditor.py test/test_loggereditor_refseries.py
git commit -F - <<'EOF'
refactor(loggereditor): _build_ref_query accepts single-value combo dict

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
```

---

### Task 4: Label helper + per-combination plot refactor

**Files:**
- Modify: `tools/loggereditor.py` — add `_ref_series_combo_label`; replace `_plot_ref_series` with combo loop; add `_plot_one_combo`
- Modify: `test/test_loggereditor_refseries.py` — add mirror + label tests

- [ ] **Step 1: Add label tests to the test file**

Add to the bottom of `test/test_loggereditor_refseries.py`:

```python
# ---------------------------------------------------------------------------
# _ref_series_combo_label
# ---------------------------------------------------------------------------


def _ref_series_auto_label_mirror(s: dict) -> str:
    base = f"{s.get('table', '?')}.{s.get('y_col', '?')}"
    filter_str = ", ".join(
        f"{f['col']}={'+'.join(str(v) for v in f['values'])}"
        for f in s.get("filters", [])
        if f.get("values")
    )
    return f"{base} [{filter_str}]" if filter_str else base


def _ref_series_combo_label(s: dict, combo: dict, is_multi: bool) -> str:
    combo_str = ", ".join(str(v) for v in combo.values())
    user_label = s.get("label", "")
    if is_multi:
        return f"{user_label} ({combo_str})" if user_label else combo_str
    return user_label or _ref_series_auto_label_mirror(s)


def test_label_single_no_user_label_no_filters():
    label = _ref_series_combo_label({**_BASE, "label": ""}, {}, is_multi=False)
    assert label == "meteo.rdep"


def test_label_single_no_user_label_with_filter():
    s = {**_BASE, "label": "", "filters": [{"col": "obsid", "values": ["A"]}]}
    label = _ref_series_combo_label(s, {"obsid": "A"}, is_multi=False)
    assert label == "meteo.rdep [obsid=A]"


def test_label_single_with_user_label():
    label = _ref_series_combo_label({**_BASE, "label": "Precipitation"}, {"obsid": "A"}, is_multi=False)
    assert label == "Precipitation"


def test_label_multi_no_user_label_two_cols():
    s = {**_BASE, "label": ""}
    label = _ref_series_combo_label(s, {"obsid": "A", "parameter": "X"}, is_multi=True)
    assert label == "A, X"


def test_label_multi_with_user_label():
    s = {**_BASE, "label": "Precip"}
    label = _ref_series_combo_label(s, {"obsid": "A", "parameter": "X"}, is_multi=True)
    assert label == "Precip (A, X)"


def test_label_multi_single_col_no_user_label():
    label = _ref_series_combo_label({**_BASE, "label": ""}, {"obsid": "B"}, is_multi=True)
    assert label == "B"
```

- [ ] **Step 2: Run to confirm label tests pass with the mirror**

```
python3 -m pytest test/test_loggereditor_refseries.py -x -v -k "label"
```
Expected: 6 new tests pass.

- [ ] **Step 3: Add `_ref_series_combo_label` to `loggereditor.py`**

Add after `_ref_series_auto_label` (around line 1679 after the edits from Task 2):

```python
def _ref_series_combo_label(s: dict, combo: dict, is_multi: bool) -> str:
    combo_str = ", ".join(str(v) for v in combo.values())
    user_label = s.get("label", "")
    if is_multi:
        return f"{user_label} ({combo_str})" if user_label else combo_str
    return user_label or _ref_series_auto_label(s)
```

- [ ] **Step 4: Replace `_plot_ref_series` and add `_plot_one_combo` in `loggereditor.py`**

Replace lines 906–941 (the full `_plot_ref_series` method) with:

```python
    def _plot_ref_series(self, conn, s: dict) -> None:
        combos = list(_iter_filter_combos(s.get("filters", [])))
        is_multi = len(combos) > 1
        for combo in combos:
            self._plot_one_combo(conn, s, combo, is_multi)

    def _plot_one_combo(self, conn, s: dict, combo: dict, is_multi: bool) -> None:
        sql, params = self._build_ref_query(conn, s, combo)
        rows = conn.execute_and_fetchall(sql, params)
        if not rows:
            return
        df = pd.DataFrame(rows, columns=["x", "y"])
        df["x"] = pd.to_datetime(df["x"], errors="coerce")
        df = df.dropna(subset=["x", "y"]).set_index("x").sort_index()["y"]
        if df.empty:
            return
        if s.get("resample"):
            df = getattr(df.resample(s["resample"]), s.get("resample_agg", "mean"))()
        if s.get("interpolate"):
            df = df.interpolate(method="time")
        norm = s.get("normalize", "")
        if norm == "date" and s.get("normalize_date"):
            ref_val = df.asof(pd.Timestamp(s["normalize_date"]))
            if pd.notna(ref_val):
                df = df - ref_val
        elif norm == "mean":
            df = df - df.mean()
        elif norm == "zscore":
            std = df.std()
            if std > 0:
                df = (df - df.mean()) / std
        df = df * s.get("scale", 1.0)
        if df.empty:
            return
        _ref_series_plot_style(
            self.ref_axes,
            df.index.to_pydatetime(),
            df.values,
            s.get("style", "line"),
            _ref_series_combo_label(s, combo, is_multi),
        )
```

- [ ] **Step 5: Run full test suite**

```
python3 -m pytest test/test_loggereditor_refseries.py -x -v
```
Expected: all tests pass.

- [ ] **Step 6: Ruff**

```
ruff check --fix tools/loggereditor.py test/test_loggereditor_refseries.py && ruff format tools/loggereditor.py test/test_loggereditor_refseries.py
```

- [ ] **Step 7: Final full run**

```
python3 -m pytest test/ -x --ignore=test/test_create_postgis_db.py -m "not postgis" -q
```
Expected: no failures.

- [ ] **Step 8: Commit**

```
git add tools/loggereditor.py test/test_loggereditor_refseries.py
git commit -F - <<'EOF'
feat(loggereditor): plot one series per cartesian-product filter combination

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
```
