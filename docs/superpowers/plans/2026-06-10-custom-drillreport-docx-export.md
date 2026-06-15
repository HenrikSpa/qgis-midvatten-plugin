# Custom General Report Word (.docx) Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the custom general report dialog write a compact .docx file directly (tables kept on one page via Word's own keep-together mechanics), selected via an output-format radio button, with python-docx as an optional dependency.

**Architecture:** Shared data collection and value formatting move from `Drillreport.__init__` into a new dependency-free module `tools/custom_drillreport_core.py` (pattern precedent: `wqualreport_core.py`). The existing HTML renderer in `tools/custom_drillreport.py` and a new renderer `tools/custom_drillreport_docx.py` both consume it — this avoids a circular import between the dialog module and the docx module. HTML output must stay byte-identical (existing tests are the guard). The dialog gets an HTML/Word radio group; Word is disabled with a tooltip when python-docx is missing.

**Tech Stack:** Python 3 / PyQt (QGIS plugin), python-docx (optional, guarded module-level import), pytest with `@pytest.mark.spatialite`.

**Spec:** `docs/superpowers/specs/2026-06-10-custom-drillreport-docx-export-design.md`

**Status (2026-06-11):** ON HOLD — feature not yet confirmed as needed. The original worktree/branch was removed; create a fresh worktree from `ai_test` (per `superpowers:using-git-worktrees`) when/if implementation starts. Use `python3`, never `python`.

