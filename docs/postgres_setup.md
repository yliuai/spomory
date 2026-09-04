# Postgres 到手后：跑通 Epic 8.2 验证的操作手册

`graph/postgres_store.py` 已经实现了和 `LocalGraphStore` 完全一致的
`GraphStoreBase` 接口，`tests/graph_store_contract.py` 定义的 8 项行为契约
测试目前只在 `LocalGraphStore` 上跑通过；`tests/test_postgres_store.py`
跑的是同一套契约测试，只是一直被跳过，因为没有真实 Postgres 可连。

## 需要你提供的

一个可写的 Postgres 连接串（`DATABASE_URL`），本地 Docker 起的、或
Supabase/Neon/Railway 之类的免费云数据库都可以——只要能建表、能读写。
不需要预先建任何表，`PostgresGraphStore.__init__` 会自动执行建表 DDL。

## 拿到连接串之后我会做的

```bash
uv pip install -e ".[cloud]"   # 装 psycopg
DATABASE_URL="postgresql://user:pass@host:port/dbname" \
    .venv/bin/python -m pytest tests/test_postgres_store.py -v
```

跑通后会在 TASKS.md 里把 Epic 8.2 勾上，并把 `docs/graph_store_interface.md`
更新为"已验证"状态（目前写的是"实现完成、未跑通真实数据库"）。

## 后续（Epic 8.2 完整验收还需要）

TASKS.md 8.2 的验收标准是"本地 MCP Server 配置切换到云端后端后，功能行为
与本地后端一致（跑一遍 Epic 6.2 的验证用例）"——这一步还需要一个真实的
Claude Desktop/Cursor 桌面环境（见 Epic 6.2 的说明），是另一个独立的
资源缺口，不是 Postgres 本身能解决的。
