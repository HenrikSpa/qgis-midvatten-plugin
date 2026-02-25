"""
pytest configuration for the Midvatten test suite.

When running with pytest-xdist (-n <N>), all PostGIS tests are grouped onto a
single worker to avoid concurrent DROP/CREATE SCHEMA conflicts on the shared
PostgreSQL server.  SQLite tests are already isolated by unique per-process file
paths so they run freely across all workers.
"""

import pytest


def pytest_collection_modifyitems(config, items):
    """Pin PostGIS tests to a single xdist worker."""
    for item in items:
        if any(m.name == "postgis" for m in item.iter_markers()):
            item.add_marker(pytest.mark.xdist_group("postgis"))
