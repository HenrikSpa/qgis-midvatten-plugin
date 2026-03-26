"""
String conversion and validation utilities for the Midvatten plugin.
"""

import logging
import time
import traceback
from collections import OrderedDict
from typing import Any

from qgis.PyQt.QtCore import QCoreApplication

log = logging.getLogger(__name__)


def tr(context: str, msg: str) -> str:
    """Shorter function alias for QCoreApplication.translate"""
    return QCoreApplication.translate(context, msg)


def returnunicode(
    anything: Any, keep_containers: bool = False
) -> Any:  # takes an input and tries to return it as unicode
    r"""

    >>> returnunicode('b')
    'b'
    >>> returnunicode(int(1))
    '1'
    >>> returnunicode(None)
    ''
    >>> returnunicode([])
    '[]'
    >>> returnunicode(['a', 'b'])
    "['a', 'b']"
    >>> returnunicode(['a', 'b'])
    "['a', 'b']"
    >>> returnunicode(['ä', 'ö'])
    "['ä', 'ö']"
    >>> returnunicode(float(1))
    '1.0'
    >>> returnunicode(None)
    ''
    >>> returnunicode([(1, ), {2: 'a'}], True)
    [('1',), {'2': 'a'}]

    :param anything: just about anything
    :return: hopefully a unicode converted anything
    """
    if isinstance(anything, str):
        return anything
    if anything is None:
        return ""
    if isinstance(anything, bytes):
        for charset in ["utf-8", "cp1252", "iso-8859-1", "ascii"]:
            try:
                return anything.decode(charset)
            except (UnicodeDecodeError, UnicodeEncodeError):
                continue
        return str(anything)  # fallback to repr
    if isinstance(anything, (list, tuple, dict, OrderedDict)):
        if isinstance(anything, list):
            decoded = [returnunicode(x, keep_containers) for x in anything]
        elif isinstance(anything, tuple):
            decoded = tuple([returnunicode(x, keep_containers) for x in anything])
        elif isinstance(anything, dict):
            decoded = dict(
                [
                    (
                        returnunicode(k, keep_containers),
                        returnunicode(v, keep_containers),
                    )
                    for k, v in anything.items()
                ]
            )
        else:  # OrderedDict
            decoded = OrderedDict(
                [
                    (
                        returnunicode(k, keep_containers),
                        returnunicode(v, keep_containers),
                    )
                    for k, v in anything.items()
                ]
            )
        if not keep_containers:
            decoded = str(decoded)
        return decoded
    return str(anything)


def unicode_2_utf8(anything):  # takes an unicode and tries to return it as utf8
    r"""

    :param anything: just about anything
    :return: hopefully a utf8 converted anything
    """
    # anything = returnunicode(anything)
    text = None
    try:
        if anything is None:
            text = b""
        elif isinstance(anything, str):
            text = anything.encode("utf-8")
        elif isinstance(anything, list):
            text = [unicode_2_utf8(x) for x in anything]
        elif isinstance(anything, tuple):
            text = tuple([unicode_2_utf8(x) for x in anything])
        elif isinstance(anything, float):
            text = anything.encode("utf-8")
        elif isinstance(anything, int):
            text = anything.encode("utf-8")
        elif isinstance(anything, dict):
            text = dict(
                [(unicode_2_utf8(k), unicode_2_utf8(v)) for k, v in anything.items()]
            )
        elif isinstance(anything, str):
            text = anything
        elif isinstance(anything, bool):
            text = anything.encode("utf-8")
    except Exception:
        from midvatten.tools.utils.message_utils import MessagebarAndLog

        MessagebarAndLog.info(log_msg=traceback.format_exc())

    if text is None:
        text = returnunicode(
            tr("unicode_2_utf8", "data type unknown, check database")
        ).encode("utf-8")
    return text


def lists_to_string(alist_of_lists, quote=False):
    r'''

        The long Version:
        reslist = []
        for row in alist_of_lists:
            if isinstance(row, (list, tuple)):
                innerlist = []
                for col in row:
                    if quote:
                        if all(['"' in returnunicode(col), '""' not in returnunicode(col)]):
                            innerword = returnunicode(col).replace('"', '""')
                        else:
                            innerword = returnunicode(col)
                        try:
                            innerlist.append('"{}"'.format(innerword))
                        except UnicodeDecodeError:
                            log.debug(str(innerword))
                            raise Exception
                    else:
                        innerlist.append(returnunicode(col))
                reslist.append(';'.join(innerlist))
            else:
                reslist.append(returnunicode(row))

        return_string = '\n'.join(reslist)


    :param alist_of_lists:
    :return: A string with '\n' separating rows and ; separating columns.

    >>> lists_to_string([1])
    '1'
    >>> lists_to_string([('a', 'b'), (1, 2)])
    'a;b\n1;2'
    >>> lists_to_string([('a', 'b'), (1, 2)], quote=True)
    '"a";"b"\n"1";"2"'
    >>> lists_to_string([('"a"', 'b'), (1, 2)], quote=False)
    '"a";b\n1;2'
    >>> lists_to_string([('"a"', 'b'), (1, 2)], quote=True)
    '"""a""";"b"\n"1";"2"'
    '''
    if isinstance(alist_of_lists, (list, tuple)):
        return_string = "\n".join(
            [
                (
                    ";".join(
                        [
                            (
                                '"{}"'.format(
                                    returnunicode(col).replace('"', '""')
                                    if all(
                                        [
                                            '"' in returnunicode(col),
                                            '""' not in returnunicode(col),
                                        ]
                                    )
                                    else returnunicode(col)
                                )
                                if quote
                                else returnunicode(col)
                            )
                            for col in row
                        ]
                    )
                    if isinstance(row, (list, tuple))
                    else returnunicode(row)
                )
                for row in alist_of_lists
            ]
        )

    else:
        return_string = returnunicode(alist_of_lists)
    return return_string


