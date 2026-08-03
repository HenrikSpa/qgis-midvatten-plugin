"""
Tests for xyplot.XYPlot's outcome messages: 'no selection' and 'no layer'
must go to the message bar, never a modal popup.
"""

from unittest import mock

import pytest

from midvatten.test import utils_for_tests
from midvatten.tools.xyplot import XYPlot


class _FakeProvider:
    def fieldNameIndex(self, name):
        return -1


class _FakeLayerWithSelection:
    """A layer-like stub that is truthy and reports a selection count."""

    def __init__(self, count):
        self._count = count

    def dataProvider(self):
        return _FakeProvider()

    def selectedFeatureCount(self):
        return self._count

    def __bool__(self):
        return True


class _FakeFalsyLayer:
    """A layer-like stub that behaves as falsy, e.g. an invalid/missing layer."""

    def dataProvider(self):
        return _FakeProvider()

    def __bool__(self):
        return False


@pytest.mark.spatialite
class TestXYPlot(utils_for_tests.MidvattenTestSpatialiteDbSv):
    @mock.patch("midvatten.tools.utils.message_utils.pop_up_info", autospec=True)
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_no_selection_uses_bar_not_popup(self, mock_messagebar, mock_popup):
        """'Please select at least one point with xy data' must reach the
        message bar (warning), never a modal popup."""
        plot = XYPlot(self.iface, self.midvatten.ms)
        plot.showtheplot(_FakeLayerWithSelection(0))
        print(f"{mock_messagebar.mock_calls=}")
        assert not mock_popup.called
        assert mock_messagebar.warning.called

    @mock.patch("midvatten.tools.utils.message_utils.pop_up_info", autospec=True)
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_no_layer_uses_bar_not_popup(self, mock_messagebar, mock_popup):
        """'Please select a layer containing observations with xy data'
        must reach the message bar (warning), never a modal popup."""
        plot = XYPlot(self.iface, self.midvatten.ms)
        plot.showtheplot(_FakeFalsyLayer())
        print(f"{mock_messagebar.mock_calls=}")
        assert not mock_popup.called
        assert mock_messagebar.warning.called
