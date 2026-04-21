# Design: screen table QML form files

**Date:** 2026-04-21
**Status:** Approved

## Problem

The `screen` table is loaded as a QGIS layer (it is in `OBS_DB_LAYERS`) but has no `screen.qml` style file. Without a QML, QGIS uses the "Auto-generate" form layout. QGIS's `QgsRelationEditorWidget`, embedded in the obs_points attribute form "screens" tab, cannot properly render the auto-generated form, so it displays as a blank white square.

Additionally, the screen table has no Swedish column aliases, unlike every other Midvatten table.

## Root cause

`definitions/screen.qml` and `definitions/screen_sv.qml` do not exist. All other non-spatial tables loaded by `LoadLayers` (stratigraphy, w_levels, comments, etc.) have QML files that set `editorlayout=tablayout`, which is required for the relation editor widget to embed the form correctly.

No changes are needed to `loadlayers.py` — the relation registration is already correct. No changes are needed to `obs_points.qml` — `buttons="63"` already enables all relation editor buttons (including Add), and `forceSuppressFormPopup="0"` combined with `featformsuppress=1` in the screen QML produces inline editing (no popup) when adding rows via the obs_points form.

## Solution

Create two QML files following the exact pattern of the other non-spatial table QMLs.

### `definitions/screen.qml`

- QGIS format: 2.6.1-Brighton (matching all other Midvatten QMLs)
- `editorlayout=tablayout`
- `featformsuppress=1`
- Single `attributeEditorContainer` named `"Screen"` with all six columns in schema order

### `definitions/screen_sv.qml`

Identical to `screen.qml` plus an `<aliases>` block:

| Column | Swedish alias |
|---|---|
| `screenid` | `filter nr` |
| `depthtop` | `från djup under my (m)` |
| `depthbot` | `till djup under my (m)` |
| `screenshort` | `filterkod` |
| `screen` | `filtertyp` |

`obsid` has no alias (consistent with all other QMLs).

## Screen table schema (reference)

```sql
CREATE TABLE screen (
  obsid     text    NOT NULL,
  screenid  integer NOT NULL,
  depthtop  double,
  depthbot  double,
  screenshort text,
  screen    text,
  UNIQUE (obsid, screenid)
)
```

## Behaviour after fix

- obs_points "screens" / "filter" tab renders the relation editor widget correctly (no white square)
- Clicking "+" in the relation widget adds a new screen row inline (no popup) — same as stratigraphy/comments
- Swedish locale loads `screen_sv.qml` automatically via the existing `_apply_style` locale check in `loadlayers.py`
- Older DBs without the screen table are unaffected (placeholder path in `_register_relations` is unchanged)

## Files changed

| File | Action |
|---|---|
| `definitions/screen.qml` | Create |
| `definitions/screen_sv.qml` | Create |