def lstrip(word: str, from_string: str) -> str:
    """
    Strips word from the start of from_string
    :param word: a string to strip
    :param from_string: the string to strip from
    :return: the new string or the old string if word was not at the beginning of from_string.

    >>> lstrip('123', '123abc')
    'abc'
    >>> lstrip('1234', '123abc')
    '123abc'
    """
    new_word = from_string
    if from_string.startswith(word):
        new_word = from_string[len(word) :]
    return new_word


def rstrip(word: str, from_string: str) -> str:
    """
    Strips word from the end of from_string
    :param word: a string to strip
    :param from_string: the string to strip from
    :return: the new string or the old string if word was not at the end of from_string.

    >>> rstrip('abc', '123abc')
    '123'
    >>> rstrip('abcd', '123abc')
    '123abc'
    """
    new_word = from_string
    if from_string.endswith(word):
        new_word = from_string[0 : -len(word)]
    return new_word


def isfloat(str: str):
    try:
        float(str)
    except ValueError:
        return False
    return True


def isinteger(str):
    try:
        int(str)
    except ValueError:
        return False
    return True


def isdate(str):
    result = False
    formats = ["%Y-%m-%d", "%Y-%m-%d %H", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"]
    for fmt in formats:
        try:
            time.strptime(str, fmt)
            result = True
        except ValueError:
            pass
    return result


def anything_to_string_representation(
    anything: Any,
    itemjoiner: str = ", ",
    pad: str = "",
    dictformatter: str = "{%s}",
    listformatter: str = "[%s]",
    tupleformatter: str = "(%s, )",
    compact: bool = False,
) -> str:
    r"""Turns anything into a string used for testing
    :param anything: just about anything
    :param itemjoiner: The string to join list/tuple/dict items with.
    :param compact: If True, use simpler output (no quotes around simple types, for tests).
    :return: A unicode string
     >>> anything_to_string_representation({('123'): 4.5, "a": '7'})
     '{"123": 4.5, "a": "7"}'
     >>> anything_to_string_representation({('123', ): 4.5, "a": '7'})
     '{("123", ): 4.5, "a": "7"}'
     >>> anything_to_string_representation(['1', '2', 3])
     '["1", "2", 3]'
     >>> anything_to_string_representation({'123': 4.5, "a": '7'}, ',\n', '    ')
     '{    "123": 4.5,\n    "a": "7"}'
     >>> anything_to_string_representation({3: 'a', 2: 'b', 1: ('c', 'd')}, compact=True)
     '{1: (c, d), 2: b, 3: a}'
    """
    if isinstance(anything, dict):
        if compact:
            aunicode = "".join(
                [
                    "{",
                    ", ".join(
                        [
                            ": ".join(
                                [
                                    anything_to_string_representation(k, compact=True),
                                    anything_to_string_representation(v, compact=True),
                                ]
                            )
                            for k, v in sorted(anything.items())
                        ]
                    ),
                    "}",
                ]
            )
        else:
            aunicode = dictformatter % itemjoiner.join(
                [
                    pad
                    + ": ".join(
                        [
                            anything_to_string_representation(
                                k,
                                itemjoiner,
                                pad + pad,
                                dictformatter,
                                listformatter,
                                tupleformatter,
                                compact,
                            ),
                            anything_to_string_representation(
                                v,
                                itemjoiner,
                                pad + pad,
                                dictformatter,
                                listformatter,
                                tupleformatter,
                                compact,
                            ),
                        ]
                    )
                    for k, v in sorted(anything.items(), key=lambda k_v: str(k_v[0]))
                ]
            )
    elif isinstance(anything, list):
        if compact:
            aunicode = "".join(
                [
                    "[",
                    ", ".join(
                        anything_to_string_representation(x, compact=True)
                        for x in anything
                    ),
                    "]",
                ]
            )
        else:
            aunicode = listformatter % itemjoiner.join(
                [
                    pad
                    + anything_to_string_representation(
                        x,
                        itemjoiner,
                        pad + pad,
                        dictformatter,
                        listformatter,
                        tupleformatter,
                        compact,
                    )
                    for x in anything
                ]
            )
    elif isinstance(anything, tuple):
        if compact:
            aunicode = "".join(
                [
                    "(",
                    ", ".join(
                        anything_to_string_representation(x, compact=True)
                        for x in anything
                    ),
                    ")",
                ]
            )
        else:
            aunicode = tupleformatter % itemjoiner.join(
                [
                    pad
                    + anything_to_string_representation(
                        x,
                        itemjoiner,
                        pad + pad,
                        dictformatter,
                        listformatter,
                        tupleformatter,
                        compact,
                    )
                    for x in anything
                ]
            )
    elif isinstance(anything, (float, int)):
        aunicode = f"{returnunicode(anything)}"
    elif isinstance(anything, str):
        if compact:
            aunicode = returnunicode(anything)
        elif '"' not in anything:
            aunicode = f'"{anything}"'
        elif "'" not in anything:
            aunicode = f"'{anything}'"
        elif not anything.startswith('"') and not anything.endswith('"'):
            aunicode = f'"""{anything}"""'
        elif not anything.startswith("'") and not anything.endswith("'"):
            aunicode = f"'''{anything}'''"
        else:
            aunicode = f'""" {anything} """'
    else:
        try:
            from qgis.PyQt import QtCore

            if isinstance(anything, QtCore.QVariant):
                aunicode = returnunicode(anything.toString().data())
            else:
                aunicode = returnunicode(str(anything))
        except ImportError:
            aunicode = returnunicode(str(anything))
    return aunicode
