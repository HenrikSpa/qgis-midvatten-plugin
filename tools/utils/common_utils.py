"""
/***************************************************************************
 This part of the Midvatten plugin handles dates.
                             -------------------
        begin                : 2016-03-09
        copyright            : (C) 2016 by HenrikSpa
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

import ast
import copy
import json
import datetime
import difflib
import math
import time
import traceback
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Optional

import matplotlib as mpl
import numpy as np
from matplotlib.dates import num2date
import qgis.utils
from qgis.PyQt import QtWidgets
from qgis.core import Qgis, QgsLogger

from midvatten.tools.utils.dialog_utils import (
    Askuser,
    HtmlDialog,
    NotFoundQuestion,
    ask_for_export_crs,
    ask_user_about_stopping,
)
from midvatten.tools.utils.exceptions import UsageError, UserInterruptError
from midvatten.tools.utils.file_utils import (
    ask_for_delimiter,
    get_delimiter,
    get_delimiter_from_file_rows,
    get_full_filename,
    tempinput,
    write_printlist_to_file,
)
from midvatten.tools.utils.layer_utils import (
    find_layer,
    getQgisVectorLayers,
    get_active_layer,
    get_selected_features_as_tuple,
    getselectedobjectnames,
    selection_check,
    strat_selection_check,
    verify_layer_selection,
)
from midvatten.tools.utils.message_utils import (
    MessagebarAndLog,
    pop_up_info,
    show_message_log,
    sql_failed_msg,
)
from midvatten.tools.utils.string_utils import (
    anything_to_string_representation,
    isdate,
    isfloat,
    isinteger,
    lists_to_string,
    lstrip,
    returnunicode,
    rstrip,
    tr,
    unicode_2_utf8,
)

LEGEND_NCOL_KEY = "ncol" if mpl.__version__ < "3.6.0" else "ncols"


def write_qgs_log_to_file(message: str, tag: str, level: Qgis.MessageLevel):
    logfile = QgsLogger.logFile()
    if logfile is not None:
        QgsLogger.logMessageToFile(
            "{}: {}({}): {} ".format(
                "%s" % (returnunicode(get_date_time())),
                returnunicode(tag),
                returnunicode(level),
                "%s" % (returnunicode(message)),
            )
        )


def verify_this_layer_selected_and_not_in_edit_mode(errorsignal, layername):
    layer = get_active_layer()
    if not layer:  # check there is actually a layer selected
        errorsignal += 1
        MessagebarAndLog.critical(
            bar_msg=returnunicode(
                tr(
                    "verify_this_layer_selected_and_not_in_edit_mode",
                    "Error, you have to select/activate %s layer!",
                )
            )
            % layername
        )
    elif layer.isEditable():
        errorsignal += 1
        MessagebarAndLog.critical(
            bar_msg=returnunicode(
                tr(
                    "verify_this_layer_selected_and_not_in_edit_mode",
                    "Error, the selected layer is currently in editing mode. Please exit this mode before updating coordinates.",
                )
            )
        )
    elif not (layer.name() == layername):
        errorsignal += 1
        MessagebarAndLog.critical(
            bar_msg=returnunicode(
                tr(
                    "verify_this_layer_selected_and_not_in_edit_mode",
                    "Error, you have to select/activate %s layer!",
                )
            )
            % layername
        )
    return errorsignal


def null_2_empty_string(input_string):
    return input_string.replace("NULL", "").replace("null", "")


def return_lower_ascii_string(textstring):
    def onlyascii(char):
        if ord(char) < 48 or ord(char) > 127:
            return ""
        else:
            return char

    filtered_string = "".join(list(filter(onlyascii, textstring)))
    filtered_string = filtered_string.lower()
    return filtered_string


def ts_gen(ts):
    """A generator that supplies one tuple from a list of tuples at a time

    ts: a list of tuples where the tuple contains two positions.

    Usage:
    a = ts_gen(ts)
    b = next(a)

    >>> for x in ts_gen(((1, 2), ('a', 'b'))): print(x)
    (1, 2)
    ('a', 'b')
    """
    for idx in range(len(ts)):
        yield (ts[idx][0], ts[idx][1])


def calc_mean_diff(coupled_vals):
    """Calculates the mean difference for all value couples in a list of tuples

        Nan-values are excluded from the mean.

    >>> calc_mean_diff(([5, 2] , [8, 1]))
    5.0
    """
    return np.mean(
        [
            float(m) - float(val)
            for m, val in coupled_vals
            if not math.isnan(m) or math.isnan(val)
        ]
    )


def find_similar(word, wordlist, hits=5):
    r"""

    :param word: the word to find similar words for
    :param wordlist: the word list to find similar in
    :param hits: the number of hits in first match (more hits will be added than this)
    :return:  a set with the matches

    some code from http://stackoverflow.com/questions/480214/how-do-you-remove-duplicates-from-a-list-in-whilst-preserving-order

    >>> find_similar('rb1203', ['Rb1203', 'rb 1203', 'gert', 'rb', 'rb1203', 'b1203', 'rb120', 'rb11', 'rb123', 'rb1203_bgfgf'], 5)
    ['rb1203', 'rb 1203', 'rb123', 'rb120', 'b1203', 'Rb1203', 'rb1203_bgfgf']
    >>> find_similar('1', ['2', '3'], 5)
    ['']
    >>> find_similar(None, ['2', '3'], 5)
    ['']
    >>> find_similar(None, None, 5)
    ['']
    >>> find_similar('1', [], 5)
    ['']
    >>> find_similar('1', False, 5)
    ['']
    >>> find_similar(False, ['2', '3'], 5)
    ['']

    """
    if None in [word, wordlist] or not wordlist or not word:
        return [""]

    matches = difflib.get_close_matches(word, wordlist, hits)

    matches.extend(
        [
            x
            for x in wordlist
            if any(
                (
                    x.startswith(word.lower()),
                    x.startswith(word.upper()),
                    x.startswith(word.capitalize()),
                )
            )
        ]
    )
    nr_of_hits = len(matches)
    if nr_of_hits == 0:
        return [""]

    # Remove duplicates
    seen = set()
    seen_add = seen.add
    matches = [x for x in matches if x and not (x in seen or seen_add(x))]

    return matches


def filter_nonexisting_values_and_ask(
    file_data: Optional[list[list[str]]] = None,
    header_value: Optional[str] = None,
    existing_values: Optional[list[str]] = None,
    try_capitalize: bool = False,
    always_ask_user: bool = False,
) -> list[list[str]]:
    """

    The class NotFoundQuestion is used with 4 buttons; 'Ignore', 'Cancel', 'Ok', 'Skip'.
    Ignore = use the chosen value and move to the next obsid.
    Cancel = raises UserInterruptError
    Ok = Tries the currently submitted obsid against the existing once. If it doesn't exist, it asks again.
    Skip = None is used as obsid and the row is removed from the file_data

    :param file_data:
    :param header_value:
    :param existing_values:
    :param try_capitalize: If True, the header_value will be matched against existing_values both original value and as capitalized value. This parameter only has an effect if always_ask_user is False.
    :param always_ask_user: The used will be requested for every distinct header_value
    :return:

    """
    if file_data is None or header_value is None:
        return []
    if existing_values is None:
        existing_values = []
    header_value = returnunicode(header_value)
    filtered_data = []
    data_to_ask_for = []
    add_column = False
    try:
        index = file_data[0].index(header_value)
    except ValueError:
        # The header and all answers will be added as a new column.
        file_data[0].append(header_value)
        index = -1
        add_column = True
        filtered_data.append(file_data[0])
        pass
    else:
        filtered_data.append(file_data[0])

    for row in file_data[1:]:
        if add_column:
            row.append(None)
        if always_ask_user:
            data_to_ask_for.append(row)
        else:
            values = [row[index]]
            if try_capitalize:
                try:
                    values.append(row[index].capitalize())
                except AttributeError:
                    pass

            for _value in values:
                if _value in existing_values:
                    row[index] = _value
                    filtered_data.append(row)
                    break
            else:
                data_to_ask_for.append(row)

    headers_colnr = dict([(header, colnr) for colnr, header in enumerate(file_data[0])])

    already_asked_values = {}  # {'obsid': {'asked_for': 'answer'}, 'report': {'asked_for_report': 'answer'}}
    reuse_column = ""
    for rownr, row in enumerate(data_to_ask_for):
        current_value = row[index]
        found = False
        # First check if the current value already has been asked for and if so
        # use the same answer again.
        for asked_header, asked_answers in already_asked_values.items():
            colnr = headers_colnr[asked_header]
            try:
                row[index] = asked_answers[row[colnr]]
            except KeyError:
                current_value = row[index]
            else:
                if row[index] is not None:
                    filtered_data.append(row)
                    found = True
                    break
                else:
                    found = True
                    break
        if found:
            continue

        submitted_value = None
        similar_values = find_similar(current_value, existing_values, hits=5)
        similar_values.extend(
            [x for x in sorted(existing_values) if x not in similar_values]
        )
        while submitted_value not in existing_values:
            # Put the found similar values on top, but include all values in the database as well
            msg = returnunicode(
                tr(
                    "filter_nonexisting_values_and_ask",
                    "(Message %s of %s)\n\nGive the %s for:\n%s",
                )
            ) % (
                str(rownr + 1),
                str(len(data_to_ask_for)),
                header_value,
                "\n".join(
                    [
                        ": ".join(
                            (file_data[0][_colnr], word if word is not None else "")
                        )
                        for _colnr, word in enumerate(row)
                    ]
                ),
            )
            question = NotFoundQuestion(
                dialogtitle=tr(
                    "filter_nonexisting_values_and_ask", "User input needed"
                ),
                msg=msg,
                existing_list=similar_values,
                default_value=similar_values[0],
                button_names=["Cancel", "Ok", "Skip"],
                reuse_header_list=sorted(headers_colnr.keys()),
                reuse_column=reuse_column,
                ignore_checkbox=True,
            )
            answer = question.answer

            submitted_value = returnunicode(question.value)
            reuse_column = returnunicode(question.reuse_column)

            if answer == "cancel":
                raise UserInterruptError()

            if answer == "skip":
                submitted_value = None

            if reuse_column:
                already_asked_values.setdefault(reuse_column, {})[
                    row[headers_colnr[reuse_column]]
                ] = submitted_value

            if submitted_value is not None:
                row[index] = submitted_value
                filtered_data.append(row)

            if answer == "skip" or question.ignore_checkbox.isChecked():
                break

    return filtered_data


def scale_nparray(x, a=1, b=0):
    """
    Scales a 1d numpy array using linear equation
    :param x: A numpy 1darray, x in y=kx+m
    :param a: k in y=ax+b
    :param b: m in y=ax+b
    :return: A numpy 1darray, y in y=ax+b

    >>> scale_nparray(np.array([2,3,1,0]), b=10)
    array([12, 13, 11, 10])
    >>> scale_nparray(np.array([2,3,1,0]), b=10, a=4)
    array([18, 22, 14, 10])
    >>> scale_nparray(np.array([2,3,1,0]), 2)
    array([4, 6, 2, 0])
    >>> scale_nparray(np.array([2,3,1,0]), 2, -5)
    array([-1,  1, -3, -5])
    >>> scale_nparray(np.array([2,3,1,0]), -2, -5)
    array([ -9, -11,  -7,  -5])
    """
    return a * copy.deepcopy(x) + b


def remove_mean_from_nparray(x):
    """ """
    x = copy.deepcopy(x)
    mean = x[np.logical_not(np.isnan(x))]
    mean = mean.mean(axis=0)
    x = x - mean

    # for colnr, col in enumerate(x):
    #     x[colnr] = x[colnr] - np.mean(x[colnr])
    return x


def waiting_cursor(func: Callable) -> Callable:
    def func_wrapper(*args, **kwargs):
        start_waiting_cursor()
        result = func(*args, **kwargs)
        stop_waiting_cursor()
        return result

    return func_wrapper


def start_waiting_cursor():
    qgis.PyQt.QtWidgets.QApplication.setOverrideCursor(qgis.PyQt.QtCore.Qt.WaitCursor)


def stop_waiting_cursor():
    qgis.PyQt.QtWidgets.QApplication.restoreOverrideCursor()


class Cancel:
    """Object for transmitting cancel messages instead of using string 'cancel'.
    use isinstance(variable, Cancel) to check for it.

    Usage:
    return Cancel()

    Return the same Cancel object.
    if isinstance(answer, Cancel):
        return answer

    Potential improvements could be to include messages inside the objects.
    """

    def __init__(self):
        pass


def transpose_lists_of_lists(list_of_lists):
    outlist_of_lists = [
        [row[colnr] for row in list_of_lists] for colnr in range(len(list_of_lists[0]))
    ]
    return outlist_of_lists


def fn_timer(function: Callable) -> Callable:
    """from http://www.marinamele.com/7-tips-to-time-python-scripts-and-control-memory-and-cpu-usage"""

    @wraps(function)
    def function_timer(*args, **kwargs):
        t0 = time.time()
        result = function(*args, **kwargs)
        t1 = time.time()
        try:
            print(
                "Total time running %s: %s seconds" % (function.__name__, str(t1 - t0))
            )
        except OSError:
            pass

        return result

    return function_timer


