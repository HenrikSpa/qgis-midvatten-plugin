# Design: Worktree Test Import Isolation

**Date:** 2026-04-17
**Status:** Implemented (see Tasks 2–3 of the implementation plan)

## Problem

The QGIS plugin symlink at
`~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/midvatten`
is a single shared resource. When multiple subagents work in parallel git
worktrees, each one repoints this symlink to its own worktree. If agent B
repoints it while agent A is mid-run, agent A's subsequent test imports
silently pull code from agent B's worktree — giving agent A false confidence
in verification results.

## Root Cause

Git worktree directories are named after branches (`plot-screens`,
`logger-series`, `obsid-cascade`, etc.), not `midvatten`. Python's import
system requires a file or directory literally named `midvatten` to appear
somewhere on `sys.path`. In production and historically in tests, the QGIS
plugins symlink fills this role — but it is globally mutable.

## Options Considered

**A. `_pkgroot/midvatten → ..` relative symlink (chosen)**
Commit a relative symlink inside the repo. Every worktree gets its own
private copy automatically on checkout. A root `conftest.py` inserts
`_pkgroot/` into `sys.path` before test collection. No shared state.

**B. Per-worktree QGIS profiles via `QGIS_CUSTOM_DATA_HOME`**
Each worktree uses a separate QGIS profile directory, each with its own
plugin symlink. Requires env-var discipline on every agent invocation and
a per-worktree setup step. More moving parts.

**C. `PYTHONPATH` injection via worktree setup script**
A helper script creates `_testroot/midvatten → ..` and writes a `.env`
file. Requires a manual step for every new worktree; fragile.

## Decision: Option A

Option A is zero-friction. The relative symlink is committed once and
present in every checkout and every future worktree with no extra steps.
The root `conftest.py` is the single authoritative place where the
injection happens.

## Implementation

### `_pkgroot/midvatten` (relative symlink)

Target: `..`

From `<worktree>/_pkgroot/midvatten`, `..` resolves to `<worktree>/`,
which is the `midvatten` package directory. Git stores symlinks as blobs
(the link target as text), so this works on any Unix checkout.

### `conftest.py` (repo root)

```python
import os
import sys

# Why this file exists:
# Worktree dirs are named after branches, not "midvatten", so Python can't
# find the package by name without a midvatten-named entry on sys.path.
# The ~/.local/share/QGIS/.../plugins/midvatten symlink fills that role in
# production, but it is a single shared resource: parallel subagents in
# different worktrees each repoint it to themselves, corrupting each other's
# test imports.
#
# _pkgroot/midvatten is a relative symlink (target: "..") committed to the
# repo. Every worktree has its own private copy pointing to itself, so
# inserting _pkgroot here gives each pytest process an isolated midvatten
# import without touching the shared QGIS plugins symlink.
#
# Note: an earlier root conftest.py (added 2026-04-17, commit 36ba19c,
# removed same day in e597e59) tried patching midvatten.__path__ after
# import. This version is different: it inserts _pkgroot before any import
# happens, so midvatten is found correctly from the first lookup.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "_pkgroot"))
```

## Effect on the Global Symlink

`~/.local/share/QGIS/.../plugins/midvatten` remains in place and is still
useful for running QGIS interactively. It is now irrelevant to tests.
Agents repointing it no longer affects any test run.

## Migrating Existing Worktrees

Each existing worktree needs a merge or rebase from this branch to receive
`_pkgroot/` and `conftest.py`. Until merged, that worktree still depends
on the old symlink. Merge as each worktree finishes its current task.
