#!/usr/bin/env python3
"""Run the pre-release build steps for the Midvatten plugin.

Steps (each can be skipped with a flag):

1. Regenerate the SOURCES/FORMS lists in midvatten.pro from the files on disk.
2. pylupdate5  -> refresh i18n/midvatten_*.ts with new translate() strings.
3. lrelease    -> compile i18n/midvatten_*.ts into the .qm files QGIS loads.
4. pyrcc5      -> regenerate resources.py from resources.qrc (import line is
                  rewritten to qgis.PyQt so it works on both Qt5 and Qt6).
5. Static Qt6 guard test and metadata/pyproject version consistency.
6. --zip: build midvatten.zip from HEAD with `git archive` (needs a clean,
   committed tree; exclusions come from .gitattributes export-ignore).

Tool lookup: pylupdate5 / pyrcc5 / lrelease are searched on PATH, then in
$MIDV_QT_TOOLS_BIN. `pip install PyQt5` in any venv provides pylupdate5 and
pyrcc5; lrelease comes from the Qt tools package (qttools5-dev-tools).

Usage:
    python3 scripts/prepare_release.py            # steps 1-5
    python3 scripts/prepare_release.py --zip      # steps 1-6
    python3 scripts/prepare_release.py --only-zip # step 6 only
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRO_FILE = ROOT / "midvatten.pro"
I18N = ROOT / "i18n"
TS_FILES = sorted(I18N.glob("midvatten_*.ts"))

# Modules that carry no user-facing strings, or are not shipped.
PRO_SKIP_FILES = {
    "resources.py",
    "plugin_zip_and_upload.py",
    "conftest.py",
    "tools/utils/util_translate.py",
    "tools/sectionplot/generate_ui_types.py",
}
PRO_SKIP_DIRS = {
    "test",
    "docs",
    "scripts",
    "_pkgroot",
    ".venv",
    ".claude",
    ".cursor",
    ".worktrees",
    ".superpowers",
    "__pycache__",
}


def find_tool(name: str) -> str:
    path = shutil.which(name)
    if path:
        return path
    extra = os.environ.get("MIDV_QT_TOOLS_BIN")
    if extra and (Path(extra) / name).exists():
        return str(Path(extra) / name)
    sys.exit(
        f"{name} not found on PATH or in $MIDV_QT_TOOLS_BIN. "
        "pylupdate5/pyrcc5: `pip install PyQt5` in a venv and point "
        "MIDV_QT_TOOLS_BIN at its bin/. lrelease: install qttools5-dev-tools."
    )


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print("$", " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT, check=True, **kwargs)


def _tracked_python_sources() -> list[str]:
    out = run(["git", "ls-files", "*.py"], capture_output=True, text=True).stdout
    keep = []
    for rel in out.split():
        parts = Path(rel).parts
        if parts[0] in PRO_SKIP_DIRS or rel in PRO_SKIP_FILES:
            continue
        if Path(rel).name == "__init__.py":
            continue
        keep.append(rel)
    return sorted(keep)


def regenerate_pro() -> None:
    """Rewrite SOURCES and FORMS in midvatten.pro; TRANSLATIONS is left as is."""
    sources = _tracked_python_sources()
    forms = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "ui").glob("*.ui"))
    text = PRO_FILE.read_text(encoding="utf-8")
    translations = re.search(r"TRANSLATIONS = \\\n.*", text, flags=re.S)
    if translations is None:
        sys.exit("midvatten.pro has no TRANSLATIONS block")

    def block(name: str, items: list[str]) -> str:
        return f"{name} = \\\n" + "".join(f"./{item} \\\n" for item in items) + "\n"

    PRO_FILE.write_text(
        block("SOURCES", sources) + block("FORMS", forms) + translations.group(0),
        encoding="utf-8",
    )
    print(f"midvatten.pro: {len(sources)} sources, {len(forms)} forms")


def update_ts() -> None:
    # No -noobsolete: obsolete entries keep old translations available in
    # Qt Linguist if a string comes back; lrelease ignores them anyway.
    run([find_tool("pylupdate5"), "-verbose", str(PRO_FILE)])


def compile_qm() -> None:
    run([find_tool("lrelease"), *map(str, TS_FILES)])


def compile_resources() -> None:
    target = ROOT / "resources.py"
    run([find_tool("pyrcc5"), "-o", str(target), str(ROOT / "resources.qrc")])
    text = target.read_text(encoding="utf-8")
    text = text.replace("from PyQt5 import QtCore", "from qgis.PyQt import QtCore")
    target.write_text(text, encoding="utf-8")


def check_versions_and_static_guards() -> None:
    metadata = (ROOT / "metadata.txt").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    meta_version = re.search(r"^version=(.+)$", metadata, flags=re.M).group(1).strip()
    py_version = re.search(r'^version = "(.+)"$', pyproject, flags=re.M).group(1)
    if meta_version != py_version:
        sys.exit(
            f"Version mismatch: metadata.txt={meta_version}, pyproject.toml={py_version}"
        )
    print(f"version {meta_version} consistent")
    run([sys.executable, "-m", "pytest", "-q", "test/test_qt6_compat_static.py"])


def build_zip() -> None:
    sys.path.insert(0, str(ROOT))
    from plugin_zip_and_upload import create_zipfile  # noqa: E402

    path = create_zipfile()
    listing = run(["unzip", "-l", path], capture_output=True, text=True).stdout
    print(listing.splitlines()[-1].strip(), "->", path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--skip-pro", action="store_true")
    parser.add_argument("--skip-ts", action="store_true", help="skip pylupdate5")
    parser.add_argument("--skip-qm", action="store_true", help="skip lrelease")
    parser.add_argument("--skip-resources", action="store_true", help="skip pyrcc5")
    parser.add_argument("--skip-checks", action="store_true")
    parser.add_argument("--zip", action="store_true", help="also build midvatten.zip")
    parser.add_argument("--only-zip", action="store_true", help="only build the zip")
    args = parser.parse_args()

    if args.only_zip:
        build_zip()
        return
    if not args.skip_pro:
        regenerate_pro()
    if not args.skip_ts:
        update_ts()
    if not args.skip_qm:
        compile_qm()
    if not args.skip_resources:
        compile_resources()
    if not args.skip_checks:
        check_versions_and_static_guards()
    if args.zip:
        build_zip()
    else:
        print("Done. Review `git diff`, commit, then run with --only-zip.")


if __name__ == "__main__":
    main()