def general_exception_handler(func: Callable) -> Callable:
    """
    If UsageError is raised without message, it is assumed that the programmer has used MessagebarAndLog for the messages
    and no additional message will be printed.

    UserInterruptError is assumed to never have an error text.

    :param func:
    :return:
    """

    def new_func(*args, **kwargs):
        try:
            result = func(*args, **kwargs)
        except UserInterruptError:
            # The user interrupted the process.
            pass
        except UsageError as e:
            msg = str(e)
            if msg:
                MessagebarAndLog.critical(
                    bar_msg=returnunicode(
                        tr("general_exception_handler", "Usage error: %s")
                    )
                    % str(e),
                    duration=30,
                )
        except Exception:
            raise
        else:
            return result
        finally:
            stop_waiting_cursor()

    return new_func


def _to_json_serializable(obj: Any) -> Any:
    """Recursively convert tuples to lists so the value can be JSON-serialised."""
    if isinstance(obj, tuple):
        return [_to_json_serializable(v) for v in obj]
    if isinstance(obj, list):
        return [_to_json_serializable(v) for v in obj]
    if isinstance(obj, dict):
        return {str(k): _to_json_serializable(v) for k, v in obj.items()}
    return obj


def save_stored_settings(ms, stored_settings, settingskey, skip_ast=False):
    """
    Saves the current parameter settings into midvatten settings

    :param ms: midvattensettings
    :param stored_settings: a tuple like ((objname', ((attr1, value1), (attr2, value2))), (objname2, ((attr3, value3), ...)
    :return: stores a JSON string in midvatten settings (falls back to Python repr for types
             that cannot be serialised)
    """
    if not skip_ast:
        try:
            settings_string = json.dumps(_to_json_serializable(stored_settings))
        except (TypeError, ValueError):
            settings_string = anything_to_string_representation(stored_settings)
    else:
        settings_string = stored_settings
    ms.settingsdict[settingskey] = settings_string
    ms.save_settings(settingskey)
    MessagebarAndLog.info(
        log_msg=returnunicode(
            tr("save_stored_settings", "Settings %s stored for key %s.")
        )
        % (settings_string, settingskey)
    )


