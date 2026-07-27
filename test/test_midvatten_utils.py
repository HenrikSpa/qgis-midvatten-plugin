"""
/***************************************************************************
 This part of the Midvatten plugin tests the module that handles often used
 utilities.

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

import math
from unittest import mock
import numpy as np
from cycler import cycler
from unittest.mock import call
import pytest

from midvatten.test.mocks_for_tests import MockUsingReturnValue
from midvatten.test.utils_for_tests import create_test_string
from midvatten.tools import import_data_to_db
from midvatten.tools.utils import (
    common_utils,
    db_utils,
    message_utils,
    midvatten_utils,
    file_utils,
    exceptions,
)
from midvatten.tools.utils.db_utils import execution
from midvatten.tools.utils.common_utils import dict_to_tuple
from midvatten.tools.utils.matplotlib_replacements import perform_all_replacements
from midvatten.tools.utils.midvatten_utils import (
    compare_verson_lists,
    version_comparison_list,
)


@pytest.mark.active
class TestFilterNonexistingObsidsAndAsk:
    @mock.patch("qgis.utils.iface", autospec=True)
    @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion", autospec=True)
    def test_filter_nonexisting_obsids_and_ask_ok(self, mock_notfound, mock_iface):
        mock_notfound.return_value.answer = "ok"
        mock_notfound.return_value.value = 10
        mock_notfound.return_value.reuse_column = "obsid"
        mock_checkbox = mock.Mock()
        mock_checkbox.return_value.isChecked.return_value = True
        mock_notfound.return_value.ignore_checkbox = (
            mock_checkbox  # isChecked.return_value = True
        )

        file_data = [
            ["obsid", "ae"],
            ["1", "b"],
            ["2", "c"],
            ["3", "d"],
            ["10", "e"],
            ["1_g", "f"],
            ["1 a", "g"],
            ["21", "h"],
        ]
        existing_obsids = ["2", "3", "10", "1_g", "1 a"]
        filtered_file_data = common_utils.filter_nonexisting_values_and_ask(
            file_data, "obsid", existing_obsids
        )
        reference_list = [
            ["obsid", "ae"],
            ["2", "c"],
            ["3", "d"],
            ["10", "e"],
            ["1_g", "f"],
            ["1 a", "g"],
            ["10", "b"],
            ["10", "h"],
        ]
        assert filtered_file_data == reference_list

    @mock.patch("qgis.utils.iface", autospec=True)
    @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion", autospec=True)
    def test_filter_nonexisting_obsids_and_ask_cancel(self, mock_notfound, mock_iface):
        mock_notfound.return_value.answer = "cancel"
        mock_notfound.return_value.value = 10
        mock_notfound.return_value.reuse_column = "obsid"

        file_data = [
            ["obsid", "ae"],
            ["1", "b"],
            ["2", "c"],
            ["3", "d"],
            ["10", "e"],
            ["1_g", "f"],
            ["1 a", "g"],
            ["21", "h"],
        ]
        existing_obsids = ["2", "3", "10", "1_g", "1 a"]
        with pytest.raises(exceptions.UserInterruptError):
            common_utils.filter_nonexisting_values_and_ask(
                file_data,
                "obsid",
                existing_obsids,
            )

    @mock.patch("qgis.utils.iface", autospec=True)
    @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion", autospec=True)
    def test_filter_nonexisting_obsids_and_ask_skip(self, mock_notfound, mock_iface):
        mock_notfound.return_value.answer = "skip"
        mock_notfound.return_value.value = 10
        mock_notfound.return_value.reuse_column = "obsid"

        file_data = [
            ["obsid", "ae"],
            ["1", "b"],
            ["2", "c"],
            ["3", "d"],
            ["10", "e"],
            ["1_g", "f"],
            ["1 a", "g"],
            ["21", "h"],
        ]
        existing_obsids = ["2", "3", "10", "1_g", "1 a"]
        filtered_file_data = common_utils.filter_nonexisting_values_and_ask(
            file_data, "obsid", existing_obsids
        )
        reference_list = [
            ["obsid", "ae"],
            ["2", "c"],
            ["3", "d"],
            ["10", "e"],
            ["1_g", "f"],
            ["1 a", "g"],
        ]
        assert filtered_file_data == reference_list

    @mock.patch("qgis.utils.iface", autospec=True)
    @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion", autospec=True)
    def test_filter_nonexisting_obsids_and_ask_none_value_skip(
        self, mock_notfound, mock_iface
    ):
        mock_notfound.return_value.answer = "skip"
        mock_notfound.return_value.value = 10
        mock_notfound.return_value.reuse_column = "obsid"

        file_data = [
            ["obsid", "ae"],
            ["1", "b"],
            ["2", "c"],
            ["3", "d"],
            ["10", "e"],
            ["1_g", "f"],
            ["1 a", "g"],
            [None, "h"],
        ]
        existing_obsids = ["2", "3", "10", "1_g", "1 a"]
        filtered_file_data = common_utils.filter_nonexisting_values_and_ask(
            file_data, "obsid", existing_obsids
        )
        reference_list = [
            ["obsid", "ae"],
            ["2", "c"],
            ["3", "d"],
            ["10", "e"],
            ["1_g", "f"],
            ["1 a", "g"],
        ]
        assert filtered_file_data == reference_list

    @mock.patch("qgis.utils.iface", autospec=True)
    @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion", autospec=True)
    def test_filter_nonexisting_obsids_and_ask_header_not_found(
        self, mock_notfound, mock_iface
    ):
        """If a asked for header column is not found, it's added to the end of the rows."""
        mock_notfound.return_value.answer = "ok"
        mock_notfound.return_value.value = 10
        mock_notfound.return_value.reuse_column = "obsid"
        mock_checkbox = mock.Mock()
        mock_checkbox.return_value.isChecked.return_value = True
        mock_notfound.return_value.ignore_checkbox = (
            mock_checkbox  # isChecked.return_value = True
        )

        file_data = [
            ["obsid", "ae"],
            ["1", "b"],
            ["2", "c"],
            ["3", "d"],
            ["10", "e"],
            ["1_g", "f"],
            ["1 a", "g"],
            ["21", "h"],
        ]
        existing_obsids = ["2", "3", "10", "1_g", "1 a"]
        filtered_file_data = common_utils.filter_nonexisting_values_and_ask(
            file_data, "header_that_should_not_exist", existing_obsids
        )
        reference_list = [
            ["obsid", "ae", "header_that_should_not_exist"],
            ["1", "b", "10"],
            ["2", "c", "10"],
            ["3", "d", "10"],
            ["10", "e", "10"],
            ["1_g", "f", "10"],
            ["1 a", "g", "10"],
            ["21", "h", "10"],
        ]
        assert filtered_file_data == reference_list

    @mock.patch("qgis.utils.iface", autospec=True)
    def test_filter_nonexisting_obsids_and_ask_header_capitalize(self, mock_iface):
        file_data = [["obsid", "ae"], ["a", "b"], ["2", "c"]]
        existing_obsids = ["A", "2"]
        filtered_file_data = common_utils.filter_nonexisting_values_and_ask(
            file_data=file_data,
            header_value="obsid",
            existing_values=existing_obsids,
            try_capitalize=True,
            always_ask_user=False,
        )
        reference_list = [["obsid", "ae"], ["A", "b"], ["2", "c"]]
        assert filtered_file_data == reference_list

    @mock.patch("qgis.utils.iface", autospec=True)
    @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion", autospec=True)
    def test_filter_nonexisting_obsids_only_ask_once(self, mock_notfound, mock_iface):
        mock_notfound.return_value.answer = "ok"
        mock_notfound.return_value.value = 10
        mock_notfound.return_value.reuse_column = "obsid"
        mock_checkbox = mock.Mock()
        mock_checkbox.return_value.isChecked.return_value = True
        mock_notfound.return_value.ignore_checkbox = (
            mock_checkbox  # isChecked.return_value = True
        )

        file_data = [
            ["obsid", "ae"],
            ["1", "b"],
            ["2", "c"],
            ["3", "d"],
            ["10", "e"],
            ["1_g", "f"],
            ["1 a", "g"],
            ["21", "h"],
            ["1", "i"],
        ]
        existing_obsids = ["2", "3", "10", "1_g", "1 a"]
        filtered_file_data = common_utils.filter_nonexisting_values_and_ask(
            file_data, "obsid", existing_obsids
        )
        reference_list = [
            ["obsid", "ae"],
            ["2", "c"],
            ["3", "d"],
            ["10", "e"],
            ["1_g", "f"],
            ["1 a", "g"],
            ["10", "b"],
            ["10", "h"],
            ["10", "i"],
        ]
        assert filtered_file_data == reference_list
        # The mock should only be called twice. First for 1, then for 21, and then 1 again should use the already given answer.
        print(str(mock_notfound.mock_calls))
        assert len(mock_notfound.mock_calls) == 4

    @mock.patch("qgis.utils.iface", autospec=True)
    @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion", autospec=True)
    def test_filter_nonexisting_obsids_and_ask_skip_only_ask_once(
        self, mock_notfound, mock_iface
    ):
        mock_notfound.return_value.answer = "skip"
        mock_notfound.return_value.value = 10
        mock_notfound.return_value.reuse_column = "obsid"

        file_data = [
            ["obsid", "ae"],
            ["1", "b"],
            ["2", "c"],
            ["3", "d"],
            ["10", "e"],
            ["1_g", "f"],
            ["1 a", "g"],
            ["21", "h"],
            ["1", "i"],
        ]
        existing_obsids = ["2", "3", "10", "1_g", "1 a"]
        filtered_file_data = common_utils.filter_nonexisting_values_and_ask(
            file_data, "obsid", existing_obsids
        )
        reference_list = [
            ["obsid", "ae"],
            ["2", "c"],
            ["3", "d"],
            ["10", "e"],
            ["1_g", "f"],
            ["1 a", "g"],
        ]
        assert filtered_file_data == reference_list
        # The mock should only be called twice. First for 1, then for 21, and then 1 again should use the already given answer.
        assert len(mock_notfound.mock_calls) == 2


