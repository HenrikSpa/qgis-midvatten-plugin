# Integration Tests: wqualreport, painters, export_worker

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise test coverage on three low-coverage user-facing modules — `tools/wqualreport.py` (9%), `tools/sectionplot/painters.py` (37%), and `tools/export_worker.py` (47%) — with tests that exercise what the user actually does.

**Architecture:**
- **wqualreport**: Lead test calls `Wqualreport.show()` with a mocked iface and a real selected QGIS layer — the same flow a user triggers from the menu. Helper-method tests follow as secondary.
- **painters**: Pure-matplotlib unit tests (Agg backend, no DB). Each `paint_*` function is tested by constructing a `SectionPlotFigure` and asserting on `plot_handles` / `ax_main.texts`. No widget needed because painters are stateless renderers.
- **export_worker**: Existing QThread tests are suppressed from coverage because `coverage.py` doesn't track threads. A `.coveragerc` fix restores them; we add the missing error-path test.

All test classes inherit from `MidvattenTestSpatialiteDbSv`, use `@pytest.mark.spatialite`, and mock `MessagebarAndLog`.

**Tech Stack:** pytest, unittest.mock, matplotlib (Agg backend), SpatiaLite, QgsVectorLayer, PyQt5/PyQt6 (QThread, QEventLoop)

---

## File Structure

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `test/test_wqualreport.py` | Full-flow `show()` tests + helper-method tests |
| Create | `test/test_sectionplot_painters.py` | Unit tests for each `paint_*` function |
| Create | `.coveragerc` | Enable thread-aware coverage measurement |
| Modify | `test/test_export_engine.py` | Add error-path test for ExportWorker |

---

## Task 1: Integration tests for `Wqualreport`

**Files:**
- Create: `test/test_wqualreport.py`

### Context

`Wqualreport.show()` is the user entry point:
1. Gets the active QGIS layer and selected features
2. For each selected feature's obsid, calls `get_data()` to query `w_qual_lab`
3. Calls `write_html_report()` to write HTML
4. Opens the HTML in a browser

The primary test replicates this entire flow by:
- Inserting real `obs_points` + `w_qual_lab` rows
- Creating a real `QgsVectorLayer` from the `obs_points` table with a selected feature
- Mocking `iface.activeLayer()` to return that layer
- Mocking `open_report_in_browser` to skip the browser
- Calling `show()` and reading the generated HTML file

Secondary tests call `get_data()` and `write_html_report()` directly to cover branches the integration test cannot easily vary (e.g. no-params path, sorting column).

**settingsdict keys used:**

| key | default value | meaning |
|-----|--------------|---------|
| `"wqualtable"` | `"w_qual_lab"` | table to query |
| `"wqual_paramcolumn"` | `"parameter"` | parameter name column |
| `"wqual_valuecolumn"` | `"reading_txt"` | value column |
| `"wqual_date_time_format"` | `"YYYY-MM-DD"` | controls substr vs full date match |
| `"wqual_unitcolumn"` | `"unit"` | unit column (empty = no unit) |
| `"wqual_sortingcolumn"` | `""` | sorting column (empty = no sort col) |

`nr_header_rows` is 2 without a sorting column, 3 with one.

**Return structure of `get_data()`:**
- `report_table[0]` = `["obsid", obsid, obsid, …]`
- `report_table[1]` = `["date_time", dt1, dt2, …]`
- `report_table[2:]` = `["parameter, unit", value, value, …]`

---

- [ ] **Step 1: Write the failing tests**

Create `test/test_wqualreport.py`:

