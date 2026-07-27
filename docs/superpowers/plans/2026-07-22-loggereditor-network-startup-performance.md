# Logger Editor Network Startup Performance Plan

> **For agentic workers:** Follow the repository workflow in `CLAUDE.md`: use
> `superpowers:using-git-worktrees` before implementation and `simplify` after
> code changes. Write the structural and timing tests before changing production
> behavior.

**Goal:** Make the Logger Editor's database bootstrap fast over high-latency
connections by loading the observation-point/calibration summary with one query
and reusing one database connection for all startup metadata.

**Architecture:** Extract the synchronous database portion of `LoggerEditor.show()`
into one small bootstrap method. It owns one `DbConnectionManager` for its whole
lifetime and returns plain startup data: observation-point labels, logger schema
variant, optional columns, and the two table timezones. Replace the separate
"all obsids" and "uncalibrated obsids" reads with one backend-specific latest-row
summary query. Add a narrow bulk-column-name helper and a bulk-timezone helper so
metadata does not repeatedly enumerate the database catalog.

**Why network latency is the target:** With no configured reference series, the
current editor startup opens six database connections and executes approximately
12 SQLite or 16 PostgreSQL queries. The action preflight opens one additional
connection. Local connection setup is cheap, but repeated PostgreSQL TCP/SSL/auth
handshakes and query round trips dominate on a network database.

**Expected database-only startup after this work:**

| Metric | Current SQLite | Current PostgreSQL | Target SQLite | Target PostgreSQL |
|---|---:|---:|---:|---:|
| Editor connections | 6 | 6 | 1 | 1 |
| Action + editor connections | 7 | 7 | 2 | 2 |
| Obsid/calibration queries | 2 | 2 | 1 | 1 |
| Editor startup queries | about 12 | about 16 | at most 5 | at most 3 |

The query targets assume a bulk column-name query: three SQLite `PRAGMA` calls,
or one PostgreSQL `information_schema.columns` call; one timezone query; and one
obsid/calibration-summary query. Reference-series queries are intentionally out of
scope for this plan and must be disabled in the startup benchmark fixture.

**Files expected to change:**

- `tools/loggereditor.py`
- `tools/utils/db_utils/schema.py`
- `tools/utils/db_utils/helpers.py`
- `tools/utils/db_utils/__init__.py`
- `test/test_wlevels_calc_calibr.py`
- `test/test_db_utils.py`
- optionally `test/test_loggereditor_startup_performance.py` if keeping the
  instrumentation isolated makes the tests clearer
- `pytest.ini` only if an opt-in `performance` marker is added

**Non-goals:** No database schema/index changes, no reference-series optimization,
no asynchronous UI work, no plot changes, no connection pool for the whole plugin,
and no change to which raw timestamp is considered latest.

---

## Task 1: Characterize results and record the network-latency baseline

- [ ] **Add correctness fixtures for the combined summary.**

  Cover:

  - an empty logger table;
  - multiple sorted obsids;
  - a calibrated latest row;
  - an uncalibrated latest row (`level_masl IS NULL` and `head_cm IS NOT NULL`);
  - a latest row with both values null, which is not marked uncalibrated;
  - older uncalibrated data followed by a calibrated row;
  - the existing same-raw-timestamp case, preserving current backend behavior;
  - filtering status for one obsid, used after a save.

  Assert the exact combobox strings, order, empty selection, and legacy public
  helper results. Do not weaken the existing
  `test_editor_starts_without_loading_an_obsid` contract.

- [ ] **Add a recording connection/factory for startup tests.**

  Record:

  - `DbConnectionManager` constructions;
  - `execute_and_fetchall` calls and normalized SQL text;
  - elapsed connection and execution time separately;
  - backend type.

  Wrap a real SpatiaLite connection for integration coverage. Use a small stub for
  PostgreSQL SQL-shape tests so no PostgreSQL service is required by the default
  suite.

