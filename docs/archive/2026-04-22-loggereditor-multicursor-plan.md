> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-04-22 · modified: 2026-04-22 · archived: 2026-07-31

# Logger Editor — Multicursor Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a toggleable crosshair button to the logger editor toolbar that shows a `+` multicursor across the 1–2 visible subplots.

**Architecture:** Copy the `Multicrosshair` pattern from dynplot verbatim: a `MultiCursorButton(NavigationButton)` class in `loggereditor.py` wraps `matplotlib.widgets.MultiCursor`, toggling its `.visible` flag when the toolbar button is checked/unchecked. No new files; no schema changes.

**Tech Stack:** Python 3, matplotlib (`MultiCursor`, `RectangleSelector`), PyQt5 (via QGIS)

---

## File Map

| Action | Path |
|--------|------|
| Copy (binary) | `icons/crosshair.png` — new file, copied from dynplot |
| Modify | `tools/loggereditor.py` — add import, add class, wire in `show()` |

---

### Task 1: Copy the crosshair icon

**Files:**
- Create: `icons/crosshair.png`

- [ ] **Step 1: Copy the icon**

```bash
cp /home/hsai1/dev/dynplot/dynplot/icons/crosshair.png \
   /home/hsai1/dev/midv/midvatten/icons/crosshair.png
```

- [ ] **Step 2: Verify it landed**

```bash
ls -lh icons/crosshair.png
```

Expected: file exists, non-zero size.

- [ ] **Step 3: Commit**

```bash
git add icons/crosshair.png
git commit -m "feat(loggereditor): add crosshair icon for multicursor button"
```

---

### Task 2: Add `MultiCursor` to imports and add `MultiCursorButton` class

**Files:**
- Modify: `tools/loggereditor.py`

- [ ] **Step 1: Extend the existing `matplotlib.widgets` import**

Current line (~line 27):
```python
from matplotlib.widgets import RectangleSelector
```

Change to:
```python
from matplotlib.widgets import MultiCursor, RectangleSelector
```

- [ ] **Step 2: Add the class at the end of `loggereditor.py`** (after `MoveNodesButton`, before `_iter_filter_combos`)

```python
class MultiCursorButton(NavigationButton):
    def __init__(self, parent, fig):
        super().__init__(parent, fig)
        self._button_setup = [
            (
                "show crosshair",
                self.clicked,
                "Show crosshair",
                os.path.join(os.path.dirname(__file__), "..", "icons", "crosshair.png"),
            )
        ]
        self.connect_toolbar()
        self.mc = MultiCursor(
            fig.canvas, fig.axes, horizOn=True, vertOn=True, color="k", lw=0.8, ls="--"
        )
        self.mc.visible = False

    def button(self):
        return list(self.actions.values())[0]

    def clicked(self):
        self.mc.visible = self.button().isChecked()
        if not self.mc.visible:
            self.fig.canvas.draw_idle()
```

- [ ] **Step 3: Lint**

```bash
ruff check --fix tools/loggereditor.py && ruff format tools/loggereditor.py
```

Expected: no errors reported.

- [ ] **Step 4: Commit**

```bash
git add tools/loggereditor.py
git commit -m "feat(loggereditor): add MultiCursorButton class"
```

---

### Task 3: Wire the button in `LoggerEditor.show()`

**Files:**
- Modify: `tools/loggereditor.py` (~line 181)

- [ ] **Step 1: Instantiate the button in `show()`**

Find this block (around line 180–181):
```python
            self.select_nodes_button = SelectNodesButton(self, self.calibrplotfigure)
            self.move_nodes_button = MoveNodesButton(self, self.calibrplotfigure)
```

Change to:
```python
            self.select_nodes_button = SelectNodesButton(self, self.calibrplotfigure)
            self.move_nodes_button = MoveNodesButton(self, self.calibrplotfigure)
            self.multi_cursor_button = MultiCursorButton(self, self.calibrplotfigure)
```

- [ ] **Step 2: Lint**

```bash
ruff check --fix tools/loggereditor.py && ruff format tools/loggereditor.py
```

Expected: no errors.

- [ ] **Step 3: Run the existing test suite to confirm no regressions**

```bash
python3 -m pytest test/test_loggereditor_refseries.py -x -q
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add tools/loggereditor.py
git commit -m "feat(loggereditor): wire MultiCursorButton into show()"
```

---

## Manual Verification

After all tasks:

1. Open QGIS, load the Midvatten plugin, open the Logger Editor.
2. Load an obsid with logger data so the main plot appears.
3. Confirm a crosshair icon appears in the matplotlib toolbar.
4. Click it — moving the mouse should show a `+` crosshair on the main subplot.
5. Configure a reference series so the lower subplot becomes visible.
6. Confirm the crosshair tracks across both subplots simultaneously.
7. Uncheck the button — crosshair disappears.