**Environment notes verified at planning time (2026-06-10):** python-docx 1.2.0 importable in the dev environment; OSGeo4W v2 index has no docx package but ships `python3-lxml` (python-docx's only compiled dependency) and `python3-openpyxl` (Excel-only, not usable for Word). Qt's `QTextDocumentWriter` ODT route was tested and rejected — see the spec's "Alternatives considered" section.

**File map:**

| File | Action | Responsibility |
|---|---|---|
| `tools/custom_drillreport_core.py` | Create | Data collection (`collect_report_data`, `ObsidReportData`) and formatting helpers shared by both renderers |
| `tools/custom_drillreport.py` | Modify | Dialog (`DrillreportUi`) + HTML renderer (`Drillreport`); consumes core; radio handling and Word export flow |
| `tools/custom_drillreport_docx.py` | Create | Optional-import docx renderer (`DocxReportWriter`, `DOCX_AVAILABLE`, OOXML helpers) |
| `ui/custom_drillreport.ui` | Modify | Output-format radio group |
| `test/test_custom_drillreport_core.py` | Create | Pure-function tests + a spatialite `collect_report_data` test |
| `test/test_custom_drillreport_docx_spatialite.py` | Create | Renderer tests + dialog Word-flow tests |
| `test/test_custom_drillreport_ui_spatialite.py` | Unchanged | Byte-identical HTML guard — must keep passing, never edit expectations |

---

### Task 1: Core module — formatting helpers (pure functions)

**Files:**
- Create: `tools/custom_drillreport_core.py`
- Test: `test/test_custom_drillreport_core.py`

- [ ] **Step 1: Write the failing tests**

Create `test/test_custom_drillreport_core.py`:

```python
"""
Tests for the shared data/formatting helpers of the custom drill report.
"""

from unittest import mock

import pytest

from midvatten.test import utils_for_tests
from midvatten.tools.custom_drillreport_core import (
    build_strat_rows,
    build_two_col_rows,
    collect_report_data,
    format_value,
    get_strat_header_translations,
)
from midvatten.tools.utils import db_utils


class TestFormatValue:
    def test_null_string_becomes_empty(self):
        assert format_value("NULL") == ""

    def test_none_becomes_empty(self):
        assert format_value(None) == ""

    def test_plain_string_passes_through(self):
        assert format_value("sand") == "sand"

    def test_rounding_caps_at_existing_decimals(self):
        # rounding gives MAX precision; existing shorter precision is kept
        assert format_value("1.2", rounding="4") == "1.2"

    def test_rounding_truncates_long_decimals(self):
        assert format_value("1.23456", rounding="2") == "1.23"

    def test_rounding_integer_value_pads(self):
        assert format_value("5", rounding="2") == "5.00"

    def test_decimal_separator_replaced(self):
        assert format_value("1.5", decimal_separator=",") == "1,5"

    def test_rounding_then_separator(self):
        assert format_value("1.23456", rounding="2", decimal_separator=",") == "1,23"

    def test_non_numeric_with_rounding_untouched(self):
        assert format_value("sand", rounding="2") == "sand"


class TestBuildTwoColRows:
    def test_basic_rows(self):
        rows = build_two_col_rows([("h_gs", "5.0")], [], False, ".")
        assert rows == [("h_gs", "5.0")]

    def test_skip_empty_skips_empty_and_null(self):
        data = [("a", ""), ("b", "NULL"), ("c", "x")]
        rows = build_two_col_rows(data, [], True, ".")
        assert rows == [("c", "x")]

    def test_skip_empty_false_keeps_empty(self):
        data = [("a", "NULL")]
        rows = build_two_col_rows(data, [], False, ".")
        assert rows == [("a", "")]

    def test_rounding_applied_per_index(self):
        data = [("a", "1.23456"), ("b", "1.23456")]
        rows = build_two_col_rows(data, ["2", None], False, ".")
        assert rows == [("a", "1.23"), ("b", "1.23456")]


class TestBuildStratRows:
    def test_depth_column_joins_top_and_bot(self):
        strat_data = [("0.0", "1.0", "sand")]
        rows = build_strat_rows(
            strat_data, ["depth", "geology"], ["depthtop", "depthbot", "geology"], "."
        )
        assert rows == [["0.0 - 1.0", "sand"]]

    def test_depth_with_decimal_separator(self):
        strat_data = [("0.5", "1.5", "sand")]
        rows = build_strat_rows(
            strat_data, ["depth", "geology"], ["depthtop", "depthbot", "geology"], ","
        )
        assert rows == [["0,5 - 1,5", "sand"]]

    def test_null_values_become_empty(self):
        strat_data = [("NULL", "NULL", "NULL")]
        rows = build_strat_rows(
            strat_data, ["depth", "geology"], ["depthtop", "depthbot", "geology"], "."
        )
        assert rows == [[" - ", ""]]

    def test_header_translations_contain_known_columns(self):
        headers = get_strat_header_translations()
        for col in ("depth", "depthtop", "depthbot", "geology", "geoshort",
                    "capacity", "development", "comment", "stratid"):
            assert col in headers


@pytest.mark.spatialite
class TestCollectReportData(utils_for_tests.MidvattenTestSpatialiteDbSv):
    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_collect_report_data_basic(self, mock_messagebar):
        db_utils.sql_alter_db(
            """INSERT INTO obs_points (obsid, east, north, h_gs, geometry)
               VALUES ('OP1', 633466, 711659, 5,
               ST_GeomFromText('POINT(633466 711659)', 3006))"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO stratigraphy (obsid, stratid, depthtop, depthbot,
               geology, geoshort, capacity, development)
               VALUES ('OP1', 1, 0, 1, 'sand', 'sand', '3', 'j')"""
        )
        records, strat_sql_columns_list = collect_report_data(
            ["OP1"],
            ["h_gs"],
            ["east", "north"],
            ["depth", "geology"],
            True,
        )
        print(f"{mock_messagebar.mock_calls=}")
        assert len(records) == 1
        record = records[0]
        assert record.obsid == "OP1"
        assert record.general_data[0][1] == "5.0"
        # XY reference system row is appended when east/north requested
        assert any("EPSG" in str(v) for _h, v in record.geo_data)
        assert record.strat_data is not None
        # 'depth' is removed and depthtop/depthbot appended, so geology
        # (the remaining original column) comes first
        assert strat_sql_columns_list == ["geology", "depthtop", "depthbot"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest test/test_custom_drillreport_core.py -x -q`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'midvatten.tools.custom_drillreport_core'`

- [ ] **Step 3: Create the core module with the formatting helpers**

Create `tools/custom_drillreport_core.py` (data collection comes in Task 3; this step adds everything except `ObsidReportData`/`collect_report_data`):

```python
"""
Shared data collection and formatting for the custom general report
("drill report"). Consumed by both the html renderer in custom_drillreport.py
and the docx renderer in custom_drillreport_docx.py.
"""

from collections import OrderedDict

from qgis.PyQt.QtCore import QCoreApplication

from midvatten.tools.utils import common_utils, db_utils
from midvatten.tools.utils.string_utils import returnunicode as ru

_EMPTY_VALS = ("", "NULL")


def format_value(value, rounding=None, decimal_separator="."):
    """Normalize a raw db value for display.

    NULL/None become '', `rounding` (a digit string) caps the number of
    decimals without padding existing shorter values beyond their own
    precision, and the decimal separator is replaced last.
    """
    value = ru(value) if ru(value) is not None and ru(value) != "NULL" else ""
    if rounding is not None:
        try:
            float(value)
        except ValueError:
            pass
        else:
            int_and_dec = value.split(".")
            if len(int_and_dec) == 2:
                prec = min(len(int_and_dec[1]), int(rounding))
            else:
                prec = int(rounding)
            value = "{:.{prec}f}".format(float(value), prec=prec)
    if decimal_separator != ".":
        value = value.replace(".", decimal_separator)
    return value


def build_two_col_rows(data, column_rounding, skip_empty: bool, decimal_separator: str):
    """Format (header, value) pairs for a key/value table.

    Applies the skip_empty rule, per-index rounding and decimal separator.
    """
    rows = []
    for idx, (header, value) in enumerate(data):
        header = ru(header)
        value = ru(value) if ru(value) is not None and ru(value) != "NULL" else ""
        if skip_empty and not (value and value != header):
            continue
        try:
            rounding = column_rounding[idx]
        except IndexError:
            rounding = None
        rows.append((header, format_value(value, rounding, decimal_separator)))
    return rows


def get_strat_header_translations():
    return OrderedDict(
        [
            (
                "stratid",
                QCoreApplication.translate("Drillreport2_strat", "Layer number"),
            ),
            (
                "depth",
                QCoreApplication.translate("Drillreport2_strat", "level (m b gs)"),
            ),
            (
                "depthtop",
                QCoreApplication.translate(
                    "Drillreport2_strat", "top of layer (m b gs)"
                ),
            ),
            (
                "depthbot",
                QCoreApplication.translate(
                    "Drillreport2_strat", "bottom of layer (m b gs)"
                ),
            ),
            (
                "geology",
                QCoreApplication.translate(
                    "Drillreport2_strat", "geology, full text"
                ),
            ),
            (
                "geoshort",
                QCoreApplication.translate("Drillreport2_strat", "geology, short"),
            ),
            (
                "capacity",
                QCoreApplication.translate("Drillreport2_strat", "capacity"),
            ),
            (
                "development",
                QCoreApplication.translate("Drillreport2_strat", "development"),
            ),
            (
                "comment",
                QCoreApplication.translate("Drillreport2_strat", "comment"),
            ),
        ]
    )


def build_strat_rows(strat_data, strat_columns, strat_sql_columns_list, decimal_separator: str):
    """Format stratigraphy db rows into display strings, one list per row.

    The 'depth' pseudo column is rendered as 'depthtop - depthbot'.
    """
    rows = []
    for row in strat_data:
        out_row = []
        for col in strat_columns:
            if col == "depth":
                try:
                    depthtop_idx = strat_sql_columns_list.index("depthtop")
                    depthbot_idx = strat_sql_columns_list.index("depthbot")
                except ValueError:
                    common_utils.MessagebarAndLog.critical(
                        bar_msg=QCoreApplication.translate(
                            "Drillreport2",
                            "Programming error, depthtop and depthbot columns was supposed to exist",
                        )
                    )
                    out_row.append(" ")
                else:
                    depthtop = (
                        ""
                        if row[depthtop_idx] == "NULL"
                        else row[depthtop_idx].replace(".", decimal_separator)
                    )
                    depthbot = (
                        ""
                        if row[depthbot_idx] == "NULL"
                        else row[depthbot_idx].replace(".", decimal_separator)
                    )
                    out_row.append(" - ".join([depthtop, depthbot]))
            else:
                value_idx = strat_sql_columns_list.index(col)
                value = "" if row[value_idx] == "NULL" else row[value_idx]
                if col in ("depthtop", "depthbot") and decimal_separator != ".":
                    value = value.replace(".", decimal_separator)
                out_row.append(value)
        rows.append(out_row)
    return rows
```

Note: `db_utils` is imported now even though only Task 3 uses it — keep it; ruff will not flag it after Task 3, and if you run ruff between tasks just leave the import in place (add `collect_report_data` in Task 3 before running `ruff check --fix .`, or run it only after Task 3).

- [ ] **Step 4: Run the pure-function tests, verify they pass (collect test still fails)**

Run: `python3 -m pytest test/test_custom_drillreport_core.py -q -k "not collect"`
Expected: PASS (TestFormatValue, TestBuildTwoColRows, TestBuildStratRows all green). The import of `collect_report_data` at module top will fail — so first comment NOTHING out; instead expect collection error. **Adjust:** to keep TDD green at this point, temporarily stub in the same file at the bottom of `tools/custom_drillreport_core.py`:

```python
def collect_report_data(*args, **kwargs):  # implemented in a later commit
    raise NotImplementedError
```

and a placeholder dataclass is NOT needed yet. Then:

Run: `python3 -m pytest test/test_custom_drillreport_core.py -q -k "not collect"`
Expected: PASS
Run: `python3 -m pytest test/test_custom_drillreport_core.py -q -k "collect"`
Expected: FAIL with NotImplementedError (this stays red until Task 3).

- [ ] **Step 5: Commit**

```bash
git add tools/custom_drillreport_core.py test/test_custom_drillreport_core.py
git commit -m "feat: shared formatting helpers for custom drill report (core module)"
```

---

### Task 2: HTML renderer consumes the core helpers (byte-identical output)

**Files:**
- Modify: `tools/custom_drillreport.py` (methods `write_two_col_table`, `write_strat_data`, `write_comment_data`; module imports)
- Test: existing `test/test_custom_drillreport_ui_spatialite.py` (do not edit)

- [ ] **Step 1: Update imports in `tools/custom_drillreport.py`**

Replace:

```python
from collections import OrderedDict
```

with nothing (delete the line — `OrderedDict` will no longer be used in this file after this task), and add below the existing midvatten imports:

```python
from midvatten.tools.custom_drillreport_core import (
    _EMPTY_VALS,
    build_strat_rows,
    build_two_col_rows,
    get_strat_header_translations,
)
```

Delete the module-level line `_EMPTY_VALS = ("", "NULL")` from `custom_drillreport.py` (it now comes from core).

- [ ] **Step 2: Replace the body loop of `write_two_col_table`**

The method keeps its exact signature. Replace everything from `rpt += r"""<p style=...` down to (and including) the `for idx, header_value in enumerate(data):` loop with:

```python
        rpt += r"""<p style="font-family:'Ubuntu'; font-size:8pt; font-weight:400; font-style:normal;">"""
        for header, value in build_two_col_rows(
            data, column_rounding, skip_empty, decimal_separator
        ):
            try:
                rpt += rf"""<TR VALIGN=TOP><TD WIDTH=33%><P><font size=1>{header}</font></P></TD><TD WIDTH=50%><P><font size=1>{value}</font></P></TD></TR>"""
            except UnicodeEncodeError:
                common_utils.MessagebarAndLog.critical(
                    bar_msg=QCoreApplication.translate(
                        "custom_drillreport",
                        "Writing drillreport failed, see log message panel",
                    ),
                    log_msg=QCoreApplication.translate(
                        "custom_drillreport",
                        "Writing header %s and value %s failed",
                    )
                    % (header, value),
                )
                raise
        rpt += r"""</p>"""
        rpt += r"""</TABLE>"""
        return rpt
```

(The old inline normalization/skip_empty/rounding/separator code is deleted; `build_two_col_rows` reproduces it exactly. Note for the reviewer: the old skip_empty branch `if value and value != "NULL" and value != header:` contained a float-test that did nothing; `not (value and value != header)` after NULL-normalization is equivalent.)

- [ ] **Step 3: Replace the row loop of `write_strat_data`**

In `write_strat_data`, replace the inline `headers_txt = OrderedDict([...])` literal with:

```python
        headers_txt = get_strat_header_translations()
```

and replace the whole `for rownr, row in enumerate(strat_data):` loop (everything between the header `</TR>` write and `rpt += r"""</p>"""`) with:

```python
            for row_values in build_strat_rows(
                strat_data, strat_columns, strat_sql_columns_list, decimal_separator
            ):
                rpt += r"""<TR VALIGN=TOP>"""
                for value in row_values:
                    rpt += rf"""<TD><P><font size=1>{value}</font></P></TD>"""
                rpt += r"""</TR>"""
```

- [ ] **Step 4: Run the existing HTML test file (byte-identical guard)**

Run: `python3 -m pytest test/test_custom_drillreport_ui_spatialite.py test/test_custom_drillreport_core.py -q -k "not collect"`
Expected: PASS, every test. If any HTML assertion fails, the refactor changed output — fix the implementation, never the test (see CLAUDE.md "Never change test reference data").

- [ ] **Step 5: Commit**

```bash
git add tools/custom_drillreport.py
git commit -m "refactor: html drill report renderer uses shared core formatting helpers"
```

---

### Task 3: Core module — `ObsidReportData` + `collect_report_data`

**Files:**
- Modify: `tools/custom_drillreport_core.py` (replace stub)
- Modify: `tools/custom_drillreport.py` (`Drillreport.__init__`)
- Test: `test/test_custom_drillreport_core.py` (the `collect` test from Task 1, currently red)

- [ ] **Step 1: Run the red test to confirm starting state**

Run: `python3 -m pytest test/test_custom_drillreport_core.py -q -k "collect"`
Expected: FAIL with NotImplementedError

- [ ] **Step 2: Implement `ObsidReportData` and `collect_report_data` in core**

In `tools/custom_drillreport_core.py`: add `from dataclasses import dataclass` to the imports (top, stdlib group), delete the `collect_report_data` stub, and add:

```python
@dataclass
class ObsidReportData:
    """All display data for one obsid, renderer-agnostic."""

    obsid: str
    general_data: list
    general_rounding: list
    geo_data: list
    geo_rounding: list
    strat_data: list
    comment_data: list


OBS_POINTS_COLS = [
    "obsid",
    "name",
    "place",
    "type",
    "length",
    "drillstop",
    "diam",
    "material",
    "screen",
    "capacity",
    "drilldate",
    "wmeas_yn",
    "wlogg_yn",
    "east",
    "north",
    "ne_accur",
    "ne_source",
    "h_toc",
    "h_tocags",
    "h_gs",
    "h_accur",
    "h_syst",
    "h_source",
    "source",
    "com_onerow",
    "com_html",
]


def _obs_points_translations():
    return {
        "obsid": QCoreApplication.translate("Drillreport2", "obsid"),
        "name": QCoreApplication.translate("Drillreport2", "name"),
        "place": QCoreApplication.translate("Drillreport2", "place"),
        "type": QCoreApplication.translate("Drillreport2", "type"),
        "length": QCoreApplication.translate("Drillreport2", "length"),
        "drillstop": QCoreApplication.translate("Drillreport2", "drillstop"),
        "diam": QCoreApplication.translate("Drillreport2", "diam"),
        "material": QCoreApplication.translate("Drillreport2", "material"),
        "screen": QCoreApplication.translate("Drillreport2", "screen"),
        "capacity": QCoreApplication.translate("Drillreport2", "capacity"),
        "drilldate": QCoreApplication.translate("Drillreport2", "drilldate"),
        "wmeas_yn": QCoreApplication.translate("Drillreport2", "wmeas_yn"),
        "wlogg_yn": QCoreApplication.translate("Drillreport2", "wlogg_yn"),
        "east": QCoreApplication.translate("Drillreport2", "east"),
        "north": QCoreApplication.translate("Drillreport2", "north"),
        "ne_accur": QCoreApplication.translate("Drillreport2", "ne_accur"),
        "ne_source": QCoreApplication.translate("Drillreport2", "ne_source"),
        "h_toc": QCoreApplication.translate("Drillreport2", "h_toc"),
        "h_tocags": QCoreApplication.translate("Drillreport2", "h_tocags"),
        "h_gs": QCoreApplication.translate("Drillreport2", "h_gs"),
        "h_accur": QCoreApplication.translate("Drillreport2", "h_accur"),
        "h_syst": QCoreApplication.translate("Drillreport2", "h_syst"),
        "h_source": QCoreApplication.translate("Drillreport2", "h_source"),
        "source": QCoreApplication.translate("Drillreport2", "source"),
        "com_onerow": QCoreApplication.translate("Drillreport2", "com_onerow"),
        "com_html": QCoreApplication.translate("Drillreport2", "com_html"),
    }


def collect_report_data(
    obsids, general_metadata, geo_metadata, strat_columns, include_comments: bool
):
    """Query the db and slice the result into per-obsid display data.

    Returns (records, strat_sql_columns_list) where records is a list of
    ObsidReportData in obsid order.
    """
    obsids = sorted(set(obsids))
    obs_points_translations = _obs_points_translations()

    dbconnection = db_utils.DbConnectionManager()
    clause, args = dbconnection.in_clause(obsids)
    cols_sql = ", ".join([dbconnection.ident(c) for c in OBS_POINTS_COLS])
    sql = f"SELECT {cols_sql} FROM {dbconnection.ident('obs_points')} WHERE obsid IN {clause} ORDER BY obsid"
    all_obs_points_data = ru(
        db_utils.get_sql_result_as_dict(
            sql, dbconnection=dbconnection, execute_args=args
        )[1],
        keep_containers=True,
    )

    if strat_columns:
        strat_sql_columns_list = [x.split(";")[0] for x in strat_columns]
        if "depth" in strat_sql_columns_list:
            strat_sql_columns_list.extend(["depthtop", "depthbot"])
            strat_sql_columns_list.remove("depth")
            strat_sql_columns_list = [
                x for x in strat_sql_columns_list if x not in ("obsid")
            ]

        cols_sql = ", ".join([dbconnection.ident(c) for c in strat_sql_columns_list])
        strat_sql = f"SELECT obsid, {cols_sql} FROM stratigraphy WHERE obsid IN {clause} ORDER BY obsid, stratid"
        all_stratigrapy_data = ru(
            db_utils.get_sql_result_as_dict(
                strat_sql,
                dbconnection=dbconnection,
                execute_args=args,
            )[1],
            keep_containers=True,
        )
    else:
        all_stratigrapy_data = {}
        strat_sql_columns_list = []

    crs = ru(
        db_utils.sql_load_fr_db(
            """SELECT srid FROM geometry_columns where f_table_name = 'obs_points'""",
            dbconnection=dbconnection,
        )[1][0][0]
    )
    crsname = ru(db_utils.get_srid_name(crs, dbconnection=dbconnection))

    dbconnection.closedb()

    general_data_no_rounding = [x.split(";")[0] for x in general_metadata]
    general_rounding = [
        x.split(";")[1] if len(x.split(";")) == 2 else None for x in general_metadata
    ]
    geo_metadata_no_rounding = [x.split(";")[0] for x in geo_metadata]
    geo_rounding = [
        x.split(";")[1] if len(x.split(";")) == 2 else None for x in geo_metadata
    ]

    records = []
    for obsid in obsids:
        obs_points_data = all_obs_points_data[obsid][0]
        general_data = [
            (
                obs_points_translations.get(header, header),
                obs_points_data[OBS_POINTS_COLS.index(header) - 1],
            )
            for header in general_data_no_rounding
        ]
        if geo_metadata:
            geo_data = [
                (
                    obs_points_translations.get(header, header),
                    obs_points_data[OBS_POINTS_COLS.index(header) - 1],
                )
                for header in geo_metadata_no_rounding
            ]
            if (
                "east" in geo_metadata_no_rounding
                or "north" in geo_metadata_no_rounding
            ):
                geo_data.append(
                    (
                        QCoreApplication.translate(
                            "Drillreport2", "XY Reference system"
                        ),
                        "%s" % ("%s, " % crsname if crsname else "")
                        + "EPSG:"
                        + crs,
                    )
                )
        else:
            geo_data = []

        strat_data = all_stratigrapy_data.get(obsid, None)

        if include_comments:
            comment_data = [
                obs_points_data[OBS_POINTS_COLS.index(header) - 1]
                for header in ("com_onerow", "com_html")
                if all(
                    [
                        obs_points_data[OBS_POINTS_COLS.index(header) - 1]
                        is not None,
                        obs_points_data[OBS_POINTS_COLS.index(header) - 1].replace(
                            "NULL", ""
                        ),
                        obs_points_data[OBS_POINTS_COLS.index(header) - 1].strip(),
                        'text-indent:0px;"><br /></p>'
                        not in obs_points_data[OBS_POINTS_COLS.index(header) - 1],
                        'text-indent:0px;"></p>'
                        not in obs_points_data[OBS_POINTS_COLS.index(header) - 1],
                        'text-indent:0px;">NULL</p>'
                        not in obs_points_data[
                            OBS_POINTS_COLS.index(header) - 1
                        ].strip(),
                    ]
                )
            ]
        else:
            comment_data = []

        records.append(
            ObsidReportData(
                obsid=obsid,
                general_data=general_data,
                general_rounding=general_rounding,
                geo_data=geo_data,
                geo_rounding=geo_rounding if geo_metadata else [],
                strat_data=strat_data,
                comment_data=comment_data,
            )
        )
    return records, strat_sql_columns_list
```

(Every query, slicing expression and the comment filter are moved verbatim from `Drillreport.__init__` — including the `index(header) - 1` offset, which exists because `get_sql_result_as_dict` keys rows by the first column and returns the remaining columns as the tuple.)

- [ ] **Step 3: Rewrite `Drillreport.__init__` to consume `collect_report_data`**

In `tools/custom_drillreport.py`, add `collect_report_data` to the core import list:

```python
from midvatten.tools.custom_drillreport_core import (
    _EMPTY_VALS,
    build_strat_rows,
    build_two_col_rows,
    collect_report_data,
    get_strat_header_translations,
)
```

Replace the entire body of `Drillreport.__init__` (same signature) with:

```python
        reportfolder = os.path.join(QDir.tempPath(), "midvatten_reports")
        if not os.path.exists(reportfolder):
            os.makedirs(reportfolder)
        reportpath = os.path.join(reportfolder, "drill_report.html")

        if len(obsids) == 0:
            common_utils.pop_up_info(
                QCoreApplication.translate(
                    "Drillreport", "Must select one or more obsids!"
                )
            )
            return None

        obsids = sorted(set(obsids))

        records, strat_sql_columns_list = collect_report_data(
            obsids, general_metadata, geo_metadata, strat_columns, include_comments
        )

        f, rpt = self.open_file(", ".join(obsids), reportpath)
        rpt += r"""<html>"""
        for record in records:
            rpt += self.write_obsid(
                record.obsid,
                record.general_data,
                record.geo_data,
                record.strat_data,
                record.comment_data,
                strat_columns,
                header_in_table=header_in_table,
                skip_empty=skip_empty,
                general_metadata_header=general_metadata_header,
                geo_metadata_header=geo_metadata_header,
                strat_columns_header=strat_columns_header,
                comment_header=comment_header,
                general_rounding=record.general_rounding,
                geo_rounding=record.geo_rounding,
                strat_sql_columns_list=strat_sql_columns_list,
                topleft_topright_colwidths=topleft_topright_colwidths,
                general_colwidth=general_colwidth,
                geo_colwidth=geo_colwidth,
                decimal_separator=decimal_separator,
            )
            rpt += r"""<p>    </p>"""
            if empty_row_between_obsids:
                rpt += r"""<p>empty_row_between_obsids</p>"""

        rpt += r"""</html>"""
        f.write(rpt)
        self.close_file(f, reportpath)
```

The old `logopath`/`imgpath` variables were never used — they are intentionally dropped. The big translations dict, the queries and the per-obsid slicing all leave this file (now in core). `db_utils` may become unused in `custom_drillreport.py` after this — check with ruff and remove the import if so.

- [ ] **Step 4: Run core tests + HTML guard**

Run: `python3 -m pytest test/test_custom_drillreport_core.py test/test_custom_drillreport_ui_spatialite.py -q`
Expected: PASS, all tests including `test_collect_report_data_basic`.

- [ ] **Step 5: Commit**

```bash
git add tools/custom_drillreport_core.py tools/custom_drillreport.py
git commit -m "refactor: extract drill report data collection into custom_drillreport_core"
```

---

### Task 4: Docx module — availability flag, plain-text helper, OOXML helpers

**Files:**
- Create: `tools/custom_drillreport_docx.py`
- Test: `test/test_custom_drillreport_docx_spatialite.py`

- [ ] **Step 1: Write the failing tests**

Create `test/test_custom_drillreport_docx_spatialite.py`:

```python
"""
Tests for the docx renderer of the custom general report and the
Word-export flow of the DrillreportUi dialog.
"""

import os
from unittest import mock

import pytest

docx = pytest.importorskip("docx")

from docx import Document  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from qgis.PyQt import QtCore  # noqa: E402

from midvatten.test import utils_for_tests  # noqa: E402
from midvatten.test.test_custom_drillreport_ui_spatialite import (  # noqa: E402
    _insert_drillreport_test_data,
)
from midvatten.tools import custom_drillreport_docx  # noqa: E402
from midvatten.tools.custom_drillreport import DrillreportUi  # noqa: E402
from midvatten.tools.custom_drillreport_core import ObsidReportData  # noqa: E402


def _docx_path():
    folder = os.path.join(QtCore.QDir.tempPath(), "midvatten_reports")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "drill_report_test.docx")
    if os.path.exists(path):
        os.remove(path)
    return path


def _all_text(document):
    return "".join(t.text or "" for t in document.element.iter(qn("w:t")))


class TestDocxHelpers:
    def test_docx_available_is_true_here(self):
        assert custom_drillreport_docx.DOCX_AVAILABLE is True

    def test_html_to_plain_text_strips_tags(self):
        assert (
            custom_drillreport_docx.html_to_plain_text("<p>a <b>comment</b></p>")
            == "a comment"
        )

    def test_set_cant_split_adds_element(self):
        document = Document()
        table = document.add_table(rows=1, cols=1)
        custom_drillreport_docx._set_cant_split(table.rows[0])
        assert "cantSplit" in table.rows[0]._tr.xml

    def test_set_cant_split_is_idempotent(self):
        document = Document()
        table = document.add_table(rows=1, cols=1)
        custom_drillreport_docx._set_cant_split(table.rows[0])
        custom_drillreport_docx._set_cant_split(table.rows[0])
        assert table.rows[0]._tr.xml.count("cantSplit") == 1

    def test_set_fixed_layout(self):
        document = Document()
        table = document.add_table(rows=1, cols=1)
        custom_drillreport_docx._set_fixed_layout(table)
        assert 'w:type="fixed"' in table._tbl.tblPr.xml

    def test_set_cell_margins(self):
        document = Document()
        table = document.add_table(rows=1, cols=1)
        custom_drillreport_docx._set_cell_margins(table)
        assert "tblCellMar" in table._tbl.tblPr.xml
```

(The renderer and UI-flow test classes are added in Tasks 5 and 7 — this file grows.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest test/test_custom_drillreport_docx_spatialite.py -x -q`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'midvatten.tools.custom_drillreport_docx'`

- [ ] **Step 3: Create the docx module (helpers only)**

Create `tools/custom_drillreport_docx.py`:

```python
"""
Docx renderer for the custom general report ("drill report").

python-docx is an optional dependency: when it is missing, DOCX_AVAILABLE is
False and the Word output option in the dialog is disabled. Nothing else in
the plugin may import python-docx directly.
"""

from qgis.PyQt.QtGui import QTextDocument

try:
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt
except ImportError:
    Document = None

from midvatten.tools.custom_drillreport_core import (
    _EMPTY_VALS,
    build_strat_rows,
    build_two_col_rows,
    get_strat_header_translations,
)
from midvatten.tools.utils.string_utils import returnunicode as ru

DOCX_AVAILABLE = Document is not None

BODY_FONT_PT = 8
SECTION_HEADER_FONT_PT = 10
OBSID_FONT_PT = 12
PAGE_MARGIN_MM = 20
CONTENT_WIDTH_MM = 210 - 2 * PAGE_MARGIN_MM
TWIPS_PER_MM = 56.7


def html_to_plain_text(html: str) -> str:
    """Convert Qt rich-text html (com_html comments) to plain text."""
    doc = QTextDocument()
    doc.setHtml(html)
    return doc.toPlainText()


def _set_cant_split(row) -> None:
    """Forbid Word from splitting this table row across pages (w:cantSplit)."""
    tr_pr = row._tr.get_or_add_trPr()
    if tr_pr.find(qn("w:cantSplit")) is None:
        tr_pr.append(OxmlElement("w:cantSplit"))


def _set_fixed_layout(table) -> None:
    """Fixed table layout so explicit cell widths are respected."""
    table.autofit = False
    tbl_pr = table._tbl.tblPr
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tbl_pr.append(layout)


def _set_cell_margins(table, margin_mm: float = 0.5) -> None:
    """Compact cell padding (python-docx has no direct API for tblCellMar)."""
    tbl_pr = table._tbl.tblPr
    margins = OxmlElement("w:tblCellMar")
    for side in ("top", "left", "bottom", "right"):
        element = OxmlElement("w:%s" % side)
        element.set(qn("w:w"), str(int(margin_mm * TWIPS_PER_MM)))
        element.set(qn("w:type"), "dxa")
        margins.append(element)
    tbl_pr.append(margins)
```

(`_EMPTY_VALS`, `build_strat_rows`, `build_two_col_rows`, `get_strat_header_translations`, `ru` and the font constants are consumed by `DocxReportWriter` in Task 5 — the import block is complete now so it does not churn.)

- [ ] **Step 4: Run tests, verify pass**

Run: `python3 -m pytest test/test_custom_drillreport_docx_spatialite.py -x -q`
Expected: PASS (6 tests). Note: ruff may flag the not-yet-used core imports — that resolves in Task 5; if committing with `ruff check` enforced pre-commit, either implement Task 5 first in the same commit or add the writer skeleton. Default: just commit; the repo does not enforce ruff in hooks.

- [ ] **Step 5: Commit**

```bash
git add tools/custom_drillreport_docx.py test/test_custom_drillreport_docx_spatialite.py
git commit -m "feat: docx helper module for custom drill report (optional python-docx)"
```

---

### Task 5: `DocxReportWriter`

**Files:**
- Modify: `tools/custom_drillreport_docx.py`
- Test: `test/test_custom_drillreport_docx_spatialite.py` (append a class)

- [ ] **Step 1: Write the failing tests**

Append to `test/test_custom_drillreport_docx_spatialite.py`:

```python
def _make_records():
    return [
        ObsidReportData(
            obsid="OP1",
            general_data=[("type", "borehole"), ("h_gs", "5.12345")],
            general_rounding=[None, "2"],
            geo_data=[("east", "633466"), ("north", "711659")],
            geo_rounding=[None, None],
            strat_data=[("0.0", "1.0", "sand"), ("1.0", "2.5", "gravel")],
            comment_data=["<p>a <b>html</b> comment</p>"],
        ),
        ObsidReportData(
            obsid="OP2",
            general_data=[("type", "well")],
            general_rounding=[None],
            geo_data=[],
            geo_rounding=[],
            strat_data=None,
            comment_data=[],
        ),
    ]


def _make_writer(records, **overrides):
    kwargs = dict(
        records=records,
        strat_columns=["depth;1*", "geology;3*"],
        strat_sql_columns_list=["depthtop", "depthbot", "geology"],
        header_in_table=True,
        skip_empty=False,
        general_metadata_header="General information",
        geo_metadata_header="Geographical information",
        strat_columns_header="Stratigraphy",
        comment_header="Comment",
        empty_row_between_obsids=False,
        topleft_topright_colwidths=["60%", "40%"],
        general_colwidth=["2*", "3*"],
        geo_colwidth=["2*", "3*"],
        decimal_separator=".",
    )
    kwargs.update(overrides)
    return custom_drillreport_docx.DocxReportWriter(**kwargs)


class TestDocxReportWriter:
    def test_save_writes_content(self):
        path = _docx_path()
        _make_writer(_make_records()).save(path)
        document = Document(path)
        text = _all_text(document)
        assert "OP1" in text
        assert "OP2" in text
        assert "sand" in text
        assert "gravel" in text
        assert "General information" in text
        assert "Stratigraphy" in text
        # rounding applied to h_gs
        assert "5.12" in text
        assert "5.12345" not in text
        # comment html converted to plain text
        assert "a html comment" in text
        assert "<b>" not in text
        # depth pseudo column joined
        assert "0.0 - 1.0" in text

    def test_every_row_has_cant_split(self):
        path = _docx_path()
        _make_writer(_make_records()).save(path)
        document = Document(path)
        xml = document.element.xml
        n_rows = len(list(document.element.iter(qn("w:tr"))))
        assert xml.count("cantSplit") == n_rows

    def test_block_paragraphs_keep_with_next(self):
        path = _docx_path()
        _make_writer(_make_records()).save(path)
        document = Document(path)
        assert "keepNext" in document.element.xml

    def test_compact_font_size(self):
        path = _docx_path()
        _make_writer(_make_records()).save(path)
        document = Document(path)
        # 8 pt body == 16 half-points in OOXML
        assert 'w:val="16"' in document.element.xml

    def test_header_outside_table(self):
        path = _docx_path()
        _make_writer(_make_records(), header_in_table=False).save(path)
        document = Document(path)
        first_block_texts = [p.text for p in document.paragraphs]
        assert "OP1" in first_block_texts

    def test_decimal_separator(self):
        path = _docx_path()
        _make_writer(_make_records(), decimal_separator=",").save(path)
        document = Document(path)
        text = _all_text(document)
        assert "5,12" in text
        assert "0,0 - 1,0" in text

    def test_skip_empty(self):
        records = [
            ObsidReportData(
                obsid="OP3",
                general_data=[("type", "NULL"), ("h_gs", "5")],
                general_rounding=[None, None],
                geo_data=[],
                geo_rounding=[],
                strat_data=None,
                comment_data=[],
            )
        ]
        path = _docx_path()
        _make_writer(records, skip_empty=True).save(path)
        document = Document(path)
        text = _all_text(document)
        assert "type" not in text
        assert "h_gs" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest test/test_custom_drillreport_docx_spatialite.py -q -k "DocxReportWriter"`
Expected: FAIL with `AttributeError: module ... has no attribute 'DocxReportWriter'`

- [ ] **Step 3: Implement `DocxReportWriter`**

Append to `tools/custom_drillreport_docx.py`:

```python
def _iter_cell_paragraphs(cell):
    """All paragraphs in a cell, including those inside nested tables."""
    for paragraph in cell.paragraphs:
        yield paragraph
    for table in cell.tables:
        for row in table.rows:
            for inner_cell in row.cells:
                yield from _iter_cell_paragraphs(inner_cell)


class DocxReportWriter:
    """Renders collected report data to a .docx file.

    The layout mirrors the html report: one outer 2-column table per obsid
    with the general and geographical key/value tables side by side, then
    stratigraphy and comments in a merged row. Every table row gets
    w:cantSplit and every paragraph of an obsid block gets keep-with-next,
    so Word keeps each block on one page unless it is taller than a page.
    """

    def __init__(
        self,
        records,
        strat_columns,
        strat_sql_columns_list,
        header_in_table: bool,
        skip_empty: bool,
        general_metadata_header: str,
        geo_metadata_header: str,
        strat_columns_header: str,
        comment_header: str,
        empty_row_between_obsids: bool,
        topleft_topright_colwidths,
        general_colwidth,
        geo_colwidth,
        decimal_separator: str,
    ):
        self.records = records
        self.strat_columns = [x.split(";")[0] for x in strat_columns]
        self.strat_colwidths = [
            x.split(";")[1] if len(x.split(";")) == 2 else "1*" for x in strat_columns
        ]
        self.strat_sql_columns_list = strat_sql_columns_list
        self.header_in_table = header_in_table
        self.skip_empty = skip_empty
        self.general_metadata_header = general_metadata_header
        self.geo_metadata_header = geo_metadata_header
        self.strat_columns_header = strat_columns_header
        self.comment_header = comment_header
        self.empty_row_between_obsids = empty_row_between_obsids
        self.topleft_topright_colwidths = topleft_topright_colwidths
        self.general_colwidth = general_colwidth
        self.geo_colwidth = geo_colwidth
        self.decimal_separator = decimal_separator

    def save(self, path: str) -> None:
        document = Document()
        section = document.sections[0]
        section.page_width = Mm(210)
        section.page_height = Mm(297)
        section.top_margin = Mm(PAGE_MARGIN_MM)
        section.bottom_margin = Mm(PAGE_MARGIN_MM)
        section.left_margin = Mm(PAGE_MARGIN_MM)
        section.right_margin = Mm(PAGE_MARGIN_MM)
        normal = document.styles["Normal"]
        normal.font.size = Pt(BODY_FONT_PT)
        normal.paragraph_format.space_before = Pt(0)
        normal.paragraph_format.space_after = Pt(0)

        for record in self.records:
            heading_paragraphs, outer_table = self._write_obsid(document, record)
            self._keep_block_together(heading_paragraphs, outer_table)
            document.add_paragraph("")
            if self.empty_row_between_obsids:
                document.add_paragraph("")

        document.save(path)

    def _write_obsid(self, document, record):
        heading_paragraphs = []
        if not self.header_in_table:
            paragraph = document.add_paragraph()
            self._add_text(
                paragraph, ru(record.obsid), size=OBSID_FONT_PT, bold=True
            )
            heading_paragraphs.append(paragraph)

        outer = document.add_table(rows=0, cols=2)
        outer.style = "Table Grid"
        _set_fixed_layout(outer)
        _set_cell_margins(outer)
        left_mm, right_mm = self._relative_widths(
            self.topleft_topright_colwidths, 2, CONTENT_WIDTH_MM, [60.0, 40.0]
        )

        if self.header_in_table:
            row = outer.add_row()
            _set_cant_split(row)
            cell = row.cells[0].merge(row.cells[1])
            self._add_text(
                cell.paragraphs[0], ru(record.obsid), size=OBSID_FONT_PT, bold=True
            )

        row = outer.add_row()
        _set_cant_split(row)
        if record.geo_data:
            left_cell, right_cell = row.cells
            left_cell.width = Mm(left_mm)
            right_cell.width = Mm(right_mm)
            self._write_two_col(
                left_cell,
                record.general_data,
                record.general_rounding,
                self.general_metadata_header,
                self.general_colwidth,
                left_mm,
            )
            self._write_two_col(
                right_cell,
                record.geo_data,
                record.geo_rounding,
                self.geo_metadata_header,
                self.geo_colwidth,
                right_mm,
            )
        else:
            cell = row.cells[0].merge(row.cells[1])
            self._write_two_col(
                cell,
                record.general_data,
                record.general_rounding,
                self.general_metadata_header,
                self.general_colwidth,
                CONTENT_WIDTH_MM,
            )

        if record.strat_data or record.comment_data:
            row = outer.add_row()
            _set_cant_split(row)
            cell = row.cells[0].merge(row.cells[1])
            if record.strat_data:
                self._write_strat(cell, record.strat_data)
            if record.comment_data:
                self._write_comment(cell, record.comment_data)

        return heading_paragraphs, outer

    def _write_two_col(
        self, cell, data, rounding_list, table_header, col_widths, total_mm
    ):
        if table_header:
            self._add_text(
                self._cell_paragraph(cell),
                table_header,
                size=SECTION_HEADER_FONT_PT,
                bold=True,
                underline=True,
            )
        rows = build_two_col_rows(
            data, rounding_list, self.skip_empty, self.decimal_separator
        )
        if not rows:
            return
        widths = self._relative_widths(col_widths, 2, total_mm, [2.0, 3.0])
        table = cell.add_table(rows=len(rows), cols=2)
        _set_fixed_layout(table)
        _set_cell_margins(table)
        for (header, value), table_row in zip(rows, table.rows):
            _set_cant_split(table_row)
            for text, inner_cell, width_mm in zip(
                (header, value), table_row.cells, widths
            ):
                inner_cell.width = Mm(width_mm)
                self._add_text(inner_cell.paragraphs[0], text)

    def _write_strat(self, cell, strat_data):
        if self.strat_columns_header:
            self._add_text(
                self._cell_paragraph(cell),
                self.strat_columns_header,
                size=SECTION_HEADER_FONT_PT,
                bold=True,
                underline=True,
            )
        rows = build_strat_rows(
            strat_data,
            self.strat_columns,
            self.strat_sql_columns_list,
            self.decimal_separator,
        )
        if not rows:
            return
        headers_txt = get_strat_header_translations()
        n_cols = len(self.strat_columns)
        widths = self._relative_widths(
            self.strat_colwidths, n_cols, CONTENT_WIDTH_MM, [1.0] * n_cols
        )
        table = cell.add_table(rows=len(rows) + 1, cols=n_cols)
        _set_fixed_layout(table)
        _set_cell_margins(table)
        header_row = table.rows[0]
        _set_cant_split(header_row)
        for col, inner_cell, width_mm in zip(
            self.strat_columns, header_row.cells, widths
        ):
            inner_cell.width = Mm(width_mm)
            self._add_text(inner_cell.paragraphs[0], headers_txt[col], underline=True)
        for values, table_row in zip(rows, table.rows[1:]):
            _set_cant_split(table_row)
            for value, inner_cell, width_mm in zip(values, table_row.cells, widths):
                inner_cell.width = Mm(width_mm)
                self._add_text(inner_cell.paragraphs[0], value)

    def _write_comment(self, cell, comment_data):
        if self.comment_header:
            self._add_text(
                self._cell_paragraph(cell),
                self.comment_header,
                size=SECTION_HEADER_FONT_PT,
                bold=True,
                underline=True,
            )
        text = ". ".join(
            [
                html_to_plain_text(ru(x))
                for x in comment_data
                if ru(x) not in _EMPTY_VALS
            ]
        )
        self._add_text(self._cell_paragraph(cell), text)

    @staticmethod
    def _keep_block_together(heading_paragraphs, outer_table):
        """keep-with-next on every paragraph of the block; the unmarked
        spacer paragraph after the block ends the keep chain, so Word moves
        a block that does not fit to the next page but still breaks blocks
        taller than one page between (cantSplit-protected) rows."""
        for paragraph in heading_paragraphs:
            paragraph.paragraph_format.keep_with_next = True
        for row in outer_table.rows:
            for cell in row.cells:
                for paragraph in _iter_cell_paragraphs(cell):
                    paragraph.paragraph_format.keep_with_next = True

    @staticmethod
    def _cell_paragraph(cell):
        """First unused paragraph of the cell, or a fresh one."""
        paragraph = cell.paragraphs[-1]
        if paragraph.runs or paragraph.text:
            paragraph = cell.add_paragraph()
        return paragraph

    @staticmethod
    def _add_text(paragraph, text, size=BODY_FONT_PT, bold=False, underline=False):
        run = paragraph.add_run(text)
        run.font.size = Pt(size)
        run.bold = bold
        run.underline = underline
        paragraph.paragraph_format.space_before = Pt(0)
        paragraph.paragraph_format.space_after = Pt(0)
        return run

    @staticmethod
    def _relative_widths(width_strings, n_cols, total_mm, fallback_numbers):
        """Parse width strings like '60%', '2*' or '120' into mm widths
        summing to total_mm. Falls back silently on malformed input (the
        html renderer already warns the user about malformed widths)."""
        try:
            numbers = [
                float(str(w).strip().rstrip("%*").strip()) for w in width_strings
            ]
        except (ValueError, TypeError):
            numbers = list(fallback_numbers)
        if len(numbers) != n_cols or any(x <= 0 for x in numbers):
            numbers = list(fallback_numbers)
        total = float(sum(numbers))
        return [x / total * total_mm for x in numbers]
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python3 -m pytest test/test_custom_drillreport_docx_spatialite.py -q`
Expected: PASS (helpers + writer classes).
If `test_every_row_has_cant_split` fails on count: remember merged cells make `row.cells` return the same cell object multiple times — `_set_cant_split` is idempotent, so the count must still equal the number of `w:tr` elements. Debug by printing `document.element.xml`.

- [ ] **Step 5: Commit**

```bash
git add tools/custom_drillreport_docx.py test/test_custom_drillreport_docx_spatialite.py
git commit -m "feat: DocxReportWriter renders compact keep-together drill report tables"
```

---

### Task 6: Dialog — output-format radio group and stored settings

**Files:**
- Modify: `ui/custom_drillreport.ui`
- Modify: `tools/custom_drillreport.py` (`DrillreportUi.__init__`, `update_from_stored_settings`, `save_stored_settings`)
- Test: `test/test_custom_drillreport_docx_spatialite.py` (append a class)

- [ ] **Step 1: Write the failing tests**

Append to `test/test_custom_drillreport_docx_spatialite.py`:

```python
@pytest.mark.spatialite
class TestOutputFormatRadios(utils_for_tests.MidvattenTestSpatialiteDbSv):
    @mock.patch(
        "midvatten.tools.custom_drillreport.common_utils.get_stored_settings",
        return_value={},
    )
    def test_html_is_default(self, mock_get_stored):
        ui = DrillreportUi(self.iface, self.midvatten.ms)
        assert ui.radio_format_html.isChecked()
        assert not ui.radio_format_word.isChecked()
        assert ui.radio_format_word.isEnabled()

    @mock.patch(
        "midvatten.tools.custom_drillreport.common_utils.get_stored_settings",
        return_value={},
    )
    def test_format_choice_round_trips_through_stored_settings(
        self, mock_get_stored
    ):
        ui1 = DrillreportUi(self.iface, self.midvatten.ms)
        ui1.radio_format_word.setChecked(True)
        ui1.save_stored_settings()
        stored = dict(ui1.stored_settings)
        assert stored["radio_format_word"] is True
        ui2 = DrillreportUi(self.iface, self.midvatten.ms)
        ui2.update_from_stored_settings(stored)
        assert ui2.radio_format_word.isChecked()

    @mock.patch("midvatten.tools.custom_drillreport_docx.DOCX_AVAILABLE", False)
    @mock.patch(
        "midvatten.tools.custom_drillreport.common_utils.get_stored_settings",
        return_value={},
    )
    def test_word_radio_disabled_without_docx(self, mock_get_stored):
        ui = DrillreportUi(self.iface, self.midvatten.ms)
        assert not ui.radio_format_word.isEnabled()
        assert "python-docx" in ui.radio_format_word.toolTip()
        assert ui.radio_format_html.isChecked()

    @mock.patch("midvatten.tools.custom_drillreport_docx.DOCX_AVAILABLE", False)
    @mock.patch(
        "midvatten.tools.custom_drillreport.common_utils.get_stored_settings",
        return_value={},
    )
    def test_stored_word_choice_ignored_without_docx(self, mock_get_stored):
        ui = DrillreportUi(self.iface, self.midvatten.ms)
        ui.update_from_stored_settings({"radio_format_word": True})
        assert ui.radio_format_html.isChecked()
        assert not ui.radio_format_word.isChecked()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest test/test_custom_drillreport_docx_spatialite.py -q -k "OutputFormatRadios"`
Expected: FAIL with `AttributeError: ... no attribute 'radio_format_html'`

- [ ] **Step 3: Add the radio group to `ui/custom_drillreport.ui`**

In `ui/custom_drillreport.ui`, directly before the `<item>` containing `horizontal_layout` (the Cancel/Ok row, currently starting at the line `<layout class="QHBoxLayout" name="horizontal_layout">`), insert a new item:

```xml
    <item>
     <layout class="QHBoxLayout" name="horizontal_layout_format">
      <item>
       <widget class="QLabel" name="label_format">
        <property name="text">
         <string>Output format</string>
        </property>
       </widget>
      </item>
      <item>
       <widget class="QRadioButton" name="radio_format_html">
        <property name="text">
         <string>HTML</string>
        </property>
        <property name="checked">
         <bool>true</bool>
        </property>
       </widget>
      </item>
      <item>
       <widget class="QRadioButton" name="radio_format_word">
        <property name="text">
         <string>Word (.docx)</string>
        </property>
       </widget>
      </item>
     </layout>
    </item>
```

(The `.ui` file is loaded at runtime with `uic.loadUiType`; no compile step. Both radios share the central widget as parent, so Qt makes them mutually exclusive automatically.)

- [ ] **Step 4: Wire the radios in `DrillreportUi`**

In `tools/custom_drillreport.py`:

a) Add the docx module import below the core import:

```python
from midvatten.tools import custom_drillreport_docx
```

b) In `DrillreportUi.__init__`, after the `self.update_from_stored_settings(self.stored_settings)` line, add:

```python
        if not custom_drillreport_docx.DOCX_AVAILABLE:
            self.radio_format_word.setEnabled(False)
            self.radio_format_word.setToolTip(
                QCoreApplication.translate(
                    "DrillreportUi",
                    "Requires the python-docx package. Install it with "
                    "'pip install python-docx' (in the OSGeo4W shell on Windows).",
                )
            )
```

c) In `update_from_stored_settings`, extend the widget-type dispatch — change

```python
                    elif isinstance(selfattr, qgis.PyQt.QtWidgets.QCheckBox):
                        selfattr.setChecked(val)
```

to

```python
                    elif isinstance(
                        selfattr,
                        (
                            qgis.PyQt.QtWidgets.QCheckBox,
                            qgis.PyQt.QtWidgets.QRadioButton,
                        ),
                    ):
                        selfattr.setChecked(val)
```

and at the very end of the method (outside the if/else, so it runs for both stored and default settings), add:

```python
        if (
            not custom_drillreport_docx.DOCX_AVAILABLE
            and self.radio_format_word.isChecked()
        ):
            self.radio_format_html.setChecked(True)
```

d) In `save_stored_settings`, add `"radio_format_word",` to the `for attrname in [...]` list (after `"decimal_separator",`), and widen the same isinstance check — change

```python
                elif isinstance(attr, qgis.PyQt.QtWidgets.QCheckBox):
                    val = attr.isChecked()
```

to

```python
                elif isinstance(
                    attr,
                    (
                        qgis.PyQt.QtWidgets.QCheckBox,
                        qgis.PyQt.QtWidgets.QRadioButton,
                    ),
                ):
                    val = attr.isChecked()
```

(Only `radio_format_word` is stored; `radio_format_html` is its complement via Qt's exclusivity. Order matters: the QCheckBox/QRadioButton branch must come before the generic error branch, exactly where the QCheckBox branch is today.)

- [ ] **Step 5: Run tests, verify pass**

Run: `python3 -m pytest test/test_custom_drillreport_docx_spatialite.py test/test_custom_drillreport_ui_spatialite.py -q`
Expected: PASS — including the pre-existing `test_save_and_restore_stored_settings` (the new key must not break it).

- [ ] **Step 6: Commit**

```bash
git add ui/custom_drillreport.ui tools/custom_drillreport.py test/test_custom_drillreport_docx_spatialite.py
git commit -m "feat: output format radio (HTML/Word) in custom drill report dialog"
```

---

### Task 7: Word export flow (OK button branch, save dialog, messages)

**Files:**
- Modify: `tools/custom_drillreport.py` (`DrillreportUi.drillreport`, new `DrillreportUi.export_word`)
- Test: `test/test_custom_drillreport_docx_spatialite.py` (append a class)

- [ ] **Step 1: Write the failing tests**

Append to `test/test_custom_drillreport_docx_spatialite.py`:

```python
@pytest.mark.spatialite
class TestWordExportFlow(utils_for_tests.MidvattenTestSpatialiteDbSv):
    def _make_ui(self, selected):
        patcher = mock.patch(
            "midvatten.tools.custom_drillreport.common_utils.get_stored_settings",
            return_value={},
        )
        patcher.start()
        try:
            ui = DrillreportUi(self.iface, self.midvatten.ms)
        finally:
            patcher.stop()
        ui.radio_format_word.setChecked(True)
        return ui

    @mock.patch(
        "midvatten.tools.custom_drillreport.qgis.PyQt.QtWidgets.QFileDialog.getSaveFileName"
    )
    @mock.patch(
        "midvatten.tools.custom_drillreport.common_utils.get_selected_object_names"
    )
    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    @mock.patch("qgis.utils.iface", autospec=True)
    def test_ok_with_word_selected_writes_docx(
        self, mock_iface, mock_messagebar, mock_getselected, mock_savefilename
    ):
        _insert_drillreport_test_data(["OP1"])
        mock_getselected.return_value = ["OP1"]
        path = _docx_path()
        mock_savefilename.return_value = (path, "Word documents (*.docx)")
        ui = self._make_ui(["OP1"])
        ui.drillreport()
        print(f"{mock_messagebar.mock_calls=}")
        assert os.path.isfile(path)
        document = Document(path)
        text = _all_text(document)
        assert "OP1" in text
        assert "sand" in text
        mock_messagebar.info.assert_called()
        mock_messagebar.critical.assert_not_called()

    @mock.patch(
        "midvatten.tools.custom_drillreport.qgis.PyQt.QtWidgets.QFileDialog.getSaveFileName"
    )
    @mock.patch(
        "midvatten.tools.custom_drillreport.common_utils.get_selected_object_names"
    )
    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    @mock.patch("qgis.utils.iface", autospec=True)
    def test_docx_suffix_appended(
        self, mock_iface, mock_messagebar, mock_getselected, mock_savefilename
    ):
        _insert_drillreport_test_data(["OP1"])
        mock_getselected.return_value = ["OP1"]
        path = _docx_path()[: -len(".docx")]
        mock_savefilename.return_value = (path, "Word documents (*.docx)")
        ui = self._make_ui(["OP1"])
        ui.drillreport()
        print(f"{mock_messagebar.mock_calls=}")
        assert os.path.isfile(path + ".docx")

    @mock.patch(
        "midvatten.tools.custom_drillreport.qgis.PyQt.QtWidgets.QFileDialog.getSaveFileName"
    )
    @mock.patch(
        "midvatten.tools.custom_drillreport.common_utils.get_selected_object_names"
    )
    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    @mock.patch("qgis.utils.iface", autospec=True)
    def test_save_dialog_cancel_is_silent(
        self, mock_iface, mock_messagebar, mock_getselected, mock_savefilename
    ):
        _insert_drillreport_test_data(["OP1"])
        mock_getselected.return_value = ["OP1"]
        mock_savefilename.return_value = ("", "")
        path = _docx_path()  # resolves AND removes any leftover file up front
        ui = self._make_ui(["OP1"])
        ui.drillreport()
        print(f"{mock_messagebar.mock_calls=}")
        mock_messagebar.critical.assert_not_called()
        assert not os.path.exists(path)

    @mock.patch(
        "midvatten.tools.custom_drillreport.qgis.PyQt.QtWidgets.QFileDialog.getSaveFileName"
    )
    @mock.patch(
        "midvatten.tools.custom_drillreport.common_utils.get_selected_object_names"
    )
    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    @mock.patch("qgis.utils.iface", autospec=True)
    def test_unwritable_path_shows_critical(
        self, mock_iface, mock_messagebar, mock_getselected, mock_savefilename
    ):
        _insert_drillreport_test_data(["OP1"])
        mock_getselected.return_value = ["OP1"]
        mock_savefilename.return_value = (
            "/nonexistent_dir_zzz/report.docx",
            "Word documents (*.docx)",
        )
        ui = self._make_ui(["OP1"])
        ui.drillreport()
        print(f"{mock_messagebar.mock_calls=}")
        mock_messagebar.critical.assert_called()

    @mock.patch("midvatten.tools.custom_drillreport.QDesktopServices.openUrl")
    @mock.patch(
        "midvatten.tools.custom_drillreport.common_utils.get_selected_object_names"
    )
    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    @mock.patch("qgis.utils.iface", autospec=True)
    def test_html_radio_still_generates_html(
        self, mock_iface, mock_messagebar, mock_getselected, mock_openurl
    ):
        _insert_drillreport_test_data(["OP1"])
        mock_getselected.return_value = ["OP1"]
        ui = self._make_ui(["OP1"])
        ui.radio_format_html.setChecked(True)
        ui.drillreport()
        print(f"{mock_messagebar.mock_calls=}")
        assert mock_openurl.called
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest test/test_custom_drillreport_docx_spatialite.py -q -k "WordExportFlow"`
Expected: FAIL — `test_ok_with_word_selected_writes_docx` produces no docx (OK still runs the HTML path).

- [ ] **Step 3: Branch `drillreport()` and add `export_word()`**

In `tools/custom_drillreport.py`, inside `DrillreportUi.drillreport`, replace the final `drillrep = Drillreport(...)` statement with:

```python
        if self.radio_format_word.isChecked():
            self.export_word(
                obsids,
                general_metadata,
                geo_metadata,
                strat_columns,
                header_in_table,
                skip_empty,
                include_comments,
                general_metadata_header,
                geo_metadata_header,
                strat_columns_header,
                comment_header,
                empty_row_between_obsids,
                topleft_topright_colwidths,
                general_colwidth,
                geo_colwidth,
                decimal_separator,
            )
            return
        Drillreport(
            obsids,
            self.ms,
            general_metadata,
            geo_metadata,
            strat_columns,
            header_in_table,
            skip_empty,
            include_comments,
            general_metadata_header,
            geo_metadata_header,
            strat_columns_header,
            comment_header,
            empty_row_between_obsids,
            topleft_topright_colwidths,
            general_colwidth,
            geo_colwidth,
            decimal_separator,
        )
```

(The old `drillrep =` assignment was never used — drop it.)

Add the new method to `DrillreportUi` (after `drillreport`):

```python
    def export_word(
        self,
        obsids,
        general_metadata,
        geo_metadata,
        strat_columns,
        header_in_table: bool,
        skip_empty: bool,
        include_comments: bool,
        general_metadata_header: str,
        geo_metadata_header: str,
        strat_columns_header: str,
        comment_header: str,
        empty_row_between_obsids: bool,
        topleft_topright_colwidths,
        general_colwidth,
        geo_colwidth,
        decimal_separator: str,
    ) -> None:
        filename, _selected_filter = qgis.PyQt.QtWidgets.QFileDialog.getSaveFileName(
            self,
            QCoreApplication.translate("DrillreportUi", "Save Word report"),
            "",
            QCoreApplication.translate("DrillreportUi", "Word documents (*.docx)"),
        )
        if not filename:
            return
        if not filename.lower().endswith(".docx"):
            filename += ".docx"

        records, strat_sql_columns_list = collect_report_data(
            obsids, general_metadata, geo_metadata, strat_columns, include_comments
        )
        writer = custom_drillreport_docx.DocxReportWriter(
            records,
            strat_columns,
            strat_sql_columns_list,
            header_in_table,
            skip_empty,
            general_metadata_header,
            geo_metadata_header,
            strat_columns_header,
            comment_header,
            empty_row_between_obsids,
            topleft_topright_colwidths,
            general_colwidth,
            geo_colwidth,
            decimal_separator,
        )
        try:
            writer.save(filename)
        except OSError as e:
            common_utils.MessagebarAndLog.critical(
                bar_msg=QCoreApplication.translate(
                    "DrillreportUi",
                    "Writing the Word report failed, see log message panel",
                ),
                log_msg=str(e),
            )
            return
        common_utils.MessagebarAndLog.info(
            bar_msg=QCoreApplication.translate(
                "DrillreportUi", "Word report saved to %s"
            )
            % filename
        )
```

- [ ] **Step 4: Run the full new test file + HTML guard**

Run: `python3 -m pytest test/test_custom_drillreport_docx_spatialite.py test/test_custom_drillreport_ui_spatialite.py test/test_custom_drillreport_core.py -q`
Expected: PASS, everything.

- [ ] **Step 5: Commit**

```bash
git add tools/custom_drillreport.py test/test_custom_drillreport_docx_spatialite.py
git commit -m "feat: Word export flow for custom drill report (save dialog, messages)"
```

---

### Task 8: Lint, format, verification

- [ ] **Step 1: Ruff**

Run:
```bash
ruff check --fix .
ruff format .
```
Review any changes (`git diff`), make sure nothing functional changed, re-run the three report test files if ruff touched the tools/test files:

Run: `python3 -m pytest test/test_custom_drillreport_docx_spatialite.py test/test_custom_drillreport_ui_spatialite.py test/test_custom_drillreport_core.py test/test_drillreport.py -q`
Expected: PASS

- [ ] **Step 2: Commit any lint fixes**

```bash
git add -A
git commit -m "style: ruff fixes for drill report docx export" || echo "nothing to commit"
```

- [ ] **Step 3: Per CLAUDE.md, invoke the `simplify` skill** on the changed code (executor: this is a required workflow step, not optional). Apply its findings, re-run the four test files above, commit.

- [ ] **Step 4: Final verification (superpowers:verification-before-completion)**

Run the related suites:
```bash
python3 -m pytest test/test_custom_drillreport_core.py test/test_custom_drillreport_docx_spatialite.py test/test_custom_drillreport_ui_spatialite.py test/test_drillreport.py -q
```
Expected: PASS. (Full suite takes ~33–43 min — run it only at the sprint boundary per project memory, before merging back to `ai_test`.)

---

## Notes for the executor

- **Never** change assertions or reference data in `test/test_custom_drillreport_ui_spatialite.py`. If an HTML test fails, the refactor broke byte-identity — fix the implementation.
- **Never** repoint `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/midvatten`; the worktree's `_pkgroot/` + root `conftest.py` handle imports.
- All imports module-level (project rule) — the docx `try/except ImportError` is the single sanctioned guard.
- User-facing strings: `QCoreApplication.translate("DrillreportUi", ...)` (or the existing `Drillreport2*` contexts for moved code — keep those contexts unchanged so existing translations keep working).
- When done: use superpowers:finishing-a-development-branch. The integration target is `ai_test` (project rule: ai_test is the living branch; never propose merging to master).