def get_stored_settings(ms, settingskey, default=None, skip_ast=False):
    """
    Reads the settings from settingskey and returns a created dict/list/tuple using ast.literal_eval

    :param ms: midvatten settings
    :param settingskey: the key to get from midvatten settings.
    :return: a tuple like ((objname', ((attr1, value1), (attr2, value2))), (objname2, ((attr3, value3), ...)
    """
    if default is None:
        default = []
    settings_string_raw = ms.settingsdict.get(settingskey, None)
    if settings_string_raw is None:
        MessagebarAndLog.info(
            bar_msg=returnunicode(
                tr(
                    "get_stored_settings",
                    "Settings key %s did not exist in midvatten settings.",
                )
            )
            % settingskey
        )
        return default
    if not settings_string_raw:
        MessagebarAndLog.info(
            log_msg=returnunicode(
                tr("get_stored_settings", "Settings key %s was empty.")
            )
            % settingskey
        )
        return default

    settings_string_raw = returnunicode(settings_string_raw)

    try:
        MessagebarAndLog.info(
            log_msg=returnunicode(
                tr("get_stored_settings", 'Reading stored settings "%s":\n%s')
            )
            % (settingskey, settings_string_raw)
        )
    except Exception:
        MessagebarAndLog.warning(log_msg=traceback.format_exc())

    if skip_ast:
        stored_settings = settings_string_raw
    else:
        try:
            stored_settings = json.loads(settings_string_raw)
        except (json.JSONDecodeError, ValueError):
            pass
        else:
            return stored_settings
        try:
            stored_settings = ast.literal_eval(settings_string_raw)
        except SyntaxError as e:
            stored_settings = default
            MessagebarAndLog.warning(
                bar_msg=returnunicode(
                    tr(
                        "get_stored_settings",
                        "Getting stored settings failed for key %s see log message panel.",
                    )
                )
                % settingskey,
                log_msg=returnunicode(
                    tr(
                        "ExportToFieldLogger",
                        'Parsing the settingsstring %s failed. Msg "%s"',
                    )
                )
                % (settings_string_raw, str(e)),
            )
        except ValueError as e:
            stored_settings = default
            MessagebarAndLog.warning(
                bar_msg=returnunicode(
                    tr(
                        "get_stored_settings",
                        "Getting stored settings failed for key %s see log message panel.",
                    )
                )
                % settingskey,
                log_msg=returnunicode(
                    tr(
                        "ExportToFieldLogger",
                        'Parsing the settingsstring %s failed. Msg "%s"',
                    )
                )
                % (settings_string_raw, str(e)),
            )

    return stored_settings


