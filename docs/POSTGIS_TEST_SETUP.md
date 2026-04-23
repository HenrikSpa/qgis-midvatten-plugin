# PostGIS Test Database Setup

Documents the steps needed to run the PostGIS-marked tests locally.

## Prerequisites

- PostgreSQL 17 running on `127.0.0.1:5432` (installed via `postgresql-17`)
- Current OS user (<CHANGE TO USER>) has a superuser role in PostgreSQL
- PostGIS extension available (`postgresql-17-postgis-3` package)

## Steps

### 1. Create the test database

```bash
psql postgres -c "CREATE DATABASE nosetests;"
```

Skip if `nosetests` already exists (`\l` lists databases).

### 2. Install PostGIS in the test database

```bash
psql -h 127.0.0.1 -p 5432 -U <CHANGE TO USER> -d nosetests -c "CREATE EXTENSION IF NOT EXISTS postgis;"
```

### 3. Configure ~/.pgpass

The tests connect via TCP (`127.0.0.1:5432`) without an explicit password in QGIS
settings. libpq reads `~/.pgpass` to supply the password automatically.

Add entries for both usernames used on this machine:

```
localhost:5432:nosetests:<CHANGE TO USER>:<CHANGE TO DBNAME>
127.0.0.1:5432:nosetests:<CHANGE TO USER>:<CHANGE TO DBNAME>
localhost:5432:nosetests:<CHANGE TO USER>:<CHANGE TO DBNAME>
127.0.0.1:5432:nosetests:<CHANGE TO USER>:<CHANGE TO DBNAME>
```

The file must be owner-readable only:

```bash
chmod 600 ~/.pgpass
```

### 4. Verify

```bash
psql -h 127.0.0.1 -p 5432 -U <CHANGE TO USER> -d nosetests -c "SELECT PostGIS_version();"
python3 -m pytest test/test_create_postgis_db.py -m postgis -x -q
```

Expected: 22 passed.

## How the tests use this

`MidvattenTestPostgisNotCreated` (in `test/utils_for_tests.py`) configures QGIS
settings to point at `127.0.0.1:5432/nosetests` with no stored password. The
PostgreSQL backend (`tools/utils/db_utils/backends/postgresql.py`) falls back to
`PGUSER`/`PGPASSWORD` env vars and then to libpq's own `.pgpass` lookup. As long
as `.pgpass` is present and the extension is installed, no additional configuration
is needed.

Each test resets the database by running `DROP SCHEMA public CASCADE` + `CREATE
SCHEMA public` rather than using a Docker container, so the server must remain
running during the test session.
