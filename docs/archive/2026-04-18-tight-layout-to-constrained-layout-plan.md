> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-04-18 · modified: 2026-04-18 · archived: 2026-07-31

# tight_layout → constrained_layout Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all `tight_layout()` calls with `constrained_layout` and add `layout="constrained"` to bare `plt.figure()` calls in tsplot, xyplot, and piper; remove dead `"tight_layout"` config keys from custplot templates.

**Architecture:** Purely mechanical edits across 9 files — no new abstractions, no interface changes. Each figure creation gets `layout="constrained"` passed at construction time; conflicting `tight_layout()` calls and the `hspace=0.12` GridSpec hint are deleted. Dead template keys are removed.

**Tech Stack:** Python 3, matplotlib, pytest

---

## Files Modified

| File | Change |
|------|--------|
| `tools/loggereditor.py` | `plt.figure(layout="constrained")`, remove `hspace=0.12`, delete 2 `tight_layout()` calls |
| `tools/tsplot.py` | `plt.figure(layout="constrained")` |
| `tools/xyplot.py` | `plt.figure(layout="constrained")` |
| `tools/piper.py` | `plt.figure(layout="constrained")` |
| `definitions/midvatten_defs.py` | Remove `"tight_layout": False` entry |
| `definitions/custplot_templates/default.txt` | Remove `"tight_layout": False` entry |
| `definitions/custplot_templates/report_H469.txt` | Remove `"tight_layout": False` entry |
| `definitions/custplot_templates/report_H350.txt` | Remove `"tight_layout": False` entry |
| `definitions/custplot_templates/report_H250.txt` | Remove `"tight_layout": False` entry |

---

### Task 1: Fix loggereditor.py

**Files:**
- Modify: `tools/loggereditor.py:132` (figure creation)
- Modify: `tools/loggereditor.py:134` (GridSpec hspace)
- Modify: `tools/loggereditor.py:783` (delete tight_layout call)
- Modify: `tools/loggereditor.py:895` (delete tight_layout call)

Context: `loggereditor.py` is the logger calibration editor. It creates a figure with a `GridSpec` (two subplots: main axis and optional reference axis). The `hspace=0.12` GridSpec parameter is overridden/ignored by constrained_layout, so it must be removed to avoid a confusing conflicting hint. Both `tight_layout()` calls simply go away.

- [ ] **Step 1: Change figure creation and remove hspace**

In `tools/loggereditor.py`, find the `show()` method (~line 130). Replace:

```python
self.calibrplotfigure = plt.figure()
self._ref_gs = GridSpec(
    2, 1, figure=self.calibrplotfigure, height_ratios=[3, 1], hspace=0.12
)
```

with:

```python
self.calibrplotfigure = plt.figure(layout="constrained")
self._ref_gs = GridSpec(
    2, 1, figure=self.calibrplotfigure, height_ratios=[3, 1]
)
```

- [ ] **Step 2: Delete the first tight_layout() call**

Find the block around line 783 that reads:

```python
        self.calibrplotfigure.tight_layout()

        if self.axes.legend_ is None:
```

Delete the `self.calibrplotfigure.tight_layout()` line (and its blank line) so it becomes:

```python
        if self.axes.legend_ is None:
```

- [ ] **Step 3: Delete the second tight_layout() call**

Find the block around line 895 that reads:

```python
        self.calibrplotfigure.tight_layout()
        self.canvas.draw()
```

Delete the `self.calibrplotfigure.tight_layout()` line so it becomes:

```python
        self.canvas.draw()
```

- [ ] **Step 4: Verify no tight_layout remains in loggereditor**

```bash
grep -n "tight_layout" tools/loggereditor.py
```

Expected: no output.

- [ ] **Step 5: Run linter**

```bash
ruff check --fix tools/loggereditor.py && ruff format tools/loggereditor.py
```

Expected: no errors.

- [ ] **Step 6: Run tests**

```bash
python3 -m pytest test/ -x -m spatialite -q 2>&1 | tail -5
```

Expected: all pass, 0 failed.

- [ ] **Step 7: Commit**

```bash
git add tools/loggereditor.py
git commit -m "refactor(loggereditor): use constrained_layout, remove tight_layout calls"
```

---

### Task 2: Fix tsplot.py and xyplot.py

**Files:**
- Modify: `tools/tsplot.py:65`
- Modify: `tools/xyplot.py:66`

Both are simple single-subplot figures. The `plt.figure()` comment says "causes conflict with plugins 'statist' and 'chartmaker'" — preserve that comment.

- [ ] **Step 1: Edit tsplot.py**

Find (~line 63):

```python
                fig = (
                    plt.figure()
                )  # causes conflict with plugins "statist" and "chartmaker"
```

Replace with:

```python
                fig = (
                    plt.figure(layout="constrained")
                )  # causes conflict with plugins "statist" and "chartmaker"
```

- [ ] **Step 2: Edit xyplot.py**

Find (~line 64):

```python
                fig = (
                    plt.figure()
                )  # causes conflict with plugins "statist" and "chartmaker"
```

Replace with:

