"""Cloud backend for Epic 8.2: same `GraphStoreBase` contract as
`LocalGraphStore`, backed by Postgres instead of SQLite + in-memory networkx.

Verified against a real PostgreSQL 10 instance via
`tests/test_postgres_store.py` (the same 8-test contract suite
`LocalGraphStore` passes), gated on a `DATABASE_URL` env var.
"""

from __future__ import annotations

from .models import Entity, Relation
from .store import GraphStoreBase

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    data JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS relations (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    object_id TEXT NOT NULL,
    data JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_relations_subject ON relations(subject_id);
CREATE INDEX IF NOT EXISTS idx_relations_object ON relations(object_id);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(lower(name));
CREATE INDEX IF NOT EXISTS idx_entities_user ON entities(user_id);
CREATE INDEX IF NOT EXISTS idx_relations_user ON relations(user_id);
"""


def _normalize(name: str) -> str:
    return name.strip().lower()


class PostgresGraphStore(GraphStoreBase):
    """Same semantics as `LocalGraphStore` (upsert writes, physical deletes),
    minus the in-memory networkx cache — every read hits Postgres directly,
    since a cloud backend can't assume a single-process in-memory mirror
    stays consistent across multiple app server instances.

    `user_id` scopes every query so multiple tenants can share one Postgres
    database (Epic 11.5's remote MCP server): every read/write filters on it,
    so a `GraphStoreBase` caller sees exactly one user's graph without the
    interface itself needing a `user_id` parameter on each method. One
    instance holds one `psycopg` connection — for a multi-tenant server, the
    caller is expected to cache one instance per `user_id` rather than
    reconnect per request; a shared connection pool would be needed to scale
    concurrent users further, which this deliberately doesn't attempt yet.
    """

    def __init__(self, dsn: str, user_id: str) -> None:
        import psycopg

        self._conn = psycopg.connect(dsn, autocommit=True)
        self._conn.execute(_SCHEMA)
        self._user_id = user_id

    def add_entities(self, entities: list[Entity]) -> None:
        with self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO entities (id, user_id, name, data) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, data = EXCLUDED.data",
                [(e.id, self._user_id, e.name, e.model_dump_json()) for e in entities],
            )

    def add_relations(self, relations: list[Relation]) -> None:
        with self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO relations (id, user_id, subject_id, object_id, data) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (id) DO UPDATE SET subject_id = EXCLUDED.subject_id, "
                "object_id = EXCLUDED.object_id, data = EXCLUDED.data",
                [
                    (r.id, self._user_id, r.subject_id, r.object_id, r.model_dump_json())
                    for r in relations
                ],
            )

    def get_entity(self, entity_id: str) -> Entity | None:
        row = self._conn.execute(
            "SELECT data FROM entities WHERE id = %s AND user_id = %s", (entity_id, self._user_id)
        ).fetchone()
        # psycopg3 auto-adapts a jsonb column to a Python dict on fetch.
        return Entity(**row[0]) if row else None

    def find_entities_by_name(self, name: str) -> list[Entity]:
        target = _normalize(name)
        rows = self._conn.execute(
            "SELECT data FROM entities WHERE user_id = %s", (self._user_id,)
        ).fetchall()
        entities = [Entity(**r[0]) for r in rows]
        return [
            e
            for e in entities
            if _normalize(e.name) == target or any(_normalize(a) == target for a in e.aliases)
        ]

    def get_neighbors(self, entity_id: str) -> list[Relation]:
        rows = self._conn.execute(
            "SELECT data FROM relations WHERE (subject_id = %s OR object_id = %s) AND user_id = %s",
            (entity_id, entity_id, self._user_id),
        ).fetchall()
        return [Relation(**r[0]) for r in rows]

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
                "DELETE FROM relations WHERE (subject_id = %s OR object_id = %s) AND user_id = %s",
                (entity_id, entity_id, self._user_id),
            )
            cur.execute(
                "DELETE FROM entities WHERE id = %s AND user_id = %s", (entity_id, self._user_id)
            )

    def delete_relation(self, relation_id: str) -> None:
        self._conn.execute(
            "DELETE FROM relations WHERE id = %s AND user_id = %s", (relation_id, self._user_id)
        )

    def all_entities(self) -> list[Entity]:
        rows = self._conn.execute(
            "SELECT data FROM entities WHERE user_id = %s", (self._user_id,)
        ).fetchall()
        return [Entity(**r[0]) for r in rows]

    def all_relations(self) -> list[Relation]:
        rows = self._conn.execute(
            "SELECT data FROM relations WHERE user_id = %s", (self._user_id,)
        ).fetchall()
        return [Relation(**r[0]) for r in rows]
