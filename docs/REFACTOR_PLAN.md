# Midvatten Refactoring Plan – Log

## Scope (excluding Phase 2.2)

- Phase 1.1: Unify string representation helpers
- Phase 1.2: Standardize SQL execution patterns
- Phase 2.1: Split common_utils.py into focused modules
- Phase 3.1: Simplify Drillreport.get_data with dataclass
- Phase 3.2: Consolidate Wqualreport classes
- Phase 3.3: Refactor plugin registration
- Phase 4: Parametrize spatialite/postgis tests

**Excluded:** Phase 2.2 (split sectionplot.py) – too large for current scope.

---

## Log: Done

- **Phase 1.1**: Unified string representation helpers. Extended `anything_to_string_representation` with `compact=True`; `create_test_string` now delegates to it. Tests pass.
- **Phase 3.1**: Simplified Drillreport.get_data with dataclasses. Added `ObsPointsRow` and `StratigraphyRow` in `tools/drillreport_models.py`; `get_data` now returns typed rows and uses parameterized SQL (`sql_literal`, `ident`). All rpt_* methods updated to use named attributes. Tests pass.
- **Phase 2.1**: Split common_utils.py into focused modules. Created `message_utils.py`, `layer_utils.py`, `string_utils.py`, `file_utils.py`, `dialog_utils.py`, `exceptions.py`. `common_utils.py` is now a re-export shim. Updated test mocks for `ask_for_delimiter` to patch `file_utils.ask_for_delimiter`. Tests pass.
- **Phase 1.2**: Standardized SQL execution patterns in wqualreport.py, xyplot.py, tsplot.py. Replaced string concatenation with `dbconnection.ident()`, `placeholder()`, and `execute_args` for parameterized queries. Tests pass.
- **Phase 1.2** (continued): Standardized SQL in wqualreport_compact.py (`get_data_from_sql`: `ident()`, `placeholders()`, `pd.read_sql(..., params=)`). Fixed unsafe SQL in sectionplot.py `plot_specific_water_level` (parameterized `_date`, `sql_ident` for table). Tests pass.
- **Phase 3.2**: Consolidated Wqualreport report path/HTML logic into `tools/wqualreport_core.py` (report_folder, report_path, write_html_preamble, write_html_close, open_report_in_browser). Both wqualreport.py and wqualreport_compact.py use it. Tests pass.
- **Phase 3.3**: Refactored plugin registration: added `tool_registry.add_plugin_action()`; `Midvatten.add_action` now delegates to it. Tests pass.

---

## Log: Remaining

1. Phase 4: Parametrize spatialite/postgis tests (deferred: backend-specific assertions)
