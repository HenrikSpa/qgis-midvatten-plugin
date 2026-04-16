#! /usr/bin/env python
"""
midvatten.tools.sectionplot — section-plot package.

Public API re-exports so that existing import paths remain valid:

    from midvatten.tools.sectionplot import SectionPlot
    from midvatten.tools.sectionplot import get_legend_items_labels
    from midvatten.tools.sectionplot import SectionPlotFigure
    from midvatten.tools.sectionplot import SectionPlotLegendManager

Mock-patch compatibility: the test suite patches symbols via the module-level
path ``midvatten.tools.sectionplot.common_utils``.  When sectionplot was a
single file those attributes were naturally available as module attributes.
Now that it is a package we must re-export the sub-module objects that tests
patch so that ``mock.patch("midvatten.tools.sectionplot.common_utils")`` still
resolves correctly.
"""

# Re-export sub-modules so mock.patch("...sectionplot.<module>") still works.
# When sectionplot was a single file, these were naturally available as module
# attributes (e.g. mock.patch("midvatten.tools.sectionplot.common_utils")).
# Now that it is a package we must make them accessible through the package.
from midvatten.tools.utils import common_utils  # noqa: F401
import midvatten.definitions.midvatten_defs as defs  # noqa: F401

from midvatten.tools.sectionplot._sectionplot import (  # noqa: F401
    SectionPlot,
    get_legend_items_labels,
    get_plot_label_name,
    tabwidget_resize,
    resample,
    groupby,
    longdateformat,
    df_idx_as_datetime,
    df_idx_as_datetime64,
    nan_helper,
    get_slider_idx,
    get_length_map,
    fill_empty_columns,
    sample_polygon,
)
from midvatten.tools.sectionplot.figure import SectionPlotFigure  # noqa: F401
from midvatten.tools.sectionplot.legend import SectionPlotLegendManager  # noqa: F401