@pytest.mark.active
class TestTempinput:
    def test_tempinput(self):
        rows = "543\n21"
        with file_utils.tempinput(rows) as filename:
            with open(filename, encoding="utf-8") as f:
                res = f.readlines()
        reference_list = ["543\n", "21"]
        assert res == reference_list


@pytest.mark.active
class TestAskUser:
    qgis_PyQt_QtGui_QInputDialog_getText = MockUsingReturnValue(["-1 hours"])
    cancel = MockUsingReturnValue([""])

    @mock.patch(
        "qgis.PyQt.QtWidgets.QInputDialog.getText",
        qgis_PyQt_QtGui_QInputDialog_getText.get_v,
    )
    def test_askuser_dateshift(self):
        question = common_utils.Askuser("DateShift")
        assert question.result == ["-1", "hours"]

    @mock.patch("qgis.PyQt.QtWidgets.QInputDialog.getText", cancel.get_v)
    def test_askuser_dateshift_cancel(self):
        question = common_utils.Askuser("DateShift")
        assert question.result == "cancel"


@pytest.mark.active
class TestSelectFiles:
    @mock.patch(
        "midvatten.tools.utils.message_utils.MessagebarAndLog", mock.MagicMock()
    )
    @mock.patch("qgis.PyQt.QtWidgets.QFileDialog.getOpenFileName")
    def test_select_files_forwards_parent_to_qfiledialog(self, mock_getopen):
        parent = object()
        mock_getopen.return_value = ("/tmp/some.csv", "")
        result = midvatten_utils.select_files(
            only_one_file=True, extension="*", parent=parent
        )
        assert result == ["/tmp/some.csv"]
        assert mock_getopen.call_args.kwargs.get("parent") is parent

    @mock.patch(
        "midvatten.tools.utils.message_utils.MessagebarAndLog", mock.MagicMock()
    )
    @mock.patch("qgis.PyQt.QtWidgets.QFileDialog.getOpenFileName")
    def test_select_files_defaults_parent_to_none(self, mock_getopen):
        mock_getopen.return_value = ("/tmp/some.csv", "")
        midvatten_utils.select_files(only_one_file=True, extension="*")
        assert mock_getopen.call_args.kwargs.get("parent") is None


