# Plugin Structure Homogenisation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace ~40 scattered handler methods in `midvatten_plugin.py` with a declarative `_ACTIONS` manifest and a single dispatcher, while giving every tool class a uniform `__init__(iface, ms)` / `show()` interface.

**Architecture:** All tool classes adopt `(iface, ms)` constructors and expose `show()`. The plugin declares every action as an `ActionSpec` dataclass entry. A `_dispatch(spec)` method handles precondition checking, persistent-window reuse, and tool invocation for all actions.

**Tech Stack:** Python 3, PyQt5 (QGIS), SQLite/PostGIS via existing `db_utils`, `pytest` for tests.

**Prerequisite:** `rosy-seeking-bunny.md` plan fully merged to `ai_test`. By then `tools/sectionplot.py` is a package at `tools/sectionplot/` and `tools/customplot.py` is a package at `tools/customplot/`. All imports go through `tools/sectionplot/__init__.py` and `tools/customplot/__init__.py`.

**Build in a git worktree.** Use subagents (one per task) to conserve context.

**Code style rules (enforced by ruff):**
- All imports must be at **module level** — never inside functions or methods (PEP 8)
- Run `ruff check --fix . && ruff format .` after every task

**Spec:** `docs/superpowers/specs/2026-04-16-plugin-structure-homogenisation-design.md`

---

## Phase 1 — Tool Interface Standardisation

The goal of Phase 1 is to give every tool class a consistent interface **before** touching `midvatten_plugin.py`. Run `python3 -m pytest test/ -x -m spatialite` after each task. No changes to `midvatten_plugin.py` in this phase.

**Transformation rule (applies to all tools):**
- `__init__(self, iface, ms)` — `iface` is the QGIS interface object, `ms` is the `MidvSettings` instance
- Constructor is **cheap**: no DB queries, no dialogs, no Matplotlib figures
- `show(self) -> None` — all deferred work happens here; modal dialogs call `self.exec()` inside `show()`

---

### Task 1: Write precondition behaviour test

Before changing anything, pin the current precondition logic so we can verify the dispatcher preserves it.

**Files:**
- Create: `test/test_plugin_dispatcher.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for plugin dispatcher precondition behaviour.

These tests verify that verify_msettings_loaded_and_layer_edit_mode
behaves as expected — called by the dispatcher for every action that
needs_db=True.
"""
import pytest
from unittest import mock

from midvatten.tools.utils.midvatten_utils import (
    verify_msettings_loaded_and_layer_edit_mode,
)


@pytest.mark.spatialite
class TestVerifyMsettings:
    def test_returns_zero_when_settings_loaded_and_no_layers(
        self, mock_midv_settings
    ):
        """No layer tuple: only checks that settings are loaded."""
        with mock.patch(
            "midvatten.tools.utils.common_utils.MessagebarAndLog"
        ) as mock_messagebar:
            err_flag = verify_msettings_loaded_and_layer_edit_mode(
                mock.MagicMock(), mock_midv_settings, ()
            )
            print(mock_messagebar.mock_calls)
        assert err_flag == 0

    def test_returns_nonzero_when_settings_not_loaded(self):
        """Missing database path means err_flag != 0."""
        with mock.patch(
            "midvatten.tools.utils.common_utils.MessagebarAndLog"
        ) as mock_messagebar:
            ms = mock.MagicMock()
            ms.settingsdict = {"database": ""}
            err_flag = verify_msettings_loaded_and_layer_edit_mode(
                mock.MagicMock(), ms, ()
            )
            print(mock_messagebar.mock_calls)
        assert err_flag != 0
```

- [ ] **Step 2: Run the test (expect it to need a fixture — add `mock_midv_settings` fixture if missing)**

```bash
python3 -m pytest test/test_plugin_dispatcher.py -x -v
```

Inspect the error. If `mock_midv_settings` fixture is missing, look in `test/utils_for_tests.py` for the equivalent fixture and use it.

- [ ] **Step 3: Fix imports / fixtures until tests pass**