```python
                fig = (
                    plt.figure(layout="constrained")
                )  # causes conflict with plugins "statist" and "chartmaker"
```

- [ ] **Step 3: Run linter**

```bash
ruff check --fix tools/tsplot.py tools/xyplot.py && ruff format tools/tsplot.py tools/xyplot.py
```

Expected: no errors.

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest test/ -x -m spatialite -q 2>&1 | tail -5
```

Expected: all pass, 0 failed.

- [ ] **Step 5: Commit**

```bash
git add tools/tsplot.py tools/xyplot.py
git commit -m "refactor(tsplot,xyplot): use constrained_layout"
```

---

### Task 3: Fix piper.py

**Files:**
- Modify: `tools/piper.py:345`

Piper has one subplot with `axis("off")`. The local `hspace` variable on line 349 reads from `mpl.rcParams["figure.subplot.hspace"]` and is used as a geometric spacing constant for drawing triangles/rhombus in data coordinates — it is completely unrelated to matplotlib's layout engine. Do NOT touch it.

- [ ] **Step 1: Edit piper.py**

Find in `make_plot()` (~line 345):

```python
            fig = plt.figure()
```

Replace with:

```python
            fig = plt.figure(layout="constrained")
```

- [ ] **Step 2: Verify hspace variable is untouched**

```bash
grep -n "hspace" tools/piper.py
```

Expected: one line, something like:
```
349:            hspace = mpl.rcParams["figure.subplot.hspace"] * self.side_length * 2
```

- [ ] **Step 3: Run linter**

```bash
ruff check --fix tools/piper.py && ruff format tools/piper.py
```

Expected: no errors.

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest test/ -x -m spatialite -q 2>&1 | tail -5
```

Expected: all pass, 0 failed.

- [ ] **Step 5: Commit**

```bash
git add tools/piper.py
git commit -m "refactor(piper): use constrained_layout"
```

---

### Task 4: Remove dead "tight_layout" config keys

**Files:**
- Modify: `definitions/midvatten_defs.py:1443`
- Modify: `definitions/custplot_templates/default.txt:89`
- Modify: `definitions/custplot_templates/report_H469.txt:88`
- Modify: `definitions/custplot_templates/report_H350.txt:88`
- Modify: `definitions/custplot_templates/report_H250.txt:88`

This key was never read by any Python code — the customplot figure was already switched to `layout="constrained"` unconditionally. These are dead config entries.

- [ ] **Step 1: Remove from midvatten_defs.py**

Find (~line 1443):

```python
        "tight_layout": False,
```

Delete that line entirely.

- [ ] **Step 2: Remove from default.txt**

In `definitions/custplot_templates/default.txt`, find (~line 89):

```
    "tight_layout": False,
```

Delete that line entirely. Check the surrounding comma structure doesn't break JSON — the line above it ends with `":"` values in a list, and the line below is `"x_Axes_tick_param"`. Ensure the preceding entry still has a trailing comma (it will, since `tight_layout` was a middle entry).

- [ ] **Step 3: Remove from report_H469.txt**

Same edit in `definitions/custplot_templates/report_H469.txt` (~line 88): delete `"tight_layout": False,`.

- [ ] **Step 4: Remove from report_H350.txt**

Same edit in `definitions/custplot_templates/report_H350.txt` (~line 88): delete `"tight_layout": False,`.

- [ ] **Step 5: Remove from report_H250.txt**

Same edit in `definitions/custplot_templates/report_H250.txt` (~line 88): delete `"tight_layout": False,`.

- [ ] **Step 6: Verify no tight_layout remains anywhere in Python files**

```bash
grep -rn "tight_layout" --include="*.py" .
```

Expected: no output.

- [ ] **Step 7: Verify no tight_layout remains in template/defs files**

```bash
grep -rn "tight_layout" definitions/
```

Expected: no output (the metadata.txt changelog mention is in the project root, not definitions/).

- [ ] **Step 8: Run linter on the Python file**

```bash
ruff check --fix definitions/midvatten_defs.py && ruff format definitions/midvatten_defs.py
```

Expected: no errors.

- [ ] **Step 9: Run tests**

```bash
python3 -m pytest test/ -x -m spatialite -q 2>&1 | tail -5
```

Expected: all pass, 0 failed.

- [ ] **Step 10: Commit**

```bash
git add definitions/midvatten_defs.py definitions/custplot_templates/default.txt definitions/custplot_templates/report_H469.txt definitions/custplot_templates/report_H350.txt definitions/custplot_templates/report_H250.txt
git commit -m "chore(custplot): remove dead tight_layout config key from templates and defs"
```

---

### Task 5: Final verification

- [ ] **Step 1: Run full non-PostGIS suite**

```bash
python3 -m pytest test/ -m spatialite -q 2>&1 | tail -10
```

Expected: 419 passed (or similar), 0 failed.

- [ ] **Step 2: Confirm no tight_layout anywhere in codebase**

```bash
grep -rn "tight_layout" --include="*.py" --include="*.txt" . | grep -v metadata.txt | grep -v ".md"
```

Expected: no output.