@pytest.mark.active
class TestSqlToParametersUnitsTuple:
    @mock.patch("midvatten.tools.utils.db_utils.helpers.sql_load_fr_db", autospec=True)
    def test_sql_to_parameters_units_tuple(self, mock_sqlload):
        mock_sqlload.return_value = (True, [("par1", "un1"), ("par2", "un2")])

        test_string = create_test_string(db_utils.sql_to_parameters_units_tuple("sql"))
        reference_string = """((par1, (un1)), (par2, (un2)))"""
        assert test_string == reference_string


@pytest.mark.active
class TestGetCurrentLocale:
    @mock.patch("midvatten.tools.utils.db_utils.DbConnectionManager")
    @mock.patch("midvatten.tools.utils.midvatten_utils.isinstance")
    @mock.patch("locale.getencoding")
    @mock.patch("locale.getlocale")
    @mock.patch("midvatten.tools.utils.midvatten_utils.get_locale_from_db")
    def test_getcurrentlocale(
        self,
        mock_get_locale,
        mock_default_locale,
        mock_getencoding,
        mock_isinstance,
        mock_dbconnection,
    ):
        mock_get_locale.return_value = "a_lang"
        mock_default_locale.return_value = [None, "an_enc"]
        mock_isinstance.return_value = False
        mock_getencoding.return_value = "an_enc"

        test_string = create_test_string(midvatten_utils.getcurrentlocale())
        reference_string = "[a_lang, an_enc]"
        # ['a_lang', 'UTF-8']
        print(midvatten_utils.getcurrentlocale())
        assert test_string == reference_string


