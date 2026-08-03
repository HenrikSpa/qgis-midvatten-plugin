from unittest import mock
import pytest
from qgis.core import QgsProject

from midvatten.test import utils_for_tests
from midvatten.tools import strat_symbology
from midvatten.tools.utils import string_utils
from midvatten.tools.utils import db_utils


class StratSymbologyMixin:
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_strat_symbology(self, mock_messagebar):
        db_utils.sql_alter_db(
            """INSERT INTO obs_points (obsid, h_gs, geometry) VALUES ('1', 5, ST_GeomFromText('POINT(1 2)', 3006))"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO stratigraphy (obsid, stratid, depthtop, depthbot, geology, geoshort, capacity, development) VALUES ('1', 1, 0, 1, 'sand', 'sand', '3', 'j')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO stratigraphy (obsid, stratid, depthtop, depthbot, geology, geoshort, capacity, development) VALUES ('1', 2, 1, 4.5, 'morän', 'morän', '3', 'j')"""
        )

        @mock.patch("qgis.utils.iface", autospec=True)
        def _test(self, mock_iface):
            mock_mapcanvas = mock_iface.mapCanvas.return_value
            mock_mapcanvas.layerCount.return_value = 0
            self.midvatten.load_strat_symbology()
            self.ss = self.midvatten.strat_symbology
            try:
                self.ss.create_symbology()
            except Exception:
                print(f"{mock_messagebar.mock_calls=}")
                raise

        _test(self)
        root = QgsProject.instance().layerTreeRoot()
        test = string_utils.anything_to_string_representation(
            utils_for_tests.recursive_children(root)
        )
        ref = '["", "", [["Midvatten strat symbology", "", [["Bars", "", [["Obsid label", True, []], ["Layer texts", True, []], ["W levels", "", [["W levels label", True, []], ["W levels", True, []]]], ["Bedrock", "", [["Bedrock label", True, []], ["Bedrock", True, []]]], ["Frame", True, []], ["Layers", "", [["Geology", True, []], ["Hydro", True, []]]], ["Shadow", True, []]]], ["Static bars", "", [["Obsid label", True, []], ["Layer texts", True, []], ["W levels", "", [["W levels label", True, []], ["W levels", True, []]]], ["Bedrock", "", [["Bedrock label", True, []], ["Bedrock", True, []]]], ["Frame", True, []], ["Layers", "", [["Geology", True, []], ["Hydro", True, []]]], ["Shadow", True, []]]], ["Rings", "", [["Bedrock", "", [["Bedrock", True, []]]], ["Layers", "", [["Geology", True, []], ["Hydro", True, []]]]]]]]]]'
        print("Test:")
        print(str(test))
        print(f"Test")
        print(test)
        print("Ref:")
        print(str(ref))
        print(f"{mock_messagebar.mock_calls=}")
        assert test == ref
        assert mock_messagebar.mock_calls == []


@pytest.mark.postgis
class TestStratSymbologyPostgis(
    StratSymbologyMixin, utils_for_tests.MidvattenTestPostgisDbSv
):
    pass


@pytest.mark.spatialite
class TestStratSymbologySpatialite(
    StratSymbologyMixin, utils_for_tests.MidvattenTestSpatialiteDbSv
):
    pass


class StratSymbologyErrorMixin:
    """One symbology style fails to apply: the bar gets a short translated
    warning, and the traceback goes only to the log (never a raw traceback
    dumped into the messagebar at .info level)."""

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_symbology_error_reports_short_warning_not_traceback_info(
        self, mock_messagebar
    ):
        db_utils.sql_alter_db(
            """INSERT INTO obs_points (obsid, h_gs, geometry) VALUES ('1', 5, ST_GeomFromText('POINT(1 2)', 3006))"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO stratigraphy (obsid, stratid, depthtop, depthbot, geology, geoshort, capacity, development) VALUES ('1', 1, 0, 1, 'sand', 'sand', '3', 'j')"""
        )

        real_apply_style = strat_symbology.apply_style

        def flaky_apply_style(layer, stylename):
            if stylename == "bars_obsid_label":
                raise RuntimeError("simulated style failure")
            return real_apply_style(layer, stylename)

        with mock.patch.object(
            strat_symbology, "apply_style", side_effect=flaky_apply_style
        ):
            strat_symbology.strat_symbology(
                self.iface,
                plot_rings=False,
                plot_bars=True,
                plot_static_bars=False,
                bars_xfactor=1,
                bars_yfactor=1,
                static_bars_xfactor=1,
                static_bars_yfactor=1,
                apply_obsid_filter=False,
            )

        print(f"{mock_messagebar.mock_calls=}")

        assert mock_messagebar.info.call_args_list == []

        warning_calls = mock_messagebar.warning.call_args_list
        assert len(warning_calls) == 1
        _, kwargs = warning_calls[0]
        assert "Obsid label" in kwargs["bar_msg"]
        assert "Traceback" not in kwargs["bar_msg"]
        assert "Traceback" in kwargs["log_msg"]
        assert "RuntimeError" in kwargs["log_msg"]


@pytest.mark.postgis
class TestStratSymbologyErrorPostgis(
    StratSymbologyErrorMixin, utils_for_tests.MidvattenTestPostgisDbSv
):
    pass


@pytest.mark.spatialite
class TestStratSymbologyErrorSpatialite(
    StratSymbologyErrorMixin, utils_for_tests.MidvattenTestSpatialiteDbSv
):
    pass
