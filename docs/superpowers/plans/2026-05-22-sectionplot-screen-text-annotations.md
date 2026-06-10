# Sectionplot Screen Text Annotations — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users annotate screen bars in the sectionplot with text from any column of the `screen` table (screenshort, screen, comment, diam_inner, diam_outer), following the same pattern as geology bar text.

**Architecture:** A new `get_screen_text_data()` function in `data.py` fetches the selected column per screen interval and returns `{col: {(x,z): text}}`. The existing `paint_layer_text()` painter is reused with `barwidth * width_factor`. A new combobox in the dock UI selects the column, wired through the declarative settings system.

**Tech Stack:** Python 3, PyQt/QGIS, matplotlib, SpatiaLite/PostGIS

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `definitions/midvatten_defs.py` | Modify (~line 76) | Add `"secplotscreentext": ""` default |
| `tools/sectionplot/settings.py` | Modify (~line 75) | Add binding for `secplotscreentext` |
| `ui/secplotdockwidget.ui` | Modify (~line 1038) | Add "Screen text:" label + combobox (row 9) |
| `tools/sectionplot/ui_types.py` | Regenerated | Picks up new widget automatically |
| `tools/sectionplot/data.py` | Modify (after line 316) | New `get_screen_text_data()` function |
| `tools/sectionplot/_sectionplot.py` | Modify (~lines 78, 130, 467, 505, 664) | Import, instance var, data fetch, combo populate, draw call |
| `test/test_sectionplot_screens.py` | Modify (append) | New tests for `get_screen_text_data()` |

---

### Task 1: Add settings default and binding

**Files:**
- Modify: `definitions/midvatten_defs.py:76`
- Modify: `tools/sectionplot/settings.py:75`

- [ ] **Step 1: Add the default to midvatten_defs.py**

In `definitions/midvatten_defs.py`, add `"secplotscreentext": ""` immediately after the `"screenwidthfactor": 1.2` line (line 76):

```python
        "screenwidthfactor": 1.2,
        "secplotscreentext": "",
```

- [ ] **Step 2: Add the binding to settings.py**

In `tools/sectionplot/settings.py`, add to `GENERAL_BINDINGS` after the `"screenwidthfactor"` entry (line 75):

```python
    "screenwidthfactor": _b("screenwidthfactor", "screen_width_factor_spin", float),
    "secplotscreentext": _b("secplotscreentext", "screen_textcol_combo_box", str),
```

- [ ] **Step 3: Run the settings test to verify nothing broke**

Run: `python3 -m pytest test/test_sectionplot_settings.py -x -v`
Expected: all existing tests PASS

- [ ] **Step 4: Commit**

```bash
git add definitions/midvatten_defs.py tools/sectionplot/settings.py
git commit -m "feat(sectionplot): add secplotscreentext settings default and binding"
```

---

### Task 2: Add combobox to the dock UI and regenerate ui_types

**Files:**
- Modify: `ui/secplotdockwidget.ui:1038`
- Regenerate: `tools/sectionplot/ui_types.py`

- [ ] **Step 1: Add the label and combobox to secplotdockwidget.ui**

In `ui/secplotdockwidget.ui`, insert a new row 9 inside `grid_layout_2` right before the closing `</layout>` tag on line 1040. Place it after the `screen_width_factor_spin` item (row 8) and before the `</layout>` of `bar_groupbox`. Insert this XML block between line 1038 (`</widget>`) and line 1039 (`</item>`):

After the closing `</item>` of row 8 (after line 1039) and before the `</layout>` on line 1040, insert:

```xml
                            <item row="9" column="0">
                             <widget class="QLabel" name="label_screen_text">
                              <property name="font">
                               <font>
                                <pointsize>9</pointsize>
                                <weight>50</weight>
                                <bold>false</bold>
                               </font>
                              </property>
                              <property name="text">
                               <string>Screen text:</string>
                              </property>
                             </widget>
                            </item>
                            <item row="9" column="1" colspan="3">
                             <widget class="QComboBox" name="screen_textcol_combo_box">
                              <property name="font">
                               <font>
                                <family>DejaVu Sans</family>
                                <pointsize>9</pointsize>
                                <weight>50</weight>
                                <bold>false</bold>
                               </font>
                              </property>
                             </widget>
                            </item>
```

