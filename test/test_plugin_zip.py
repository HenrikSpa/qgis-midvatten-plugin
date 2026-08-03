"""Guards the packaging exclusion lists in plugin_zip_and_upload.py."""

import plugin_zip_and_upload as pz

MUST_IGNORE_FOLDERS = {
    ".git",
    "__pycache__",
    "test",
    ".venv",
    ".worktrees",
    ".logger-import-worktree",
    ".claude",
    ".cursor",
    ".superpowers",
    ".pytest_cache",
    ".ruff_cache",
    ".idea",
    "docs",
    "scripts",
    "_pkgroot",
}
MUST_IGNORE_FILES = {
    ".gitignore",
    "plugin_zip_and_upload.py",
    "conftest.py",
    "pytest.ini",
    "pyproject.toml",
    ".coveragerc",
    "CLAUDE.md",
    ".claudeignore",
    ".cursorignore",
}
MUST_IGNORE_SUFFIXES = {".pyc", ".zip", ".swp", ".swo", ".orig", ".rej"}


def test_ignore_folders_cover_dev_dirs():
    assert MUST_IGNORE_FOLDERS.issubset(set(pz.IGNORE_FOLDERS))


def test_ignore_files_cover_dev_files():
    assert MUST_IGNORE_FILES.issubset(set(pz.IGNORE_FILES))


def test_ignore_suffixes_cover_editor_artifacts():
    assert MUST_IGNORE_SUFFIXES.issubset(set(pz.IGNORE_FILESUFFIX))
