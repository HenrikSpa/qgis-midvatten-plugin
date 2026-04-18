"""ExportEngine — pure-Python, chunk-based export from any DbConnectionManager
source to a SpatiaLite destination."""

import logging
import threading
from typing import Callable

from midvatten.tools.utils import db_utils
from midvatten.tools.utils.db_utils import DbConnectionManager
from midvatten.definitions import midvatten_defs as defs

log = logging.getLogger(__name__)


class ExportCancelledError(Exception):
    pass


class ExportEngine:
    CHUNK_SIZE = 5_000
