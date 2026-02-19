import os
import sys

# Ensure QGIS Python modules are importable when running tests outside QGIS.
# 1) Respect an explicit QGIS_PYTHON_PATH if set
# 2) Fall back to common system locations used on Debian/Ubuntu
_qgis_extra_paths = []
_env_path = os.environ.get("QGIS_PYTHON_PATH")
if _env_path:
    _qgis_extra_paths.extend(_env_path.split(os.pathsep))

_qgis_extra_paths.extend(
    [
        "/usr/share/qgis/python",
        "/usr/lib/qgis/python",
    ]
)

for _p in _qgis_extra_paths:
    if _p and os.path.isdir(_p) and _p not in sys.path:
        # Prepend so that the real QGIS modules win over any stubs.
        sys.path.insert(0, _p)

from qgis.PyQt import QtWidgets
from qgis.core import QgsApplication

# Assurance that this only happens once for each test run
app = QtWidgets.QApplication([])
qgs = QgsApplication([], False)
qgs.initQgis()
