# Instruction for new agent – Phase 4

Copy-paste the text below into a new agent chat to continue Phase 4.

---

Continue the Midvatten refactor: implement Phase 4 (parametrize spatialite/postgis tests).

**Context**
- Refactor plan: `docs/REFACTOR_PLAN.md`. Phase 4 is the only remaining item: "Parametrize spatialite/postgis tests (deferred: backend-specific assertions)."
- Phase 4 plan: `docs/REFACTOR_PHASE4_PLAN.md` (read it first).

**What to do**
1. Read `docs/REFACTOR_PHASE4_PLAN.md` and `test/utils_for_tests.py`. Understand the current Spatialite vs PostGIS base classes and how tests are split.
2. Add a backend-parametrization mechanism in `test/utils_for_tests.py` so the same test class can run with either Spatialite or PostGIS (e.g. parametrized base or test generator).
3. Merge one test pair into a single parametrized module. Start with `test_drillreport_spatialite.py` and `test_drillreport_postgis.py` → single `test_drillreport.py` that runs the same tests for both backends. Handle any backend-specific assertions via the backend parameter.
4. Run tests in this order: `nosetests3 test/test_create_spatialite_db.py test/test_create_postgis_db.py --failure-detail --with-doctest --nologcapture --stop`, then the merged drillreport tests, then the full suite. Follow `.cursor/skills/run-nosetests/SKILL.md` and testing rules (MessagebarAndLog mock, no change to reference data unless intent changes).
5. Update `docs/REFACTOR_PHASE4_PLAN.md` with a short log of what was implemented and what's left (e.g. which pairs are still to merge). Optionally update `docs/REFACTOR_PLAN.md` Phase 4 line.

**Constraints**
- Do not modify database schema. Follow `.cursor/rules/testing-rules/rule-for-modifying-tests.mdc` and `.cursor/rules/core-rules/rule-for-coding-style.mdc`.

---
