> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-04-18 · modified: 2026-04-18 · archived: 2026-07-31

# Design: Migrate tight_layout → constrained_layout

**Date:** 2026-04-18
**Branch:** ai_test (implement in new worktree)
**Scope:** Medium (B+A) — fix all tight_layout usages + add constrained_layout to bare figures + dead config cleanup

## Background

`tight_layout()` is a one-shot call that adjusts subplot spacing at draw time but does not update on resize. `constrained_layout` is a full layout engine that runs on every draw/resize, keeping spacing correct continuously. Matplotlib recommends constrained_layout as the modern approach.

The codebase already uses `layout="constrained"` in `customplot/_customplot.py` and in the dynamic-size branch of `sectionplot/_sectionplot.py`. This migration makes the remaining figures consistent.

## Files Changed

### tools/loggereditor.py (3 edits)

- `plt.figure()` → `plt.figure(layout="constrained")` (line 132)
- Remove `hspace=0.12` from `GridSpec(2, 1, figure=..., height_ratios=[3, 1], hspace=0.12)` — constrained_layout overrides this parameter; leaving it in creates a conflicting hint
- Delete `self.calibrplotfigure.tight_layout()` at line 783
- Delete `self.calibrplotfigure.tight_layout()` at line 895

### tools/tsplot.py (1 edit)

- `plt.figure()` → `plt.figure(layout="constrained")` (line 65)
- Single subplot, standard labels/title — constrained_layout prevents clipping at figure edges

### tools/xyplot.py (1 edit)

- `plt.figure()` → `plt.figure(layout="constrained")` (line 66)
- Same pattern as tsplot

### tools/piper.py (1 edit)

- `plt.figure()` → `plt.figure(layout="constrained")` (line 345)
- **Safe despite custom geometry:** Piper has one subplot with `axis("off")` — no tick labels or axis labels for the layout engine to fit around. The local `hspace` variable (line 349) reads from `mpl.rcParams["figure.subplot.hspace"]` and is used as a geometric spacing constant for drawing triangles/rhombus in data coordinates — it is completely unrelated to matplotlib's layout engine and is unaffected. The `set_rotated_axes_labels` callback fires on `draw_event` (after constrained_layout), so aspect-ratio-based label rotation stays correct.

### Dead config cleanup (5 files)

The `"tight_layout": False` key appears in custplot templates and defaults but is never read by any Python code (customplot already uses `layout="constrained"` unconditionally). Remove the key from:

- `definitions/midvatten_defs.py` (line 1443)
- `definitions/custplot_templates/default.txt` (line 89)
- `definitions/custplot_templates/report_H469.txt` (line 88)
- `definitions/custplot_templates/report_H350.txt` (line 88)
- `definitions/custplot_templates/report_H250.txt` (line 88)

## Files NOT Changed

| File | Reason |
|------|--------|
| `tools/customplot/_customplot.py` | Already on `layout="constrained"` |
| `tools/sectionplot/_sectionplot.py` | Dynamic branch already on constrained; static branch intentionally uses `subplots_adjust` (template-driven) |

## Caveats

- `constrained_layout` cannot be combined with `subplots_adjust()` or `tight_layout()` calls — these are all removed/absent in the affected files
- `GridSpec(hspace=...)` is ignored when constrained_layout is active — so `hspace=0.12` is removed from loggereditor's GridSpec
- No matplotlib version concern: `layout="constrained"` (string form) requires matplotlib ≥ 3.6; QGIS ships ≥ 3.6 on all supported platforms

## Testing

```bash
python3 -m pytest test/ -x -m spatialite
```

No test changes expected — no test directly exercises matplotlib layout rendering.
