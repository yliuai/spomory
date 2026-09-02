# 记忆导出格式（"记忆护照"）

对应 TASKS.md Epic 7.1/7.2。这是创业方案「三、记忆归属权/可迁移」章节"记忆护照"
承诺在工程层面的落地：用户可以随时导出完整的个人知识图谱，格式自洽、不丢失信息、
不需要依赖本产品本身的代码就能被独立脚本解析。

## 设计参考

参考 MIF（Memory Interchange Format）、PAM（Portable AI Memory）两个早期草案的
设计思路，但不完全照搬（两者都还只是 v0.1 级个人项目草案，未被任何主流厂商采纳）：

- **语义/情景/程序记忆分类**：每条实体/关系都带 `memory_type` 字段
  （`semantic` / `episodic` / `procedural`）。当前实现里新抽取的记忆默认归类为
  `semantic`（陈述性事实），情景记忆（"某次对话发生了什么"）和程序记忆（"用户的操作
  习惯"）的自动分类留给 Epic 3 的记忆管理器接入后再细化。
- **来源溯源**：参照 W3C PROV-O 的思路（不照搬完整规范），每条 `provenance`
  记录 `source_id`（来源文档/对话 id）、`source_span`（原文片段）、`extractor`
  （抽取管道名称+版本）。
- **JSON-LD 结构化数据**：顶层用 `@context`/`@type` 声明词汇表和文档类型，
  使导出文件在没有本项目代码的情况下也能被通用 JSON-LD 工具理解。

## Schema

`memory_core/export/schema.py` 定义了 `MemoryExport`：

```
{
  "@context": {...},                 # JSON-LD 词汇表
  "@type": "memory:MemoryPassport",
  "exported_at": "<ISO8601 UTC>",
  "subject_id": "<用户id>",
  "entities": [
    {
      "id": "...", "name": "...", "type": "...", "memory_type": "semantic",
      "attributes": {...}, "aliases": [...],
      "provenance": [{"source_id": "...", "source_span": "...", "extractor": "..."}],
      "created_at": "...", "updated_at": "..."
    }
  ],
  "relations": [
    {
      "id": "...", "subject_id": "...", "predicate": "...", "object_id": "...",
      "confidence": 0.95, "memory_type": "semantic",
      "provenance": [...], "created_at": "...", "updated_at": "..."
    }
  ]
}
```

完整示例见 [`examples/memory_passport_sample.json`](examples/memory_passport_sample.json)。

## 自洽性验证

`tests/test_export.py::test_export_round_trips_without_information_loss` 验证：
每条 `relation` 的 `subject_id`/`object_id` 都能在 `entities` 列表里找到对应
记录——独立脚本仅凭导出文件本身就能重建出完整图结构，不需要访问原始数据库。

## 真删除

`memory_core/export/exporter.py` 的 `delete_all()` 对应 Epic 7.3
"删除权=真删除"承诺：物理删除底层存储（SQLite）里的记录，返回一个
`DeletionReceipt`（删除前后的实体/关系计数对比）。
`tests/test_export.py::test_delete_all_is_physically_verifiable_at_the_storage_layer`
直接查询 SQLite 文件本身（不经过应用层）确认数据确实被物理清除，而不只是在
应用层查不到——这是对通义千问"删除即彻底丢失、无迁移路径"负面案例的正面回应：
删除权同样必须是可验证的真删除，不能是标记删除。