```bash
python3 -m pytest test/test_plugin_dispatcher.py -x -v
```
Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
git add test/test_plugin_dispatcher.py
git commit -m "test: pin precondition behaviour before dispatcher refactor"
```

---

### Task 2A: Standardise — parent-only simple tools

These tools take `parent` (a `QWidget`) as their only constructor argument from the plugin. Change to `(iface, ms)` and derive `parent` from `iface.mainWindow()` internally.

**Files to modify:**
- `tools/w_flow_calc_aveflow.py` — `CalculateAveflow`
- `tools/strat_symbology.py` — `StratSymbology`
- `tools/column_values_from_selected_features.py` — `ValuesFromSelectedFeaturesGui`

**Transformation example (`CalculateAveflow`):**

```python
# BEFORE
class CalculateAveflow(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        setupUi(self)
        # ... signal connections ...

# AFTER
class CalculateAveflow(QDialog):
    def __init__(self, iface, ms):
        super().__init__(iface.mainWindow())
        self._iface = iface
        self._ms = ms
        setupUi(self)
        # ... signal connections unchanged ...

    def show(self) -> None:
        self.exec()
```

**For `StratSymbology`** — already calls `self.show()` at end of `__init__`. Move that call out; add `show()` method:

```python
# BEFORE
class StratSymbology(QDialog):
    def __init__(self, iface, parent):
        super().__init__(parent)
        self.iface = iface
        setupUi(self)
        self.show()   # ← remove this line

# AFTER
class StratSymbology(QDialog):
    def __init__(self, iface, ms):
        super().__init__(iface.mainWindow())
        self.iface = iface
        self._ms = ms
        setupUi(self)
        # no self.show() here

    def show(self) -> None:
        super().show()
```

**For `ValuesFromSelectedFeaturesGui`** — same pattern; `parent` stored as `self.iface`.

- [ ] **Step 1: Apply changes to `CalculateAveflow`** (see above)
- [ ] **Step 2: Apply changes to `StratSymbology`** (see above)
- [ ] **Step 3: Apply changes to `ValuesFromSelectedFeaturesGui`**

```python
class ValuesFromSelectedFeaturesGui(QDialog):
    def __init__(self, iface, ms):
        super().__init__(iface.mainWindow())
        self.iface = iface
        self._ms = ms
        setupUi(self)
        self.reload_combobox()
        # ... signal connections unchanged ...

    def show(self) -> None:
        super().show()
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest test/ -x -m spatialite
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tools/w_flow_calc_aveflow.py tools/strat_symbology.py tools/column_values_from_selected_features.py
git commit -m "refactor: standardise (iface, ms) interface for simple parent-only tools"
```

---

### Task 2B: Standardise — dialog tools with ms already

These tools already take `ms` or `midv_settings`; just rename args and ensure `show()` is the entry point.

**Files to modify:**
- `tools/custom_drillreport.py` — `DrillreportUi`
- `tools/wqualreport_compact.py` — `CompactWqualReportUi`
- `tools/export_fieldlogger.py` — `ExportToFieldLogger` (persistent window)

**Transformation (`DrillreportUi`):**

```python
# BEFORE
class DrillreportUi(QDialog):
    def __init__(self, parent, midv_settings):
        super().__init__(parent)
        self.iface = parent
        self.ms = midv_settings
        ...

# AFTER
class DrillreportUi(QDialog):
    def __init__(self, iface, ms):
        super().__init__(iface.mainWindow())
        self.iface = iface
        self.ms = ms
        ...

    def show(self) -> None:
        self.exec()
```

**`CompactWqualReportUi`** — currently calls `self.show()` at end of `__init__`. Move to `show()` method. The DB queries in `__init__` (`tables_columns()`) stay in `__init__` because this is a persistent window; they run once at creation.

```python
# AFTER
class CompactWqualReportUi(QMainWindow):
    def __init__(self, iface, ms):
        super().__init__(iface.mainWindow())
        self.iface = iface
        self.ms = ms
        setupUi(self)
        self._load_tables()   # was inline in __init__, keep here for persistent window
        # ... signal connections ...
        # REMOVE: self.show()

    def show(self) -> None:
        super().show()
        self.activateWindow()
```

**`ExportToFieldLogger`** — same pattern. This is a persistent window (the dispatcher handles reuse via `persistent=True`).

```python
# AFTER
class ExportToFieldLogger(QMainWindow):
    def __init__(self, iface, ms):
        super().__init__(iface.mainWindow())
        self.iface = iface
        self.ms = ms
        setupUi(self)
        self._init_ui()  # the existing setup that was in __init__
        # REMOVE: self.show()

    def show(self) -> None:
        super().show()
        self.activateWindow()
```

- [ ] **Step 1: Apply changes to `DrillreportUi`**
- [ ] **Step 2: Apply changes to `CompactWqualReportUi`**
- [ ] **Step 3: Apply changes to `ExportToFieldLogger`**
- [ ] **Step 4: Run tests**

```bash
python3 -m pytest test/ -x -m spatialite
```

- [ ] **Step 5: Commit**

```bash
git add tools/custom_drillreport.py tools/wqualreport_compact.py tools/export_fieldlogger.py
git commit -m "refactor: standardise (iface, ms) interface for ms-dialog tools"
```

---

### Task 2C: Standardise — active-layer tools

These tools currently receive `layer` (from `iface.activeLayer()`) and `settingsdict` (from `ms.settingsdict`) as constructor args. Move to `(iface, ms)` and fetch them inside `show()`.

**Files to modify:**
- `tools/piper.py` — `PiperPlot`
- `tools/tsplot.py` — `TimeSeriesPlot`
- `tools/xyplot.py` — `XYPlot`
- `tools/stratigraphy.py` — `Stratigraphy`
- `tools/calculate_level.py` — `CalculateLevel`

**Transformation (`PiperPlot`):**

```python
# BEFORE
class PiperPlot:
    def __init__(self, msettings, activelayer):
        self.ms = msettings
        self.activelayer = activelayer

    def get_data_and_make_plot(self):
        ...  # uses self.activelayer and self.ms

# AFTER
class PiperPlot:
    def __init__(self, iface, ms):
        self._iface = iface
        self.ms = ms

    def show(self) -> None:
        self.activelayer = self._iface.activeLayer()
        self.get_data_and_make_plot()  # existing method, unchanged

    def get_data_and_make_plot(self):
        ...  # unchanged; uses self.activelayer and self.ms
```

**`TimeSeriesPlot`** — currently calls `showtheplot(layer)` inside `__init__`. Move to `show()`:

```python
# BEFORE
class TimeSeriesPlot:
    def __init__(self, layer=None, settingsdict=None):
        self.settingsdict = settingsdict
        self.showtheplot(layer)

# AFTER
class TimeSeriesPlot:
    def __init__(self, iface, ms):
        self._iface = iface
        self.settingsdict = ms.settingsdict

    def show(self) -> None:
        self.showtheplot(self._iface.activeLayer())

    def showtheplot(self, layer):
        ...  # unchanged
```

**`XYPlot`** — identical pattern to `TimeSeriesPlot`. Apply the same transformation.

**`Stratigraphy`** — rename `show_survey()` → add `show()` that calls `show_survey()`:

```python
# BEFORE
class Stratigraphy(QMainWindow):
    def __init__(self, iface, layer=None, settingsdict=None):
        ...
        self.layer = layer

    def show_survey(self):
        ...

# AFTER
class Stratigraphy(QMainWindow):
    def __init__(self, iface, ms):
        super().__init__(iface.mainWindow())
        self.iface = iface
        self._ms = ms
        self.layer = iface.activeLayer()  # moved from plugin handler

    def show(self) -> None:
        self.show_survey()

    def show_survey(self):
        ...  # unchanged
```

**`CalculateLevel`** — currently `__init__(parent, layerin)` where `layerin` is `iface.activeLayer()`:

```python
# BEFORE
class CalculateLevel(QDialog):
    def __init__(self, parent: QWidget, layerin):
        super().__init__(parent)
        self.layer = layerin

# AFTER
class CalculateLevel(QDialog):
    def __init__(self, iface, ms):
        super().__init__(iface.mainWindow())
        self._iface = iface
        self._ms = ms
        self.layer = iface.activeLayer()
        setupUi(self)
        # ... signal connections unchanged ...

    def show(self) -> None:
        self.exec()
```

- [ ] **Step 1: Apply changes to `PiperPlot`**
- [ ] **Step 2: Apply changes to `TimeSeriesPlot`**
- [ ] **Step 3: Apply changes to `XYPlot`**
- [ ] **Step 4: Apply changes to `Stratigraphy`**
- [ ] **Step 5: Apply changes to `CalculateLevel`**
- [ ] **Step 6: Run tests**

```bash
python3 -m pytest test/ -x -m spatialite
```

- [ ] **Step 7: Commit**

```bash
git add tools/piper.py tools/tsplot.py tools/xyplot.py tools/stratigraphy.py tools/calculate_level.py
git commit -m "refactor: standardise (iface, ms) interface for active-layer tools"
```

---

### Task 2D: Standardise — importers

All importers share the same `(parent, msettings)` pattern (inherited from `BaseImporter` or `DiverofficeImport`). Change to `(iface, ms)`. The `parent` arg passed to `super().__init__()` becomes `iface.mainWindow()`.

**Files to modify:**
- `tools/import_fieldlogger.py` — `FieldloggerImport`
- `tools/import_general_csv_gui.py` — `GeneralCsvImportGui`
- `tools/import_interlab4.py` — `Interlab4Import`
- `tools/import_diveroffice.py` — `DiverofficeImport`
- `tools/import_levelogger.py` — `LeveloggerImport`
- `tools/import_hobologger.py` — `HobologgerImport`
- `tools/import_data_to_db.py` — `MidvDataImporter` base class (if it defines `__init__`)

**Check first:** Read `tools/import_data_to_db.py` to find `MidvDataImporter.__init__` and any base class that defines the `(parent, msettings)` signature. Update the base class first; subclasses flow through.

**Transformation (`DiverofficeImport`, the shared base for Levelogger/Hobo):**

```python
# BEFORE
class DiverofficeImport(QMainWindow):
    def __init__(self, parent, msettings=None):
        super().__init__(parent)
        self.ms = msettings
        self.load_gui()   # expensive: DB queries in __init__

# AFTER
class DiverofficeImport(QMainWindow):
    def __init__(self, iface, ms):
        super().__init__(iface.mainWindow())
        self._iface = iface
        self.ms = ms
        # setupUi and signal connections only — NO load_gui() here

    def show(self) -> None:
        self.load_gui()   # DB queries deferred to show()
        super().show()

    def load_gui(self):
        ...  # unchanged
```

**`LeveloggerImport` and `HobologgerImport`** inherit from `DiverofficeImport`. Check if they override `__init__`. If yes, apply the same pattern. If not, they inherit the new `__init__` automatically — verify with a test.

**`FieldloggerImport`:**

```python
# AFTER
class FieldloggerImport(QMainWindow):  # or whatever base it uses
    def __init__(self, iface, ms):
        super().__init__(iface.mainWindow())
        self._iface = iface
        self.ms = ms
        setupUi(self)
        # signal connections only

    def show(self) -> None:
        self.parse_observations_and_populate_gui()
        super().show()
```

**`GeneralCsvImportGui`:**

```python
# AFTER
class GeneralCsvImportGui(QMainWindow):
    def __init__(self, iface, ms):
        super().__init__(iface.mainWindow())
        self.iface = iface
        self.ms = ms
        self.dbconnection = None  # was optional, stays optional
        setupUi(self)
        # signal connections only

    def show(self) -> None:
        self.load_gui()
        super().show()
```

**`Interlab4Import`:**

```python
# AFTER
class Interlab4Import(QMainWindow):
    def __init__(self, iface, ms):
        super().__init__(iface.mainWindow())
        self._iface = iface
        self.ms = ms
        setupUi(self)
        # signal connections only

    def show(self) -> None:
        self.init_gui()   # deferred DB queries
        super().show()
```

- [ ] **Step 1: Read `tools/import_data_to_db.py` base class signature, update it first if needed**
- [ ] **Step 2: Apply changes to `DiverofficeImport`**
- [ ] **Step 3: Apply changes to `LeveloggerImport` (verify inheritance works, check if __init__ is overridden)**
- [ ] **Step 4: Apply changes to `HobologgerImport` (same check)**
- [ ] **Step 5: Apply changes to `FieldloggerImport`**
- [ ] **Step 6: Apply changes to `GeneralCsvImportGui`**
- [ ] **Step 7: Apply changes to `Interlab4Import`**
- [ ] **Step 8: Run tests**

```bash
python3 -m pytest test/ -x -m spatialite
```

- [ ] **Step 9: Commit**

```bash
git add tools/import_data_to_db.py tools/import_fieldlogger.py tools/import_general_csv_gui.py tools/import_interlab4.py tools/import_diveroffice.py tools/import_levelogger.py tools/import_hobologger.py
git commit -m "refactor: standardise (iface, ms) interface for all importers"
```

---

### Task 2E: Standardise — immediately-executing tools

These tools do all their work immediately in `__init__` (no persistent dialog). Move work to `show()`.

**Files to modify:**
- `tools/drillreport.py` — `Drillreport`
- `tools/wqualreport.py` — `Wqualreport`
- `tools/prepareforqgis2threejs.py` — `PrepareForQgis2Threejs`

**`Drillreport`** — currently `__init__(obsids, settingsdict)` runs the whole report. Move to `show()`, fetch obsids from `iface.activeLayer()`:

```python
# BEFORE
class Drillreport:
    def __init__(self, obsids=None, settingsdict=None):
        # ... creates full HTML report ...

# AFTER
class Drillreport:
    def __init__(self, iface, ms):
        self._iface = iface
        self._ms = ms

    def show(self) -> None:
        layer = self._iface.activeLayer()
        obsids = tuple(
            str(f["obsid"])
            for f in layer.selectedFeatures()
        )
        settingsdict = self._ms.settingsdict
        self._run_report(obsids, settingsdict)

    def _run_report(self, obsids, settingsdict):
        # move the existing __init__ body here, unchanged
        ...
```

**`Wqualreport`** — same pattern. Currently `__init__(layer, settingsdict)` does everything:

```python
# AFTER
class Wqualreport:
    def __init__(self, iface, ms):
        self._iface = iface
        self._ms = ms

    def show(self) -> None:
        layer = self._iface.activeLayer()
        settingsdict = self._ms.settingsdict
        self._run_report(layer, settingsdict)

    def _run_report(self, layer, settingsdict):
        # existing __init__ body moved here, unchanged
        ...
```

**`PrepareForQgis2Threejs`** — currently `__init__(iface, settingsdict)` does heavy work immediately. Move to `show()`:

```python
# BEFORE
class PrepareForQgis2Threejs:
    def __init__(self, iface, settingsdict=None):
        self.iface = iface
        self.settingsdict = settingsdict
        self.add_layers()  # heavy, immediate

# AFTER
class PrepareForQgis2Threejs:
    def __init__(self, iface, ms):
        self.iface = iface
        self._ms = ms

    def show(self) -> None:
        self.settingsdict = self._ms.settingsdict
        self.add_layers()  # deferred to show()

    def add_layers(self):
        ...  # unchanged
```

- [ ] **Step 1: Apply changes to `Drillreport`**
- [ ] **Step 2: Apply changes to `Wqualreport`**
- [ ] **Step 3: Apply changes to `PrepareForQgis2Threejs`**
- [ ] **Step 4: Run tests**

```bash
python3 -m pytest test/ -x -m spatialite
```

- [ ] **Step 5: Commit**

```bash
git add tools/drillreport.py tools/wqualreport.py tools/prepareforqgis2threejs.py
git commit -m "refactor: standardise (iface, ms) interface for immediately-executing tools"
```

---

### Task 2F: Standardise — persistent plot tools

**Files to modify:**
- `tools/loggereditor.py` — `LoggerEditor`
- `tools/customplot/_customplot.py` — `CustomPlot`

**`LoggerEditor`** — `__init__(parent, settingsdict1, obsid)` creates Matplotlib figure immediately and calls `self.show()`. Move figure creation and show() call to `show()`:

```python
# BEFORE
class LoggerEditor(QMainWindow):
    def __init__(self, parent, settingsdict1=None, obsid=""):
        super().__init__(parent)
        self.settingsdict = settingsdict1
        self.obsid = obsid
        # Matplotlib setup
        self.calibrplotfigure = plt.figure()
        self.axes = self.calibrplotfigure.add_subplot(111)
        self.canvas = FigureCanvas(self.calibrplotfigure)
        self.mpltoolbar = NavigationToolbar(...)
        # ... signal connections ...
        self.show()

# AFTER
class LoggerEditor(QMainWindow):
    def __init__(self, iface, ms):
        super().__init__(iface.mainWindow())
        self._iface = iface
        self.settingsdict = ms.settingsdict
        self.obsid = ""
        setupUi(self)
        # signal connections only — NO Matplotlib setup, NO self.show()

    def show(self) -> None:
        # Matplotlib setup deferred here
        self.calibrplotfigure = plt.figure()
        self.axes = self.calibrplotfigure.add_subplot(111)
        self.canvas = FigureCanvas(self.calibrplotfigure)
        self.mpltoolbar = NavigationToolbar(self.canvas, self.widget_plot)
        self._layout_plot_widgets()
        super().show()
        self.activateWindow()

    def _layout_plot_widgets(self):
        # extract the canvas/toolbar layout additions from old __init__
        ...
```

**`CustomPlot`** — `__init__(parent, msettings)` does DB queries immediately. This is a persistent window — the DB queries in `__init__` run once. Keep them there (deferred init on a persistent window that's created once is fine). Just rename args:

```python
# BEFORE
class CustomPlot(QMainWindow):
    def __init__(self, parent, msettings):
        super().__init__(parent)
        self.ms = msettings
        self.ms.load_settings()
        self.tables_columns = db_utils.tables_columns(...)
        ...

# AFTER
class CustomPlot(QMainWindow):
    def __init__(self, iface, ms):
        super().__init__(iface.mainWindow())
        self._iface = iface
        self.ms = ms
        self.ms.load_settings()
        self.tables_columns = db_utils.tables_columns(...)  # kept: persistent window, runs once
        ...

    def show(self) -> None:
        super().show()
        self.activateWindow()
```

- [ ] **Step 1: Apply changes to `LoggerEditor`**
- [ ] **Step 2: Apply changes to `CustomPlot`** (in `tools/customplot/_customplot.py`)
- [ ] **Step 3: Run tests**

```bash
python3 -m pytest test/ -x -m spatialite
```

- [ ] **Step 4: Commit**

```bash
git add tools/loggereditor.py tools/customplot/_customplot.py
git commit -m "refactor: standardise (iface, ms) interface for persistent plot tools"
```

---

### Task 2G: Standardise — SectionPlot (most complex)

`SectionPlot` is the most complex case. The plugin's `plot_section()` handler has 157 lines of validation that belong inside the tool. Move all of it into `SectionPlot.show()`.

**File to modify:** `tools/sectionplot/_sectionplot.py`

**Step-by-step breakdown:**

- [ ] **Step 1: Read the current `plot_section()` method in `midvatten_plugin.py` in full**

Read lines 1296–1453. Understand the validation logic:
- Checks for a line layer being selected
- Validates geometry type (must be LineString)
- Gets obs_points layer
- Checks obs_points not in edit mode (inline, not via the standard utility)
- Gets selected features from the line layer
- Calls `self.sectionplot.create_new_plot(msettings, selected_obspoints, line_layer)`

- [ ] **Step 2: Update `SectionPlot.__init__`**

```python
# BEFORE
class SectionPlot(QDockWidget):
    def __init__(self, parent1, iface1):
        super().__init__(parent1)
        self.parent = parent1
        self.iface = iface1
        self.figures = {}
        ...
        setupUi(self)
        self.init_ui()

# AFTER
class SectionPlot(QDockWidget):
    def __init__(self, iface, ms):
        super().__init__(iface.mainWindow())
        self.iface = iface
        self._ms = ms
        self.figures = {}
        ...
        setupUi(self)
        self.init_ui()
        # no self.show() — dispatcher handles that
```

- [ ] **Step 3: Add `show()` to `SectionPlot` that absorbs all validation from the plugin handler**

Read lines 1296–1453 of `midvatten_plugin.py` (the full `plot_section()` method body). Then write `show()` by pasting that body and applying three substitutions:
- `self.ms` → `self._ms`
- `self.sectionplot.create_new_plot(...)` → `self.create_new_plot(...)`
- Remove the `if not hasattr(self, "sectionplot"):` lazy-init guard (the class IS the sectionplot)

```python
def show(self) -> None:
    """Validate layers and trigger section plot.
    All validation moved from midvatten_plugin.plot_section() lines 1296-1453."""
    # --- paste body of plot_section() here with substitutions above ---
    # End with:
    self.create_new_plot(self._ms.settingsdict, selected_obspoints, line_layer)
    super().show()
    self.activateWindow()
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest test/ -x -m spatialite
```

- [ ] **Step 5: Commit**

```bash
git add tools/sectionplot/_sectionplot.py
git commit -m "refactor: move 157-line plot_section validation into SectionPlot.show()"
```

---

### Task 2H: Standardise — ExportData

`ExportData` currently receives `(obsid_p, obsid_l)` — selected obsids from the plugin handler. Move the selection fetching into `show()`.

**File to modify:** `tools/export_data.py`

- [ ] **Step 1: Read `export_csv()` in `midvatten_plugin.py`** to understand exactly how `obsid_p` and `obsid_l` are built.

- [ ] **Step 2: Apply changes to `ExportData`**

```python
# BEFORE
class ExportData:
    def __init__(self, obsid_p, obsid_l):
        self.ID_obs_points = obsid_p
        self.ID_obs_lines = obsid_l

# AFTER
class ExportData:
    def __init__(self, iface, ms):
        self._iface = iface
        self._ms = ms

    def show(self) -> None:
        ms = self._ms
        iface = self._iface
        # Fetch obsid_p from obs_points layer
        obs_points_layers = iface.mapLayersByName(ms.settingsdict["obs_points"])
        if obs_points_layers:
            self.ID_obs_points = tuple(
                str(f["obsid"])
                for f in obs_points_layers[0].selectedFeatures()
            )
        else:
            self.ID_obs_points = ()
        # Fetch obsid_l from obs_lines layer (optional layer)
        obs_lines_layers = iface.mapLayersByName(ms.settingsdict.get("obs_lines", ""))
        if obs_lines_layers:
            self.ID_obs_lines = tuple(
                str(f["obsid"])
                for f in obs_lines_layers[0].selectedFeatures()
            )
        else:
            self.ID_obs_lines = ()
        # Show export dialog (existing method)
        self.export_2_csv()

    def export_2_csv(self):
        ...  # unchanged; uses self.ID_obs_points and self.ID_obs_lines
```

- [ ] **Step 3: Run tests**

```bash
python3 -m pytest test/ -x -m spatialite
```

- [ ] **Step 4: Commit**

```bash
git add tools/export_data.py
git commit -m "refactor: standardise (iface, ms) for ExportData; move obsid selection inside show()"
```

---

### Task 2I: Standardise — NewDb and LoadLayers

`NewDb` and `LoadLayers` are used multiple ways from the plugin. They get callbacks in ActionSpec instead of tool_class, so we give them clean `show_*` methods.

**Files to modify:**
- `tools/create_db.py` — `NewDb`
- `tools/loadlayers.py` — `LoadLayers`

**`NewDb`** — already has `__init__(self)` with no args. Add two show methods:

```python
class NewDb:
    def __init__(self):
        self.db_settings = ""

    def show_sqlite(self) -> None:
        """Entry point for creating a new SpatiaLite DB."""
        import configparser
        cfg = configparser.ConfigParser()
        cfg.read(os.path.join(os.path.dirname(__file__), '..', 'metadata.txt'))
        verno = cfg.get('general', 'version')
        self.create_new_spatialite_db(verno)

    def show_postgis(self) -> None:
        """Entry point for creating a new PostGIS DB."""
        import configparser
        cfg = configparser.ConfigParser()
        cfg.read(os.path.join(os.path.dirname(__file__), '..', 'metadata.txt'))
        verno = cfg.get('general', 'version')
        self.create_new_postgis_db(verno)

    def create_new_spatialite_db(self, verno, ...):
        ...  # unchanged

    def create_new_postgis_db(self, verno, ...):
        ...  # unchanged
```

Note: The `metadata.txt` path reading was previously done in the plugin handler. Move it into the show methods above, extracting the path from `__file__` rather than relying on the plugin object.

**`LoadLayers`** — already takes `(iface, settingsdict, group_name)`. Rename `settingsdict` to use `ms`:

```python
# BEFORE
class LoadLayers:
    def __init__(self, iface, settingsdict=None, group_name="Midvatten_OBS_DB"):
        self.iface = iface
        self.settingsdict = settingsdict

# AFTER — used via callbacks, not tool_class, so no show() needed
# Just rename for internal consistency; callbacks in ActionSpec pass ms.settingsdict
class LoadLayers:
    def __init__(self, iface, settingsdict=None, group_name="Midvatten_OBS_DB"):
        self.iface = iface
        self.settingsdict = settingsdict
        # unchanged — constructor still does the work immediately
```

`LoadLayers` stays as-is since it's used via `callback` in ActionSpec:
```python
callback=lambda: LoadLayers(self.iface, self.ms.settingsdict, "Midvatten_data_domains")
```

- [ ] **Step 1: Add `show_sqlite()` and `show_postgis()` to `NewDb`** (move verno reading from plugin)
- [ ] **Step 2: No changes needed to `LoadLayers`** (stays callback-driven)
- [ ] **Step 3: Run tests**

```bash
python3 -m pytest test/ -x -m spatialite
```

- [ ] **Step 4: Commit**

```bash
git add tools/create_db.py
git commit -m "refactor: add show_sqlite/show_postgis to NewDb; read verno internally"
```

---

## Phase 2 — ActionSpec Manifest + Dispatcher

Phase 1 must be fully committed and all tests green before starting Phase 2. In Phase 2, `midvatten_plugin.py` is transformed: the ~40 handler methods are replaced by the `_ACTIONS` list and `_dispatch()`.

---

### Task 3: Add ActionSpec dataclass and _dispatch() to plugin

**File to modify:** `midvatten_plugin.py`

- [ ] **Step 1: Add imports at top of `midvatten_plugin.py`**

```python
from dataclasses import dataclass, field
from typing import Callable
```

- [ ] **Step 2: Add `ActionSpec` dataclass after imports, before the `Midvatten` class**

```python
@dataclass
class ActionSpec:
    id: str
    label: str
    icon: str
    menu: str  # "import" | "export" | "edit" | "plot" | "report" | "db" | "utils"
    tool_class: type | None = None
    callback: Callable[[], None] | None = None
    needs_db: bool = True
    critical_layers: tuple[str, ...] = field(default_factory=tuple)
    needs_selection: bool = False
    needs_active_layer: str | None = None
    persistent: bool = False
```

- [ ] **Step 3: Add `_dispatch()` method to the `Midvatten` class**

```python
@common_utils.general_exception_handler
@common_utils.waiting_cursor
def _dispatch(self, spec: ActionSpec) -> None:
    """Single entry point for all plugin actions."""
    if spec.needs_db:
        err_flag = midvatten_utils.verify_msettings_loaded_and_layer_edit_mode(
            self.iface, self.ms, spec.critical_layers
        )
        if err_flag:
            return
    if spec.needs_selection:
        # verify_layer_selection(err_flag, threshold): err_flag=0 (fresh), threshold=0 (≥1 feature)
        err_flag = common_utils.verify_layer_selection(0, 0)
        if err_flag:
            return
    if spec.needs_active_layer:
        # verify_this_layer_selected_and_not_in_edit_mode(err_flag, layername)
        err_flag = common_utils.verify_this_layer_selected_and_not_in_edit_mode(
            0, spec.needs_active_layer
        )
        if err_flag:
            return

    # Persistent window reuse
    if spec.persistent:
        existing = self._open_tools.get(spec.id)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return

    # Run callback or tool
    if spec.callback is not None:
        spec.callback()
        return
    tool = spec.tool_class(self.iface, self.ms)
    tool.show()
    if spec.persistent:
        self._open_tools[spec.id] = tool
```

- [ ] **Step 4: Add `self._open_tools: dict = {}` to `Midvatten.__init__`**

- [ ] **Step 5: Run tests** (no behavior change yet)

```bash
python3 -m pytest test/ -x -m spatialite
```

- [ ] **Step 6: Commit**

```bash
git add midvatten_plugin.py
git commit -m "refactor: add ActionSpec dataclass and _dispatch() to plugin"
```

---

### Task 4: Build the _ACTIONS list and wire up initGui()

This is the core of Phase 2. Build the complete manifest, update `initGui()` to loop over it.

**File to modify:** `midvatten_plugin.py`

- [ ] **Step 1: Add the complete `_ACTIONS` list** after the `ActionSpec` dataclass definition (module level, before the `Midvatten` class). The full list — one entry per action. Verify each entry against the original handler method before removing it.

```python
def _make_actions(plugin: "Midvatten") -> list[ActionSpec]:
    """Build the full action manifest. Called once from initGui()."""
    iface = plugin.iface
    ms = plugin.ms
    return [
        # ── Import ──────────────────────────────────────────────────
        ActionSpec(
            id="import_fieldlogger",
            label=tr("Midvatten", "Import data (Fieldlogger)"),
            icon="fieldlogger.png",
            menu="import",
            tool_class=FieldloggerImport,
            critical_layers=("obs_points", "w_qual_field", "w_levels", "w_flow", "comments"),
        ),
        ActionSpec(
            id="import_csv",
            label=tr("Midvatten", "Import data from CSV"),
            icon="import_csv.png",
            menu="import",
            tool_class=GeneralCsvImportGui,
            critical_layers=("obs_points", "obs_lines", "zz_flowtype"),
            persistent=True,
        ),
        ActionSpec(
            id="import_interlab4",
            label=tr("Midvatten", "Import water quality (Interlab4)"),
            icon="interlab4.png",
            menu="import",
            tool_class=Interlab4Import,
            critical_layers=("obs_points", "w_qual_lab"),
        ),
        ActionSpec(
            id="import_diveroffice",
            label=tr("Midvatten", "Import logger data (DiverOffice)"),
            icon="diveroffice.png",
            menu="import",
            tool_class=DiverofficeImport,
            critical_layers=("obs_points", "w_levels_logger"),
        ),
        ActionSpec(
            id="import_levelogger",
            label=tr("Midvatten", "Import logger data (Levelogger)"),
            icon="levelogger.png",
            menu="import",
            tool_class=LeveloggerImport,
            critical_layers=("obs_points", "w_levels_logger"),
        ),
        ActionSpec(
            id="import_hobologger",
            label=tr("Midvatten", "Import logger data (Hobo)"),
            icon="hobologger.png",
            menu="import",
            tool_class=HobologgerImport,
            critical_layers=("obs_points", "w_levels_logger"),
        ),
        # ── Export ──────────────────────────────────────────────────
        ActionSpec(
            id="export_csv",
            label=tr("Midvatten", "Export data to CSV"),
            icon="export_csv.png",
            menu="export",
            tool_class=ExportData,
            critical_layers=(
                "obs_points", "w_levels", "w_qual_lab", "stratigraphy",
                "comments", "w_flow",
            ),
            needs_selection=True,
        ),
        ActionSpec(
            id="export_spatialite",
            label=tr("Midvatten", "Export to SpatiaLite"),
            icon="export_spatialite.png",
            menu="export",
            tool_class=ExportSpatialite,
            critical_layers=(
                "obs_points", "w_levels", "w_qual_lab", "stratigraphy",
                "comments", "w_flow",
            ),
        ),
        ActionSpec(
            id="export_fieldlogger",
            label=tr("Midvatten", "Export to Fieldlogger"),
            icon="fieldlogger.png",
            menu="export",
            tool_class=ExportToFieldLogger,
            persistent=True,
        ),
        # ── Edit ────────────────────────────────────────────────────
        ActionSpec(
            id="wlvlloggcalibrate",
            label=tr("Midvatten", "Logger calibration"),
            icon="loggereditor.png",
            menu="edit",
            tool_class=LoggerEditor,
            critical_layers=("w_levels_logger", "w_levels"),
            persistent=True,
        ),
        ActionSpec(
            id="wlvlcalculate",
            label=tr("Midvatten", "Calculate water level"),
            icon="calculate_level.png",
            menu="edit",
            tool_class=CalculateLevel,
            critical_layers=("obs_points", "w_levels"),
            needs_active_layer="obs_points",
        ),
        ActionSpec(
            id="calculate_aveflow",
            label=tr("Midvatten", "Calculate average flow"),
            icon="aveflow.png",
            menu="edit",
            tool_class=CalculateAveflow,
            critical_layers=("obs_points", "w_flow"),
            needs_selection=True,
        ),
        # ── Plot ────────────────────────────────────────────────────
        ActionSpec(
            id="plot_timeseries",
            label=tr("Midvatten", "Time series plot"),
            icon="tsplot.png",
            menu="plot",
            tool_class=TimeSeriesPlot,
            needs_selection=True,
        ),
        ActionSpec(
            id="plot_xy",
            label=tr("Midvatten", "XY plot"),
            icon="xyplot.png",
            menu="plot",
            tool_class=XYPlot,
            needs_selection=True,
        ),
        ActionSpec(
            id="plot_piper",
            label=tr("Midvatten", "Piper diagram"),
            icon="piper.png",
            menu="plot",
            tool_class=PiperPlot,
            critical_layers=("w_qual_lab", "w_qual_field"),
            needs_selection=True,
            persistent=True,
        ),
        ActionSpec(
            id="plot_stratigraphy",
            label=tr("Midvatten", "Stratigraphy plot"),
            icon="stratigraphy.png",
            menu="plot",
            tool_class=Stratigraphy,
            needs_selection=True,
            persistent=True,
        ),
        ActionSpec(
            id="plot_section",
            label=tr("Midvatten", "Section plot"),
            icon="sectionplot.png",
            menu="plot",
            tool_class=SectionPlot,
            persistent=True,
        ),
        ActionSpec(
            id="plot_sqlite",
            label=tr("Midvatten", "Custom plot"),
            icon="customplot.png",
            menu="plot",
            tool_class=CustomPlot,
            persistent=True,
        ),
        # ── Report ──────────────────────────────────────────────────
        ActionSpec(
            id="drillreport",
            label=tr("Midvatten", "Drill report"),
            icon="drillreport.png",
            menu="report",
            tool_class=Drillreport,
            critical_layers=("obs_points", "w_levels", "w_qual_lab"),
            needs_selection=True,
        ),
        ActionSpec(
            id="custom_drillreport",
            label=tr("Midvatten", "Custom drill report"),
            icon="drillreport.png",
            menu="report",
            tool_class=DrillreportUi,
            critical_layers=("obs_points", "w_levels", "w_qual_lab"),
        ),
        ActionSpec(
            id="waterqualityreport",
            label=tr("Midvatten", "Water quality report"),
            icon="wqualreport.png",
            menu="report",
            tool_class=Wqualreport,
            needs_selection=True,
        ),
        ActionSpec(
            id="waterqualityreportcompact",
            label=tr("Midvatten", "Compact water quality report"),
            icon="wqualreport_compact.png",
            menu="report",
            tool_class=CompactWqualReportUi,
        ),
        # ── DB management ───────────────────────────────────────────
        ActionSpec(
            id="new_db",
            label=tr("Midvatten", "New SpatiaLite database"),
            icon="newdb.png",
            menu="db",
            callback=lambda: NewDb().show_sqlite(),
            needs_db=False,
        ),
        ActionSpec(
            id="new_postgis_db",
            label=tr("Midvatten", "New PostGIS database"),
            icon="newdb.png",
            menu="db",
            callback=lambda: NewDb().show_postgis(),
            needs_db=False,
        ),
        ActionSpec(
            id="add_midvatten_layers",
            label=tr("Midvatten", "Add Midvatten layers"),
            icon="addlayers.png",
            menu="db",
            callback=lambda: LoadLayers(iface, ms.settingsdict),
        ),
        ActionSpec(
            id="load_data_tables",
            label=tr("Midvatten", "Load data tables"),
            icon="addlayers.png",
            menu="db",
            callback=lambda: LoadLayers(iface, ms.settingsdict, "Midvatten_data_tables"),
        ),
        ActionSpec(
            id="load_data_domains",
            label=tr("Midvatten", "Load data domains"),
            icon="addlayers.png",
            menu="db",
            callback=lambda: LoadLayers(iface, ms.settingsdict, "Midvatten_data_domains"),
        ),
        ActionSpec(
            id="load_strat_symbology",
            label=tr("Midvatten", "Load stratigraphy symbology"),
            icon="strat.png",
            menu="db",
            tool_class=StratSymbology,
            persistent=True,
        ),
        ActionSpec(
            id="vacuum_db",
            label=tr("Midvatten", "Vacuum database"),
            icon="vacuum.png",
            menu="db",
            callback=lambda: db_utils.vacuum_db(ms),
        ),
        ActionSpec(
            id="zip_db",
            label=tr("Midvatten", "Backup database"),
            icon="zip.png",
            menu="db",
            callback=lambda: db_utils.backup_db(ms),
        ),
        ActionSpec(
            id="calculate_db_table_rows",
            label=tr("Midvatten", "Count table rows"),
            icon="count.png",
            menu="db",
            callback=lambda: db_utils.calculate_db_table_rows(ms),
        ),
        # ── Utils ───────────────────────────────────────────────────
        ActionSpec(
            id="list_of_values_from_selected_features",
            label=tr("Midvatten", "List values from selection"),
            icon="values.png",
            menu="utils",
            tool_class=ValuesFromSelectedFeaturesGui,
            needs_db=False,
        ),
        ActionSpec(
            id="prepare_layers_for_qgis2threejs",
            label=tr("Midvatten", "Prepare for Qgis2threejs"),
            icon="qgis2threejs.png",
            menu="utils",
            tool_class=PrepareForQgis2Threejs,
            critical_layers=("obs_points", "stratigraphy"),
        ),
        ActionSpec(
            id="add_view_obs_points_lines",
            label=tr("Midvatten", "Add obs_points/obs_lines view"),
            icon="view.png",
            menu="utils",
            callback=lambda: midvatten_utils.add_view_obs_points_obs_lines(ms),
        ),
        ActionSpec(
            id="add_non_essential_tables",
            label=tr("Midvatten", "Add non-essential tables"),
            icon="tables.png",
            menu="utils",
            callback=lambda: midvatten_utils.add_non_essential_tables(ms),
        ),
    ]
```

> **Note on icons:** The icon filenames above are placeholders based on naming conventions. Check each existing handler's `self.add_action(...)` call in the current `midvatten_plugin.py` to get the exact icon filename and label string before committing. Do not guess icon names.

- [ ] **Step 2: Update `initGui()` to call `_make_actions()` and loop over the manifest**

Replace the existing `_create_actions()`, `_build_menus()`, `_build_toolbar()`, and `_connect_signals()` with a loop:

```python
def initGui(self) -> None:
    self._open_tools: dict = {}
    self._actions: list[ActionSpec] = _make_actions(self)
    self._qactions: dict[str, QAction] = {}

    # Build menus
    menus = {
        "import": self.iface.addPluginToMenu(tr("Midvatten", "&Import"), None) or self._make_submenu("&Import data"),
        # ... etc — read the existing _build_menus() to get the exact submenu labels
    }

    for spec in self._actions:
        action = QAction(
            QIcon(os.path.join(self.plugin_dir, "icons", spec.icon)),
            spec.label,
            self.iface.mainWindow(),
        )
        action.triggered.connect(lambda checked, s=spec: self._dispatch(s))
        self._qactions[spec.id] = action
        # add to correct menu/toolbar — read existing _build_menus() for exact placement
        self.iface.addPluginToMenu(spec.menu_label, action)

    # Settings, About, Help actions (not in _ACTIONS — they don't follow the tool pattern)
    self._add_settings_action()
    self._add_about_action()
```

> **Note:** The existing `_build_menus()` and `_build_toolbar()` contain exact menu structure, separators, and toolbar entries. Read these methods in full and replicate their menu structure inside the new loop. Do not reconstruct from memory.

- [ ] **Step 3: Add `tool_registry.py` logic inline** — read `tool_registry.py` and inline the `add_plugin_action` helper's logic into the loop above. Confirm `tool_registry.py` can then be deleted.

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest test/ -x -m spatialite
```

- [ ] **Step 5: Smoke test** — open the plugin in QGIS and trigger one action from each menu category.

- [ ] **Step 6: Commit**

```bash
git add midvatten_plugin.py
git commit -m "refactor: replace 40 handler methods with _ACTIONS manifest and _dispatch()"
```

---

### Task 5: Remove old handler methods and delete tool_registry.py

- [ ] **Step 1: Delete all the old handler methods** from `midvatten_plugin.py` (the ~40 methods replaced by the manifest). Each one should now be dead code.

- [ ] **Step 2: Delete `tool_registry.py`**

```bash
git rm tool_registry.py
```

- [ ] **Step 3: Search for any remaining imports of `tool_registry`**

```bash
grep -r "tool_registry" .
```
Expected: no matches.

- [ ] **Step 4: Run full test suite**

```bash
python3 -m pytest test/ -x
```

- [ ] **Step 5: Verify line count**

```bash
wc -l midvatten_plugin.py
```
Expected: below 500.

- [ ] **Step 6: Run ruff**

```bash
ruff check --fix . && ruff format .
```

- [ ] **Step 7: Commit**

```bash
git rm tool_registry.py
git add midvatten_plugin.py
git commit -m "refactor: delete tool_registry.py; remove dead handler methods from plugin"
```

---

## Phase 3 — ExportSpatialite Extraction

The `export_spatialite()` handler (~90 lines) becomes a self-contained class. Behavior is preserved exactly — no UX changes.

---

### Task 6: Create ExportSpatialite class

**Files:**
- Create: `tools/export_spatialite.py`
- Modify: `midvatten_plugin.py` — update the `export_spatialite` entry in `_ACTIONS`

- [ ] **Step 1: Read the full `export_spatialite()` method body in `midvatten_plugin.py`** to understand what it does.

- [ ] **Step 2: Read `export_spatialite()` in `midvatten_plugin.py`** (lines ~727–816). Note every import it uses and every `self.iface`/`self.ms` reference.

- [ ] **Step 3: Create `tools/export_spatialite.py`**

Paste the full body of the old handler into `show()`, substituting `self.iface` → `self._iface` and `self.ms` → `self._ms`. Add the required imports at the top of the file.

```python
"""ExportSpatialite — exports the current database to a new SpatiaLite file.

Behavior is identical to the former export_spatialite() handler in
midvatten_plugin.py. All dialog sequences are preserved.
"""
# add all imports used by the former handler body
from midvatten.tools.utils import common_utils, midvatten_utils
from midvatten.tools.utils.db_utils import connection as db_connection
from midvatten.tools.create_db import NewDb
from midvatten.tools.export_data import ExportData


class ExportSpatialite:
    def __init__(self, iface, ms):
        self._iface = iface
        self._ms = ms

    def show(self) -> None:
        # Full body of former export_spatialite() pasted here.
        # self.iface → self._iface, self.ms → self._ms
        iface = self._iface
        ms = self._ms
        # ... pasted body ...
```

- [ ] **Step 3: Update `_ACTIONS` in `midvatten_plugin.py`** — the `export_spatialite` entry should already reference `ExportSpatialite` from the plan above. Add the import at the top of `midvatten_plugin.py`:

```python
from midvatten.tools.export_spatialite import ExportSpatialite
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest test/ -x -m spatialite
```

- [ ] **Step 5: Run ruff**

```bash
ruff check --fix . && ruff format .
```

- [ ] **Step 6: Commit**

```bash
git add tools/export_spatialite.py midvatten_plugin.py
git commit -m "refactor: extract ExportSpatialite class from plugin handler"
```

---

## Final Verification

- [ ] Full test suite passes: `python3 -m pytest test/`
- [ ] `midvatten_plugin.py` is below 500 lines: `wc -l midvatten_plugin.py`
- [ ] `tool_registry.py` is gone: `ls tool_registry.py` → No such file
- [ ] No bare `except Exception` added: `grep -n "except Exception:" tools/*.py tools/**/*.py`
- [ ] Ruff clean: `ruff check .`
- [ ] Manual smoke test in QGIS: one action per menu category triggered and working
