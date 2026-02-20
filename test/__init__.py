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
        os.path.join(__file__, '..')
    ]
)

for _p in _qgis_extra_paths:
    if _p and os.path.isdir(_p) and _p not in sys.path:
        # Prepend so that the real QGIS modules win over any stubs.
        sys.path.insert(0, _p)

from qgis.core import QgsApplication

# Initialise a single global QGIS application instance for tests.
# We deliberately avoid creating a separate QtWidgets.QApplication here,
# as that can conflict with other Qt event loops under pytest.
if QgsApplication.instance() is None:
    qgs = QgsApplication([], False)
    qgs.initQgis()
else:
    qgs = QgsApplication.instance()
