"""Root conftest for the interlab4-obsid-bulk-editor worktree.

Ensures that ``midvatten.tools.obsid_assignment_dialog`` (and any other
new modules added only to this worktree) are importable even when the
installed QGIS-plugin ``midvatten`` package points at a different worktree
or branch.

Strategy: install a sys.meta_path finder that, after the real 'midvatten'
package is imported, inserts this worktree root into midvatten.__path__ and
midvatten.tools.__path__ so new submodules here shadow the installed copy.
"""

import importlib.abc
import importlib.machinery
import sys
from pathlib import Path

_WORKTREE_ROOT = str(Path(__file__).parent.resolve())
_TOOLS_ROOT = str(Path(_WORKTREE_ROOT) / "tools")


def _patch_midvatten():
    """Insert worktree dirs into midvatten / midvatten.tools __path__."""
    pkg = sys.modules.get("midvatten")
    if pkg is not None:
        pth = getattr(pkg, "__path__", None)
        if pth is not None and _WORKTREE_ROOT not in pth:
            pth.insert(0, _WORKTREE_ROOT)
    tools = sys.modules.get("midvatten.tools")
    if tools is not None:
        tpth = getattr(tools, "__path__", None)
        if tpth is not None and _TOOLS_ROOT not in tpth:
            tpth.insert(0, _TOOLS_ROOT)


class _MidvattenPathPatcher(importlib.abc.MetaPathFinder):
    """Fires _patch_midvatten() the first time any midvatten.* import is attempted."""

    _patched = False

    def find_spec(self, fullname, path, target=None):
        if not self._patched and (
            fullname == "midvatten" or fullname.startswith("midvatten.")
        ):
            _patch_midvatten()
            if sys.modules.get("midvatten") is not None:
                _MidvattenPathPatcher._patched = True
        return None  # always fall through to real importers


sys.meta_path.insert(0, _MidvattenPathPatcher())

# Also try immediately in case midvatten is already on sys.modules.
_patch_midvatten()
