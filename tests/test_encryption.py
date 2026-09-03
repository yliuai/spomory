import sqlite3

import pytest

pytest.importorskip("cryptography")

from cryptography.fernet import Fernet

from memory_core.graph.local_store import LocalGraphStore
from memory_core.graph.models import Entity, Relation


def test_raw_database_file_holds_no_plaintext_when_encrypted(tmp_path):
    db_path = tmp_path / "g.sqlite3"
    key = Fernet.generate_key()

    store = LocalGraphStore(db_path, encryption_key=key)
    secret_name = "张三非常秘密的客户信息ZhangSanSecretClient"
    store.add_entities([Entity(name=secret_name, type="person")])
    del store  # ensure nothing but the on-disk file is being inspected

    conn = sqlite3.connect(db_path)
    raw = conn.execute("SELECT data FROM entities").fetchone()[0]
    conn.close()

    assert secret_name not in raw
    assert "person" not in raw  # the whole JSON blob is ciphertext, not just the name


def test_encrypted_store_round_trips_correctly(tmp_path):
    db_path = tmp_path / "g.sqlite3"
    key = Fernet.generate_key()

    store = LocalGraphStore(db_path, encryption_key=key)
    a, b = Entity(name="a", type="thing"), Entity(name="b", type="thing")
    store.add_entities([a, b])
    store.add_relations([Relation(subject_id=a.id, predicate="r", object_id=b.id)])
    del store

    reopened = LocalGraphStore(db_path, encryption_key=key)
    assert len(reopened.all_entities()) == 2
    assert len(reopened.all_relations()) == 1
    assert reopened.get_entity(a.id).name == "a"


def test_wrong_key_fails_to_decrypt(tmp_path):
    db_path = tmp_path / "g.sqlite3"
    store = LocalGraphStore(db_path, encryption_key=Fernet.generate_key())
    store.add_entities([Entity(name="a", type="thing")])
    del store

    from cryptography.fernet import InvalidToken

    with pytest.raises(InvalidToken):
        LocalGraphStore(db_path, encryption_key=Fernet.generate_key())


def test_unencrypted_store_is_unaffected():
    store = LocalGraphStore(":memory:")
    store.add_entities([Entity(name="a", type="thing")])
    assert store.all_entities()[0].name == "a"
