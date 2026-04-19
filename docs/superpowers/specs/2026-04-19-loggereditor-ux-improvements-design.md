# Logger Editor UX Improvements — Design Spec

**Date:** 2026-04-19  
**Branch:** ai_test  
**File:** `tools/loggereditor.py`

## Context

The logger editor (`LoggerEditor` in `tools/loggereditor.py`) recently gained a reference series dock panel (`QDockWidget`, object name `ref_series_dock`). Two UX issues were found:

1. **Panel lost after close** — Closing the dock with its "x" button hides it. The only restore path is `View > Reference series` (a `toggleViewAction()` already wired to the menu), but users don't discover this. A visible toolbar toggle button is the fix.

2. **List requires two clicks to edit** — Selecting an item in the reference series `QListWidget` and then clicking "Edit" works, but double-clicking an item should also open the editor. No double-click handler exists today.

## Fix 1 — Toolbar toggle button

Add a `QToolBar` to the `LoggerEditor` QMainWindow containing the dock's built-in `toggleViewAction()`. The action is checkable: checked = dock visible, unchecked = dock hidden. The toolbar state stays in sync automatically because `toggleViewAction()` is owned by the dock.

**Changes in `_setup_ref_dock()`:**
- Add `QToolBar` to the `QtWidgets` import block
- Create a `QToolBar` labelled "Reference series" and add it to the window with `self.addToolBar()`
- Call `ref_toolbar.addAction(self._ref_dock.toggleViewAction())`

## Fix 2 — Double-click to edit

Connect `self._ref_list.itemDoubleClicked` to a lambda that calls `self._on_edit_ref_series()`. The signal passes the clicked item as an argument, which is discarded via `lambda _:`. The existing handler uses `currentRow()`, which is already set correctly when the double-click fires.

**Change in `_setup_ref_dock()`:**
- Add one line: `self._ref_list.itemDoubleClicked.connect(lambda _: self._on_edit_ref_series())`

## Files to modify

| File | What changes |
|------|-------------|
| `tools/loggereditor.py` | Add `QToolBar` import; add toolbar + double-click connection in `_setup_ref_dock()` |

No other files, no schema changes, no new classes.

## Verification

1. Open the logger editor in QGIS
2. **Toolbar test**: Confirm toolbar row appears with a "Reference series" checkable button
3. **Close test**: Close the dock with its "x" → button unchecks; click toolbar button → dock reappears
4. **Double-click test**: Add at least one reference series; double-click it in the list → `RefSeriesDialog` opens pre-filled with that series' data
5. **Edit button still works**: Select an item, click Edit → same dialog opens
6. Run `python3 -m pytest test/ -x -m spatialite` to confirm no regressions
