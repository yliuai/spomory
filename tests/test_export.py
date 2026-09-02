import json
import sqlite3

from memory_core.export.exporter import delete_all, export_all
from memory_core.graph.local_store import LocalGraphStore
from memory_core.graph.models import Entity, Relation


def _seed_store(db_path) -> LocalGraphStore:
    store = LocalGraphStore(db_path)
    a = Entity(name="张三", type="person")
    b = Entity(name="某公司", type="organization")
    store.add_entities([a, b])
    store.add_relations([Relation(subject_id=a.id, predicate="任职于", object_id=b.id)])
    return store


def test_export_round_trips_without_information_loss(tmp_path):
    store = _seed_store(tmp_path / "g.sqlite3")
    export = export_all(store, subject_id="user-1")

    # Simulate an independent script parsing the export file back into a graph.
    payload = json.loads(export.model_dump_json(by_alias=True))
    entities = payload["entities"]
    relations = payload["relations"]

    assert len(entities) == 2
    assert len(relations) == 1
    assert {e["name"] for e in entities} == {"张三", "某公司"}
    assert relations[0]["predicate"] == "任职于"
    # every relation's endpoints must resolve to an id present in `entities`
    entity_ids = {e["id"] for e in entities}
    assert relations[0]["subject_id"] in entity_ids
    assert relations[0]["object_id"] in entity_ids
    assert payload["@type"] == "memory:MemoryPassport"


def test_delete_all_is_physically_verifiable_at_the_storage_layer(tmp_path):
    db_path = tmp_path / "g.sqlite3"
    store = _seed_store(db_path)

    receipt = delete_all(store, subject_id="user-1")
    assert receipt.fully_deleted
    assert receipt.entities_deleted == 2
    assert receipt.relations_deleted == 1

    # Don't trust the application layer — query the raw SQLite file directly.
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0] == 0
    conn.close()
