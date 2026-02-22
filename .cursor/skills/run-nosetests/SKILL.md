---
name: run-nosetests
description: Run the midvatten test suite with nosetests3 in the recommended order and with the right flags. Use when running tests, before or after code changes, or when the user asks to run the test suite or nosetests.
---

# Run nosetests (midvatten test suite)

## When to use

- Before running tests (e.g. before committing or to verify changes).
- When the user asks to run the test suite or nosetests.

## Order of running tests

Run tests in this order so failures are easier to diagnose:

1. **First**: Tests named like `test_create_*_db.py` (e.g. `test_create_spatialite_db.py`, `test_create_postgis_db.py`). If these fail, many other tests will also fail.
2. **Second**: Central tests: `test_db_utils*.py`, `test_midvatten_utils*.py`, `test_midvatten_defs*.py`.
3. **Third**: Specific tests that cover the code you changed.
4. **Finally**: The full test suite.

## How to run

- Use **nosetests3** from the **midvatten** repository root or from the **midvatten/test** folder.
- Recommended flags to see the cause of failures:

  ```bash
  nosetests3 --failure-detail --with-doctest --nologcapture --stop
  ```

- **`--stop`**: Stop on first failure.
- **`--failure-detail`**: Show detailed failure info.
- **`--with-doctest`**: Include doctests.
- **`--nologcapture`**: Don’t capture logs (so log output is visible). Omit if a failing test is too noisy; some log messages are informational only.

## Examples

From repo root, run create-db tests then full suite:

```bash
cd /path/to/midvatten
nosetests3 test/test_create_spatialite_db.py test/test_create_postgis_db.py --failure-detail --with-doctest --nologcapture --stop
nosetests3 test/ --failure-detail --with-doctest --nologcapture --stop
```

From the test folder:

```bash
cd /path/to/midvatten/test
nosetests3 --failure-detail --with-doctest --nologcapture --stop
```
