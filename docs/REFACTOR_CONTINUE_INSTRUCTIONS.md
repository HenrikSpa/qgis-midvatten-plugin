# Instructions to Continue Midvatten Refactoring

Copy-paste this to a new agent to continue the refactoring build.

## Context

The midvatten repository is being refactored per `docs/REFACTOR_PLAN.md`. Phase 2.2 (split sectionplot.py) is excluded. The following has been completed:

- **Phase 1.1**: Unified string representation helpers. `create_test_string` in `test/utils_for_tests.py` now delegates to `common_utils.anything_to_string_representation(anything, compact=True)`.
- **Phase 3.1**: Drillreport simplified with dataclasses. New file `tools/drillreport_models.py` defines `ObsPointsRow` and `StratigraphyRow`. `tools/drillreport.py` `get_data` returns typed rows and uses parameterized SQL (`db_utils.sql_literal`, `dbconnection.ident`).
- **Phase 2.1**: Split common_utils.py into focused modules (message_utils, layer_utils, string_utils, file_utils, dialog_utils, exceptions). common_utils.py is a re-export shim.
- **Phase 1.2**: Standardized SQL in wqualreport.py, xyplot.py, tsplot.py, wqualreport_compact.py, sectionplot.py.
- **Phase 3.2**: Consolidated Wqualreport report logic into `tools/wqualreport_core.py`.
- **Phase 3.3**: Refactored plugin registration into `tool_registry.add_plugin_action`.

## Remaining Tasks (in order)

1. **Phase 4**: Parametrize spatialite/postgis tests (deferred: backend-specific assertions).

## Constraints

- Do **not** modify database schema (see `.cursor/rules/database-sql-rules/rule-not-modify-database-schema.mdc`).
- Follow `.cursor/rules/testing-rules/rule-for-creating-tests.mdc` and `rule-for-running-tests.mdc`.
- Run tests after each phase: `nosetests3 test/test_create_spatialite_db.py test/test_create_postgis_db.py --failure-detail --with-doctest --nologcapture --stop` then full suite.
- Update `docs/REFACTOR_PLAN.md` after each completed phase.

## Test Run

```bash
cd /home/hsai1/dev/midv/midvatten
nosetests3 test/test_create_spatialite_db.py test/test_create_postgis_db.py --failure-detail --with-doctest --nologcapture --stop
nosetests3 test/ --failure-detail --with-doctest --nologcapture --stop
```
