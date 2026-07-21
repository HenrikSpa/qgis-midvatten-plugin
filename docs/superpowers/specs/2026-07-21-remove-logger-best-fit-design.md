# Remove Automatic Logger-Elevation Best Fit — Design

**Date:** 2026-07-21
**Scope:** Logger editor calibration controls

## Goal

Simplify calibration by removing the automatic workflow that infers logger
elevation from `head_cm` and manual measurements. The editor will retain three
distinct operations:

1. Calculate `level_masl` from `head_cm` and a user-entered logger elevation.
2. Fit existing `level_masl` values automatically to manual measurements.
3. Add a user-entered offset to existing `level_masl` values.

## User Interface

Remove the **Calculate best fit (auto)** button from the “Calculate from water
head” section. Keep the manual elevation field and **Calculate** button.

Keep **Fit to measurements (auto)**, the offset field and **Add** button, and
the search-radius input. Change the search-radius label from the plural
“Auto methods search radius” to wording that refers only to the remaining
automatic fit method.

No other layout or calibration controls change.

## Application Logic

Remove the signal connection and `logger_pos_best_fit()` wrapper used only by
the deleted button. Simplify `calc_best_fit()` so it always compares manual
measurements with existing `level_masl`, writes the resulting difference to the
offset field, and applies that offset through the existing buffered edit path.

The shared calibration state remains because it still distinguishes the two
manual operations: calculating from logger elevation and adding an offset.
Matching by search radius, selection-period handling, undo/redo, dirty-state
tracking, and database saving remain unchanged.

## Error Handling

Retain the current messages for invalid search-radius input and for periods in
which no logger values can be matched to manual measurements. Removing the
automatic elevation path introduces no new failure mode.

## Tests

Update logger calibration tests to exercise the remaining automatic fit through
`level_masl_best_fit()` instead of setting internal calibration state and
calling the generic helper directly. Add a UI regression assertion that the
removed button is not exposed while the remaining calibration controls are
still present.

Run:

```bash
python3 -m pytest test/test_wlevels_calc_calibr.py -q
```

The pre-change baseline is 64 passing tests with one unrelated Matplotlib
warning.

## Out of Scope

- Changing the best-fit matching algorithm.
- Renaming unrelated historical “best fit” terminology.
- Changing database schemas or persisted logger data.
- Altering the three remaining calibration operations.