@pytest.mark.active
class TestGetDelimiter:
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_get_delimiter_only_one_column(self, mock_messagebar):
        file = ["obsid", "rb1"]

        with file_utils.tempinput("\n".join(file), "utf-8") as filename:

            @mock.patch(
                "midvatten.tools.utils.file_utils.qgis.PyQt.QtWidgets.QInputDialog.getText"
            )
            @mock.patch("qgis.utils.iface", autospec=True)
            def _test(filename, mock_iface, mock_get_text):
                mock_get_text.return_value = (";", True)
                delimiter = file_utils.get_delimiter(filename, "utf-8")
                print(f"{mock_messagebar.mock_calls=}")
                assert delimiter == ";"

            _test(filename)

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_get_delimiter_delimiter_not_found(self, mock_messagebar):
        file = ["obsid;acol,acol2", "rb1;1,2"]

        with file_utils.tempinput("\n".join(file), "utf-8") as filename:

            @mock.patch(
                "midvatten.tools.utils.file_utils.qgis.PyQt.QtWidgets.QInputDialog.getText"
            )
            @mock.patch("qgis.utils.iface", autospec=True)
            def _test(filename, mock_iface, mock_get_text):
                mock_get_text.return_value = (",", True)
                delimiter = file_utils.get_delimiter(filename, "utf-8")
                print(f"{mock_messagebar.mock_calls=}")
                assert delimiter == ","

            _test(filename)

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_get_delimiter_semicolon(self, mock_messagebar):
        file = ["obsid;acol;acol2", "rb1;1;2"]

        with file_utils.tempinput("\n".join(file), "utf-8") as filename:

            @mock.patch(
                "midvatten.tools.utils.file_utils.qgis.PyQt.QtWidgets.QInputDialog.getText"
            )
            @mock.patch("qgis.utils.iface", autospec=True)
            def _test(filename, mock_iface, mock_get_text):
                mock_get_text.return_value = (";", True)
                delimiter = file_utils.get_delimiter(filename, "utf-8")
                print(f"{mock_messagebar.mock_calls=}")
                assert delimiter == ";"

            _test(filename)

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_get_delimiter_comma(self, mock_messagebar):
        file = ["obsid,acol,acol2", "rb1,1,2"]

        with file_utils.tempinput("\n".join(file), "utf-8") as filename:

            @mock.patch(
                "midvatten.tools.utils.file_utils.qgis.PyQt.QtWidgets.QInputDialog.getText"
            )
            @mock.patch("qgis.utils.iface", autospec=True)
            def _test(filename, mock_iface, mock_get_text):
                mock_get_text.return_value = (",", True)
                delimiter = file_utils.get_delimiter(filename, "utf-8")
                print(f"{mock_messagebar.mock_calls=}")
                assert delimiter == ","

            _test(filename)

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_get_delimiter_quoted_comma_in_semicolon_data(self, mock_messagebar):
        file = ['"hello, world";42;foo', '"test, data";99;bar']

        with file_utils.tempinput("\n".join(file), "utf-8") as filename:

            @mock.patch(
                "midvatten.tools.utils.file_utils.qgis.PyQt.QtWidgets.QInputDialog.getText"
            )
            @mock.patch("qgis.utils.iface", autospec=True)
            def _test(filename, mock_iface, mock_get_text):
                delimiter = file_utils.get_delimiter(filename, "utf-8")
                print(f"{mock_messagebar.mock_calls=}")
                assert delimiter == ";"

            _test(filename)

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_get_delimiter_quoted_semicolon_in_comma_data(self, mock_messagebar):
        file = ['"hello; world",42,foo', '"test; data",99,bar']

        with file_utils.tempinput("\n".join(file), "utf-8") as filename:

            @mock.patch(
                "midvatten.tools.utils.file_utils.qgis.PyQt.QtWidgets.QInputDialog.getText"
            )
            @mock.patch("qgis.utils.iface", autospec=True)
            def _test(filename, mock_iface, mock_get_text):
                delimiter = file_utils.get_delimiter(filename, "utf-8")
                print(f"{mock_messagebar.mock_calls=}")
                assert delimiter == ","

            _test(filename)


