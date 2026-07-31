> **2026-07-31 note:** the Root Cause section and Option A are stale — the Shadow has been a
> separate QGIS layer/renderer since 2021 (`tools/strat_symbology.py:329`), and `bars_strat.qml`
> has one `ELSE` rule that `symbology_using_cloning()` deactivates
> (`tools/strat_symbology.py:578`). The bug in the TODO at `tools/strat_symbology.py:99` is
> still open, but re-derive the mechanism (layer stacking, not rule order) before choosing a fix.
> Options B/C, the file pointers and the verification steps below are still usable.

# Finding 5 — Known Logical Bug in `strat_symbology.py`

## Location

`tools/strat_symbology.py:87–88`

```python
def strat_symbology(...):
    """
    TODO: There is a logical bug where layers that should get caught as ELSE isn't because
          the shadow ("maxdepthbot" = "depthbot") gets them...
          I might have to put the shadow in other layer...
    """
```

## Problem Description

The `bars_strat` database view (line 624) includes a `maxdepthbot` column computed as `MAX(depthbot)` per borehole. The Shadow QGIS style layer (`bars_shadow` at line 157) uses this view and applies a visual shadow effect to rows where `"maxdepthbot" = "depthbot"` (i.e., the deepest stratum in each borehole).

The bug: QGIS rule-based symbology evaluates rules in order. The Shadow rule (matching deepest-row stratum) fires on rows that should instead fall through to the ELSE rule (rows whose geoshort is not in any known category). Because `maxdepthbot = depthbot` can be true for any geology type (including unknown ones), the Shadow layer incorrectly catches unknown-geology deepest rows before ELSE can.

**Visual result:** Unknown geology types at the bottom of a borehole get shadow styling instead of the default/ELSE styling.

## Root Cause

The Shadow rule is evaluated in the same rule-based renderer as the geology classification rules. QGIS rule-based symbology is first-match: once a rule matches, ELSE is never evaluated for that feature.

## Fix Options

### Option A (Preferred): Separate the Shadow into its own QGIS renderer layer
- Keep geology classification rules (including ELSE) in the existing `Geology` QGIS layer
- Add a new layer on top of or below it specifically for the shadow, using the same `bars_strat` view
- The shadow layer would only apply a transparent overlay using `"maxdepthbot" = "depthbot"` with no ELSE conflict
- This separates concerns: classification rules stay in one layer, visual effects in another

### Option B: Exclude unknown geoshorts from the Shadow rule
- Modify the Shadow rule filter to: `"maxdepthbot" = "depthbot" AND "geoshort" IN (<known geoshort list>)`
- Pro: minimal change, con: requires maintaining a list of known geoshorts in the rule

### Option C: Move Shadow rule to be evaluated last, before ELSE
- Change rule order so Shadow is last non-ELSE rule
- Pro: simple ordering fix, con: QGIS style XML ordering may be fragile

## Relevant Files

- `tools/strat_symbology.py` — `strat_symbology()` function (line 75), `add_views_to_db()` (line 623)
- `tools/strat_symbology.py` — `group_spec` dict with symbology layer names (lines 146–170)
- The QGIS `.qml` style files in `styles/` directory (contains the actual rule-based symbology XML for `bars_shadow`)

## Investigation Steps Before Fixing

1. Locate the `bars_shadow` QML style file in the `styles/` directory
2. Inspect the rule-based filter expressions in the QML to confirm the Shadow rule's filter
3. Check how `add_bars_symbology()` applies the style (called around line 195 for Geology/Hydro)
4. Decide between Option A or B based on whether the shadow is meant to be a classification or a visual overlay

## Verification

1. Create a test DB with stratigraphy rows where the deepest stratum has an unknown geoshort
2. Run strat_symbology
3. Verify the unknown-geology deepest row uses the ELSE/default style rather than the shadow style
4. Verify known-geology deepest rows still get the shadow visual effect
