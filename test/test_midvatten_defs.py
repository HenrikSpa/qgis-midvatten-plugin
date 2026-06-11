"""
/***************************************************************************
 This part of the Midvatten plugin tests the module that handles exports to
  fieldlogger format.

                             -------------------
        begin                : 2016-03-08
        copyright            : (C) 2016 by joskal (HenrikSpa)
        email                : groundwatergis [at] gmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import pytest
from unittest import mock

from midvatten.tools.utils import db_utils, string_utils
from midvatten.test import utils_for_tests
from midvatten.definitions import midvatten_defs


class DefsFunctionsMixin:
    def test_tables_columns(self):
        res = db_utils.db_tables_columns_info()
        assert res
        assert isinstance(res, dict)
        for k, v in res.items():
            assert isinstance(k, str)
            assert isinstance(v, (tuple, list))
            for x in v:
                assert isinstance(x, (tuple, list))
                assert x


@pytest.mark.postgis
class TestDefsFunctionsPostgis(
    DefsFunctionsMixin, utils_for_tests.MidvattenTestPostgisDbSv
):
    pass


@pytest.mark.spatialite
class TestDefsFunctionsSpatialite(
    DefsFunctionsMixin, utils_for_tests.MidvattenTestSpatialiteDbSv
):
    pass


class GeocolorsymbolsMixin:
    def test_only_moran(self):
        db_utils.sql_alter_db("DELETE FROM zz_strat")
        db_utils.sql_alter_db("DELETE FROM zz_stratigraphy_plots")
        db_utils.sql_alter_db(
            """INSERT INTO zz_strat(geoshort, strata) VALUES('morän', 'morän')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO zz_strat(geoshort, strata) VALUES('moran', 'morän')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO zz_stratigraphy_plots(strata, color_mplot, hatch_mplot, color_qt, brush_qt) VALUES('morän', 'theMPcolor', '/', 'theQTcolor', 'thePattern')"""
        )

        test_string = string_utils.anything_to_string_representation(
            midvatten_defs.geocolorsymbols()
        )
        reference_string = """{"moran": ("thePattern", "theQTcolor", ), "morän": ("thePattern", "theQTcolor", )}"""
        print(test_string)
        assert test_string == reference_string

    def test_missing_colors_patterns(self):
        db_utils.sql_alter_db("DELETE FROM zz_strat")
        db_utils.sql_alter_db("DELETE FROM zz_stratigraphy_plots")
        db_utils.sql_alter_db(
            """INSERT INTO zz_strat(geoshort, strata) VALUES('nostrata', 'noshort')"""
        )
        db_utils.sql_alter_db(
            """INSERT INTO zz_stratigraphy_plots(strata, color_mplot, hatch_mplot, color_qt, brush_qt) VALUES('moran', 'theMPcolor', '/', 'theQTcolor', 'thePattern')"""
        )

        test_string = string_utils.anything_to_string_representation(
            midvatten_defs.geocolorsymbols()
        )
        reference_string = """{"nostrata": ("NoBrush", "white", )}"""
        assert test_string == reference_string


@pytest.mark.postgis
class TestGeocolorsymbolsPostgis(
    GeocolorsymbolsMixin, utils_for_tests.MidvattenTestPostgisDbSv
):
    pass


@pytest.mark.spatialite
class TestGeocolorsymbolsSpatialite(
    GeocolorsymbolsMixin, utils_for_tests.MidvattenTestSpatialiteDbSv
):
    pass


class PlotFallbackDictsMixin:
    """Fallback dicts for Swedish/English locale fire when the DB reads fail."""

    # ── plot_types_dict ──────────────────────────────────────────────────────

    @mock.patch("midvatten.definitions.midvatten_defs.MessagebarAndLog")
    @mock.patch(
        "midvatten.definitions.midvatten_defs.is_locale_swedish", return_value=True
    )
    @mock.patch(
        "midvatten.definitions.midvatten_defs.get_sql_result_as_dict",
        return_value=(False, {}),
    )
    def test_plot_types_dict_fallback_swedish(
        self, mock_db, mock_locale, mock_messagebar
    ):
        print(mock_messagebar.mock_calls)
        result = midvatten_defs.plot_types_dict(international="no")
        print(mock_messagebar.mock_calls)
        assert "Berg" in result
        assert "Okänt" in result
        assert "Rock" not in result
        assert "Unknown" not in result

    @mock.patch("midvatten.definitions.midvatten_defs.MessagebarAndLog")
    @mock.patch(
        "midvatten.definitions.midvatten_defs.is_locale_swedish", return_value=False
    )
    @mock.patch(
        "midvatten.definitions.midvatten_defs.get_sql_result_as_dict",
        return_value=(False, {}),
    )
    def test_plot_types_dict_fallback_english(
        self, mock_db, mock_locale, mock_messagebar
    ):
        print(mock_messagebar.mock_calls)
        result = midvatten_defs.plot_types_dict(international="no")
        print(mock_messagebar.mock_calls)
        assert "Rock" in result
        assert "Unknown" in result
        assert "Berg" not in result
        assert "Okänt" not in result

    # ── plot_colors_dict ─────────────────────────────────────────────────────

    @mock.patch("midvatten.definitions.midvatten_defs.MessagebarAndLog")
    @mock.patch(
        "midvatten.definitions.midvatten_defs.is_locale_swedish", return_value=True
    )
    @mock.patch(
        "midvatten.definitions.midvatten_defs.create_dict_from_db_2_cols",
        return_value=(False, {}),
    )
    def test_plot_colors_dict_fallback_swedish(
        self, mock_db, mock_locale, mock_messagebar
    ):
        print(mock_messagebar.mock_calls)
        result = midvatten_defs.plot_colors_dict()
        print(mock_messagebar.mock_calls)
        assert "berg" in result  # keys are lowercased by the function
        assert "okänt" in result
        assert "rock" not in result

    @mock.patch("midvatten.definitions.midvatten_defs.MessagebarAndLog")
    @mock.patch(
        "midvatten.definitions.midvatten_defs.is_locale_swedish", return_value=False
    )
    @mock.patch(
        "midvatten.definitions.midvatten_defs.create_dict_from_db_2_cols",
        return_value=(False, {}),
    )
    def test_plot_colors_dict_fallback_english(
        self, mock_db, mock_locale, mock_messagebar
    ):
        print(mock_messagebar.mock_calls)
        result = midvatten_defs.plot_colors_dict()
        print(mock_messagebar.mock_calls)
        assert "rock" in result
        assert "unknown" in result
        assert "berg" not in result

    # ── plot_hatches_dict ────────────────────────────────────────────────────

    @mock.patch("midvatten.definitions.midvatten_defs.MessagebarAndLog")
    @mock.patch(
        "midvatten.definitions.midvatten_defs.is_locale_swedish", return_value=True
    )
    @mock.patch(
        "midvatten.definitions.midvatten_defs.create_dict_from_db_2_cols",
        return_value=(False, {}),
    )
    def test_plot_hatches_dict_fallback_swedish(
        self, mock_db, mock_locale, mock_messagebar
    ):
        print(mock_messagebar.mock_calls)
        result = midvatten_defs.plot_hatch_dict()
        print(mock_messagebar.mock_calls)
        assert "berg" in result
        assert "okänt" in result
        assert "rock" not in result

    @mock.patch("midvatten.definitions.midvatten_defs.MessagebarAndLog")
    @mock.patch(
        "midvatten.definitions.midvatten_defs.is_locale_swedish", return_value=False
    )
    @mock.patch(
        "midvatten.definitions.midvatten_defs.create_dict_from_db_2_cols",
        return_value=(False, {}),
    )
    def test_plot_hatches_dict_fallback_english(
        self, mock_db, mock_locale, mock_messagebar
    ):
        print(mock_messagebar.mock_calls)
        result = midvatten_defs.plot_hatch_dict()
        print(mock_messagebar.mock_calls)
        assert "rock" in result
        assert "unknown" in result
        assert "berg" not in result


@pytest.mark.spatialite
class TestPlotFallbackDictsSpatialite(
    PlotFallbackDictsMixin, utils_for_tests.MidvattenTestSpatialiteDbSv
):
    pass
