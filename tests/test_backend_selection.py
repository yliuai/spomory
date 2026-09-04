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


def test_database_url_set_attempts_postgres_backend(monkeypatch):
    pytest.importorskip("psycopg")
    from memory_core.mcp_server.server import _select_store_from_env

    # An unreachable DSN: proves the DATABASE_URL branch is actually taken
    # (it tries to connect to Postgres) rather than silently using SQLite.
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody:nothing@127.0.0.1:1/doesnotexist")

    with pytest.raises(Exception):  # noqa: B017 - psycopg.OperationalError, connection refused
        _select_store_from_env()
