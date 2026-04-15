"""Single point of truth for Matplotlib Qt backend imports.

Handles the rename from backend_qt5agg (Matplotlib < 3.6 era) to
backend_qtagg (Matplotlib 3.6+). Import FigureCanvas and NavigationToolbar
from here instead of duplicating try/except blocks.
"""

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.backends.backend_qtagg import (
        NavigationToolbar2QT as NavigationToolbar,
    )
except ImportError:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.backends.backend_qt5agg import (
        NavigationToolbar2QT as NavigationToolbar,
    )

__all__ = ["FigureCanvas", "NavigationToolbar"]
