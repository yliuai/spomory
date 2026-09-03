from memory_core.audit import AuditLog
from memory_core.export.exporter import delete_all
from memory_core.graph.local_store import LocalGraphStore
from memory_core.graph.models import Entity, Relation


def test_record_and_query_deletion():
    log = AuditLog(":memory:")
    log.record_deletion(user_id="u1", entities_deleted=2, relations_deleted=1)

    records = log.query("u1")
    assert len(records) == 1
    assert records[0].event_type == "true_delete"
    assert records[0].detail == {"entities_deleted": 2, "relations_deleted": 1}
    assert records[0].created_at  # non-empty timestamp


def test_query_is_scoped_per_user():
    log = AuditLog(":memory:")
    log.record_deletion(user_id="u1", entities_deleted=1, relations_deleted=0)
    log.record_deletion(user_id="u2", entities_deleted=5, relations_deleted=3)

    assert len(log.query("u1")) == 1
    assert len(log.query("u2")) == 1
    assert log.query("u1")[0].detail["entities_deleted"] == 1


def test_delete_all_writes_an_audit_record(tmp_path):
    store = LocalGraphStore(tmp_path / "g.sqlite3")
    a, b = Entity(name="a", type="thing"), Entity(name="b", type="thing")
    store.add_entities([a, b])
    store.add_relations([Relation(subject_id=a.id, predicate="r", object_id=b.id)])

    log = AuditLog(":memory:")
    delete_all(store, subject_id="user-1", audit_log=log)

    records = log.query("user-1")
    assert len(records) == 1
    assert records[0].detail["entities_deleted"] == 2
    assert records[0].detail["relations_deleted"] == 1
