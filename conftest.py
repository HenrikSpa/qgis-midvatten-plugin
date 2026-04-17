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
