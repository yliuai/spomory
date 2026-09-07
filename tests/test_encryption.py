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


def test_migrate_plaintext_to_encrypted_rewrites_rows_and_keeps_a_backup(tmp_path):
    from memory_core.graph.local_store import migrate_plaintext_to_encrypted

    db_path = tmp_path / "g.sqlite3"
    plain = LocalGraphStore(db_path)
    a, b = Entity(name="张三", type="person"), Entity(name="李四", type="person")
    plain.add_entities([a, b])
    plain.add_relations([Relation(subject_id=a.id, predicate="认识", object_id=b.id)])
    plain._conn.close()

    key = Fernet.generate_key()
    assert migrate_plaintext_to_encrypted(db_path, key) is True

    backup_path = db_path.with_suffix(db_path.suffix + ".pre-encryption-backup")
    assert backup_path.exists()

    conn = sqlite3.connect(db_path)
    raw = conn.execute("SELECT data FROM entities WHERE id = ?", (a.id,)).fetchone()[0]
    conn.close()
    assert "张三" not in raw

    reopened = LocalGraphStore(db_path, encryption_key=key)
    assert {e.name for e in reopened.all_entities()} == {"张三", "李四"}
    assert len(reopened.all_relations()) == 1


def test_migrate_plaintext_to_encrypted_is_a_noop_on_missing_or_empty_or_already_encrypted_db(
    tmp_path,
):
    from memory_core.graph.local_store import migrate_plaintext_to_encrypted

    key = Fernet.generate_key()

    # no file yet
    assert migrate_plaintext_to_encrypted(tmp_path / "missing.sqlite3", key) is False

    # file exists, schema created, but no rows written
    empty_path = tmp_path / "empty.sqlite3"
    LocalGraphStore(empty_path)._conn.close()
    assert migrate_plaintext_to_encrypted(empty_path, key) is False

    # already encrypted -- calling it again must not double-encrypt or crash
    encrypted_path = tmp_path / "already.sqlite3"
    store = LocalGraphStore(encrypted_path, encryption_key=key)
    store.add_entities([Entity(name="a", type="thing")])
    store._conn.close()
    assert migrate_plaintext_to_encrypted(encrypted_path, key) is False
    assert LocalGraphStore(encrypted_path, encryption_key=key).all_entities()[0].name == "a"
