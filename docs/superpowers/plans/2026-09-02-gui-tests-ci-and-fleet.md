# Plan: GUI tests as a CI gate (Qt6 + Qt5) and across the plugin fleet

Follow-on to the GUI test harness (`test/gui/`). This operationalises the three highest-ROI uses
identified after the harness found 4 Qt6 bugs that the ~200 unit tests (dummy `iface`) could not:
**(1)** run `coverage` on Qt6 as a CI/release gate, **(2)** run both toolkits before release,
**(3)** point the generic-QAction sweep at the other `~/dev` plugins.

## Central decision (blocks 1 & 2): the CI fixture
`coverage` needs a *populated* SpatiaLite DB with the critical layers loaded — but the tutorial DB lives
only in the **wiki** repo, and nothing is committed to the plugin repo. Three options:

- **A. Commit a minimal fixture** — a ~50 KB `test/gui/fixtures/mini.sqlite` with a few rows in every
  critical table, generated once by a script (create_db + a scripted fill from tiny inline CSVs) and
  checked in. CI is then self-contained and fast. **Recommended.**
- B. Build the full tutorial DB in CI via the wiki's `build.py` (checkout the wiki repo + run ~5 min).
  Slower, couples plugin CI to the wiki, but reuses the exact fixture.
- C. Have the harness build the fixture at job start with `create_db` + `fill` (needs the source CSVs
  committed somewhere). Essentially A without a binary blob — a set of tiny CSVs under `test/gui/fixtures/`.

Recommendation: **A** (a committed `mini.sqlite`), with a `make_fixture.py` that regenerates it so it is
reproducible, not a mystery blob. Decide this first; everything else follows.

## Phase 1 — Qt6 coverage as a CI job + release gate
1. `make_fixture.py` → `test/gui/fixtures/mini.sqlite` (option A); commit both.
2. `.github/workflows/gui-qt6.yml` (no CI exists yet): on push + PR, job `services`/`container:
   qgis/qgis:4.2.2`, `pip install pandas pyqt6-webengine`, run the harness `--mode coverage` (and
   `--mode generic_actions`) against `mini.sqlite`. The driver already exits 1 on any FAIL → the job is
   red on any Qt6 breakage. This is the gate: required check on PRs, and required before a release tag.
3. Wire `run_gui_tests.py` to accept the fixture path and run inside an already-running container (CI
   provides the container; no nested `docker run`). Add a thin `--in-container` path that skips the
   docker-run wrapper and calls `xvfb-run qgis --code runner.py ...` directly.

## Phase 2 — both toolkits before release
- Add a **Qt5 job** using `container: qgis/qgis:3.28` (or the pinned 3.x the team ships against): the
  SAME harness/scenes, Qt5. In CI the `--host` variant becomes a second container, not the literal host
  — this sidesteps the Wayland display-leak entirely (no interactive session in CI).
- Matrix: `{qgis:4.2.2 [Qt6], qgis:3.x [Qt5]} × {coverage, generic_actions}`. Both toolkits required to
  pass before a release tag. Keep the local `--host` path for developer use on the Wayland desktop
  (already isolated via `QT_QPA_PLATFORM=xcb` + drop `WAYLAND_DISPLAY`).

## Phase 3 — the fleet (other `~/dev` plugins)
Six in-house plugins face the same Qt6 migration with far fewer unit tests: `midv_inventory`,
`midv_soil3d`, `qgis_midv_tolkn_plugin`, `dynplot/dynplot`, `midv_addons/midv_addons`,
`dd/drawdowndiagnistic` (plus third-party `Qgis2threejs`, lower priority).

- **3a — Feasibility audit (parallel, subagents, read-only — running now):** one agent per in-house
  plugin. Each: find the entry (`classFactory` / plugin class), inventory external deps beyond
  qgis/PyQt/stdlib, and grep for the 5 Qt6 risk patterns that bit midvatten —
  (i) `addDockWidget(` with a non-enum first arg, (ii) unscoped Qt/class enum members,
  (iii) `.ui` `<enum>` values removed in Qt6 (e.g. `AdjustToMinimumContentsLength`),
  (iv) `setFlags(...ItemIsSelectable)` without `ItemIsEnabled`, (v) `.exec_(`. Report a
  **feasibility rating** (easy/medium/hard to sweep), **concrete risk findings (file:line)**, and what a
  sweep would need (menu registration? a DB fixture?). No containers in this phase — pure read.
- **3b — Generic fleet sweep:** a driver that mounts each plugin (+ its deps) into the qgis/qgis:4.2.2
  container and runs `generic_actions` (menu-QAction discovery, no per-plugin manifest needed). Fixtures
  per plugin as 3a determines. Unique `--name` per container; never `ancestor=`-filtered `docker kill`.
- **3c — Triage & fix** the Qt6 bugs found, per plugin.

## Where subagents help (and don't)
- **Phase 3a is the natural parallel win** — 6 independent, read-only plugin audits. Dispatched now.
- **Phases 1 & 2 are one coherent CI design** hinging on the fixture decision — better done as a single
  sequential piece (one implementer) than fanned out. Not subagent work until the fixture is decided.

## Sequencing
Decide the fixture (A/B/C) → Phase 1 → Phase 2 (adds the Qt5 job) → Phase 3b/3c (after 3a reports land).
Phase 3a runs concurrently now and does not block 1/2.