@pytest.mark.active
class TestGeneralExceptionHandler:
    def test_no_args_no_kwargs(self):
        @common_utils.general_exception_handler
        def no_args_no_kwargs():
            return True

        assert no_args_no_kwargs()

    def test_only_args(self):
        @common_utils.general_exception_handler
        def only_args(*args):
            return args

        assert only_args(True)[0]
        assert only_args(True, False)[0]
        assert not only_args(True, False)[1]

    def test_only_kwargs(self):
        @common_utils.general_exception_handler
        def only_kwargs(**kwargs):
            return kwargs

        assert only_kwargs(true=True)["true"]
        assert not only_kwargs(false=False)["false"]
        assert only_kwargs(true=True, false=False)["true"]
        assert only_kwargs(true=True, false=False)["true"]
        assert len(only_kwargs(true=True)) == 1
        assert len(only_kwargs(true=True, false=False)) == 2

    def test_one_arg(self):
        @common_utils.general_exception_handler
        def one_arg(t):
            return t

        assert one_arg(True)
        assert isinstance(one_arg("t"), str)
        assert one_arg("a") == "a"

    def test_args_kwargs(self):
        @common_utils.general_exception_handler
        def args_kwargs(*args, **kwargs):
            return args, kwargs

        assert not args_kwargs()[0]
        assert not args_kwargs()[1]
        assert len(args_kwargs()) == 2

    def test_one_arg_args_kwargs(self):
        @common_utils.general_exception_handler
        def one_arg_args_kwargs(t, *args, **kwargs):
            return t, args, kwargs

        assert one_arg_args_kwargs("a")[0] == "a"
        assert len(one_arg_args_kwargs("a")[1]) == 0
        assert len(one_arg_args_kwargs("a")[2]) == 0


