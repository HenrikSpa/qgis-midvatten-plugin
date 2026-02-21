# Safe SQL parameterization – progress log

Started: 2025-02-20

## Done
- db_utils.py: PRAGMA foreign_keys (no interpolation); get_table_info (sql_ident for SQLite, placeholders for Postgres); get_foreign_keys (sql_ident for SQLite); get_all_obsids (sql_ident + dbconnection)

## In progress
- db_utils.py second batch done: cast_null (allowed list + ident), test_not_null_and_not_empty_string (ident), test_if_numeric (ident + fixed type list), get_srid_name (placeholder)
- loggereditor.py: load_obsid_and_init (meas_sql, head_level_masl_sql with placeholders + execute_args); getlastcalibration (placeholders); update_level_masl_from_level_masl/from_head (placeholders + sql_alter_db all_args); set_level_masl_to_null/delete period (ident(table_name), placeholders, all_args)

## Done (this session)
- sectionplot.py: plot_water_level_interactive (sql_ident for secplotwlvltab), INSERT temporary section line (sql_ident for temptable_name)
- import_data_to_db.py: get_remaining_rownumbers SQL (sql_ident for temptable_rowid_name, temptable_name); list_to_table_using_pandas Postgres branch (sql_ident for temptable_name, placeholders for values)
- midvatten_plugin.py: waterqualityreport wqual check (sql_ident + execute_args, DbConnectionManager with closedb in finally)
- strat_symbology.py: CREATE VIEW for SQLite uses ident(view_name)
- custom_drillreport.py: stratigraphy query built with f-string + cols_sql/clause (no % for identifiers)
- customplot.py: draw_plot uses ident() for table/columns, placeholders + execute args for filter values; test_customplot_spatialite passes

## Done (test files)
- test_vectorlayer_spatialite.py: INSERT obs_points use placeholder + all_args
- test_db_utils_spatialite.py / test_db_utils_postgis.py: INSERT use placeholder + all_args
- test_midv_qgis2threejs_spatialite.py / test_midv_qgis2threejs_postgis.py: SELECT use sql_ident(layer_name), dbconnection with closedb

## Remaining
- create_db.py (optional: test_about_db_creation)

## Abort/resume
If context is full: start a new agent, open this file and continue from "Remaining". Run tests after each batch: from repo root or test: `nosetests3 test_create_spatialite_db.py --failure-detail --with-doctest --nologcapture` then other tests.
