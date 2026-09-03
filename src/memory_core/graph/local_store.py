"""Default local backend: networkx in-memory graph + SQLite persistence."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import networkx as nx

from .models import Entity, Relation
from .store import GraphStoreBase


def _normalize(name: str) -> str:
    return name.strip().lower()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS relations (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL,
    object_id TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_relations_subject ON relations(subject_id);
CREATE INDEX IF NOT EXISTS idx_relations_object ON relations(object_id);
"""


class LocalGraphStore(GraphStoreBase):
    """``GraphStoreBase`` backed by ``networkx.MultiDiGraph`` with SQLite persistence.

    Writes go to both the in-memory graph (for fast traversal) and SQLite
    (write-through, so a process restart replays state from disk).
    """

    def __init__(self, db_path: str | Path = ":memory:", encryption_key: bytes | None = None) -> None:
        """``encryption_key`` (Epic 10.1): when given, every entity/relation's
        JSON blob is Fernet-encrypted before it touches disk — a database
        file/backup then holds only ciphertext, never plaintext names,
        attributes, or provenance. Generate one with
        ``cryptography.fernet.Fernet.generate_key()`` and keep it outside
        the database (env var / secrets manager), not next to the db file.
        """
        self.db_path = str(db_path)
        self._fernet = None
        if encryption_key is not None:
            from cryptography.fernet import Fernet

            self._fernet = Fernet(encryption_key)
        # check_same_thread=False: MCP tool calls run in a worker thread pool
        # (anyio.to_thread), not the thread the store was constructed on.
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._graph = nx.MultiDiGraph()
        self._load_from_db()

    def _encode(self, json_str: str) -> str:
        if self._fernet is None:
            return json_str
        return self._fernet.encrypt(json_str.encode()).decode()

    def _decode(self, stored: str) -> str:
        if self._fernet is None:
            return stored
        return self._fernet.decrypt(stored.encode()).decode()

    def _load_from_db(self) -> None:
        for (data,) in self._conn.execute("SELECT data FROM entities"):
            entity = Entity(**json.loads(self._decode(data)))
            self._graph.add_node(entity.id, entity=entity)
        for (data,) in self._conn.execute("SELECT data FROM relations"):
            relation = Relation(**json.loads(self._decode(data)))
            self._graph.add_edge(
                relation.subject_id, relation.object_id, key=relation.id, relation=relation
            )

    def add_entities(self, entities: list[Entity]) -> None:
        rows = [(e.id, self._encode(e.model_dump_json())) for e in entities]
        self._conn.executemany(
            "INSERT INTO entities (id, data) VALUES (?, ?) "
            "ON CONFLICT(id) DO UPDATE SET data = excluded.data",
            rows,
        )
        self._conn.commit()
        for entity in entities:
            self._graph.add_node(entity.id, entity=entity)

    def add_relations(self, relations: list[Relation]) -> None:
        rows = [
            (r.id, r.subject_id, r.object_id, self._encode(r.model_dump_json())) for r in relations
        ]
        self._conn.executemany(
            "INSERT INTO relations (id, subject_id, object_id, data) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET data = excluded.data, "
            "subject_id = excluded.subject_id, object_id = excluded.object_id",
            rows,
        )
        self._conn.commit()
        for relation in relations:
            self._graph.add_edge(
                relation.subject_id, relation.object_id, key=relation.id, relation=relation
            )

    def get_entity(self, entity_id: str) -> Entity | None:
        if entity_id not in self._graph.nodes:
            return None
        return self._graph.nodes[entity_id]["entity"]

    def find_entities_by_name(self, name: str) -> list[Entity]:
        target = _normalize(name)
        return [
            data["entity"]
            for _, data in self._graph.nodes(data=True)
            if _normalize(data["entity"].name) == target
            or any(_normalize(alias) == target for alias in data["entity"].aliases)
        ]

    def get_neighbors(self, entity_id: str) -> list[Relation]:
        relations: list[Relation] = []
        for _, _, data in self._graph.out_edges(entity_id, data=True):
            relations.append(data["relation"])
        for _, _, data in self._graph.in_edges(entity_id, data=True):
            relations.append(data["relation"])
        return relations

    def query_subgraph(
        self, entity_ids: list[str], hops: int = 1
    ) -> tuple[list[Entity], list[Relation]]:
        undirected = self._graph.to_undirected(as_view=True)
        reachable: set[str] = set()
        for entity_id in entity_ids:
            if entity_id not in undirected:
                continue
            reachable |= nx.single_source_shortest_path_length(
                undirected, entity_id, cutoff=hops
            ).keys()

        entities = [self._graph.nodes[n]["entity"] for n in reachable]
        relations = [
            data["relation"]
            for u, v, data in self._graph.edges(data=True)
            if u in reachable and v in reachable
        ]
        return entities, relations

    def delete_entity(self, entity_id: str) -> None:
        self._conn.execute("DELETE FROM entities WHERE id = ?", (entity_id,))
        self._conn.execute(
            "DELETE FROM relations WHERE subject_id = ? OR object_id = ?",
            (entity_id, entity_id),
        )
        self._conn.commit()
        if entity_id in self._graph:
            self._graph.remove_node(entity_id)

    def delete_relation(self, relation_id: str) -> None:
        self._conn.execute("DELETE FROM relations WHERE id = ?", (relation_id,))
        self._conn.commit()
        for u, v, key in list(self._graph.edges(keys=True)):
            if key == relation_id:
                self._graph.remove_edge(u, v, key=key)
                break

    def all_entities(self) -> list[Entity]:
        return [data["entity"] for _, data in self._graph.nodes(data=True)]

    def all_relations(self) -> list[Relation]:
        return [data["relation"] for _, _, data in self._graph.edges(data=True)]