@pytest.mark.active
class TestContinuousColorCycle:
    def setup_method(self):
        perform_all_replacements()

    def test_continous_color_cycle_combo(self):
        color_cycler = cycler("color", ["r", "g", "b"])
        marker_cycler = cycler("marker", ["o", "+", "s"])
        line_cycler = cycler("linestyle", ["-", "--", "-."])

        color_cycle_len = len(color_cycler)
        color_cycle = color_cycler()

        used_style_color_combo = set()
        color_line_cycle = common_utils.ContinuousColorCycle(
            color_cycle, color_cycle_len, line_cycler, used_style_color_combo
        )
        color_marker_cycle = common_utils.ContinuousColorCycle(
            color_cycle, color_cycle_len, marker_cycler, used_style_color_combo
        )

        res = []
        res.append(dict_to_tuple(next(color_line_cycle)))
        res.append(dict_to_tuple(next(color_line_cycle)))
        res.append(dict_to_tuple(next(color_marker_cycle)))
        res.append(dict_to_tuple(next(color_line_cycle)))
        res = tuple(res)
        print(str(res))
        assert res == (
            (("color", "r"), ("linestyle", "-")),
            (("color", "g"), ("linestyle", "-")),
            (("color", "b"), ("marker", "o")),
            (("color", "b"), ("linestyle", "-")),
        )

    def test_continous_color_cycle_line_and_markers(self):
        # TODO: Test that i can also cycle line and markers. I mean the product line_cycler * marker_cycler
        color_cycler = cycler("color", ["r", "g", "b"])
        marker_cycler = cycler("marker", ["o", "+", "s"])
        line_cycler = cycler("linestyle", ["-", "--", "-."])

        style_cycler = marker_cycler * line_cycler

        color_cycle_len = len(color_cycler)
        color_cycle = color_cycler()

        used_style_color_combo = set()
        color_style_cycler = common_utils.ContinuousColorCycle(
            color_cycle, color_cycle_len, style_cycler, used_style_color_combo
        )
        color_line_cycle = common_utils.ContinuousColorCycle(
            color_cycle, color_cycle_len, line_cycler, used_style_color_combo
        )
        color_marker_cycle = common_utils.ContinuousColorCycle(
            color_cycle, color_cycle_len, marker_cycler, used_style_color_combo
        )

        res = []
        res.append(dict_to_tuple(next(color_style_cycler)))
        res.append(dict_to_tuple(next(color_style_cycler)))
        res.append(dict_to_tuple(next(color_marker_cycle)))
        res.append(dict_to_tuple(next(color_line_cycle)))
        res.append(dict_to_tuple(next(color_style_cycler)))
        res.append(dict_to_tuple(next(color_style_cycler)))
        res = tuple(res)
        print(str(res))
        assert res == (
            (("color", "r"), ("linestyle", "-"), ("marker", "o")),
            (("color", "g"), ("linestyle", "-"), ("marker", "o")),
            (("color", "b"), ("marker", "o")),
            (("color", "r"), ("linestyle", "-")),
            (("color", "b"), ("linestyle", "-"), ("marker", "o")),
            (("color", "r"), ("linestyle", "--"), ("marker", "o")),
        )

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    @mock.patch("midvatten.tools.utils.common_utils.np.random.rand")
    def test_continous_color_cycle_ran_out(self, mock_np_random_rand, mock_messagebar):
        """Test that i can also cycle line and markers. I mean the product line_cycler * marker_cycler"""
        color_cycler = cycler("color", ["r", "g"])
        line_cycler = cycler("linestyle", ["-", "--"])

        mock_np_random_rand.side_effect = np.array(["123", "456", "789"])

        color_cycle_len = len(color_cycler)
        color_cycle = color_cycler()

        used_style_color_combo = set()

        color_line_cycle = common_utils.ContinuousColorCycle(
            color_cycle, color_cycle_len, line_cycler, used_style_color_combo
        )

        res = []
        res.append(dict_to_tuple(next(color_line_cycle)))
        res.append(dict_to_tuple(next(color_line_cycle)))
        res.append(dict_to_tuple(next(color_line_cycle)))
        res.append(dict_to_tuple(next(color_line_cycle)))
        res.append(dict_to_tuple(next(color_line_cycle)))
        res.append(dict_to_tuple(next(color_line_cycle)))
        res.append(dict_to_tuple(next(color_line_cycle)))

        res = tuple(res)
        print(str(res))
        print(f"{mock_messagebar.mock_calls=}")
        assert res == (
            (("color", "r"), ("linestyle", "-")),
            (("color", "g"), ("linestyle", "-")),
            (("color", "r"), ("linestyle", "--")),
            (("color", "g"), ("linestyle", "--")),
            (("color", "123"), ("linestyle", "-")),
            (("color", "456"), ("linestyle", "--")),
            (("color", "789"), ("linestyle", "-")),
        )
        assert mock_messagebar.mock_calls == [
            call.info(
                bar_msg="Style cycler ran out of unique combinations. Using random color!"
            ),
            call.info(
                bar_msg="Style cycler ran out of unique combinations. Using random color!"
            ),
            call.info(
                bar_msg="Style cycler ran out of unique combinations. Using random color!"
            ),
        ]


@pytest.mark.active
class TestVersionComparisonLists:
    def test_compare_verson_lists_same_not_old(self):
        is_old = compare_verson_lists(
            version_comparison_list("3.16"), version_comparison_list("3.16")
        )
        assert not is_old

    def test_compare_verson_lists_one_above_not_old(self):
        is_old = compare_verson_lists(
            version_comparison_list("3.17"), version_comparison_list("3.16")
        )
        assert not is_old

    def test_compare_verson_lists_one_more_not_old(self):
        is_old = compare_verson_lists(
            version_comparison_list("3.16.1"), version_comparison_list("3.16")
        )
        assert not is_old

    def test_compare_verson_lists_one_more_beta_not_old(self):
        is_old = compare_verson_lists(
            version_comparison_list("3.16.1b2"), version_comparison_list("3.16")
        )
        assert not is_old

    def test_compare_verson_same_length_old(self):
        is_old = compare_verson_lists(
            version_comparison_list("3.14"), version_comparison_list("3.16")
        )
        assert is_old

    def test_compare_verson_lists_one_more_old(self):
        is_old = compare_verson_lists(
            version_comparison_list("3.14.1"), version_comparison_list("3.16")
        )
        assert is_old

    def test_compare_verson_lists_one_more_beta_old(self):
        is_old = compare_verson_lists(
            version_comparison_list("3.14.1b2"), version_comparison_list("3.16")
        )
        assert is_old