```python
"""Integration tests for Wqualreport — tests the full user-triggered flow."""

import io
import os
from unittest import mock

import pytest
from qgis.core import QgsProject, QgsVectorLayer

from midvatten.test import utils_for_tests
from midvatten.tools.utils import db_utils
from midvatten.tools.wqualreport import Wqualreport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_wqual_data(obsid: str = "OBS1") -> None:
    """Insert one obs_point and several w_qual_lab rows for *obsid*."""
    db_utils.sql_alter_db(
        f"""INSERT INTO obs_points (obsid, geometry)
            VALUES ('{obsid}', ST_GeomFromText('POINT(0 0)', 3006))"""
    )
    rows = [
        ("Iron", "mg/l", "1.5", "2024-01-01 10:00"),
        ("Calcium", "mg/l", "120.0", "2024-01-01 10:00"),
        ("Iron", "mg/l", "2.0", "2024-06-01 10:00"),
        ("Calcium", "mg/l", "130.0", "2024-06-01 10:00"),
    ]
    for param, unit, reading_txt, date_time in rows:
        db_utils.sql_alter_db(
            f"""INSERT INTO w_qual_lab
                    (obsid, report, parameter, unit, reading_txt, date_time)
                VALUES
                    ('{obsid}', 'R1', '{param}', '{unit}', '{reading_txt}', '{date_time}')"""
        )


def _make_obs_points_layer() -> QgsVectorLayer:
    """Create a QgsVectorLayer from obs_points and select all features."""
    dbconnection = db_utils.DbConnectionManager()
    uri = dbconnection.uri
    uri.setDataSource("", "obs_points", "geometry", "", "rowid")
    dbtype = db_utils.get_dbtype(dbconnection.dbtype)
    vlayer = QgsVectorLayer(uri.uri(), "obs_points_test", dbtype)
    QgsProject.instance().addMapLayer(vlayer)
    feature_ids = [f.id() for f in vlayer.getFeatures()]
    vlayer.selectByIds(feature_ids)
    dbconnection.closedb()
    return vlayer


def _report_path() -> str:
    from qgis.PyQt import QtCore
    return os.path.join(QtCore.QDir.tempPath(), "midvatten_reports", "w_qual_report.html")


def _default_settingsdict() -> dict:
    return {
        "wqualtable": "w_qual_lab",
        "wqual_paramcolumn": "parameter",
        "wqual_valuecolumn": "reading_txt",
        "wqual_date_time_format": "YYYY-MM-DD",
        "wqual_unitcolumn": "unit",
        "wqual_sortingcolumn": "",
        "database": "",
    }


# ---------------------------------------------------------------------------
# Integration test — full user flow
# ---------------------------------------------------------------------------

@pytest.mark.spatialite
class TestWqualreportSpatialite(utils_for_tests.MidvattenTestSpatialiteDbSv):

    @mock.patch("midvatten.tools.wqualreport.open_report_in_browser")
    @mock.patch("midvatten.tools.wqualreport.common_utils.start_waiting_cursor")
    @mock.patch("midvatten.tools.wqualreport.common_utils.stop_waiting_cursor")
    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_show_generates_html_with_selected_obsid(
        self, mock_messagebar, mock_stop, mock_start, mock_openurl
    ):
        """show() with a selected obs_point generates an HTML file with
        parameter names and values for that obsid."""
        _insert_wqual_data("OBS1")
        layer = _make_obs_points_layer()

        mock_iface = mock.MagicMock()
        mock_iface.activeLayer.return_value = layer
        self.midvatten.ms.settingsdict.update(_default_settingsdict())

        report = Wqualreport(mock_iface, self.midvatten.ms)
        report.show()

        print(f"{mock_messagebar.mock_calls=}")

        reportpath = _report_path()
        assert os.path.isfile(reportpath), "HTML report was not created"
        with open(reportpath, encoding="utf-8") as f:
            html = f.read()

        assert "OBS1" in html
        assert "Iron" in html
        assert "Calcium" in html
        assert "mg/l" in html
        assert mock_openurl.called

    @mock.patch("midvatten.tools.wqualreport.open_report_in_browser")
    @mock.patch("midvatten.tools.wqualreport.common_utils.start_waiting_cursor")
    @mock.patch("midvatten.tools.wqualreport.common_utils.stop_waiting_cursor")
    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_show_two_obsids_both_appear_in_report(
        self, mock_messagebar, mock_stop, mock_start, mock_openurl
    ):
        """When two obs_points are selected, both appear in the HTML report."""
        _insert_wqual_data("OBS1")
        _insert_wqual_data("OBS2")
        layer = _make_obs_points_layer()

        mock_iface = mock.MagicMock()
        mock_iface.activeLayer.return_value = layer
        self.midvatten.ms.settingsdict.update(_default_settingsdict())

        report = Wqualreport(mock_iface, self.midvatten.ms)
        report.show()

        print(f"{mock_messagebar.mock_calls=}")

        reportpath = _report_path()
        assert os.path.isfile(reportpath)
        with open(reportpath, encoding="utf-8") as f:
            html = f.read()

        assert "OBS1" in html
        assert "OBS2" in html

    # -----------------------------------------------------------------------
    # Secondary: helper-method tests to cover branches not reachable via show()
    # -----------------------------------------------------------------------

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_get_data_returns_correct_shape(self, mock_messagebar):
        """get_data() returns a list with nr_header_rows + n_params rows."""
        _insert_wqual_data("OBS1")

        mock_iface = mock.MagicMock()
        self.midvatten.ms.settingsdict.update(_default_settingsdict())
        report = Wqualreport(mock_iface, self.midvatten.ms)
        report.settingsdict = _default_settingsdict()

        dbconn = db_utils.DbConnectionManager()
        try:
            table = report.get_data(obsid="OBS1", dbconnection=dbconn)
        finally:
            dbconn.closedb()

        print(f"{mock_messagebar.mock_calls=}")
        assert table is not False
        assert len(table) == 4       # 2 headers + 2 params
        assert len(table[0]) == 3   # label + 2 date columns
        assert table[0][0] == "obsid"
        assert table[1][0] == "date_time"
        assert table[0][1] == "OBS1"

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_get_data_no_parameters_returns_false(self, mock_messagebar):
        """get_data() returns False when obsid has no rows in w_qual_lab."""
        db_utils.sql_alter_db(
            "INSERT INTO obs_points (obsid, geometry)"
            " VALUES ('EMPTY', ST_GeomFromText('POINT(0 0)', 3006))"
        )
        mock_iface = mock.MagicMock()
        report = Wqualreport(mock_iface, self.midvatten.ms)
        report.settingsdict = _default_settingsdict()

        dbconn = db_utils.DbConnectionManager()
        try:
            result = report.get_data(obsid="EMPTY", dbconnection=dbconn)
        finally:
            dbconn.closedb()

        print(f"{mock_messagebar.mock_calls=}")
        assert result is False

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_get_data_with_sorting_column_has_three_header_rows(self, mock_messagebar):
        """When wqual_sortingcolumn is set, nr_header_rows == 3."""
        _insert_wqual_data("OBS1")

        mock_iface = mock.MagicMock()
        report = Wqualreport(mock_iface, self.midvatten.ms)
        report.settingsdict = {**_default_settingsdict(), "wqual_sortingcolumn": "report"}

        dbconn = db_utils.DbConnectionManager()
        try:
            table = report.get_data(obsid="OBS1", dbconnection=dbconn)
        finally:
            dbconn.closedb()

        print(f"{mock_messagebar.mock_calls=}")
        assert table is not False
        assert table[2][0] == "report"   # third header row label
        assert len(table) == 5           # 3 headers + 2 params

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_write_html_report_uses_th_for_headers_td_for_data(self, mock_messagebar):
        """write_html_report() uses <th> for header rows and <td> for data rows."""
        _insert_wqual_data("OBS1")

        mock_iface = mock.MagicMock()
        report = Wqualreport(mock_iface, self.midvatten.ms)
        report.settingsdict = _default_settingsdict()

        dbconn = db_utils.DbConnectionManager()
        try:
            table = report.get_data(obsid="OBS1", dbconnection=dbconn)
        finally:
            dbconn.closedb()

        buf = io.StringIO()
        report.write_html_report(table, buf)
        html = buf.getvalue()

        print(f"{mock_messagebar.mock_calls=}")
        assert "<th>" in html
        assert "<td>" in html
        assert "Iron" in html
        assert "Calcium" in html
```

