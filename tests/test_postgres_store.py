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

        store = PostgresGraphStore(DATABASE_URL, user_id="contract-test-user")
        # isolate each test: unique-enough IDs make cross-test pollution
        # unlikely to matter, but truncate for a clean slate regardless.
        store._conn.execute("TRUNCATE entities, relations")
        yield store
        store._conn.execute("TRUNCATE entities, relations")


def test_user_id_isolates_entities_and_relations():
    """Epic 11.5: one Postgres database, many tenants -- two `user_id`s
    against the same DSN must not see each other's graph at all, since the
    remote MCP server caches one `PostgresGraphStore` per authenticated user
    and relies entirely on this filter for isolation."""
    from memory_core.graph.models import Entity, Relation
    from memory_core.graph.postgres_store import PostgresGraphStore

    store_a = PostgresGraphStore(DATABASE_URL, user_id="tenant-a")
    store_b = PostgresGraphStore(DATABASE_URL, user_id="tenant-b")
    store_a._conn.execute("TRUNCATE entities, relations")

    alice = Entity(name="Alice", type="person")
    bob = Entity(name="Bob", type="person")
    store_a.add_entities([alice])
    store_b.add_entities([bob])
    store_a.add_relations([Relation(subject_id=alice.id, predicate="knows", object_id=alice.id)])

    try:
        assert {e.id for e in store_a.all_entities()} == {alice.id}
        assert {e.id for e in store_b.all_entities()} == {bob.id}
        assert store_a.get_entity(bob.id) is None
        assert store_b.find_entities_by_name("Alice") == []
        assert len(store_a.all_relations()) == 1
        assert store_b.all_relations() == []

        # tenant B can't delete tenant A's relation/entity by guessing IDs
        store_b.delete_entity(alice.id)
        assert store_a.get_entity(alice.id) is not None
    finally:
        store_a._conn.execute("TRUNCATE entities, relations")