def to_float_or_none(anything):
    if isinstance(anything, float):
        return anything
    elif isinstance(anything, int):
        return float(anything)
    elif isinstance(anything, str):
        try:
            a_float = float(anything.replace(",", "."))
        except TypeError:
            return None
        except ValueError:
            return None
        except Exception:
            return None
        else:
            return a_float
    elif anything is None:
        return anything
    else:
        try:
            a_float = float(str(anything).replace(",", "."))
        except Exception:
            return None
        else:
            return a_float


def sql_unicode_list(an_iterator: tuple[str, ...]) -> str:
    return ", ".join([f"'{returnunicode(x)}'" for x in an_iterator])


def get_save_file_name_no_extension(**kwargs) -> str:
    filename = qgis.PyQt.QtWidgets.QFileDialog.getSaveFileName(**kwargs)
    if not filename[0]:
        raise UserInterruptError()
    else:
        return filename[0]


def dict_to_tuple(adict: dict) -> tuple[tuple[Any, Any], ...]:
    return tuple([(k, v) for k, v in sorted(adict.items())])


class ContinuousColorCycle:
    def __init__(
        self, color_cycle, color_cycle_len, style_cycler, used_style_color_combo
    ):
        self.color_cycle = color_cycle
        self.color_cycle_len = color_cycle_len
        self.style_cycler_len = len(style_cycler)
        self.style_cycle = style_cycler()
        # Initiate the first to match the logic in __next__
        next(self.style_cycle)
        self.used_style_color_combo = used_style_color_combo

    def __next__(self):
        # Go one lap around the cycle
        [next(self.style_cycle) for _ in range(self.style_cycler_len - 1)]

        for _ in range(self.style_cycler_len):
            s = next(self.style_cycle)
            for _ in range(self.color_cycle_len):
                c = next(self.color_cycle)
                next_combo = dict(c)
                next_combo.update(s)
                next_combo_str = dict_to_tuple(next_combo)
                if next_combo_str not in self.used_style_color_combo:
                    self.used_style_color_combo.add(next_combo_str)
                    return next_combo
        else:
            MessagebarAndLog.info(
                bar_msg=returnunicode(
                    tr(
                        "Customplot",
                        "Style cycler ran out of unique combinations. Using random color!",
                    )
                )
            )
            # Use next again to not get the same as last time.
            next(self.style_cycle)
            next_combo = dict(next(self.style_cycle))
            r = np.random.rand(3, 1).ravel()
            next_combo.update({"color": r})
            return next_combo