- [ ] **Step 2: Regenerate ui_types.py**

Run: `python3 tools/sectionplot/generate_ui_types.py`

Verify that the regenerated `tools/sectionplot/ui_types.py` now contains:

```python
    screen_textcol_combo_box: QtWidgets.QComboBox
```

- [ ] **Step 3: Run the ui_types test**

Run: `python3 -m pytest test/test_sectionplot_ui_types.py -x -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add ui/secplotdockwidget.ui tools/sectionplot/ui_types.py
git commit -m "feat(sectionplot): add screen text combobox to dock UI"
```

---

### Task 3: Write the data function with tests (TDD)

**Files:**
- Create test: `test/test_sectionplot_screens.py` (append to existing file)
- Modify: `tools/sectionplot/data.py` (after line 316)

- [ ] **Step 1: Write the failing tests**

Append to `test/test_sectionplot_screens.py` — add test methods to the `GetScreenPlotDataMixin` class, and also add helper insert methods. These tests share the existing mixin/fixture infrastructure:

```python
    def _insert_screen_data_with_text(self):
        """Insert screen rows that include the `screen` and `comment` columns."""
        db_utils.sql_alter_db(
            """INSERT INTO screen (obsid, screenid, depthtop, depthbot, screenshort, screen, comment)
               VALUES ('P1', 1, 2.0, 5.0, 'JWS', 'Johnson well screen 2-5m', 'Good condition')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO screen (obsid, screenid, depthtop, depthbot, screenshort, screen, comment)
               VALUES ('P1', 2, 8.0, 12.0, 'PVC solid', NULL, '')"""
        )

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_get_screen_text_data_basic(self, mock_messagebar):
        """get_screen_text_data returns {col: {(x,z): text}} with correct positions."""
        from midvatten.tools.sectionplot.data import get_screen_text_data

        self._insert_obs_points()
        self._insert_screen_data_with_text()

        secplot = self._make_secplot()
        try:
            result = get_screen_text_data(
                {"P1": 1.0}, secplot.z_data, "screen", secplot.dbconnection
            )
        finally:
            secplot.dbconnection.closedb()

        print(f"{mock_messagebar.mock_calls=}")

        # screen col: row1 has text, row2 is NULL → filtered out
        assert "screen" in result
        texts = result["screen"]
        # Row 1: depthtop=2, depthbot=5 → height=3, bottom=100-5=95, z=95+1.5=96.5
        assert (1.0, 96.5) in texts
        assert texts[(1.0, 96.5)] == "Johnson well screen 2-5m"
        # Row 2 had NULL screen → should be absent
        assert len(texts) == 1

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_get_screen_text_data_comment_column(self, mock_messagebar):
        """get_screen_text_data works for comment column, filters empty strings."""
        from midvatten.tools.sectionplot.data import get_screen_text_data

        self._insert_obs_points()
        self._insert_screen_data_with_text()

        secplot = self._make_secplot()
        try:
            result = get_screen_text_data(
                {"P1": 1.0}, secplot.z_data, "comment", secplot.dbconnection
            )
        finally:
            secplot.dbconnection.closedb()

        print(f"{mock_messagebar.mock_calls=}")

        # comment col: row1='Good condition', row2='' (filtered out)
        assert "comment" in result
        texts = result["comment"]
        assert (1.0, 96.5) in texts
        assert texts[(1.0, 96.5)] == "Good condition"
        assert len(texts) == 1

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_get_screen_text_data_empty_result(self, mock_messagebar):
        """get_screen_text_data returns {} for empty obsids."""
        from midvatten.tools.sectionplot.data import get_screen_text_data

        secplot = self._make_secplot()
        try:
            result = get_screen_text_data(
                {}, secplot.z_data, "screen", secplot.dbconnection
            )
        finally:
            secplot.dbconnection.closedb()

        assert result == {}

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_get_screen_text_data_no_screen_table(self, mock_messagebar):
        """get_screen_text_data returns {} when screen table is absent."""
        from midvatten.tools.sectionplot.data import get_screen_text_data

        self._insert_obs_points()

        secplot = self._make_secplot()
        try:
            secplot.dbconnection.execute("DROP TABLE screen")
            result = get_screen_text_data(
                {"P1": 1.0}, secplot.z_data, "screen", secplot.dbconnection
            )
        finally:
            secplot.dbconnection.closedb()

        print(f"{mock_messagebar.mock_calls=}")

        assert result == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest test/test_sectionplot_screens.py -x -v -k "screen_text"`
