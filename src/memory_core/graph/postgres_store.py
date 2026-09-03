"""Cloud backend for Epic 8.2: same `GraphStoreBase` contract as
`LocalGraphStore`, backed by Postgres instead of SQLite + in-memory networkx.

Scaffolding only — there is no Postgres instance available in this
development environment to run it against, so unlike every other store in
this codebase, this one has NOT been exercised against a real database.
`tests/test_postgres_store.py` runs the exact same behavioral contract
suite `LocalGraphStore` passes, but is skipped unless a `DATABASE_URL` env
var points at a real Postgres. Treat this module as implementing the
interface correctly by code review, not as verified.
"""

from __future__ import annotations

import json

from .models import Entity, Relation
from .store import GraphStoreBase

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    data JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS relations (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL,
    object_id TEXT NOT NULL,
    data JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_relations_subject ON relations(subject_id);
CREATE INDEX IF NOT EXISTS idx_relations_object ON relations(object_id);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(lower(name));
"""


def _normalize(name: str) -> str:
    return name.strip().lower()


class PostgresGraphStore(GraphStoreBase):
    """Same semantics as `LocalGraphStore` (upsert writes, physical deletes),
    minus the in-memory networkx cache — every read hits Postgres directly,
    since a cloud backend can't assume a single-process in-memory mirror
    stays consistent across multiple app server instances.
    """

    def __init__(self, dsn: str) -> None:
        import psycopg

        self._conn = psycopg.connect(dsn, autocommit=True)
        self._conn.execute(_SCHEMA)

    def add_entities(self, entities: list[Entity]) -> None:
        with self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO entities (id, name, data) VALUES (%s, %s, %s) "
                "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, data = EXCLUDED.data",
                [(e.id, e.name, e.model_dump_json()) for e in entities],
            )

    def add_relations(self, relations: list[Relation]) -> None:
        with self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO relations (id, subject_id, object_id, data) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (id) DO UPDATE SET subject_id = EXCLUDED.subject_id, "
                "object_id = EXCLUDED.object_id, data = EXCLUDED.data",
                [(r.id, r.subject_id, r.object_id, r.model_dump_json()) for r in relations],
            )

    def get_entity(self, entity_id: str) -> Entity | None:
        row = self._conn.execute(
            "SELECT data FROM entities WHERE id = %s", (entity_id,)
        ).fetchone()
        return Entity(**json.loads(row[0])) if row else None

    def find_entities_by_name(self, name: str) -> list[Entity]:
        target = _normalize(name)
        rows = self._conn.execute("SELECT data FROM entities").fetchall()
        entities = [Entity(**json.loads(r[0])) for r in rows]
        return [
            e
            for e in entities
            if _normalize(e.name) == target or any(_normalize(a) == target for a in e.aliases)
        ]

    def get_neighbors(self, entity_id: str) -> list[Relation]:
        rows = self._conn.execute(
            "SELECT data FROM relations WHERE subject_id = %s OR object_id = %s",
            (entity_id, entity_id),
        ).fetchall()
        return [Relation(**json.loads(r[0])) for r in rows]

    def query_subgraph(
        self, entity_ids: list[str], hops: int = 1
    ) -> tuple[list[Entity], list[Relation]]:
        # BFS in Python against Postgres-backed adjacency rather than a
        # recursive CTE, to keep the traversal semantics identical to
        # LocalGraphStore's (same hop-count contract, same result shape).
        reachable: set[str] = set(entity_ids)
        frontier: set[str] = set(entity_ids)
        for _ in range(hops):
            if not frontier:
                break
            neighbor_relations = [r for entity_id in frontier for r in self.get_neighbors(entity_id)]
            next_frontier: set[str] = set()
            for r in neighbor_relations:
                for endpoint in (r.subject_id, r.object_id):
                    if endpoint not in reachable:
                        reachable.add(endpoint)
                        next_frontier.add(endpoint)
            frontier = next_frontier

        entities = [e for eid in reachable if (e := self.get_entity(eid)) is not None]
        all_relations = [
            r
            for eid in reachable
            for r in self.get_neighbors(eid)
            if r.subject_id in reachable and r.object_id in reachable
        ]
        unique_relations = {r.id: r for r in all_relations}
        return entities, list(unique_relations.values())

    def delete_entity(self, entity_id: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "DELETE FROM relations WHERE subject_id = %s OR object_id = %s",
                (entity_id, entity_id),
            )
            cur.execute("DELETE FROM entities WHERE id = %s", (entity_id,))

    def delete_relation(self, relation_id: str) -> None:
        self._conn.execute("DELETE FROM relations WHERE id = %s", (relation_id,))

    def all_entities(self) -> list[Entity]:
        rows = self._conn.execute("SELECT data FROM entities").fetchall()
        return [Entity(**json.loads(r[0])) for r in rows]

    def all_relations(self) -> list[Relation]:
        rows = self._conn.execute("SELECT data FROM relations").fetchall()
        return [Relation(**json.loads(r[0])) for r in rows]