class PickAnnotator:
    def __init__(self, fig, canvas=None, mousebutton="left"):
        self.fig = fig
        self.annotation = None

        self.mousebutton = mousebutton
        if canvas is None:
            canvas = fig.canvas

        canvas.mpl_connect("pick_event", lambda event: self.identify_plot(event))
        canvas.mpl_connect("figure_enter_event", self.remove_annotation)
        MessagebarAndLog.info(log_msg=tr("PickAnnotator", "PickAnnotator initialized."))

    def identify_plot(self, event):
        try:
            mouseevent = event.mouseevent
            if mouseevent.button.name.lower() != self.mousebutton:
                return
            artist = event.artist
            ax = artist.axes

            try:
                xtext = datetime.datetime.strftime(
                    num2date(mouseevent.xdata), "%Y-%m-%d %H:%M:%S"
                )
            except Exception:
                xtext = mouseevent.xdata

            try:
                ytext = round(mouseevent.ydata, 3)
            except Exception:
                ytext = mouseevent.ydata
            new_text = ", ".join([f'"{artist.get_label()}"', str(xtext), str(ytext)])

            pos = (mouseevent.xdata, mouseevent.ydata)
            if not isinstance(self.annotation, mpl.text.Annotation):
                try:
                    self.annotation = ax.annotate(
                        text=new_text,
                        xy=pos,
                        fontsize=8,
                        xycoords="data",
                        bbox=dict(boxstyle="round", fc="w", ec="k", alpha=0.5),
                    )
                except Exception:
                    self.annotation = ax.annotate(
                        new_text,
                        xy=pos,
                        fontsize=8,
                        xycoords="data",
                        bbox=dict(boxstyle="round", fc="w", ec="k", alpha=0.5),
                    )
            else:
                self.annotation.set_text(new_text)
                self.annotation.set_x(pos[0])
                self.annotation.set_y(pos[1])

            self.fig.canvas.draw()
            self.fig.canvas.flush_events()
        except Exception as e:
            MessagebarAndLog.info(
                log_msg=tr("PickAnnotator", "Adding annotation failed, msg: %s.")
                % str(e)
            )
            raise

    def remove_annotation(self, event):
        if isinstance(self.annotation, mpl.text.Annotation):
            try:
                self.annotation.remove()
                self.annotation = None
                self.fig.canvas.draw()
                self.fig.canvas.flush_events()
            except Exception as e:
                MessagebarAndLog.info(
                    log_msg=tr("PickAnnotator", "Removing annotation failed, msg: %s.")
                    % str(e)
                )


