"""Backend-level tests for repeated-statement execution."""

from unittest import mock

import pytest

pytest.importorskip("qgis.PyQt")

from midvatten.tools.utils.db_utils.backends.base import Backend
from midvatten.tools.utils.db_utils.backends.postgresql import (
    PostgreSQLBackend,
    _EXECUTE_BATCH_PAGE_SIZE,
)


def _postgres_backend() -> PostgreSQLBackend:
    backend = PostgreSQLBackend.__new__(PostgreSQLBackend)
    backend._cursor = mock.MagicMock()
    return backend


def test_postgresql_executemany_uses_execute_batch():
    backend = _postgres_backend()
    params = [(1, "a"), (2, "b")]

    with mock.patch(
        "midvatten.tools.utils.db_utils.backends.postgresql.psycopg2.extras.execute_batch"
    ) as execute_batch:
        backend.executemany("UPDATE t SET v = %s WHERE id = %s", params)

    execute_batch.assert_called_once_with(
        backend.cursor,
        "UPDATE t SET v = %s WHERE id = %s",
        params,
        page_size=_EXECUTE_BATCH_PAGE_SIZE,
    )
    backend.cursor.executemany.assert_not_called()


def test_postgresql_executemany_empty_params_is_noop():
    backend = _postgres_backend()

    with mock.patch(
        "midvatten.tools.utils.db_utils.backends.postgresql.psycopg2.extras.execute_batch"
    ) as execute_batch:
        backend.executemany("UPDATE t SET v = %s", [])

    execute_batch.assert_not_called()
    backend.cursor.executemany.assert_not_called()


def test_postgresql_executemany_logs_and_reraises():
    backend = _postgres_backend()
    error = RuntimeError("batch failed")

    with (
        mock.patch(
            "midvatten.tools.utils.db_utils.backends.postgresql.psycopg2.extras.execute_batch",
            side_effect=error,
        ),
        mock.patch.object(Backend, "log_execute_error") as log_error,
        pytest.raises(RuntimeError, match="batch failed"),
    ):
        backend.executemany("UPDATE t SET v = %s", [(1,)])

    log_error.assert_called_once_with("UPDATE t SET v = %s", [(1,)], error)
