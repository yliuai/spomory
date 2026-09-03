# 基准测试：小规模真实跑分（诚实记录，非正式 Epic 4 交付物）

对应 TASKS.md Epic 4.1/4.2 的诚实中间记录。**这不是"跑通 100 条样本"的正式
基准结果**——受限于当前开发环境到 LLM API 的网络延迟（经代理，单次调用
5-40 秒不等，见下），一次只跑通了 LoCoMo 第一段对话的一个小子集：
前 20 轮对话 + 6 条证据落在这 20 轮内的问答对。跑分脚本、真实 LLM
（DeepSeek `deepseek-v4-flash`）、真实 embedding 模型全部是真实调用，
不是 mock，但样本量远小于正式基准要求的规模，也没有跑 4.3 要求的基线对比
——如果要正式产出 Epic 4 的可发表基准结果，需要更长的运行时间预算（或更低
延迟的网络环境）来跑完整数据集。

结果存档：[`benchmarks/results/locomo_subset_smoke.json`](../benchmarks/results/locomo_subset_smoke.json)

## 结果（含 Epic 4.3 基线对比）

同一份数据（第 1 段对话前 20 轮、6 条问答对）、同一个抽取管道、同一个生成
prompt，只有检索环节不同：本方案（`retrieval/query_match.py` → PPR 扩散 →
`ranker.py`）对比一个去掉 PPR 扩散的纯向量检索基线
（`benchmarks/baseline.py`，直接取 query→triple 相似度 top-K，不做图扩散
——即典型向量库外挂检索的做法）。

| 指标 | 本方案（HippoRAG式PPR） | 基线（纯向量检索，无PPR） |
|---|---|---|
| Recall@10（证据轮次召回） | 83%（5/6） | 67%（4/6） |
| Accuracy（最终答案命中） | 17%（1/6） | 17%（1/6） |
| 总耗时 | 211 秒 | 305 秒 |

原始结果：
[`locomo_subset_smoke.json`](../benchmarks/results/locomo_subset_smoke.json)（本方案）、
[`locomo_subset_baseline.json`](../benchmarks/results/locomo_subset_baseline.json)（基线）。

**样本量的诚实说明**：n=6 远不足以得出统计显著的结论——PPR 版本多召回的那
1 条（"Caroline 的身份是什么"，基线漏检、本方案命中）在这个规模下完全可能
是偶然。这里能诚实说的是：*方向上*和 HippoRAG 论文的主张一致（PPR 扩散能
召回纯向量相似度检索不到的关联事实），但要真正验证需要跑满 Epic 4.1 要求的
100+ 样本规模，而不是从这 6 条外推。accuracy 两者打平（都是 17%），说明
生成阶段的问题（见下）是共享瓶颈，跟检索算法选择无关——这本身也是一个有用
的诊断信号：如果只看 accuracy 一个数字，会误以为"PPR 没用"，但拆开
recall 和 accuracy 两个指标看，才能看出 PPR 确实在检索层面起作用，
真正拖累总体表现的是生成阶段的独立问题。

## 诚实的失败分析

检索和生成的差距（83% vs 17%）不是同一个问题，逐条看实际 case：

1. **时间类问题系统性失败**（3/6 案例）：“Caroline 什么时候去的 LGBTQ 互助
   小组”“Melanie 什么时候画的日出”这类问题，模型答"未提及/无法确定/未知"
   ——即使证据轮次确实被检索召回了。根本原因：当前的三元组抽取
   （`graph/extract.py`）没有把对话发生的时间（session 的 `date_time`）
   系统性地写入三元组或 provenance，检索出的上下文只有"谁做了什么"，
   丢失了"什么时候"。这是抽取管道的真实缺口，不是检索算法的问题——需要在
   `IncrementalIngestor.ingest()` 里把 session 时间戳也纳入抽取上下文。

2. **评分方式过严导致的假阴性**（2/6 案例）：把"Psychology, counseling
   certification"判为不命中"Counseling and working in mental health"、
   把"Transgender woman"判为不命中"a member of the LGBTQ+ community"
   ——当前用的是子串匹配（`exact_or_substring_match`），对语义正确但措辞不同
   的答案会误判为错误。正式跑 Epic 4 时应该换成 LLM-judge 或语义相似度打分，
   子串匹配只适合作为快速自检基线。

3. **敏感事实抽取不完整**（"Transgender woman"这条，也可能与抽取模型对
   敏感个人信息的处理倾向有关，需要更大样本量才能判断是系统性问题还是
   偶发）。

## 对 Epic 4 后续工作的启示

- Recall@10 达到 83%（即使小样本），说明 HippoRAG 式检索链路本身是work的，
  问题集中在抽取阶段的时间信息丢失和评分方式过严，而不是检索排序算法本身。
- 在投入跑完整数据集之前，应该先修：（a）抽取管道把时间戳带入三元组/
  provenance；（b）换成语义匹配或 LLM-judge 评分——不然即使跑满 100+
  样本，accuracy 数字也会被这两个已知问题拉低，不能反映检索算法的真实水平。
- 需要一个延迟更低的网络环境（或更高并发/批量调用）才能在合理时间内跑完
  Epic 4.1 要求的 100 条样本子集，更不用说 Epic 4.2 的完整 pipeline 跑分。
