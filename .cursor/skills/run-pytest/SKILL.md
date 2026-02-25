---
name: run-pytest
description: Run the midvatten test suite with pytest. Use when running tests, before or after code changes, or when the user asks to run the test suite or pytest.
---

# Run pytest (midvatten test suite)

## When to use

- Before running tests (e.g. before committing or to verify changes).
- When the user asks to run the test suite or pytest.

## Order of running tests

Run tests in this order so failures are easier to diagnose:

1. **First**: Tests named like `test_create_*_db.py` (e.g. `test_create_spatialite_db.py`, `test_create_postgis_db.py`). If these fail, many other tests will also fail.
2. **Second**: Central tests: `test_db_utils*.py`, `test_midvatten_utils*.py`, `test_midvatten_defs*.py`.
3. **Third**: Specific tests that cover the code you changed.
4. **Finally**: The full test suite.

## How to run

- Use **pytest** from the **midvatten** repository root (e.g. `python3 -m pytest`).
- To stop on first failure, add **`-x`**.
- Assertion details are shown by default when a test fails.

## Commands

**Run all active tests:**

```bash
python3 -m pytest test/
```

**Run only SQLite/Spatialite backend tests:**

```bash
python3 -m pytest test/ -m spatialite
```

**Run only PostgreSQL/PostGIS backend tests:**

```bash
python3 -m pytest test/ -m postgis
```

**Run tests for both backends:**

```bash
python3 -m pytest test/ -m "spatialite or postgis"
```

## Examples

From repo root, run create-db tests then full suite:

```bash
cd /path/to/midvatten
python3 -m pytest test/test_create_spatialite_db.py test/test_create_postgis_db.py -x
python3 -m pytest test/ -x
```

Stop on first failure in a subset of tests:

```bash
python3 -m pytest test/ -m spatialite -x
```
