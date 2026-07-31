> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-06-10 · modified: 2026-06-10 · archived: 2026-07-31

# Design: Update Plot refreshes reference series

**Date:** 2026-04-22

## Problem

In the Logger editor, clicking "Update plot" re-reads the main logger/measurement data from the database and redraws the main axes, but does not refresh the reference series subplot. This means that if the user has plotted the currently selected obsid (or any other well) as a reference series, the reference curve stays stale until the user manually adds/edits/removes a reference series entry.

## Solution

Call `_draw_reference_subplot()` at the end of `update_plot()`, after `_finish_plot()`.

`_draw_reference_subplot()` already handles:
- No reference series configured (hides subplot, no-op).
- Formatter/locator preservation across `ref_axes.cla()`.
- Opening its own DB connection via `use_or_create_connection`.

The only guard in `update_plot()` that affects placement is the `if obsid is None: return` early exit (line 604). The new call sits after that guard, so reference series are only refreshed when the main plot loads successfully — consistent with existing behaviour.

## Change

**File:** `tools/loggereditor.py`  
**Method:** `update_plot()`  
**After line:** `self._finish_plot(handles, labels)`  
**Add:** `self._draw_reference_subplot()`

## Testing

- Manual: open Logger editor, add a reference series, click Update plot — ref series curve should refresh.
- Regression: Update plot with no reference series configured should behave identically to before.