- [ ] **Write a failing structural startup test.**

  Exercise only the extracted/intended database bootstrap path with
  `loggered_ref_series` set to `[]`. Assert the target contract:

  - exactly one editor-owned connection;
  - exactly one query reading `w_levels_logger` for the obsid/calibration summary;
  - no call from startup to `get_all_obsids_in_w_levels_logger()` followed by a
    separate `get_uncalibrated_obsids()` call;
  - at most five SQLite startup statements;
  - every helper receives the same connection object.

  The test should fail against the current implementation because startup owns no
  shared connection and uses two logger queries.

- [ ] **Add a repeatable latency benchmark test.**

  Use `time.perf_counter()` and five or more repetitions, reporting the median.
  Inject fixed latency at the actual abstraction boundaries, for example:

  - 40 ms per `DbConnectionManager` construction;
  - 10 ms per `execute_and_fetchall` call.

  Compare two paths over the same fixture:

  1. a test-local legacy strategy that reproduces the current six-connection,
     two-summary-query startup sequence;
  2. the production bootstrap method.

  Print both medians and the speed-up factor. The reliable regression assertions
  remain connection/query counts; the elapsed assertion is supporting evidence
  and should use a generous bound, such as optimized median below 60% of legacy
  median. Mark this test `performance` if its sleeps make the default suite
  noticeably slower.

- [ ] **Run the tests before production changes and record the baseline.**

  Record connection count, query count, legacy median, and current production
  median. A failure of the new target assertions is expected at this stage.

---

## Task 2: Replace the two logger scans with one summary query

- [ ] **Add one internal summary method.**

  Add a method shaped like:

  ```python
  get_obsids_with_calibration_status(
      obsid: str | None = None,
      dbconnection: DbConnectionManager | None = None,
  ) -> list[tuple[str, bool]]
  ```

  It must return one sorted row per obsid: `(obsid, is_uncalibrated)`.

- [ ] **Preserve the existing latest-row semantics.**

  For SQLite, combine the current grouped `MAX(date_time)` query and status test
  into one result set. For PostgreSQL, retain the current `DISTINCT ON (obsid)` and
  raw `ORDER BY obsid, date_time DESC` behavior, adding the status expression to
  that result. Do not switch to normalized timestamps in this performance change;
  mixed/malformed and tied raw timestamps make that a separate correctness topic.

- [ ] **Populate the combobox directly from the summary rows.**

  Build the final labels once and call `addItems()` once. Avoid the current second
  pass that repeatedly edits combobox items. If a membership collection remains
  anywhere, make it a `set`, not a list.

- [ ] **Keep compatibility wrappers small.**

  Retain `get_all_obsids_in_w_levels_logger()` and `get_uncalibrated_obsids()` if
  tests or external callers depend on them, but implement them as projections of
  the new summary method and let callers pass an existing connection. Startup must
  call the combined method exactly once rather than both wrappers.

- [ ] **Run the summary correctness and SQL-shape tests for both dialects.**

  PostgreSQL tests may use a recording stub for SQL/parameters. Run real PostGIS
  integration tests when the configured service is available.

---

## Task 3: Use one connection and batch the metadata queries

- [ ] **Extract one database-bootstrap method from `show()`.**

  The method should open a `DbConnectionManager` in a context/finally block and
  pass it to every database helper. It should return or assign all database-derived
  startup state together:

  - obsid labels and calibration flags;
  - `w_levels_logger` columns;
  - whether `w_logger_series` exists;
  - `w_levels_logger` timezone;
  - `w_levels` timezone;
  - schema variant.

  Do not leave helper calls that silently create their own connections.

- [ ] **Add a narrow bulk column-name helper.**

  Add a schema helper that accepts a sequence of table names and returns
  `{table_name: [column_name, ...]}` without fetching primary-key metadata:

  - SQLite: one `PRAGMA table_info(...)` per requested table; a missing table
    yields an empty list.
  - PostgreSQL: one parameterized `information_schema.columns` query for all
    requested tables and the active schema.

  This is deliberately narrower than `tables_columns()`. Do not change the broad
  helper's behavior for unrelated callers merely to optimize Logger Editor.