@pytest.mark.active
class TestCalcMeanDiff:
    def test_basic_mean(self):
        assert common_utils.calc_mean_diff([(5, 2), (8, 1)]) == 5.0

    def test_nan_val_pairs_are_excluded(self):
        # A NaN in either position must not poison the mean.
        result = common_utils.calc_mean_diff(
            [(5, 2), (8, 1), (float("nan"), 3), (4, float("nan"))]
        )
        assert result == 5.0

    def test_all_nan_returns_nan(self):
        result = common_utils.calc_mean_diff([(float("nan"), float("nan"))])
        assert math.isnan(result)


@pytest.mark.active
class TestDecoratorMetadata:
    def test_general_exception_handler_preserves_metadata(self):
        @common_utils.general_exception_handler
        def my_decorated_func():
            """My docstring."""

        assert my_decorated_func.__name__ == "my_decorated_func"
        assert my_decorated_func.__doc__ == "My docstring."

    def test_if_connection_ok_preserves_metadata(self):
        @execution.if_connection_ok
        def my_db_func():
            """Db docstring."""

        assert my_db_func.__name__ == "my_db_func"
        assert my_db_func.__doc__ == "Db docstring."

    def test_import_exception_handler_preserves_metadata(self):
        @import_data_to_db.import_exception_handler
        def my_import_func():
            """Import docstring."""

        assert my_import_func.__name__ == "my_import_func"
        assert my_import_func.__doc__ == "Import docstring."

    def test_waiting_cursor_preserves_metadata(self):
        @common_utils.waiting_cursor
        def my_cursor_func():
            """Cursor docstring."""

        assert my_cursor_func.__name__ == "my_cursor_func"
        assert my_cursor_func.__doc__ == "Cursor docstring."

    def test_waiting_cursor_restores_after_exception(self):
        @common_utils.waiting_cursor
        def failing_operation():
            raise RuntimeError("operation failed")

        with (
            mock.patch.object(common_utils, "start_waiting_cursor") as start_cursor,
            mock.patch.object(common_utils, "stop_waiting_cursor") as stop_cursor,
            pytest.raises(RuntimeError, match="operation failed"),
        ):
            failing_operation()

        start_cursor.assert_called_once_with()
        stop_cursor.assert_called_once_with()

    @pytest.mark.parametrize("cursor_outermost", [False, True])
    def test_cursor_and_exception_handlers_restore_once(self, cursor_outermost):
        def failing_operation():
            raise RuntimeError("operation failed")

        if cursor_outermost:
            decorated = common_utils.waiting_cursor(
                common_utils.general_exception_handler(failing_operation)
            )
        else:
            decorated = common_utils.general_exception_handler(
                common_utils.waiting_cursor(failing_operation)
            )

        with (
            mock.patch.object(common_utils, "start_waiting_cursor") as start_cursor,
            mock.patch.object(common_utils, "stop_waiting_cursor") as stop_cursor,
            pytest.raises(RuntimeError, match="operation failed"),
        ):
            decorated()

        start_cursor.assert_called_once_with()
        stop_cursor.assert_called_once_with()


@pytest.mark.active
class TestMessageDispatcher:
    def test_queued_log_payload_is_delivered_by_keyword(self):
        delivered = {}

        def fake_deliver(**kwargs):
            delivered.update(kwargs)

        with mock.patch.object(
            message_utils.MessagebarAndLog,
            "_log_on_main_thread",
            side_effect=fake_deliver,
        ):
            message_utils._message_dispatcher._deliver(
                {
                    "bar_msg": "bar",
                    "log_msg": "log",
                    "duration": 5,
                    "messagebar_level": 1,
                    "log_level": 2,
                    "button": False,
                }
            )

        assert delivered == {
            "bar_msg": "bar",
            "log_msg": "log",
            "duration": 5,
            "messagebar_level": 1,
            "log_level": 2,
            "button": False,
        }
