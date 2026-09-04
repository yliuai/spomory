# Epic 8.2：云端 Postgres 后端——已部署并验证

`graph/postgres_store.py` 已经在真实 PostgreSQL 10 实例上跑通了
`tests/graph_store_contract.py` 定义的全部 8 项行为契约测试（和
`LocalGraphStore` 跑的是同一套测试），以及 MCP Server 的功能对等性验证
（`tests/test_postgres_mcp_parity.py`：把 `build_server()` 的后端换成
`PostgresGraphStore`，跑 `add_memory` → `search_memory` 全流程，行为和本地
后端一致）。

## 部署位置

复用了 Epic 3.4 GPU 训练用的同一台服务器（`10.2.29.91`，CentOS 8）：

- PostgreSQL 10（`dnf install postgresql-server`），服务已 `systemctl enable`
  常驻运行。
- 数据库 `memory_core`，用户 `memory_core`，仅监听 `127.0.0.1`（未对外网开放，
  按最小暴露面配置——如果要从这台机器以外访问，需要另外改
  `postgresql.conf` 的 `listen_addresses` 和 `pg_hba.conf`，并考虑防火墙/
  SSH 隧道而不是直接暴露公网端口）。
- 连接串：`postgresql://memory_core:mc_local_dev_pw_7f3a9@127.0.0.1:5432/memory_core`
  （测试用密码，正式启用前应该换成更强的密码并放进密钥管理，不要硬编码）。

## 跑测试的方式

```bash
ssh root@10.2.29.91
cd /mnt/coding/memory-core
DATABASE_URL="postgresql://memory_core:mc_local_dev_pw_7f3a9@127.0.0.1:5432/memory_core" \
    .venv/bin/python -m pytest tests/test_postgres_store.py tests/test_postgres_mcp_parity.py -v
```

## 发现并修复的真实 bug

第一次跑测试时全部 8 个契约测试都失败在读取阶段：`psycopg` v3 会把
`jsonb` 列自动反序列化成 Python `dict`，而 `postgres_store.py` 原来的代码
还在对读出来的值调用 `json.loads()`（照抄了 `LocalGraphStore` 处理 SQLite
`TEXT` 列的写法）——对一个已经是 `dict` 的对象调用 `json.loads` 直接抛
`TypeError`。这是只有连上真实 Postgres 才会暴露的问题，SQLite 版本因为
存的是纯文本列，同样的代码反而是对的。修掉之后 8/8 通过。

## 还没做的

Epic 8.2 的验收标准还提到"接入实际的 Claude Desktop/Cursor 桌面客户端"——
这部分见 Epic 6.2，和 `docs/mcp_quickstart.md` 里写的连接步骤，需要你在
本地跑一次真实的桌面会话，不是这台服务器能验证的。
