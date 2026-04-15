# Design: PostgreSQL Schema Support

**Date:** 2026-04-15  
**Branch:** postgis-schema-support  
**Status:** Approved

## Problem

All PostGIS connections hardcode `schema = "public"`. Users with data in a non-public schema (common in shared enterprise databases) cannot use the plugin. A second plugin also sets `dbconnection.schema` at runtime to redirect CSV imports, but the session `search_path` was never updated — only the explicit `ident()` call in `import_data_to_db.py` was affected.

## Approach

`PostgreSQLBackend` already executes `SET search_path` after connecting; it just hardcodes `"public"`. Making `schema` a configurable, settable property fixes everything:

- All ~126 unqualified SQL queries automatically target the correct schema (no query changes needed)
- `create_layer()` already reads `dbconnection.schemas()` → `dbconnection.schema` and passes it to `QgsDataSourceUri.setDataSource()` — layer loading works automatically
- The external plugin's `dbconnection.schema = "custom"` pattern now also re-executes `SET search_path`

## Architecture

```
QGIS project file (.qgs)
  └── "Midvatten"/"database" key
        └── {'postgis': {'connection': 'name/host/port/db', 'schema': 'monitoring'}}
                                                              ↑ NEW
                                                    defaults to 'public' if absent

midvsettingsdialog.py (PostgisSettings)
  └── schema editable QComboBox
        └── populated via get_available_schemas(dbconnection) → information_schema.schemata

connection.py (create_backend)
  └── reads schema from settings dict
        └── PostgreSQLBackend(connection_name=..., schema='monitoring')
              └── SET search_path = "monitoring", public   ← covers all queries
```

## Files Changed

| File | Change |
|------|--------|
| `tools/utils/db_utils/backends/postgresql.py` | `schema` → settable property; `__init__` accepts `schema=` |
| `tools/utils/db_utils/backends/base.py` | No-op `schema` setter (SQLite safety) |
| `tools/utils/db_utils/connection.py` | Pass schema to backend; `DbConnectionManager.schema` as proxy property |
| `tools/utils/db_utils/schema.py` | New `get_available_schemas()` function |
| `tools/utils/db_utils/__init__.py` | Export `get_available_schemas` |
| `midvsettingsdialog.py` | Schema editable QComboBox in `PostgisSettings` |
| `tools/create_db.py` | `CREATE SCHEMA IF NOT EXISTS`; remove hardcoded `SET search_path = public` |

**No changes** to SQL queries, `loadlayers.py`, `midvatten_utils.py`, or `midvatten_defs.py`.

## Key Decisions

- **search_path always includes `public` as fallback** (`SET search_path = <schema>, public`) so PostGIS functions remain accessible when using a custom schema
- **Schema stored in database dict** alongside connection name (not a separate settings key) — keeps connection config self-contained; backward compatible (missing key defaults to `"public"`)
- **`CREATE SCHEMA IF NOT EXISTS`** at DB creation time — safe no-op if schema exists; requires `CREATE` privilege on DB (users who can create tables always have this)
- **Editable QComboBox** in settings dialog — populated from live DB, but allows typing a new name for fresh databases
- **`CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA public`** — explicit schema for PostGIS to avoid accidentally installing into a custom schema

## Backward Compatibility

- Old project files without `schema` key → `connection_settings.get("schema", "public")` → `"public"` — zero behavior change
- External plugin setting `dbconnection.schema = "custom"` → now also re-executes `SET search_path = "custom", public` via property setter
