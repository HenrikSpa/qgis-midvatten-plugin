"""Guards the release packaging: `git archive` + export-ignore in .gitattributes."""

import subprocess
import zipfile
from pathlib import Path
from unittest import mock

import pytest

import plugin_zip_and_upload as pz

ROOT = Path(pz.__file__).resolve().parent

# Development baggage that must never reach the QGIS plugin repository.
FORBIDDEN_PREFIXES = (
    "midvatten/test/",
    "midvatten/docs/",
    "midvatten/scripts/",
    "midvatten/.claude/",
    "midvatten/.cursor/",
    "midvatten/.superpowers/",
    "midvatten/_pkgroot/",
)
FORBIDDEN_FILES = {
    "midvatten/.gitignore",
    "midvatten/.gitattributes",
    "midvatten/.claudeignore",
    "midvatten/.cursorignore",
    "midvatten/.coveragerc",
    "midvatten/CLAUDE.md",
    "midvatten/conftest.py",
    "midvatten/pytest.ini",
    "midvatten/pyproject.toml",
    "midvatten/midvatten.pro",
    "midvatten/plugin_zip_and_upload.py",
    "midvatten/i18n/translations.pro",
    "midvatten/tools/sectionplot/generate_ui_types.py",
}
FORBIDDEN_SUFFIXES = (".ts", ".pro", ".pyc")

# Runtime files the plugin cannot work without.
REQUIRED_FILES = {
    "midvatten/__init__.py",
    "midvatten/metadata.txt",
    "midvatten/requirements.txt",
    "midvatten/resources.py",
    "midvatten/midvatten_plugin.py",
    "midvatten/i18n/midvatten_sv_SE.qm",
    "midvatten/ui/midvsettingsdock.ui",
    "midvatten/definitions/upgrade_postgresql_to_2_0_0.sql",
    "midvatten/templates/about_template.htm",
    "midvatten/icons/svg/ref_panel.svg",
}


@pytest.fixture(scope="module")
def archive_names(tmp_path_factory):
    out = tmp_path_factory.mktemp("zip") / "midvatten.zip"
    subprocess.run(
        ["git", "archive", "--format=zip", "--prefix=midvatten/", "-o", out, "HEAD"],
        cwd=ROOT,
        check=True,
    )
    with zipfile.ZipFile(out) as zf:
        return set(zf.namelist())


def test_archive_excludes_development_baggage(archive_names):
    offenders = sorted(
        name
        for name in archive_names
        if name.startswith(FORBIDDEN_PREFIXES)
        or name in FORBIDDEN_FILES
        or name.endswith(FORBIDDEN_SUFFIXES)
    )
    assert not offenders


def test_archive_contains_runtime_files(archive_names):
    assert REQUIRED_FILES <= archive_names


def test_create_zipfile_refuses_uncommitted_changes():
    dirty = mock.Mock(stdout=" M midvatten_plugin.py\n")
    with mock.patch.object(pz.subprocess, "run", return_value=dirty) as run:
        with pytest.raises(SystemExit):
            pz.create_zipfile()
    assert run.call_count == 1  # never reached git archive


def test_create_zipfile_archives_head_under_midvatten_prefix():
    clean = mock.Mock(stdout="")
    with mock.patch.object(pz.subprocess, "run", return_value=clean) as run:
        path = pz.create_zipfile()
    archive_cmd = run.call_args_list[1].args[0]
    assert archive_cmd[:5] == [
        "git",
        "archive",
        "--format=zip",
        "--prefix=midvatten/",
        "-o",
    ]
    assert archive_cmd[-1] == "HEAD"
    assert path == str(ROOT / "midvatten.zip")
