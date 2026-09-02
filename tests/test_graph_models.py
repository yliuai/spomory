import json

from memory_core.graph.models import Entity, Provenance, Relation


def test_entity_json_roundtrip():
    entity = Entity(
        name="张三",
        type="person",
        attributes={"role": "客户"},
        provenance=[Provenance(source_id="doc-1", source_span="张三是我们的客户")],
    )
    payload = entity.model_dump_json()
    restored = Entity(**json.loads(payload))
    assert restored.name == "张三"
    assert restored.type == "person"
    assert restored.provenance[0].source_id == "doc-1"
    assert restored.created_at == entity.created_at


def test_relation_json_roundtrip():
    relation = Relation(
        subject_id="e1",
        predicate="任职于",
        object_id="e2",
        confidence=0.9,
        provenance=[Provenance(source_id="doc-1", source_span="张三在某公司工作")],
    )
    payload = relation.model_dump_json()
    restored = Relation(**json.loads(payload))
    assert restored.subject_id == "e1"
    assert restored.predicate == "任职于"
    assert restored.object_id == "e2"
    assert restored.confidence == 0.9
