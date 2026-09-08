# Epic 8.2: cloud Postgres backend -- deployed and verified

`graph/postgres_store.py` has already passed all 8 behavioral contract
tests defined in `tests/graph_store_contract.py` against a real
PostgreSQL 10 instance (the exact same suite `LocalGraphStore` runs),
plus MCP Server functional-parity verification
(`tests/test_postgres_mcp_parity.py`: swap `build_server()`'s backend for
`PostgresGraphStore`, run the full `add_memory` → `search_memory`
pipeline, and confirm the behavior matches the local backend).

## Deployment location

Reuses the same server Epic 3.4's GPU training used (`10.2.29.91`,
CentOS 8):

- PostgreSQL 10 (`dnf install postgresql-server`), with the service
  `systemctl enable`d to run persistently.
- Database `memory_core`, user `memory_core`, listening only on
  `127.0.0.1` (not exposed to the outside network -- configured for
  minimal exposure; accessing it from outside this machine would require
  separately changing `postgresql.conf`'s `listen_addresses` and
  `pg_hba.conf`, and using a firewall/SSH tunnel rather than exposing the
  port directly to the public internet).
- Connection string:
  `postgresql://memory_core:mc_local_dev_pw_7f3a9@127.0.0.1:5432/memory_core`
  (a test password -- should be swapped for a stronger one and put into
  secrets management before real use, not hardcoded).

## How to run the tests

```bash
ssh root@10.2.29.91
cd /mnt/coding/memory-core
DATABASE_URL="postgresql://memory_core:mc_local_dev_pw_7f3a9@127.0.0.1:5432/memory_core" \
    .venv/bin/python -m pytest tests/test_postgres_store.py tests/test_postgres_mcp_parity.py -v
```

## A real bug found and fixed

The first time the tests ran, all 8 contract tests failed at the read
stage: `psycopg` v3 auto-deserializes `jsonb` columns into a Python
`dict`, but `postgres_store.py`'s original code was still calling
`json.loads()` on the value it read back (copied from how
`LocalGraphStore` handles SQLite `TEXT` columns) -- calling `json.loads`
on an object that's already a `dict` raises a `TypeError` directly. This
is a problem that only surfaces once you connect to a real Postgres; the
SQLite version's identical-looking code was actually correct there,
because it stores a plain text column. After the fix, 8/8 passed.

## Not yet done

Epic 8.2's acceptance criteria also mention "connect a real Claude
Desktop/Cursor desktop client" -- that part is covered by Epic 6.2 and
the connection steps written in `docs/mcp_quickstart.md`; it requires you
to run a real desktop session locally, which isn't something this server
can verify.
