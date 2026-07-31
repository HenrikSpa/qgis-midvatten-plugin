> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-04-22 · modified: 2026-04-22 · archived: 2026-07-31

# Deferred UX Improvements — Notes for Future Plan

**Date:** 2026-04-16
**Status:** Deferred — implement after plugin-structure-homogenisation is complete
**Prerequisite:** `2026-04-16-plugin-structure-homogenisation-design.md` implemented

---

## Why deferred

These improvements require rewriting test mocks: tests currently simulate the current sequential dialog pattern (one dialog question at a time). Moving to unified single dialogs means all those mocks need to be rewritten to set settings on the new dialog. Scope is too large to bundle with the structural refactor.

---

## 1. Logger importer unification

**Problem:** Three separate tools — `DiverofficeImport`, `LeveloggerImport`, `HobologgerImport` — each open with a large wall of format-specification text before the actual import dialog. The format info is not contextual and overwhelms the user. The three tools are structurally nearly identical (all import into `w_levels_logger`, differ only in file format parsing).

**Proposed solution:** One `LoggerImport` tool (`tools/import_logger.py`) with a single dialog containing:
- Format selector (dropdown or radio buttons: DiverOffice / Levelogger / Hobo)
- File selection
- Relevant import settings for the selected format
- Format-specific help text displayed *next to the relevant controls*, not as a pre-import wall of text

Internally, the format-specific parsing is isolated into separate parser classes (already roughly true — the three files are mostly parsing logic). The shared base `MidvDataImporter` from `import_data_to_db.py` is already there.

In the ActionSpec, this becomes **one entry** instead of three.

**Test impact:** The three existing importer tests need to be rewritten for the new unified dialog.

---

## 2. NewDb unified dialog

**Problem:** `new_db()` and `new_postgis_db()` both show: "are you sure?" confirmation → then several sequential single-question dialogs (database path, CRS, version, etc.). This is disorienting — the user cannot see the full set of choices before committing.

**Proposed solution:** One `NewDbDialog` that presents all settings at once — database path / connection parameters, CRS, version — with OK / Cancel. The "are you sure?" question disappears because the user sees all settings before committing and can cancel.

Both SQLite and PostGIS variants become one dialog with a backend selector (tab or dropdown), or two separate dialogs if keeping them separate is cleaner.

**Test impact:** Tests currently mock a sequence of dialog responses. Need rewriting for the unified dialog.

---

## 3. ExportSpatialite unified dialog

**Problem:** `export_spatialite()` currently shows: confirm dialog → EPSG selection dialog → several more sequential questions. Same sequential-dialog anti-pattern as NewDb.

**Proposed solution:** `ExportSpatialiteDialog` — one dialog with all settings (destination path, CRS, which data to include), OK / Cancel. This is the UX upgrade to the `ExportSpatialite` class that was created during the structural refactor.

**Test impact:** Tests currently mock sequential dialogs. Need rewriting.

---

## Implementation notes

- Start with the logger importer unification — it removes two files and simplifies the ActionSpec manifest.
- NewDb and ExportSpatialite dialogs can be done together since they share the same anti-pattern and the same fix.
- Each of these is its own mini-spec + plan cycle before implementation.
