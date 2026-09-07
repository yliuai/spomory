import pytest

pytest.importorskip("mcp")


def test_defaults_to_local_store_without_database_url(monkeypatch, tmp_path):
    from memory_core.graph.local_store import LocalGraphStore
    from memory_core.mcp_server.server import _select_store_from_env

    monkeypatch.delenv("DATABASE_URL", raising=False)
    # MEMORY_CORE_DATA_DIR -> tmp_path: without this, the real default
    # (~/.memory-core) would get written to by every test run.
    monkeypatch.setenv("MEMORY_CORE_DATA_DIR", str(tmp_path))

    store = _select_store_from_env()
    assert isinstance(store, LocalGraphStore)
    assert (tmp_path / "memory_core.sqlite3").exists()


def test_new_local_store_is_encrypted_by_default(monkeypatch, tmp_path):
    """Epic 11.2: a freshly created install shouldn't need any extra
    configuration to get encryption at rest -- calling _select_store_from_env
    the normal way should be enough."""
    pytest.importorskip("cryptography")
    from memory_core.mcp_server.server import _select_store_from_env

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("MEMORY_CORE_DATA_DIR", str(tmp_path))

    from memory_core.graph.models import Entity

    store = _select_store_from_env()
    store.add_entities([Entity(name="张三非常秘密的信息ZhangSanSecret", type="person")])

    key_path = tmp_path / "encryption.key"
    assert key_path.exists()
    assert oct(key_path.stat().st_mode)[-3:] == "600"

    import sqlite3

    conn = sqlite3.connect(tmp_path / "memory_core.sqlite3")
    raw = conn.execute("SELECT data FROM entities").fetchone()[0]
    conn.close()
    assert "张三非常秘密的信息ZhangSanSecret" not in raw


def test_encryption_key_persists_across_restarts(monkeypatch, tmp_path):
    """A new process picking the same MEMORY_CORE_DATA_DIR must reuse the
    same key -- generating a new one every start would make existing data
    permanently unreadable."""
    pytest.importorskip("cryptography")
    from memory_core.mcp_server.server import _select_store_from_env

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("MEMORY_CORE_DATA_DIR", str(tmp_path))

    from memory_core.graph.models import Entity

    first = _select_store_from_env()
    first.add_entities([Entity(name="张三", type="person")])

    second = _select_store_from_env()
    assert second.all_entities()[0].name == "张三"


def test_existing_plaintext_database_is_migrated_transparently(monkeypatch, tmp_path):
    """Epic 11.2's compatibility requirement: someone upgrading from before
    encryption was on by default shouldn't lose data or hit a crash -- their
    existing plaintext db should keep working, now encrypted, the next time
    the server starts."""
    pytest.importorskip("cryptography")
    from memory_core.graph.local_store import LocalGraphStore
    from memory_core.graph.models import Entity
    from memory_core.mcp_server.server import _select_store_from_env

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("MEMORY_CORE_DATA_DIR", str(tmp_path))

    # Simulate a pre-encryption install: a plaintext db already on disk,
    # with no encryption.key next to it yet.
    db_path = tmp_path / "memory_core.sqlite3"
    legacy_store = LocalGraphStore(db_path)
    legacy_store.add_entities([Entity(name="张三", type="person")])
    legacy_store._conn.close()

    migrated = _select_store_from_env()

    assert migrated.all_entities()[0].name == "张三"
    assert (tmp_path / "memory_core.sqlite3.pre-encryption-backup").exists()

    import sqlite3

    conn = sqlite3.connect(db_path)
    raw = conn.execute("SELECT data FROM entities").fetchone()[0]
    conn.close()
    assert "张三" not in raw


def test_database_url_set_attempts_postgres_backend(monkeypatch):
    pytest.importorskip("psycopg")
    from memory_core.mcp_server.server import _select_store_from_env

    # An unreachable DSN: proves the DATABASE_URL branch is actually taken
    # (it tries to connect to Postgres) rather than silently using SQLite.
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody:nothing@127.0.0.1:1/doesnotexist")

    with pytest.raises(Exception):  # noqa: B017 - psycopg.OperationalError, connection refused
        _select_store_from_env()