Expected: FAIL — `ImportError: cannot import name 'get_screen_text_data'`

- [ ] **Step 3: Implement get_screen_text_data()**

In `tools/sectionplot/data.py`, add this function after `get_screen_plot_data()` (after line 316):

```python
_SCREEN_TEXT_COLUMNS = frozenset({"screenshort", "screen", "comment", "diam_inner", "diam_outer"})


def get_screen_text_data(
    obsids_x_position: dict,
    z_data: dict,
    text_column: str,
    dbconnection=None,
) -> dict:
    """Fetch text labels for screen intervals, keyed by (x, z) position.

    Returns ``{text_column: {(x, z): text_value}}`` — same structure as
    ``get_plot_data_layer_texts()`` so ``paint_layer_text()`` can be reused.
    """
    if text_column not in _SCREEN_TEXT_COLUMNS:
        return {}
    if not db_utils.verify_table_exists("screen", dbconnection=dbconnection):
        return {}
    if not obsids_x_position:
        return {}

    texts: dict = {}
    ph = dbconnection.placeholder()
    col = ident(text_column, allowed=_SCREEN_TEXT_COLUMNS)
    sql = f"SELECT depthtop, depthbot, {col} FROM screen WHERE obsid = {ph} ORDER BY screenid"

    for obs, x in obsids_x_position.items():
        if obs not in z_data:
            continue
        recs = dbconnection.execute_and_fetchall(sql, args=(obs,))
        if not recs:
            continue
        z = z_data[obs]["z"]
        for row in recs:
            depthtop, depthbot, text_val = row[0], row[1], row[2]
            if depthtop is None or depthbot is None:
                continue
            if text_val is None or not str(text_val).strip() or str(text_val).lower().strip() == "null":
                continue
            height = float(depthbot) - float(depthtop)
            bottom = z - float(depthbot)
            mid_z = bottom + (height / 2)
            texts.setdefault(text_column, {})[(x, mid_z)] = text_val

    return texts
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest test/test_sectionplot_screens.py -x -v`
Expected: ALL PASS (both existing screen bar tests and new screen text tests)

- [ ] **Step 5: Commit**

```bash
git add tools/sectionplot/data.py test/test_sectionplot_screens.py
git commit -m "feat(sectionplot): add get_screen_text_data() with tests"
```

---

### Task 4: Wire up the UI and drawing logic

**Files:**
- Modify: `tools/sectionplot/_sectionplot.py`

This task connects all the pieces: imports the new function, populates the combobox, fetches text data, and calls the painter.

- [ ] **Step 1: Add the import**

In `tools/sectionplot/_sectionplot.py`, add `get_screen_text_data` to the data imports (around line 77):

