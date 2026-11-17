"""Test configuration.

By default every test uses its own temporary SQLite file. To run the whole suite
against PostgreSQL instead, point CONTENT_FLOW_TEST_POSTGRES_URL at an empty,
disposable database (its `public` schema is dropped before every test):

    CONTENT_FLOW_TEST_POSTGRES_URL=postgresql://postgres:postgres@localhost:55432/contentflow_test python -m pytest
"""
from __future__ import annotations

import os
from typing import Iterator

import pytest

POSTGRES_TEST_URL = os.environ.get("CONTENT_FLOW_TEST_POSTGRES_URL", "").strip()

if POSTGRES_TEST_URL:
    os.environ["CONTENT_FLOW_DATABASE_URL"] = POSTGRES_TEST_URL

    @pytest.fixture(autouse=True)
    def fresh_postgres_schema() -> Iterator[None]:
        from app.database import get_engine

        with get_engine().begin() as connection:
            connection.exec_driver_sql("DROP SCHEMA public CASCADE")
            connection.exec_driver_sql("CREATE SCHEMA public")
        yield