- [ ] **Add a bulk timezone helper.**

  Load both table timezone descriptions in one parameterized query. Reuse already
  loaded `about_db` column names so the helper does not enumerate schema metadata
  again. Keep `get_timezone_from_db()` as a one-table compatibility wrapper and
  centralize the existing description parsing in one function.

- [ ] **Close the shared connection exactly once on every path.**

  Add coverage for successful startup and a forced query exception. Preserve
  current user-facing error reporting and ensure a partially initialized editor
  does not retain a live connection.

- [ ] **Do not broaden scope into the action preflight.**

  The existing preflight connection remains, so end-to-end action startup targets
  two total connections. Returning a live connection from the generic verifier
  would affect every plugin action and should be evaluated separately only if the
  real-network measurements still show a material problem.

---

## Task 4: Demonstrate the speed-up

- [ ] **Run the injected-latency comparison.**

  Report:

  ```text
  legacy median:    ... ms (6 connections, 12/16 queries)
  optimized median: ... ms (1 connection, <=5/<=3 queries)
  speed-up:          ...x
  ```

  Expected modeled time with 40 ms connection and 10 ms query latency is about
  360 ms versus 90 ms for SQLite-shaped startup, before constant Python/UI work.
  Actual measured values, not this model, go in the implementation report.

- [ ] **Measure an ordinary local SpatiaLite fixture.**

  Run at least ten repetitions and report the median, but do not require a large
  local speed-up. The acceptance condition is no meaningful regression; local
  database work is already fast and Qt/Matplotlib may dominate whole-window time.

- [ ] **Measure a real network PostGIS database when available.**

  With the same project and no reference series, record at least five cold editor
  database-bootstrap runs before and after. Report median and range, connection
  count, query count, host latency context, and whether SSL/service configuration
  is in use. Never store credentials or connection strings in benchmark output.

- [ ] **Run `EXPLAIN` only as a diagnostic.**

  This plan reduces round trips rather than changing indexes. Confirm the combined
  latest-row query does not introduce an obviously worse plan on a representative
  large table, but do not add schema indexes without a separate proposal.

---

## Task 5: Regression verification

- [ ] Run focused SpatiaLite tests:

  ```bash
  python3 -m pytest \
    test/test_wlevels_calc_calibr.py \
    test/test_db_utils.py \
    -m spatialite -x -v
  ```

- [ ] Run the full Logger Editor test set:

  ```bash
  python3 -m pytest \
    test/test_wlevels_calc_calibr.py \
    test/test_loggereditor_series.py \
    test/test_loggereditor_dupes.py \
    test/test_loggereditor_resolve_ui.py \
    test/test_loggereditor_separation.py \
    test/test_loggereditor_refseries.py \
    test/test_loggereditor_plot_limits.py \
    test/test_loggereditor_plot_interaction.py \
    -m spatialite -x -v
  ```

- [ ] Run PostgreSQL-focused tests when the configured test database is available.
  If unavailable, record that explicitly and rely on the SQL-shape unit tests plus
  CI rather than claiming live PostgreSQL verification.

- [ ] Run Ruff on changed files, then the repository-required `simplify` review and
  rerun affected tests.

---

## Acceptance criteria

- Editor database bootstrap constructs exactly one `DbConnectionManager`.
- End-to-end action startup constructs at most two connections: preflight plus
  editor bootstrap.
- Startup reads obsids and their latest calibration status with one query.
- SQLite editor bootstrap uses at most five database statements; PostgreSQL uses
  at most three, excluding configured reference-series work.
- Existing combobox ordering, suffixes, empty initial selection, legacy schemas,
  timezone parsing, and same-timestamp behavior remain unchanged.
- The injected-latency benchmark reports a clear wall-clock improvement and its
  structural counts explain that improvement.
- Local SpatiaLite startup does not regress materially.
- A real network PostGIS before/after result is reported when such a database is
  available; absence of that environment is stated, not hidden.