```python
from midvatten.tools.sectionplot.data import (  # noqa: E402
    prepare_obsid_positions as _prepare_obsid_positions,
    get_z_data as _get_z_data,
    get_plot_data_bars as _get_plot_data_bars,
    get_screen_plot_data as _get_screen_plot_data,
    get_screen_text_data as _get_screen_text_data,
    get_plot_data_layer_texts as _get_plot_data_layer_texts,
    get_drillstops as _get_drillstops,
    get_plot_data_seismic as _get_plot_data_seismic,
    get_water_levels_from_df as _get_water_levels_from_df,
    get_length_map,  # noqa: F401 — re-exported via __init__.py
    fill_empty_columns,  # noqa: F401 — re-exported via __init__.py
    slider_val_to_idx,  # noqa: F401 — re-exported via __init__.py
```

- [ ] **Step 2: Add instance variable initialization**

In `_sectionplot.py`, near line 132 where `self.layer_texts = {}` is initialized, add:

```python
        self.screen_texts = {}
```

- [ ] **Step 3: Populate the screen text combobox in fill_combo_boxes()**

In `fill_combo_boxes()`, after the geology textcol_combo_box population (after line 506), add:

```python
        self.screen_textcol_combo_box.clear()
        screen_textitems = [
            "",
            "screenshort",
            "screen",
            "comment",
            "diam_inner",
            "diam_outer",
        ]
        for item in screen_textitems:
            self.screen_textcol_combo_box.addItem(item)
```

Then after the existing `set_combobox(self.textcol_combo_box, ...)` block (around lines 518-521), add:

```python
        if len(str(self.ms.settingsdict["secplotscreentext"])):
            set_combobox(
                self.screen_textcol_combo_box,
                str(self.ms.settingsdict["secplotscreentext"]),
            )
```

- [ ] **Step 4: Fetch screen text data in the data-loading section**

In the data-loading section, after the `self.screen_bars = ...` call (around line 471), add:

```python
        self.screen_texts = _get_screen_text_data(
            obsids_x_position=self.obsids_x_position,
            z_data=self.z_data,
            text_column=self.ms.settingsdict["secplotscreentext"],
            dbconnection=self.dbconnection,
        )
```

- [ ] **Step 5: Paint screen text in draw_plot()**

In `draw_plot()`, after the screen bars are painted and `self._screen_bar_containers` is set (after the block ending around line 667), but still inside the `if _screens_mode != "none" and self.screen_bars:` guard, add:

```python
                    _screen_text_col = self.ms.settingsdict["secplotscreentext"]
                    if _screen_text_col and self.screen_texts:
                        _painters.paint_layer_text(
                            self.figure,
                            self.screen_texts,
                            _screen_text_col,
                            self.ms.settingsdict["secplotlayertextalignment"],
                            self.barwidth
                            * float(self.ms.settingsdict["screenwidthfactor"]),
                            self.secplot_templates.loaded_template,
                        )
```

- [ ] **Step 6: Run the full sectionplot test suite**

Run: `python3 -m pytest test/test_sectionplot_screens.py test/test_sectionplot_settings.py test/test_sectionplot_ui_types.py -x -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add tools/sectionplot/_sectionplot.py
git commit -m "feat(sectionplot): wire screen text combobox, data fetch, and paint call"
```

---

### Task 5: End-to-end verification

- [ ] **Step 1: Run the full test suite for sectionplot-related tests**

Run: `python3 -m pytest test/test_sectionplot_screens.py test/test_sectionplot_settings.py test/test_sectionplot_ui_types.py test/test_sectionplot_painters.py test/test_sectionplot_spatialite.py test/test_sectionplot.py -x -v`
Expected: ALL PASS

- [ ] **Step 2: Run ruff lint and format**

```bash
ruff check --fix tools/sectionplot/data.py tools/sectionplot/_sectionplot.py tools/sectionplot/settings.py definitions/midvatten_defs.py test/test_sectionplot_screens.py
ruff format tools/sectionplot/data.py tools/sectionplot/_sectionplot.py tools/sectionplot/settings.py definitions/midvatten_defs.py test/test_sectionplot_screens.py
```

- [ ] **Step 3: Commit any lint/format fixes**

```bash
git add -u
git commit -m "style: ruff lint and format for screen text feature"
```
