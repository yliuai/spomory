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

## 设计原则

1. **只声明检索/写入需要的最小操作集**，不把任何具体后端（networkx、
   Postgres+pgvector、图数据库）的实现细节泄漏到接口里。
2. **写操作是幂等的**（按 id upsert），因为 Epic 1.5 的增量合并逻辑会反复
   对同一实体做更新，接口不应该强迫调用方先查询再决定插入还是更新。
3. **`delete_entity` 必须是物理删除**，不是软删除标记——这是 Epic 7.3
   "真删除"承诺在存储层的落地点，任何新后端实现都必须遵守这一点。
4. **子图查询用跳数而非固定深度**，为 Epic 2 的个性化 PageRank 检索保留
   足够的召回范围控制空间。

## 已知实现

- `LocalGraphStore`（`graph/local_store.py`）：基于 `networkx` 内存图 +
  SQLite 持久化，Phase 0/Phase 1 本地默认后端。
- 云端后端（Postgres + pgvector 或托管图数据库）计划在 Epic 8.2 补充，
  接口不变。
