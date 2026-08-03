A toolset for managing and working with hydrogeological observational data. Distributed under the terms of the GNU GPL License v2.

NOTE: This is as of 2025-05-16 the official and maintained repository for the Midvatten plugin (forked from https://github.com/jkall/qgis-midvatten-plugin).

## Installation & dependencies

**QGIS version:** Requires QGIS ≥ 3.40.

**Python packages:** This plugin requires numpy, pandas, and matplotlib. These packages are installed automatically by the `qpip` plugin dependency (present on most QGIS installations). When you first install Midvatten, a `qpip` dialog will appear asking to install these packages — click "Install" to proceed. This is a one-time step.

**PostGIS support:** If you plan to connect to PostgreSQL/PostGIS databases, you will also need the `psycopg2` package. This is optional and only required for PostGIS; SQLite/SpatiaLite databases do not need it.

**For changelog and detailed release notes,** see the `metadata.txt` file in this repository, specifically the `changelog=` section.

## Features

The following features are included:

  * Database generator
  * Load Default Layers
  * Simple edit tools
  * View plots, eg.
    * Time series
    * Piper Diagram
    * Stratigraphy plot
    * Geological section plots
  * View reports
    * Water quality report
    * General obspoint (e.g. drill hole) report
  * Importing/Exporting tools
    * various csv formats
    * [DiverOffice] ( http://www.vanessen.com/products/software/diver-office) files from Water Level Dataloggers from [vanEssen instruments] (http://www.vanessen.com)
    * FieldLogger files from the [FieldLogger app] (https://play.google.com/store/apps/details?id=nl.artesia.fieldlogger)

Please visit the [wiki](https://github.com/henrikspa/qgis-midvatten-plugin/wiki) for more information.

For database upgrade instructions (including the `w_logger_series`
change in DB version 1.10.0) and direct-SQL patterns for working with
the new schema, see
[`docs/LOGGER_SERIES_MIGRATION.md`](docs/LOGGER_SERIES_MIGRATION.md).

## Development

### Coding style

This project follows PEP 8 naming conventions:

- **Classes:** CapWords (e.g. `MidvattenSettingsDock`)
- **Functions, methods, variables:** `lowercase_with_underscores`
- **Constants:** `UPPER_CASE_WITH_UNDERSCORES`

Run the linter from the repository root:

```bash
ruff check midvatten/
ruff format midvatten/
```

New code must pass `ruff check` before merging.

_Copyright (c) 2016 Josef Källgården_
