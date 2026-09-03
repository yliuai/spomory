"""Runs the exact same contract suite LocalGraphStore passes, against
PostgresGraphStore — skipped unless DATABASE_URL points at a real Postgres,
since none is available in this development environment. This is Epic 8.2's
honest verification status: implements the interface, unexercised.
"""

import os

import pytest

pytest.importorskip("psycopg")

from .graph_store_contract import GraphStoreContractTests

DATABASE_URL = os.environ.get("DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="set DATABASE_URL to a real Postgres instance to run this"
)


class TestPostgresGraphStoreContract(GraphStoreContractTests):
    @pytest.fixture
    def store(self):
        from memory_core.graph.postgres_store import PostgresGraphStore

        store = PostgresGraphStore(DATABASE_URL)
        # isolate each test: unique-enough IDs make cross-test pollution
        # unlikely to matter, but truncate for a clean slate regardless.
        store._conn.execute("TRUNCATE entities, relations")
        yield store
        store._conn.execute("TRUNCATE entities, relations")