- [ ] **Step 2: Run tests to verify they fail (not yet pass)**

```
python3 -m pytest test/test_wqualreport.py -x -v 2>&1 | head -40
```

Expected: tests are collected but fail. Common failure at this stage: `AttributeError` on the layer or `KeyError` on `settingsdict`. Both indicate the test fixtures aren't yet right — that's expected before implementation.

- [ ] **Step 3: Run the full set and confirm all pass**

```
python3 -m pytest test/test_wqualreport.py -v
```

Expected: `5 passed`. Troubleshooting:

- If `show()` raises `UnboundLocalError: report_data` — that is a bug in `wqualreport.py` (the variable is only assigned inside the loop, so if the loop body never runs it's unbound on line 92). Do NOT change reference data. Instead check that `_make_obs_points_layer()` actually selects features: add `assert vlayer.selectedFeatureCount() > 0` right after `selectByIds`.
- If `fieldNameIndex("obsid")` returns -1: the layer's obsid field may have a different case. Add a debug print of `[f.name() for f in vlayer.fields()]` and correct `"obsid"` if needed.
- If `io.StringIO` raises on binary write: change to `io.BytesIO` (unlikely — `write_html_report` writes strings).

- [ ] **Step 4: Commit**

```bash
git add test/test_wqualreport.py
git commit -m "test: integration tests for Wqualreport — full show() flow + helper methods"
```

---

## Task 2: Unit tests for `sectionplot/painters.py`

**Files:**
- Create: `test/test_sectionplot_painters.py`

### Context

`painters.py` functions are pure matplotlib renderers — they accept a `SectionPlotFigure` and raw data, draw onto `figure.ax_main`, and append handles to `figure.plot_handles`. No database or QGIS layers are involved for the six core paint functions.

**How to create a test figure:**

```python
import matplotlib
matplotlib.use("Agg")  # already applied by utils_for_tests but safe to repeat
import matplotlib.pyplot as plt
from midvatten.tools.sectionplot.figure import SectionPlotFigure

fig = plt.figure(FigureClass=SectionPlotFigure)
fig.ax_main = fig.add_subplot(111)
fig.plot_handles = []
fig.obsid_annotation = {}
```

**Minimal template dict** (taken from default_file string in `test_sectionplot_templates.py`):

```python
MINIMAL_TEMPLATE = {
    "geology_Axes_bar": {"DEFAULT": {"edgecolor": "black"}},
    "drillstop_Axes_plot": {
        "color": "black", "marker": "^", "markersize": 8, "linestyle": ""
    },
    "layer_Axes_annotate": {
        "va": "center", "xytext": (5, 0), "fontsize": 9,
        "bbox": {
            "alpha": 0.6, "fc": "white",
            "boxstyle": "square,pad=0.05", "edgecolor": "white",
        },
        "ha": "left", "textcoords": "offset points",
    },
    "obsid_Axes_bar": {"edgecolor": "black", "linewidth": 0.5, "fill": False},
    "obsid_Axes_annotate": {
        "va": "top", "xytext": (0, 10), "fontsize": 9,
        "bbox": {
            "alpha": 0.4, "fc": "white",
            "boxstyle": "square,pad=0.05", "edgecolor": "white",
        },
        "rotation": 0, "ha": "center", "textcoords": "offset points",
    },
}
```

**Functions covered:**

| Function | What it does |
|----------|-------------|
| `_qgis_color_str_to_mpl` | Converts `"r,g,b[,a]"` string → float tuple |
| `paint_bars` | Stratigraphy/hydrology bar chart |
| `paint_screen_bars` | Screen-interval bars |
| `paint_drill_stop` | Drill-stop marker line |
| `paint_layer_text` | Text annotations on bars |
| `paint_obsids` | Obsid label annotations + frame bars |

---

- [ ] **Step 1: Write the failing tests**

Create `test/test_sectionplot_painters.py`:

```python
"""Unit tests for sectionplot/painters.py pure rendering functions.

painters.py functions take a SectionPlotFigure (a matplotlib Figure subclass)
and draw onto figure.ax_main, appending handles to figure.plot_handles.
No real DB or QGIS layer is needed for these tests.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pytest
from unittest import mock

from midvatten.tools.sectionplot.figure import SectionPlotFigure
from midvatten.tools.sectionplot.painters import (
    _qgis_color_str_to_mpl,
    paint_bars,
    paint_screen_bars,
    paint_drill_stop,
    paint_layer_text,
    paint_obsids,
)

MINIMAL_TEMPLATE = {
    "geology_Axes_bar": {"DEFAULT": {"edgecolor": "black"}},
    "drillstop_Axes_plot": {
        "color": "black", "marker": "^", "markersize": 8, "linestyle": ""
    },
    "layer_Axes_annotate": {
        "va": "center", "xytext": (5, 0), "fontsize": 9,
        "bbox": {
            "alpha": 0.6, "fc": "white",
            "boxstyle": "square,pad=0.05", "edgecolor": "white",
        },
        "ha": "left", "textcoords": "offset points",
    },
    "obsid_Axes_bar": {"edgecolor": "black", "linewidth": 0.5},
    "obsid_Axes_annotate": {
        "va": "top", "xytext": (0, 10), "fontsize": 9,
        "bbox": {
            "alpha": 0.4, "fc": "white",
            "boxstyle": "square,pad=0.05", "edgecolor": "white",
        },
        "rotation": 0, "ha": "center", "textcoords": "offset points",
    },
}


def _make_figure() -> SectionPlotFigure:
    """Return a fresh SectionPlotFigure with ax_main configured."""
    fig = plt.figure(FigureClass=SectionPlotFigure)
    fig.ax_main = fig.add_subplot(111)
    fig.plot_handles = []
    fig.obsid_annotation = {}
    return fig


# ---------------------------------------------------------------------------
# _qgis_color_str_to_mpl — pure function, no DB, no mock needed
# ---------------------------------------------------------------------------

class TestQgisColorStrToMpl:
    def test_rgb_string(self):
        r, g, b = _qgis_color_str_to_mpl("255,128,0")
        assert abs(r - 1.0) < 1e-6
        assert abs(g - 128 / 255) < 1e-6
        assert abs(b - 0.0) < 1e-6

    def test_rgba_string(self):
        result = _qgis_color_str_to_mpl("255,0,0,128")
        assert len(result) == 4
        assert abs(result[3] - 128 / 255) < 1e-6

    def test_black(self):
        assert _qgis_color_str_to_mpl("0,0,0") == (0.0, 0.0, 0.0)

    def test_white(self):
        assert _qgis_color_str_to_mpl("255,255,255") == (1.0, 1.0, 1.0)


# ---------------------------------------------------------------------------
# paint_bars
# ---------------------------------------------------------------------------

@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
class TestPaintBars:
    def test_adds_one_handle_per_type(self, mock_messagebar):
        """paint_bars appends one BarContainer per bar type."""
        fig = _make_figure()
        bars_dict = {
            "sand":   {"x": [2.0], "height": [2.0], "bottom": [-2.0]},
            "gravel": {"x": [8.0], "height": [3.0], "bottom": [-3.0]},
        }
        color_dict = {"sand": "yellow", "gravel": "gray"}

        paint_bars(fig, bars_dict, MINIMAL_TEMPLATE, color_dict)

        print(f"{mock_messagebar.mock_calls=}")
        assert len(fig.plot_handles) == 2

    def test_single_type(self, mock_messagebar):
        fig = _make_figure()
        bars_dict = {"clay": {"x": [1.0], "height": [5.0], "bottom": [-5.0]}}
        color_dict = {"clay": "brown"}

        paint_bars(fig, bars_dict, MINIMAL_TEMPLATE, color_dict)

        print(f"{mock_messagebar.mock_calls=}")
        assert len(fig.plot_handles) == 1

    def test_invalid_color_falls_back_to_white(self, mock_messagebar):
        """paint_bars recovers when the color string is invalid."""
        fig = _make_figure()
        bars_dict = {"rock": {"x": [1.0], "height": [1.0], "bottom": [0.0]}}
        color_dict = {"rock": "not-a-color"}

        paint_bars(fig, bars_dict, MINIMAL_TEMPLATE, color_dict)

        print(f"{mock_messagebar.mock_calls=}")
        # The fallback bar is still rendered (white), so one handle is still present.
        assert len(fig.plot_handles) == 1

    def test_bar_label_is_type_name(self, mock_messagebar):
        """The bar container's label matches the geology type name."""
        fig = _make_figure()
        bars_dict = {"limestone": {"x": [3.0], "height": [4.0], "bottom": [-4.0]}}
        color_dict = {"limestone": "beige"}

        paint_bars(fig, bars_dict, MINIMAL_TEMPLATE, color_dict)

        print(f"{mock_messagebar.mock_calls=}")
        assert fig.plot_handles[0].get_label() == "limestone"


# ---------------------------------------------------------------------------
# paint_screen_bars
# ---------------------------------------------------------------------------

@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
class TestPaintScreenBars:
    def test_adds_handle_per_screenshort(self, mock_messagebar):
        fig = _make_figure()
        bars_dict = {
            "open": {"x": [2.0], "height": [1.0], "bottom": [-3.0]},
        }

        paint_screen_bars(fig, bars_dict, style_dict={}, width=1.0)

        print(f"{mock_messagebar.mock_calls=}")
        assert len(fig.plot_handles) == 1

    def test_two_screen_types(self, mock_messagebar):
        fig = _make_figure()
        bars_dict = {
            "open":  {"x": [2.0], "height": [1.0], "bottom": [-3.0]},
            "cased": {"x": [5.0], "height": [2.0], "bottom": [-5.0]},
        }

        paint_screen_bars(fig, bars_dict, style_dict={}, width=1.0)

        print(f"{mock_messagebar.mock_calls=}")
        assert len(fig.plot_handles) == 2

    def test_custom_style_applied(self, mock_messagebar):
        """Style from style_dict is used when screenshort key matches."""
        fig = _make_figure()
        bars_dict = {"cased": {"x": [3.0], "height": [2.0], "bottom": [-5.0]}}
        style_dict = {
            "cased": {
                "facecolor": "blue", "edgecolor": "red",
                "hatch": "xx", "linewidth": 2.0,
            }
        }

        paint_screen_bars(fig, bars_dict, style_dict=style_dict, width=1.0)

        print(f"{mock_messagebar.mock_calls=}")
        assert len(fig.plot_handles) == 1


# ---------------------------------------------------------------------------
# paint_drill_stop
# ---------------------------------------------------------------------------

@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
class TestPaintDrillStop:
    def test_adds_one_line_handle(self, mock_messagebar):
        fig = _make_figure()
        drillstops = [(2.0, -5.0), (8.0, -8.0)]

        paint_drill_stop(fig, drillstops, MINIMAL_TEMPLATE, drillstop_label="drillstop")

        print(f"{mock_messagebar.mock_calls=}")
        assert len(fig.plot_handles) == 1

    def test_label_used_in_legend(self, mock_messagebar):
        """The drillstop_label appears as the artist's label."""
        fig = _make_figure()
        drillstops = [(1.0, -3.0)]

        paint_drill_stop(fig, drillstops, MINIMAL_TEMPLATE, drillstop_label="bedrock hit")

        print(f"{mock_messagebar.mock_calls=}")
        assert fig.plot_handles[0].get_label() == "bedrock hit"


# ---------------------------------------------------------------------------
# paint_layer_text
# ---------------------------------------------------------------------------

@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
class TestPaintLayerText:
    def test_annotates_non_none_texts(self, mock_messagebar):
        fig = _make_figure()
        layer_texts = {
            "geoshort": {(2.0, -1.0): "sand", (8.0, -1.5): "gravel"}
        }

        paint_layer_text(
            fig, layer_texts, "geoshort",
            text_alignment="center", barwidth=1.0,
            template=MINIMAL_TEMPLATE,
        )

        print(f"{mock_messagebar.mock_calls=}")
        texts = [t.get_text() for t in fig.ax_main.texts]
        assert "sand" in texts
        assert "gravel" in texts

    def test_none_text_skipped(self, mock_messagebar):
        """None text values produce no annotation."""
        fig = _make_figure()
        layer_texts = {"geoshort": {(2.0, -1.0): None, (8.0, -1.5): "clay"}}

        paint_layer_text(
            fig, layer_texts, "geoshort",
            text_alignment="center", barwidth=1.0,
            template=MINIMAL_TEMPLATE,
        )

        print(f"{mock_messagebar.mock_calls=}")
        texts = [t.get_text() for t in fig.ax_main.texts]
        assert len(texts) == 1
        assert "clay" in texts

    def test_edge_alignment_shifts_x(self, mock_messagebar):
        """Edge alignment produces a different x than center alignment."""
        fig_center = _make_figure()
        fig_edge = _make_figure()
        layer_texts = {"geoshort": {(2.0, -1.0): "sand"}}

        paint_layer_text(
            fig_center, layer_texts, "geoshort",
            text_alignment="center", barwidth=1.0, template=MINIMAL_TEMPLATE,
        )
        paint_layer_text(
            fig_edge, layer_texts, "geoshort",
            text_alignment="edge", barwidth=1.0, template=MINIMAL_TEMPLATE,
        )

        print(f"{mock_messagebar.mock_calls=}")
        x_center = fig_center.ax_main.texts[0].get_position()[0]
        x_edge = fig_edge.ax_main.texts[0].get_position()[0]
        assert x_edge != x_center


# ---------------------------------------------------------------------------
# paint_obsids
# ---------------------------------------------------------------------------

@mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
class TestPaintObsids:
    def test_frame_bar_added_when_stratigraphy_enabled(self, mock_messagebar):
        fig = _make_figure()
        z_data = {"P1": {"z": 10.0, "barheight": 5.0, "bottom": -5.0}}
        obsids_x_position = {"P1": 2.0}

        paint_obsids(
            fig, z_data, obsids_x_position, MINIMAL_TEMPLATE,
            barwidth=1.0, plot_stratigraphy=True, plot_hydrology=False,
            plot_labels=False,
        )

        print(f"{mock_messagebar.mock_calls=}")
        assert len(fig.plot_handles) == 1

    def test_frame_bar_added_when_hydrology_enabled(self, mock_messagebar):
        fig = _make_figure()
        z_data = {"P1": {"z": 10.0, "barheight": 5.0, "bottom": -5.0}}
        obsids_x_position = {"P1": 2.0}

        paint_obsids(
            fig, z_data, obsids_x_position, MINIMAL_TEMPLATE,
            barwidth=1.0, plot_stratigraphy=False, plot_hydrology=True,
            plot_labels=False,
        )

        print(f"{mock_messagebar.mock_calls=}")
        assert len(fig.plot_handles) == 1

    def test_no_frame_bar_when_neither_enabled(self, mock_messagebar):
        fig = _make_figure()
        z_data = {"P1": {"z": 10.0, "barheight": 5.0, "bottom": -5.0}}
        obsids_x_position = {"P1": 2.0}

        paint_obsids(
            fig, z_data, obsids_x_position, MINIMAL_TEMPLATE,
            barwidth=1.0, plot_stratigraphy=False, plot_hydrology=False,
            plot_labels=False,
        )

        print(f"{mock_messagebar.mock_calls=}")
        assert len(fig.plot_handles) == 0

    def test_label_annotations_added_when_plot_labels_true(self, mock_messagebar):
        fig = _make_figure()
        fig.obsid_annotation = {"P1": (2.0, 10.5)}
        z_data = {"P1": {"z": 10.0, "barheight": 5.0, "bottom": -5.0}}
        obsids_x_position = {"P1": 2.0}

        paint_obsids(
            fig, z_data, obsids_x_position, MINIMAL_TEMPLATE,
            barwidth=1.0, plot_stratigraphy=False, plot_hydrology=False,
            plot_labels=True,
        )

        print(f"{mock_messagebar.mock_calls=}")
        texts = [t.get_text() for t in fig.ax_main.texts]
        assert "P1" in texts

    def test_zero_barheight_skipped(self, mock_messagebar):
        """An obsid with barheight=0 produces no frame bar."""
        fig = _make_figure()
        z_data = {"P1": {"z": 10.0, "barheight": 0, "bottom": 0}}
        obsids_x_position = {"P1": 2.0}

        paint_obsids(
            fig, z_data, obsids_x_position, MINIMAL_TEMPLATE,
            barwidth=1.0, plot_stratigraphy=True, plot_hydrology=False,
            plot_labels=False,
        )

        print(f"{mock_messagebar.mock_calls=}")
        assert len(fig.plot_handles) == 0
```

- [ ] **Step 2: Run tests to see initial failures**

```
python3 -m pytest test/test_sectionplot_painters.py -x -v
```

Expected: collected, then possibly `ImportError` if `_qgis_color_str_to_mpl` is not exported. Fix: confirm its spelling in `painters.py` (`grep -n "_qgis_color_str_to_mpl" tools/sectionplot/painters.py`).

- [ ] **Step 3: Run all painter tests and confirm they pass**

```
python3 -m pytest test/test_sectionplot_painters.py -v
```

Expected: all tests pass. Likely failure cause: `"fill": False` in `MINIMAL_TEMPLATE["obsid_Axes_bar"]` is not a valid matplotlib `bar()` kwarg. If so, remove `"fill": False` from that key in the template defined in the test file.

- [ ] **Step 4: Commit**

```bash
git add test/test_sectionplot_painters.py
git commit -m "test: unit tests for sectionplot/painters.py paint_* functions"
```

---

## Task 3: Fix ExportWorker coverage + add error-path test

**Files:**
- Create: `.coveragerc`
- Modify: `test/test_export_engine.py`

### Context

`tools/export_worker.py` shows 47% coverage (lines 44–78 uncovered), but three QThread tests already exist in `TestExportEngine` (lines 730, 777, 826). The coverage gap is because `coverage.py` does not instrument code running in Python threads by default.

**Fix 1:** Add `.coveragerc` with `concurrency = thread`. This alone will make the existing tests cover the success and cancel paths in `run()`.

**Fix 2:** The error path (line 76–78: `except Exception: … self.error.emit(…)`) genuinely is not covered by the existing tests — they don't trigger a `DbConnectionManager` failure inside the thread. Add one targeted test for this path.

---

- [ ] **Step 1: Create `.coveragerc`**

Create `.coveragerc` at the project root:

```ini
[run]
concurrency = thread
```

- [ ] **Step 2: Confirm existing worker tests now appear in coverage**

```
python3 -m pytest test/test_export_engine.py -m "not postgis" -k "worker" --cov=tools/export_worker --cov-report=term-missing -q
```

Expected: `tools/export_worker.py` goes from 47% to ≥ 80%. Lines 76–78 (error path) likely remain uncovered because the existing error test uses a bad path that fails before `connect2db()` is called inside the thread — a traceback may actually be emitted via `error`, but confirm by checking the missing lines.

- [ ] **Step 3: Add the error-path test to `TestExportEngine` in `test_export_engine.py`**

Open `test/test_export_engine.py` and find class `TestExportEngine`. Add the following method right after `test_worker_calls_export_bytea_as_bytes` (around line 870):

```python
    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_worker_error_path_emits_error_signal(self, mock_messagebar):
        """ExportWorker emits the error signal when source connect2db() fails."""
        from qgis.PyQt.QtCore import QEventLoop, QThread

        from midvatten.tools.export_worker import ExportWorker

        worker = ExportWorker(
            source_db_settings="/nonexistent/no_such_db.sqlite",
            dest_path="/tmp/wont_be_created.sqlite",
            obsid_points=(),
            obsid_lines=(),
            dest_srid="3006",
        )
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)

        errors: list[str] = []
        finished: list[str] = []
        worker.error.connect(errors.append)
        worker.finished.connect(finished.append)

        loop = QEventLoop()
        worker.finished.connect(loop.quit)
        worker.error.connect(loop.quit)
        thread.start()
        loop.exec_()
        thread.wait()

        print(f"{mock_messagebar.mock_calls=}")
        assert errors, "Expected error signal to be emitted"
        assert finished == [], "Expected no finished signal on error"
        assert "Traceback" in errors[0]
```

- [ ] **Step 4: Run only the new test to confirm it passes**

```
python3 -m pytest test/test_export_engine.py::TestExportEngine::test_worker_error_path_emits_error_signal -v
```

Expected: `PASSED`.

- [ ] **Step 5: Check final ExportWorker coverage**

```
python3 -m pytest test/test_export_engine.py -m "not postgis" --cov=tools/export_worker --cov-report=term-missing -q
```

Expected: ≥ 90% coverage. Remaining gaps will be `_close_connections` body when both connections are None (not reachable via public API).

- [ ] **Step 6: Commit**

```bash
git add .coveragerc test/test_export_engine.py
git commit -m "test: fix thread coverage tracking + add ExportWorker error-path test"
```

---

## Self-Review

### Spec coverage

| Requirement | Covered by |
|-------------|-----------|
| `Wqualreport.show()` full flow (selected feature → HTML) | Task 1 test 1 |
| Two selected obsids both appear in report | Task 1 test 2 |
| `get_data()` correct shape (2 headers + n params) | Task 1 test 3 |
| `get_data()` no-params → False | Task 1 test 4 |
| `get_data()` with sorting column → 3 headers | Task 1 test 5 |
| `write_html_report()` th/td structure | Task 1 test 6 |
| `_qgis_color_str_to_mpl` rgb/rgba/black/white | Task 2 (4 cases) |
| `paint_bars` one handle per type, label, invalid-color fallback | Task 2 |
| `paint_screen_bars` one/two types, custom style | Task 2 |
| `paint_drill_stop` handle + label | Task 2 |
| `paint_layer_text` annotation, None skip, edge vs center | Task 2 |
| `paint_obsids` frame bar on stratigraphy/hydrology/neither, labels, zero barheight | Task 2 |
| ExportWorker thread coverage | Task 3 `.coveragerc` |
| ExportWorker error path | Task 3 new test |

### Placeholder scan

No "TBD", "TODO", "similar to Task N", or "implement later" entries. All test code is complete.

### Type consistency

- `_make_figure()` → `SectionPlotFigure` used consistently across all paint tests.
- `bars_dict` shape `{"type": {"x": list, "height": list, "bottom": list}}` matches painter signatures.
- `drillstops` = `list[tuple[float, float]]` in both definition and test.
- `layer_texts` = `{column_name: {(x, z): text}}` consistent throughout.
- `MINIMAL_TEMPLATE` does not contain `"fill": False` in `obsid_Axes_bar` (removed to avoid invalid kwarg to `ax.bar()`).
