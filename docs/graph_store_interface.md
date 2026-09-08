# GraphStoreBase 接口设计说明

对应 TASKS.md Epic 1.2。这份说明先于任何具体实现存在，目的是让接口在
Phase 0 就冻结，Phase 2 向社区开放存储适配层时不需要推倒重来
（参见创业方案「九、插件生态与开放策略」——存储/后端适配层是唯一计划开放给
第三方实现的架构层，检索算法和记忆管理策略不开放）。

## 接口方法

| 方法 | 用途 |
|---|---|
| `add_entities(entities)` | 批量插入/更新实体（按 id upsert） |
| `add_relations(relations)` | 批量插入/更新关系（按 id upsert） |
| `get_entity(entity_id)` | 按 id 查询单个实体 |
| `find_entities_by_name(name)` | 按名称/别名精确查找，供 Epic 1.5 增量合并时做实体消歧 |
| `get_neighbors(entity_id)` | 查询某实体作为 subject 或 object 的全部关系 |
| `query_subgraph(entity_ids, hops)` | 查询以给定实体为中心、N 跳内的induced子图，供 Epic 2 检索使用 |
| `delete_entity(entity_id)` | 物理删除实体及相关关系，对应 Epic 7.3 的"真删除"承诺 |
| `all_entities()` / `all_relations()` | 全量导出用，供 Epic 7 导出接口和基准测试使用 |
| `archive_relation_version(old_relation, superseded_at)` | Epic 11.7：把一条关系被 UPDATE 覆盖前的内容存进事务时间历史，供 `relation_as_of` 查询 |
| `relation_as_of(relation_id, as_of)` | Epic 11.7：查询某条关系在历史某个事务时间点上的值——系统当时相信的事实，不是现在的事实 |

## 设计原则

1. **只声明检索/写入需要的最小操作集**，不把任何具体后端（networkx、
   Postgres+pgvector、图数据库）的实现细节泄漏到接口里。
2. **写操作是幂等的**（按 id upsert），因为 Epic 1.5 的增量合并逻辑会反复
   对同一实体做更新，接口不应该强迫调用方先查询再决定插入还是更新。
3. **`delete_entity` 必须是物理删除**，不是软删除标记——这是 Epic 7.3
   "真删除"承诺在存储层的落地点，任何新后端实现都必须遵守这一点。
4. **子图查询用跳数而非固定深度**，为 Epic 2 的个性化 PageRank 检索保留
   足够的召回范围控制空间。
5. **`add_relations` 的按 id upsert 语义不隐式产生历史**——Epic 11.7 的
   事务时间归档是调用方（`memory_manager/actions.py` 的 UPDATE 分支）
   显式决定"这是一次事实纠正"之后，另外调用 `archive_relation_version`
   才发生的，不是 `add_relations` 自动做的。这样设计是因为 `add_relations`
   也被数据迁移之类的场景用来重写内容没变的行（比如 Epic 11.2 的加密
   迁移脚本），如果归档逻辑挂在 `add_relations` 里，这类重写会被误判成
   "事实变化"，伪造出根本没发生过的历史记录。

## 已知实现

- `LocalGraphStore`（`graph/local_store.py`）：基于 `networkx` 内存图 +
  SQLite 持久化，Phase 0/Phase 1 本地默认后端。`relation_history` 表
  （Epic 11.7）复用和主表一样的 Fernet 加密。
- `PostgresGraphStore`（`graph/postgres_store.py`，Epic 8.2）：接口不变，
  已在真实 PostgreSQL 10 实例上跑通全部契约测试
  （`tests/graph_store_contract.py`）和 MCP Server 功能对等性验证
  （`tests/test_postgres_mcp_parity.py`），详见 `docs/postgres_setup.md`。
  `relation_history` 表（Epic 11.7）按 `user_id` 隔离，和其他表的多租户
  规则一致。

## 事务时间 vs 现实时间（Epic 11.7）

`relation_as_of(relation_id, as_of)` 回答的是**事务时间**问题——"系统在
某个时间点相信什么是真的"，靠 `Relation.valid_from`（这条关系当前值
成为系统信念的起点，每次 UPDATE 都会前移）和 `relation_history` 表
（存归档的旧值 + 它当时生效的时间区间）重建。

这**不是**完整的双时态（bitemporal）模型——真正的双时态还需要**现实
时间**（valid time）：事实在现实世界里从什么时候开始为真，可能早于
系统知道这件事的时间（比如"三月份换了工作"，但系统是九月才被告知）。
现实时间需要从原文里抽取时间信息才能支持，目前的抽取管道
（`graph/incremental.py`）不做这件事——`docs/methodology.md` 第 4 节
"抽取管道对时间信息的处理是一个已发现的真实缺口"说的就是这个问题，
Epic 11.7 只解决了事务时间这一半，这个缺口本身还在。
