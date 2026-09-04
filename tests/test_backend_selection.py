import tempfile

import pytest

pytest.importorskip("mcp")


def test_defaults_to_local_store_without_database_url(monkeypatch):
    from memory_core.graph.local_store import LocalGraphStore
    from memory_core.mcp_server.server import _select_store_from_env

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(tempfile.mkdtemp())

    store = _select_store_from_env()
    assert isinstance(store, LocalGraphStore)


def test_database_url_set_attempts_postgres_backend(monkeypatch):
    pytest.importorskip("psycopg")
    from memory_core.mcp_server.server import _select_store_from_env

    # An unreachable DSN: proves the DATABASE_URL branch is actually taken
    # (it tries to connect to Postgres) rather than silently using SQLite.
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody:nothing@127.0.0.1:1/doesnotexist")

    with pytest.raises(Exception):  # noqa: B017 - psycopg.OperationalError, connection refused
        _select_store_from_env()