class Timer:
    def __init__(self, name):
        self.t0 = time.time()
        self.t1 = self.t0
        self.name = name

    def stop(self):
        t = time.time()
        MessagebarAndLog.info(
            log_msg=tr("Timer", "Total time running %s: %s seconds")
            % (self.name, str(t - self.t0))
        )

    def current_time(self, info=""):
        MessagebarAndLog.info(
            log_msg=tr("Timer", "Current time running %s%s: %s seconds")
            % (self.name, info, str(time.time() - self.t0))
        )

    def diff(self, info=""):
        t = time.time()
        diff = time.time() - self.t1
        self.t1 = t
        MessagebarAndLog.info(
            log_msg=tr("Timer", "Current time running %s%s: %s seconds")
            % (self.name, info, str(diff))
        )


@contextmanager
def timer(name):
    t0 = time.time()
    yield
    t1 = time.time()
    MessagebarAndLog.info(
        log_msg=tr("timer", "Total time running %s: %s seconds") % (name, str(t1 - t0))
    )


def get_date_time() -> str:
    """returns date and time as a string in a pre-formatted format"""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def format_timezone_string(index: int) -> str:
    if index < -12 or index > 14:
        raise Exception("Error, timezone must be between -12 and + 14.")
    if index < 0:
        return f"UTC{str(index)}"
    elif not index:
        return "UTC"
    else:
        return f"UTC+{str(index)}"
